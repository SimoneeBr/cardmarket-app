"""Persistent action queue for Cardmarket write/read operations.

Guarantees
- **Persistence**: actions live in PostgreSQL; nothing is lost on restarts.
- **Serialization per account**: at most one PROCESSING action per connection.
- **Idempotency**: a unique idempotency key per logical operation.
- **Crash safety**: an expired lease on a write action flags it
  ``needs_verification`` so the agent checks Cardmarket before re-executing.
- **Honest outcomes**: SUCCESS only when the agent verified the result;
  an unverifiable outcome becomes NEEDS_ATTENTION (message status UNKNOWN).
"""

import logging
import random
from datetime import timedelta
from typing import Any

from cmc_shared.enums import (
    WRITE_ACTIONS,
    ActionOutcome,
    ActionStatus,
    ActionType,
    ConnectionStatus,
    DomainEventType,
    EntityType,
    ErrorCode,
    MessageStatus,
    OrderStatus,
    ShippingStatus,
)
from cmc_shared.protocol import ActionResultRequest, ClaimedAction
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import utcnow
from app.models import Action, CardmarketConnection, Message, Order, User
from app.services import events
from app.services.audit import AuditAction, AuditResult, record

log = logging.getLogger("cmc.actions")

# Actions that may run while the Cardmarket session is not CONNECTED.
SESSION_ACTIONS = frozenset({ActionType.PAIR_SESSION, ActionType.VERIFY_SESSION})


class ActionStateError(Exception):
    pass


def backoff_delay(attempts: int) -> timedelta:
    settings = get_settings()
    base = settings.action_backoff_base_seconds * (2 ** max(attempts - 1, 0))
    capped = min(base, settings.action_backoff_max_seconds)
    jitter = random.uniform(0, capped * 0.2)  # noqa: S311 - not security sensitive
    return timedelta(seconds=capped + jitter)


def enqueue(
    db: Session,
    conn: CardmarketConnection,
    type_: ActionType,
    payload: dict[str, Any],
    *,
    idempotency_key: str,
    user: User | None = None,
    correlation_id: str | None = None,
) -> tuple[Action, bool]:
    """Insert an action, or return the existing one with the same key."""
    existing = db.scalar(select(Action).where(Action.idempotency_key == idempotency_key))
    if existing is not None:
        return existing, False
    action = Action(
        connection_id=conn.id,
        type=type_,
        payload=payload,
        status=ActionStatus.PENDING,
        attempts=0,
        max_attempts=get_settings().action_max_attempts,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        requested_by_user_id=user.id if user else None,
        result={},
        needs_verification=False,
    )
    db.add(action)
    db.flush()
    log.info("action enqueued", extra={"action_id": action.id, "action_type": str(type_)})
    return action, True


