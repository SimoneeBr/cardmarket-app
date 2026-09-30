"""Sync engine: applies normalized snapshots from the agent to the database.

Responsibilities
- per-account sync lease (no two concurrent syncs of the same account);
- idempotent upserts (re-sending the same batch changes nothing);
- change detection -> domain events (OrderCreated, OrderPaid, ...);
- reconciliation of outbound messages sent through the action queue.

The very first successful sync of an account is an *initial import*: events are
recorded for the activity log but produce no notifications (no push storm).
"""

import hashlib
import logging
import secrets
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from cmc_shared.enums import (
    CartStatus,
    DomainEventType,
    EntityType,
    ErrorCode,
    MessageDirection,
    MessageStatus,
    OrderStatus,
    PaymentStatus,
    ShippingStatus,
    SyncEntity,
    SyncRunStatus,
)
from cmc_shared.models import (
    NormalizedCart,
    NormalizedCartSummary,
    NormalizedConversation,
    NormalizedConversationSummary,
    NormalizedItem,
    NormalizedMessage,
    NormalizedOrder,
    NormalizedOrderSummary,
)
from cmc_shared.protocol import CartsBatch, ConversationsBatch, OrdersBatch, SyncBatchResult
from cmc_shared.status_mapping import (
    derive_payment_status,
    derive_shipping_status,
    is_cart_progress,
    is_order_progress,
)
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session, selectinload

from app.config import get_settings
from app.db import utcnow
from app.models import (
    CardmarketConnection,
    Cart,
    CartItem,
    Conversation,
    Message,
    Order,
    OrderItem,
    SyncRun,
)
from app.services import events

log = logging.getLogger("cmc.sync")

# Only fingerprints of records seen recently are sent back to the agent.
_FINGERPRINT_WINDOW = timedelta(days=90)


class SyncLockError(Exception):
    pass


@dataclass
class _Stats:
    found: int = 0
    changed: int = 0
    events: int = 0
    changed_ids: set[str] = field(default_factory=set)

    def mark_changed(self, key: str) -> None:
        self.changed_ids.add(key)

    def result(self) -> SyncBatchResult:
        return SyncBatchResult(
            records_found=self.found, records_changed=len(self.changed_ids), events=self.events
        )


# --------------------------------------------------------------------------- #
# Lease / run lifecycle
# --------------------------------------------------------------------------- #


def acquire_lock(db: Session, conn: CardmarketConnection, owner: str) -> bool:
    now = utcnow()
    ttl = timedelta(seconds=get_settings().sync_lock_ttl_seconds)
    result = db.execute(
        update(CardmarketConnection)
        .where(
            CardmarketConnection.id == conn.id,
            or_(
                CardmarketConnection.sync_lock_owner.is_(None),
                CardmarketConnection.sync_lock_expires_at < now,
                CardmarketConnection.sync_lock_owner == owner,
            ),
        )
        .values(sync_lock_owner=owner, sync_lock_expires_at=now + ttl)
        .execution_options(synchronize_session=False)
    )
    db.refresh(conn)
    return bool(result.rowcount)  # type: ignore[attr-defined]


def release_lock(db: Session, conn: CardmarketConnection, owner: str) -> None:
    db.execute(
        update(CardmarketConnection)
        .where(CardmarketConnection.id == conn.id, CardmarketConnection.sync_lock_owner == owner)
        .values(sync_lock_owner=None, sync_lock_expires_at=None)
        .execution_options(synchronize_session=False)
    )


def start_run(
    db: Session, conn: CardmarketConnection, owner: str, entity: SyncEntity, trigger: str
) -> SyncRun:
    if not acquire_lock(db, conn, owner):
        raise SyncLockError(f"sync already running (owner={conn.sync_lock_owner})")
    # A previous run by the same owner that never completed is closed as failed.
    for stale in db.scalars(
        select(SyncRun).where(
            SyncRun.connection_id == conn.id, SyncRun.status == SyncRunStatus.RUNNING
        )
    ):
        stale.status = SyncRunStatus.FAILED
        stale.completed_at = utcnow()
        stale.error = "interrupted (agent restarted or lease expired)"
        stale.error_code = ErrorCode.UNKNOWN
    run = SyncRun(
        connection_id=conn.id,
        sync_id=secrets.token_hex(6),
        started_at=utcnow(),
        status=SyncRunStatus.RUNNING,
        entity_type=entity,
        trigger=trigger,
        records_found=0,
        records_changed=0,
        artifacts=[],
    )
    db.add(run)
    db.flush()
    return run


