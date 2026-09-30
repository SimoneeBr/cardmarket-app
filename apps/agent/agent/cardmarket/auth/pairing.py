"""Manual pairing: a human logs in (and completes 2FA) in the agent's browser.

The agent NEVER types credentials, never solves CAPTCHAs and never handles 2FA
codes. It only opens the login page in a *headed* browser (visible through the
noVNC viewer in Docker, or directly on a desktop) and polls until the page
shows a logged-in state, then keeps the session in the persistent profile.
"""

import asyncio
import logging
import time

from cmc_shared.enums import ConnectionStatus, ErrorCode

from agent.adapter import SessionState
from agent.cardmarket.auth.detector import detect_session
from agent.cardmarket.browser.session import BrowserSession
from agent.cardmarket.urls import CardmarketUrls
from agent.errors import AgentError

log = logging.getLogger("cmc.agent.pairing")

POLL_SECONDS = 3.0


async def run_pairing(
    browser: BrowserSession, urls: CardmarketUrls, timeout_seconds: int
) -> SessionState:
    was_headless = browser.headless
    if was_headless:
        await browser.restart(headless=False)  # a human must see the page
    try:
        await browser.goto(urls.login)
        log.info("pairing: waiting for a human to log in", extra={"timeout_s": timeout_seconds})
        deadline = time.monotonic() + timeout_seconds
        state = SessionState(ConnectionStatus.CONNECTING)
        while time.monotonic() < deadline:
            await asyncio.sleep(POLL_SECONDS)
            try:
                state = detect_session(await browser.content())
            except AgentError as exc:
                log.debug("pairing poll failed: %s", exc.message)
                continue
            if state.connected:
                # Re-check on a normal page so the result does not depend on a redirect.
                state = detect_session(await browser.goto(urls.home))
                if state.connected:
                    log.info("pairing completed")
                    return state
        return SessionState(
            ConnectionStatus.AUTH_REQUIRED,
            f"pairing timed out after {timeout_seconds}s (last state: {state.status})",
            ErrorCode.AUTH_ERROR,
        )
    finally:
        if was_headless:
            await browser.restart(headless=True)
