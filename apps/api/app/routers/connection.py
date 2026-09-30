import secrets
from typing import Annotated

from cmc_shared.enums import (
    ActionStatus,
    ActionType,
    AgentCommandType,
    ConnectionStatus,
    EntityType,
)
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from app.config import get_settings
from app.db import utcnow
from app.deps import DbSession, ReqCtx, require
from app.models import Action, CardmarketSession, SyncRun, User
from app.schemas import ActionBrief, ConnectionOut, Page, SyncRunOut, SyncStatusOut
from app.security.permissions import Permission
from app.services import action_queue
from app.services.audit import AuditAction, AuditResult, record
from app.services.connection import agent_online, get_primary_connection, queue_command, set_status
from app.services.runtime_settings import get_runtime_settings

router = APIRouter(prefix="/api", tags=["connection"])

Viewer = Annotated[User, Depends(require(Permission.VIEW_DATA))]
ConnAdmin = Annotated[User, Depends(require(Permission.MANAGE_CONNECTION))]
SyncTrigger = Annotated[User, Depends(require(Permission.TRIGGER_SYNC))]
Operator = Annotated[User, Depends(require(Permission.VIEW_OPERATIONS))]

_SESSION_ACTIONS = (ActionType.PAIR_SESSION, ActionType.VERIFY_SESSION)
_ACTIVE = (ActionStatus.PENDING, ActionStatus.PROCESSING)


def _active_session_action(db: DbSession) -> Action | None:
    return db.scalar(
        select(Action)
        .where(Action.type.in_(_SESSION_ACTIONS), Action.status.in_(_ACTIVE))
        .order_by(Action.id.desc())
        .limit(1)
    )


def connection_out(db: DbSession) -> ConnectionOut:
    conn = get_primary_connection(db)
    session = db.scalar(
        select(CardmarketSession)
        .where(CardmarketSession.connection_id == conn.id)
        .order_by(CardmarketSession.id.desc())
        .limit(1)
    )
    action = _active_session_action(db)
    now = utcnow()
    settings = get_settings()
    return ConnectionOut(
        status=conn.status,
        agent_online=agent_online(conn),
        agent_mode=conn.agent_mode,
        agent_version=conn.agent_version,
        agent_last_seen_at=conn.agent_last_seen_at,
        agent_detail=conn.agent_detail,
        last_successful_sync=conn.last_successful_sync,
        last_authentication=conn.last_authentication,
        last_error=conn.last_error,
        last_error_code=conn.last_error_code,
        last_error_at=conn.last_error_at,
        status_changed_at=conn.status_changed_at,
        sync_running=bool(
            conn.sync_lock_owner and conn.sync_lock_expires_at and conn.sync_lock_expires_at > now
        ),
        session_paired_at=session.paired_at if session and not session.invalidated_at else None,
        session_last_verified_at=session.last_verified_at
        if session and not session.invalidated_at
        else None,
        pending_session_action=ActionBrief.model_validate(action) if action else None,
        mock_mode=settings.mock_cardmarket,
        pairing_viewer_url=settings.pairing_viewer_url or None,
    )


@router.get("/connection/status", response_model=ConnectionOut)
def connection_status(db: DbSession, _: Viewer) -> ConnectionOut:
    out = connection_out(db)
    db.commit()
    return out


def _enqueue_session_action(
    db: DbSession, user: User, ctx: ReqCtx, type_: ActionType, audit: AuditAction
) -> ActionBrief:
    existing = _active_session_action(db)
    if existing is not None:
        return ActionBrief.model_validate(existing)
    conn = get_primary_connection(db, for_update=True)
    if type_ == ActionType.PAIR_SESSION:
        set_status(db, conn, ConnectionStatus.CONNECTING)
    action, _ = action_queue.enqueue(
        db,
        conn,
        type_,
        {"requested_by": user.email},
        idempotency_key=f"{type_.lower()}:{secrets.token_hex(8)}",
        user=user,
        correlation_id=ctx.request_id,
    )
    record(
        db,
        audit,
        user=user,
        entity_type=EntityType.CONNECTION,
        entity_id=conn.id,
        result=AuditResult.PENDING,
        details={"action_id": action.id},
        ctx=ctx,
    )
    db.commit()
    return ActionBrief.model_validate(action)


@router.post("/connection/pair", response_model=ActionBrief, status_code=202)
def pair(db: DbSession, user: ConnAdmin, ctx: ReqCtx) -> ActionBrief:
    """Start manual pairing: the agent opens Cardmarket, a human logs in (incl. 2FA)."""
    return _enqueue_session_action(
        db, user, ctx, ActionType.PAIR_SESSION, AuditAction.PAIRING_REQUESTED
    )


@router.post("/connection/reconnect", response_model=ActionBrief, status_code=202)
def reconnect(db: DbSession, user: ConnAdmin, ctx: ReqCtx) -> ActionBrief:
    """Re-check the persisted browser session without asking for a new login."""
    return _enqueue_session_action(
        db, user, ctx, ActionType.VERIFY_SESSION, AuditAction.RECONNECT_REQUESTED
    )


@router.post("/connection/disconnect", response_model=ConnectionOut)
def disconnect(db: DbSession, user: ConnAdmin, ctx: ReqCtx) -> ConnectionOut:
    conn = get_primary_connection(db, for_update=True)
    set_status(db, conn, ConnectionStatus.DISCONNECTED)
    queue_command(conn, AgentCommandType.DISCONNECT)
    record(
        db,
        AuditAction.DISCONNECT_REQUESTED,
        user=user,
        entity_type=EntityType.CONNECTION,
        entity_id=conn.id,
        ctx=ctx,
    )
    db.commit()
    return connection_out(db)


@router.post("/connection/sync-now", response_model=ConnectionOut)
def sync_now(db: DbSession, user: SyncTrigger, ctx: ReqCtx) -> ConnectionOut:
    conn = get_primary_connection(db, for_update=True)
    queue_command(conn, AgentCommandType.SYNC_NOW)
    record(
        db,
        AuditAction.SYNC_REQUESTED,
        user=user,
        entity_type=EntityType.CONNECTION,
        entity_id=conn.id,
        ctx=ctx,
    )
    db.commit()
    return connection_out(db)


@router.get("/sync/status", response_model=SyncStatusOut)
def sync_status(db: DbSession, _: Viewer) -> SyncStatusOut:
    conn = get_primary_connection(db)
    runtime = get_runtime_settings(db)
    runs = db.scalars(select(SyncRun).order_by(SyncRun.id.desc()).limit(10)).all()
    now = utcnow()
    return SyncStatusOut(
        sync_enabled=runtime.sync_enabled,
        sync_interval_seconds=runtime.sync_interval_seconds,
        last_successful_sync=conn.last_successful_sync,
        running=bool(
            conn.sync_lock_owner and conn.sync_lock_expires_at and conn.sync_lock_expires_at > now
        ),
        last_runs=[SyncRunOut.model_validate(r) for r in runs],
    )


@router.get("/sync/runs", response_model=Page[SyncRunOut])
def sync_runs(
    db: DbSession,
    _: Operator,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[SyncRunOut]:
    total = int(db.scalar(select(func.count(SyncRun.id))) or 0)
    rows = db.scalars(select(SyncRun).order_by(SyncRun.id.desc()).limit(limit).offset(offset)).all()
    return Page(
        items=[SyncRunOut.model_validate(r) for r in rows], total=total, limit=limit, offset=offset
    )
