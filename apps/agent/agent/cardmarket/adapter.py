"""Live Cardmarket adapter (Playwright + Chromium, persistent profile)."""

import logging

from cmc_shared.enums import ConnectionStatus, ErrorCode
from cmc_shared.models import (
    NormalizedCart,
    NormalizedCartSummary,
    NormalizedConversation,
    NormalizedConversationSummary,
    NormalizedOrder,
    NormalizedOrderSummary,
)
from cmc_shared.protocol import AgentCommand

from agent.adapter import SendReceipt, SessionState
from agent.cardmarket.actions import writes
from agent.cardmarket.auth.detector import detect_session
from agent.cardmarket.auth.pairing import run_pairing
from agent.cardmarket.browser.session import BrowserSession
from agent.cardmarket.carts.reader import CartsReader
from agent.cardmarket.messages.reader import MessagesReader
from agent.cardmarket.orders.reader import OrdersReader
from agent.cardmarket.parsers.messages import parse_thread
from agent.cardmarket.parsers.orders import parse_order_detail
from agent.cardmarket.urls import CardmarketUrls
from agent.config import AgentSettings
from agent.errors import AccessBlockedError, AuthRequiredError

log = logging.getLogger("cmc.agent.live")

_AUTH_LOST = (ConnectionStatus.SESSION_EXPIRED, ConnectionStatus.AUTH_REQUIRED)


class PlaywrightCardmarketAdapter:
    name = "playwright"

    def __init__(
        self,
        settings: AgentSettings,
        browser: BrowserSession | None = None,
        urls: CardmarketUrls | None = None,
    ) -> None:
        self.settings = settings
        self.browser = browser or BrowserSession(settings)
        self.urls = urls or CardmarketUrls.from_settings(settings)
        self.orders = OrdersReader(self._load, self.urls, settings.max_list_pages)
        self.messages = MessagesReader(self._load, self.urls)
        self.carts = CartsReader(self._load, self.urls)

    async def start(self) -> None:
        await self.browser.start()

    async def close(self) -> None:
        await self.browser.close()

    async def _load(self, url: str) -> str:
        """Navigate; abort immediately if Cardmarket asks to log in again."""
        html = await self.browser.goto(url)
        state = detect_session(html)
        if state.error_code == ErrorCode.ACCESS_BLOCKED:
            artifacts = await self.browser.capture_failure("access-blocked")
            raise AccessBlockedError(state.message or "access blocked", artifacts=artifacts)
        if state.status in _AUTH_LOST:
            artifacts = await self.browser.capture_failure("auth-required")
            raise AuthRequiredError(state.message or "authentication required", artifacts=artifacts)
        return html

    # --------------------------------------------------------------- session

    async def check_session(self) -> SessionState:
        return detect_session(await self.browser.goto(self.urls.home))

    async def pair(self, timeout_seconds: int) -> SessionState:
        return await run_pairing(self.browser, self.urls, timeout_seconds)

    async def disconnect(self) -> None:
        # The profile is kept on purpose: "disconnect" only stops the agent from
        # using the session. Delete the profile volume to forget it entirely.
        log.info("disconnect requested; browser profile kept")

    # ----------------------------------------------------------------- reads

    async def list_orders(self) -> list[NormalizedOrderSummary]:
        return await self.orders.list()

    async def get_order(self, summary: NormalizedOrderSummary) -> NormalizedOrder:
        return await self.orders.detail(summary)

    async def list_conversations(self) -> list[NormalizedConversationSummary]:
        return await self.messages.list()

    async def get_conversation(
        self, summary: NormalizedConversationSummary
    ) -> NormalizedConversation:
        return await self.messages.thread(summary)

    async def list_carts(self) -> list[NormalizedCartSummary]:
        return await self.carts.list()

    async def get_cart(self, summary: NormalizedCartSummary) -> NormalizedCart:
        return await self.carts.detail(summary)

    # ---------------------------------------------------------------- writes

    async def submit_message(
        self, conversation: NormalizedConversationSummary, body: str
    ) -> SendReceipt:
        # Open the thread and re-check it is the intended one right before acting.
        url = self.messages.thread_url(conversation)
        parse_thread(await self._load(url), conversation, url)  # raises if not the right thread
        return await writes.send_message(self.browser, body)

    async def submit_mark_shipped(
        self, order: NormalizedOrderSummary, tracking_number: str | None
    ) -> None:
        url = self.orders.detail_url(order)
        parse_order_detail(await self._load(url), url, order.cardmarket_id)  # right order?
        await writes.mark_shipped(self.browser, tracking_number)

    # ------------------------------------------------------------ diagnostics

    async def capture_failure(self, label: str) -> list[str]:
        return await self.browser.capture_failure(label)

    async def handle_command(self, command: AgentCommand) -> None:
        log.info("command ignored by live adapter", extra={"command": str(command.type)})
