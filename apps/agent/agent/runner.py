"""Main agent loop.

Single task, single browser context: sync cycles and actions are naturally
serialized for the account (no concurrent use of the Cardmarket session).
"""

import asyncio
import contextlib
import logging
import random
import signal
import time

from cmc_shared.enums import AgentCommandType, AgentMode, ConnectionStatus
from cmc_shared.logging import correlation_var
from cmc_shared.protocol import AgentCommand, HeartbeatRequest, HeartbeatResponse, SessionReport

from agent.actions import ActionExecutor
from agent.adapter import CardmarketAdapter, SessionState
from agent.api_client import ApiClient
from agent.config import AgentSettings
from agent.errors import ApiUnavailableError
from agent.health import write_health
from agent.sync import SyncCycle

log = logging.getLogger("cmc.agent")


class Backoff:
    """Exponential backoff with jitter, capped; reset on success."""

    def __init__(self, base: float = 2.0, cap: float = 300.0) -> None:
        self.base, self.cap, self.failures = base, cap, 0

    def next_delay(self) -> float:
        self.failures += 1
        delay = float(min(self.cap, self.base * 2 ** (self.failures - 1)))
        return delay + random.uniform(0, delay * 0.25)  # noqa: S311

    def reset(self) -> None:
        self.failures = 0


