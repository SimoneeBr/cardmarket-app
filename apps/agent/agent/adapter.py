"""The contract every Cardmarket adapter (mock or live) implements.

Adapters only *read* normalized data and perform *primitive* writes. The
execute -> verify protocol, retries and reporting live in ``agent.actions``
so the safety rules are identical for mock and live adapters.
"""

from dataclasses import dataclass
from typing import Protocol

from cmc_shared.enums import ConnectionStatus, ErrorCode
from cmc_shared.models import (
    NormalizedCart,
    NormalizedCartSummary,
    NormalizedConversation,
    NormalizedConversationSummary,
    NormalizedOrder,
    NormalizedOrderSummary,
)
from cmc_shared.protocol import AgentCommand


@dataclass(frozen=True)
class SessionState:
    status: ConnectionStatus
    message: str | None = None
    error_code: ErrorCode | None = None

    @property
    def connected(self) -> bool:
        return self.status == ConnectionStatus.CONNECTED


@dataclass(frozen=True)
class SendReceipt:
    """What the adapter knows right after submitting a message."""

    submitted: bool
    cardmarket_message_id: str | None = None


class CardmarketAdapter(Protocol):
    name: str

    async def start(self) -> None: ...

    async def close(self) -> None: ...

    # --- session -------------------------------------------------------------
    async def check_session(self) -> SessionState: ...

    async def pair(self, timeout_seconds: int) -> SessionState: ...

    async def disconnect(self) -> None: ...

    # --- reads -----------------------------------------------------------------
    async def list_orders(self) -> list[NormalizedOrderSummary]: ...

    async def get_order(self, summary: NormalizedOrderSummary) -> NormalizedOrder: ...

    async def list_conversations(self) -> list[NormalizedConversationSummary]: ...

    async def get_conversation(
        self, summary: NormalizedConversationSummary
    ) -> NormalizedConversation: ...

    async def list_carts(self) -> list[NormalizedCartSummary]: ...

    async def get_cart(self, summary: NormalizedCartSummary) -> NormalizedCart: ...

    # --- primitive writes (never call directly: use agent.actions) --------------
    async def submit_message(
        self, conversation: NormalizedConversationSummary, body: str
    ) -> SendReceipt: ...

    async def submit_mark_shipped(
        self, order: NormalizedOrderSummary, tracking_number: str | None
    ) -> None: ...

    # --- diagnostics -------------------------------------------------------------
    async def capture_failure(self, label: str) -> list[str]: ...

    async def handle_command(self, command: AgentCommand) -> None: ...
