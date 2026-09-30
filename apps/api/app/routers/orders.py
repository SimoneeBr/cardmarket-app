from enum import StrEnum
from typing import Annotated, Any

from cmc_shared.enums import ActionStatus, ActionType, EntityType, OrderStatus, PaymentStatus
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import selectinload

from app.db import utcnow
from app.deps import DbSession, ReqCtx, require
from app.models import Action, Conversation, Order, OrderItem, User
from app.schemas import (
    ActionBrief,
    ConversationRef,
    ItemOut,
    OrderDetail,
    OrderListItem,
    Page,
    ShipOrderRequest,
)
from app.security.permissions import Permission
from app.services import action_queue
from app.services.audit import AuditAction, AuditResult, record
from app.services.connection import get_primary_connection

router = APIRouter(prefix="/api/orders", tags=["orders"])

Viewer = Annotated[User, Depends(require(Permission.VIEW_DATA))]
Shipper = Annotated[User, Depends(require(Permission.UPDATE_ORDER))]

_ACTIVE = (ActionStatus.PENDING, ActionStatus.PROCESSING, ActionStatus.NEEDS_ATTENTION)


class OrderFilter(StrEnum):
    ALL = "all"
    NEW = "new"
    PAID = "paid"
    UNPAID = "unpaid"
    TO_SHIP = "to_ship"
    SHIPPED = "shipped"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class OrderSort(StrEnum):
    DATE_DESC = "date_desc"
    DATE_ASC = "date_asc"
    TOTAL_DESC = "total_desc"
    TOTAL_ASC = "total_asc"
    BUYER = "buyer"


def _apply_filter(stmt: Select[Order], filter_: OrderFilter) -> Select[Order]:
    match filter_:
        case OrderFilter.NEW:
            return stmt.where(Order.acknowledged_at.is_(None))
        case OrderFilter.PAID:
            return stmt.where(Order.payment_status == PaymentStatus.PAID)
        case OrderFilter.UNPAID:
            return stmt.where(Order.status == OrderStatus.UNPAID)
        case OrderFilter.TO_SHIP:
            return stmt.where(Order.status == OrderStatus.PAID)
        case OrderFilter.SHIPPED:
            return stmt.where(Order.status == OrderStatus.SHIPPED)
        case OrderFilter.COMPLETED:
            return stmt.where(Order.status == OrderStatus.COMPLETED)
        case OrderFilter.CANCELLED:
            return stmt.where(Order.status == OrderStatus.CANCELLED)
    return stmt


_SORTS: dict[OrderSort, tuple[Any, ...]] = {
    OrderSort.DATE_DESC: (Order.order_date.desc().nulls_last(), Order.id.desc()),
    OrderSort.DATE_ASC: (Order.order_date.asc().nulls_last(), Order.id),
    OrderSort.TOTAL_DESC: (Order.total_amount.desc().nulls_last(), Order.id.desc()),
    OrderSort.TOTAL_ASC: (Order.total_amount.asc().nulls_last(), Order.id),
    OrderSort.BUYER: (func.lower(Order.buyer_name), Order.id.desc()),
}


@router.get("", response_model=Page[OrderListItem])
def list_orders(
    db: DbSession,
    _: Viewer,
    filter: OrderFilter = OrderFilter.ALL,
    q: Annotated[str | None, Query(max_length=100)] = None,
    sort: OrderSort = OrderSort.DATE_DESC,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[OrderListItem]:
    conn = get_primary_connection(db)
    stmt = _apply_filter(select(Order).where(Order.connection_id == conn.id), filter)
    if q:
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Order.buyer_name).like(like),
                func.lower(Order.cardmarket_id).like(like),
                Order.id.in_(
                    select(OrderItem.order_id).where(func.lower(OrderItem.card_name).like(like))
                ),
            )
        )
    total = int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    rows = db.scalars(stmt.order_by(*_SORTS[sort]).limit(limit).offset(offset)).all()
    return Page(
        items=[OrderListItem.model_validate(o) for o in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


def _get_order(db: DbSession, order_id: int) -> Order:
    order = db.scalar(select(Order).options(selectinload(Order.items)).where(Order.id == order_id))
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ordine non trovato")
    return order


def _detail(db: DbSession, order: Order) -> OrderDetail:
    convos = db.scalars(
        select(Conversation)
        .where(Conversation.order_id == order.id)
        .order_by(Conversation.last_message_at.desc().nulls_last())
    ).all()
    action = db.scalar(
        select(Action)
        .where(
            Action.type == ActionType.MARK_ORDER_SHIPPED,
            Action.status.in_(_ACTIVE),
            Action.payload["order_id"].as_integer() == order.id,
        )
        .order_by(Action.id.desc())
        .limit(1)
    )
    base = OrderListItem.model_validate(order).model_dump()
    return OrderDetail(
        **base,
        tracking_number=order.tracking_number,
        raw_source_reference=order.raw_source_reference,
        detail_fetched_at=order.detail_fetched_at,
        items=[ItemOut.model_validate(i) for i in order.items],
        conversations=[ConversationRef.model_validate(c) for c in convos],
        pending_action=ActionBrief.model_validate(action) if action else None,
    )


@router.get("/{order_id}", response_model=OrderDetail)
def get_order(order_id: int, db: DbSession, _: Viewer) -> OrderDetail:
    return _detail(db, _get_order(db, order_id))


@router.post("/{order_id}/acknowledge", response_model=OrderDetail)
def acknowledge_order(order_id: int, db: DbSession, _: Viewer) -> OrderDetail:
    order = _get_order(db, order_id)
    if order.acknowledged_at is None:
        order.acknowledged_at = utcnow()
        db.commit()
    return _detail(db, order)


@router.post("/{order_id}/ship", response_model=ActionBrief, status_code=status.HTTP_202_ACCEPTED)
def ship_order(
    order_id: int, body: ShipOrderRequest, db: DbSession, user: Shipper, ctx: ReqCtx
) -> ActionBrief:
    """Queue 'mark as shipped' on Cardmarket. Local status changes only once verified."""
    order = _get_order(db, order_id)
    if order.status != OrderStatus.PAID:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Solo gli ordini pagati possono essere spediti"
        )
    conn = get_primary_connection(db)
    active = db.scalar(
        select(Action).where(
            Action.type == ActionType.MARK_ORDER_SHIPPED,
            Action.status.in_(_ACTIVE),
            Action.payload["order_id"].as_integer() == order.id,
        )
    )
    if active is not None:
        return ActionBrief.model_validate(active)
    action, created = action_queue.enqueue(
        db,
        conn,
        ActionType.MARK_ORDER_SHIPPED,
        {
            "order_id": order.id,
            "order_cardmarket_id": order.cardmarket_id,
            "buyer_name": order.buyer_name,
            "tracking_number": body.tracking_number,
            "source_url": order.raw_source_reference,
        },
        idempotency_key=f"ship:{order.id}:{body.client_key}",
        user=user,
        correlation_id=ctx.request_id,
    )
    if created:
        record(
            db,
            AuditAction.MARK_ORDER_SHIPPED,
            user=user,
            entity_type=EntityType.ORDER,
            entity_id=order.cardmarket_id,
            result=AuditResult.PENDING,
            details={"action_id": action.id, "tracking": bool(body.tracking_number)},
            ctx=ctx,
        )
    db.commit()
    return ActionBrief.model_validate(action)
