"""ACCESS_BLOCKED is a blocking, non-retryable state (offline tests).

A "navigation" is any adapter call that would load a Cardmarket page. The
CountingAdapter wraps the mock adapter and counts them; the last tests use the
real Playwright adapter against the local fake site serving the real
(anonymised) Cloudflare block page and count the HTTP requests it receives.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from cmc_shared.enums import (
    ActionOutcome,
    ActionType,
    AgentCommandType,
    ConnectionStatus,
    ErrorCode,
    SyncRunStatus,
)
from cmc_shared.protocol import ClaimedAction

from agent.adapter import SessionState
from agent.config import AgentSettings
from agent.errors import AccessBlockedError, NetworkError
from agent.mock.adapter import MockCardmarketAdapter
from agent.runner import AgentRunner
from tests.conftest import FakeApi, block_external_requests, send_action
from tests.fake_site import FakeSite

RAY = "a43632d17d8bea6f"
BLOCKED_MSG = (
    "Access blocked by Cloudflare before reaching Cardmarket; session state unknown "
    f"(Cloudflare Ray ID {RAY})"
)
_NAVIGATING = {
    "check_session", "pair", "list_orders", "get_order", "list_conversations",
    "get_conversation", "list_carts", "get_cart", "submit_message", "submit_mark_shipped",
}  # fmt: skip


class CountingAdapter:
    """Mock adapter whose Cardmarket calls are counted and can be made to fail."""

    name = "counting"

    def __init__(self, inner: MockCardmarketAdapter) -> None:
        self.inner = inner
        self.calls: list[str] = []
        self.mode = "ok"  # ok | blocked | blocked_mid_sync | network | changed | auth

    @property
    def navigations(self) -> int:
        return sum(1 for c in self.calls if c in _NAVIGATING)

    async def check_session(self) -> SessionState:
        self.calls.append("check_session")
        if self.mode == "blocked":
            return SessionState(ConnectionStatus.ERROR, BLOCKED_MSG, ErrorCode.ACCESS_BLOCKED)
        if self.mode == "changed":
            return SessionState(ConnectionStatus.ERROR, "unknown", ErrorCode.CARDMARKET_CHANGED)
        if self.mode == "auth":
            return SessionState(ConnectionStatus.SESSION_EXPIRED, "login", ErrorCode.AUTH_ERROR)
        return await self.inner.check_session()

    async def list_orders(self) -> Any:
        self.calls.append("list_orders")
        if self.mode == "blocked_mid_sync":
            raise AccessBlockedError(BLOCKED_MSG)
        if self.mode == "network":
            raise NetworkError("net::ERR_CONNECTION_RESET")
        return await self.inner.list_orders()

    def __getattr__(self, name: str) -> Any:
        target = getattr(self.inner, name)
        if name not in _NAVIGATING:
            return target

        async def counted(*args: Any, **kwargs: Any) -> Any:
            self.calls.append(name)
            return await target(*args, **kwargs)

        return counted


@pytest.fixture
async def rig(
    settings: AgentSettings, fake_api: FakeApi
) -> tuple[AgentRunner, CountingAdapter, FakeApi]:
    inner = MockCardmarketAdapter(settings)
    await inner.start()
    adapter = CountingAdapter(inner)
    runner = AgentRunner(settings, fake_api, adapter)  # type: ignore[arg-type]
    await runner._bootstrap()
    return runner, adapter, fake_api


async def cycles(runner: AgentRunner, n: int) -> None:
    """Run n loop iterations, each with a sync due (simulates time passing)."""
    for _ in range(n):
        runner.next_sync_at = 0
        await runner.tick()


# 6. normal initial state -------------------------------------------------------


async def test_normal_state_keeps_syncing(rig: Any) -> None:
    runner, adapter, api = rig
    await cycles(runner, 3)
    assert runner.access_blocked is None
    assert api.sync_starts == 3
    assert [c["status"] for c in api.completed] == [SyncRunStatus.SUCCESS] * 3
    assert adapter.calls.count("check_session") == 1 + 3  # bootstrap + one per cycle


# 1 + 2 + 8. ACCESS_BLOCKED stops navigation, idempotently, keeps the Ray ID -------


async def test_blocked_session_check_suspends_all_navigation(rig: Any) -> None:
    runner, adapter, api = rig
    adapter.mode = "blocked"
    await cycles(runner, 1)  # this cycle hits the block
    assert runner.access_blocked is not None and RAY in runner.access_blocked
    reported = api.sessions[-1]
    assert (reported.status, reported.error_code) == (
        ConnectionStatus.ERROR,
        ErrorCode.ACCESS_BLOCKED,
    )
    assert RAY in (reported.message or "")

    after_block = adapter.navigations
    await cycles(runner, 1)
    assert adapter.navigations == after_block  # next cycle: nothing
    await cycles(runner, 20)
    assert adapter.navigations == after_block  # many cycles: still nothing
    assert api.sync_starts == 0
    reports_blocked = [s for s in api.sessions if s.error_code == ErrorCode.ACCESS_BLOCKED]
    assert len(reports_blocked) == 1  # idempotent: no repeated reports either


async def test_block_during_sync_aborts_the_cycle(rig: Any) -> None:
    runner, adapter, api = rig
    adapter.mode = "blocked_mid_sync"
    await cycles(runner, 1)
    assert adapter.calls[-1] == "list_orders"  # no conversations/carts/details after it
    assert api.completed[-1]["status"] == SyncRunStatus.FAILED
    assert api.completed[-1]["error_code"] == ErrorCode.ACCESS_BLOCKED
    assert RAY in api.completed[-1]["error_message"]
    before = adapter.navigations
    await cycles(runner, 5)
    assert adapter.navigations == before


async def test_sync_now_is_ignored_while_blocked(rig: Any) -> None:
    runner, adapter, api = rig
    adapter.mode = "blocked"
    await cycles(runner, 1)
    before = adapter.navigations
    api.commands.append({"type": AgentCommandType.SYNC_NOW, "params": {}})
    runner.next_heartbeat_at = 0
    await runner.tick()
    assert runner.sync_now is False
    assert adapter.navigations == before


async def test_block_persisted_by_api_skips_startup_probe(
    settings: AgentSettings, fake_api: FakeApi
) -> None:
    fake_api.blocked = True  # e.g. the agent restarted while blocked
    inner = MockCardmarketAdapter(settings)
    await inner.start()
    adapter = CountingAdapter(inner)
    runner = AgentRunner(settings, fake_api, adapter)  # type: ignore[arg-type]
    await runner._bootstrap()
    await cycles(runner, 3)
    assert adapter.navigations == 0


async def test_write_action_hitting_a_block_is_not_executed(rig: Any) -> None:
    runner, adapter, api = rig
    convo = (await adapter.inner.list_conversations())[0]
    adapter.mode = "blocked"

    async def blocked_get_conversation(summary: Any) -> Any:
        adapter.calls.append("get_conversation")
        raise AccessBlockedError(BLOCKED_MSG)

    adapter.get_conversation = blocked_get_conversation  # type: ignore[method-assign]
    api.queue.append(send_action(7, convo.cardmarket_id, convo.buyer_name, "ciao"))
    await runner.process_actions()
    result = api.results[7]
    assert (result.outcome, result.error_code) == (ActionOutcome.RETRY, ErrorCode.ACCESS_BLOCKED)
    assert "submit_message" not in adapter.calls
    assert runner.access_blocked is not None


# 3, 4, 5. other error codes keep their current behaviour ------------------------


async def test_network_error_keeps_current_behaviour(rig: Any) -> None:
    runner, adapter, api = rig
    adapter.mode = "network"
    await cycles(runner, 1)
    assert runner.access_blocked is None
    # the failing section is recorded, the other sections still sync (PARTIAL)
    assert api.completed[-1]["status"] == SyncRunStatus.PARTIAL
    assert {"list_conversations", "list_carts"} <= set(adapter.calls)
    before = adapter.navigations
    await cycles(runner, 1)
    assert adapter.navigations > before  # retried on the next cycle, as before


@pytest.mark.parametrize(
    ("mode", "status", "code"),
    [
        ("changed", ConnectionStatus.ERROR, ErrorCode.CARDMARKET_CHANGED),
        ("auth", ConnectionStatus.SESSION_EXPIRED, ErrorCode.AUTH_ERROR),
    ],
)
async def test_other_session_errors_keep_current_behaviour(
    rig: Any, mode: str, status: ConnectionStatus, code: ErrorCode
) -> None:
    runner, adapter, api = rig
    adapter.mode = mode
    await cycles(runner, 3)
    assert runner.access_blocked is None
    assert (api.sessions[-1].status, api.sessions[-1].error_code) == (status, code)
    # unchanged: the session is probed again on every cycle, no sync is started
    assert adapter.calls.count("check_session") == 1 + 3
    assert api.completed == [] or all(c["status"] != SyncRunStatus.FAILED for c in api.completed)


# 7. resume only through an explicit operator action -------------------------------


async def test_resume_only_via_explicit_verify_session(rig: Any) -> None:
    runner, adapter, api = rig
    adapter.mode = "blocked"
    await cycles(runner, 1)
    adapter.mode = "ok"  # the block went away on the Cardmarket side...
    await cycles(runner, 5)
    assert runner.access_blocked is not None  # ...but nothing retries on its own
    assert api.sync_starts == 0

    # operator presses "Riconnetti" -> VERIFY_SESSION (explicit navigation)
    api.queue.append(
        ClaimedAction(
            id=9, type=ActionType.VERIFY_SESSION, payload={}, attempts=1, idempotency_key="v"
        )
    )
    await runner.process_actions()
    assert api.results[9].outcome == ActionOutcome.SUCCESS
    assert runner.access_blocked is None
    await cycles(runner, 2)
    assert api.sync_starts == 2  # automatic sync resumed


async def test_explicit_verify_while_still_blocked_stays_blocked(rig: Any) -> None:
    runner, adapter, api = rig
    adapter.mode = "blocked"
    await cycles(runner, 1)
    api.queue.append(
        ClaimedAction(
            id=10, type=ActionType.VERIFY_SESSION, payload={}, attempts=1, idempotency_key="v2"
        )
    )
    await runner.process_actions()
    result = api.results[10]
    assert (result.outcome, result.error_code) == (ActionOutcome.FAILED, ErrorCode.ACCESS_BLOCKED)
    assert runner.access_blocked is not None
    before = adapter.navigations
    await cycles(runner, 3)
    assert adapter.navigations == before


async def test_heartbeat_alone_never_clears_the_block(rig: Any) -> None:
    runner, adapter, api = rig
    adapter.mode = "blocked"
    await cycles(runner, 1)
    api.blocked = False  # API says not blocked (e.g. data purged): no automatic resume
    runner.next_heartbeat_at = 0
    await cycles(runner, 3)
    assert runner.access_blocked is not None


# Real Playwright adapter against the local fake site (Cloudflare page) ------------


@pytest.fixture
def blocked_site() -> Iterator[FakeSite]:
    with FakeSite() as site:
        site.state.cloudflare_blocked = True
        yield site


@pytest.mark.browser
async def test_live_adapter_stops_requesting_after_block(
    settings: AgentSettings, fake_api: FakeApi, blocked_site: FakeSite
) -> None:
    from agent.cardmarket.adapter import PlaywrightCardmarketAdapter
    from agent.cardmarket.urls import CardmarketUrls

    live = PlaywrightCardmarketAdapter(
        settings.model_copy(update={"mock_cardmarket": False}),
        urls=CardmarketUrls(blocked_site.base_url, "it", "Lorcana"),
    )
    await live.start()
    await block_external_requests(live)
    attempted: list[str] = []
    live.browser.page.on("request", lambda r: attempted.append(r.url))
    try:
        runner = AgentRunner(settings, fake_api, live)  # type: ignore[arg-type]
        await runner._bootstrap()  # startup probe: 1 request, blocked
        assert blocked_site.state.gets == 1
        assert runner.access_blocked is not None and RAY in runner.access_blocked
        await cycles(runner, 10)
        assert blocked_site.state.gets == 1  # zero further requests
        assert fake_api.sessions[-1].error_code == ErrorCode.ACCESS_BLOCKED
        assert "203.0.113.10" not in (fake_api.sessions[-1].message or "")  # no IP leaked
        assert attempted and all(u.startswith("http://127.0.0.1") for u in attempted), attempted
    finally:
        await live.close()


@pytest.mark.browser
async def test_pairing_stops_on_block_page(
    settings: AgentSettings, blocked_site: FakeSite, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agent.cardmarket.adapter import PlaywrightCardmarketAdapter
    from agent.cardmarket.urls import CardmarketUrls

    live = PlaywrightCardmarketAdapter(
        settings.model_copy(update={"mock_cardmarket": False}),
        urls=CardmarketUrls(blocked_site.base_url, "it", "Lorcana"),
    )
    await live.start()
    await block_external_requests(live)

    async def stay_headless(*, headless: bool) -> None:
        return None

    monkeypatch.setattr(live.browser, "restart", stay_headless)
    monkeypatch.setattr("agent.cardmarket.auth.pairing.POLL_SECONDS", 0.01)
    try:
        state = await live.pair(timeout_seconds=30)
    finally:
        await live.close()
    assert (state.status, state.error_code) == (ConnectionStatus.ERROR, ErrorCode.ACCESS_BLOCKED)
    assert blocked_site.state.gets == 1  # only the login page, no waiting/polling loop


def test_fixture_is_the_anonymised_capture() -> None:
    html = (
        Path(__file__).parent / "fixtures" / "cardmarket" / "cloudflare_blocked.html"
    ).read_text()
    assert RAY in html and "203.0.113.10" in html


@pytest.mark.browser
async def test_navigation_records_http_status_and_final_url(
    settings: AgentSettings, blocked_site: FakeSite, caplog: pytest.LogCaptureFixture
) -> None:
    from agent.cardmarket.browser.session import BrowserSession

    browser = BrowserSession(settings.model_copy(update={"mock_cardmarket": False}))
    await browser.start()
    await browser.page.context.route(
        "**/*",
        lambda route: (
            route.continue_() if route.request.url.startswith("http://127.0.0.1") else route.abort()
        ),
    )
    try:
        with caplog.at_level("INFO", logger="cmc.agent.browser"):
            await browser.goto(f"{blocked_site.base_url}/it/Lorcana/Orders/Sales/Paid")
    finally:
        await browser.close()
    assert browser.last_navigation is not None
    assert browser.last_navigation["status"] == 403
    assert str(browser.last_navigation["final_url"]).endswith("/it/Lorcana/Orders/Sales/Paid")
    record = next(r for r in caplog.records if r.getMessage() == "navigation")
    assert record.http_status == 403  # type: ignore[attr-defined]
    assert "203.0.113.10" not in str(record.__dict__)
