"""FastAPI application factory."""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import event
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_sessionmaker
from app.logging import configure_logging
from app.middleware import CSRFMiddleware, RequestContextMiddleware, SecurityHeadersMiddleware
from app.routers import (
    admin,
    auth,
    carts,
    connection,
    conversations,
    dashboard,
    health,
    internal_agent,
    notifications,
    orders,
    templates,
)
from app.services import notifications as notification_engine
from app.services import push
from app.services.retention import apply_retention

log = logging.getLogger("cmc.api")

_hooks_installed = False


def install_hooks() -> None:
    """Wire the event bus and the post-commit push delivery (idempotent)."""
    global _hooks_installed
    if _hooks_installed:
        return
    notification_engine.install()
    event.listen(Session, "after_commit", push.flush_pending)
    event.listen(Session, "after_rollback", push.discard_pending)
    _hooks_installed = True


async def _maintenance_loop(interval: int) -> None:
    while True:
        await asyncio.sleep(interval)
        try:
            with get_sessionmaker()() as db:
                await asyncio.to_thread(apply_retention, db)
        except Exception:
            log.exception("maintenance failed")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    settings.validate_for_runtime()
    task = None
    if settings.environment != "test" and settings.maintenance_interval_seconds > 0:
        task = asyncio.create_task(_maintenance_loop(settings.maintenance_interval_seconds))
    log.info(
        "api started", extra={"environment": settings.environment, "mock": settings.mock_cardmarket}
    )
    yield
    if task:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    install_hooks()
    app = FastAPI(
        title="Cardmarket Companion API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/api/docs" if settings.environment != "production" else None,
        openapi_url="/api/openapi.json" if settings.environment != "production" else None,
    )
    # Order: outermost last.
    app.add_middleware(CSRFMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestContextMiddleware)

    @app.exception_handler(OperationalError)
    async def _db_unavailable(_: Request, exc: OperationalError) -> JSONResponse:
        log.error("database unavailable", extra={"error_code": "DATABASE_ERROR"})
        return JSONResponse({"detail": "Database non disponibile", "code": "DATABASE_ERROR"}, 503)

    @app.exception_handler(SQLAlchemyError)
    async def _db_error(_: Request, exc: SQLAlchemyError) -> JSONResponse:
        log.exception("database error", extra={"error_code": "DATABASE_ERROR"})
        return JSONResponse({"detail": "Errore del database", "code": "DATABASE_ERROR"}, 500)

    for module in (
        health,
        auth,
        dashboard,
        orders,
        conversations,
        carts,
        notifications,
        templates,
        connection,
        admin,
        internal_agent,
    ):
        app.include_router(module.router)
    return app


app = create_app()
