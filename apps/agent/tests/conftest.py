import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from cmc_shared.enums import ActionType
from cmc_shared.protocol import (
    ActionResultRequest,
    CartsBatch,
    ClaimedAction,
    ConversationsBatch,
    HeartbeatRequest,
    HeartbeatResponse,
    OrdersBatch,
    SessionReport,
    SyncBatchResult,
    SyncStartResponse,
)

os.environ.setdefault("ENVIRONMENT", "test")

from agent.config import AgentSettings


@pytest.fixture
def settings(tmp_path: Path) -> AgentSettings:
    return AgentSettings(
        environment="test",
        agent_api_token="t" * 40,  # type: ignore[arg-type]
        agent_id="agent-test",
        mock_cardmarket=True,
        mock_state_file=tmp_path / "mock" / "state.json",
        mock_auto_pair=True,
        mock_pairing_delay_seconds=0.01,
        mock_activity_rate=0.0,
        browser_profile_dir=tmp_path / "profile",
        artifacts_dir=tmp_path / "artifacts",
        min_navigation_delay_ms=0,
        max_navigation_delay_ms=0,
        navigation_timeout_ms=10_000,
        action_timeout_ms=3_000,
        heartbeat_seconds=0,
        action_poll_seconds=0.01,
    )


class FakeApi:
    """In-memory stand-in for the companion API (records what the agent sends)."""

    def __init__(self) -> None:
        self.sessions: list[SessionReport] = []
        self.orders: list[OrdersBatch] = []
        self.conversations: list[ConversationsBatch] = []
        self.carts: list[CartsBatch] = []
        self.completed: list[dict[str, Any]] = []
        self.results: dict[int, ActionResultRequest] = {}
        self.queue: list[ClaimedAction] = []
        self.known: dict[str, dict[str, str]] = {"orders": {}, "conversations": {}, "carts": {}}
        self.commands: list[dict[str, Any]] = []
        self.heartbeats = 0

    async def heartbeat(self, req: HeartbeatRequest) -> HeartbeatResponse:
        self.heartbeats += 1
        commands, self.commands = self.commands, []
        return HeartbeatResponse.model_validate(
            {"sync_enabled": True, "sync_interval_seconds": 30, "commands": commands}
        )

    async def report_session(self, req: SessionReport) -> HeartbeatResponse:
        self.sessions.append(req)
        return HeartbeatResponse(sync_enabled=True, sync_interval_seconds=30)

    async def sync_start(self, agent_id: str, trigger: str) -> SyncStartResponse:
        return SyncStartResponse(
            granted=True,
            sync_run_id=1,
            sync_id="abc",
            known_orders=self.known["orders"],
            known_conversations=self.known["conversations"],
            known_carts=self.known["carts"],
        )

    def _remember(self, kind: str, summaries: list[Any]) -> None:
        for s in summaries:
            self.known[kind][s.cardmarket_id] = s.fingerprint()

    async def push_orders(self, run_id: int, batch: OrdersBatch) -> SyncBatchResult:
        self.orders.append(batch)
        self._remember("orders", batch.summaries)
        return SyncBatchResult(
            records_found=len(batch.summaries), records_changed=len(batch.details), events=0
        )

    async def push_conversations(self, run_id: int, batch: ConversationsBatch) -> SyncBatchResult:
        self.conversations.append(batch)
        self._remember("conversations", batch.summaries)
        return SyncBatchResult(
            records_found=len(batch.summaries), records_changed=len(batch.details), events=0
        )

    async def push_carts(self, run_id: int, batch: CartsBatch) -> SyncBatchResult:
        self.carts.append(batch)
        self._remember("carts", batch.summaries)
        return SyncBatchResult(
            records_found=len(batch.summaries), records_changed=len(batch.details), events=0
        )

    async def sync_complete(self, run_id: int, status: Any, **kw: Any) -> None:
        self.completed.append({"status": status, **kw})

    async def claim_action(self, agent_id: str, lease_seconds: int) -> ClaimedAction | None:
        return self.queue.pop(0) if self.queue else None

    async def report_action(self, action_id: int, result: ActionResultRequest) -> None:
        self.results[action_id] = result

    async def close(self) -> None:
        pass


@pytest.fixture
def fake_api() -> Iterator[FakeApi]:
    yield FakeApi()


def send_action(
    action_id: int,
    convo: str,
    buyer: str,
    body: str,
    *,
    recovery: bool = False,
    requested_at: str | None = None,
) -> ClaimedAction:
    return ClaimedAction(
        id=action_id,
        type=ActionType.SEND_MESSAGE,
        payload={
            "message_id": action_id,
            "conversation_cardmarket_id": convo,
            "buyer_name": buyer,
            "body": body,
            **({"requested_at": requested_at} if requested_at else {}),
        },
        attempts=1,
        idempotency_key=f"k{action_id}",
        recovery=recovery,
    )