class AgentRunner:
    def __init__(self, settings: AgentSettings, api: ApiClient, adapter: CardmarketAdapter) -> None:
        self.settings = settings
        self.api = api
        self.adapter = adapter
        self.stop_event = asyncio.Event()
        self.status = ConnectionStatus.DISCONNECTED
        self.sync_enabled = True
        self.sync_interval = settings.sync_interval_seconds
        self.next_sync_at = 0.0
        self.next_heartbeat_at = 0.0
        self.sync_now = False
        self.api_backoff = Backoff()
        self.sync_backoff = Backoff(base=settings.sync_interval_seconds, cap=900)
        self.executor = ActionExecutor(
            adapter, self.report_session, settings.pairing_timeout_seconds
        )
        self.sync = SyncCycle(
            adapter, api, settings.agent_id, settings.max_details_per_sync, self.report_session
        )

    # --------------------------------------------------------------- reporting

    async def report_session(self, state: SessionState) -> None:
        if state.status == self.status and state.status == ConnectionStatus.CONNECTED:
            return  # nothing new; avoid chatty updates
        response = await self.api.report_session(
            SessionReport(
                status=state.status,
                error_code=state.error_code,
                message=state.message,
                authenticated=state.connected,
            )
        )
        if state.status != self.status:
            log.info("session status", extra={"from": str(self.status), "to": str(state.status)})
        self.status = state.status
        self._apply_settings(response)

    def _apply_settings(self, response: HeartbeatResponse) -> None:
        self.sync_enabled = response.sync_enabled
        self.sync_interval = response.sync_interval_seconds

    async def heartbeat(self) -> None:
        response = await self.api.heartbeat(
            HeartbeatRequest(
                agent_id=self.settings.agent_id,
                version=self.settings.agent_version,
                mode=AgentMode.MOCK if self.settings.mock_cardmarket else AgentMode.LIVE,
                connection_status=self.status,
                detail=f"adapter={self.adapter.name}",
            )
        )
        self._apply_settings(response)
        for command in response.commands:
            await self.handle_command(command)
        self.next_heartbeat_at = time.monotonic() + self.settings.heartbeat_seconds

    async def handle_command(self, command: AgentCommand) -> None:
        log.info("command received", extra={"command": str(command.type)})
        if command.type == AgentCommandType.SYNC_NOW:
            self.sync_now = True
        elif command.type == AgentCommandType.DISCONNECT:
            await self.adapter.disconnect()
            self.status = ConnectionStatus.DISCONNECTED
        else:
            await self.adapter.handle_command(command)
            if command.type == AgentCommandType.SIMULATE_NEW_ACTIVITY:
                self.sync_now = True
            elif command.type == AgentCommandType.SIMULATE_SESSION_EXPIRED:
                self.sync_now = True  # detect it right away

    # ----------------------------------------------------------------- actions

    async def process_actions(self) -> int:
        processed = 0
        while processed < self.settings.max_actions_per_tick and not self.stop_event.is_set():
            action = await self.api.claim_action(
                self.settings.agent_id, self.settings.action_lease_seconds
            )
            if action is None:
                break
            token = correlation_var.set(
                {
                    "action_id": str(action.id),
                    **({"correlation_id": action.correlation_id} if action.correlation_id else {}),
                }
            )
            try:
                log.info(
                    "action started",
                    extra={
                        "action_type": str(action.type),
                        "recovery": action.recovery,
                        "attempt": action.attempts,
                    },
                )
                result = await self.executor.execute(action)
                await self.api.report_action(action.id, result)
                log.info(
                    "action finished",
                    extra={"outcome": str(result.outcome), "error_code": str(result.error_code)},
                )
            finally:
                correlation_var.reset(token)
            processed += 1
        return processed

    # -------------------------------------------------------------------- sync

    async def maybe_sync(self) -> None:
        due = self.sync_now or time.monotonic() >= self.next_sync_at
        if not due:
            return
        trigger = "manual" if self.sync_now else "schedule"
        self.sync_now = False
        if not self.sync_enabled or self.status == ConnectionStatus.DISCONNECTED:
            self.next_sync_at = time.monotonic() + self.sync_interval
            return
        token = correlation_var.set({})
        try:
            outcome = await self.sync.run(trigger)
        finally:
            correlation_var.reset(token)
        if outcome.ran and outcome.status is not None and outcome.status.value == "FAILED":
            delay = self.sync_backoff.next_delay()
            log.warning("sync failed, backing off", extra={"delay_s": round(delay, 1)})
        else:
            self.sync_backoff.reset()
            delay = self.sync_interval
        self.next_sync_at = time.monotonic() + delay

    # -------------------------------------------------------------------- loop

    async def tick(self) -> None:
        if time.monotonic() >= self.next_heartbeat_at:
            await self.heartbeat()
        await self.process_actions()
        await self.maybe_sync()

    async def _health_writer(self) -> None:
        while not self.stop_event.is_set():
            try:
                write_health(self.settings.health_file, self.api.last_success, str(self.status))
            except OSError:
                log.warning("cannot write health file", exc_info=True)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self.stop_event.wait(), timeout=10)

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        health_task = asyncio.create_task(self._health_writer())
        for sig in (signal.SIGTERM, signal.SIGINT):
            with contextlib.suppress(NotImplementedError):
                loop.add_signal_handler(sig, self.stop_event.set)
        log.info(
            "agent starting",
            extra={"agent_id": self.settings.agent_id, "adapter": self.adapter.name},
        )
        await self.adapter.start()
        try:
            await self._bootstrap()
            while not self.stop_event.is_set():
                try:
                    await self.tick()
                    self.api_backoff.reset()
                    wait = self.settings.action_poll_seconds
                except ApiUnavailableError as exc:
                    wait = self.api_backoff.next_delay()
                    log.warning(
                        "api unavailable, retrying",
                        extra={"delay_s": round(wait, 1), "error": str(exc)[:200]},
                    )
                except Exception:
                    wait = self.api_backoff.next_delay()
                    log.exception(
                        "unexpected error in agent loop", extra={"delay_s": round(wait, 1)}
                    )
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self.stop_event.wait(), timeout=wait)
        finally:
            log.info("agent shutting down")
            health_task.cancel()
            await self.adapter.close()
            await self.api.close()

    async def _bootstrap(self) -> None:
        """Report the persisted session state as soon as we start."""
        while not self.stop_event.is_set():
            try:
                await self.heartbeat()
                state = await self.adapter.check_session()
                self.status = ConnectionStatus.DISCONNECTED  # force a first report
                await self.report_session(state)
                return
            except ApiUnavailableError as exc:
                wait = self.api_backoff.next_delay()
                log.warning(
                    "api not reachable at startup",
                    extra={"delay_s": round(wait, 1), "error": str(exc)[:200]},
                )
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self.stop_event.wait(), timeout=wait)
