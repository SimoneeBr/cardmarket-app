"""Shopping cart list / detail parsers."""

from cmc_shared.enums import CartStatus
from cmc_shared.models import NormalizedCart, NormalizedCartSummary, NormalizedItem

from agent.cardmarket.parsers.common import (
    all_of,
    attr_of,
    id_of,
    map_cart_status,
    node_datetime,
    parse_html,
    parse_int,
    parse_money,
    require_page,
    require_text,
    text_of,
)
from agent.errors import CardmarketChangedError


def parse_cart_list(html: str) -> list[NormalizedCartSummary]:
    tree = parse_html(html)
    require_page(tree, "carts.list_page", "carts list")
    out = []
    for row in all_of(tree, "carts.row"):
        cart_id = id_of(row, "carts.row")
        if not cart_id:
            raise CardmarketChangedError("cart row without id")
        status_text = text_of(row, "carts.row_status")
        status = map_cart_status(status_text)
        if status == CartStatus.UNKNOWN:
            raise CardmarketChangedError(f"cart {cart_id}: unknown status '{status_text}'")
        total, currency = parse_money(text_of(row, "carts.row_total"))
        out.append(
            NormalizedCartSummary(
                cardmarket_id=cart_id,
                buyer_name=require_text(row, "carts.row_buyer", f"cart {cart_id}"),
                status=status,
                total_amount=total,
                currency=currency,
                item_count=parse_int(text_of(row, "carts.row_items")),
                created_at=node_datetime(row, "carts.row_date"),
                source_url=attr_of(row, "carts.row_link", "href"),
            )
        )
    return out


def parse_cart_detail(html: str, summary: NormalizedCartSummary, url: str) -> NormalizedCart:
    tree = parse_html(html)
    require_page(tree, "carts.detail_page", "cart detail")
    items = []
    for row in all_of(tree, "orders.item_row"):  # same article table as orders
        name = text_of(row, "orders.item_name")
        if not name:
            raise CardmarketChangedError(f"cart {summary.cardmarket_id}: article without name")
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
    return NormalizedCart(**{**summary.model_dump(), "source_url": url}, items=items)
