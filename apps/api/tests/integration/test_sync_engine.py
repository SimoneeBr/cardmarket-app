from cmc_shared.enums import UserRole
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import DomainEvent, Message, Notification, Order
from tests.conftest import AgentSim, agent_headers, make_user, order_detail, order_summary, ts


def _events(db: Session) -> list[str]:
    return [e.type.value for e in db.scalars(select(DomainEvent).order_by(DomainEvent.id))]


def _notifications(db: Session) -> int:
    return int(db.scalar(select(func.count(Notification.id))) or 0)


def test_agent_endpoints_require_token(client: TestClient) -> None:
    res = client.post("/internal/agent/heartbeat", json={})
    assert res.status_code == 401
    res = client.post(
        "/internal/agent/heartbeat", json={}, headers={"Authorization": "Bearer wrong"}
    )
    assert res.status_code == 401


def test_sync_refused_when_not_connected(client: TestClient) -> None:
    res = client.post("/internal/agent/sync/start", json={"agent_id": "a"}, headers=agent_headers())
    assert res.json()["granted"] is False


def test_sync_lock_prevents_concurrent_runs(client: TestClient, agent: AgentSim) -> None:
    agent.connect()
    agent.start()
    other = client.post(
        "/internal/agent/sync/start", json={"agent_id": "another-agent"}, headers=agent_headers()
    )
    assert other.json()["granted"] is False
    agent.complete()
    again = client.post(
        "/internal/agent/sync/start", json={"agent_id": "another-agent"}, headers=agent_headers()
    )
    assert again.json()["granted"] is True


def test_initial_import_records_events_without_notifications(db: Session, agent: AgentSim) -> None:
    make_user(db, UserRole.ADMIN)
    agent.connect()
    agent.full_sync(orders={"summaries": [order_summary("1001"), order_summary("1002", "PAID")]})
    assert _events(db).count("OrderCreated") == 2
    assert _notifications(db) == 0
    # Initial orders are not flagged as "new".
    assert all(not o.is_new for o in db.scalars(select(Order)))


def test_incremental_sync_generates_events_and_notifications(db: Session, agent: AgentSim) -> None:
    admin = make_user(db, UserRole.ADMIN)
    staff = make_user(db, UserRole.STAFF)
    agent.connect()
    agent.full_sync(orders={"summaries": [order_summary("1001")]})

    data = agent.start()
    assert "1001" in data["known_orders"]
    result = agent.orders(
        summaries=[order_summary("1001", "PAID"), order_summary("1003")],
        details=[order_detail("1003")],
    )
    agent.complete()
    assert result["records_changed"] == 2
    evts = _events(db)
    assert evts[-2:] == ["OrderPaid", "OrderCreated"] or set(evts[-2:]) == {
        "OrderPaid",
        "OrderCreated",
    }
    paid = db.scalar(select(Order).where(Order.cardmarket_id == "1001"))
    assert paid is not None and paid.payment_status.value == "PAID" and paid.paid_at is not None
    new = db.scalar(select(Order).where(Order.cardmarket_id == "1003"))
    assert new is not None and new.is_new and len(new.items) == 2
    # One notification per event per recipient (admin + staff for order events).
    per_user = dict(
        db.execute(select(Notification.user_id, func.count()).group_by(Notification.user_id)).all()
    )
    assert per_user == {admin.id: 2, staff.id: 2}


def test_resending_same_batch_is_idempotent(db: Session, agent: AgentSim) -> None:
    agent.connect()
    agent.full_sync(orders={"summaries": [order_summary("1")], "details": [order_detail("1")]})
    before = _events(db)
    agent.start()
    result = agent.orders(summaries=[order_summary("1")])
    agent.complete()
    assert result["records_changed"] == 0
    assert _events(db) == before
    assert db.scalar(select(func.count(Order.id))) == 1


def test_status_regression_is_generic_change(db: Session, agent: AgentSim) -> None:
    agent.connect()
    agent.full_sync(orders={"summaries": [order_summary("1", "SHIPPED")]})
    agent.full_sync(orders={"summaries": [order_summary("1", "PAID")]})
    assert _events(db)[-1] == "OrderStatusChanged"


