"""Real Playwright + Chromium against a local fake Cardmarket site.

These tests exercise the live adapter end to end (navigation, parsing,
session detection, safety guard, write + verification, artifacts, persistent
profile) without touching the real Cardmarket.
"""

import dataclasses
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from cmc_shared.enums import ActionOutcome, ActionType, ConnectionStatus, ErrorCode, OrderStatus
from cmc_shared.models import NormalizedConversationSummary
from cmc_shared.protocol import ClaimedAction

from agent.actions import ActionExecutor
from agent.adapter import SessionState
from agent.cardmarket import selectors
from agent.cardmarket.actions.writes import SEND_KEYS, SHIP_KEYS
from agent.cardmarket.adapter import PlaywrightCardmarketAdapter
from agent.cardmarket.urls import CardmarketUrls
from agent.config import AgentSettings
from agent.errors import AuthRequiredError
from tests.conftest import send_action
from tests.fake_site import FakeSite

pytestmark = pytest.mark.browser


@pytest.fixture
def site() -> Iterator[FakeSite]:
    with FakeSite() as s:
        yield s


@pytest.fixture
async def live(
    settings: AgentSettings, site: FakeSite
) -> AsyncIterator[PlaywrightCardmarketAdapter]:
    live_settings = settings.model_copy(update={"mock_cardmarket": False, "max_list_pages": 1})
    adapter = PlaywrightCardmarketAdapter(
        live_settings, urls=CardmarketUrls(site.base_url, "it", "Magic")
    )
    await adapter.start()
    yield adapter
    await adapter.close()


