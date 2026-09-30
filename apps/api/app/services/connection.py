"""Cardmarket connection state machine and agent liveness."""

from datetime import timedelta
from typing import Any

from cmc_shared.enums import (
    AgentCommandType,
    ConnectionStatus,
    DomainEventType,
    EntityType,
    ErrorCode,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import utcnow
from app.models import CardmarketConnection, CardmarketSession
from app.services import events

PRIMARY_CONNECTION_ID = 1

_AUTH_LOST = {ConnectionStatus.SESSION_EXPIRED, ConnectionStatus.AUTH_REQUIRED}


def get_primary_connection(db: Session, *, for_update: bool = False) -> CardmarketConnection:
    stmt = select(CardmarketConnection).where(CardmarketConnection.id == PRIMARY_CONNECTION_ID)
    if for_update:
        stmt = stmt.with_for_update()
    conn = db.scalar(stmt)
    if conn is None:
        conn = CardmarketConnection(
            id=PRIMARY_CONNECTION_ID, status=ConnectionStatus.DISCONNECTED, pending_commands=[]
        )
        db.add(conn)
        db.flush()
    return conn


def agent_online(conn: CardmarketConnection) -> bool:
    if conn.agent_last_seen_at is None:
        return False
    limit = timedelta(seconds=get_settings().agent_offline_after_seconds)
    return utcnow() - conn.agent_last_seen_at <= limit


def set_status(
    db: Session,
    conn: CardmarketConnection,
    status: ConnectionStatus,
    *,
    error_code: ErrorCode | None = None,
    message: str | None = None,
    authenticated: bool = False,
) -> bool:
    """Apply a status transition; returns True if the status changed."""
    previous = conn.status
    now = utcnow()
    if status == ConnectionStatus.ERROR or status in _AUTH_LOST:
        conn.last_error = message
        conn.last_error_code = error_code or (
            ErrorCode.AUTH_ERROR if status in _AUTH_LOST else ErrorCode.UNKNOWN
        )
        conn.last_error_at = now
    if status == ConnectionStatus.CONNECTED and authenticated:
        conn.last_authentication = now
        _touch_session(db, conn, paired=previous != ConnectionStatus.CONNECTED)
    if previous == status:
        return False

    conn.status = status
    conn.status_changed_at = now
    if status in _AUTH_LOST and previous not in _AUTH_LOST:
        _invalidate_session(db, conn)
        events.emit(
            db,
            DomainEventType.SESSION_EXPIRED,
            EntityType.CONNECTION,
            conn.id,
            {"status": status, "previous": previous, "message": message},
        )
    elif status == ConnectionStatus.CONNECTED and previous != ConnectionStatus.CONNECTED:
        events.emit(
            db,
            DomainEventType.CONNECTION_RESTORED,
            EntityType.CONNECTION,
            conn.id,
            {"previous": previous},
        )
    return True


def _touch_session(db: Session, conn: CardmarketConnection, *, paired: bool) -> None:
    session = db.scalar(
        select(CardmarketSession)
        .where(CardmarketSession.connection_id == conn.id)
        .order_by(CardmarketSession.id.desc())
    )
    now = utcnow()
    if session is None or session.invalidated_at is not None:
        session = CardmarketSession(
            connection_id=conn.id, profile_ref=f"agent:{conn.agent_id or 'default'}", paired_at=now
        )
        db.add(session)
    elif paired and session.paired_at is None:
        session.paired_at = now
    session.last_verified_at = now


def _invalidate_session(db: Session, conn: CardmarketConnection) -> None:
    session = db.scalar(
        select(CardmarketSession)
        .where(
            CardmarketSession.connection_id == conn.id,
            CardmarketSession.invalidated_at.is_(None),
        )
        .order_by(CardmarketSession.id.desc())
    )
    if session is not None:
        session.invalidated_at = utcnow()


def queue_command(
    conn: CardmarketConnection, command: AgentCommandType, params: dict[str, Any] | None = None
) -> None:
    # Reassign (not mutate) so SQLAlchemy detects the JSON change.
    conn.pending_commands = [
        *(conn.pending_commands or []),
        {"type": str(command), "params": params or {}},
    ]


def pop_commands(conn: CardmarketConnection) -> list[dict[str, Any]]:
    commands = list(conn.pending_commands or [])
    conn.pending_commands = []
    return commands
