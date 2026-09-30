"""Mock Cardmarket adapter: a simulated marketplace with persistent state.

Behaves like the live adapter from the agent's point of view (same contract,
same error types), so sync, actions, verification and recovery are exercised
end-to-end without a Cardmarket account.

Test hooks inside message bodies:
- ``[mock:fail]``        -> network error before submission (RETRY)
- ``[mock:unverified]``  -> "submitted" but never appears (UNVERIFIED -> UNKNOWN)
- ``[mock:unsafe]``      -> UI not recognised (UNSAFE -> NEEDS_ATTENTION)
"""

import asyncio
import json
import logging
import os
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from cmc_shared.enums import AgentCommandType, ConnectionStatus, ErrorCode
from cmc_shared.models import (
    NormalizedCart,
    NormalizedCartSummary,
    NormalizedConversation,
    NormalizedConversationSummary,
    NormalizedOrder,
    NormalizedOrderSummary,
)
from cmc_shared.protocol import AgentCommand
from cmc_shared.status_mapping import derive_payment_status, derive_shipping_status

from agent.adapter import SendReceipt, SessionState
from agent.config import AgentSettings
from agent.errors import (
    AuthRequiredError,
    CardmarketChangedError,
    NetworkError,
    SelectorNotFoundError,
    UnsafeUIError,
)
from agent.mock import dataset

log = logging.getLogger("cmc.agent.mock")


def _now() -> datetime:
    return datetime.now(UTC)


