"""Action execution with mandatory verification.

    [recovery?] verify-first  ->  already done?  -> SUCCESS (no re-execution)
    snapshot before
    execute (primitive write)
    snapshot after / verify    ->  observed?      -> SUCCESS
                                  not observed   -> UNVERIFIED (never SUCCESS)

Error mapping
- UI not recognised / ambiguous before acting      -> UNSAFE   (NEEDS_ATTENTION)
- transient failure *before* anything was submitted -> RETRY
- any failure *after* submission                    -> UNVERIFIED
"""

import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta

from cmc_shared.enums import (
    ActionOutcome,
    ActionType,
    ConnectionStatus,
    ErrorCode,
    MessageDirection,
    OrderStatus,
)
from cmc_shared.models import (
    NormalizedConversation,
    NormalizedConversationSummary,
    NormalizedMessage,
    NormalizedOrderSummary,
)
from cmc_shared.protocol import ActionResultRequest, ClaimedAction

from agent.adapter import CardmarketAdapter, SessionState
from agent.errors import AccessBlockedError, AgentError, AuthRequiredError, UnsafeUIError, classify

log = logging.getLogger("cmc.agent.actions")

SessionReporter = Callable[[SessionState], Awaitable[None]]

# Clock skew / minute-precision tolerance when matching our own message.
_MATCH_TOLERANCE = timedelta(minutes=10)


def _normalize(text: str) -> str:
    return " ".join(text.split())


def _result(
    outcome: ActionOutcome,
    *,
    code: ErrorCode | None = None,
    message: str | None = None,
    artifacts: list[str] | None = None,
    **result: object,
) -> ActionResultRequest:
    return ActionResultRequest(
        outcome=outcome,
        error_code=code,
        error_message=message,
        result=dict(result),
        artifacts=artifacts or [],
    )


def _find_outbound(
    convo: NormalizedConversation,
    body: str,
    *,
    exclude_keys: set[str] | None = None,
    not_before: datetime | None = None,
) -> NormalizedMessage | None:
    target = _normalize(body)
    for msg in reversed(convo.messages):
        if msg.direction != MessageDirection.OUTBOUND or _normalize(msg.body) != target:
            continue
        key = _key(msg)
        if exclude_keys is not None and key in exclude_keys:
            continue
        if not_before and msg.sent_at and msg.sent_at < not_before - _MATCH_TOLERANCE:
            continue
        return msg
    return None


def _key(msg: NormalizedMessage) -> str:
    return msg.cardmarket_id or f"{msg.sent_at}|{_normalize(msg.body)}"


