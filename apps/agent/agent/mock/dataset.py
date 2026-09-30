"""Deterministic, realistic fake marketplace data for MOCK_CARDMARKET=true."""

import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

CARDS: list[tuple[str, str, Decimal]] = [
    ("Lightning Bolt", "Magic 2010", Decimal("1.80")),
    ("Counterspell", "Modern Horizons 2", Decimal("0.90")),
    ("Sheoldred, the Apocalypse", "Dominaria United", Decimal("68.00")),
    ("The One Ring", "The Lord of the Rings", Decimal("54.50")),
    ("Ragavan, Nimble Pilferer", "Modern Horizons 2", Decimal("42.00")),
    ("Orcish Bowmasters", "The Lord of the Rings", Decimal("31.00")),
    ("Solitude", "Modern Horizons 2", Decimal("18.90")),
    ("Thoughtseize", "Theros", Decimal("12.40")),
    ("Fatal Push", "Aether Revolt", Decimal("2.20")),
    ("Llanowar Elves", "Dominaria", Decimal("0.25")),
    ("Swords to Plowshares", "Eternal Masters", Decimal("2.60")),
    ("Snapcaster Mage", "Innistrad", Decimal("9.80")),
    ("Brainstorm", "Masters 25", Decimal("0.80")),
    ("Dark Ritual", "Dominaria Remastered", Decimal("0.35")),
    ("Charizard ex", "Obsidian Flames", Decimal("22.00")),
    ("Pikachu", "Base Set 2", Decimal("3.50")),
    ("Blue-Eyes White Dragon", "Legend of Blue Eyes", Decimal("15.00")),
    ("Ash Blossom & Joyous Spring", "Maximum Crisis", Decimal("4.90")),
]
LANGUAGES = ["English", "Italian", "German", "French", "Spanish", "Japanese"]
CONDITIONS = ["MT", "NM", "EX", "GD", "LP"]
BUYERS = [
    "mario_rossi",
    "luca.bianchi",
    "andrea_tcg",
    "giulia89",
    "franz_mtg",
    "kartenhaus",
    "pierre_d",
    "sofia.collect",
    "marco_modern",
    "elena_pkmn",
    "tom_cards",
    "valentina_v",
    "cardshark_it",
    "hans_m",
    "ana_garcia",
]
INBOUND_OPENERS = [
    "Ciao, quando pensi di spedire?",
    "Hai ancora disponibile la copia NM?",
    "Grazie! Arrivato tutto perfetto.",
    "Posso aggiungere un'altra carta all'ordine?",
    "Hi, could you ship with tracking please?",
    "La busta è arrivata un po' rovinata ma le carte sono ok.",
    "Accetti pagamento unico per due ordini?",
    "Buongiorno, ho pagato ora. Grazie!",
]
INBOUND_FOLLOWUPS = [
    "Perfetto, grazie mille!",
    "Ok, aspetto il tracking.",
    "Grazie per la risposta veloce 🙂",
    "Va bene, nessun problema.",
]
OUTBOUND_REPLIES = [
    "Ciao! Spediamo domani mattina.",
    "Certo, spediamo con tracking.",
    "Grazie a te, alla prossima!",
    "Sì, è ancora disponibile.",
]

# Distribution of order statuses in the initial dataset.
ORDER_STATUSES = ["UNPAID"] * 5 + ["PAID"] * 8 + ["SHIPPED"] * 6 + ["COMPLETED"] * 4 + ["CANCELLED"]
CART_STATUSES = ["TO_PAY"] * 5 + ["PAID"] * 4 + ["COMPLETED"] * 3


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat()


def make_items(rng: random.Random, count: int | None = None) -> list[dict[str, Any]]:
    items = []
    for card, expansion, base in rng.sample(CARDS, count or rng.randint(1, 5)):
        qty = rng.choice([1, 1, 1, 2, 4])
        price = (base * Decimal(str(rng.uniform(0.85, 1.2)))).quantize(Decimal("0.01"))
        items.append(
            {
                "card_name": card,
                "expansion": expansion,
                "language": rng.choice(LANGUAGES),
                "condition": rng.choice(CONDITIONS),
                "quantity": qty,
                "unit_price": str(price),
                "total_price": str(price * qty),
            }
        )
    return items


