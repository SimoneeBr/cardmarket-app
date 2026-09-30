"""Web Push delivery (VAPID). Runs after commit on a small thread pool."""

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_sessionmaker
from app.models import PushSubscription

log = logging.getLogger("cmc.push")

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="push")
PENDING_KEY = "pending_push"


@dataclass(frozen=True)
class PushMessage:
    user_id: int
    title: str
    body: str
    url: str
    tag: str


def queue_push(db: Session, message: PushMessage) -> None:
    """Defer a push until the surrounding transaction commits."""
    db.info.setdefault(PENDING_KEY, []).append(message)


def flush_pending(db: Session) -> None:
    messages: list[PushMessage] = db.info.pop(PENDING_KEY, [])
    if messages and get_settings().push_enabled:
        _executor.submit(_deliver_all, messages)


def discard_pending(db: Session) -> None:
    db.info.pop(PENDING_KEY, None)


def _deliver_all(messages: list[PushMessage]) -> None:
    try:
        with get_sessionmaker()() as db:
            for message in messages:
                subs = db.scalars(
                    select(PushSubscription).where(PushSubscription.user_id == message.user_id)
                ).all()
                for sub in subs:
                    send_to_subscription(db, sub, message)
            db.commit()
    except Exception:
        log.exception("push delivery batch failed")


def send_to_subscription(db: Session, sub: PushSubscription, message: PushMessage) -> bool:
    from pywebpush import WebPushException, webpush

    settings = get_settings()
    payload = json.dumps(
        {"title": message.title, "body": message.body, "url": message.url, "tag": message.tag}
    )
    try:
        webpush(
            subscription_info={
                "endpoint": sub.endpoint,
                "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
            },
            data=payload,
            vapid_private_key=settings.vapid_private_key.get_secret_value(),
            vapid_claims={"sub": settings.vapid_subject},
            timeout=10,
        )
        return True
    except WebPushException as exc:
        status_code = getattr(exc.response, "status_code", None)
        if status_code in (404, 410):
            # Subscription expired or revoked by the browser: forget it.
            db.execute(delete(PushSubscription).where(PushSubscription.id == sub.id))
            log.info("push subscription removed", extra={"subscription_id": sub.id})
        else:
            log.warning("push failed", extra={"subscription_id": sub.id, "status": status_code})
        return False
