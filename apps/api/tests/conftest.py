"""Test fixtures.

Integration tests run against a real PostgreSQL (``TEST_DATABASE_URL``,
default: the docker container started by ``scripts/test-db.sh``). The schema
is created through the Alembic migrations, so migrations are tested too.
"""

import os
import secrets
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

TEST_DB = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://cmc:cmc@localhost:55432/cmc_test"
)
AGENT_TOKEN = "test-agent-token-" + "x" * 32

os.environ.update(
    {
        "ENVIRONMENT": "test",
        "DATABASE_URL": TEST_DB,
        "AGENT_API_TOKEN": AGENT_TOKEN,
        "COOKIE_SECURE": "false",
        "LOG_FORMAT": "console",
        "LOG_LEVEL": "WARNING",
        "MOCK_CARDMARKET": "true",
        "ACTION_BACKOFF_BASE_SECONDS": "0",
    }
)

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from cmc_shared.enums import UserRole  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import get_engine, get_sessionmaker  # noqa: E402
from app.models import Base, User  # noqa: E402
from app.security.passwords import hash_password  # noqa: E402
from app.security.rate_limit import limiter  # noqa: E402

API_DIR = os.path.dirname(os.path.dirname(__file__))
PASSWORD = "correct-horse-42"


def _db_available() -> bool:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def migrated_db() -> Iterator[None]:
    if not _db_available():
        pytest.skip(f"PostgreSQL not reachable at {TEST_DB} (run scripts/test-db.sh)")
    with get_engine().begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    cfg = Config(os.path.join(API_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(API_DIR, "migrations"))
    command.upgrade(cfg, "head")
    yield


@pytest.fixture
def db(migrated_db: None) -> Iterator[Session]:
    tables = ", ".join(f'"{t.name}"' for t in reversed(Base.metadata.sorted_tables))
    with get_engine().begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    limiter.clear()
    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db: Session) -> Iterator[TestClient]:
    from app.main import app

    with TestClient(app) as c:
        yield c


def make_user(
    db: Session, role: UserRole = UserRole.ADMIN, email: str | None = None, active: bool = True
) -> User:
    user = User(
        email=email or f"{role.lower()}-{secrets.token_hex(3)}@example.com",
        name=f"{role.title()} User",
        role=role,
        password_hash=hash_password(PASSWORD),
        active=active,
    )
    db.add(user)
    db.commit()
    return user


def login(client: TestClient, user: User) -> TestClient:
    res = client.post("/api/auth/login", json={"email": user.email, "password": PASSWORD})
    assert res.status_code == 200, res.text
    client.headers["x-csrf-token"] = client.cookies[get_settings().csrf_cookie_name]
    return client


@pytest.fixture
def admin_client(client: TestClient, db: Session) -> TestClient:
    return login(client, make_user(db, UserRole.ADMIN))


def agent_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {AGENT_TOKEN}"}


def ts(day: int, hour: int = 10) -> str:
    return datetime(2026, 9, day, hour, 0, tzinfo=UTC).isoformat()


def order_summary(cm_id: str, status: str = "UNPAID", **kw: Any) -> dict[str, Any]:
    return {
        "cardmarket_id": cm_id,
        "buyer_name": kw.pop("buyer_name", "mario_rossi"),
        "status": status,
        "total_amount": str(kw.pop("total_amount", Decimal("12.50"))),
        "currency": "EUR",
        "item_count": kw.pop("item_count", 2),
        "order_date": kw.pop("order_date", ts(28)),
        **kw,
    }


def order_detail(cm_id: str, status: str = "UNPAID", **kw: Any) -> dict[str, Any]:
    return {
        **order_summary(cm_id, status, **kw),
        "items": [
            {
                "card_name": "Lightning Bolt",
                "expansion": "M10",
                "language": "English",
                "condition": "NM",
                "quantity": 1,
                "unit_price": "10.00",
                "total_price": "10.00",
            },
            {
                "card_name": "Counterspell",
                "expansion": "MH2",
                "language": "Italian",
                "condition": "EX",
                "quantity": 1,
                "unit_price": "2.50",
                "total_price": "2.50",
            },
        ],
    }


class AgentSim:
    """Drives the internal agent API like the real agent would."""

    def __init__(self, client: TestClient) -> None:
        self.client = client
        self.run_id: int | None = None

    def post(self, path: str, body: dict[str, Any] | None = None) -> Any:
        res = self.client.post(f"/internal/agent{path}", json=body or {}, headers=agent_headers())
        assert res.status_code < 300, res.text
        return res.json() if res.status_code != 204 and res.content else None

    def connect(self) -> None:
        self.post(
            "/heartbeat",
            {
                "agent_id": "agent-test",
                "version": "t",
                "mode": "MOCK",
                "connection_status": "CONNECTED",
            },
        )
        self.post("/session", {"status": "CONNECTED", "authenticated": True})

    def start(self) -> dict[str, Any]:
        data = self.post("/sync/start", {"agent_id": "agent-test"})
        assert data["granted"], data
        self.run_id = data["sync_run_id"]
        return data

    def orders(
        self,
        summaries: list[dict[str, Any]] | None = None,
        details: list[dict[str, Any]] | None = None,
    ) -> Any:
        return self.post(
            f"/sync/{self.run_id}/orders", {"summaries": summaries or [], "details": details or []}
        )

    def conversations(
        self,
        summaries: list[dict[str, Any]] | None = None,
        details: list[dict[str, Any]] | None = None,
    ) -> Any:
        return self.post(
            f"/sync/{self.run_id}/conversations",
            {"summaries": summaries or [], "details": details or []},
        )

    def carts(
        self,
        summaries: list[dict[str, Any]] | None = None,
        details: list[dict[str, Any]] | None = None,
    ) -> Any:
        return self.post(
            f"/sync/{self.run_id}/carts", {"summaries": summaries or [], "details": details or []}
        )

    def complete(self, status: str = "SUCCESS", **kw: Any) -> None:
        self.post(f"/sync/{self.run_id}/complete", {"status": status, **kw})

    def full_sync(self, **batches: Any) -> None:
        self.start()
        if "orders" in batches:
            self.orders(**batches["orders"])
        if "conversations" in batches:
            self.conversations(**batches["conversations"])
        if "carts" in batches:
            self.carts(**batches["carts"])
        self.complete()


@pytest.fixture
def agent(client: TestClient) -> AgentSim:
    return AgentSim(client)
