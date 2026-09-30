"""Central registry of every Cardmarket selector. Nothing else in the code base
may contain a Cardmarket CSS/XPath/text selector.

TODO: VERIFY AGAINST LIVE CARDMARKET
    None of these selectors has been verified against the live site yet (the
    pages are behind a login we did not have while writing this). They describe
    the structure the parsers expect and are exercised by the HTML fixtures in
    ``tests/fixtures/cardmarket``. Calibrate them with::

        python -m agent calibrate

    then set ``verified=True`` on the entries you have confirmed.

Safety rules
- Read selectors may be unverified: a mismatch makes the parser raise
  CARDMARKET_CHANGED, which is harmless.
- **Write-action selectors must be ``verified=True``**, otherwise the agent
  refuses to act (NEEDS_ATTENTION). See ``actions/guard.py``.

Strategy preference (first match wins, in order): role/label/text/test-id,
then CSS, then XPath only as last resort. Avoid nth-child, hashed classes and
deep DOM paths.
"""

from dataclasses import dataclass
from enum import StrEnum

# Bump when selectors/parsers change in a way that affects parsed output.
REGISTRY_VERSION = "2026.09.30-unverified"


class Kind(StrEnum):
    ROLE = "role"  # value = ARIA role, name = accessible name (regex allowed)
    LABEL = "label"  # accessible label text
    TEXT = "text"  # visible text
    TEST_ID = "test_id"  # data-* attribute test id
    CSS = "css"
    XPATH = "xpath"


@dataclass(frozen=True)
class Strategy:
    kind: Kind
    value: str
    name: str | None = None  # accessible name for ROLE


@dataclass(frozen=True)
class SelectorSpec:
    key: str
    strategies: tuple[Strategy, ...]
    description: str
    verified: bool = False
    # Critical selectors guard write actions: they must match exactly one element.
    critical: bool = False
    # Attributes (on the matched element) carrying the Cardmarket id, in order.
    id_attrs: tuple[str, ...] = ()

    @property
    def css(self) -> tuple[str, ...]:
        """CSS strategies only (used by the HTML parsers)."""
        return tuple(s.value for s in self.strategies if s.kind == Kind.CSS)


def css(value: str) -> Strategy:
    return Strategy(Kind.CSS, value)


def role(value: str, name: str) -> Strategy:
    return Strategy(Kind.ROLE, value, name)


def text(value: str) -> Strategy:
    return Strategy(Kind.TEXT, value)


def label(value: str) -> Strategy:
    return Strategy(Kind.LABEL, value)