def _conv(cm_id: str, messages: list[dict[str, str]], **kw: str) -> dict[str, object]:
    return {
        "cardmarket_id": cm_id,
        "buyer_name": "luca",
        "order_cardmarket_id": kw.get("order"),
        "unread": True,
        "last_message_at": messages[-1]["sent_at"] if messages else None,
        "messages": messages,
    }


def _msg(i: str, direction: str, body: str, day: int, hour: int = 10) -> dict[str, str]:
    return {
        "cardmarket_id": i,
        "direction": direction,
        "sender": "luca" if direction == "INBOUND" else "shop",
        "body": body,
        "sent_at": ts(day, hour),
    }


def test_conversations_merge_link_and_notify(db: Session, agent: AgentSim) -> None:
    make_user(db, UserRole.STAFF)
    agent.connect()
    agent.full_sync(
        conversations={"details": [_conv("c1", [_msg("m1", "INBOUND", "Ciao", 20)], order="1001")]}
    )
    assert _notifications(db) == 0  # initial import
    agent.full_sync(orders={"summaries": [order_summary("1001", "PAID")]})
    agent.full_sync(
        conversations={
            "details": [
                _conv(
                    "c1",
                    [
                        _msg("m1", "INBOUND", "Ciao", 20),
                        _msg("m2", "INBOUND", "Quando spedite?", 21),
                    ],
                    order="1001",
                )
            ]
        }
    )
    assert db.scalar(select(func.count(Message.id))) == 2
    assert _events(db).count("MessageReceived") == 2
    # One for the order created after the initial import, one for the new message.
    types = sorted(n.type.value for n in db.scalars(select(Notification)))
    assert types == ["MESSAGE_RECEIVED", "ORDER_CREATED"]
    convo_order = db.scalar(select(Order).where(Order.cardmarket_id == "1001"))
    from app.models import Conversation

    convo = db.scalar(select(Conversation))
    assert convo is not None and convo_order is not None
    assert convo.order_id == convo_order.id  # linked once the order was synced
    assert convo.unread is True
    assert convo.last_message_preview == "Quando spedite?"


def test_outbound_reply_on_cardmarket_clears_unread(db: Session, agent: AgentSim) -> None:
    agent.connect()
    agent.full_sync(conversations={"details": [_conv("c1", [_msg("m1", "INBOUND", "Ciao", 20)])]})
    agent.full_sync(
        conversations={
            "details": [
                _conv(
                    "c1", [_msg("m1", "INBOUND", "Ciao", 20), _msg("m2", "OUTBOUND", "Eccomi", 21)]
                )
            ]
        }
    )
    from app.models import Conversation

    convo = db.scalar(select(Conversation))
    assert convo is not None and convo.unread is False


def test_carts_created_and_paid(db: Session, agent: AgentSim) -> None:
    make_user(db, UserRole.ADMIN)
    cart = {
        "cardmarket_id": "k1",
        "buyer_name": "anna",
        "status": "TO_PAY",
        "total_amount": "30.00",
        "item_count": 3,
    }
    agent.connect()
    agent.full_sync(carts={"summaries": [{**cart, "cardmarket_id": "k0"}]})  # initial import
    agent.full_sync(carts={"summaries": [cart]})
    agent.full_sync(carts={"summaries": [{**cart, "status": "PAID"}]})
    assert _events(db)[-2:] == ["CartCreated", "CartPaid"]
    assert _notifications(db) == 2


def test_failed_sync_notifies_once_per_streak(db: Session, agent: AgentSim) -> None:
    make_user(db, UserRole.ADMIN)
    agent.connect()
    agent.full_sync()
    for _ in range(3):
        agent.start()
        agent.complete("FAILED", error_code="NETWORK_ERROR", error_message="timeout")
    assert _events(db).count("SyncFailed") == 1
    assert _notifications(db) == 1


