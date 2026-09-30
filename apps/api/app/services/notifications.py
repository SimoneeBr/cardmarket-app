"""Notification engine: domain events -> per-user notifications (+ web push).

Rules are data: which event produces which notification type, the text, the
deep link and the default audience. User preferences override the defaults.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from cmc_shared.enums import DomainEventType, EntityType, NotificationType, UserRole
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.models import DomainEvent, Notification, NotificationPreference, User
from app.services import events
from app.services.push import PushMessage, queue_push

log = logging.getLogger("cmc.notifications")

ALL_ROLES = frozenset(UserRole)
OPERATORS = frozenset({UserRole.ADMIN, UserRole.MANAGER})


@dataclass(frozen=True)
class Rule:
    type: NotificationType
    title: Callable[[dict[str, Any]], str]
    body: Callable[[dict[str, Any]], str]
    link: Callable[[DomainEvent], str]
    default_roles: frozenset[UserRole]


def _money(p: dict[str, Any]) -> str:
    total = p.get("total_amount")
    return f" · {total} {p.get('currency', 'EUR')}" if total is not None else ""


def _order_link(e: DomainEvent) -> str:
    return f"/orders/{e.entity_id}"


def _cart_link(e: DomainEvent) -> str:
    return f"/carts/{e.entity_id}"


RULES: dict[DomainEventType, Rule] = {
    DomainEventType.ORDER_CREATED: Rule(
        NotificationType.ORDER_CREATED,
        lambda p: f"Nuovo ordine #{p.get('cardmarket_id')}",
        lambda p: f"{p.get('buyer_name')}{_money(p)}",
        _order_link,
        ALL_ROLES,
    ),
    DomainEventType.ORDER_PAID: Rule(
        NotificationType.ORDER_PAID,
        lambda p: f"Ordine #{p.get('cardmarket_id')} pagato",
        lambda p: f"{p.get('buyer_name')}{_money(p)} · da spedire",
        _order_link,
        ALL_ROLES,
    ),
    DomainEventType.ORDER_SHIPPED: Rule(
        NotificationType.ORDER_SHIPPED,
        lambda p: f"Ordine #{p.get('cardmarket_id')} spedito",
        lambda p: str(p.get("buyer_name", "")),
        _order_link,
        OPERATORS,
    ),
    DomainEventType.MESSAGE_RECEIVED: Rule(
        NotificationType.MESSAGE_RECEIVED,
        lambda p: f"Messaggio da {p.get('buyer_name')}",
        lambda p: str(p.get("preview", ""))[:140],
        lambda e: f"/chat/{e.payload.get('conversation_id', e.entity_id)}",
        ALL_ROLES,
    ),
    DomainEventType.CART_CREATED: Rule(
        NotificationType.CART_CREATED,
        lambda p: f"Nuovo carrello di {p.get('buyer_name')}",
        lambda p: f"{p.get('item_count') or '?'} articoli{_money(p)}",
        _cart_link,
        ALL_ROLES,
    ),
    DomainEventType.CART_PAID: Rule(
        NotificationType.CART_PAID,
        lambda p: f"Carrello di {p.get('buyer_name')} pagato",
        lambda p: f"{p.get('item_count') or '?'} articoli{_money(p)}",
        _cart_link,
        ALL_ROLES,
    ),
    DomainEventType.SESSION_EXPIRED: Rule(
        NotificationType.SESSION_EXPIRED,
        lambda p: "Cardmarket: autenticazione richiesta",
        lambda p: "La sessione Cardmarket non è più valida. Ricollega l'account.",
        lambda e: "/settings/connection",
        OPERATORS,
    ),
    DomainEventType.SYNC_FAILED: Rule(
        NotificationType.SYNC_ERROR,
        lambda p: "Errore di sincronizzazione",
        lambda p: f"{p.get('error_code', 'UNKNOWN')}: {str(p.get('error', ''))[:120]}",
        lambda e: "/settings/operations",
        OPERATORS,
    ),
    DomainEventType.ACTION_FAILED: Rule(
        NotificationType.ACTION_FAILED,
        lambda p: f"Azione non riuscita: {p.get('action_type')}",
        lambda p: str(p.get("reason", ""))[:140],
        lambda e: "/settings/operations",
        OPERATORS,
    ),
}


def default_enabled(role: UserRole, type_: NotificationType) -> bool:
    for rule in RULES.values():
        if rule.type == type_:
            return role in rule.default_roles
    return False


def effective_preferences(db: Session, user: User) -> dict[NotificationType, tuple[bool, bool]]:
    """Return {type: (in_app, push)} merging stored overrides with role defaults."""
    stored = {
        p.type: (p.in_app, p.push)
        for p in db.scalars(
            select(NotificationPreference).where(NotificationPreference.user_id == user.id)
        )
    }
    result: dict[NotificationType, tuple[bool, bool]] = {}
    for type_ in NotificationType:
        enabled = default_enabled(user.role, type_)
        result[type_] = stored.get(type_, (enabled, enabled))
    return result


def _recipients(db: Session, event: DomainEvent, rule: Rule) -> list[tuple[User, bool]]:
    users = db.scalars(select(User).where(User.active.is_(True))).all()
    forced = event.payload.get("notify_user_id")
    out: list[tuple[User, bool]] = []
    for user in users:
        in_app, push = effective_preferences(db, user)[rule.type]
        if user.id == forced:
            in_app = True
        if in_app:
            out.append((user, push))
    return out


def handle_event(db: Session, event: DomainEvent) -> None:
    rule = RULES.get(event.type)
    if rule is None or event.initial_import:
        return
    title, body = rule.title(event.payload), rule.body(event.payload)
    link = rule.link(event)
    now = utcnow()
    for user, push in _recipients(db, event, rule):
        db.add(
            Notification(
                user_id=user.id,
                type=rule.type,
                title=title,
                body=body,
                entity_type=event.entity_type,
                entity_id=event.entity_id,
                event_id=event.id,
                read=False,
                created_at=now,
            )
        )
        if push:
            queue_push(
                db,
                PushMessage(
                    user_id=user.id,
                    title=title,
                    body=body,
                    url=link,
                    tag=f"{rule.type}:{event.entity_id}",
                ),
            )


def link_for(entity_type: EntityType | None, entity_id: int | None, type_: NotificationType) -> str:
    """Deep link used by the web app for a stored notification."""
    if entity_type == EntityType.ORDER and entity_id:
        return f"/orders/{entity_id}"
    if entity_type == EntityType.CART and entity_id:
        return f"/carts/{entity_id}"
    if entity_type == EntityType.CONVERSATION and entity_id:
        return f"/chat/{entity_id}"
    if type_ == NotificationType.SESSION_EXPIRED:
        return "/settings/connection"
    if type_ in (NotificationType.SYNC_ERROR, NotificationType.ACTION_FAILED):
        return "/settings/operations"
    return "/notifications"


def install() -> None:
    events.subscribe(handle_event)