_SPECS: tuple[SelectorSpec, ...] = (
    # --------------------------------------------------------------- session
    SelectorSpec(
        "session.logged_in_marker",
        (css("[data-testid='account-menu']"), css("#account-dropdown"), css("a[href*='/Account']")),
        "Element only present when logged in (account menu / username).",
    ),
    SelectorSpec(
        "session.login_form",
        (
            css("form[action*='Login']"),
            css("input[name='username'] ~ input[type='password']"),
            css("#login-form"),
        ),
        "Login form: its presence means the session is not authenticated.",
    ),
    SelectorSpec(
        "session.challenge",
        (
            css("#challenge-form"),
            css("iframe[src*='challenges.cloudflare.com']"),
            css("[data-sitekey]"),
        ),
        "Bot/CAPTCHA challenge. Never automated: pairing must be done by a human.",
    ),
    SelectorSpec(
        "session.twofa_form",
        (css("input[autocomplete='one-time-code']"), css("form[action*='TwoFactor']")),
        "2FA prompt. Never automated.",
    ),
    # ---------------------------------------------------------------- orders
    SelectorSpec(
        "orders.list_page",
        (css("[data-page='orders-list']"), css("#StatusTable"), css("table.orders-table")),
        "Signature of an order list page.",
    ),
    SelectorSpec(
        "orders.list_row",
        (css("[data-order-id]"), css("tr.order-row")),
        "One order in the list.",
        id_attrs=("data-order-id",),
    ),
    SelectorSpec(
        "orders.row_id", (css("[data-field='order-id']"), css(".order-id")), "Order id cell."
    ),
    SelectorSpec(
        "orders.row_buyer", (css("[data-field='buyer']"), css(".buyer a")), "Buyer username."
    ),
    SelectorSpec(
        "orders.row_status", (css("[data-field='status']"), css(".status")), "Status label."
    ),
    SelectorSpec("orders.row_total", (css("[data-field='total']"), css(".total")), "Total price."),
    SelectorSpec(
        "orders.row_items",
        (css("[data-field='item-count']"), css(".article-count")),
        "Article count.",
    ),
    SelectorSpec("orders.row_date", (css("[data-field='date']"), css(".date")), "Order date."),
    SelectorSpec(
        "orders.row_link",
        (css("a[data-field='detail-link']"), css("a[href*='/Orders/']")),
        "Detail link.",
    ),
    SelectorSpec(
        "orders.next_page", (css("a[rel='next']"), css("a[aria-label='Next page']")), "Pagination."
    ),
    SelectorSpec(
        "orders.detail_page",
        (css("[data-page='order-detail']"), css("#OrderDetail")),
        "Signature of an order detail page.",
    ),
    SelectorSpec(
        "orders.detail_id", (css("[data-field='order-id']"), css("h1 .order-id")), "Order id."
    ),
    SelectorSpec(
        "orders.detail_buyer", (css("[data-field='buyer']"), css(".buyer-info a")), "Buyer."
    ),
    SelectorSpec(
        "orders.detail_status", (css("[data-field='status']"), css(".order-status")), "Status."
    ),
    SelectorSpec(
        "orders.detail_total", (css("[data-field='total']"), css(".order-total")), "Total."
    ),
    SelectorSpec("orders.detail_paid_at", (css("[data-field='paid-at']"),), "Payment timestamp."),
    SelectorSpec(
        "orders.detail_shipped_at", (css("[data-field='shipped-at']"),), "Shipping timestamp."
    ),
    SelectorSpec("orders.detail_date", (css("[data-field='date']"),), "Order date."),
    SelectorSpec("orders.detail_tracking", (css("[data-field='tracking']"),), "Tracking number."),
    SelectorSpec(
        "orders.item_row", (css("[data-article-row]"), css("tr.article-row")), "Article row."
    ),
    SelectorSpec("orders.item_name", (css("[data-field='name']"), css(".name a")), "Card name."),
    SelectorSpec("orders.item_expansion", (css("[data-field='expansion']"),), "Expansion."),
    SelectorSpec("orders.item_language", (css("[data-field='language']"),), "Language."),
    SelectorSpec("orders.item_condition", (css("[data-field='condition']"),), "Condition."),
    SelectorSpec("orders.item_quantity", (css("[data-field='quantity']"),), "Quantity."),
    SelectorSpec("orders.item_price", (css("[data-field='price']"),), "Unit price."),
    # Write: mark as shipped
    SelectorSpec(
        "orders.ship_button",
        (
            role("button", "(?i)^(confirm shipment|mark as sent|segna come spedito)$"),
            css("button[data-action='confirm-shipping']"),
        ),
        "Button that starts 'mark as shipped'.",
        critical=True,
    ),
    SelectorSpec(
        "orders.tracking_input",
        (label("(?i)tracking"), css("input[name='trackingNumber']")),
        "Tracking number input in the shipping dialog.",
        critical=True,
    ),
    SelectorSpec(
        "orders.ship_confirm",
        (
            role("button", "(?i)^(confirm|conferma)$"),
            css("button[data-action='confirm-shipping-submit']"),
        ),
        "Final confirmation of the shipping dialog.",
        critical=True,
    ),
    # --------------------------------------------------------------- messages
    SelectorSpec(
        "messages.list_page",
        (css("[data-page='messages-list']"), css("#MessageThreads")),
        "Signature of the conversations list page.",
    ),
    SelectorSpec(
        "messages.thread_row",
        (css("[data-thread-id]"), css(".thread-row")),
        "One conversation.",
        id_attrs=("data-thread-id",),
    ),
    SelectorSpec(
        "messages.thread_partner",
        (css("[data-field='partner']"), css(".partner")),
        "Buyer username.",
    ),
    SelectorSpec(
        "messages.thread_preview",
        (css("[data-field='preview']"), css(".preview")),
        "Last message preview.",
    ),
    SelectorSpec(
        "messages.thread_date", (css("[data-field='date']"), css(".date")), "Last message date."
    ),
    SelectorSpec(
        "messages.thread_unread", (css("[data-unread='true']"), css(".unread")), "Unread marker."
    ),
    SelectorSpec(
        "messages.thread_order", (css("[data-field='order-ref']"),), "Linked order reference."
    ),
    SelectorSpec(
        "messages.thread_link",
        (css("a[data-field='thread-link']"), css("a[href*='/Messages/']")),
        "Thread link.",
    ),
    SelectorSpec(
        "messages.thread_page",
        (css("[data-page='message-thread']"), css("#MessageThread")),
        "Signature of a conversation page.",
        id_attrs=("data-thread-id",),
    ),
    SelectorSpec(
        "messages.thread_header_partner",
        (css("[data-field='partner']"), css("h1 .partner")),
        "Partner in header.",
    ),
    SelectorSpec(
        "messages.message",
        (css("[data-message-id]"), css(".message")),
        "One message bubble.",
        id_attrs=("data-message-id",),
    ),
    SelectorSpec(
        "messages.message_body", (css("[data-field='body']"), css(".message-body")), "Message text."
    ),
    SelectorSpec(
        "messages.message_date",
        (css("[data-field='date']"), css(".message-date")),
        "Message timestamp.",
    ),
    SelectorSpec(
        "messages.message_outbound_marker",
        (css("[data-direction='outbound']"), css(".message.own")),
        "Own message marker.",
    ),
    # Write: send message
    SelectorSpec(
        "messages.compose_input",
        (label("(?i)^(message|messaggio)$"), css("textarea[name='message']")),
        "Message composer textarea of the open thread.",
        critical=True,
    ),
    SelectorSpec(
        "messages.send_button",
        (role("button", "(?i)^(send|invia)$"), css("button[data-action='send-message']")),
        "Send button of the open thread.",
        critical=True,
    ),
    # ------------------------------------------------------------------ carts
    SelectorSpec(
        "carts.list_page",
        (css("[data-page='carts-list']"), css("#ShoppingCarts")),
        "Signature of the carts list page.",
    ),
    SelectorSpec(
        "carts.row",
        (css("[data-cart-id]"), css(".cart-row")),
        "One cart.",
        id_attrs=("data-cart-id",),
    ),
    SelectorSpec("carts.row_buyer", (css("[data-field='buyer']"),), "Buyer."),
    SelectorSpec("carts.row_status", (css("[data-field='status']"),), "Status."),
    SelectorSpec("carts.row_total", (css("[data-field='total']"),), "Total."),
    SelectorSpec("carts.row_items", (css("[data-field='item-count']"),), "Article count."),
    SelectorSpec("carts.row_date", (css("[data-field='date']"),), "Creation date."),
    SelectorSpec("carts.row_link", (css("a[data-field='detail-link']"),), "Detail link."),
    SelectorSpec(
        "carts.detail_page", (css("[data-page='cart-detail']"),), "Signature of a cart page."
    ),
)

REGISTRY: dict[str, SelectorSpec] = {spec.key: spec for spec in _SPECS}


def get(key: str) -> SelectorSpec:
    try:
        return REGISTRY[key]
    except KeyError as exc:  # programming error, not a site change
        raise KeyError(f"unknown selector key: {key}") from exc


def critical_unverified() -> list[str]:
    return sorted(k for k, s in REGISTRY.items() if s.critical and not s.verified)
