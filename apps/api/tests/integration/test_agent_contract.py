"""Contract test: the REAL agent runner (mock adapter) against the REAL API.

The agent talks HTTP to the FastAPI app through an in-process ASGI transport,
and the API writes to PostgreSQL: this covers the whole
frontend-API -> queue -> agent -> "Cardmarket" -> verify -> DB loop.
Skipped when the agent package is not installed in this environment.
"""

from pathlib import Path

import httpx
import pytest
from cmc_shared.enums import UserRole
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Cart, Conversation, Message, Notification, Order
from tests.conftest import AGENT_TOKEN, login, make_user

agent_config = pytest.importorskip("agent.config")
from agent.api_client import ApiClient  # noqa: E402
from agent.mock.adapter import MockCardmarketAdapter  # noqa: E402
from agent.runner import AgentRunner  # noqa: E402


@pytest.fixture
async def runner(db: Session, tmp_path: Path) -> AgentRunner:
    from app.main import app

    settings = agent_config.AgentSettings(
        environment="test",
        agent_api_token=AGENT_TOKEN,
        agent_id="agent-contract",
        mock_cardmarket=True,
        mock_state_file=tmp_path / "state.json",
        mock_auto_pair=True,
        mock_pairing_delay_seconds=0.01,
        mock_activity_rate=0.0,
        heartbeat_seconds=0,
        max_details_per_sync=100,
    )
    api = ApiClient("http://api", AGENT_TOKEN, transport=httpx.ASGITransport(app=app))
    adapter = MockCardmarketAdapter(settings)
    await adapter.start()
    r = AgentRunner(settings, api, adapter)
    await r._bootstrap()
    return r


def _count(db: Session, model: type) -> int:
    db.expire_all()
    return int(db.scalar(select(func.count()).select_from(model)) or 0)


async def test_full_loop(runner: AgentRunner, client: TestClient, db: Session) -> None:
    admin = make_user(db, UserRole.ADMIN)
    login(client, admin)

    # 1. first cycle: initial import of the whole mock marketplace
    await runner.tick()
    assert _count(db, Order) == 24
    assert _count(db, Conversation) == 12
    assert _count(db, Cart) == 12
    assert _count(db, Notification) == 0  # initial import is silent
    dashboard = client.get("/api/dashboard").json()
    assert dashboard["connection"]["status"] == "CONNECTED"
    assert dashboard["connection"]["agent_online"] is True

    # 2. a user sends a message: queued -> executed -> verified -> SENT
    convo_id = client.get("/api/conversations").json()["items"][0]["id"]
    res = client.post(
        f"/api/conversations/{convo_id}/messages",
        json={"body": "Spediamo domani!", "client_key": "contract-1"},
    )
    assert res.json()["status"] == "PENDING"
    await runner.tick()
    messages = client.get(f"/api/conversations/{convo_id}").json()["messages"]
    sent = [m for m in messages if m["body"] == "Spediamo domani!"]
    assert len(sent) == 1 and sent[0]["status"] == "SENT"

    # the following sync sees the message on "Cardmarket" and does not duplicate it
    runner.sync_now = True
    await runner.tick()
    db.expire_all()
    assert db.scalar(select(func.count(Message.id)).where(Message.body == "Spediamo domani!")) == 1

    # 3. session expires on Cardmarket -> detected, admins notified, writes wait
    assert (
        client.post("/api/admin/simulate", json={"scenario": "session_expired"}).status_code == 200
    )
    await runner.tick()
    status = client.get("/api/connection/status").json()
    assert status["status"] in ("AUTH_REQUIRED", "SESSION_EXPIRED")
    notif = client.get("/api/notifications").json()["items"]
    assert any(n["type"] == "SESSION_EXPIRED" for n in notif)

    client.post(
        f"/api/conversations/{convo_id}/messages",
        json={"body": "in coda", "client_key": "contract-2"},
    )
    await runner.tick()
    queued = [
        m
        for m in client.get(f"/api/conversations/{convo_id}").json()["messages"]
        if m["body"] == "in coda"
    ]
    assert queued[0]["status"] == "PENDING"  # not attempted without a session

    # 4. admin re-pairs -> CONNECTED -> the queued message is delivered
    assert client.post("/api/connection/pair").status_code == 202
    await runner.tick()
    await runner.tick()
    assert client.get("/api/connection/status").json()["status"] == "CONNECTED"
    delivered = [
        m
        for m in client.get(f"/api/conversations/{convo_id}").json()["messages"]
        if m["body"] == "in coda"
    ]
    assert delivered[0]["status"] == "SENT"


async def test_mark_shipped_through_agent(
    runner: AgentRunner, client: TestClient, db: Session
) -> None:
    login(client, make_user(db, UserRole.STAFF))
    await runner.tick()
    order = client.get("/api/orders", params={"filter": "to_ship"}).json()["items"][0]
    assert (
        client.post(
            f"/api/orders/{order['id']}/ship",
            json={"tracking_number": "RR9IT", "client_key": "ship-contract"},
        ).status_code
        == 202
    )
    await runner.tick()
    detail = client.get(f"/api/orders/{order['id']}").json()
    assert detail["status"] == "SHIPPED" and detail["tracking_number"] == "RR9IT"
    assert detail["pending_action"] is None