def test_session_expired_notifies_admins(db: Session, client: TestClient, agent: AgentSim) -> None:
    admin = make_user(db, UserRole.ADMIN)
    staff = make_user(db, UserRole.STAFF)
    agent.connect()
    agent.post(
        "/session",
        {"status": "SESSION_EXPIRED", "error_code": "AUTH_ERROR", "message": "login page shown"},
    )
    recipients = set(db.scalars(select(Notification.user_id)))
    assert recipients == {admin.id}
    assert staff.id not in recipients
    # Sync is refused while the session is expired.
    res = client.post("/internal/agent/sync/start", json={"agent_id": "a"}, headers=agent_headers())
    assert res.json()["granted"] is False


def test_admin_disconnect_is_not_undone_by_agent(admin_client: TestClient, agent: AgentSim) -> None:
    agent.connect()
    assert admin_client.post("/api/connection/disconnect").json()["status"] == "DISCONNECTED"
    res = agent.post("/session", {"status": "CONNECTED", "authenticated": True})
    assert res["sync_enabled"] is False
    assert admin_client.get("/api/connection/status").json()["status"] == "DISCONNECTED"
    # An explicit reconnect request lets the agent's report through.
    admin_client.post("/api/connection/reconnect")
    agent.post("/session", {"status": "CONNECTED", "authenticated": True})
    assert admin_client.get("/api/connection/status").json()["status"] == "CONNECTED"


BLOCKED = {
    "status": "ERROR",
    "error_code": "ACCESS_BLOCKED",
    "message": "Access blocked by Cloudflare before reaching Cardmarket; "
    "session state unknown (Cloudflare Ray ID a43632d17d8bea6f)",
}


def test_access_blocked_is_persisted_and_stops_automatic_sync(
    db: Session, client: TestClient, agent: AgentSim
) -> None:
    make_user(db, UserRole.ADMIN)
    agent.connect()
    res = agent.post("/session", BLOCKED)
    assert res["access_blocked"] is True and res["sync_enabled"] is False
    # survives an agent restart: every heartbeat keeps saying "blocked"
    hb = agent.post(
        "/heartbeat",
        {"agent_id": "agent-test", "version": "t", "mode": "LIVE", "connection_status": "ERROR"},
    )
    assert hb["access_blocked"] is True and hb["sync_enabled"] is False
    start = client.post(
        "/internal/agent/sync/start", json={"agent_id": "a"}, headers=agent_headers()
    )
    assert start.json()["granted"] is False
    # admins see the reason (with Ray ID) and are notified exactly once
    agent.post("/session", BLOCKED)
    agent.post("/session", BLOCKED)
    notes = db.scalars(select(Notification)).all()
    assert (
        len(notes) == 1
        and "ACCESS_BLOCKED" in notes[0].body
        and "a43632d17d8bea6f" in notes[0].body
    )


def test_access_blocked_clears_only_on_explicit_session_result(
    admin_client: TestClient, agent: AgentSim
) -> None:
    agent.connect()
    agent.post("/session", BLOCKED)
    status = admin_client.get("/api/connection/status").json()
    assert (status["status"], status["last_error_code"]) == ("ERROR", "ACCESS_BLOCKED")
    assert "a43632d17d8bea6f" in status["last_error"]
    # explicit operator action: reconnect -> the agent reports CONNECTED
    assert admin_client.post("/api/connection/reconnect").status_code == 202
    res = agent.post("/session", {"status": "CONNECTED", "authenticated": True})
    assert res["access_blocked"] is False and res["sync_enabled"] is True


def test_other_errors_do_not_set_access_blocked(agent: AgentSim) -> None:
    agent.connect()
    for code in ("CARDMARKET_CHANGED", "NETWORK_ERROR"):
        res = agent.post("/session", {"status": "ERROR", "error_code": code, "message": "x"})
        assert res["access_blocked"] is False
    res = agent.post("/session", {"status": "SESSION_EXPIRED", "error_code": "AUTH_ERROR"})
    assert res["access_blocked"] is False


def test_blocked_sync_run_is_not_double_notified(db: Session, agent: AgentSim) -> None:
    make_user(db, UserRole.ADMIN)
    agent.connect()
    agent.full_sync()
    agent.start()
    agent.post("/session", BLOCKED)  # block detected mid-sync
    agent.complete("FAILED", error_code="ACCESS_BLOCKED", error_message=BLOCKED["message"])
    assert _notifications(db) == 1
