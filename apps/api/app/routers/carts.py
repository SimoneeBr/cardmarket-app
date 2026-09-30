from enum import StrEnum
from typing import Annotated

from cmc_shared.enums import CartStatus
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from app.deps import DbSession, require
from app.models import Cart, User
from app.schemas import CartDetail, CartListItem, Page
from app.security.permissions import Permission
from app.services.connection import get_primary_connection

router = APIRouter(prefix="/api/carts", tags=["carts"])

Viewer = Annotated[User, Depends(require(Permission.VIEW_DATA))]


class CartFilter(StrEnum):
    ALL = "all"
    TO_PAY = "to_pay"
    PAID = "paid"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


_STATUS = {
    CartFilter.TO_PAY: CartStatus.TO_PAY,
    CartFilter.PAID: CartStatus.PAID,
    CartFilter.COMPLETED: CartStatus.COMPLETED,
    CartFilter.CANCELLED: CartStatus.CANCELLED,
}


@router.get("", response_model=Page[CartListItem])
def list_carts(
    db: DbSession,
    _: Viewer,
    filter: CartFilter = CartFilter.ALL,
    q: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[CartListItem]:
    conn = get_primary_connection(db)
    stmt = select(Cart).where(Cart.connection_id == conn.id)
    if filter in _STATUS:
        stmt = stmt.where(Cart.status == _STATUS[filter])
    if q:
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(
            or_(func.lower(Cart.buyer_name).like(like), func.lower(Cart.cardmarket_id).like(like))
        )
    total = int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    rows = db.scalars(
        stmt.order_by(
            func.coalesce(Cart.cardmarket_created_at, Cart.created_at).desc(), Cart.id.desc()
        )
        .limit(limit)
        .offset(offset)
    ).all()
    return Page(
        items=[CartListItem.model_validate(c) for c in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{cart_id}", response_model=CartDetail)
def get_cart(cart_id: int, db: DbSession, _: Viewer) -> CartDetail:
    cart = db.scalar(select(Cart).options(selectinload(Cart.items)).where(Cart.id == cart_id))
    if cart is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Carrello non trovato")
    return CartDetail.model_validate(cart)
