from pathlib import Path
from typing import Annotated

from cmc_shared.enums import (
    ActionStatus,
    AgentCommandType,
    EntityType,
    SyncRunStatus,
    UserRole,
)
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.deps import DbSession, ReqCtx, require
from app.models import Action, AuditLog, SyncRun, User
from app.schemas import (
    ActionOut,
    AuditLogOut,
    ErrorsOut,
    OkResponse,
    Page,
    PurgeRequest,
    RuntimeSettingsOut,
    RuntimeSettingsUpdate,
    SimulationRequest,
    SyncRunOut,
    UserCreate,
    UserOut,
    UserUpdate,
)
from app.security.passwords import hash_password, validate_password_strength
from app.security.permissions import Permission
from app.security.sessions import revoke_user_sessions
from app.services import action_queue
from app.services.audit import AuditAction, record
from app.services.connection import get_primary_connection, queue_command
from app.services.retention import apply_retention, purge_cardmarket_data
from app.services.runtime_settings import get_runtime_settings, update_runtime_settings

router = APIRouter(prefix="/api/admin", tags=["admin"])

UserAdmin = Annotated[User, Depends(require(Permission.MANAGE_USERS))]
Operator = Annotated[User, Depends(require(Permission.VIEW_OPERATIONS))]
ActionManager = Annotated[User, Depends(require(Permission.MANAGE_ACTIONS))]
SettingsAdmin = Annotated[User, Depends(require(Permission.MANAGE_SETTINGS))]
Purger = Annotated[User, Depends(require(Permission.PURGE_DATA))]

PURGE_CONFIRMATION = "ELIMINA DATI"


# ------------------------------------------------------------------ users


def _strong(password: str) -> None:
    try:
        validate_password_strength(password)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


@router.get("/users", response_model=list[UserOut])
def list_users(db: DbSession, _: UserAdmin) -> list[User]:
    return list(db.scalars(select(User).order_by(User.id)))


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(body: UserCreate, db: DbSession, admin: UserAdmin, ctx: ReqCtx) -> User:
    _strong(body.password)
    user = User(
        email=body.email.lower(),
        name=body.name,
        role=body.role,
        password_hash=hash_password(body.password),
        active=True,
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "Email già registrata") from exc
    record(
        db,
        AuditAction.USER_CREATED,
        user=admin,
        entity_type=EntityType.USER,
        entity_id=user.id,
        details={"role": str(user.role)},
        ctx=ctx,
    )
    db.commit()
    return user


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: int, body: UserUpdate, db: DbSession, admin: UserAdmin, ctx: ReqCtx
) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Utente non trovato")
    changes = body.model_dump(exclude_unset=True)
    demoting_self = user.id == admin.id and (
        changes.get("active") is False or changes.get("role", UserRole.ADMIN) != UserRole.ADMIN
    )
    if demoting_self:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Non puoi disabilitare o declassare te stesso"
        )
    if "name" in changes:
        user.name = changes["name"]
    if "role" in changes:
        user.role = changes["role"]
    if "active" in changes:
        user.active = changes["active"]
        if not user.active:
            revoke_user_sessions(db, user.id)
    if changes.get("password"):
        _strong(changes["password"])
        user.password_hash = hash_password(changes["password"])
        revoke_user_sessions(db, user.id)
    changes.pop("password", None)
    record(
        db,
        AuditAction.USER_UPDATED,
        user=admin,
        entity_type=EntityType.USER,
        entity_id=user.id,
        details={k: str(v) for k, v in changes.items()}
        | ({"password": "changed"} if body.password else {}),
        ctx=ctx,
    )
    db.commit()
    return user


# ---------------------------------------------------------------- actions


