"""Read-only, authenticated diagnostics. Project safe fields, never raw errors."""
from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from .. import core_connection
from ..database import get_db, runtime_config
from ..models import Client, LocalMutation, LocalSyncState, User, Workspace
from ..security import client_from_token, current_user
from ..sync.background import SAFE_SYNC_ERRORS
from ..sync.protocol import SYNC_PROTOCOL_VERSION
from ..utils.time import iso_utc

router = APIRouter(tags=["diagnostics"])


def automation_runtime(request):
    engine = getattr(request.app.state, "automation_engine", None)
    task = getattr(engine, "task", None)
    running = bool(task is not None and not task.done())
    return {"scheduler": running, "worker": running}


@router.get("/client/diagnostics")
def client_diagnostics(request: Request, response: Response, item: Client = Depends(client_from_token)):
    # Core client credentials are already checked by the existing dependency.
    response.headers["Cache-Control"] = "no-store"
    return {"protocol": SYNC_PROTOCOL_VERSION, "clientId": item.id,
            "workspaceId": item.workspace_id, "automation": automation_runtime(request)}


def remote_snapshot(user_id):
    result = {"status": "disconnected", "url": None, "workspaceId": None,
              "clientId": None, "tokenConfigured": False, "protocol": None,
              "automation": {"scheduler": None, "worker": None}}
    try:
        metadata = core_connection.load_connection(user_id)
        if metadata is None:
            return result
        # Validate again before using/displaying an origin: no userinfo/query/path.
        result["url"] = core_connection.validate_core_url(metadata.coreUrl)
        result.update(workspaceId=metadata.workspaceId, clientId=metadata.clientId)
        credential = core_connection.credential_store.load(user_id)
        result["tokenConfigured"] = bool(credential)
        if not credential:
            result["status"] = "unauthorized"
            return result
        result["status"] = core_connection.test_connection(user_id)["status"]
        if result["status"] != "connected":
            return result
        with core_connection._http_client() as client:
            response = client.get(metadata.coreUrl + "/api/v1/client/diagnostics",
                                  headers={"Authorization": "Bearer " + credential})
        if response.status_code == 404:
            return result  # Older Core: connected, protocol/runtime unverified.
        if response.status_code in (401, 403):
            result["status"] = "unauthorized"
            return result
        if response.is_redirect or response.status_code != 200:
            result["status"] = "unreachable"
            return result
        body = response.json()
        if body.get("clientId") != metadata.clientId or body.get("workspaceId") != metadata.workspaceId:
            result["status"] = "unauthorized"
            return result
        protocol = body.get("protocol")
        result["protocol"] = protocol if type(protocol) is int and 0 < protocol < 1000 else None
        runtime = body.get("automation", {})
        result["automation"] = {name: runtime.get(name) if type(runtime.get(name)) is bool else None
                                for name in ("scheduler", "worker")}
    except Exception:
        # Exception messages and response bodies may contain credentials.
        result["status"] = "unavailable"
    return result


@router.get("/settings/diagnostics")
def diagnostics(request: Request, response: Response, user: User = Depends(current_user), db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    local = runtime_config.mode == "local"
    db.execute(text("SELECT 1"))
    workspace = db.scalar(select(Workspace).where(Workspace.owner_user_id == user.id,
                         Workspace.kind == "personal").order_by(Workspace.created_at, Workspace.id))
    state = db.get(LocalSyncState, workspace.id) if local and workspace else None
    counts = dict(db.execute(select(LocalMutation.status, func.count()).where(
                  LocalMutation.workspace_id == workspace.id).group_by(LocalMutation.status)).all()) if local and workspace else {}
    # Release DB transaction before network probing; never seed queues or run sync.
    workspace_id = workspace.id if workspace else None
    user_id = user.id
    sync = {"pending": counts.get("pending", 0), "rejected": counts.get("rejected", 0),
            "conflicts": counts.get("conflict", 0), "inFlight": counts.get("in_flight", 0),
            "lastSuccessAt": iso_utc(state.last_success_at) if state else None,
            "lastError": (state.last_error if state.last_error in SAFE_SYNC_ERRORS else "internal_error") if state and state.last_error else None}
    db.rollback()
    remote = remote_snapshot(user_id) if local else None
    remote_protocol = remote["protocol"] if remote else SYNC_PROTOCOL_VERSION
    compatible = remote_protocol == SYNC_PROTOCOL_VERSION if remote_protocol is not None else None
    runtime = automation_runtime(request)
    return {"appVersion": request.app.version, "mode": runtime_config.mode,
            "backend": "healthy", "database": {"kind": db.get_bind().dialect.name, "status": "ok"},
            "workspaceId": workspace_id, "core": remote,
            "sync": sync if local else None,
            "protocol": {"local": SYNC_PROTOCOL_VERSION, "core": remote_protocol, "compatible": compatible},
            "automation": {"local": runtime if local else {"scheduler": False, "worker": False},
                           "core": remote["automation"] if remote else runtime}}
