from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from cmc_shared.enums import CartStatus, ConnectionStatus, ErrorCode, MessageDirection, OrderStatus
from cmc_shared.models import NormalizedCartSummary, NormalizedConversationSummary

from agent.cardmarket import selectors
from agent.cardmarket.auth.detector import detect_session
from agent.cardmarket.parsers.carts import parse_cart_detail, parse_cart_list
from agent.cardmarket.parsers.common import map_order_status, parse_datetime, parse_money
from agent.cardmarket.parsers.messages import parse_conversation_list, parse_thread
from agent.cardmarket.parsers.orders import parse_order_detail, parse_order_list
from agent.errors import CardmarketChangedError

FIXTURES = Path(__file__).parent / "fixtures" / "cardmarket"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text()


class TestCommon:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("1.234,56 €", Decimal("1234.56")),
            ("€ 12.50", Decimal("12.50")),
            ("4,2 EUR", Decimal("4.20")),
            ("1,234.00 €", Decimal("1234.00")),
            ("0,25 €", Decimal("0.25")),
        ],
    )
    def test_money(self, raw: str, expected: Decimal) -> None:
        assert parse_money(raw) == (expected, "EUR")

    def test_money_missing(self) -> None:
        assert parse_money(None) == (None, "EUR")
        assert parse_money("n/a")[0] is None

    def test_dates_are_local_time_aware(self) -> None:
        dt = parse_datetime("30.09.26 19:32")
        assert dt is not None and dt.astimezone(UTC) == datetime(2026, 9, 30, 17, 32, tzinfo=UTC)
        assert parse_datetime("2026-09-30T10:00:00+00:00") == datetime(2026, 9, 30, 10, tzinfo=UTC)
        assert parse_datetime("ieri") is None

    @pytest.mark.parametrize(
        ("raw", "status"),
        [
            ("Pagato", OrderStatus.PAID),
            ("  NON PAGATO ", OrderStatus.UNPAID),
            ("Sent", OrderStatus.SHIPPED),
            ("Arrivato", OrderStatus.COMPLETED),
            ("??", OrderStatus.UNKNOWN),
        ],
    )
    def test_status_mapping(self, raw: str, status: OrderStatus) -> None:
        assert map_order_status(raw) == status


class TestOrders:
    def test_list(self) -> None:
        orders, next_href = parse_order_list(fixture("order_list.html"), "u")
        assert [o.cardmarket_id for o in orders] == ["1184201", "1184202"]
        first = orders[0]
        assert first.buyer_name == "mario_rossi"
        assert first.status == OrderStatus.PAID
        assert first.total_amount == Decimal("1234.56")
        assert first.item_count == 3
        assert first.order_date == datetime(2026, 9, 29, 16, 30, tzinfo=UTC)
        assert first.source_url == "/it/Magic/Orders/1184201"
        assert orders[1].status == OrderStatus.UNPAID
        assert next_href == "/it/Magic/Orders/Sales/Paid?site=2"

    def test_detail(self) -> None:
        order = parse_order_detail(fixture("order_detail.html"), "https://x/o/1184201", "1184201")
        assert order.status == OrderStatus.PAID
        assert order.payment_status.value == "PAID"
        assert order.tracking_number is None
        assert [i.card_name for i in order.items] == ["Lightning Bolt", "Thoughtseize"]
        assert order.items[0].quantity == 2 and order.items[0].total_price == Decimal("3.60")
        assert order.item_count == 3
        assert order.paid_at is not None

    def test_detail_for_a_different_order_is_rejected(self) -> None:
        with pytest.raises(CardmarketChangedError, match="expected #999"):
            parse_order_detail(fixture("order_detail.html"), "u", "999")

    def test_unknown_layout(self) -> None:
        with pytest.raises(CardmarketChangedError) as err:
            parse_order_list(fixture("unknown_layout.html"), "u")
        assert err.value.code == ErrorCode.CARDMARKET_CHANGED

    def test_unknown_status_is_not_guessed(self) -> None:
        html = fixture("order_list.html").replace("Pagato", "Stato nuovo")
        with pytest.raises(CardmarketChangedError, match="unknown status"):
            parse_order_list(html, "u")


class TestMessages:
    def test_list(self) -> None:
        threads = parse_conversation_list(fixture("messages_list.html"))
        assert [t.cardmarket_id for t in threads] == ["T7001", "T7002"]
        assert threads[0].unread is True and threads[1].unread is False
        assert threads[0].order_cardmarket_id == "1184201"
        assert threads[1].order_cardmarket_id is None
        assert threads[0].last_message_preview == "Quando spedite?"

    def test_thread(self) -> None:
        summary = NormalizedConversationSummary(cardmarket_id="T7001", buyer_name="mario_rossi")
        convo = parse_thread(fixture("message_thread.html"), summary, "u")
        assert [m.direction for m in convo.messages] == [
            MessageDirection.INBOUND,
            MessageDirection.OUTBOUND,
            MessageDirection.INBOUND,
        ]
        assert convo.messages[1].body == "Spediamo domani mattina."
        assert convo.messages[1].sender == "shop"
        assert convo.messages[0].sender == "mario_rossi"
        assert convo.last_message_preview == "Perfetto, grazie!"

    def test_thread_mismatch_is_rejected(self) -> None:
        summary = NormalizedConversationSummary(cardmarket_id="T9999", buyer_name="x")
        with pytest.raises(CardmarketChangedError, match="expected T9999"):
            parse_thread(fixture("message_thread.html"), summary, "u")


class TestCarts:
    def test_list_and_detail(self) -> None:
        carts = parse_cart_list(fixture("carts_list.html"))
        assert [(c.cardmarket_id, c.status) for c in carts] == [
            ("C50001", CartStatus.TO_PAY),
            ("C50002", CartStatus.PAID),
        ]
        assert carts[0].total_amount == Decimal("32.40") and carts[0].item_count == 5
        detail = parse_cart_detail(
            fixture("cart_detail.html"),
            NormalizedCartSummary(cardmarket_id="C50001", buyer_name="g", status=CartStatus.TO_PAY),
            "u",
        )
        assert detail.items[0].card_name == "Llanowar Elves" and detail.items[
            0
        ].total_price == Decimal("1.00")


class TestSessionDetection:
    def test_states(self) -> None:
        assert detect_session(fixture("order_list.html")).status == ConnectionStatus.CONNECTED
        assert detect_session(fixture("login.html")).status == ConnectionStatus.SESSION_EXPIRED
        challenge = detect_session(fixture("challenge.html"))
        assert challenge.status == ConnectionStatus.AUTH_REQUIRED and "manually" in (
            challenge.message or ""
        )
        unknown = detect_session(fixture("unknown_layout.html"))
        assert (
            unknown.status == ConnectionStatus.ERROR
            and unknown.error_code == ErrorCode.CARDMARKET_CHANGED
        )


class TestRegistry:
    def test_every_write_selector_is_critical_and_unverified_until_calibrated(self) -> None:
        critical = selectors.critical_unverified()
        assert "messages.send_button" in critical and "orders.ship_confirm" in critical

    def test_no_fragile_selectors(self) -> None:
        for spec in selectors.REGISTRY.values():
            for strategy in spec.strategies:
                assert "nth-child" not in strategy.value, spec.key
                assert strategy.kind != selectors.Kind.XPATH, (
                    f"{spec.key}: prefer semantic selectors"
                )
