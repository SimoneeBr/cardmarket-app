"""Mock adapter + executor + sync cycle + runner (no browser, no API server)."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from cmc_shared.enums import (
    ActionOutcome,
    ActionType,
    AgentCommandType,
    ConnectionStatus,
    ErrorCode,
    OrderStatus,
    SyncRunStatus,
)
from cmc_shared.protocol import AgentCommand, ClaimedAction

from agent.actions import ActionExecutor
from agent.adapter import SessionState
from agent.config import AgentSettings
from agent.mock.adapter import MockCardmarketAdapter
from agent.runner import AgentRunner, Backoff
from agent.sync import SyncCycle
from tests.conftest import FakeApi, send_action


async def _adapter(settings: AgentSettings) -> MockCardmarketAdapter:
    adapter = MockCardmarketAdapter(settings)
    await adapter.start()
    return adapter


def _executor(adapter: MockCardmarketAdapter, reports: list[SessionState]) -> ActionExecutor:
    async def report(state: SessionState) -> None:
        reports.append(state)

    return ActionExecutor(adapter, report, pairing_timeout=5)


async def test_dataset_is_rich_enough(settings: AgentSettings) -> None:
    adapter = await _adapter(settings)
    orders = await adapter.list_orders()
    convos = await adapter.list_conversations()
    carts = await adapter.list_carts()
    assert len(orders) >= 20 and len(convos) >= 10 and len(carts) >= 10
    assert {o.status for o in orders} >= {
        OrderStatus.UNPAID,
        OrderStatus.PAID,
        OrderStatus.SHIPPED,
        OrderStatus.COMPLETED,
    }
    thread = await adapter.get_conversation(convos[0])
    assert thread.messages and thread.messages[0].direction.value == "INBOUND"


async def test_state_survives_restart(settings: AgentSettings) -> None:
    adapter = await _adapter(settings)
    convo = (await adapter.list_conversations())[0]
    await adapter.submit_message(convo, "persisted?")
    await adapter.close()
    again = await _adapter(settings)
    thread = await again.get_conversation(convo)
    assert thread.messages[-1].body == "persisted?" or any(
        m.body == "persisted?" for m in thread.messages
    )


async def test_send_message_is_verified(settings: AgentSettings) -> None:
    adapter = await _adapter(settings)
    convo = (await adapter.list_conversations())[0]
    result = await _executor(adapter, []).execute(
        send_action(1, convo.cardmarket_id, convo.buyer_name, "Spediamo domani")
    )
    assert result.outcome == ActionOutcome.SUCCESS
    assert result.result["cardmarket_message_id"]


@pytest.mark.parametrize(
    ("body", "outcome", "code"),
    [
        ("x [mock:fail]", ActionOutcome.RETRY, ErrorCode.NETWORK_ERROR),
        ("x [mock:unverified]", ActionOutcome.UNVERIFIED, ErrorCode.VERIFICATION_FAILED),
        ("x [mock:unsafe]", ActionOutcome.UNSAFE, ErrorCode.SELECTOR_NOT_FOUND),
    ],
)
async def test_send_failure_modes(
    settings: AgentSettings, body: str, outcome: ActionOutcome, code: ErrorCode
) -> None:
    adapter = await _adapter(settings)
    convo = (await adapter.list_conversations())[0]
    result = await _executor(adapter, []).execute(
        send_action(1, convo.cardmarket_id, convo.buyer_name, body)
    )
    assert (result.outcome, result.error_code) == (outcome, code)


async def test_wrong_buyer_is_refused(settings: AgentSettings) -> None:
    adapter = await _adapter(settings)
    convo = (await adapter.list_conversations())[0]
    result = await _executor(adapter, []).execute(
        send_action(1, convo.cardmarket_id, "someone_else", "hi")
    )
    assert result.outcome == ActionOutcome.UNSAFE
    thread = await adapter.get_conversation(convo)
    assert all(m.body != "hi" for m in thread.messages)


async def test_recovery_does_not_send_twice(settings: AgentSettings) -> None:
    adapter = await _adapter(settings)
    convo = (await adapter.list_conversations())[0]
    requested = (datetime.now(UTC) - timedelta(seconds=5)).isoformat()
    await adapter.submit_message(
        convo, "Ciao, spedito!"
    )  # first attempt reached Cardmarket, then crash
    result = await _executor(adapter, []).execute(
        send_action(
            1,
            convo.cardmarket_id,
            convo.buyer_name,
            "Ciao, spedito!",
            recovery=True,
            requested_at=requested,
        )
    )
    assert result.outcome == ActionOutcome.SUCCESS and result.result.get("recovered") is True
    thread = await adapter.get_conversation(convo)
    assert sum(m.body == "Ciao, spedito!" for m in thread.messages) == 1


async def test_recovery_sends_when_not_found(settings: AgentSettings) -> None:
    adapter = await _adapter(settings)
    convo = (await adapter.list_conversations())[0]
    result = await _executor(adapter, []).execute(
        send_action(
            1,
            convo.cardmarket_id,
            convo.buyer_name,
            "Nuovo",
            recovery=True,
            requested_at=datetime.now(UTC).isoformat(),
        )
    )
    assert result.outcome == ActionOutcome.SUCCESS and not result.result.get("recovered")


async def test_mark_shipped_verified_and_idempotent(settings: AgentSettings) -> None:
    adapter = await _adapter(settings)
    paid = next(o for o in await adapter.list_orders() if o.status == OrderStatus.PAID)
    action = ClaimedAction(
        id=5,
        type=ActionType.MARK_ORDER_SHIPPED,
        payload={
            "order_cardmarket_id": paid.cardmarket_id,
            "buyer_name": paid.buyer_name,
            "tracking_number": "RR1IT",
        },
        attempts=1,
        idempotency_key="s",
    )
    executor = _executor(adapter, [])
    assert (await executor.execute(action)).outcome == ActionOutcome.SUCCESS
    detail = await adapter.get_order(paid)
    assert detail.status == OrderStatus.SHIPPED and detail.tracking_number == "RR1IT"
    again = await executor.execute(action)
    assert again.outcome == ActionOutcome.SUCCESS and again.result["already_shipped"] is True


async def test_session_expiry_and_pairing(settings: AgentSettings) -> None:
    adapter = await _adapter(settings)
    await adapter.handle_command(AgentCommand(type=AgentCommandType.SIMULATE_SESSION_EXPIRED))
    assert (await adapter.check_session()).status == ConnectionStatus.AUTH_REQUIRED
    reports: list[SessionState] = []
    convo_result = await _executor(adapter, reports).execute(send_action(1, "T7000", "x", "hi"))
    assert convo_result.outcome == ActionOutcome.RETRY
    assert reports[-1].status == ConnectionStatus.SESSION_EXPIRED
    pair = ClaimedAction(
        id=2, type=ActionType.PAIR_SESSION, payload={}, attempts=1, idempotency_key="p"
    )
    result = await _executor(adapter, reports).execute(pair)
    assert result.outcome == ActionOutcome.SUCCESS
    assert [r.status for r in reports[-2:]] == [
        ConnectionStatus.CONNECTING,
        ConnectionStatus.CONNECTED,
    ]


async def test_incremental_sync_fetches_only_changed_details(
    settings: AgentSettings, fake_api: FakeApi
) -> None:
    adapter = await _adapter(settings)
    reports: list[SessionState] = []

    async def report(state: SessionState) -> None:
        reports.append(state)

    cycle = SyncCycle(adapter, fake_api, "agent-test", max_details=100, report_session=report)  # type: ignore[arg-type]
    first = await cycle.run()
    assert first.status == SyncRunStatus.SUCCESS
    assert len(fake_api.orders[0].details) == len(fake_api.orders[0].summaries) == 24
    second = await cycle.run()
    assert second.status == SyncRunStatus.SUCCESS
    assert fake_api.orders[1].details == [] and fake_api.conversations[1].details == []

    await adapter.handle_command(AgentCommand(type=AgentCommandType.SIMULATE_NEW_ACTIVITY))
    await cycle.run()
    changed = (
        len(fake_api.orders[2].details)
        + len(fake_api.conversations[2].details)
        + len(fake_api.carts[2].details)
    )
    assert 1 <= changed <= 3


async def test_detail_budget_defers_records(settings: AgentSettings, fake_api: FakeApi) -> None:
    adapter = await _adapter(settings)

    async def report(state: SessionState) -> None:
        pass

    cycle = SyncCycle(adapter, fake_api, "agent-test", max_details=10, report_session=report)  # type: ignore[arg-type]
    await cycle.run()
    assert len(fake_api.orders[0].details) == 10
    assert len(fake_api.orders[0].summaries) == 10  # deferred ones are not pushed
    await cycle.run()
    await cycle.run()
    assert len(fake_api.known["orders"]) == 24


async def test_simulated_sync_error_is_partial(settings: AgentSettings, fake_api: FakeApi) -> None:
    adapter = await _adapter(settings)
    await adapter.handle_command(AgentCommand(type=AgentCommandType.SIMULATE_SYNC_ERROR))

    async def report(state: SessionState) -> None:
        pass

    outcome = await SyncCycle(adapter, fake_api, "a", 100, report).run()  # type: ignore[arg-type]
    assert outcome.status == SyncRunStatus.PARTIAL
    assert fake_api.completed[-1]["error_code"] == ErrorCode.CARDMARKET_CHANGED


async def test_runner_loop_processes_commands_actions_and_shuts_down(
    settings: AgentSettings, fake_api: FakeApi
) -> None:
    adapter = await _adapter(settings)
    convo = (await adapter.list_conversations())[0]
    fake_api.queue.append(send_action(42, convo.cardmarket_id, convo.buyer_name, "dal runner"))
    runner = AgentRunner(settings, fake_api, adapter)  # type: ignore[arg-type]
    task = asyncio.create_task(runner.run())
    for _ in range(200):
        if 42 in fake_api.results and fake_api.completed:
            break
        await asyncio.sleep(0.02)
    runner.stop_event.set()
    await asyncio.wait_for(task, 5)
    assert fake_api.results[42].outcome == ActionOutcome.SUCCESS
    assert fake_api.completed[0]["status"] == SyncRunStatus.SUCCESS
    assert fake_api.sessions[0].status == ConnectionStatus.CONNECTED


def test_backoff_is_exponential_and_capped() -> None:
    backoff = Backoff(base=1, cap=8)
    delays = [backoff.next_delay() for _ in range(6)]
    assert delays[0] < 1.5 and 8 <= delays[-1] <= 10
    backoff.reset()
    assert backoff.next_delay() < 1.5


async def test_health_file_reflects_loop_and_api(
    settings: AgentSettings, fake_api: FakeApi, tmp_path
) -> None:  # type: ignore[no-untyped-def]
    from agent.health import check_health

    health = tmp_path / "health.json"
    settings = settings.model_copy(update={"health_file": health})
    fake_api.last_success = None  # type: ignore[attr-defined]
    adapter = await _adapter(settings)
    runner = AgentRunner(settings, fake_api, adapter)  # type: ignore[arg-type]
    task = asyncio.create_task(runner.run())
    await asyncio.sleep(0.2)
    ok, detail = check_health(health)
    assert not ok and "API" in detail  # loop alive but no API success recorded
    fake_api.last_success = __import__("time").time()  # type: ignore[attr-defined]
    await asyncio.sleep(0)
    runner.stop_event.set()
    await asyncio.wait_for(task, 5)


def test_health_check_rules(tmp_path) -> None:  # type: ignore[no-untyped-def]
    import time

    from agent.health import check_health, write_health

    path = tmp_path / "h.json"
    assert check_health(path) == (False, "no health file yet")
    write_health(path, time.time(), "CONNECTED")
    assert check_health(path)[0] is True
    assert check_health(path, now=time.time() + 120)[0] is False  # loop stalled
    write_health(path, time.time() - 1000, "CONNECTED")
    assert check_health(path)[0] is False  # API not reachable for too long
