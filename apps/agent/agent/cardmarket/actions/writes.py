"""Primitive write interactions on Cardmarket pages.

Contract (see ``agent.actions``): raise only if NOTHING was submitted. Once
the final click happened, return normally and let the executor verify.
"""

import logging

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Locator

from agent.adapter import SendReceipt
from agent.cardmarket import selectors
from agent.cardmarket.actions.guard import require_verified, resolve_unique
from agent.cardmarket.browser.session import BrowserSession
from agent.errors import UnsafeUIError

log = logging.getLogger("cmc.agent.writes")

SEND_KEYS = ("messages.compose_input", "messages.send_button")
SHIP_KEYS = ("orders.ship_button", "orders.tracking_input", "orders.ship_confirm")


async def send_message(browser: BrowserSession, body: str) -> SendReceipt:
    """Type and send ``body`` in the currently open (and already checked) thread."""
    require_verified(*SEND_KEYS)
    page = browser.page
    compose = await resolve_unique(page, selectors.get("messages.compose_input"))
    send = await resolve_unique(page, selectors.get("messages.send_button"))
    await compose.fill(body)
    if (await compose.input_value()).strip() != body.strip():
        raise UnsafeUIError("composer did not accept the text as typed")
    await _final_click(send, "send")
    return SendReceipt(submitted=True)


async def mark_shipped(browser: BrowserSession, tracking_number: str | None) -> None:
    """Confirm shipment on the currently open (and already checked) order page."""
    require_verified(*SHIP_KEYS)
    page = browser.page
    await (await resolve_unique(page, selectors.get("orders.ship_button"))).click()
    if tracking_number:
        field = await resolve_unique(page, selectors.get("orders.tracking_input"))
        await field.fill(tracking_number)
    confirm = await resolve_unique(page, selectors.get("orders.ship_confirm"))
    await _final_click(confirm, "confirm shipping")


async def _final_click(target: Locator, what: str) -> None:
    """Point of no return: from here on NOTHING may raise, because a raised
    error would be read as "not submitted" and could lead to a double send."""
    try:
        await target.click()
        await target.page.wait_for_load_state("domcontentloaded")
    except PlaywrightError:
        log.warning("%s click raised; outcome will be verified", what, exc_info=True)
