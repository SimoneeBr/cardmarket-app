import logging
import secrets
import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.config import get_settings
from app.logging import correlation_var, request_id_var
from app.security.sessions import tokens_match

log = logging.getLogger("cmc.http")

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
# Endpoints reachable before a session exists (no CSRF cookie yet).
_CSRF_EXEMPT = frozenset({"/api/auth/login", "/api/setup/admin"})


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Request id propagation + structured access log."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        incoming = request.headers.get("x-request-id", "")
        request_id = (
            incoming if 8 <= len(incoming) <= 64 and incoming.isascii() else secrets.token_hex(8)
        )
        request.state.request_id = request_id
        token = request_id_var.set(request_id)
        corr_token = correlation_var.set({})
        started = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        duration_ms = round((time.perf_counter() - started) * 1000, 1)
        response.headers["x-request-id"] = request_id
        if not request.url.path.startswith("/health"):
            request_id_var.set(request_id)
            log.info(
                "request",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "duration_ms": duration_ms,
                },
            )
            request_id_var.set(None)
        correlation_var.reset(corr_token)
        return response


class CSRFMiddleware(BaseHTTPMiddleware):
    """Double-submit cookie check for cookie-authenticated unsafe requests."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        settings = get_settings()
        path = request.url.path
        if (
            request.method not in _SAFE_METHODS
            and path.startswith("/api/")
            and path not in _CSRF_EXEMPT
            and settings.session_cookie_name in request.cookies
        ):
            cookie = request.cookies.get(settings.csrf_cookie_name)
            header = request.headers.get("x-csrf-token")
            if not tokens_match(cookie, header):
                return JSONResponse({"detail": "CSRF token non valido"}, status_code=403)
        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers.setdefault("x-content-type-options", "nosniff")
        response.headers.setdefault("referrer-policy", "same-origin")
        response.headers.setdefault("x-frame-options", "DENY")
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("cache-control", "no-store")
        return response