def _total(items: list[dict[str, Any]], shipping: Decimal = Decimal("1.15")) -> str:
    return str(sum(Decimal(i["total_price"]) for i in items) + shipping)


def make_order(rng: random.Random, cm_id: int, status: str, created: datetime) -> dict[str, Any]:
    items = make_items(rng)
    paid_at = (
        created + timedelta(hours=rng.randint(1, 20))
        if status in ("PAID", "SHIPPED", "COMPLETED")
        else None
    )
    shipped_at = (
        paid_at + timedelta(hours=rng.randint(6, 40))
        if paid_at and status in ("SHIPPED", "COMPLETED")
        else None
    )
    return {
        "cardmarket_id": str(cm_id),
        "buyer_name": rng.choice(BUYERS),
        "status": status,
        "order_date": _iso(created),
        "paid_at": _iso(paid_at) if paid_at else None,
        "shipped_at": _iso(shipped_at) if shipped_at else None,
        "tracking_number": f"RR{rng.randint(10**8, 10**9 - 1)}IT"
        if shipped_at and rng.random() < 0.7
        else None,
        "items": items,
        "total_amount": _total(items),
        "currency": "EUR",
    }


def make_cart(rng: random.Random, cm_id: int, status: str, created: datetime) -> dict[str, Any]:
    items = make_items(rng)
    return {
        "cardmarket_id": f"C{cm_id}",
        "buyer_name": rng.choice(BUYERS),
        "status": status,
        "created_at": _iso(created),
        "items": items,
        "total_amount": _total(items, Decimal("0")),
        "currency": "EUR",
    }


def make_conversation(
    rng: random.Random,
    cm_id: int,
    order: dict[str, Any] | None,
    start: datetime,
    msg_seq: list[int],
) -> dict[str, Any]:
    buyer = order["buyer_name"] if order else rng.choice(BUYERS)
    messages = []
    at = start
    msg_seq[0] += 1
    messages.append(
        {
            "cardmarket_id": f"M{msg_seq[0]}",
            "direction": "INBOUND",
            "sender": buyer,
            "body": rng.choice(INBOUND_OPENERS),
            "sent_at": _iso(at),
        }
    )
    for _ in range(rng.randint(0, 3)):
        at += timedelta(minutes=rng.randint(5, 600))
        outbound = messages[-1]["direction"] == "INBOUND"
        msg_seq[0] += 1
        messages.append(
            {
                "cardmarket_id": f"M{msg_seq[0]}",
                "direction": "OUTBOUND" if outbound else "INBOUND",
                "sender": "shop" if outbound else buyer,
                "body": rng.choice(OUTBOUND_REPLIES if outbound else INBOUND_FOLLOWUPS),
                "sent_at": _iso(at),
            }
        )
    return {
        "cardmarket_id": f"T{cm_id}",
        "buyer_name": buyer,
        "order_cardmarket_id": order["cardmarket_id"] if order else None,
        "unread": messages[-1]["direction"] == "INBOUND",
        "messages": messages,
    }


def build_dataset(seed: int, now: datetime | None = None) -> dict[str, Any]:
    rng = random.Random(seed)
    now = now or datetime.now(UTC)
    orders = []
    next_order = 1_184_200
    for index, status in enumerate(ORDER_STATUSES):
        created = now - timedelta(hours=6 + index * 9 + rng.randint(0, 5))
        orders.append(make_order(rng, next_order + index, status, created))
    carts = []
    for index, status in enumerate(CART_STATUSES):
        created = now - timedelta(hours=2 + index * 7 + rng.randint(0, 3))
        carts.append(make_cart(rng, 50_000 + index, status, created))
    msg_seq = [9_000]
    conversations = []
    linked = rng.sample(orders, 9)
    for index in range(12):
        order = linked[index] if index < len(linked) else None
        start = now - timedelta(hours=1 + index * 11 + rng.randint(0, 6))
        conversations.append(make_conversation(rng, 7_000 + index, order, start, msg_seq))
    return {
        "version": 1,
        "authenticated": False,
        "rng_state": rng.randint(0, 2**31),
        "next_order_id": next_order + len(orders),
        "next_cart_id": 50_000 + len(carts),
        "next_thread_id": 7_000 + len(conversations),
        "next_message_id": msg_seq[0] + 1,
        "orders": orders,
        "carts": carts,
        "conversations": conversations,
    }
