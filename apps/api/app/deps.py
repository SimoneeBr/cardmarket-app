"""FastAPI dependencies: authentication, authorization, agent auth."""

import hmac
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.models import User
from app.security.permissions import Permission, has_permission
from app.security.sessions import resolve_session

DbSession = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]


@dataclass(frozen=True)
class RequestContext:
    ip: str | None
    user_agent: str | None
    request_id: str | None


def get_request_context(request: Request) -> RequestContext:
    forwarded = request.headers.get("x-forwarded-for")
    ip = (
        forwarded.split(",")[0].strip()
        if forwarded
        else (request.client.host if request.client else None)
    )
    return RequestContext(
        ip=ip,
        user_agent=request.headers.get("user-agent"),
        request_id=getattr(request.state, "request_id", None),
    )


ReqCtx = Annotated[RequestContext, Depends(get_request_context)]


def get_current_user(request: Request, db: DbSession, settings: AppSettings) -> User:
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Autenticazione richiesta")
    session = resolve_session(db, token)
    if session is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sessione scaduta")
    request.state.user_id = session.user_id
    return session.user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require(permission: Permission) -> Callable[[User], User]:
    def checker(user: CurrentUser) -> User:
        if not has_permission(user.role, permission):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Permesso negato")
        return user

    return checker


def verify_agent_token(
    settings: AppSettings, authorization: Annotated[str | None, Header()] = None
) -> None:
    expected = settings.agent_api_token.get_secret_value()
    if not expected:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Agent token not configured")
    scheme, _, supplied = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid agent token")
