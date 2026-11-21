"""Shared Space（/api/v1/spaces）REST API 路由定义。"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from ..database import get_db
from ..runtime_mode import require_core_mode
from ..security import authenticate_user_jwt, bearer
from ..workspaces import get_personal_workspace
from . import service
from .schemas import (
    ProtectedPasswordChangeInput,
    SpaceAuditLogOut,
    SpaceBlobInitInput,
    SpaceBlobOut,
    SpaceCapabilitiesOut,
    SpaceChangesPageOut,
    SpaceCreateInput,
    SpaceDeviceGrantOut,
    SpaceEntryCreateInput,
    SpaceEntryDetailOut,
    SpaceEntrySummaryOut,
    SpaceEntryUpdateInput,
    SpaceEnvelopeOut,
    SpaceEnvelopeUpdateInput,
    SpaceOut,
    SpacePasswordUnlockInput,
    SpaceRotateEpochInput,
    SpaceStandardCandidateOut,
    SpaceStandardMutation,
    SpaceStandardMutationOut,
    SpaceStandardResolution,
    SpaceStandardSnapshot,
    SpaceTokenCreateInput,
    SpaceTokenCreatedOut,
    SpaceTokenOut,
)


router = APIRouter(prefix="/api/v1/spaces", tags=["spaces"])


def _space_actor(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> service.SpaceActor:
    """统一解析用户 JWT 或空间专用 Token（ss_live_ / sv_live_）。拒绝其他任意凭据类型。"""
    if credentials is None or not credentials.credentials:
        raise HTTPException(401, "Missing authorization credential")
    raw = credentials.credentials
    if raw.startswith(service.STANDARD_TOKEN_PREFIX) or raw.startswith(service.VAULT_TOKEN_PREFIX):
        actor = service.authenticate_space_token(raw, db)
        if actor is None:
            raise HTTPException(401, "Invalid or revoked space token")
        return actor
    if raw.startswith(("nc_live_", "na_live_", "nd_live_", "sn_live_")):
        raise HTTPException(403, "This credential type cannot access Shared Space directly")
    user = authenticate_user_jwt(raw, db)
    if user is None:
        raise HTTPException(401, "Invalid authorization token")
    ws = get_personal_workspace(db, user)
    return service.SpaceActor(kind="user", workspace_id=ws.id, user_id=user.id, actor_id=str(user.id))


@router.get("/capabilities", response_model=SpaceCapabilitiesOut)
def get_capabilities(_actor: service.SpaceActor = Depends(_space_actor)):
    return service.get_capabilities()


@router.get("", response_model=list[SpaceOut])
def list_spaces(
    actor: service.SpaceActor = Depends(_space_actor),
    db: Session = Depends(get_db),
):
    return service.list_spaces(db, actor)


@router.post("", response_model=SpaceOut, status_code=201)
def create_space(
    payload: SpaceCreateInput,
    actor: service.SpaceActor = Depends(_space_actor),
    db: Session = Depends(get_db),
):
    return service.create_space(db, actor, payload)


@router.get("/{space_id}", response_model=SpaceOut)
def get_space(
    space_id: str,
    actor: service.SpaceActor = Depends(_space_actor),
    db: Session = Depends(get_db),
):
    return service.get_space(db, actor, space_id)


@router.delete("/{space_id}", status_code=204)
def delete_space(
    space_id: str,
    actor: service.SpaceActor = Depends(_space_actor),
    db: Session = Depends(get_db),
):
    service.archive_space(db, actor, space_id)
    return Response(status_code=204)


# ---------------- KeyEnvelope / 改密 / Epoch 轮换 ----------------


@router.get("/{space_id}/envelope", response_model=SpaceEnvelopeOut)
def get_envelope(
    space_id: str,
    epoch: int | None = Query(default=None, ge=1),
    actor: service.SpaceActor = Depends(_space_actor),
    db: Session = Depends(get_db),
):
    return service.get_envelope(db, actor, space_id, epoch=epoch)


@router.put("/{space_id}/envelope", response_model=SpaceEnvelopeOut)
def update_envelope(
    space_id: str,
    payload: SpaceEnvelopeUpdateInput,
    actor: service.SpaceActor = Depends(_space_actor),
    db: Session = Depends(get_db),
):
    return service.update_envelope_cas(db, actor, space_id, payload)


@router.post("/{space_id}/rotate-epoch", response_model=SpaceEnvelopeOut)
def rotate_epoch(
    space_id: str,
    payload: SpaceRotateEpochInput,
    actor: service.SpaceActor = Depends(_space_actor),
    db: Session = Depends(get_db),
):
    return service.rotate_epoch(db, actor, space_id, payload)


@router.post("/{space_id}/change-password", response_model=SpaceOut)
def change_protected_password(
    space_id: str,
    payload: ProtectedPasswordChangeInput,
    actor: service.SpaceActor = Depends(_space_actor),
    db: Session = Depends(get_db),
):
    return service.change_protected_password(db, actor, space_id, payload)


# ---------------- 分块文件暂存与下载 ----------------


@router.post("/{space_id}/blobs/init", response_model=SpaceBlobOut, status_code=201)
def init_blob(
    space_id: str,
    payload: SpaceBlobInitInput,
    actor: service.SpaceActor = Depends(_space_actor),
    db: Session = Depends(get_db),
):
    return service.init_blob(db, actor, space_id, payload)


@router.put("/{space_id}/blobs/{blob_id}/chunks/{chunk_index}", response_model=SpaceBlobOut)
async def put_blob_chunk(
    space_id: str,
    blob_id: str,
    chunk_index: int,
    request: Request,
    x_chunk_sha256: str | None = Header(default=None, alias="X-Chunk-Sha256"),
    actor: service.SpaceActor = Depends(_space_actor),
    db: Session = Depends(get_db),
):
    body = await request.body()
    return service.upload_blob_chunk(
        db,
        actor,
        space_id,
        blob_id,
        chunk_index,
        body,
        expected_sha256=x_chunk_sha256,
    )


@router.get("/{space_id}/blobs/{blob_id}/chunks/{chunk_index}")
def get_blob_chunk(
    space_id: str,
    blob_id: str,
    chunk_index: int,
    actor: service.SpaceActor = Depends(_space_actor),
    db: Session = Depends(get_db),
):
    data, digest = service.download_blob_chunk(db, actor, space_id, blob_id, chunk_index)
    headers = {"X-Chunk-Sha256": digest, "Cache-Control": "no-store"}
    return Response(content=data, media_type="application/octet-stream", headers=headers)


# ---------------- 条目读写、按次解锁与下载 ----------------


@router.get("/{space_id}/entries", response_model=list[SpaceEntrySummaryOut])
def list_entries(
    space_id: str,
    search: str | None = Query(default=None, max_length=120),
    entryType: str | None = Query(default=None),
    includeDeleted: bool = Query(default=False),
    actor: service.SpaceActor = Depends(_space_actor),
    db: Session = Depends(get_db),
):
    return service.list_entries(
        db,
        actor,
        space_id,
        search=search,
        entry_type=entryType,
        include_deleted=includeDeleted,
    )


@router.post("/{space_id}/entries", response_model=SpaceEntryDetailOut, status_code=201)
def create_entry(
    space_id: str,
    payload: SpaceEntryCreateInput,
    actor: service.SpaceActor = Depends(_space_actor),
    db: Session = Depends(get_db),
):
    return service.create_entry(db, actor, space_id, payload)


@router.get("/{space_id}/entries/{entry_id}", response_model=SpaceEntryDetailOut)
def get_entry(
    space_id: str,
    entry_id: str,
    revision: int | None = Query(default=None, ge=1),
    actor: service.SpaceActor = Depends(_space_actor),
    db: Session = Depends(get_db),
):
    return service.get_entry(db, actor, space_id, entry_id, revision=revision)


@router.post("/{space_id}/entries/{entry_id}/unlock", response_model=SpaceEntryDetailOut)
def unlock_protected_entry(
    space_id: str,
    entry_id: str,
    payload: SpacePasswordUnlockInput,
    actor: service.SpaceActor = Depends(_space_actor),
    db: Session = Depends(get_db),
):
    return service.unlock_protected_entry(
        db,
        actor,
        space_id,
        entry_id,
        password=payload.password,
        revision=payload.revision,
    )


@router.get("/{space_id}/entries/{entry_id}/download")
def download_entry_get(
    space_id: str,
    entry_id: str,
    revision: int | None = Query(default=None, ge=1),
    actor: service.SpaceActor = Depends(_space_actor),
    db: Session = Depends(get_db),
):
    data, mime, file_name = service.download_entry_bytes(db, actor, space_id, entry_id, revision=revision)
    encoded_name = quote(file_name)
    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}",
        "Cache-Control": "no-store",
    }
    return Response(content=data, media_type=mime, headers=headers)


@router.post("/{space_id}/entries/{entry_id}/download")
def download_entry_post(
    space_id: str,
    entry_id: str,
    payload: SpacePasswordUnlockInput,
    actor: service.SpaceActor = Depends(_space_actor),
    db: Session = Depends(get_db),
):
    data, mime, file_name = service.download_entry_bytes(
        db,
        actor,
        space_id,
        entry_id,
        password=payload.password,
        revision=payload.revision,
    )
    encoded_name = quote(file_name)
    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}",
        "Cache-Control": "no-store",
    }
    return Response(content=data, media_type=mime, headers=headers)


@router.put("/{space_id}/entries/{entry_id}", response_model=SpaceEntryDetailOut)
def update_entry(
    space_id: str,
    entry_id: str,
    payload: SpaceEntryUpdateInput,
    actor: service.SpaceActor = Depends(_space_actor),
    db: Session = Depends(get_db),
):
    return service.update_entry(db, actor, space_id, entry_id, payload)


@router.delete("/{space_id}/entries/{entry_id}", status_code=204)
def delete_entry(
    space_id: str,
    entry_id: str,
    actor: service.SpaceActor = Depends(_space_actor),
    db: Session = Depends(get_db),
):
    service.delete_entry(db, actor, space_id, entry_id)
    return Response(status_code=204)


@router.post("/{space_id}/entries/{entry_id}/sync", response_model=SpaceStandardMutationOut)
def sync_standard_entry(
    space_id: str,
    entry_id: str,
    payload: SpaceStandardMutation,
    actor: service.SpaceActor = Depends(_space_actor),
    db: Session = Depends(get_db),
):
    return service.sync_standard_entry(db, actor, space_id, entry_id, payload)


@router.get("/{space_id}/sync-conflicts", response_model=list[SpaceStandardCandidateOut])
def list_standard_conflicts(
    space_id: str,
    actor: service.SpaceActor = Depends(_space_actor),
    db: Session = Depends(get_db),
):
    return service.list_standard_conflicts(db, actor, space_id)


@router.get("/{space_id}/sync-snapshot", response_model=SpaceStandardSnapshot)
def standard_space_snapshot(
    space_id: str,
    actor: service.SpaceActor = Depends(_space_actor),
    db: Session = Depends(get_db),
):
    return service.standard_space_snapshot(db, actor, space_id)


@router.post("/{space_id}/sync-conflicts/{candidate_id}/resolve", response_model=SpaceStandardMutationOut)
def resolve_standard_conflict(
    space_id: str,
    candidate_id: str,
    payload: SpaceStandardResolution,
    actor: service.SpaceActor = Depends(_space_actor),
    db: Session = Depends(get_db),
):
    return service.resolve_standard_conflict(db, actor, space_id, candidate_id, payload)


# ---------------- 隔离增量游标、专用 Token 与审计 ----------------


@router.get("/{space_id}/changes", response_model=SpaceChangesPageOut)
def list_changes(
    space_id: str,
    sinceSeq: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    actor: service.SpaceActor = Depends(_space_actor),
    db: Session = Depends(get_db),
):
    return service.list_changes(db, actor, space_id, since_seq=sinceSeq, limit=limit)


@router.get("/{space_id}/tokens", response_model=list[SpaceTokenOut])
def list_tokens(
    space_id: str,
    actor: service.SpaceActor = Depends(_space_actor),
    db: Session = Depends(get_db),
):
    return service.list_tokens(db, actor, space_id)


@router.post("/{space_id}/tokens", response_model=SpaceTokenCreatedOut, status_code=201)
def create_token(
    space_id: str,
    payload: SpaceTokenCreateInput,
    actor: service.SpaceActor = Depends(_space_actor),
    db: Session = Depends(get_db),
):
    return service.create_token(db, actor, space_id, payload)


@router.delete("/{space_id}/tokens/{token_id}", status_code=204)
def revoke_token(
    space_id: str,
    token_id: str,
    actor: service.SpaceActor = Depends(_space_actor),
    db: Session = Depends(get_db),
):
    service.revoke_token(db, actor, space_id, token_id)
    return Response(status_code=204)


@router.get("/{space_id}/device-grants", response_model=list[SpaceDeviceGrantOut], dependencies=[Depends(require_core_mode)])
def list_device_grants(space_id: str, actor: service.SpaceActor = Depends(_space_actor), db: Session = Depends(get_db)):
    return service.list_device_grants(db, actor, space_id)


@router.put("/{space_id}/device-grants/{client_id}", status_code=204, dependencies=[Depends(require_core_mode)])
@router.delete("/{space_id}/device-grants/{client_id}", status_code=204, dependencies=[Depends(require_core_mode)])
def set_device_grant(
    space_id: str, client_id: str, request: Request,
    actor: service.SpaceActor = Depends(_space_actor), db: Session = Depends(get_db),
):
    service.set_device_grant(db, actor, space_id, client_id, allow=request.method == "PUT")
    return Response(status_code=204)


@router.get("/{space_id}/audit-logs", response_model=list[SpaceAuditLogOut])
def list_audit_logs(
    space_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    action: str | None = Query(default=None, max_length=48),
    actor: service.SpaceActor = Depends(_space_actor),
    db: Session = Depends(get_db),
):
    return service.list_audit_logs(db, actor, space_id, limit=limit, action=action)