def claim_next(
    db: Session, conn: CardmarketConnection, agent_id: str, lease_seconds: int
) -> ClaimedAction | None:
    """Claim the next runnable action for this account (one at a time)."""
    # Row lock on the connection serializes concurrent claimers for the account.
    db.execute(
        select(CardmarketConnection.id).where(CardmarketConnection.id == conn.id).with_for_update()
    )
    now = utcnow()
    in_flight = db.scalars(
        select(Action).where(
            Action.connection_id == conn.id, Action.status == ActionStatus.PROCESSING
        )
    ).all()
    stale: Action | None = None
    for action in in_flight:
        if action.lease_expires_at and action.lease_expires_at > now:
            return None  # another action is legitimately running
        stale = stale or action
    if stale is not None:
        # The agent died (or lost the lease) mid-action: it may have executed.
        if stale.type in WRITE_ACTIONS:
            stale.needs_verification = True
        if conn.status != ConnectionStatus.CONNECTED and stale.type not in SESSION_ACTIONS:
            # Cannot act without a session: park it until the session is back.
            stale.status = ActionStatus.PENDING
            stale.lease_owner = None
            stale.lease_expires_at = None
            stale = None
    if stale is not None:
        chosen = stale
    else:
        stmt = (
            select(Action)
            .where(
                Action.connection_id == conn.id,
                Action.status == ActionStatus.PENDING,
                (Action.not_before.is_(None)) | (Action.not_before <= now),
            )
            .order_by(Action.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if conn.status != ConnectionStatus.CONNECTED:
            stmt = stmt.where(Action.type.in_(SESSION_ACTIONS))
        found = db.scalar(stmt)
        if found is None:
            return None
        chosen = found

    chosen.status = ActionStatus.PROCESSING
    chosen.attempts += 1
    chosen.started_at = now
    chosen.lease_owner = agent_id
    chosen.lease_expires_at = now + timedelta(seconds=lease_seconds)
    db.flush()
    return ClaimedAction(
        id=chosen.id,
        type=chosen.type,
        payload=chosen.payload,
        attempts=chosen.attempts,
        idempotency_key=chosen.idempotency_key,
        correlation_id=chosen.correlation_id,
        recovery=chosen.needs_verification,
    )


def _finish(action: Action, status: ActionStatus, report: ActionResultRequest) -> None:
    action.status = status
    action.completed_at = utcnow() if status != ActionStatus.PENDING else None
    action.lease_owner = None
    action.lease_expires_at = None
    action.last_error = report.error_message
    action.last_error_code = report.error_code
    action.result = {**report.result, "outcome": str(report.outcome), "artifacts": report.artifacts}


def report_result(db: Session, action: Action, report: ActionResultRequest) -> Action:
    if action.status != ActionStatus.PROCESSING:
        raise ActionStateError(f"action {action.id} is {action.status}, not PROCESSING")

    outcome = report.outcome
    if outcome == ActionOutcome.SUCCESS:
        _finish(action, ActionStatus.SUCCESS, report)
        action.needs_verification = False
        _on_success(db, action, report)
    elif outcome == ActionOutcome.RETRY and action.attempts < action.max_attempts:
        _finish(action, ActionStatus.PENDING, report)
        action.not_before = utcnow() + backoff_delay(action.attempts)
    elif outcome == ActionOutcome.UNVERIFIED:
        _finish(action, ActionStatus.NEEDS_ATTENTION, report)
        action.needs_verification = True
        _on_unresolved(db, action, report, MessageStatus.UNKNOWN)
    elif outcome == ActionOutcome.UNSAFE:
        _finish(action, ActionStatus.NEEDS_ATTENTION, report)
        _on_unresolved(db, action, report, MessageStatus.FAILED)
    else:  # FAILED, or RETRY with attempts exhausted
        if outcome == ActionOutcome.RETRY:
            report = report.model_copy(
                update={"error_message": f"retries exhausted: {report.error_message}"}
            )
        _finish(action, ActionStatus.FAILED, report)
        _on_unresolved(db, action, report, MessageStatus.FAILED)

    record(
        db,
        AuditAction.ACTION_COMPLETED,
        actor="agent",
        entity_type=EntityType.ACTION,
        entity_id=action.id,
        result=_audit_result(action.status),
        error=report.error_message,
        details={
            "type": str(action.type),
            "outcome": str(outcome),
            "status": str(action.status),
            "attempts": action.attempts,
            "correlation_id": action.correlation_id,
        },
    )
    return action


def _audit_result(status: ActionStatus) -> AuditResult:
    if status == ActionStatus.SUCCESS:
        return AuditResult.SUCCESS
    return AuditResult.PENDING if status == ActionStatus.PENDING else AuditResult.FAILURE


def _message_for(db: Session, action: Action) -> Message | None:
    message_id = action.payload.get("message_id")
    return db.get(Message, message_id) if message_id else None


def _on_success(db: Session, action: Action, report: ActionResultRequest) -> None:
    if action.type == ActionType.SEND_MESSAGE:
        message = _message_for(db, action)
        if message is not None:
            message.status = MessageStatus.SENT
            cm_id = report.result.get("cardmarket_message_id")
            if cm_id and message.cardmarket_id is None:
                message.cardmarket_id = str(cm_id)
            message.sent_at = message.sent_at or utcnow()
            message.conversation.last_message_at = message.sent_at
            message.conversation.last_message_preview = message.body[:280]
            message.conversation.unread = False
            events.emit(
                db,
                DomainEventType.MESSAGE_SENT,
                EntityType.CONVERSATION,
                message.conversation_id,
                {"message_id": message.id, "buyer_name": message.conversation.buyer_name},
            )
    elif action.type == ActionType.MARK_ORDER_SHIPPED:
        order = db.get(Order, action.payload.get("order_id"))
        if order is not None and order.status != OrderStatus.SHIPPED:
            old = order.status
            order.status = OrderStatus.SHIPPED
            order.shipping_status = ShippingStatus.SHIPPED
            order.shipped_at = order.shipped_at or utcnow()
            if action.payload.get("tracking_number"):
                order.tracking_number = action.payload["tracking_number"]
            events.emit(
                db,
                DomainEventType.ORDER_SHIPPED,
                EntityType.ORDER,
                order.id,
                {
                    "cardmarket_id": order.cardmarket_id,
                    "buyer_name": order.buyer_name,
                    "previous_status": str(old),
                    "via": "action_queue",
                },
            )


def _on_unresolved(
    db: Session, action: Action, report: ActionResultRequest, message_status: MessageStatus
) -> None:
    if action.type == ActionType.SEND_MESSAGE:
        message = _message_for(db, action)
        if message is not None:
            message.status = message_status
    if action.type in SESSION_ACTIONS:
        return  # session problems are notified through the connection state
    events.emit(
        db,
        DomainEventType.ACTION_FAILED,
        EntityType.ACTION,
        action.id,
        {
            "action_type": str(action.type),
            "status": str(action.status),
            "error_code": str(report.error_code or ErrorCode.UNKNOWN),
            "reason": report.error_message or str(report.outcome),
            "notify_user_id": action.requested_by_user_id,
        },
    )


def retry(db: Session, action: Action) -> Action:
    if action.status not in (ActionStatus.FAILED, ActionStatus.NEEDS_ATTENTION):
        raise ActionStateError("only FAILED or NEEDS_ATTENTION actions can be retried")
    action.status = ActionStatus.PENDING
    action.not_before = None
    action.attempts = 0
    action.completed_at = None
    if action.type == ActionType.SEND_MESSAGE:
        message = _message_for(db, action)
        if message is not None:
            message.status = MessageStatus.PENDING
    return action


def cancel(db: Session, action: Action) -> Action:
    if action.status not in (
        ActionStatus.PENDING,
        ActionStatus.NEEDS_ATTENTION,
        ActionStatus.FAILED,
    ):
        raise ActionStateError("action cannot be cancelled in its current state")
    action.status = ActionStatus.FAILED
    action.completed_at = utcnow()
    action.last_error = "cancelled by operator"
    if action.type == ActionType.SEND_MESSAGE:
        message = _message_for(db, action)
        if message is not None and message.status != MessageStatus.SENT:
            message.status = MessageStatus.FAILED
    return action


def resolve_as_done(db: Session, action: Action) -> Action:
    """Operator checked Cardmarket manually and confirms the action happened."""
    if action.status != ActionStatus.NEEDS_ATTENTION:
        raise ActionStateError("only NEEDS_ATTENTION actions can be resolved manually")
    report = ActionResultRequest(outcome=ActionOutcome.SUCCESS, result={"resolved_manually": True})
    action.status = ActionStatus.SUCCESS
    action.completed_at = utcnow()
    action.needs_verification = False
    action.result = {**action.result, "resolved_manually": True}
    _on_success(db, action, report)
    return action