def known_fingerprints(db: Session, conn: CardmarketConnection) -> dict[str, dict[str, str]]:
    since = utcnow() - _FINGERPRINT_WINDOW

    def _collect(model: type[Order] | type[Conversation] | type[Cart]) -> dict[str, str]:
        rows = db.execute(
            select(model.cardmarket_id, model.fingerprint).where(
                model.connection_id == conn.id, model.last_seen_at >= since
            )
        ).all()
        return {cm_id: fp for cm_id, fp in rows if fp}

    return {
        "orders": _collect(Order),
        "conversations": _collect(Conversation),
        "carts": _collect(Cart),
    }


def complete_run(
    db: Session,
    conn: CardmarketConnection,
    run: SyncRun,
    status: SyncRunStatus,
    *,
    error_code: ErrorCode | None = None,
    error_message: str | None = None,
    artifacts: list[str] | None = None,
) -> None:
    now = utcnow()
    previous = db.scalar(
        select(SyncRun)
        .where(
            SyncRun.connection_id == conn.id,
            SyncRun.id != run.id,
            SyncRun.status != SyncRunStatus.RUNNING,
        )
        .order_by(SyncRun.id.desc())
        .limit(1)
    )
    run.status = status
    run.completed_at = now
    run.error = error_message
    run.error_code = error_code
    run.artifacts = artifacts or []
    if status in (SyncRunStatus.SUCCESS, SyncRunStatus.PARTIAL):
        conn.last_successful_sync = now
    if status == SyncRunStatus.FAILED:
        conn.last_error = error_message
        conn.last_error_code = error_code or ErrorCode.UNKNOWN
        conn.last_error_at = now
        # Edge-triggered: notify only on the first failure of a streak.
        if previous is None or previous.status != SyncRunStatus.FAILED:
            events.emit(
                db,
                DomainEventType.SYNC_FAILED,
                EntityType.SYNC_RUN,
                run.id,
                {"error_code": str(error_code or ErrorCode.UNKNOWN), "error": error_message},
                sync_run_id=run.id,
            )
    release_lock(db, conn, conn.sync_lock_owner or "")


def is_initial_import(db: Session, conn: CardmarketConnection) -> bool:
    return conn.last_successful_sync is None


# --------------------------------------------------------------------------- #
# Orders
# --------------------------------------------------------------------------- #


def _replace_items[ItemT: (OrderItem, CartItem)](
    target: list[ItemT], items: list[NormalizedItem], factory: type[ItemT]
) -> None:
    target.clear()
    for position, item in enumerate(items):
        target.append(
            factory(
                position=position,
                card_name=item.card_name,
                expansion=item.expansion,
                language=item.language,
                condition=item.condition,
                quantity=item.quantity,
                unit_price=item.unit_price,
                total_price=item.total_price,
                extra=dict(item.extra),
            )
        )


def _order_payload(order: Order) -> dict[str, Any]:
    return {
        "cardmarket_id": order.cardmarket_id,
        "buyer_name": order.buyer_name,
        "total_amount": str(order.total_amount) if order.total_amount is not None else None,
        "currency": order.currency,
        "status": str(order.status),
    }


def _emit_order_transition(
    db: Session, order: Order, old: OrderStatus, run: SyncRun, initial: bool, stats: _Stats
) -> None:
    new = order.status
    payload = {**_order_payload(order), "previous_status": str(old)}
    progressed = is_order_progress(old, new)
    if progressed and new == OrderStatus.PAID:
        type_ = DomainEventType.ORDER_PAID
    elif progressed and new == OrderStatus.SHIPPED:
        type_ = DomainEventType.ORDER_SHIPPED
    else:
        type_ = DomainEventType.ORDER_STATUS_CHANGED
    events.emit(
        db, type_, EntityType.ORDER, order.id, payload, sync_run_id=run.id, initial_import=initial
    )
    stats.events += 1


def _apply_order_fields(order: Order, data: NormalizedOrderSummary, now_seen: Any) -> None:
    order.buyer_name = data.buyer_name
    order.status = data.status
    if data.total_amount is not None:
        order.total_amount = data.total_amount
    order.currency = data.currency
    if data.item_count is not None:
        order.item_count = data.item_count
    if data.order_date is not None:
        order.order_date = data.order_date
    if data.source_url:
        order.raw_source_reference = data.source_url
    order.fingerprint = data.fingerprint()
    order.last_seen_at = now_seen


