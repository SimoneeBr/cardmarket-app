from datetime import datetime
from typing import Any

from cmc_shared.enums import AgentMode, ConnectionStatus, ErrorCode
from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, JsonType, TimestampMixin, enum_column


class CardmarketConnection(TimestampMixin, Base):
    """One Cardmarket account operated by one agent.

    The MVP uses a single row, but every account-scoped table references it so
    that multi-account support does not need a schema rewrite.

    NOTE: no Cardmarket credential is ever stored here.
    """

    __tablename__ = "cardmarket_connection"

    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(String(80), default="Cardmarket")
    status: Mapped[ConnectionStatus] = mapped_column(
        enum_column(ConnectionStatus), default=ConnectionStatus.DISCONNECTED
    )
    last_successful_sync: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    last_error_code: Mapped[ErrorCode | None] = mapped_column(enum_column(ErrorCode))
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_authentication: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Agent liveness
    agent_id: Mapped[str | None] = mapped_column(String(80))
    agent_version: Mapped[str | None] = mapped_column(String(40))
    agent_mode: Mapped[AgentMode | None] = mapped_column(enum_column(AgentMode))
    agent_last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    agent_detail: Mapped[str | None] = mapped_column(Text)

    # Sync lease (prevents two concurrent syncs of the same account)
    sync_lock_owner: Mapped[str | None] = mapped_column(String(80))
    sync_lock_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Commands waiting to be delivered to the agent on the next heartbeat
    pending_commands: Mapped[list[dict[str, Any]]] = mapped_column(JsonType, default=list)


class CardmarketSession(TimestampMixin, Base):
    """Reference to the persistent browser profile holding the Cardmarket session.

    Cookies stay inside the Chromium profile on the agent's protected volume;
    the database only knows *where* it is and when it was last verified.
    """

    __tablename__ = "cardmarket_session"

    id: Mapped[int] = mapped_column(primary_key=True)
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("cardmarket_connection.id", ondelete="CASCADE"), index=True
    )
    storage: Mapped[str] = mapped_column(String(40), default="browser-profile")
    profile_ref: Mapped[str] = mapped_column(String(255))
    paired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
