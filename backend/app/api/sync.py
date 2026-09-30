from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
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
from ..sync.service import apply_mutation, ensure_core_sync_initialized, get_changes
from ..utils.time import iso_utc
from ..workspaces import get_personal_workspace


router = APIRouter(prefix="/api/v1/sync", tags=["sync"])


class MutationBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    protocolVersion: int = 1
    mutations: list[dict] = Field(min_length=1, max_length=100)


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
    return {"pending": counts.get("pending", 0), "conflicts": counts.get("conflict", 0),
            "inFlight": counts.get("in_flight", 0), "rejected": counts.get("rejected", 0),
            "cursor": state.cursor, "queueSeeded": state.queue_seeded_at is not None,
            "lastSuccessAt": iso_utc(state.last_success_at), "lastError": state.last_error}


@router.post("/run")
def local_run(_local: None = Depends(require_local_mode), user: User = Depends(current_user),
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
    factory = sessionmaker(bind=db.get_bind(), autoflush=False, expire_on_commit=False)
    return run_sync_cycle(factory, user_id, workspace_id, metadata, credential)
