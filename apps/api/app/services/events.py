"""In-process domain event bus.

Events are persisted (append-only ``domain_events``) inside the caller's
transaction and dispatched synchronously to subscribers, which may add more
rows (e.g. notifications) to the same transaction. Side effects that leave the
process (web push) are deferred until after commit by the subscribers.
"""

import logging
from collections.abc import Callable
from typing import Any

from cmc_shared.enums import DomainEventType, EntityType
from sqlalchemy.orm import Session

from app.db import utcnow
from app.models import DomainEvent

log = logging.getLogger("cmc.events")

Handler = Callable[[Session, DomainEvent], None]
_subscribers: list[Handler] = []


def subscribe(handler: Handler) -> Handler:
    if handler not in _subscribers:
        _subscribers.append(handler)
    return handler


def emit(
    db: Session,
    type_: DomainEventType,
    entity_type: EntityType,
    entity_id: int | None,
    payload: dict[str, Any] | None = None,
    *,
    sync_run_id: int | None = None,
    initial_import: bool = False,
) -> DomainEvent:
    event = DomainEvent(
        type=type_,
        entity_type=entity_type,
        entity_id=entity_id,
        payload=payload or {},
        sync_run_id=sync_run_id,
        initial_import=initial_import,
        occurred_at=utcnow(),
    )
    db.add(event)
    db.flush()
    log.info("domain_event", extra={"event": str(type_), "entity_id": entity_id})
    for handler in _subscribers:
        handler(db, event)
    return event
