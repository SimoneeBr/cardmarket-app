"""Endpoints used exclusively by the Cardmarket agent (bearer token).

Not exposed through the web origin: the Next.js proxy and the production
reverse proxy only forward ``/api/*``.
"""

import logging

from cmc_shared.enums import ActionStatus, ActionType, ConnectionStatus, EntityType, SyncRunStatus
from cmc_shared.protocol import (
    ActionResultRequest,
    AgentCommand,
    CartsBatch,
    ClaimedAction,
    ClaimRequest,
    ConversationsBatch,
    HeartbeatRequest,
    HeartbeatResponse,
    OrdersBatch,
    SessionReport,
    SyncBatchResult,
    SyncCompleteRequest,
    SyncStartRequest,
    SyncStartResponse,
)
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select

from app.db import utcnow
from app.deps import DbSession, verify_agent_token
from app.logging import bind_correlation
from app.models import Action, CardmarketConnection, SyncRun
from app.services import action_queue, sync_engine
from app.services.audit import AuditAction, AuditResult, record
from app.services.connection import (
    get_primary_connection,
    is_access_blocked,
    pop_commands,
    set_status,
)
from app.services.runtime_settings import get_runtime_settings

log = logging.getLogger("cmc.agent_api")

router = APIRouter(
    prefix="/internal/agent", tags=["internal-agent"], dependencies=[Depends(verify_agent_token)]
)


def _agent_response(
    conn: CardmarketConnection,
    interval: int,
    sync_enabled: bool,
    commands: list[AgentCommand] | None = None,
) -> HeartbeatResponse:
    blocked = is_access_blocked(conn)
    return HeartbeatResponse(
        sync_enabled=sync_enabled and conn.status != ConnectionStatus.DISCONNECTED and not blocked,
        sync_interval_seconds=interval,
        commands=commands or [],
        access_blocked=blocked,
    )


@router.post("/heartbeat", response_model=HeartbeatResponse)
def heartbeat(body: HeartbeatRequest, db: DbSession) -> HeartbeatResponse:
    conn = get_primary_connection(db, for_update=True)
    conn.agent_id = body.agent_id
    conn.agent_version = body.version
    conn.agent_mode = body.mode
    conn.agent_last_seen_at = utcnow()
    conn.agent_detail = body.detail
    commands = [AgentCommand.model_validate(c) for c in pop_commands(conn)]
    runtime = get_runtime_settings(db)
    db.commit()
    return _agent_response(conn, runtime.sync_interval_seconds, runtime.sync_enabled, commands)


def _admin_disconnected(
    db: DbSession, conn: CardmarketConnection, reported: ConnectionStatus
) -> bool:
    if conn.status != ConnectionStatus.DISCONNECTED or reported == ConnectionStatus.DISCONNECTED:
        return False
    if conn.last_authentication is None:
        return False  # never paired: accept the first successful session
    active = db.scalar(
        select(Action.id).where(
            Action.type.in_((ActionType.PAIR_SESSION, ActionType.VERIFY_SESSION)),
            Action.status.in_((ActionStatus.PENDING, ActionStatus.PROCESSING)),
        )
    )
    return active is None


@router.post("/session", response_model=HeartbeatResponse)
def report_session(body: SessionReport, db: DbSession) -> HeartbeatResponse:
    conn = get_primary_connection(db, for_update=True)
    previous = conn.status
    if _admin_disconnected(db, conn, body.status):
        # An operator disconnected the account: only an explicit pair/reconnect
        # request may bring it back, not an automatic report from the agent.
        runtime = get_runtime_settings(db)
        db.commit()
        return HeartbeatResponse(
            sync_enabled=False, sync_interval_seconds=runtime.sync_interval_seconds
        )
    changed = set_status(
        db,
        conn,
        body.status,
        error_code=body.error_code,
        message=body.message,
        authenticated=body.authenticated,
    )
    if changed:
        record(
            db,
            AuditAction.SESSION_STATUS_CHANGED,
            actor="agent",
            entity_type=EntityType.CONNECTION,
            entity_id=conn.id,
            result=AuditResult.SUCCESS
            if body.status == ConnectionStatus.CONNECTED
            else AuditResult.FAILURE,
            error=body.message,
            details={"from": str(previous), "to": str(body.status)},
        )
    runtime = get_runtime_settings(db)
    db.commit()
    return _agent_response(conn, runtime.sync_interval_seconds, runtime.sync_enabled)


