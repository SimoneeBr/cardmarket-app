"""Internal HTTP protocol between the agent and the API (``/internal/agent/*``).

The agent never touches the database directly: it pushes normalized snapshots
and action results, and pulls actions/commands. This keeps the schema owned by
a single service and lets the agent run on a separate host.
"""

from typing import Any

from pydantic import BaseModel, Field

from cmc_shared.enums import (
    ActionOutcome,
    ActionType,
    AgentCommandType,
    AgentMode,
    ConnectionStatus,
    ErrorCode,
    SyncEntity,
    SyncRunStatus,
)
from cmc_shared.models import (
    NormalizedCart,
    NormalizedCartSummary,
    NormalizedConversation,
    NormalizedConversationSummary,
    NormalizedOrder,
    NormalizedOrderSummary,
)


class AgentCommand(BaseModel):
    type: AgentCommandType
    params: dict[str, Any] = Field(default_factory=dict)


class HeartbeatRequest(BaseModel):
    agent_id: str
    version: str
    mode: AgentMode
    connection_status: ConnectionStatus
    detail: str | None = None


class HeartbeatResponse(BaseModel):
    sync_enabled: bool
    sync_interval_seconds: int
    commands: list[AgentCommand] = Field(default_factory=list)


class SessionReport(BaseModel):
    status: ConnectionStatus
    error_code: ErrorCode | None = None
    message: str | None = None
    authenticated: bool = False


class SyncStartRequest(BaseModel):
    agent_id: str
    entity: SyncEntity = SyncEntity.FULL
    trigger: str = "schedule"


class SyncStartResponse(BaseModel):
    granted: bool
    sync_run_id: int | None = None
    sync_id: str | None = None
    reason: str | None = None
    # Fingerprints already stored, used by the agent to fetch only changed details.
    known_orders: dict[str, str] = Field(default_factory=dict)
    known_conversations: dict[str, str] = Field(default_factory=dict)
    known_carts: dict[str, str] = Field(default_factory=dict)


class OrdersBatch(BaseModel):
    summaries: list[NormalizedOrderSummary] = Field(default_factory=list)
    details: list[NormalizedOrder] = Field(default_factory=list)


class ConversationsBatch(BaseModel):
    summaries: list[NormalizedConversationSummary] = Field(default_factory=list)
    details: list[NormalizedConversation] = Field(default_factory=list)


class CartsBatch(BaseModel):
    summaries: list[NormalizedCartSummary] = Field(default_factory=list)
    details: list[NormalizedCart] = Field(default_factory=list)


class SyncBatchResult(BaseModel):
    records_found: int
    records_changed: int
    events: int


class SyncCompleteRequest(BaseModel):
    status: SyncRunStatus
    error_code: ErrorCode | None = None
    error_message: str | None = None
    artifacts: list[str] = Field(default_factory=list)


class ClaimRequest(BaseModel):
    agent_id: str
    lease_seconds: int = Field(default=300, ge=30, le=3600)


class ClaimedAction(BaseModel):
    id: int
    type: ActionType
    payload: dict[str, Any]
    attempts: int
    idempotency_key: str
    correlation_id: str | None = None
    # True when a previous attempt may have executed before the agent died:
    # the agent MUST verify before (re-)executing a write action.
    recovery: bool = False


class ActionResultRequest(BaseModel):
    outcome: ActionOutcome
    error_code: ErrorCode | None = None
    error_message: str | None = None
    result: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[str] = Field(default_factory=list)
