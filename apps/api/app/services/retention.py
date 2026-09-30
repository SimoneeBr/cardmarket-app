"""Data retention and local data deletion (privacy)."""

import logging
from datetime import timedelta

from cmc_shared.enums import ActionStatus
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import utcnow
from app.models import (
    Action,
    AuditLog,
    Cart,
    Conversation,
    DomainEvent,
    Message,
    Notification,
    Order,
    SyncRun,
    UserSession,
)

log = logging.getLogger("cmc.retention")


def apply_retention(db: Session) -> dict[str, int]:
    settings = get_settings()
    now = utcnow()
    deleted: dict[str, int] = {}

    def _run(name: str, stmt: object) -> None:
        result = db.execute(stmt)  # type: ignore[call-overload]
        deleted[name] = int(result.rowcount or 0)

    _run(
        "messages",
        delete(Message).where(
            Message.created_at < now - timedelta(days=settings.retention_messages_days)
        ),
    )
    _run(
        "notifications",
        delete(Notification).where(
            Notification.created_at < now - timedelta(days=settings.retention_notifications_days)
        ),
    )
    _run(
        "audit_logs",
        delete(AuditLog).where(
            AuditLog.created_at < now - timedelta(days=settings.retention_audit_days)
        ),
    )
    _run(
        "domain_events",
        delete(DomainEvent).where(
            DomainEvent.occurred_at < now - timedelta(days=settings.retention_notifications_days)
        ),
    )
    _run(
        "sync_runs",
        delete(SyncRun).where(
            SyncRun.started_at < now - timedelta(days=settings.retention_sync_runs_days)
        ),
    )
    _run(
        "actions",
        delete(Action).where(
            Action.status.in_((ActionStatus.SUCCESS, ActionStatus.FAILED)),
            Action.completed_at < now - timedelta(days=settings.retention_sync_runs_days),
        ),
    )
    _run("expired_sessions", delete(UserSession).where(UserSession.expires_at < now))
    db.commit()
    if any(deleted.values()):
        log.info("retention applied", extra={"deleted": deleted})
    return deleted


def purge_cardmarket_data(db: Session) -> dict[str, int]:
    """Delete every locally mirrored customer record (orders, chats, carts)."""
    counts: dict[str, int] = {}
    for name, model in (
        ("notifications", Notification),
        ("domain_events", DomainEvent),
        ("conversations", Conversation),
        ("orders", Order),
        ("carts", Cart),
    ):
        counts[name] = int(db.execute(delete(model)).rowcount or 0)  # type: ignore[attr-defined]
    return counts
