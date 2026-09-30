"""Conversation list / thread parsers."""

from cmc_shared.enums import MessageDirection
from cmc_shared.models import (
    NormalizedConversation,
    NormalizedConversationSummary,
    NormalizedMessage,
)

from agent.cardmarket.parsers.common import (
    all_of,
    attr_of,
    first,
    id_of,
    matches,
    node_datetime,
    parse_html,
    require_page,
    require_text,
    text_of,
)
from agent.errors import CardmarketChangedError


def parse_conversation_list(html: str) -> list[NormalizedConversationSummary]:
    tree = parse_html(html)
    require_page(tree, "messages.list_page", "messages list")
    out = []
    for row in all_of(tree, "messages.thread_row"):
        thread_id = id_of(row, "messages.thread_row")
        if not thread_id:
            raise CardmarketChangedError("conversation row without id")
        order_ref = text_of(row, "messages.thread_order")
        out.append(
            NormalizedConversationSummary(
                cardmarket_id=thread_id,
                buyer_name=require_text(row, "messages.thread_partner", f"thread {thread_id}"),
                order_cardmarket_id=order_ref.lstrip("#") if order_ref else None,
                unread=matches(row, "messages.thread_unread"),
                last_message_at=node_datetime(row, "messages.thread_date"),
                last_message_preview=text_of(row, "messages.thread_preview"),
                source_url=attr_of(row, "messages.thread_link", "href"),
            )
        )
    return out


def parse_thread(
    html: str, summary: NormalizedConversationSummary, url: str
) -> NormalizedConversation:
    tree = parse_html(html)
    require_page(tree, "messages.thread_page", "message thread")
    partner = require_text(
        tree, "messages.thread_header_partner", f"thread {summary.cardmarket_id}"
    )
    page_node = first(tree, "messages.thread_page")
    page_thread = id_of(page_node, "messages.thread_page") if page_node is not None else None
    if page_thread and page_thread != summary.cardmarket_id:
        raise CardmarketChangedError(
            f"thread page is {page_thread}, expected {summary.cardmarket_id}"
        )
    messages = []
    for node in all_of(tree, "messages.message"):
        body = text_of(node, "messages.message_body")
        if body is None:
            raise CardmarketChangedError(f"thread {summary.cardmarket_id}: message without body")
        outbound = matches(node, "messages.message_outbound_marker")
        messages.append(
            NormalizedMessage(
                cardmarket_id=id_of(node, "messages.message"),
                direction=MessageDirection.OUTBOUND if outbound else MessageDirection.INBOUND,
                sender="shop" if outbound else partner,
                body=body,
                sent_at=node_datetime(node, "messages.message_date"),
            )
        )
    last = messages[-1] if messages else None
    return NormalizedConversation(
        cardmarket_id=summary.cardmarket_id,
        buyer_name=partner,
        order_cardmarket_id=summary.order_cardmarket_id,
        unread=summary.unread,
        last_message_at=(last.sent_at if last else None) or summary.last_message_at,
        last_message_preview=(last.body[:140] if last else summary.last_message_preview),
        source_url=url,
        messages=messages,
    )
