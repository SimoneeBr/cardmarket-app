from typing import Annotated

from cmc_shared.enums import NotificationType
from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import delete, func, select, update

from app.config import get_settings
from app.deps import CurrentUser, DbSession
from app.models import Notification, NotificationPreference, PushSubscription
from app.schemas import (
    NotificationOut,
    NotificationPreferenceOut,
    NotificationPreferencesUpdate,
    OkResponse,
    Page,
    PushConfigOut,
    PushSubscriptionIn,
)
from app.services.notifications import effective_preferences, link_for
from app.services.push import PushMessage, send_to_subscription

router = APIRouter(prefix="/api", tags=["notifications"])


def _out(n: Notification) -> NotificationOut:
    return NotificationOut(
        id=n.id,
        type=n.type,
        title=n.title,
        body=n.body,
        entity_type=n.entity_type,
        entity_id=n.entity_id,
        read=n.read,
        created_at=n.created_at,
        link=link_for(n.entity_type, n.entity_id, n.type),
    )


@router.get("/notifications", response_model=Page[NotificationOut])
def list_notifications(
    db: DbSession,
    user: CurrentUser,
    unread_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[NotificationOut]:
    stmt = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        stmt = stmt.where(Notification.read.is_(False))
    total = int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    rows = db.scalars(
        stmt.order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return Page(items=[_out(n) for n in rows], total=total, limit=limit, offset=offset)


@router.get("/notifications/unread-count")
def unread_count(db: DbSession, user: CurrentUser) -> dict[str, int]:
    count = db.scalar(
        select(func.count(Notification.id)).where(
            Notification.user_id == user.id, Notification.read.is_(False)
        )
    )
    return {"unread": int(count or 0)}


@router.post("/notifications/{notification_id}/read", response_model=OkResponse)
def mark_read(notification_id: int, db: DbSession, user: CurrentUser) -> OkResponse:
    result = db.execute(
        update(Notification)
        .where(Notification.id == notification_id, Notification.user_id == user.id)
        .values(read=True)
    )
    if not result.rowcount:  # type: ignore[attr-defined]
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notifica non trovata")
    db.commit()
    return OkResponse()


@router.post("/notifications/read-all", response_model=OkResponse)
def mark_all_read(db: DbSession, user: CurrentUser) -> OkResponse:
    db.execute(
        update(Notification)
        .where(Notification.user_id == user.id, Notification.read.is_(False))
        .values(read=True)
    )
    db.commit()
    return OkResponse()


@router.delete("/notifications", response_model=OkResponse)
def clear_read(db: DbSession, user: CurrentUser) -> OkResponse:
    """Delete the user's already-read notifications."""
    db.execute(
        delete(Notification).where(Notification.user_id == user.id, Notification.read.is_(True))
    )
    db.commit()
    return OkResponse()


@router.get("/notification-preferences", response_model=list[NotificationPreferenceOut])
def get_preferences(db: DbSession, user: CurrentUser) -> list[NotificationPreferenceOut]:
    prefs = effective_preferences(db, user)
    return [NotificationPreferenceOut(type=t, in_app=a, push=p) for t, (a, p) in prefs.items()]


@router.put("/notification-preferences", response_model=list[NotificationPreferenceOut])
def update_preferences(
    body: NotificationPreferencesUpdate, db: DbSession, user: CurrentUser
) -> list[NotificationPreferenceOut]:
    stored = {
        p.type: p
        for p in db.scalars(
            select(NotificationPreference).where(NotificationPreference.user_id == user.id)
        )
    }
    for pref in body.preferences:
        row = stored.get(pref.type)
        if row is None:
            db.add(
                NotificationPreference(
                    user_id=user.id,
                    type=pref.type,
                    in_app=pref.in_app,
                    push=pref.push and pref.in_app,
                )
            )
        else:
            row.in_app, row.push = pref.in_app, pref.push and pref.in_app
    db.commit()
    return get_preferences(db, user)


@router.get("/push/config", response_model=PushConfigOut)
def push_config() -> PushConfigOut:
    settings = get_settings()
    return PushConfigOut(
        enabled=settings.push_enabled,
        public_key=settings.vapid_public_key or None,
    )


@router.post("/push/subscriptions", response_model=OkResponse)
def subscribe(body: PushSubscriptionIn, db: DbSession, user: CurrentUser) -> OkResponse:
    p256dh, auth = body.keys.get("p256dh"), body.keys.get("auth")
    if not p256dh or not auth:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Chiavi push mancanti")
    sub = db.scalar(select(PushSubscription).where(PushSubscription.endpoint == body.endpoint))
    if sub is None:
        db.add(PushSubscription(user_id=user.id, endpoint=body.endpoint, p256dh=p256dh, auth=auth))
    else:
        sub.user_id, sub.p256dh, sub.auth = user.id, p256dh, auth
    db.commit()
    return OkResponse()


@router.post("/push/unsubscribe", response_model=OkResponse)
def unsubscribe(body: PushSubscriptionIn, db: DbSession, user: CurrentUser) -> OkResponse:
    db.execute(
        delete(PushSubscription).where(
            PushSubscription.endpoint == body.endpoint, PushSubscription.user_id == user.id
        )
    )
    db.commit()
    return OkResponse()


@router.post("/push/test")
def push_test(db: DbSession, user: CurrentUser) -> dict[str, int]:
    if not get_settings().push_enabled:
        raise HTTPException(status.HTTP_409_CONFLICT, "Web Push non configurato (VAPID)")
    subs = db.scalars(select(PushSubscription).where(PushSubscription.user_id == user.id)).all()
    message = PushMessage(
        user_id=user.id,
        title="Cardmarket Companion",
        body="Notifiche push attive ✅",
        url="/notifications",
        tag=str(NotificationType.ORDER_CREATED),
    )
    delivered = sum(1 for s in subs if send_to_subscription(db, s, message))
    db.commit()
    return {"subscriptions": len(subs), "delivered": delivered}
