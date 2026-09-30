"""Operational tables: sync runs, action queue, events, notifications, audit, settings."""

from datetime import datetime
from typing import Any

from cmc_shared.enums import (
    ActionStatus,
    ActionType,
    DomainEventType,
    EntityType,
    ErrorCode,
    NotificationType,
    SyncEntity,
    SyncRunStatus,
)
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, JsonType, TimestampMixin, enum_column


class SyncRun(Base):
    __tablename__ = "sync_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("cardmarket_connection.id", ondelete="CASCADE"), index=True
    )
    sync_id: Mapped[str] = mapped_column(String(32), unique=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[SyncRunStatus] = mapped_column(enum_column(SyncRunStatus))
    entity_type: Mapped[SyncEntity] = mapped_column(enum_column(SyncEntity))
    trigger: Mapped[str] = mapped_column(String(40), default="schedule")
    records_found: Mapped[int] = mapped_column(Integer, default=0)
    records_changed: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[ErrorCode | None] = mapped_column(enum_column(ErrorCode))
    artifacts: Mapped[list[str]] = mapped_column(JsonType, default=list)


class Action(Base):
    """Persistent, per-account serialized queue of Cardmarket operations."""

    __tablename__ = "action_queue"
    __table_args__ = (Index("ix_action_queue_claim", "connection_id", "status", "not_before"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("cardmarket_connection.id", ondelete="CASCADE")
    )
    type: Mapped[ActionType] = mapped_column(enum_column(ActionType))
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict)
    status: Mapped[ActionStatus] = mapped_column(
        enum_column(ActionStatus), default=ActionStatus.PENDING
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    last_error: Mapped[str | None] = mapped_column(Text)
    last_error_code: Mapped[ErrorCode | None] = mapped_column(enum_column(ErrorCode))
    result: Mapped[dict[str, Any]] = mapped_column(default=dict)
    # Set when a previous attempt may have reached Cardmarket (crash, lost lease,
    # unverified outcome): the agent must verify before executing again.
    needs_verification: Mapped[bool] = mapped_column(Boolean, default=False)
    idempotency_key: Mapped[str] = mapped_column(String(80), unique=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    requested_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    not_before: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_owner: Mapped[str | None] = mapped_column(String(80))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class DomainEvent(Base):
    """Append-only log of domain events (also feeds the dashboard activity)."""

    __tablename__ = "domain_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[DomainEventType] = mapped_column(enum_column(DomainEventType, 40), index=True)
    entity_type: Mapped[EntityType] = mapped_column(enum_column(EntityType))
    entity_id: Mapped[int | None] = mapped_column(Integer)
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict)
    sync_run_id: Mapped[int | None] = mapped_column(ForeignKey("sync_runs.id", ondelete="SET NULL"))
    initial_import: Mapped[bool] = mapped_column(Boolean, default=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class Notification(Base):
    """One row per recipient user, so read state is per user."""

    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_user_read", "user_id", "read", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    type: Mapped[NotificationType] = mapped_column(enum_column(NotificationType))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    entity_type: Mapped[EntityType | None] = mapped_column(enum_column(EntityType))
    entity_id: Mapped[int | None] = mapped_column(Integer)
    event_id: Mapped[int | None] = mapped_column(
        ForeignKey("domain_events.id", ondelete="SET NULL")
    )
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    actor: Mapped[str] = mapped_column(String(120))
    action: Mapped[str] = mapped_column(String(60), index=True)
    entity_type: Mapped[EntityType | None] = mapped_column(enum_column(EntityType))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    result: Mapped[str] = mapped_column(String(20))
    error: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(default=dict)
    ip: Mapped[str | None] = mapped_column(String(64))
    request_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class MessageTemplate(TimestampMixin, Base):
    __tablename__ = "message_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(60), unique=True)
    label: Mapped[str] = mapped_column(String(80))
    icon: Mapped[str] = mapped_column(String(16), default="")
    body: Mapped[str] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class AppSetting(TimestampMixin, Base):
    """Runtime-editable settings (admin panel). Env vars provide defaults."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(default=dict)
