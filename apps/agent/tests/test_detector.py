"""Offline tests for session detection, including the Cloudflare block page.

`cloudflare_blocked.html` is an anonymised copy of the real page returned on
2026-09-30 for every navigation to Cardmarket (see fixtures/cardmarket/README.md).
"""

from pathlib import Path

import pytest
from cmc_shared.enums import ConnectionStatus, ErrorCode

from agent.cardmarket.auth.detector import cloudflare_block_ray_id, detect_session
from agent.cardmarket.parsers.common import parse_html

FIXTURES = Path(__file__).parent / "fixtures" / "cardmarket"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_real_cloudflare_block_page_is_access_blocked() -> None:
    state = detect_session(fixture("cloudflare_blocked.html"))
    assert state.status == ConnectionStatus.ERROR
    assert state.error_code == ErrorCode.ACCESS_BLOCKED
    assert "a43632d17d8bea6f" in (state.message or "")
    assert "session state unknown" in (state.message or "")
    # Neither a session problem nor a challenge to complete.
    assert not state.connected
    assert state.error_code not in (ErrorCode.AUTH_ERROR, ErrorCode.CARDMARKET_CHANGED)


def test_block_message_never_contains_the_requester_ip() -> None:
    message = detect_session(fixture("cloudflare_blocked.html")).message or ""
    assert "203.0.113.10" not in message


def test_authenticated_page() -> None:
    state = detect_session(fixture("order_list.html"))
    assert state.status == ConnectionStatus.CONNECTED and state.error_code is None


def test_login_form() -> None:
    state = detect_session(fixture("login.html"))
    assert (state.status, state.error_code) == (
        ConnectionStatus.SESSION_EXPIRED,
        ErrorCode.AUTH_ERROR,
    )


def test_existing_cloudflare_challenge_stays_a_challenge() -> None:
    state = detect_session(fixture("challenge.html"))
    assert (state.status, state.error_code) == (
        ConnectionStatus.AUTH_REQUIRED,
        ErrorCode.AUTH_ERROR,
    )


def test_unknown_layout_stays_cardmarket_changed() -> None:
    state = detect_session(fixture("unknown_layout.html"))
    assert (state.status, state.error_code) == (
        ConnectionStatus.ERROR,
        ErrorCode.CARDMARKET_CHANGED,
    )


@pytest.mark.parametrize(
    ("name", "html", "expected"),
    [
        (
            "logged-in page mentioning Cloudflare",
            "<html><head><title>Cardmarket</title></head><body>"
            '<a data-testid="account-menu" href="/it/Lorcana/Account">shop</a>'
            "<footer>Performance &amp; security by Cloudflare</footer></body></html>",
            ConnectionStatus.CONNECTED,
        ),
        (
            "block-like title without Cloudflare error container",
            "<html><head><title>Attention Required! | Cloudflare</title></head>"
            "<body><h1>Sorry, you have been blocked</h1></body></html>",
            ConnectionStatus.ERROR,
        ),
        (
            "Cloudflare container without block title or heading",
            '<html><head><title>Oops</title></head><body><div id="cf-wrapper">'
            "<h1>Cloudflare is great</h1></div></body></html>",
            ConnectionStatus.ERROR,
        ),
    ],
)
def test_mentions_of_cloudflare_are_not_a_block(
    name: str, html: str, expected: ConnectionStatus
) -> None:
    state = detect_session(html)
    assert state.error_code != ErrorCode.ACCESS_BLOCKED, name
    assert state.status == expected, name
    assert cloudflare_block_ray_id(parse_html(html)) is None


def test_block_page_without_ray_id_is_still_blocked() -> None:
    html = fixture("cloudflare_blocked.html").replace("a43632d17d8bea6f", "")
    state = detect_session(html)
    assert state.error_code == ErrorCode.ACCESS_BLOCKED
    assert "Ray ID" not in (state.message or "")