def _apply_order_detail(order: Order, data: NormalizedOrder) -> None:
    order.payment_status = (
        data.payment_status
        if data.payment_status != PaymentStatus.UNKNOWN
        else derive_payment_status(data.status)
    )
    order.shipping_status = (
        data.shipping_status
        if data.shipping_status != ShippingStatus.UNKNOWN
        else derive_shipping_status(data.status)
    )
    if data.paid_at:
        order.paid_at = data.paid_at
    if data.shipped_at:
        order.shipped_at = data.shipped_at
    if data.tracking_number:
        order.tracking_number = data.tracking_number
    _replace_items(order.items, data.items, OrderItem)
    if data.item_count is None and data.items:
        order.item_count = sum(i.quantity for i in data.items)
    order.extra = dict(data.extra)
    order.detail_fetched_at = utcnow()


def apply_orders(
    db: Session, conn: CardmarketConnection, run: SyncRun, batch: OrdersBatch
) -> SyncBatchResult:
    stats = _Stats()
    initial = is_initial_import(db, conn)
    now = utcnow()
    # A detail supersedes the summary for the same order.
    records: dict[str, NormalizedOrderSummary] = {s.cardmarket_id: s for s in batch.summaries}
    records.update({d.cardmarket_id: d for d in batch.details})
    if not records:
        return stats.result()
    existing = {
        o.cardmarket_id: o
        for o in db.scalars(
            select(Order)
            .options(selectinload(Order.items))
            .where(Order.connection_id == conn.id, Order.cardmarket_id.in_(records))
        )
    }
    created: list[Order] = []
    for cm_id, data in records.items():
        stats.found += 1
        order = existing.get(cm_id)
        if order is None:
            order = Order(
                connection_id=conn.id,
                cardmarket_id=cm_id,
                buyer_name=data.buyer_name,
                status=data.status,
                payment_status=derive_payment_status(data.status),
                shipping_status=derive_shipping_status(data.status),
                currency=data.currency,
                last_seen_at=now,
                extra={},
                # Orders seen during the initial import are not "new" for the shop.
                acknowledged_at=now if initial else None,
            )
            _apply_order_fields(order, data, now)
            if isinstance(data, NormalizedOrder):
                order.items = []
                _apply_order_detail(order, data)
            db.add(order)
            db.flush()
            created.append(order)
            stats.mark_changed(cm_id)
            events.emit(
                db,
                DomainEventType.ORDER_CREATED,
                EntityType.ORDER,
                order.id,
                _order_payload(order),
                sync_run_id=run.id,
                initial_import=initial,
            )
            stats.events += 1
            continue

        old_status, old_fp = order.status, order.fingerprint
        _apply_order_fields(order, data, now)
        if isinstance(data, NormalizedOrder):
            _apply_order_detail(order, data)
        elif old_status != order.status:
            # Summary-only update: keep derived statuses consistent.
            order.payment_status = derive_payment_status(order.status)
            order.shipping_status = derive_shipping_status(order.status)
        if (
            order.status == OrderStatus.PAID
            and old_status == OrderStatus.UNPAID
            and not order.paid_at
        ):
            order.paid_at = now
        if order.status == OrderStatus.SHIPPED and not order.shipped_at:
            order.shipped_at = now
        if old_fp != order.fingerprint or isinstance(data, NormalizedOrder):
            stats.mark_changed(cm_id)
        if old_status != order.status:
            _emit_order_transition(db, order, old_status, run, initial, stats)

    if created:
        _link_conversations_to_orders(db, conn, created)
    run.records_found += stats.found
    run.records_changed += len(stats.changed_ids)
    return stats.result()


def _link_conversations_to_orders(
    db: Session, conn: CardmarketConnection, orders: list[Order]
) -> None:
    by_cm = {o.cardmarket_id: o for o in orders}
    for convo in db.scalars(
        select(Conversation).where(
            Conversation.connection_id == conn.id,
            Conversation.order_id.is_(None),
            Conversation.order_cardmarket_id.in_(by_cm),
        )
    ):
        if convo.order_cardmarket_id is not None:
            convo.order_id = by_cm[convo.order_cardmarket_id].id


# --------------------------------------------------------------------------- #
# Conversations / messages
# --------------------------------------------------------------------------- #


def message_key(message: NormalizedMessage) -> str:
    """Stable identity for a message; synthetic when Cardmarket exposes no id."""
    if message.cardmarket_id:
        return str(message.cardmarket_id)
    raw = f"{message.direction}|{message.sent_at}|{message.body.strip()}"
    return "h:" + hashlib.sha256(raw.encode()).hexdigest()[:40]


