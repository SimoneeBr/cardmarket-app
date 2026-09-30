from cmc_shared.enums import EntityType, UserRole
from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import func, select

from app.config import Settings
from app.db import utcnow
from app.deps import AppSettings, CurrentUser, DbSession, ReqCtx
from app.models import User
from app.schemas import (
    ChangePasswordRequest,
    LoginRequest,
    MeOut,
    OkResponse,
    SetupAdminRequest,
    SetupStatus,
    UserOut,
)
from app.security.passwords import (
    hash_password,
    needs_rehash,
    validate_password_strength,
    verify_password,
)
from app.security.permissions import permissions_for
from app.security.rate_limit import limiter
from app.security.sessions import (
    clear_auth_cookies,
    create_session,
    revoke_session,
    revoke_user_sessions,
    set_auth_cookies,
    tokens_match,
)
from app.services.audit import AuditAction, AuditResult, record
from app.services.connection import agent_online, get_primary_connection

router = APIRouter(prefix="/api", tags=["auth"])


def _me(user: User) -> MeOut:
    base = UserOut.model_validate(user).model_dump()
    return MeOut(**base, permissions=[str(p) for p in permissions_for(user.role)])


def _web_setup_mode(settings: Settings) -> str:
    if settings.environment != "production":
        return "open"
    return "token" if settings.setup_token.get_secret_value() else "disabled"


def _user_count(db: DbSession) -> int:
    return int(db.scalar(select(func.count(User.id))) or 0)


@router.get("/setup/status", response_model=SetupStatus)
def setup_status(db: DbSession, settings: AppSettings) -> SetupStatus:
    conn = get_primary_connection(db)
    db.commit()
    return SetupStatus(
        needs_admin=_user_count(db) == 0,
        mock_mode=settings.mock_cardmarket,
        push_enabled=settings.push_enabled,
        connection_status=conn.status,
        agent_online=agent_online(conn),
        has_synced=conn.last_successful_sync is not None,
        web_setup=_web_setup_mode(settings),
    )


@router.post("/setup/admin", response_model=MeOut, status_code=status.HTTP_201_CREATED)
def setup_admin(
    body: SetupAdminRequest, db: DbSession, settings: AppSettings, ctx: ReqCtx, response: Response
) -> MeOut:
    """First-run only: create the initial administrator."""
    if not limiter.hit(f"setup:{ctx.ip}", 5, 300):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Troppi tentativi")
    mode = _web_setup_mode(settings)
    if mode == "disabled":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Setup via web disabilitato in produzione: usa 'python -m app.scripts.create_admin' "
            "oppure imposta SETUP_TOKEN",
        )
    if mode == "token" and not tokens_match(
        body.setup_token, settings.setup_token.get_secret_value()
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Codice di setup non valido")
    # Lock the users table so two concurrent first-run requests cannot both win.
    if db.get_bind().dialect.name == "postgresql":
        db.execute(select(func.pg_advisory_xact_lock(4242)))
    if _user_count(db) > 0:
        raise HTTPException(status.HTTP_409_CONFLICT, "Setup già completato")
    try:
        validate_password_strength(body.password)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    user = User(
        email=body.email.lower(),
        name=body.name,
        role=UserRole.ADMIN,
        password_hash=hash_password(body.password),
        active=True,
        last_login_at=utcnow(),
    )
    db.add(user)
    db.flush()
    record(
        db,
        AuditAction.SETUP_ADMIN,
        user=user,
        entity_type=EntityType.USER,
        entity_id=user.id,
        ctx=ctx,
    )
    token = create_session(db, user, settings, ctx.ip, ctx.user_agent)
    db.commit()
    set_auth_cookies(response, token, settings)
    return _me(user)


@router.post("/auth/login", response_model=MeOut)
def login(
    body: LoginRequest, db: DbSession, settings: AppSettings, ctx: ReqCtx, response: Response
) -> MeOut:
    email = body.email.lower()
    key_ip, key_email = f"login-ip:{ctx.ip}", f"login-email:{email}"
    window = settings.login_rate_limit_window_seconds
    if not (
        limiter.hit(key_ip, settings.login_rate_limit_attempts * 3, window)
        and limiter.hit(key_email, settings.login_rate_limit_attempts, window)
    ):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "Troppi tentativi, riprova più tardi"
        )

    user = db.scalar(select(User).where(User.email == email))
    # Always run the hash verification (constant-ish time, no user enumeration).
    password_ok = verify_password(user.password_hash if user else None, body.password)
    if user is None or not password_ok or not user.active:
        record(
            db,
            AuditAction.LOGIN_FAILED,
            actor=f"anonymous:{email}",
            result=AuditResult.FAILURE,
            error="invalid credentials" if not user or user.active else "user disabled",
            ctx=ctx,
        )
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Credenziali non valide")

    limiter.reset(key_email)
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
    user.last_login_at = utcnow()
    token = create_session(db, user, settings, ctx.ip, ctx.user_agent)
    record(db, AuditAction.LOGIN, user=user, ctx=ctx)
    db.commit()
    set_auth_cookies(response, token, settings)
    return _me(user)


@router.post("/auth/logout", response_model=OkResponse)
def logout(
    request: Request,
    db: DbSession,
    settings: AppSettings,
    user: CurrentUser,
    ctx: ReqCtx,
    response: Response,
) -> OkResponse:
    token = request.cookies.get(settings.session_cookie_name)
    if token:
        revoke_session(db, token)
    record(db, AuditAction.LOGOUT, user=user, ctx=ctx)
    db.commit()
    clear_auth_cookies(response, settings)
    return OkResponse()


@router.get("/me", response_model=MeOut)
def me(user: CurrentUser) -> MeOut:
    return _me(user)


@router.post("/me/password", response_model=OkResponse)
def change_password(
    body: ChangePasswordRequest,
    db: DbSession,
    settings: AppSettings,
    user: CurrentUser,
    ctx: ReqCtx,
    response: Response,
) -> OkResponse:
    if not verify_password(user.password_hash, body.current_password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Password attuale errata")
    try:
        validate_password_strength(body.new_password)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    user.password_hash = hash_password(body.new_password)
    revoke_user_sessions(db, user.id)
    token = create_session(db, user, settings, ctx.ip, ctx.user_agent)
    record(db, AuditAction.PASSWORD_CHANGED, user=user, ctx=ctx)
    db.commit()
    set_auth_cookies(response, token, settings)
    return OkResponse()
