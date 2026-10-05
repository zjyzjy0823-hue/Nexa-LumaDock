from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from ..database import get_db
from .. import core_connection
from ..models import Client, LocalMutation, LocalSyncState, User
from ..runtime_mode import require_local_mode
from ..security import client_from_token, current_user
from ..sync.protocol import SYNC_PROTOCOL_VERSION
from ..sync.adapters import seed_version
from ..sync.local import seed_local_queue
from ..sync.engine import run_sync_cycle
from ..sync.conflicts import get_conflict, list_conflicts, resolve_conflict
from ..sync.notifications import get_coordinator
from ..sync.background import SAFE_SYNC_ERRORS
from ..sync.service import apply_mutation, ensure_core_sync_initialized, get_changes
from ..utils.time import iso_utc
from ..workspaces import get_personal_workspace


class SafeSyncRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def safe_handler(request):
            try:
                return await handler(request)
            except RequestValidationError:
                if request.url.path.startswith("/api/v1/sync/conflicts/") and request.url.path.endswith("/resolve"):
                    return JSONResponse(status_code=422, content={"detail": "invalid_conflict_resolution"})
                raise

        return safe_handler


router = APIRouter(prefix="/api/v1/sync", tags=["sync"], route_class=SafeSyncRoute)


class MutationBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    protocolVersion: int = 1
    mutations: list[dict] = Field(min_length=1, max_length=100)


class ConflictResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")
    strategy: Literal["local", "remote"]
    expectedRemoteRevision: int | None = Field(default=None, ge=0, le=2**63 - 1, strict=True)


@router.get("/conflicts")
def conflicts(_local: None = Depends(require_local_mode), user: User = Depends(current_user),
              db: Session = Depends(get_db)):
    return list_conflicts(db, get_personal_workspace(db, user).id)


@router.get("/conflicts/{conflict_id}")
def conflict_detail(conflict_id: str, _local: None = Depends(require_local_mode),
                    user: User = Depends(current_user), db: Session = Depends(get_db)):
    return get_conflict(db, get_personal_workspace(db, user).id, conflict_id)


@router.post("/conflicts/{conflict_id}/resolve")
def conflict_resolution(conflict_id: str, payload: ConflictResolution,
                        _local: None = Depends(require_local_mode), user: User = Depends(current_user),
                        db: Session = Depends(get_db)):
    return resolve_conflict(db, user.id, get_personal_workspace(db, user).id,
                            conflict_id, payload.strategy, payload.expectedRemoteRevision)


@router.post("/mutations")
def mutations(payload: MutationBatch, client: Client = Depends(client_from_token),
              db: Session = Depends(get_db)):
    if payload.protocolVersion != SYNC_PROTOCOL_VERSION:
        raise HTTPException(409, "sync_protocol_mismatch")
    return {"protocolVersion": SYNC_PROTOCOL_VERSION,
            "results": [apply_mutation(db, client, mutation) for mutation in payload.mutations]}


@router.get("/changes")
def changes(cursor: int = Query(default=0, ge=0), limit: int = Query(default=100, ge=1, le=100),
            protocolVersion: int = Query(default=1),
            client: Client = Depends(client_from_token), db: Session = Depends(get_db)):
    if protocolVersion != SYNC_PROTOCOL_VERSION:
        raise HTTPException(409, "sync_protocol_mismatch")
    try:
        ensure_core_sync_initialized(db, client.workspace_id)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return get_changes(db, client.workspace_id, cursor, limit)


@router.get("/status")
def local_status(_local: None = Depends(require_local_mode), user: User = Depends(current_user),
                 db: Session = Depends(get_db)):
    workspace_id = get_personal_workspace(db, user).id
    try:
        state = db.get(LocalSyncState, workspace_id)
        if state is None or state.queue_seed_version < seed_version():
            state = seed_local_queue(db, workspace_id)
            db.commit()
    except Exception:
        db.rollback()
        raise
    counts = dict(db.execute(select(LocalMutation.status, func.count()).where(
        LocalMutation.workspace_id == workspace_id).group_by(LocalMutation.status)).all())
    try:
        connected = core_connection.load_connection(user.id) is not None
        connection_error = None
    except HTTPException as error:
        connected = False
        connection_error = None if error.status_code == 409 else "invalid_connection"
    coordinator = get_coordinator(db.get_bind())
    scheduling = coordinator.snapshot(workspace_id) if coordinator is not None else {
        "enabled": False, "running": False, "connected": connected,
        "blocked": bool(connection_error), "lastAttemptAt": None, "nextRetryAt": None}
    if connection_error:
        scheduling.update(enabled=False, blocked=True, nextRetryAt=None)
    last_error = connection_error or state.last_error
    if last_error is not None and last_error not in SAFE_SYNC_ERRORS:
        last_error = "internal_error"
    return {"pending": counts.get("pending", 0), "conflicts": counts.get("conflict", 0),
            "inFlight": counts.get("in_flight", 0), "rejected": counts.get("rejected", 0),
            "cursor": state.cursor, "queueSeeded": state.queue_seeded_at is not None,
            "lastSuccessAt": iso_utc(state.last_success_at), "lastError": last_error,
            **scheduling, "connected": connected}


@router.post("/run")
async def local_run(_local: None = Depends(require_local_mode), user: User = Depends(current_user),
              db: Session = Depends(get_db)):
    user_id = user.id
    workspace_id = get_personal_workspace(db, user).id
    # Release the request session's SQLite read transaction before the engine
    # opens its short write transactions and performs network I/O.
    db.rollback()
    metadata = core_connection.load_connection(user_id)
    if metadata is None:
        raise HTTPException(409, "Core connection is not configured")
    try:
        credential = core_connection.credential_store.load(user_id)
    except OSError:
        credential = None
    if not credential or not credential.startswith("nc_live_"):
        raise HTTPException(401, "Client credential is unavailable")
    coordinator = get_coordinator(db.get_bind())
    if coordinator is not None:
        return await coordinator.manual(user_id, workspace_id)
    factory = sessionmaker(bind=db.get_bind(), autoflush=False, expire_on_commit=False)
    # Standalone router embeddings keep the existing manual API and engine.
    from asyncio import to_thread
    return await to_thread(run_sync_cycle, factory, user_id, workspace_id, metadata, credential)
