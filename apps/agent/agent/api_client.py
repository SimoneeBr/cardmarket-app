"""HTTP client for the companion API's internal agent endpoints."""

import asyncio
import logging
from typing import Any, TypeVar

import httpx
from cmc_shared.enums import SyncEntity, SyncRunStatus
from cmc_shared.protocol import (
    ActionResultRequest,
    CartsBatch,
    ClaimedAction,
    ClaimRequest,
    ConversationsBatch,
    HeartbeatRequest,
    HeartbeatResponse,
    OrdersBatch,
    SessionReport,
    SyncBatchResult,
    SyncCompleteRequest,
    SyncStartRequest,
    SyncStartResponse,
)
from pydantic import BaseModel

from agent.errors import ApiUnavailableError

log = logging.getLogger("cmc.agent.api")

M = TypeVar("M", bound=BaseModel)


class ApiClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout: float = 30.0,
        retries: int = 3,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {token}", "User-Agent": "cmc-agent"},
            timeout=timeout,
            transport=transport,
        )
        self._retries = retries

    async def close(self) -> None:
        await self._client.aclose()

    async def _post(
        self, path: str, body: BaseModel | None, *, idempotent: bool = True
    ) -> httpx.Response:
        payload = body.model_dump(mode="json") if body is not None else {}
        attempts = self._retries if idempotent else 1
        last: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                res = await self._client.post(f"/internal/agent{path}", json=payload)
            except httpx.TransportError as exc:
                last = exc
                log.warning("api unreachable", extra={"path": path, "attempt": attempt})
                await asyncio.sleep(min(2**attempt, 10))
                continue
            if res.status_code >= 500 and attempt < attempts:
                last = ApiUnavailableError(f"{res.status_code} on {path}")
                await asyncio.sleep(min(2**attempt, 10))
                continue
            if res.status_code >= 400:
                raise ApiUnavailableError(f"{res.status_code} on {path}: {res.text[:200]}")
            return res
        raise ApiUnavailableError(f"API unavailable ({path}): {last}")

    async def _call(self, path: str, body: BaseModel | None, model: type[M]) -> M:
        res = await self._post(path, body)
        return model.model_validate(res.json())

    # ---------------------------------------------------------------- endpoints

    async def heartbeat(self, req: HeartbeatRequest) -> HeartbeatResponse:
        return await self._call("/heartbeat", req, HeartbeatResponse)

    async def report_session(self, req: SessionReport) -> HeartbeatResponse:
        return await self._call("/session", req, HeartbeatResponse)

    async def sync_start(self, agent_id: str, trigger: str) -> SyncStartResponse:
        req = SyncStartRequest(agent_id=agent_id, entity=SyncEntity.FULL, trigger=trigger)
        return await self._call("/sync/start", req, SyncStartResponse)

    async def push_orders(self, run_id: int, batch: OrdersBatch) -> SyncBatchResult:
        return await self._call(f"/sync/{run_id}/orders", batch, SyncBatchResult)

    async def push_conversations(self, run_id: int, batch: ConversationsBatch) -> SyncBatchResult:
        return await self._call(f"/sync/{run_id}/conversations", batch, SyncBatchResult)

    async def push_carts(self, run_id: int, batch: CartsBatch) -> SyncBatchResult:
        return await self._call(f"/sync/{run_id}/carts", batch, SyncBatchResult)

    async def sync_complete(
        self,
        run_id: int,
        status: SyncRunStatus,
        *,
        error_code: Any = None,
        error_message: str | None = None,
        artifacts: list[str] | None = None,
    ) -> None:
        req = SyncCompleteRequest(
            status=status,
            error_code=error_code,
            error_message=error_message,
            artifacts=artifacts or [],
        )
        await self._post(f"/sync/{run_id}/complete", req)

    async def claim_action(self, agent_id: str, lease_seconds: int) -> ClaimedAction | None:
        # Not retried blindly: a lost response would leave a claimed action that
        # the lease-expiry recovery (with verification) will pick up later.
        res = await self._post(
            "/actions/claim",
            ClaimRequest(agent_id=agent_id, lease_seconds=lease_seconds),
            idempotent=False,
        )
        if res.status_code == 204 or not res.content or res.json() is None:
            return None
        return ClaimedAction.model_validate(res.json())

    async def report_action(self, action_id: int, result: ActionResultRequest) -> None:
        await self._post(f"/actions/{action_id}/result", result)
