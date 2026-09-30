from enum import StrEnum
from typing import Annotated

from cmc_shared.enums import ActionType, EntityType, MessageDirection, MessageStatus
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.db import utcnow
from app.deps import DbSession, ReqCtx, require
from app.models import Action, Conversation, Message, User
from app.schemas import (
    ConversationDetail,
    ConversationListItem,
    MessageOut,
    OkResponse,
    Page,
    SendMessageRequest,
)
from app.security.permissions import Permission
from app.security.rate_limit import limiter
from app.services import action_queue
from app.services.audit import AuditAction, AuditResult, record
from app.services.connection import get_primary_connection

router = APIRouter(prefix="/api/conversations", tags=["conversations"])

Viewer = Annotated[User, Depends(require(Permission.VIEW_DATA))]
Sender = Annotated[User, Depends(require(Permission.SEND_MESSAGE))]


class ConversationFilter(StrEnum):
    ALL = "all"
    UNREAD = "unread"
    WITH_ORDER = "with_order"


@router.get("", response_model=Page[ConversationListItem])
def list_conversations(
    db: DbSession,
    _: Viewer,
    filter: ConversationFilter = ConversationFilter.ALL,
    q: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[ConversationListItem]:
    conn = get_primary_connection(db)
    stmt = select(Conversation).where(Conversation.connection_id == conn.id)
    if filter == ConversationFilter.UNREAD:
        stmt = stmt.where(Conversation.unread.is_(True))
    elif filter == ConversationFilter.WITH_ORDER:
        stmt = stmt.where(Conversation.order_id.is_not(None))
    if q:
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Conversation.buyer_name).like(like),
                func.lower(Conversation.order_cardmarket_id).like(like),
                func.lower(Conversation.last_message_preview).like(like),
            )
        )
    total = int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    rows = db.scalars(
        stmt.options(selectinload(Conversation.order))
        .order_by(Conversation.last_message_at.desc().nulls_last(), Conversation.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return Page(
        items=[ConversationListItem.model_validate(c) for c in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


def _get(db: DbSession, conversation_id: int) -> Conversation:
    convo = db.scalar(
        select(Conversation)
        .options(selectinload(Conversation.messages), selectinload(Conversation.order))
        .where(Conversation.id == conversation_id)
    )
    if convo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversazione non trovata")
    return convo


@router.get("/{conversation_id}", response_model=ConversationDetail)
def get_conversation(conversation_id: int, db: DbSession, _: Viewer) -> ConversationDetail:
    return ConversationDetail.model_validate(_get(db, conversation_id))


@router.post("/{conversation_id}/read", response_model=OkResponse)
def mark_read(conversation_id: int, db: DbSession, _: Viewer) -> OkResponse:
    convo = _get(db, conversation_id)
    if convo.unread:
        convo.unread = False
        db.commit()
    return OkResponse()


@router.post(
    "/{conversation_id}/messages", response_model=MessageOut, status_code=status.HTTP_202_ACCEPTED
)
def send_message(
    conversation_id: int, body: SendMessageRequest, db: DbSession, user: Sender, ctx: ReqCtx
) -> MessageOut:
    """Queue a message. It becomes SENT only after the agent verified it on Cardmarket."""
    convo = _get(db, conversation_id)
    idempotency_key = f"msg:{convo.id}:{body.client_key}"
    existing = db.scalar(select(Action).where(Action.idempotency_key == idempotency_key))
    if existing is not None:
        message = db.get(Message, existing.payload.get("message_id"))
        if message is not None:
            return MessageOut.model_validate(message)

    if not limiter.hit(f"msg:{user.id}", get_settings().message_rate_limit_per_minute, 60):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Troppi messaggi, attendi un minuto")

    message = Message(
        conversation_id=convo.id,
        direction=MessageDirection.OUTBOUND,
        sender=user.name,
        body=body.body,
        status=MessageStatus.PENDING,
        sent_by_user_id=user.id,
        created_at=utcnow(),
    )
    db.add(message)
    db.flush()
    action, _created = action_queue.enqueue(
        db,
        get_primary_connection(db),
        ActionType.SEND_MESSAGE,
        {
            "message_id": message.id,
            "conversation_id": convo.id,
            "conversation_cardmarket_id": convo.cardmarket_id,
            "buyer_name": convo.buyer_name,
            "source_url": convo.raw_source_reference,
            "body": body.body,
            # Lets the agent recognise its own message when verifying after a crash.
            "requested_at": message.created_at.isoformat(),
        },
        idempotency_key=idempotency_key,
        user=user,
        correlation_id=ctx.request_id,
    )
    message.action_id = action.id
    record(
        db,
        AuditAction.SEND_MESSAGE,
        user=user,
        entity_type=EntityType.CONVERSATION,
        entity_id=convo.cardmarket_id,
        result=AuditResult.PENDING,
        details={"action_id": action.id, "message_id": message.id, "length": len(body.body)},
        ctx=ctx,
    )
    db.commit()
    return MessageOut.model_validate(message)
