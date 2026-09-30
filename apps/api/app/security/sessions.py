"""Opaque server-side sessions stored hashed in the database."""

import hashlib
import hmac
import secrets
from datetime import timedelta

from fastapi import Response
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import utcnow
from app.models import User, UserSession

# Refresh last_seen_at at most this often to avoid a write on every request.
_TOUCH_INTERVAL = timedelta(minutes=5)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(
    db: Session, user: User, settings: Settings, ip: str | None, user_agent: str | None
) -> str:
    token = secrets.token_urlsafe(32)
    now = utcnow()
    db.add(
        UserSession(
            user_id=user.id,
            token_hash=_hash_token(token),
            created_at=now,
            last_seen_at=now,
            expires_at=now + timedelta(hours=settings.session_ttl_hours),
            ip=ip,
            user_agent=(user_agent or "")[:255] or None,
        )
    )
    return token


def resolve_session(db: Session, token: str) -> UserSession | None:
    row = db.scalar(select(UserSession).where(UserSession.token_hash == _hash_token(token)))
    if row is None:
        return None
    now = utcnow()
    if row.expires_at <= now or not row.user.active:
        db.delete(row)
        db.commit()
        return None
    if now - row.last_seen_at > _TOUCH_INTERVAL:
        row.last_seen_at = now
        db.commit()
    return row


def revoke_session(db: Session, token: str) -> None:
    db.execute(delete(UserSession).where(UserSession.token_hash == _hash_token(token)))


def revoke_user_sessions(db: Session, user_id: int) -> None:
    db.execute(delete(UserSession).where(UserSession.user_id == user_id))


def set_auth_cookies(response: Response, token: str, settings: Settings) -> str:
    csrf = secrets.token_urlsafe(24)
    max_age = settings.session_ttl_hours * 3600
    common = {
        "max_age": max_age,
        "secure": settings.cookie_secure,
        "samesite": "lax",
        "domain": settings.cookie_domain,
        "path": "/",
    }
    response.set_cookie(settings.session_cookie_name, token, httponly=True, **common)  # type: ignore[arg-type]
    # Readable by JS on purpose: double-submit CSRF token.
    response.set_cookie(settings.csrf_cookie_name, csrf, httponly=False, **common)  # type: ignore[arg-type]
    return csrf


def clear_auth_cookies(response: Response, settings: Settings) -> None:
    for name in (settings.session_cookie_name, settings.csrf_cookie_name):
        response.delete_cookie(name, path="/", domain=settings.cookie_domain)


def tokens_match(a: str | None, b: str | None) -> bool:
    return bool(a and b) and hmac.compare_digest(str(a), str(b))
