"""Audit trail of important operations (who, what, when, result)."""

import logging
from enum import StrEnum
from typing import Any

from cmc_shared.enums import EntityType
from sqlalchemy.orm import Session

from app.db import utcnow
from app.deps import RequestContext
from app.models import AuditLog, User

log = logging.getLogger("cmc.audit")


class AuditAction(StrEnum):
    LOGIN = "LOGIN"
    LOGIN_FAILED = "LOGIN_FAILED"
    LOGOUT = "LOGOUT"
    PASSWORD_CHANGED = "PASSWORD_CHANGED"  # noqa: S105 - audit label, not a secret
    SETUP_ADMIN = "SETUP_ADMIN"
    USER_CREATED = "USER_CREATED"
    USER_UPDATED = "USER_UPDATED"
    SEND_MESSAGE = "SEND_MESSAGE"
    MARK_ORDER_SHIPPED = "MARK_ORDER_SHIPPED"
    ACTION_COMPLETED = "ACTION_COMPLETED"
    ACTION_RETRIED = "ACTION_RETRIED"
    ACTION_CANCELLED = "ACTION_CANCELLED"
    ACTION_RESOLVED = "ACTION_RESOLVED"
    PAIRING_REQUESTED = "PAIRING_REQUESTED"
    RECONNECT_REQUESTED = "RECONNECT_REQUESTED"
    DISCONNECT_REQUESTED = "DISCONNECT_REQUESTED"
    SESSION_STATUS_CHANGED = "SESSION_STATUS_CHANGED"
    SYNC_REQUESTED = "SYNC_REQUESTED"
    SYNC_FAILED = "SYNC_FAILED"
    SETTINGS_CHANGED = "SETTINGS_CHANGED"
    TEMPLATE_CHANGED = "TEMPLATE_CHANGED"
    SIMULATION = "SIMULATION"
    DATA_PURGED = "DATA_PURGED"


class AuditResult(StrEnum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    PENDING = "PENDING"


def record(
    db: Session,
    action: AuditAction,
    *,
    user: User | None = None,
    actor: str | None = None,
    entity_type: EntityType | None = None,
    entity_id: str | int | None = None,
    result: AuditResult = AuditResult.SUCCESS,
    error: str | None = None,
    details: dict[str, Any] | None = None,
    ctx: RequestContext | None = None,
) -> AuditLog:
    entry = AuditLog(
        user_id=user.id if user else None,
        actor=actor or (f"user:{user.email}" if user else "system"),
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        result=result,
        error=error,
        details=details or {},
        ip=ctx.ip if ctx else None,
        request_id=ctx.request_id if ctx else None,
        created_at=utcnow(),
    )
    db.add(entry)
    log.info(
        "audit",
        extra={
            "audit_action": str(action),
            "actor": entry.actor,
            "entity": f"{entity_type}:{entity_id}" if entity_type else None,
            "result": str(result),
        },
    )
    return entry
