from datetime import timedelta

from cmc_shared.enums import UserRole
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.models import Action, Conversation, Message, Notification, Order
from app.scripts.seed import seed_templates
from tests.conftest import (
    AgentSim,
    agent_headers,
    login,
    make_user,
    order_detail,
    order_summary,
    ts,
)


def _setup_conversation(agent: AgentSim) -> None:
    agent.connect()
    agent.full_sync(
        orders={
            "summaries": [order_summary("1001", "PAID", buyer_name="mario")],
            "details": [order_detail("1001", "PAID", buyer_name="mario")],
        },
        conversations={
            "details": [
                {
                    "cardmarket_id": "c1",
                    "buyer_name": "mario",
                    "order_cardmarket_id": "1001",
                    "unread": True,
                    "last_message_at": ts(29),
                    "messages": [
                        {
                            "cardmarket_id": "m1",
                            "direction": "INBOUND",
                            "sender": "mario",
                            "body": "Quando spedite?",
                            "sent_at": ts(29),
                        }
                    ],
                }
            ]
        },
    )


def _claim(client: TestClient) -> dict | None:
    res = client.post(
        "/internal/agent/actions/claim", json={"agent_id": "agent-test"}, headers=agent_headers()
    )
    return res.json() if res.status_code == 200 else None


def _result(client: TestClient, action_id: int, outcome: str, **kw: object) -> None:
    res = client.post(
        f"/internal/agent/actions/{action_id}/result",
        json={"outcome": outcome, **kw},
        headers=agent_headers(),
    )
    assert res.status_code == 204, res.text


def _send(
    client: TestClient, convo_id: int, body: str = "Spediamo domani", key: str = "client-key-1"
) -> dict:
    res = client.post(
        f"/api/conversations/{convo_id}/messages", json={"body": body, "client_key": key}
    )
    assert res.status_code == 202, res.text
    return res.json()


def test_send_message_full_flow_with_verification(
    admin_client: TestClient, db: Session, agent: AgentSim
) -> None:
    _setup_conversation(agent)
    convo = db.scalar(select(Conversation))
    assert convo is not None
    msg = _send(admin_client, convo.id)
    assert msg["status"] == "PENDING"
    # Resubmitting with the same client key is idempotent.
    again = _send(admin_client, convo.id)
    assert again["id"] == msg["id"]
    assert len(db.scalars(select(Action)).all()) == 1

    claimed = _claim(admin_client)
    assert (
        claimed
        and claimed["type"] == "SEND_MESSAGE"
        and claimed["payload"]["body"] == "Spediamo domani"
    )
    assert claimed["recovery"] is False
    assert _claim(admin_client) is None  # serialized: one action at a time

    _result(admin_client, claimed["id"], "SUCCESS", result={"cardmarket_message_id": "m2"})
    db.expire_all()
    message = db.get(Message, msg["id"])
    assert message is not None and message.status.value == "SENT" and message.cardmarket_id == "m2"

    # The next sync sees the same message on Cardmarket: no duplicate.
    agent.full_sync(
        conversations={
            "details": [
                {
                    "cardmarket_id": "c1",
                    "buyer_name": "mario",
                    "unread": False,
                    "messages": [
                        {
                            "cardmarket_id": "m1",
                            "direction": "INBOUND",
                            "sender": "mario",
                            "body": "Quando spedite?",
                            "sent_at": ts(29),
                        },
                        {
                            "cardmarket_id": "m2",
                            "direction": "OUTBOUND",
                            "sender": "shop",
                            "body": "Spediamo domani",
                            "sent_at": ts(30),
                        },
                    ],
                }
            ]
        }
    )
    assert len(db.scalars(select(Message)).all()) == 2


def test_unverified_send_becomes_unknown_and_needs_attention(
    admin_client: TestClient, db: Session, agent: AgentSim
) -> None:
    _setup_conversation(agent)
    convo = db.scalar(select(Conversation))
    assert convo is not None
    msg = _send(admin_client, convo.id)
    claimed = _claim(admin_client)
    assert claimed
    _result(
        admin_client,
        claimed["id"],
        "UNVERIFIED",
        error_code="VERIFICATION_FAILED",
        error_message="message not found after send",
    )
    db.expire_all()
    assert db.get(Message, msg["id"]).status.value == "UNKNOWN"  # type: ignore[union-attr]
    action = db.get(Action, claimed["id"])
    assert (
        action is not None
        and action.status.value == "NEEDS_ATTENTION"
        and action.needs_verification
    )
    assert db.scalar(select(Notification).where(Notification.type == "ACTION_FAILED")) is not None

    # Retrying keeps the verify-first flag so the agent will not double send.
    res = admin_client.post(f"/api/admin/actions/{claimed['id']}/retry")
    assert res.status_code == 200
    again = _claim(admin_client)
    assert again and again["recovery"] is True


