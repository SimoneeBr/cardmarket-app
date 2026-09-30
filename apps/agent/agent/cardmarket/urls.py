"""Cardmarket URL builders.

TODO: VERIFY AGAINST LIVE CARDMARKET
    The paths below follow the publicly visible URL scheme
    ``/{language}/{game}/...`` but the exact seller pages (sales by status,
    messages, shopping carts) have not been verified with a logged-in session.
    Adjust them here only; nothing else builds Cardmarket URLs.
"""

from dataclasses import dataclass
from urllib.parse import urljoin

from agent.config import AgentSettings

# Order list pages to scan, keyed by the status they are expected to contain.
# TODO: VERIFY AGAINST LIVE CARDMARKET - status segment names.
ORDER_LIST_SEGMENTS: tuple[str, ...] = (
    "Orders/Sales/Unpaid",
    "Orders/Sales/Paid",
    "Orders/Sales/Sent",
    "Orders/Sales/Arrived",
)


@dataclass(frozen=True)
class CardmarketUrls:
    base: str
    language: str
    game: str

    @classmethod
    def from_settings(cls, settings: AgentSettings) -> "CardmarketUrls":
        return cls(
            settings.cardmarket_base_url.rstrip("/"),
            settings.cardmarket_language,
            settings.cardmarket_game,
        )

    def _url(self, path: str) -> str:
        return f"{self.base}/{self.language}/{self.game}/{path.lstrip('/')}"

    @property
    def home(self) -> str:
        return self._url("")

    @property
    def login(self) -> str:
        # TODO: VERIFY AGAINST LIVE CARDMARKET - dedicated login page path.
        return self._url("Login")

    @property
    def order_lists(self) -> list[str]:
        return [self._url(segment) for segment in ORDER_LIST_SEGMENTS]

    def order_detail(self, order_id: str) -> str:
        # TODO: VERIFY AGAINST LIVE CARDMARKET
        return self._url(f"Orders/{order_id}")

    @property
    def messages(self) -> str:
        # TODO: VERIFY AGAINST LIVE CARDMARKET
        return self._url("Account/Messages")

    def thread(self, thread_id: str) -> str:
        # TODO: VERIFY AGAINST LIVE CARDMARKET
        return self._url(f"Account/Messages/{thread_id}")

    @property
    def carts(self) -> str:
        # TODO: VERIFY AGAINST LIVE CARDMARKET - seller view of buyers' carts.
        return self._url("Orders/Sales/ShoppingCarts")

    def absolute(self, href: str) -> str:
        return urljoin(self.base + "/", href)

    def is_cardmarket(self, url: str) -> bool:
        return url.startswith(self.base)
