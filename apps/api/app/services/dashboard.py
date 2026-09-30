"""Dashboard aggregation: everything that needs an action, at a glance."""

from datetime import timedelta
from decimal import Decimal
from typing import Any

from cmc_shared.enums import (
    ActionStatus,
    CartStatus,
    DomainEventType,
    OrderStatus,
    SyncRunStatus,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.models import Action, Cart, Conversation, DomainEvent, Notification, Order, SyncRun, User
from app.services.connection import agent_online, get_primary_connection
from app.services.notifications import RULES

SALES_WINDOW_DAYS = 7
_SOLD = (OrderStatus.PAID, OrderStatus.SHIPPED, OrderStatus.COMPLETED)

_FALLBACK_TITLES: dict[DomainEventType, str] = {
    DomainEventType.ORDER_STATUS_CHANGED: "Ordine #{cardmarket_id}: stato {status}",
    DomainEventType.MESSAGE_SENT: "Messaggio inviato a {buyer_name}",
    DomainEventType.CART_STATUS_CHANGED: "Carrello di {buyer_name}: stato {status}",
    DomainEventType.CONNECTION_RESTORED: "Cardmarket connesso",
}


def describe_event(event: DomainEvent) -> tuple[str, str | None]:
    rule = RULES.get(event.type)
    if rule is not None:
        return rule.title(event.payload), rule.link(event)
    template = _FALLBACK_TITLES.get(event.type, str(event.type))
    try:
        title = template.format(**event.payload)
    except (KeyError, IndexError):
        title = str(event.type)
    link = None
    if event.type == DomainEventType.ORDER_STATUS_CHANGED:
        link = f"/orders/{event.entity_id}"
    elif event.type == DomainEventType.MESSAGE_SENT:
        link = f"/chat/{event.entity_id}"
    elif event.type == DomainEventType.CART_STATUS_CHANGED:
        link = f"/carts/{event.entity_id}"
    return title, link


def _count(db: Session, stmt: Any) -> int:
    return int(db.scalar(stmt) or 0)


def build_dashboard(db: Session, user: User) -> dict[str, Any]:
    now = utcnow()
    conn = get_primary_connection(db)
    order_count = select(func.count(Order.id)).where(Order.connection_id == conn.id)
    cart_count = select(func.count(Cart.id)).where(Cart.connection_id == conn.id)

    sales_rows = db.execute(
        select(Order.currency, func.coalesce(func.sum(Order.total_amount), 0), func.count(Order.id))
        .where(
            Order.connection_id == conn.id,
            Order.status.in_(_SOLD),
            Order.order_date >= now - timedelta(days=SALES_WINDOW_DAYS),
        )
        .group_by(Order.currency)
    ).all()
    sales = [
        {"currency": currency, "total": Decimal(total or 0), "orders": int(count)}
        for currency, total, count in sorted(sales_rows, key=lambda r: int(r[2]), reverse=True)
    ]

    activity = []
    for event in db.scalars(
        select(DomainEvent)
        .where(DomainEvent.initial_import.is_(False))
        .order_by(DomainEvent.occurred_at.desc(), DomainEvent.id.desc())
        .limit(15)
    ):
        title, link = describe_event(event)
        activity.append(
            {
                "id": event.id,
                "type": event.type,
                "title": title,
                "occurred_at": event.occurred_at,
                "link": link,
            }
        )

    return {
        "connection": {
            "status": conn.status,
            "agent_online": agent_online(conn),
            "agent_mode": conn.agent_mode,
            "last_successful_sync": conn.last_successful_sync,
            "last_error": conn.last_error,
            "last_error_code": conn.last_error_code,
        },
        "orders": {
            "new": _count(db, order_count.where(Order.acknowledged_at.is_(None))),
            "to_ship": _count(db, order_count.where(Order.status == OrderStatus.PAID)),
            "unpaid": _count(db, order_count.where(Order.status == OrderStatus.UNPAID)),
            "paid_24h": _count(
                db,
                order_count.where(
                    Order.paid_at >= now - timedelta(hours=24), Order.status.in_(_SOLD)
                ),
            ),
        },
        "messages": {
            "unread_conversations": _count(
                db,
                select(func.count(Conversation.id)).where(
                    Conversation.connection_id == conn.id, Conversation.unread.is_(True)
                ),
            )
        },
        "carts": {
            "to_pay": _count(db, cart_count.where(Cart.status == CartStatus.TO_PAY)),
            "paid": _count(db, cart_count.where(Cart.status == CartStatus.PAID)),
        },
        "sales": {"window_days": SALES_WINDOW_DAYS, "by_currency": sales},
        "attention": {
            "failed_syncs_24h": _count(
                db,
                select(func.count(SyncRun.id)).where(
                    SyncRun.status == SyncRunStatus.FAILED,
                    SyncRun.started_at >= now - timedelta(hours=24),
                ),
            ),
            "actions_needing_attention": _count(
                db,
                select(func.count(Action.id)).where(Action.status == ActionStatus.NEEDS_ATTENTION),
            ),
            "failed_actions_24h": _count(
                db,
                select(func.count(Action.id)).where(
                    Action.status == ActionStatus.FAILED,
                    Action.completed_at >= now - timedelta(hours=24),
                ),
            ),
        },
        "notifications_unread": _count(
            db,
            select(func.count(Notification.id)).where(
                Notification.user_id == user.id, Notification.read.is_(False)
            ),
        ),
        "activity": activity,
        "generated_at": now,
    }