@router.post("/sync/start", response_model=SyncStartResponse)
def sync_start(body: SyncStartRequest, db: DbSession) -> SyncStartResponse:
    conn = get_primary_connection(db, for_update=True)
    if conn.status != ConnectionStatus.CONNECTED:
        return SyncStartResponse(granted=False, reason=f"connection is {conn.status}")
    try:
        run = sync_engine.start_run(db, conn, body.agent_id, body.entity, body.trigger)
    except sync_engine.SyncLockError as exc:
        db.rollback()
        return SyncStartResponse(granted=False, reason=str(exc))
    fingerprints = sync_engine.known_fingerprints(db, conn)
    db.commit()
    bind_correlation(sync_id=run.sync_id)
    log.info("sync started", extra={"sync_run_id": run.id})
    return SyncStartResponse(
        granted=True,
        sync_run_id=run.id,
        sync_id=run.sync_id,
        known_orders=fingerprints["orders"],
        known_conversations=fingerprints["conversations"],
        known_carts=fingerprints["carts"],
    )


def _running_run(db: DbSession, run_id: int) -> SyncRun:
    run = db.get(SyncRun, run_id)
    if run is None or run.status != SyncRunStatus.RUNNING:
        raise HTTPException(status.HTTP_409_CONFLICT, "sync run is not running")
    bind_correlation(sync_id=run.sync_id)
    return run


@router.post("/sync/{run_id}/orders", response_model=SyncBatchResult)
def sync_orders(run_id: int, body: OrdersBatch, db: DbSession) -> SyncBatchResult:
    run = _running_run(db, run_id)
    result = sync_engine.apply_orders(db, get_primary_connection(db), run, body)
    db.commit()
    return result


@router.post("/sync/{run_id}/conversations", response_model=SyncBatchResult)
def sync_conversations(run_id: int, body: ConversationsBatch, db: DbSession) -> SyncBatchResult:
    run = _running_run(db, run_id)
    result = sync_engine.apply_conversations(db, get_primary_connection(db), run, body)
    db.commit()
    return result


@router.post("/sync/{run_id}/carts", response_model=SyncBatchResult)
def sync_carts(run_id: int, body: CartsBatch, db: DbSession) -> SyncBatchResult:
    run = _running_run(db, run_id)
    result = sync_engine.apply_carts(db, get_primary_connection(db), run, body)
    db.commit()
    return result


@router.post("/sync/{run_id}/complete", status_code=status.HTTP_204_NO_CONTENT)
def sync_complete(run_id: int, body: SyncCompleteRequest, db: DbSession) -> Response:
    run = _running_run(db, run_id)
    conn = get_primary_connection(db, for_update=True)
    sync_engine.complete_run(
        db,
        conn,
        run,
        body.status,
        error_code=body.error_code,
        error_message=body.error_message,
        artifacts=body.artifacts,
    )
    if body.status == SyncRunStatus.FAILED:
        record(
            db,
            AuditAction.SYNC_FAILED,
            actor="agent",
            entity_type=EntityType.SYNC_RUN,
            entity_id=run.id,
            result=AuditResult.FAILURE,
            error=body.error_message,
            details={"error_code": str(body.error_code)},
        )
    db.commit()
    log.info(
        "sync completed",
        extra={
            "status": str(body.status),
            "found": run.records_found,
            "changed": run.records_changed,
        },
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/actions/claim", response_model=ClaimedAction | None)
def claim_action(body: ClaimRequest, db: DbSession, response: Response) -> ClaimedAction | None:
    conn = get_primary_connection(db)
    claimed = action_queue.claim_next(db, conn, body.agent_id, body.lease_seconds)
    db.commit()
    if claimed is None:
        response.status_code = status.HTTP_204_NO_CONTENT
        return None
    bind_correlation(action_id=str(claimed.id))
    log.info(
        "action claimed", extra={"action_type": str(claimed.type), "recovery": claimed.recovery}
    )
    return claimed


@router.post("/actions/{action_id}/result", status_code=status.HTTP_204_NO_CONTENT)
def action_result(action_id: int, body: ActionResultRequest, db: DbSession) -> Response:
    action = db.get(Action, action_id)
    if action is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "action not found")
    bind_correlation(action_id=str(action.id))
    try:
        action_queue.report_result(db, action, body)
    except action_queue.ActionStateError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    db.commit()
    log.info("action result", extra={"outcome": str(body.outcome), "status": str(action.status)})
    return Response(status_code=status.HTTP_204_NO_CONTENT)
