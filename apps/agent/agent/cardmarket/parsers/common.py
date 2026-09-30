"""Parsing helpers shared by all Cardmarket parsers.

Parsers work on HTML strings (``page.content()``), which keeps them pure and
unit-testable with fixtures. All selectors come from ``selectors.REGISTRY``.
"""

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from cmc_shared.enums import CartStatus, OrderStatus
from selectolax.lexbor import LexborHTMLParser, LexborNode

from agent.cardmarket import selectors
from agent.errors import CardmarketChangedError

PARSER_VERSION = "1"

Node = LexborNode | LexborHTMLParser

# TODO: VERIFY AGAINST LIVE CARDMARKET - status wording (all languages in use).
ORDER_STATUS_TEXT: dict[str, OrderStatus] = {
    "unpaid": OrderStatus.UNPAID,
    "bought": OrderStatus.UNPAID,
    "non pagato": OrderStatus.UNPAID,
    "acquistato": OrderStatus.UNPAID,
    "paid": OrderStatus.PAID,
    "pagato": OrderStatus.PAID,
    "sent": OrderStatus.SHIPPED,
    "shipped": OrderStatus.SHIPPED,
    "spedito": OrderStatus.SHIPPED,
    "inviato": OrderStatus.SHIPPED,
    "arrived": OrderStatus.COMPLETED,
    "received": OrderStatus.COMPLETED,
    "arrivato": OrderStatus.COMPLETED,
    "ricevuto": OrderStatus.COMPLETED,
    "cancelled": OrderStatus.CANCELLED,
    "canceled": OrderStatus.CANCELLED,
    "annullato": OrderStatus.CANCELLED,
    "cancellato": OrderStatus.CANCELLED,
}

# TODO: VERIFY AGAINST LIVE CARDMARKET
CART_STATUS_TEXT: dict[str, CartStatus] = {
    "to pay": CartStatus.TO_PAY,
    "unpaid": CartStatus.TO_PAY,
    "da pagare": CartStatus.TO_PAY,
    "paid": CartStatus.PAID,
    "pagato": CartStatus.PAID,
    "completed": CartStatus.COMPLETED,
    "completato": CartStatus.COMPLETED,
    "cancelled": CartStatus.CANCELLED,
    "annullato": CartStatus.CANCELLED,
}

_DATE_FORMATS = (
    "%d.%m.%y %H:%M",
    "%d.%m.%Y %H:%M",
    "%d/%m/%Y %H:%M",
    "%d.%m.%Y",
    "%d/%m/%Y",
    "%d.%m.%y",
)


def parse_html(html: str) -> LexborHTMLParser:
    return LexborHTMLParser(html)


def first(node: Node, key: str) -> LexborNode | None:
    """First element matching any CSS strategy of the selector spec."""
    for css in selectors.get(key).css:
        found = node.css_first(css)
        if found is not None:
            return found
    return None


def all_of(node: Node, key: str) -> list[LexborNode]:
    for css in selectors.get(key).css:
        found = node.css(css)
        if found:
            return list(found)
    return []


def text_of(node: Node, key: str) -> str | None:
    found = first(node, key)
    if found is None:
        return None
    value = " ".join(found.text(separator=" ").split())
    return value or None


def attr_of(node: Node, key: str, attribute: str) -> str | None:
    found = first(node, key)
    return found.attributes.get(attribute) if found is not None else None


def matches(node: LexborNode, key: str) -> bool:
    """True if the node itself, or one of its descendants, matches the spec."""
    return any(node.css_matches(c) or node.css_first(c) is not None for c in selectors.get(key).css)


def id_of(node: LexborNode, key: str) -> str | None:
    for attribute in selectors.get(key).id_attrs:
        value = node.attributes.get(attribute)
        if value:
            return value.strip()
    return None


def require_page(tree: Node, key: str, page_name: str) -> None:
    """Refuse to parse a page whose signature is missing (site changed)."""
    if first(tree, key) is None:
        raise CardmarketChangedError(
            f"{page_name}: page signature '{key}' not found (parser v{PARSER_VERSION})"
        )


def require_text(node: Node, key: str, context: str) -> str:
    value = text_of(node, key)
    if not value:
        raise CardmarketChangedError(f"{context}: required field '{key}' missing")
    return value


def parse_money(raw: str | None) -> tuple[Decimal | None, str]:
    """'1.234,56 €' / '€ 12.50' / '12,50 EUR' -> (Decimal, currency)."""
    if not raw:
        return None, "EUR"
    currency = "EUR"
    if "£" in raw or "GBP" in raw:
        currency = "GBP"
    elif "CHF" in raw:
        currency = "CHF"
    digits = re.sub(r"[^\d,.\-]", "", raw)
    if not digits:
        return None, currency
    if "," in digits and "." in digits:
        # the right-most separator is the decimal one
        if digits.rfind(",") > digits.rfind("."):
            digits = digits.replace(".", "").replace(",", ".")
        else:
            digits = digits.replace(",", "")
    elif "," in digits:
        digits = digits.replace(",", ".")
    try:
        return Decimal(digits).quantize(Decimal("0.01")), currency
    except InvalidOperation:
        return None, currency


def parse_int(raw: str | None) -> int | None:
    if not raw:
        return None
    match = re.search(r"\d+", raw)
    return int(match.group()) if match else None


def parse_datetime(raw: str | None, tz: str = "Europe/Rome") -> datetime | None:
    """Parse Cardmarket dates (local time) or ISO strings into aware datetimes."""
    if not raw:
        return None
    raw = raw.strip()
    try:
        parsed = datetime.fromisoformat(raw)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=ZoneInfo(tz))
    except ValueError:
        pass
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=ZoneInfo(tz))
        except ValueError:
            continue
    return None


def node_datetime(node: Node, key: str) -> datetime | None:
    found = first(node, key)
    if found is None:
        return None
    # Prefer machine-readable attributes when present (<time datetime="...">).
    return parse_datetime(found.attributes.get("datetime") or found.text(strip=True))


def map_order_status(raw: str | None) -> OrderStatus:
    return _map(raw, ORDER_STATUS_TEXT, OrderStatus.UNKNOWN)


def map_cart_status(raw: str | None) -> CartStatus:
    return _map(raw, CART_STATUS_TEXT, CartStatus.UNKNOWN)


def _map[T](raw: str | None, table: dict[str, T], default: T) -> T:
    if not raw:
        return default
    key = " ".join(raw.lower().split())
    if key in table:
        return table[key]
    for label, status in table.items():
        if re.search(rf"\b{re.escape(label)}\b", key):
            return status
    return default
