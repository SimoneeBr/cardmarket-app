"""One incremental sync cycle.

1. verify session            4. conversations (thread only if changed)
2. acquire lease (API)        5. carts (detail only if changed)
3. orders (detail only if     6. complete the run (SUCCESS / PARTIAL / FAILED)
   the list fingerprint changed)

Records whose detail could not be fetched in this cycle (budget exhausted or
per-record error) are *not* pushed, so their stale fingerprint makes the next
cycle retry them.
"""

import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from cmc_shared.enums import ConnectionStatus, ErrorCode, SyncRunStatus
from cmc_shared.logging import bind_correlation
from cmc_shared.protocol import CartsBatch, ConversationsBatch, OrdersBatch

from agent.adapter import CardmarketAdapter, SessionState
from agent.api_client import ApiClient
from agent.errors import AccessBlockedError, AgentError, AuthRequiredError, classify

log = logging.getLogger("cmc.agent.sync")


@dataclass
class SyncOutcome:
    ran: bool
    status: SyncRunStatus | None = None
    reason: str | None = None
    errors: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)


class _Record(Protocol):
    @property
    def cardmarket_id(self) -> str: ...

    def fingerprint(self) -> str: ...


async def _details_for_changed[S: _Record, D](
    summaries: Sequence[S],
    known: dict[str, str],
    fetch: Callable[[S], Awaitable[D]],
    budget: list[int],
    errors: list[str],
) -> tuple[list[S], list[D]]:
    """Return (summaries to push, details fetched) honoring the detail budget."""
    push: list[S] = []
    details: list[D] = []
    for summary in summaries:
        cm_id = summary.cardmarket_id
        changed = known.get(cm_id) != summary.fingerprint()
        if not changed:
            push.append(summary)
            continue
        if budget[0] <= 0:
            continue  # deferred to the next cycle
        budget[0] -= 1
        try:
            details.append(await fetch(summary))
            push.append(summary)
        except (AuthRequiredError, AccessBlockedError):
            raise
        except AgentError as exc:
            if exc.code == ErrorCode.CARDMARKET_CHANGED:
                raise
            errors.append(f"{cm_id}: {exc.code}: {exc.message}")
    return push, details


class SyncCycle:
    def __init__(
        self,
        adapter: CardmarketAdapter,
        api: ApiClient,
        agent_id: str,
        max_details: int,
        report_session: Callable[[SessionState], Awaitable[None]],
    ) -> None:
        self.adapter = adapter
        self.api = api
        self.agent_id = agent_id
        self.max_details = max_details
        self.report_session = report_session

    async def run(self, trigger: str = "schedule") -> SyncOutcome:
        session = await self.adapter.check_session()
        await self.report_session(session)
        if not session.connected:
            return SyncOutcome(ran=False, reason=f"session {session.status}")

        start = await self.api.sync_start(self.agent_id, trigger)
        if not start.granted or start.sync_run_id is None:
            return SyncOutcome(ran=False, reason=start.reason)
        run_id = start.sync_run_id
        bind_correlation(sync_id=start.sync_id or str(run_id))
        log.info("sync cycle started", extra={"trigger": trigger})

        budget = [self.max_details]
        errors: list[str] = []
        stats: dict[str, Any] = {}
        failed_entities: list[str] = []
        try:
            for entity, step in (
                ("orders", self._orders),
                ("conversations", self._conversations),
                ("carts", self._carts),
            ):
                try:
                    stats[entity] = await step(run_id, start, budget, errors)
                except (AuthRequiredError, AccessBlockedError):
                    raise
                except AgentError as exc:
                    # One section of the site changed: keep syncing the others.
                    failed_entities.append(entity)
                    errors.append(f"{entity}: {exc.code}: {exc.message}")
                    log.error(
                        "sync step failed", extra={"entity": entity, "error_code": str(exc.code)}
                    )
                    exc.artifacts = exc.artifacts or await self.adapter.capture_failure(
                        f"sync-{entity}"
                    )
                    stats.setdefault("artifacts", []).extend(exc.artifacts)
                    if len(failed_entities) == 3:
                        raise
        except AccessBlockedError as exc:
            # Stop immediately: no further Cardmarket page in this cycle (or later ones,
            # see AgentRunner.access_blocked).
            await self.report_session(SessionState(ConnectionStatus.ERROR, exc.message, exc.code))
            await self.api.sync_complete(
                run_id,
                SyncRunStatus.FAILED,
                error_code=exc.code,
                error_message=exc.message,
                artifacts=exc.artifacts,
            )
            return SyncOutcome(
                ran=True, status=SyncRunStatus.FAILED, reason="blocked", errors=[exc.message]
            )
        except AuthRequiredError as exc:
            await self.report_session(
                SessionState(ConnectionStatus.SESSION_EXPIRED, exc.message, exc.code)
            )
            await self.api.sync_complete(
                run_id, SyncRunStatus.FAILED, error_code=exc.code, error_message=exc.message
            )
            return SyncOutcome(
                ran=True, status=SyncRunStatus.FAILED, reason="auth", errors=[exc.message]
            )
        except Exception as exc:
            code, _ = classify(exc)
            artifacts = stats.get("artifacts") or await self.adapter.capture_failure("sync")
            message = "; ".join(errors) if errors else str(exc)
            await self.api.sync_complete(
                run_id,
                SyncRunStatus.FAILED,
                error_code=code,
                error_message=message[:2000],
                artifacts=artifacts,
            )
            log.exception("sync failed", extra={"error_code": str(code)})
            return SyncOutcome(ran=True, status=SyncRunStatus.FAILED, errors=[message])

        status = SyncRunStatus.PARTIAL if errors else SyncRunStatus.SUCCESS
        partial_code: ErrorCode | None = (
            ErrorCode.CARDMARKET_CHANGED
            if failed_entities
            else (ErrorCode.UNKNOWN if errors else None)
        )
        await self.api.sync_complete(
            run_id,
            status,
            error_code=partial_code,
            error_message="; ".join(errors)[:2000] or None,
            artifacts=stats.get("artifacts", []),
        )
        log.info("sync cycle finished", extra={"status": str(status), "stats": stats})
        return SyncOutcome(ran=True, status=status, errors=errors, stats=stats)

    async def _orders(
        self, run_id: int, start: Any, budget: list[int], errors: list[str]
    ) -> dict[str, int]:
        summaries = await self.adapter.list_orders()
        push, details = await _details_for_changed(
            summaries, start.known_orders, self.adapter.get_order, budget, errors
        )
        res = await self.api.push_orders(run_id, OrdersBatch(summaries=push, details=details))
        return {"listed": len(summaries), "details": len(details), "changed": res.records_changed}

    async def _conversations(
        self, run_id: int, start: Any, budget: list[int], errors: list[str]
    ) -> dict[str, int]:
        summaries = await self.adapter.list_conversations()
        push, details = await _details_for_changed(
            summaries, start.known_conversations, self.adapter.get_conversation, budget, errors
        )
        res = await self.api.push_conversations(
            run_id, ConversationsBatch(summaries=push, details=details)
        )
        return {"listed": len(summaries), "details": len(details), "changed": res.records_changed}

    async def _carts(
        self, run_id: int, start: Any, budget: list[int], errors: list[str]
    ) -> dict[str, int]:
        summaries = await self.adapter.list_carts()
        push, details = await _details_for_changed(
            summaries, start.known_carts, self.adapter.get_cart, budget, errors
        )
        res = await self.api.push_carts(run_id, CartsBatch(summaries=push, details=details))
        return {"listed": len(summaries), "details": len(details), "changed": res.records_changed}