def _normalize_body(body: str) -> str:
    return " ".join(body.split())


def _resolve_order_id(
    db: Session, conn: CardmarketConnection, order_cm_id: str | None
) -> int | None:
    if not order_cm_id:
        return None
    return db.scalar(
        select(Order.id).where(Order.connection_id == conn.id, Order.cardmarket_id == order_cm_id)
    )


def _apply_conversation_fields(
    db: Session,
    conn: CardmarketConnection,
    convo: Conversation,
    data: NormalizedConversationSummary,
) -> None:
    convo.buyer_name = data.buyer_name
    if data.order_cardmarket_id:
        convo.order_cardmarket_id = data.order_cardmarket_id
        if convo.order_id is None:
            convo.order_id = _resolve_order_id(db, conn, data.order_cardmarket_id)
    if data.last_message_at is not None:
        convo.last_message_at = data.last_message_at
    if data.last_message_preview is not None:
        convo.last_message_preview = data.last_message_preview[:280]
    if data.source_url:
        convo.raw_source_reference = data.source_url
    convo.fingerprint = data.fingerprint()
    convo.last_seen_at = utcnow()


def _merge_messages(
    db: Session,
    convo: Conversation,
    data: NormalizedConversation,
    run: SyncRun,
    initial: bool,
    stats: _Stats,
) -> None:
    existing_keys = {m.cardmarket_id for m in convo.messages if m.cardmarket_id}
    # Local outbound messages not yet matched with their Cardmarket counterpart.
    unmatched_outbound = [
        m
        for m in convo.messages
        if m.direction == MessageDirection.OUTBOUND
        and m.cardmarket_id is None
        and m.status in (MessageStatus.PENDING, MessageStatus.SENT, MessageStatus.UNKNOWN)
    ]
    new_inbound: list[Message] = []
    for msg in data.messages:
        key = message_key(msg)
        if key in existing_keys:
            continue
        existing_keys.add(key)
        if msg.direction == MessageDirection.OUTBOUND:
            match = next(
                (
                    m
                    for m in unmatched_outbound
                    if _normalize_body(m.body) == _normalize_body(msg.body)
                ),
                None,
            )
            if match is not None:
                unmatched_outbound.remove(match)
                match.cardmarket_id = key
                match.sent_at = msg.sent_at or match.sent_at
                if match.status != MessageStatus.SENT:
                    # Seen on Cardmarket: the send did happen.
                    match.status = MessageStatus.SENT
                stats.mark_changed(f"msg:{key}")
                continue
        row = Message(
            conversation_id=convo.id,
            cardmarket_id=key,
            direction=msg.direction,
            sender=msg.sender,
            body=msg.body,
            sent_at=msg.sent_at,
            status=MessageStatus.SENT,
            created_at=utcnow(),
        )
        convo.messages.append(row)
        stats.mark_changed(f"msg:{key}")
        if msg.direction == MessageDirection.INBOUND:
            new_inbound.append(row)

    db.flush()
    for row in new_inbound:
        events.emit(
            db,
            DomainEventType.MESSAGE_RECEIVED,
            EntityType.CONVERSATION,
            convo.id,
            {
                "conversation_id": convo.id,
                "message_id": row.id,
                "buyer_name": convo.buyer_name,
                "preview": row.body[:140],
            },
            sync_run_id=run.id,
            initial_import=initial,
        )
        stats.events += 1

    dated = [(m.sent_at, m.id or 0, m) for m in convo.messages if m.sent_at is not None]
    latest = max(dated, key=lambda t: (t[0], t[1]))[2] if dated else None
    if latest is not None and latest.sent_at is not None:
        if convo.last_message_at is None or latest.sent_at > convo.last_message_at:
            convo.last_message_at = latest.sent_at
        convo.last_message_preview = latest.body[:280]
    if new_inbound:
        convo.unread = True
    if latest is not None and latest.direction == MessageDirection.OUTBOUND:
        # The shop replied (from here or directly on Cardmarket).
        convo.unread = False