def test_unverified_message_reconciled_by_sync(
    admin_client: TestClient, db: Session, agent: AgentSim
) -> None:
    _setup_conversation(agent)
    convo = db.scalar(select(Conversation))
    assert convo is not None
    msg = _send(admin_client, convo.id, body="Spediamo  domani")
    claimed = _claim(admin_client)
    assert claimed
    _result(admin_client, claimed["id"], "UNVERIFIED")
    agent.full_sync(
        conversations={
            "details": [
                {
                    "cardmarket_id": "c1",
                    "buyer_name": "mario",
                    "messages": [
                        {
                            "cardmarket_id": "m9",
                            "direction": "OUTBOUND",
                            "sender": "shop",
                            "body": "Spediamo domani",
                            "sent_at": ts(30),
                        },
                    ],
                }
            ]
        }
    )
    db.expire_all()
    message = db.get(Message, msg["id"])
    assert message is not None and message.status.value == "SENT" and message.cardmarket_id == "m9"


def test_retry_with_backoff_then_exhaustion(
    admin_client: TestClient, db: Session, agent: AgentSim
) -> None:
    _setup_conversation(agent)
    convo = db.scalar(select(Conversation))
    assert convo is not None
    msg = _send(admin_client, convo.id)
    action_id = None
    for _ in range(5):
        claimed = _claim(admin_client)
        assert claimed, "action should be claimable again (backoff base is 0 in tests)"
        action_id = claimed["id"]
        _result(
            admin_client, action_id, "RETRY", error_code="NETWORK_ERROR", error_message="offline"
        )
    db.expire_all()
    action = db.get(Action, action_id)
    assert action is not None and action.status.value == "FAILED"
    assert db.get(Message, msg["id"]).status.value == "FAILED"  # type: ignore[union-attr]


def test_stale_lease_is_recovered_with_verification(
    admin_client: TestClient, db: Session, agent: AgentSim
) -> None:
    _setup_conversation(agent)
    convo = db.scalar(select(Conversation))
    assert convo is not None
    _send(admin_client, convo.id)
    claimed = _claim(admin_client)
    assert claimed
    # Simulate agent crash: lease expires.
    action = db.get(Action, claimed["id"])
    assert action is not None
    action.lease_expires_at = utcnow() - timedelta(seconds=1)
    db.commit()
    reclaimed = _claim(admin_client)
    assert reclaimed and reclaimed["id"] == claimed["id"] and reclaimed["recovery"] is True
    assert reclaimed["attempts"] == 2


def test_write_actions_wait_for_session(
    admin_client: TestClient, db: Session, agent: AgentSim
) -> None:
    _setup_conversation(agent)
    convo = db.scalar(select(Conversation))
    assert convo is not None
    _send(admin_client, convo.id)
    agent.post("/session", {"status": "SESSION_EXPIRED"})
    assert _claim(admin_client) is None
    res = admin_client.post("/api/connection/pair")
    assert res.status_code == 202
    claimed = _claim(admin_client)
    assert claimed and claimed["type"] == "PAIR_SESSION"


def test_ship_order_flow(admin_client: TestClient, db: Session, agent: AgentSim) -> None:
    _setup_conversation(agent)
    order = db.scalar(select(Order))
    assert order is not None
    res = admin_client.post(
        f"/api/orders/{order.id}/ship",
        json={"tracking_number": "RR123IT", "client_key": "ship-key-1"},
    )
    assert res.status_code == 202
    # Local status does not change before verification.
    db.expire_all()
    assert db.get(Order, order.id).status.value == "PAID"  # type: ignore[union-attr]
    claimed = _claim(admin_client)
    assert claimed and claimed["payload"]["tracking_number"] == "RR123IT"
    _result(admin_client, claimed["id"], "SUCCESS")
    db.expire_all()
    shipped = db.get(Order, order.id)
    assert (
        shipped is not None
        and shipped.status.value == "SHIPPED"
        and shipped.tracking_number == "RR123IT"
    )
    again = admin_client.post(f"/api/orders/{order.id}/ship", json={"client_key": "ship-key-2"})
    assert again.status_code == 409


def test_orders_api_filters_search_and_ack(admin_client: TestClient, agent: AgentSim) -> None:
    agent.connect()
    agent.full_sync(orders={"summaries": [order_summary("0")]})  # initial import
    agent.full_sync(
        orders={
            "summaries": [
                order_summary("1001", "UNPAID", buyer_name="alice"),
                order_summary("1002", "PAID", buyer_name="bob"),
                order_summary("1003", "SHIPPED", buyer_name="carol"),
            ],
            "details": [order_detail("1002", "PAID", buyer_name="bob")],
        }
    )

    def ids(**params: str) -> list[str]:
        return [
            o["cardmarket_id"]
            for o in admin_client.get("/api/orders", params=params).json()["items"]
        ]

    assert set(ids(filter="to_ship")) == {"1002"}
    assert set(ids(filter="paid")) == {"1002", "1003"}
    assert set(ids(filter="unpaid")) == {"1001", "0"}
    assert set(ids(filter="new")) == {"1001", "1002", "1003"}
    assert ids(q="bob") == ["1002"]
    assert ids(q="lightning") == ["1002"]  # search by card name
    page = admin_client.get("/api/orders", params={"limit": 2}).json()
    assert page["total"] == 4 and len(page["items"]) == 2
    order_id = admin_client.get("/api/orders", params={"q": "bob"}).json()["items"][0]["id"]
    detail = admin_client.get(f"/api/orders/{order_id}").json()
    assert detail["is_new"] and len(detail["items"]) == 2
    assert admin_client.post(f"/api/orders/{order_id}/acknowledge").json()["is_new"] is False


