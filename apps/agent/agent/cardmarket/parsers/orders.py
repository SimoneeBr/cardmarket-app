"""Order list / detail parsers."""

from cmc_shared.enums import OrderStatus
from cmc_shared.models import NormalizedItem, NormalizedOrder, NormalizedOrderSummary
from cmc_shared.status_mapping import derive_payment_status, derive_shipping_status
from selectolax.lexbor import LexborNode

from agent.cardmarket.parsers.common import (
    all_of,
    attr_of,
    first,
    id_of,
    map_order_status,
    node_datetime,
    parse_html,
    parse_int,
    parse_money,
    require_page,
    require_text,
    text_of,
)
from agent.errors import CardmarketChangedError


def _order_id(row: LexborNode) -> str:
    value = id_of(row, "orders.list_row") or text_of(row, "orders.row_id")
    if not value:
        raise CardmarketChangedError("order row without id")
    return value.lstrip("#").strip()


def parse_order_list(html: str, page_url: str) -> tuple[list[NormalizedOrderSummary], str | None]:
    """Return (summaries, next page href)."""
    tree = parse_html(html)
    require_page(tree, "orders.list_page", "order list")
    summaries = []
    for row in all_of(tree, "orders.list_row"):
        cm_id = _order_id(row)
        status_text = text_of(row, "orders.row_status")
        status = map_order_status(status_text)
        if status == OrderStatus.UNKNOWN:
            raise CardmarketChangedError(f"order {cm_id}: unknown status '{status_text}'")
        total, currency = parse_money(text_of(row, "orders.row_total"))
        summaries.append(
            NormalizedOrderSummary(
                cardmarket_id=cm_id,
                buyer_name=require_text(row, "orders.row_buyer", f"order {cm_id}"),
                status=status,
                total_amount=total,
                currency=currency,
                item_count=parse_int(text_of(row, "orders.row_items")),
                order_date=node_datetime(row, "orders.row_date"),
                source_url=attr_of(row, "orders.row_link", "href"),
            )
        )
    next_href = attr_of(tree, "orders.next_page", "href")
    return summaries, next_href


def parse_order_detail(html: str, url: str, expected_id: str) -> NormalizedOrder:
    tree = parse_html(html)
    require_page(tree, "orders.detail_page", "order detail")
    cm_id = require_text(tree, "orders.detail_id", "order detail").lstrip("#").strip()
    if cm_id != expected_id:
        # Never attribute data (or later an action) to the wrong order.
        raise CardmarketChangedError(f"order detail shows #{cm_id}, expected #{expected_id}")
    status_text = text_of(tree, "orders.detail_status")
    status = map_order_status(status_text)
    if status == OrderStatus.UNKNOWN:
        raise CardmarketChangedError(f"order {cm_id}: unknown status '{status_text}'")
    total, currency = parse_money(text_of(tree, "orders.detail_total"))

    items = []
    for row in all_of(tree, "orders.item_row"):
        name = text_of(row, "orders.item_name")
        if not name:
            raise CardmarketChangedError(f"order {cm_id}: article without name")
        quantity = parse_int(text_of(row, "orders.item_quantity")) or 1
        unit, _ = parse_money(text_of(row, "orders.item_price"))
        items.append(
            NormalizedItem(
                card_name=name,
                expansion=text_of(row, "orders.item_expansion"),
                language=text_of(row, "orders.item_language"),
                condition=text_of(row, "orders.item_condition"),
                quantity=quantity,
                unit_price=unit,
                total_price=unit * quantity if unit is not None else None,
            )
        )
    tracking = text_of(tree, "orders.detail_tracking")
    return NormalizedOrder(
        cardmarket_id=cm_id,
        buyer_name=require_text(tree, "orders.detail_buyer", f"order {cm_id}"),
        status=status,
        total_amount=total,
        currency=currency,
        item_count=sum(i.quantity for i in items) if items else None,
        order_date=node_datetime(tree, "orders.detail_date"),
        source_url=url,
        payment_status=derive_payment_status(status),
        shipping_status=derive_shipping_status(status),
        paid_at=node_datetime(tree, "orders.detail_paid_at"),
        shipped_at=node_datetime(tree, "orders.detail_shipped_at"),
        tracking_number=tracking if tracking and tracking != "-" else None,
        items=items,
        extra={
            "parser_version": "1",
            "has_ship_button": first(tree, "orders.ship_button") is not None,
        },
    )
