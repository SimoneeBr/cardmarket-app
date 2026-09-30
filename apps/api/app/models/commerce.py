"""Orders, carts and conversations mirrored from Cardmarket."""

from datetime import datetime
from decimal import Decimal
from typing import Any

from cmc_shared.enums import (
    CartStatus,
    MessageDirection,
    MessageStatus,
    OrderStatus,
    PaymentStatus,
    ShippingStatus,
)
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, enum_column

Money = Numeric(12, 2)


class Order(TimestampMixin, Base):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("connection_id", "cardmarket_id"),
        Index("ix_orders_status_date", "status", "order_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("cardmarket_connection.id", ondelete="CASCADE")
    )
    cardmarket_id: Mapped[str] = mapped_column(String(64))
    buyer_name: Mapped[str] = mapped_column(String(120), index=True)
    status: Mapped[OrderStatus] = mapped_column(enum_column(OrderStatus))
    payment_status: Mapped[PaymentStatus] = mapped_column(
        enum_column(PaymentStatus), default=PaymentStatus.UNKNOWN
    )
    shipping_status: Mapped[ShippingStatus] = mapped_column(
        enum_column(ShippingStatus), default=ShippingStatus.UNKNOWN
    )
    total_amount: Mapped[Decimal | None] = mapped_column(Money)
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    item_count: Mapped[int | None] = mapped_column(Integer)
    order_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    shipped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    tracking_number: Mapped[str | None] = mapped_column(String(80))
    raw_source_reference: Mapped[str | None] = mapped_column(String(500))
    fingerprint: Mapped[str | None] = mapped_column(String(32))
    detail_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    extra: Mapped[dict[str, Any]] = mapped_column(default=dict)

    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", order_by="OrderItem.position"
    )

    @property
    def is_new(self) -> bool:
        """Not yet looked at by anyone in the shop."""
        return self.acknowledged_at is None


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    card_name: Mapped[str] = mapped_column(String(255))
    expansion: Mapped[str | None] = mapped_column(String(120))
    language: Mapped[str | None] = mapped_column(String(40))
    condition: Mapped[str | None] = mapped_column(String(40))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    unit_price: Mapped[Decimal | None] = mapped_column(Money)
    total_price: Mapped[Decimal | None] = mapped_column(Money)
    extra: Mapped[dict[str, Any]] = mapped_column(default=dict)

    order: Mapped[Order] = relationship(back_populates="items")


class Conversation(TimestampMixin, Base):
    __tablename__ = "conversations"
    __table_args__ = (UniqueConstraint("connection_id", "cardmarket_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("cardmarket_connection.id", ondelete="CASCADE")
    )
    cardmarket_id: Mapped[str] = mapped_column(String(64))
    buyer_name: Mapped[str] = mapped_column(String(120), index=True)
    order_id: Mapped[int | None] = mapped_column(
        ForeignKey("orders.id", ondelete="SET NULL"), index=True
    )
    # Kept so the link can be resolved later if the order is synced after the chat.
    order_cardmarket_id: Mapped[str | None] = mapped_column(String(64))
    unread: Mapped[bool] = mapped_column(Boolean, default=False)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_message_preview: Mapped[str | None] = mapped_column(String(280))
    raw_source_reference: Mapped[str | None] = mapped_column(String(500))
    fingerprint: Mapped[str | None] = mapped_column(String(32))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    order: Mapped[Order | None] = relationship()
    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by=lambda: (Message.sent_at.asc().nulls_last(), Message.id),
    )


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (UniqueConstraint("conversation_id", "cardmarket_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    cardmarket_id: Mapped[str | None] = mapped_column(String(64))
    direction: Mapped[MessageDirection] = mapped_column(enum_column(MessageDirection))
    sender: Mapped[str] = mapped_column(String(120))
    body: Mapped[str] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[MessageStatus] = mapped_column(enum_column(MessageStatus))
    sent_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action_id: Mapped[int | None] = mapped_column(
        ForeignKey("action_queue.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class Cart(TimestampMixin, Base):
    __tablename__ = "carts"
    __table_args__ = (UniqueConstraint("connection_id", "cardmarket_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("cardmarket_connection.id", ondelete="CASCADE")
    )
    cardmarket_id: Mapped[str] = mapped_column(String(64))
    buyer_name: Mapped[str] = mapped_column(String(120), index=True)
    status: Mapped[CartStatus] = mapped_column(enum_column(CartStatus), index=True)
    total_amount: Mapped[Decimal | None] = mapped_column(Money)
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    item_count: Mapped[int | None] = mapped_column(Integer)
    cardmarket_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw_source_reference: Mapped[str | None] = mapped_column(String(500))
    fingerprint: Mapped[str | None] = mapped_column(String(32))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    extra: Mapped[dict[str, Any]] = mapped_column(default=dict)

    items: Mapped[list["CartItem"]] = relationship(
        back_populates="cart", cascade="all, delete-orphan", order_by="CartItem.position"
    )


class CartItem(Base):
    __tablename__ = "cart_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    cart_id: Mapped[int] = mapped_column(ForeignKey("carts.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    card_name: Mapped[str] = mapped_column(String(255))
    expansion: Mapped[str | None] = mapped_column(String(120))
    language: Mapped[str | None] = mapped_column(String(40))
    condition: Mapped[str | None] = mapped_column(String(40))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    unit_price: Mapped[Decimal | None] = mapped_column(Money)
    total_price: Mapped[Decimal | None] = mapped_column(Money)
    extra: Mapped[dict[str, Any]] = mapped_column(default=dict)

    cart: Mapped[Cart] = relationship(back_populates="items")