@router.get("/actions", response_model=Page[ActionOut])
def list_actions(
    db: DbSession,
    _: Operator,
    status_filter: Annotated[ActionStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[ActionOut]:
    stmt = select(Action)
    if status_filter:
        stmt = stmt.where(Action.status == status_filter)
    total = int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    rows = db.scalars(stmt.order_by(Action.id.desc()).limit(limit).offset(offset)).all()
    return Page(
        items=[ActionOut.model_validate(a) for a in rows], total=total, limit=limit, offset=offset
    )


def _action(db: DbSession, action_id: int) -> Action:
    action = db.get(Action, action_id)
    if action is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Azione non trovata")
    return action


def _transition(
    db: DbSession, action: Action, fn: object, audit: AuditAction, user: User, ctx: ReqCtx
) -> ActionOut:
    try:
        fn(db, action)  # type: ignore[operator]
    except action_queue.ActionStateError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    record(
        db,
        audit,
        user=user,
        entity_type=EntityType.ACTION,
        entity_id=action.id,
        details={"type": str(action.type)},
        ctx=ctx,
    )
    db.commit()
    return ActionOut.model_validate(action)


@router.post("/actions/{action_id}/retry", response_model=ActionOut)
def retry_action(action_id: int, db: DbSession, user: ActionManager, ctx: ReqCtx) -> ActionOut:
    return _transition(
        db, _action(db, action_id), action_queue.retry, AuditAction.ACTION_RETRIED, user, ctx
    )


@router.post("/actions/{action_id}/cancel", response_model=ActionOut)
def cancel_action(action_id: int, db: DbSession, user: ActionManager, ctx: ReqCtx) -> ActionOut:
    return _transition(
        db, _action(db, action_id), action_queue.cancel, AuditAction.ACTION_CANCELLED, user, ctx
    )


@router.post("/actions/{action_id}/resolve", response_model=ActionOut)
def resolve_action(action_id: int, db: DbSession, user: ActionManager, ctx: ReqCtx) -> ActionOut:
    """Operator verified on Cardmarket that the action did happen."""
    return _transition(
        db,
        _action(db, action_id),
        action_queue.resolve_as_done,
        AuditAction.ACTION_RESOLVED,
        user,
        ctx,
    )


# ------------------------------------------------------------ audit / errors


@router.get("/audit-logs", response_model=Page[AuditLogOut])
def audit_logs(
    db: DbSession,
    _: Operator,
    action: Annotated[str | None, Query(max_length=60)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[AuditLogOut]:
    stmt = select(AuditLog)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    total = int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    rows = db.scalars(stmt.order_by(AuditLog.id.desc()).limit(limit).offset(offset)).all()
    return Page(
        items=[AuditLogOut.model_validate(a) for a in rows], total=total, limit=limit, offset=offset
    )


@router.get("/errors", response_model=ErrorsOut)
def errors(db: DbSession, _: Operator) -> ErrorsOut:
    conn = get_primary_connection(db)
    runs = db.scalars(
        select(SyncRun)
        .where(SyncRun.status == SyncRunStatus.FAILED)
        .order_by(SyncRun.id.desc())
        .limit(20)
    ).all()
    actions = db.scalars(
        select(Action)
        .where(Action.status.in_((ActionStatus.FAILED, ActionStatus.NEEDS_ATTENTION)))
        .order_by(Action.id.desc())
        .limit(20)
    ).all()
    return ErrorsOut(
        sync_runs=[SyncRunOut.model_validate(r) for r in runs],
        actions=[ActionOut.model_validate(a) for a in actions],
        connection_error=conn.last_error,
        connection_error_code=conn.last_error_code,
    )


@router.get("/artifacts/{name}")
def artifact(name: str, _: Operator) -> FileResponse:
    """Serve a failure screenshot/trace captured by the agent (shared volume)."""
    base = Path(get_settings().artifacts_dir).resolve()
    target = (base / name).resolve()
    if base not in target.parents or not target.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Artifact non trovato")
    return FileResponse(target)


# --------------------------------------------------------------- settings


@router.get("/settings", response_model=RuntimeSettingsOut)
def get_settings_(db: DbSession, _: Operator) -> RuntimeSettingsOut:
    return RuntimeSettingsOut(**get_runtime_settings(db).model_dump())


@router.put("/settings", response_model=RuntimeSettingsOut)
def put_settings(
    body: RuntimeSettingsUpdate, db: DbSession, user: SettingsAdmin, ctx: ReqCtx
) -> RuntimeSettingsOut:
    changes = body.model_dump(exclude_none=True)
    updated = update_runtime_settings(db, changes)
    record(
        db,
        AuditAction.SETTINGS_CHANGED,
        user=user,
        entity_type=EntityType.SETTINGS,
        entity_id="runtime",
        details=changes,
        ctx=ctx,
    )
    db.commit()
    return RuntimeSettingsOut(**updated.model_dump())


# ------------------------------------------------------------- simulation

_SCENARIOS = {
    "session_expired": AgentCommandType.SIMULATE_SESSION_EXPIRED,
    "sync_error": AgentCommandType.SIMULATE_SYNC_ERROR,
    "new_activity": AgentCommandType.SIMULATE_NEW_ACTIVITY,
}


@router.post("/simulate", response_model=OkResponse)
def simulate(
    body: SimulationRequest, db: DbSession, user: SettingsAdmin, ctx: ReqCtx
) -> OkResponse:
    """Mock mode only: ask the mock agent to simulate a scenario."""
    if not get_settings().mock_cardmarket:
        raise HTTPException(status.HTTP_409_CONFLICT, "Disponibile solo con MOCK_CARDMARKET=true")
    conn = get_primary_connection(db, for_update=True)
    queue_command(conn, _SCENARIOS[body.scenario])
    record(db, AuditAction.SIMULATION, user=user, details={"scenario": body.scenario}, ctx=ctx)
    db.commit()
    return OkResponse()


# ----------------------------------------------------------------- privacy


@router.post("/retention/run")
def run_retention(db: DbSession, _: SettingsAdmin) -> dict[str, int]:
    return apply_retention(db)


@router.post("/data/purge")
def purge(body: PurgeRequest, db: DbSession, user: Purger, ctx: ReqCtx) -> dict[str, int]:
    """Delete all locally mirrored customer data. Cardmarket is not touched."""
    if body.confirm != PURGE_CONFIRMATION:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Digita esattamente '{PURGE_CONFIRMATION}'"
        )
    counts = purge_cardmarket_data(db)
    conn = get_primary_connection(db, for_update=True)
    conn.last_successful_sync = None  # next sync is an initial import (no notification storm)
    record(db, AuditAction.DATA_PURGED, user=user, details=counts, ctx=ctx)
    db.commit()
    return counts