def apply_conversations(
    db: Session, conn: CardmarketConnection, run: SyncRun, batch: ConversationsBatch
) -> SyncBatchResult:
    stats = _Stats()
    initial = is_initial_import(db, conn)
    records: dict[str, NormalizedConversationSummary] = {
        s.cardmarket_id: s for s in batch.summaries
    }
    records.update({d.cardmarket_id: d for d in batch.details})
    if not records:
        return stats.result()
    existing = {
        c.cardmarket_id: c
        for c in db.scalars(
            select(Conversation)
            .options(selectinload(Conversation.messages))
            .where(Conversation.connection_id == conn.id, Conversation.cardmarket_id.in_(records))
        )
    }
    for cm_id, data in records.items():
        stats.found += 1
        convo = existing.get(cm_id)
        if convo is None:
            convo = Conversation(
                connection_id=conn.id,
                cardmarket_id=cm_id,
                buyer_name=data.buyer_name,
                unread=data.unread and not initial,
                last_seen_at=utcnow(),
            )
            convo.messages = []
            _apply_conversation_fields(db, conn, convo, data)
            db.add(convo)
            db.flush()
            stats.mark_changed(cm_id)
        else:
            old_fp = convo.fingerprint
            _apply_conversation_fields(db, conn, convo, data)
            if old_fp != convo.fingerprint:
                stats.mark_changed(cm_id)
        if isinstance(data, NormalizedConversation):
            _merge_messages(db, convo, data, run, initial, stats)

    run.records_found += stats.found
    run.records_changed += len(stats.changed_ids)
    return stats.result()


# --------------------------------------------------------------------------- #
# Carts
# --------------------------------------------------------------------------- #


def _cart_payload(cart: Cart) -> dict[str, Any]:
    return {
        "cardmarket_id": cart.cardmarket_id,
        "buyer_name": cart.buyer_name,
        "total_amount": str(cart.total_amount) if cart.total_amount is not None else None,
        "currency": cart.currency,
        "item_count": cart.item_count,
        "status": str(cart.status),
    }


def _apply_cart_fields(cart: Cart, data: NormalizedCartSummary) -> None:
    cart.buyer_name = data.buyer_name
    cart.status = data.status
    if data.total_amount is not None:
        cart.total_amount = data.total_amount
    cart.currency = data.currency
    if data.item_count is not None:
        cart.item_count = data.item_count
    if data.created_at is not None:
        cart.cardmarket_created_at = data.created_at
    if data.source_url:
        cart.raw_source_reference = data.source_url
    cart.fingerprint = data.fingerprint()
    cart.last_seen_at = utcnow()
    if isinstance(data, NormalizedCart):
        _replace_items(cart.items, data.items, CartItem)
        cart.extra = dict(data.extra)


def apply_carts(
    db: Session, conn: CardmarketConnection, run: SyncRun, batch: CartsBatch
) -> SyncBatchResult:
    stats = _Stats()
    initial = is_initial_import(db, conn)
    records: dict[str, NormalizedCartSummary] = {s.cardmarket_id: s for s in batch.summaries}
    records.update({d.cardmarket_id: d for d in batch.details})
    if not records:
        return stats.result()
    existing = {
        c.cardmarket_id: c
        for c in db.scalars(
            select(Cart)
            .options(selectinload(Cart.items))
            .where(Cart.connection_id == conn.id, Cart.cardmarket_id.in_(records))
        )
    }
    for cm_id, data in records.items():
        stats.found += 1
        cart = existing.get(cm_id)
        if cart is None:
            cart = Cart(
                connection_id=conn.id,
                cardmarket_id=cm_id,
                buyer_name=data.buyer_name,
                status=data.status,
                currency=data.currency,
                last_seen_at=utcnow(),
                extra={},
            )
            cart.items = []
            _apply_cart_fields(cart, data)
            db.add(cart)
            db.flush()
            stats.mark_changed(cm_id)
            events.emit(
                db,
                DomainEventType.CART_CREATED,
                EntityType.CART,
                cart.id,
                _cart_payload(cart),
                sync_run_id=run.id,
                initial_import=initial,
            )
            stats.events += 1
            continue
        old_status, old_fp = cart.status, cart.fingerprint
        _apply_cart_fields(cart, data)
        if old_fp != cart.fingerprint or isinstance(data, NormalizedCart):
            stats.mark_changed(cm_id)
        if old_status != cart.status:
            paid = cart.status == CartStatus.PAID and is_cart_progress(old_status, cart.status)
            events.emit(
                db,
                DomainEventType.CART_PAID if paid else DomainEventType.CART_STATUS_CHANGED,
                EntityType.CART,
                cart.id,
                {**_cart_payload(cart), "previous_status": str(old_status)},
                sync_run_id=run.id,
                initial_import=initial,
            )
            stats.events += 1

    run.records_found += stats.found
    run.records_changed += len(stats.changed_ids)
    return stats.result()
