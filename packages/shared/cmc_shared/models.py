"""Normalized Cardmarket data model.

The agent's parsers translate Cardmarket pages into these models; the API sync
engine only ever sees these models. Fields that cannot be reliably extracted
must be left ``None`` rather than guessed.
"""

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from cmc_shared.enums import (
    CartStatus,
    MessageDirection,
    OrderStatus,
    PaymentStatus,
    ShippingStatus,
)


class _Normalized(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def _fingerprint(parts: dict[str, Any]) -> str:
    raw = json.dumps(parts, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


class NormalizedItem(_Normalized):
    card_name: str
    expansion: str | None = None
    language: str | None = None
    condition: str | None = None
    quantity: int = Field(ge=0, default=1)
    unit_price: Decimal | None = None
    total_price: Decimal | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class NormalizedOrderSummary(_Normalized):
    """What is visible in an order list row."""

    cardmarket_id: str = Field(min_length=1)
    buyer_name: str
    status: OrderStatus
    total_amount: Decimal | None = None
    currency: str = "EUR"
    item_count: int | None = None
    order_date: datetime | None = None
    source_url: str | None = None

    def fingerprint(self) -> str:
        """Changes whenever a list-level field changes -> detail refetch needed."""
        return _fingerprint(
            {
                "status": self.status,
                "total": self.total_amount,
                "items": self.item_count,
            }
        )


class NormalizedOrder(NormalizedOrderSummary):
    """Full order detail."""

    payment_status: PaymentStatus = PaymentStatus.UNKNOWN
    shipping_status: ShippingStatus = ShippingStatus.UNKNOWN
    paid_at: datetime | None = None
    shipped_at: datetime | None = None
    tracking_number: str | None = None
    items: list[NormalizedItem] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class NormalizedMessage(_Normalized):
    cardmarket_id: str | None = None
    direction: MessageDirection
    sender: str
    body: str
    sent_at: datetime | None = None


class NormalizedConversationSummary(_Normalized):
    cardmarket_id: str = Field(min_length=1)
    buyer_name: str
    order_cardmarket_id: str | None = None
    unread: bool = False
    last_message_at: datetime | None = None
    last_message_preview: str | None = None
    source_url: str | None = None

    def fingerprint(self) -> str:
        return _fingerprint(
            {
                "last": self.last_message_at,
                "unread": self.unread,
                "preview": self.last_message_preview,
            }
        )


class NormalizedConversation(NormalizedConversationSummary):
    messages: list[NormalizedMessage] = Field(default_factory=list)


class NormalizedCartSummary(_Normalized):
    cardmarket_id: str = Field(min_length=1)
    buyer_name: str
    status: CartStatus
    total_amount: Decimal | None = None
    currency: str = "EUR"
    item_count: int | None = None
    created_at: datetime | None = None
    source_url: str | None = None

    def fingerprint(self) -> str:
        return _fingerprint(
            {"status": self.status, "total": self.total_amount, "items": self.item_count}
        )


class NormalizedCart(NormalizedCartSummary):
    items: list[NormalizedItem] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)