@pytest.fixture
def verified(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pretend the write selectors were calibrated against the live site."""
    for key in (*SEND_KEYS, *SHIP_KEYS):
        monkeypatch.setitem(
            selectors.REGISTRY, key, dataclasses.replace(selectors.REGISTRY[key], verified=True)
        )


def executor(
    adapter: PlaywrightCardmarketAdapter, reports: list[SessionState] | None = None
) -> ActionExecutor:
    async def report(state: SessionState) -> None:
        if reports is not None:
            reports.append(state)

    return ActionExecutor(adapter, report, pairing_timeout=20)


THREAD = ("T7001", "mario_rossi")


async def test_reads_normalized_data(live: PlaywrightCardmarketAdapter) -> None:
    assert (await live.check_session()).status == ConnectionStatus.CONNECTED
    orders = await live.list_orders()
    assert {o.cardmarket_id: o.status for o in orders} == {
        "1184201": OrderStatus.PAID,
        "1184202": OrderStatus.UNPAID,
        "1184190": OrderStatus.SHIPPED,
    }
    detail = await live.get_order(next(o for o in orders if o.cardmarket_id == "1184201"))
    assert detail.buyer_name == "mario_rossi" and detail.items[0].card_name == "Lightning Bolt"
    threads = await live.list_conversations()
    assert threads[0].cardmarket_id == "T7001" and threads[0].order_cardmarket_id == "1184201"
    thread = await live.get_conversation(threads[0])
    assert thread.messages[0].body == "Quando pensi di spedire?"
    carts = await live.list_carts()
    assert carts[0].cardmarket_id == "C1"


async def test_unverified_selectors_block_writes(
    live: PlaywrightCardmarketAdapter, site: FakeSite
) -> None:
    result = await executor(live).execute(send_action(1, *THREAD, "Spediamo domani"))
    assert result.outcome == ActionOutcome.UNSAFE
    assert "not verified" in (result.error_message or "")
    assert site.state.posts == []  # nothing was sent
    assert result.artifacts and result.artifacts[0].endswith(".png")


async def test_send_message_executes_and_verifies(
    live: PlaywrightCardmarketAdapter, site: FakeSite, verified: None
) -> None:
    result = await executor(live).execute(send_action(1, *THREAD, "Spediamo domani mattina"))
    assert result.outcome == ActionOutcome.SUCCESS, result
    assert result.result["cardmarket_message_id"] == "M9101"
    assert [p["message"] for p in site.state.posts] == ["Spediamo domani mattina"]


async def test_ambiguous_ui_is_never_clicked(
    live: PlaywrightCardmarketAdapter, site: FakeSite, verified: None
) -> None:
    site.state.duplicate_send_button = True
    result = await executor(live).execute(send_action(1, *THREAD, "ciao"))
    assert result.outcome == ActionOutcome.UNSAFE and "ambiguous" in (result.error_message or "")
    assert site.state.posts == []


async def test_unverifiable_send_is_not_success(
    live: PlaywrightCardmarketAdapter, site: FakeSite, verified: None
) -> None:
    site.state.swallow_messages = True
    result = await executor(live).execute(send_action(1, *THREAD, "sparisce"))
    assert result.outcome == ActionOutcome.UNVERIFIED
    assert result.error_code == ErrorCode.VERIFICATION_FAILED
    assert len(site.state.posts) == 1


async def test_wrong_conversation_is_refused(
    live: PlaywrightCardmarketAdapter, site: FakeSite, verified: None
) -> None:
    result = await executor(live).execute(send_action(1, "T7001", "someone_else", "ciao"))
    assert result.outcome == ActionOutcome.UNSAFE
    assert site.state.posts == []


async def test_mark_shipped_with_tracking(
    live: PlaywrightCardmarketAdapter, site: FakeSite, verified: None
) -> None:
    action = ClaimedAction(
        id=3,
        type=ActionType.MARK_ORDER_SHIPPED,
        payload={
            "order_cardmarket_id": "1184201",
            "buyer_name": "mario_rossi",
            "tracking_number": "RR999IT",
        },
        attempts=1,
        idempotency_key="s",
    )
    result = await executor(live).execute(action)
    assert result.outcome == ActionOutcome.SUCCESS, result
    assert site.state.orders["1184201"] == {
        **site.state.orders["1184201"],
        "status": "Spedito",
        "tracking": "RR999IT",
    }


async def test_session_expiry_detected_with_screenshot(
    live: PlaywrightCardmarketAdapter, site: FakeSite, settings: AgentSettings
) -> None:
    site.state.logged_in = False
    assert (await live.check_session()).status == ConnectionStatus.SESSION_EXPIRED
    with pytest.raises(AuthRequiredError) as err:
        await live.list_orders()
    assert err.value.artifacts
    assert (Path(settings.artifacts_dir) / err.value.artifacts[0]).exists()


async def test_pairing_waits_for_human_login(
    live: PlaywrightCardmarketAdapter, site: FakeSite, monkeypatch: pytest.MonkeyPatch
) -> None:
    site.state.logged_in = False
    site.state.login_after_polls = 3  # the "human" logs in after a few polls

    async def stay_headless(*, headless: bool) -> None:  # CI has no display
        return None

    monkeypatch.setattr(live.browser, "restart", stay_headless)
    monkeypatch.setattr("agent.cardmarket.auth.pairing.POLL_SECONDS", 0.05)

    async def refresh_polls() -> str:
        # Each poll re-reads the page, as if the human was clicking through the login.
        await live.browser.page.goto(live.urls.login)
        return await live.browser.page.content()

    monkeypatch.setattr(live.browser, "content", refresh_polls)
    state = await live.pair(timeout_seconds=10)
    assert state.status == ConnectionStatus.CONNECTED


async def test_profile_persists_session_across_restarts(
    settings: AgentSettings, site: FakeSite
) -> None:
    live_settings = settings.model_copy(update={"mock_cardmarket": False})
    urls = CardmarketUrls(site.base_url, "it", "Magic")
    first = PlaywrightCardmarketAdapter(live_settings, urls=urls)
    await first.start()
    await first.check_session()  # site sets a session cookie
    await first.close()
    second = PlaywrightCardmarketAdapter(live_settings, urls=urls)
    await second.start()
    cookies = await second.browser.page.context.cookies()
    await second.close()
    assert any(c["name"] == "cm_session" for c in cookies)
    assert Path(settings.browser_profile_dir).stat().st_mode & 0o077 == 0  # noqa: ASYNC240


async def test_recovered_action_with_live_adapter_does_not_resend(
    live: PlaywrightCardmarketAdapter, site: FakeSite, verified: None
) -> None:
    # First attempt sent the message, then the agent "crashed" before reporting.
    await live.submit_message(
        NormalizedConversationSummary(cardmarket_id="T7001", buyer_name="mario_rossi"),
        "già inviato",
    )
    assert len(site.state.posts) == 1
    result = await executor(live).execute(
        send_action(
            9, *THREAD, "già inviato", recovery=True, requested_at="2026-09-30T08:59:00+00:00"
        )
    )
    assert result.outcome == ActionOutcome.SUCCESS and result.result["recovered"] is True
    assert len(site.state.posts) == 1
