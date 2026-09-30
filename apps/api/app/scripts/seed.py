"""Idempotent seed: default templates, connection row, optional users.

Usage::

    python -m app.scripts.seed                 # templates + connection row
    python -m app.scripts.seed --demo-users    # + manager/staff demo users (dev only)

An administrator is created from SEED_ADMIN_EMAIL / SEED_ADMIN_PASSWORD when
both are set; otherwise the web first-run wizard asks for one.
"""

import argparse
import logging
import os
import sys

from cmc_shared.enums import UserRole
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_sessionmaker
from app.models import MessageTemplate, User
from app.security.passwords import hash_password, validate_password_strength
from app.services.connection import get_primary_connection

log = logging.getLogger("cmc.seed")

DEFAULT_TEMPLATES: list[dict[str, str | int]] = [
    {
        "key": "ship_tomorrow",
        "label": "Spedizione domani",
        "icon": "📦",
        "body": "Ciao {{buyer_name}}, grazie per l'ordine #{{order_id}}! "
        "Lo spediremo domani mattina.",
        "position": 0,
    },
    {
        "key": "shipped_tracking",
        "label": "Tracking",
        "icon": "🚚",
        "body": "Ciao {{buyer_name}}, l'ordine #{{order_id}} è stato spedito. "
        "Numero di tracking: {{tracking_number}}.",
        "position": 1,
    },
    {
        "key": "delay",
        "label": "Ritardo",
        "icon": "⏳",
        "body": "Ciao {{buyer_name}}, ci scusiamo: l'ordine #{{order_id}} partirà con un leggero "
        "ritardo. Ti aggiorneremo appena spedito.",
        "position": 2,
    },
    {
        "key": "info_request",
        "label": "Richiesta info",
        "icon": "❓",
        "body": "Ciao {{buyer_name}}, avremmo bisogno di un'informazione sul tuo ordine "
        "#{{order_id}}. Puoi risponderci qui?",
        "position": 3,
    },
    {
        "key": "thanks",
        "label": "Grazie",
        "icon": "🙏",
        "body": "Grazie mille {{buyer_name}}! Speriamo di rivederti presto.",
        "position": 4,
    },
]

DEMO_USERS = [
    ("manager@example.com", "Manager Demo", UserRole.MANAGER, "manager-demo-123"),
    ("staff@example.com", "Staff Demo", UserRole.STAFF, "staff-demo-123"),
]


def seed_templates(db: Session) -> int:
    existing = set(db.scalars(select(MessageTemplate.key)))
    created = 0
    for template in DEFAULT_TEMPLATES:
        if template["key"] not in existing:
            db.add(MessageTemplate(**template, active=True))
            created += 1
    return created


def ensure_user(db: Session, email: str, name: str, role: UserRole, password: str) -> bool:
    if db.scalar(select(User).where(User.email == email.lower())):
        return False
    validate_password_strength(password)
    db.add(
        User(
            email=email.lower(),
            name=name,
            role=role,
            password_hash=hash_password(password),
            active=True,
        )
    )
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo-users", action="store_true", help="create demo manager/staff users")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    with get_sessionmaker()() as db:
        get_primary_connection(db)
        log.info("templates created: %d", seed_templates(db))
        email, password = os.getenv("SEED_ADMIN_EMAIL"), os.getenv("SEED_ADMIN_PASSWORD")
        if (
            email
            and password
            and ensure_user(db, email, "Amministratore", UserRole.ADMIN, password)
        ):
            log.info("admin user created: %s", email)
        if args.demo_users:
            if get_settings().environment == "production":
                log.error("--demo-users is not allowed in production")
                return 1
            for demo in DEMO_USERS:
                if ensure_user(db, *demo):
                    log.info("demo user created: %s", demo[0])
        db.commit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