class ActionExecutor:
    def __init__(
        self, adapter: CardmarketAdapter, report_session: SessionReporter, pairing_timeout: int
    ) -> None:
        self.adapter = adapter
        self.report_session = report_session
        self.pairing_timeout = pairing_timeout

    async def execute(self, action: ClaimedAction) -> ActionResultRequest:
        handlers = {
            ActionType.SEND_MESSAGE: self._send_message,
            ActionType.MARK_ORDER_SHIPPED: self._mark_shipped,
            ActionType.PAIR_SESSION: self._pair,
            ActionType.VERIFY_SESSION: self._verify_session,
        }
        handler = handlers.get(action.type)
        if handler is None:
            return _result(
                ActionOutcome.FAILED,
                code=ErrorCode.ACTION_FAILED,
                message=f"unsupported action {action.type}",
            )
        try:
            return await handler(action)
        except AccessBlockedError as exc:
            # Nothing was submitted (the block happened on page load). The action
            # stays queued; write actions are not claimed until the session is back.
            await self.report_session(SessionState(ConnectionStatus.ERROR, exc.message, exc.code))
            return _result(
                ActionOutcome.RETRY, code=exc.code, message=exc.message, artifacts=exc.artifacts
            )
        except AuthRequiredError as exc:
            await self.report_session(
                SessionState(ConnectionStatus.SESSION_EXPIRED, exc.message, exc.code)
            )
            return _result(
                ActionOutcome.RETRY, code=exc.code, message=exc.message, artifacts=exc.artifacts
            )
        except UnsafeUIError as exc:
            artifacts = exc.artifacts or await self.adapter.capture_failure(
                f"action-{action.id}-unsafe"
            )
            return _result(
                ActionOutcome.UNSAFE, code=exc.code, message=exc.message, artifacts=artifacts
            )
        except Exception as exc:  # pre-submission failures only (see handlers)
            code, retryable = classify(exc)
            artifacts = exc.artifacts if isinstance(exc, AgentError) else []
            artifacts = artifacts or await self.adapter.capture_failure(f"action-{action.id}")
            log.warning(
                "action failed before submission",
                extra={"action_id": action.id, "error_code": str(code)},
            )
            outcome = ActionOutcome.RETRY if retryable else ActionOutcome.FAILED
            if code == ErrorCode.CARDMARKET_CHANGED:
                outcome = ActionOutcome.UNSAFE
            return _result(outcome, code=code, message=str(exc)[:500], artifacts=artifacts)

    # ------------------------------------------------------------ SEND_MESSAGE

    async def _send_message(self, action: ClaimedAction) -> ActionResultRequest:
        p = action.payload
        body = str(p["body"])
        summary = NormalizedConversationSummary(
            cardmarket_id=str(p["conversation_cardmarket_id"]),
            buyer_name=str(p.get("buyer_name") or ""),
            source_url=p.get("source_url"),
        )
        requested_at = datetime.fromisoformat(p["requested_at"]) if p.get("requested_at") else None

        before = await self.adapter.get_conversation(summary)
        if (
            before.buyer_name
            and summary.buyer_name
            and _normalize(before.buyer_name) != _normalize(summary.buyer_name)
        ):
            raise UnsafeUIError(
                f"conversation {summary.cardmarket_id} belongs to '{before.buyer_name}', "
                f"expected '{summary.buyer_name}'"
            )
        if action.recovery:
            existing = _find_outbound(before, body, not_before=requested_at)
            if existing is not None:
                log.info(
                    "message already on cardmarket; not resending", extra={"action_id": action.id}
                )
                return _result(
                    ActionOutcome.SUCCESS,
                    cardmarket_message_id=existing.cardmarket_id,
                    recovered=True,
                )
            if requested_at is None:
                return _result(
                    ActionOutcome.UNVERIFIED,
                    code=ErrorCode.VERIFICATION_FAILED,
                    message="cannot rule out a previous send; manual check required",
                )
        known = {_key(m) for m in before.messages}

        receipt = await self.adapter.submit_message(
            summary, body
        )  # may raise pre-submission errors
        if not receipt.submitted:
            return _result(
                ActionOutcome.RETRY,
                code=ErrorCode.ACTION_FAILED,
                message="message was not submitted",
            )

        try:
            after = await self.adapter.get_conversation(summary)
        except Exception as exc:
            code, _ = classify(exc)
            return _result(
                ActionOutcome.UNVERIFIED,
                code=ErrorCode.VERIFICATION_FAILED,
                message=f"verification read failed: {code}: {exc}"[:500],
            )
        sent = _find_outbound(after, body, exclude_keys=known)
        if sent is None:
            artifacts = await self.adapter.capture_failure(f"action-{action.id}-unverified")
            return _result(
                ActionOutcome.UNVERIFIED,
                code=ErrorCode.VERIFICATION_FAILED,
                message="message not found in the conversation after sending",
                artifacts=artifacts,
            )
        return _result(
            ActionOutcome.SUCCESS,
            cardmarket_message_id=sent.cardmarket_id or receipt.cardmarket_message_id,
        )

    # ------------------------------------------------------ MARK_ORDER_SHIPPED

    async def _mark_shipped(self, action: ClaimedAction) -> ActionResultRequest:
        p = action.payload
        summary = NormalizedOrderSummary(
            cardmarket_id=str(p["order_cardmarket_id"]),
            buyer_name=str(p.get("buyer_name") or ""),
            status=OrderStatus.PAID,
            source_url=p.get("source_url"),
        )
        tracking = p.get("tracking_number")
        before = await self.adapter.get_order(summary)
        if before.status in (OrderStatus.SHIPPED, OrderStatus.COMPLETED):
            return _result(ActionOutcome.SUCCESS, already_shipped=True)
        if before.status != OrderStatus.PAID:
            return _result(
                ActionOutcome.FAILED,
                code=ErrorCode.ACTION_FAILED,
                message=f"order is {before.status} on Cardmarket, not PAID",
            )
        if summary.buyer_name and _normalize(before.buyer_name) != _normalize(summary.buyer_name):
            raise UnsafeUIError(
                f"order {summary.cardmarket_id} buyer mismatch ('{before.buyer_name}')"
            )

        await self.adapter.submit_mark_shipped(summary, tracking)

        try:
            after = await self.adapter.get_order(summary)
        except Exception as exc:
            return _result(
                ActionOutcome.UNVERIFIED,
                code=ErrorCode.VERIFICATION_FAILED,
                message=f"verification read failed: {exc}"[:500],
            )
        if after.status in (OrderStatus.SHIPPED, OrderStatus.COMPLETED):
            return _result(ActionOutcome.SUCCESS, status=str(after.status))
        artifacts = await self.adapter.capture_failure(f"action-{action.id}-unverified")
        return _result(
            ActionOutcome.UNVERIFIED,
            code=ErrorCode.VERIFICATION_FAILED,
            message=f"order still {after.status} after submit",
            artifacts=artifacts,
        )

    # --------------------------------------------------------------- sessions

    async def _pair(self, action: ClaimedAction) -> ActionResultRequest:
        await self.report_session(SessionState(ConnectionStatus.CONNECTING, "pairing in progress"))
        state = await self.adapter.pair(self.pairing_timeout)
        await self.report_session(state)
        if state.connected:
            return _result(ActionOutcome.SUCCESS, status=str(state.status))
        return _result(
            ActionOutcome.FAILED,
            code=state.error_code or ErrorCode.AUTH_ERROR,
            message=state.message or "pairing not completed",
        )

    async def _verify_session(self, action: ClaimedAction) -> ActionResultRequest:
        state = await self.adapter.check_session()
        await self.report_session(state)
        if state.connected:
            return _result(ActionOutcome.SUCCESS, status=str(state.status))
        return _result(
            ActionOutcome.FAILED,
            code=state.error_code or ErrorCode.AUTH_ERROR,
            message=state.message or f"session is {state.status}",
        )
