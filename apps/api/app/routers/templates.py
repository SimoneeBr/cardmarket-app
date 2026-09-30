from typing import Annotated

from cmc_shared.enums import EntityType
from cmc_shared.templating import TEMPLATE_VARIABLES, render_template, unknown_variables
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.deps import CurrentUser, DbSession, ReqCtx, require
from app.models import Conversation, MessageTemplate, Order, User
from app.schemas import (
    OkResponse,
    TemplateIn,
    TemplateOut,
    TemplateRenderOut,
    TemplateRenderRequest,
)
from app.security.permissions import Permission
from app.services.audit import AuditAction, record
from app.services.runtime_settings import get_runtime_settings

router = APIRouter(prefix="/api/templates", tags=["templates"])

Editor = Annotated[User, Depends(require(Permission.MANAGE_TEMPLATES))]


def _validate(body: TemplateIn) -> None:
    unknown = unknown_variables(body.body)
    if unknown:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"Variabili sconosciute: {', '.join(sorted(unknown))}. "
            f"Disponibili: {', '.join(sorted(TEMPLATE_VARIABLES))}",
        )


@router.get("", response_model=list[TemplateOut])
def list_templates(
    db: DbSession, _: CurrentUser, include_inactive: bool = False
) -> list[MessageTemplate]:
    stmt = select(MessageTemplate).order_by(MessageTemplate.position, MessageTemplate.id)
    if not include_inactive:
        stmt = stmt.where(MessageTemplate.active.is_(True))
    return list(db.scalars(stmt))


@router.get("/variables")
def list_variables(_: CurrentUser) -> list[str]:
    return sorted(TEMPLATE_VARIABLES)


@router.post("", response_model=TemplateOut, status_code=status.HTTP_201_CREATED)
def create_template(body: TemplateIn, db: DbSession, user: Editor, ctx: ReqCtx) -> MessageTemplate:
    _validate(body)
    template = MessageTemplate(**body.model_dump())
    db.add(template)
    try:
        db.flush()
    except IntegrityError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "Chiave template già esistente") from exc
    record(
        db,
        AuditAction.TEMPLATE_CHANGED,
        user=user,
        entity_type=EntityType.TEMPLATE,
        entity_id=template.id,
        details={"op": "create"},
        ctx=ctx,
    )
    db.commit()
    return template


@router.put("/{template_id}", response_model=TemplateOut)
def update_template(
    template_id: int, body: TemplateIn, db: DbSession, user: Editor, ctx: ReqCtx
) -> MessageTemplate:
    _validate(body)
    template = db.get(MessageTemplate, template_id)
    if template is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template non trovato")
    for key, value in body.model_dump().items():
        setattr(template, key, value)
    try:
        db.flush()
    except IntegrityError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "Chiave template già esistente") from exc
    record(
        db,
        AuditAction.TEMPLATE_CHANGED,
        user=user,
        entity_type=EntityType.TEMPLATE,
        entity_id=template.id,
        details={"op": "update"},
        ctx=ctx,
    )
    db.commit()
    return template


@router.delete("/{template_id}", response_model=OkResponse)
def delete_template(template_id: int, db: DbSession, user: Editor, ctx: ReqCtx) -> OkResponse:
    template = db.get(MessageTemplate, template_id)
    if template is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template non trovato")
    db.delete(template)
    record(
        db,
        AuditAction.TEMPLATE_CHANGED,
        user=user,
        entity_type=EntityType.TEMPLATE,
        entity_id=template_id,
        details={"op": "delete"},
        ctx=ctx,
    )
    db.commit()
    return OkResponse()


@router.post("/{template_id}/render", response_model=TemplateRenderOut)
def render(
    template_id: int, body: TemplateRenderRequest, db: DbSession, _: CurrentUser
) -> TemplateRenderOut:
    template = db.get(MessageTemplate, template_id)
    if template is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template non trovato")
    order: Order | None = db.get(Order, body.order_id) if body.order_id else None
    buyer: str | None = None
    if body.conversation_id:
        convo = db.get(Conversation, body.conversation_id)
        if convo is not None:
            buyer = convo.buyer_name
            order = order or convo.order
    if order is not None:
        buyer = buyer or order.buyer_name
    context = {
        "buyer_name": buyer,
        "order_id": order.cardmarket_id if order else None,
        "tracking_number": body.tracking_number or (order.tracking_number if order else None),
        "total_amount": f"{order.total_amount} {order.currency}"
        if order and order.total_amount is not None
        else None,
        "shop_name": get_runtime_settings(db).shop_name or None,
    }
    text, missing = render_template(template.body, context)
    return TemplateRenderOut(text=text, missing_variables=sorted(missing))