class MockCardmarketAdapter:
    name = "mock"

    def __init__(self, settings: AgentSettings) -> None:
        self.settings = settings
        self.path = Path(settings.mock_state_file)
        self.state: dict[str, Any] = {}
        self.rng = random.Random(settings.mock_seed)
        self._fail_next_sync = False
        self._evolved_this_cycle = False

    # ---------------------------------------------------------------- state

    async def start(self) -> None:
        if self.path.exists():
            self.state = json.loads(self.path.read_text())
            log.info("mock state loaded", extra={"path": str(self.path)})
        else:
            self.state = dataset.build_dataset(self.settings.mock_seed)
            self.state["authenticated"] = self.settings.mock_auto_pair
            self._save()
            log.info("mock dataset generated", extra={"orders": len(self.state["orders"])})
        self.rng = random.Random(self.state.get("rng_state", self.settings.mock_seed))

    async def close(self) -> None:
        self._save()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        self.state["rng_state"] = self.rng.randint(0, 2**31)
        tmp.write_text(json.dumps(self.state, indent=1))
        os.replace(tmp, self.path)  # atomic: survives crashes mid-write

    def _require_auth(self) -> None:
        if not self.state.get("authenticated"):
            raise AuthRequiredError("mock: Cardmarket session expired (login page shown)")

    async def _latency(self) -> None:
        await asyncio.sleep(self.rng.uniform(0.01, 0.05))

    # -------------------------------------------------------------- session

    async def check_session(self) -> SessionState:
        await self._latency()
        if self.state.get("authenticated"):
            return SessionState(ConnectionStatus.CONNECTED)
        return SessionState(
            ConnectionStatus.AUTH_REQUIRED, "mock: login required", ErrorCode.AUTH_ERROR
        )

    async def pair(self, timeout_seconds: int) -> SessionState:
        log.info("mock pairing: simulating manual login + 2FA by a human")
        await asyncio.sleep(min(self.settings.mock_pairing_delay_seconds, timeout_seconds))
        self.state["authenticated"] = True
        self._save()
        return SessionState(ConnectionStatus.CONNECTED, "mock: paired")

    async def disconnect(self) -> None:
        log.info("mock disconnect: session kept, syncing stopped by the API")

    # ------------------------------------------------------------- commands

    async def handle_command(self, command: AgentCommand) -> None:
        if command.type == AgentCommandType.SIMULATE_SESSION_EXPIRED:
            self.state["authenticated"] = False
            self._save()
        elif command.type == AgentCommandType.SIMULATE_SYNC_ERROR:
            self._fail_next_sync = True
        elif command.type == AgentCommandType.SIMULATE_NEW_ACTIVITY:
            for _ in range(3):
                self._evolve(force=True)
            self._save()

    # ------------------------------------------------------------ evolution

    def _evolve(self, force: bool = False) -> None:
        """Make the marketplace move: new orders, payments, messages, carts."""
        if not force and self.rng.random() > self.settings.mock_activity_rate:
            return
        now = _now()
        choice = self.rng.choice(
            ["new_order", "pay_order", "message", "new_cart", "pay_cart", "complete"]
        )
        if choice == "new_order":
            order = dataset.make_order(self.rng, self.state["next_order_id"], "UNPAID", now)
            self.state["next_order_id"] += 1
            self.state["orders"].insert(0, order)
        elif choice == "pay_order":
            unpaid = [o for o in self.state["orders"] if o["status"] == "UNPAID"]
            if unpaid:
                order = self.rng.choice(unpaid)
                order["status"], order["paid_at"] = "PAID", now.isoformat()
        elif choice == "complete":
            shipped = [o for o in self.state["orders"] if o["status"] == "SHIPPED"]
            if shipped:
                self.rng.choice(shipped)["status"] = "COMPLETED"
        elif choice == "message":
            convo = self.rng.choice(self.state["conversations"])
            self._append_message(
                convo,
                "INBOUND",
                convo["buyer_name"],
                self.rng.choice(dataset.INBOUND_OPENERS + dataset.INBOUND_FOLLOWUPS),
            )
        elif choice == "new_cart":
            cart = dataset.make_cart(self.rng, self.state["next_cart_id"], "TO_PAY", now)
            self.state["next_cart_id"] += 1
            self.state["carts"].insert(0, cart)
        elif choice == "pay_cart":
            to_pay = [c for c in self.state["carts"] if c["status"] == "TO_PAY"]
            if to_pay:
                self.rng.choice(to_pay)["status"] = "PAID"
        log.info("mock activity", extra={"kind": choice})

    def _append_message(
        self, convo: dict[str, Any], direction: str, sender: str, body: str
    ) -> dict[str, Any]:
        message = {
            "cardmarket_id": f"M{self.state['next_message_id']}",
            "direction": direction,
            "sender": sender,
            "body": body,
            "sent_at": _now().isoformat(),
        }
        self.state["next_message_id"] += 1
        convo["messages"].append(message)
        convo["unread"] = direction == "INBOUND"
        return message

    def _maybe_fail(self) -> None:
        if self._fail_next_sync:
            self._fail_next_sync = False
            raise CardmarketChangedError(
                "mock: simulated sync error (page structure not recognised)"
            )

    # ------------------------------------------------------------------ reads

    async def list_orders(self) -> list[NormalizedOrderSummary]:
        self._require_auth()
        self._maybe_fail()
        self._evolve()
        self._save()
        await self._latency()
        return [self._order_summary(o) for o in self.state["orders"]]

    @staticmethod
    def _order_summary(o: dict[str, Any]) -> NormalizedOrderSummary:
        return NormalizedOrderSummary(
            cardmarket_id=o["cardmarket_id"],
            buyer_name=o["buyer_name"],
            status=o["status"],
            total_amount=o["total_amount"],
            currency=o["currency"],
            item_count=sum(i["quantity"] for i in o["items"]),
            order_date=o["order_date"],
            source_url=f"mock://orders/{o['cardmarket_id']}",
        )

    def _find(self, kind: str, cm_id: str) -> dict[str, Any]:
        for record in self.state[kind]:
            if record["cardmarket_id"] == cm_id:
                return dict(record)
        raise SelectorNotFoundError(f"mock: {kind} {cm_id} not found")

    async def get_order(self, summary: NormalizedOrderSummary) -> NormalizedOrder:
        self._require_auth()
        await self._latency()
        o = self._find("orders", summary.cardmarket_id)
        base = self._order_summary(o)
        return NormalizedOrder(
            **base.model_dump(),
            payment_status=derive_payment_status(base.status),
            shipping_status=derive_shipping_status(base.status),
            paid_at=o.get("paid_at"),
            shipped_at=o.get("shipped_at"),
            tracking_number=o.get("tracking_number"),
            items=o["items"],
        )

    @staticmethod
    def _convo_summary(c: dict[str, Any]) -> NormalizedConversationSummary:
        last = c["messages"][-1] if c["messages"] else None
        return NormalizedConversationSummary(
            cardmarket_id=c["cardmarket_id"],
            buyer_name=c["buyer_name"],
            order_cardmarket_id=c.get("order_cardmarket_id"),
            unread=c.get("unread", False),
            last_message_at=last["sent_at"] if last else None,
            last_message_preview=last["body"][:140] if last else None,
            source_url=f"mock://threads/{c['cardmarket_id']}",
        )

    async def list_conversations(self) -> list[NormalizedConversationSummary]:
        self._require_auth()
        await self._latency()
        return [self._convo_summary(c) for c in self.state["conversations"]]

    async def get_conversation(
        self, summary: NormalizedConversationSummary
    ) -> NormalizedConversation:
        self._require_auth()
        await self._latency()
        c = self._find("conversations", summary.cardmarket_id)
        base = self._convo_summary(c)
        return NormalizedConversation(**base.model_dump(), messages=c["messages"])

    @staticmethod
    def _cart_summary(c: dict[str, Any]) -> NormalizedCartSummary:
        return NormalizedCartSummary(
            cardmarket_id=c["cardmarket_id"],
            buyer_name=c["buyer_name"],
            status=c["status"],
            total_amount=c["total_amount"],
            currency=c["currency"],
            item_count=sum(i["quantity"] for i in c["items"]),
            created_at=c["created_at"],
            source_url=f"mock://carts/{c['cardmarket_id']}",
        )

    async def list_carts(self) -> list[NormalizedCartSummary]:
        self._require_auth()
        await self._latency()
        return [self._cart_summary(c) for c in self.state["carts"]]

    async def get_cart(self, summary: NormalizedCartSummary) -> NormalizedCart:
        self._require_auth()
        await self._latency()
        c = self._find("carts", summary.cardmarket_id)
        return NormalizedCart(**self._cart_summary(c).model_dump(), items=c["items"])

    # ------------------------------------------------------------------ writes

    async def submit_message(
        self, conversation: NormalizedConversationSummary, body: str
    ) -> SendReceipt:
        self._require_auth()
        if "[mock:fail]" in body:
            raise NetworkError("mock: network error before submission")
        if "[mock:unsafe]" in body:
            raise UnsafeUIError("mock: send button not uniquely identified")
        await self._latency()
        if "[mock:unverified]" in body:
            return SendReceipt(submitted=True)  # pretend; it never shows up
        for convo in self.state["conversations"]:
            if convo["cardmarket_id"] == conversation.cardmarket_id:
                message = self._append_message(convo, "OUTBOUND", "shop", body)
                convo["unread"] = False
                if self.rng.random() < 0.3:  # buyers sometimes answer quickly
                    reply = self._append_message(
                        convo,
                        "INBOUND",
                        convo["buyer_name"],
                        self.rng.choice(dataset.INBOUND_FOLLOWUPS),
                    )
                    reply["sent_at"] = (_now() + timedelta(seconds=5)).isoformat()
                self._save()
                return SendReceipt(submitted=True, cardmarket_message_id=message["cardmarket_id"])
        raise SelectorNotFoundError(f"mock: conversation {conversation.cardmarket_id} not found")

    async def submit_mark_shipped(
        self, order: NormalizedOrderSummary, tracking_number: str | None
    ) -> None:
        self._require_auth()
        await self._latency()
        for record in self.state["orders"]:
            if record["cardmarket_id"] == order.cardmarket_id:
                record["status"] = "SHIPPED"
                record["shipped_at"] = _now().isoformat()
                if tracking_number:
                    record["tracking_number"] = tracking_number
                self._save()
                return
        raise SelectorNotFoundError(f"mock: order {order.cardmarket_id} not found")

    async def capture_failure(self, label: str) -> list[str]:
        return []  # nothing to screenshot in mock mode
