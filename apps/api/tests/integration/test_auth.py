from cmc_shared.enums import UserRole
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditLog
from tests.conftest import PASSWORD, login, make_user


def test_first_run_setup_creates_admin_once(client: TestClient, db: Session) -> None:
    status = client.get("/api/setup/status").json()
    assert status["needs_admin"] is True
    res = client.post(
        "/api/setup/admin",
        json={"email": "Boss@Shop.it", "name": "Boss", "password": "super-secret-9"},
    )
    assert res.status_code == 201, res.text
    assert res.json()["role"] == "ADMIN"
    assert res.json()["email"] == "boss@shop.it"
    assert client.get("/api/me").status_code == 200  # logged in right away
    assert client.get("/api/setup/status").json()["needs_admin"] is False
    again = client.post(
        "/api/setup/admin", json={"email": "x@y.it", "name": "X", "password": "super-secret-9"}
    )
    assert again.status_code == 409


def test_login_logout_and_audit(client: TestClient, db: Session) -> None:
    user = make_user(db, UserRole.STAFF)
    login(client, user)
    me = client.get("/api/me").json()
    assert me["email"] == user.email
    assert "SEND_MESSAGE" in me["permissions"]
    assert "MANAGE_USERS" not in me["permissions"]
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/me").status_code == 401
    actions = [a.action for a in db.scalars(select(AuditLog).order_by(AuditLog.id))]
    assert actions == ["LOGIN", "LOGOUT"]


def test_wrong_password_and_disabled_user(client: TestClient, db: Session) -> None:
    user = make_user(db, UserRole.STAFF)
    res = client.post("/api/auth/login", json={"email": user.email, "password": "nope-nope-1"})
    assert res.status_code == 401
    disabled = make_user(db, UserRole.STAFF, active=False)
    res = client.post("/api/auth/login", json={"email": disabled.email, "password": PASSWORD})
    assert res.status_code == 401
    assert db.scalar(select(AuditLog).where(AuditLog.action == "LOGIN_FAILED")) is not None


def test_login_rate_limit(client: TestClient, db: Session) -> None:
    user = make_user(db)
    codes = [
        client.post(
            "/api/auth/login", json={"email": user.email, "password": "bad-password-1"}
        ).status_code
        for _ in range(10)
    ]
    assert codes[-1] == 429


def test_csrf_required_for_mutations(client: TestClient, db: Session) -> None:
    login(client, make_user(db))
    token = client.headers.pop("x-csrf-token")
    assert client.post("/api/notifications/read-all").status_code == 403
    client.headers["x-csrf-token"] = token
    assert client.post("/api/notifications/read-all").status_code == 200


def test_session_cookie_flags(client: TestClient, db: Session) -> None:
    user = make_user(db)
    res = client.post("/api/auth/login", json={"email": user.email, "password": PASSWORD})
    cookies = res.headers.get_list("set-cookie")
    session_cookie = next(c for c in cookies if c.startswith("cmc_session="))
    assert "HttpOnly" in session_cookie
    assert "SameSite=lax" in session_cookie


def test_role_enforcement_server_side(client: TestClient, db: Session) -> None:
    login(client, make_user(db, UserRole.STAFF))
    assert client.get("/api/admin/users").status_code == 403
    assert client.get("/api/admin/actions").status_code == 403
    assert client.post("/api/connection/pair").status_code == 403
    assert (
        client.post("/api/templates", json={"key": "k", "label": "l", "body": "b"}).status_code
        == 403
    )
    assert client.get("/api/orders").status_code == 200


def test_manager_cannot_manage_users_or_pair(client: TestClient, db: Session) -> None:
    login(client, make_user(db, UserRole.MANAGER))
    assert client.get("/api/admin/actions").status_code == 200
    assert client.get("/api/admin/users").status_code == 403
    assert client.post("/api/connection/pair").status_code == 403


def test_admin_user_management(admin_client: TestClient, db: Session) -> None:
    res = admin_client.post(
        "/api/admin/users",
        json={"email": "new@shop.it", "name": "New", "role": "STAFF", "password": "welcome-2026"},
    )
    assert res.status_code == 201
    uid = res.json()["id"]
    dup = admin_client.post(
        "/api/admin/users",
        json={"email": "new@shop.it", "name": "New", "role": "STAFF", "password": "welcome-2026"},
    )
    assert dup.status_code == 409
    res = admin_client.patch(f"/api/admin/users/{uid}", json={"role": "MANAGER", "active": False})
    assert res.json()["role"] == "MANAGER" and res.json()["active"] is False
    me = admin_client.get("/api/me").json()
    assert (
        admin_client.patch(f"/api/admin/users/{me['id']}", json={"active": False}).status_code
        == 409
    )
    weak = admin_client.post(
        "/api/admin/users",
        json={"email": "w@shop.it", "name": "W", "role": "STAFF", "password": "aaaaaaaaaaaa"},
    )
    assert weak.status_code == 422


def test_health(client: TestClient) -> None:
    assert client.get("/health/live").json()["status"] == "ok"
    assert client.get("/health/ready").json()["database"] == "ok"
    assert "x-request-id" in client.get("/health/live").headers