def test_dashboard_counts(admin_client: TestClient, agent: AgentSim) -> None:
    _setup_conversation(agent)
    agent.full_sync(
        orders={"summaries": [order_summary("2001", "PAID", order_date=utcnow().isoformat())]},
        carts={"summaries": [{"cardmarket_id": "k1", "buyer_name": "anna", "status": "TO_PAY"}]},
    )
    data = admin_client.get("/api/dashboard").json()
    assert data["connection"]["status"] == "CONNECTED"
    assert data["connection"]["agent_online"] is True
    assert data["orders"]["to_ship"] == 2
    assert data["orders"]["new"] == 1
    assert data["messages"]["unread_conversations"] == 1
    assert data["carts"]["to_pay"] == 1
    assert data["sales"]["by_currency"][0]["orders"] >= 1
    assert any(a["type"] == "OrderCreated" for a in data["activity"])


def test_notifications_api(client: TestClient, db: Session, agent: AgentSim) -> None:
    user = make_user(db, UserRole.STAFF)
    login(client, user)
    agent.connect()
    agent.full_sync(orders={"summaries": [order_summary("0")]})
    agent.full_sync(orders={"summaries": [order_summary("1"), order_summary("2")]})
    assert client.get("/api/notifications/unread-count").json()["unread"] == 2
    items = client.get("/api/notifications").json()["items"]
    assert items[0]["link"].startswith("/orders/")
    assert client.post(f"/api/notifications/{items[0]['id']}/read").status_code == 200
    assert client.get("/api/notifications/unread-count").json()["unread"] == 1
    client.post("/api/notifications/read-all")
    assert client.get("/api/notifications/unread-count").json()["unread"] == 0
    client.delete("/api/notifications")
    assert client.get("/api/notifications").json()["total"] == 0

    prefs = client.get("/api/notification-preferences").json()
    assert {p["type"] for p in prefs} >= {"ORDER_CREATED", "SESSION_EXPIRED"}
    client.put(
        "/api/notification-preferences",
        json={"preferences": [{"type": "ORDER_CREATED", "in_app": False, "push": False}]},
    )
    agent.full_sync(orders={"summaries": [order_summary("3")]})
    assert client.get("/api/notifications/unread-count").json()["unread"] == 0


def test_templates_render_and_validation(
    admin_client: TestClient, db: Session, agent: AgentSim
) -> None:
    seed_templates(db)
    db.commit()
    _setup_conversation(agent)
    convo = db.scalar(select(Conversation))
    assert convo is not None
    templates = admin_client.get("/api/templates").json()
    tracking = next(t for t in templates if t["key"] == "shipped_tracking")
    out = admin_client.post(
        f"/api/templates/{tracking['id']}/render", json={"conversation_id": convo.id}
    ).json()
    assert "mario" in out["text"] and "#1001" in out["text"]
    assert out["missing_variables"] == ["tracking_number"]
    bad = admin_client.post("/api/templates", json={"key": "x", "label": "X", "body": "{{secret}}"})
    assert bad.status_code == 422


def test_simulation_and_purge(admin_client: TestClient, db: Session, agent: AgentSim) -> None:
    _setup_conversation(agent)
    assert (
        admin_client.post("/api/admin/simulate", json={"scenario": "session_expired"}).status_code
        == 200
    )
    hb = agent.post(
        "/heartbeat",
        {
            "agent_id": "agent-test",
            "version": "t",
            "mode": "MOCK",
            "connection_status": "CONNECTED",
        },
    )
    assert hb["commands"][0]["type"] == "SIMULATE_SESSION_EXPIRED"
    assert (
        agent.post(
            "/heartbeat",
            {
                "agent_id": "agent-test",
                "version": "t",
                "mode": "MOCK",
                "connection_status": "CONNECTED",
            },
        )["commands"]
        == []
    )
    assert admin_client.post("/api/admin/data/purge", json={"confirm": "no"}).status_code == 400
    res = admin_client.post("/api/admin/data/purge", json={"confirm": "ELIMINA DATI"})
    assert res.status_code == 200 and res.json()["orders"] == 1
    assert admin_client.get("/api/orders").json()["total"] == 0
