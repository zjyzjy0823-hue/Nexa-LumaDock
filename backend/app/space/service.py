"""Shared Space 三档分级核心业务、权限隔离、信封加解密、Token 与审计服务。"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import os
import secrets
from typing import Any, Literal
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..database import runtime_config
from ..models import (
    SharedSpace,
    SpaceAccessAuditLog,
    SpaceBlob,
    SpaceChange,
    SpaceEntry,
    SpaceEntryRevision,
    SpaceKeyEnvelope,
    SpaceMutationReceipt,
    SpaceSyncCandidate,
    SpaceToken,
    User,
    utcnow,
)
from ..utils.time import iso_utc
from ..workspaces import get_personal_workspace
from . import crypto, storage
from .schemas import (
    ProtectedPasswordChangeInput,
    SpaceAuditLogOut,
    SpaceBlobInitInput,
    SpaceBlobOut,
    SpaceCapabilitiesOut,
    SpaceChangeOut,
    SpaceChangesPageOut,
    SpaceCreateInput,
    SpaceEntryCreateInput,
    SpaceEntryDetailOut,
    SpaceEntrySummaryOut,
    SpaceEntryUpdateInput,
    SpaceEnvelopeOut,
    SpaceEnvelopeUpdateInput,
    SpaceOut,
    SpaceRotateEpochInput,
    SpaceStandardCandidateOut,
    SpaceStandardMutation,
    SpaceStandardMutationOut,
    SpaceStandardResolution,
    SpaceStandardSnapshot,
    SpaceTokenCreateInput,
    SpaceTokenCreatedOut,
    SpaceTokenOut,
    valid_uuid,
)


STANDARD_TOKEN_PREFIX = "ss_live_"
VAULT_TOKEN_PREFIX = "sv_live_"


@dataclass(frozen=True)
class SpaceActor:
    """统一的 Shared Space 访问主体。"""
    kind: Literal["user", "standard_token", "vault_token", "device"]
    workspace_id: str
    user_id: int
    actor_id: str
    token: SpaceToken | None = None


def _is_enabled() -> bool:
    env_val = os.environ.get("STUDIOLO_SHARED_SPACE_ENABLED")
    if env_val is not None:
        return env_val.strip().lower() in ("1", "true", "yes")
    return runtime_config.shared_space_enabled


def _require_enabled() -> None:
    if not _is_enabled():
        raise HTTPException(503, "Shared Space feature is disabled")


def _vault_master_key() -> str:
    env_key = os.environ.get("STUDIOLO_VAULT_MASTER_KEY")
    if env_key is not None:
        return env_key
    return runtime_config.vault_master_key


def _require_vault_workspace_key(workspace_id: str) -> bytes:
    master = _vault_master_key()
    if len(master.encode("utf-8")) < crypto.KEY_BYTES:
        raise HTTPException(503, "Protected vault master key is not configured")
    return crypto.derive_vault_workspace_key(master, workspace_id)


def _max_file_bytes() -> int:
    env_val = os.environ.get("STUDIOLO_SPACE_MAX_FILE_BYTES")
    if env_val:
        return max(1024 * 1024, int(env_val))
    return runtime_config.space_max_file_bytes


def _default_quota_bytes() -> int:
    env_val = os.environ.get("STUDIOLO_SPACE_DEFAULT_QUOTA_BYTES")
    if env_val:
        return max(_max_file_bytes(), int(env_val))
    return runtime_config.space_default_quota_bytes


def get_capabilities() -> SpaceCapabilitiesOut:
    enabled = _is_enabled()
    protected_ok = len(_vault_master_key().encode("utf-8")) >= crypto.KEY_BYTES
    return SpaceCapabilitiesOut(
        enabled=enabled,
        protectedAvailable=protected_ok,
        maxFileBytes=_max_file_bytes(),
        defaultQuotaBytes=_default_quota_bytes(),
        defaultChunkSize=crypto.DEFAULT_CHUNK_SIZE,
        tiers=["standard", "protected", "e2ee"],
    )


def _record_audit(
    db: Session,
    *,
    workspace_id: str,
    space_id: str,
    actor_kind: str,
    actor_id: str,
    action: str,
    outcome: str = "allowed",
    entry_id: str | None = None,
    detail: str = "",
) -> None:
    """记录脱敏后的访问审计日志（严禁包含明文与密码）。"""
    log = SpaceAccessAuditLog(
        id=str(uuid4()),
        workspace_id=workspace_id,
        space_id=space_id,
        entry_id=entry_id,
        actor_kind=actor_kind,
        actor_id=actor_id[:64],
        action=action[:48],
        outcome=outcome[:20],
        detail=detail[:240],
        created_at=utcnow(),
    )
    db.add(log)


def _record_change(
    db: Session,
    *,
    workspace_id: str,
    space_id: str,
    entry_id: str | None,
    revision: int,
    epoch: int,
    change_type: str,
) -> None:
    if db.get_bind().dialect.name == "postgresql":
        # Allocate change sequences in commit order within a space.
        db.execute(select(SharedSpace.id).where(SharedSpace.id == space_id).with_for_update())
    db.add(
        SpaceChange(
            workspace_id=workspace_id,
            space_id=space_id,
            entry_id=entry_id,
            revision=revision,
            epoch=epoch,
            change_type=change_type,
            created_at=utcnow(),
        )
    )


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def authenticate_space_token(raw_token: str, db: Session) -> SpaceActor | None:
    """校验 ss_live_ / sv_live_ 空间专用 Token，校验吊销状态与有效期。"""
    if raw_token.startswith(STANDARD_TOKEN_PREFIX):
        expected_kind = "standard"
        actor_kind: Literal["standard_token", "vault_token"] = "standard_token"
    elif raw_token.startswith(VAULT_TOKEN_PREFIX):
        expected_kind = "vault"
        actor_kind = "vault_token"
    else:
        return None

    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    token = db.scalar(
        select(SpaceToken).where(
            SpaceToken.token_hash == token_hash,
            SpaceToken.token_kind == expected_kind,
            SpaceToken.revoked_at.is_(None),
        )
    )
    if token is None:
        return None
    expires_at = _as_utc(token.expires_at)
    if expires_at is not None and expires_at <= utcnow():
        return None

    token.last_used_at = utcnow()
    db.flush()
    return SpaceActor(
        kind=actor_kind,
        workspace_id=token.workspace_id,
        user_id=token.user_id,
        actor_id=token.id,
        token=token,
    )


def _validate_e2ee_envelope_structure(envelope: dict[str, Any], expected_epoch: int) -> None:
    if not isinstance(envelope, dict):
        raise HTTPException(422, "Invalid KeyEnvelope")
    if envelope.get("version") != crypto.CRYPTO_PROTOCOL_VERSION:
        raise HTTPException(422, "Unsupported KeyEnvelope version")
    if envelope.get("aead") != crypto.AEAD_ALGORITHM:
        raise HTTPException(422, "Unsupported KeyEnvelope AEAD algorithm")
    if envelope.get("epoch") != expected_epoch:
        raise HTTPException(422, f"KeyEnvelope epoch must equal {expected_epoch}")
    kdf = envelope.get("kdf")
    if not isinstance(kdf, dict) or kdf.get("algorithm") != crypto.KDF_ALGORITHM:
        raise HTTPException(422, "Unsupported KeyEnvelope KDF algorithm")
    try:
        salt = crypto.b64url_decode(str(kdf.get("saltB64", "")))
        nonce = crypto.b64url_decode(str(envelope.get("nonceB64", "")))
        wrapped = crypto.b64url_decode(str(envelope.get("wrappedKeyB64", "")))
    except crypto.SpaceCryptoError as exc:
        raise HTTPException(422, str(exc)) from exc
    if len(salt) < crypto.SALT_BYTES or len(nonce) != crypto.NONCE_BYTES or len(wrapped) != crypto.KEY_BYTES + crypto.TAG_BYTES:
        raise HTTPException(422, "KeyEnvelope binary field length invalid")


def _validate_wrapped_dek_structure(wrapped_dek: dict[str, Any], expected_epoch: int) -> None:
    if not isinstance(wrapped_dek, dict):
        raise HTTPException(422, "Invalid WrappedDek")
    if wrapped_dek.get("version") != crypto.CRYPTO_PROTOCOL_VERSION:
        raise HTTPException(422, "Unsupported WrappedDek version")
    if wrapped_dek.get("aead") != crypto.AEAD_ALGORITHM:
        raise HTTPException(422, "Unsupported WrappedDek AEAD algorithm")
    if wrapped_dek.get("epoch") != expected_epoch:
        raise HTTPException(409, f"Stale epoch: expected {expected_epoch}")
    try:
        nonce = crypto.b64url_decode(str(wrapped_dek.get("nonceB64", "")))
        ct = crypto.b64url_decode(str(wrapped_dek.get("wrappedDekB64", "")))
    except crypto.SpaceCryptoError as exc:
        raise HTTPException(422, str(exc)) from exc
    if len(nonce) != crypto.NONCE_BYTES or len(ct) != crypto.KEY_BYTES + crypto.TAG_BYTES:
        raise HTTPException(422, "WrappedDek binary field length invalid")


def _owned_space(db: Session, workspace_id: str, space_id: str, *, standard_only: bool = False) -> SharedSpace:
    try:
        sid = valid_uuid(space_id)
    except ValueError as exc:
        raise HTTPException(404, "Space not found") from exc
    query = select(SharedSpace).where(
        SharedSpace.id == sid,
        SharedSpace.workspace_id == workspace_id,
        SharedSpace.archived_at.is_(None),
    )
    if standard_only:
        query = query.where(SharedSpace.tier == "standard")
    space = db.scalar(query)
    if space is None:
        raise HTTPException(404, "Space not found")
    return space


def _enforce_token_space_access(
    db: Session,
    actor: SpaceActor,
    space: SharedSpace,
    *,
    required_scope: Literal["read", "write"],
    entry_id: str | None = None,
    action: str = "access",
) -> None:
    """强边界检查：按三档矩阵强制隔离 standard_token 与 vault_token。"""
    if actor.kind == "user":
        return
    if actor.kind == "device":
        if space.tier != "standard" or required_scope != "read":
            raise HTTPException(404, "Space not found")
        return

    token = actor.token
    assert token is not None

    if token.space_id != space.id:
        _record_audit(
            db,
            workspace_id=space.workspace_id,
            space_id=space.id,
            actor_kind=actor.kind,
            actor_id=actor.actor_id,
            action=action,
            outcome="denied",
            entry_id=entry_id,
            detail="Token bound to another space",
        )
        db.commit()
        raise HTTPException(403, "Token is not authorized for this space")

    if space.tier == "e2ee":
        _record_audit(
            db,
            workspace_id=space.workspace_id,
            space_id=space.id,
            actor_kind=actor.kind,
            actor_id=actor.actor_id,
            action=action,
            outcome="denied",
            entry_id=entry_id,
            detail="Direct API tokens are forbidden on E2EE spaces",
        )
        db.commit()
        raise HTTPException(403, "API tokens cannot access E2EE spaces")

    if actor.kind == "standard_token" and space.tier != "standard":
        _record_audit(
            db,
            workspace_id=space.workspace_id,
            space_id=space.id,
            actor_kind=actor.kind,
            actor_id=actor.actor_id,
            action=action,
            outcome="denied",
            entry_id=entry_id,
            detail="Standard token cannot access protected space",
        )
        db.commit()
        raise HTTPException(403, "Standard token cannot access protected space")

    if actor.kind == "vault_token" and space.tier != "protected":
        _record_audit(
            db,
            workspace_id=space.workspace_id,
            space_id=space.id,
            actor_kind=actor.kind,
            actor_id=actor.actor_id,
            action=action,
            outcome="denied",
            entry_id=entry_id,
            detail="Vault token is only valid for protected spaces",
        )
        db.commit()
        raise HTTPException(403, "Vault token is only valid for protected spaces")

    scopes = set(token.scopes_json or [])
    if required_scope not in scopes:
        _record_audit(
            db,
            workspace_id=space.workspace_id,
            space_id=space.id,
            actor_kind=actor.kind,
            actor_id=actor.actor_id,
            action=action,
            outcome="denied",
            entry_id=entry_id,
            detail=f"Missing required scope: {required_scope}",
        )
        db.commit()
        raise HTTPException(403, f"Token missing '{required_scope}' scope")

    if entry_id is not None and token.entry_ids_json is not None:
        if entry_id not in set(token.entry_ids_json):
            _record_audit(
                db,
                workspace_id=space.workspace_id,
                space_id=space.id,
                actor_kind=actor.kind,
                actor_id=actor.actor_id,
                action=action,
                outcome="denied",
                entry_id=entry_id,
                detail="Entry not in token allowlist",
            )
            db.commit()
            raise HTTPException(403, "Token is not authorized for this entry")


def _space_to_out(db: Session, space: SharedSpace) -> SpaceOut:
    entry_count = db.scalar(
        select(func.count(SpaceEntry.id)).where(
            SpaceEntry.space_id == space.id,
            SpaceEntry.deleted_at.is_(None),
        )
    ) or 0
    return SpaceOut(
        id=space.id,
        workspaceId=space.workspace_id,
        name=space.name,
        description=space.description,
        tier=space.tier,  # type: ignore[arg-type]
        activeEpoch=int(space.active_epoch),
        envelopeVersion=int(space.envelope_version),
        quotaBytes=int(space.quota_bytes),
        usedBytes=int(space.used_bytes),
        entryCount=int(entry_count),
        archivedAt=iso_utc(space.archived_at) if space.archived_at else None,
        createdAt=iso_utc(space.created_at),
        updatedAt=iso_utc(space.updated_at),
    )


def list_spaces(db: Session, actor: SpaceActor, *, space_ids: set[str] | None = None) -> list[SpaceOut]:
    _require_enabled()
    query = select(SharedSpace).where(
        SharedSpace.workspace_id == actor.workspace_id,
        SharedSpace.archived_at.is_(None),
    )
    if actor.token is not None:
        query = query.where(SharedSpace.id == actor.token.space_id)
    if actor.kind == "device":
        query = query.where(SharedSpace.tier == "standard", SharedSpace.id.in_(space_ids or set()))
    spaces = list(db.scalars(query.order_by(SharedSpace.created_at.desc())))
    return [_space_to_out(db, sp) for sp in spaces]


def get_space(db: Session, actor: SpaceActor, space_id: str) -> SpaceOut:
    _require_enabled()
    space = _owned_space(db, actor.workspace_id, space_id)
    _enforce_token_space_access(db, actor, space, required_scope="read", action="space.get")
    return _space_to_out(db, space)


def create_space(db: Session, actor: SpaceActor, payload: SpaceCreateInput) -> SpaceOut:
    _require_enabled()
    if actor.kind != "user":
        raise HTTPException(403, "Only workspace user can create spaces")

    now = utcnow()
    quota_bytes = payload.quotaBytes if payload.quotaBytes is not None else _default_quota_bytes()
    verifier: str | None = None

    if payload.tier == "protected":
        _require_vault_workspace_key(actor.workspace_id)
        if not payload.password:
            raise HTTPException(422, "Protected space requires an initial password")
        if payload.envelope is not None:
            raise HTTPException(422, "Protected space does not accept client KeyEnvelope")
        verifier = crypto.hash_space_password(payload.password)
    elif payload.tier == "e2ee":
        if payload.password is not None:
            raise HTTPException(422, "E2EE space must never send plaintext password to Core")
        if payload.envelope is None:
            raise HTTPException(422, "E2EE space requires an initial epoch=1 KeyEnvelope")
        _validate_e2ee_envelope_structure(payload.envelope, expected_epoch=1)
    else:
        if payload.password is not None or payload.envelope is not None:
            raise HTTPException(422, "Standard space does not accept password or KeyEnvelope")

    if payload.id is not None:
        try:
            space_id = valid_uuid(payload.id)
        except ValueError as exc:
            raise HTTPException(422, "Invalid space id") from exc
        if db.get(SharedSpace, space_id) is not None:
            raise HTTPException(409, "Space id already exists")
    else:
        space_id = str(uuid4())

    space = SharedSpace(
        id=space_id,
        user_id=actor.user_id,
        workspace_id=actor.workspace_id,
        name=payload.name.strip(),
        description=payload.description.strip(),
        tier=payload.tier,
        active_epoch=1,
        envelope_version=1,
        password_verifier=verifier,
        quota_bytes=quota_bytes,
        used_bytes=0,
        created_at=now,
        updated_at=now,
    )
    db.add(space)
    db.flush()

    if payload.tier == "e2ee" and payload.envelope is not None:
        db.add(
            SpaceKeyEnvelope(
                id=str(uuid4()),
                workspace_id=actor.workspace_id,
                space_id=space.id,
                epoch=1,
                envelope_version=1,
                envelope_json=payload.envelope,
                created_at=now,
                updated_at=now,
            )
        )

    _record_audit(
        db,
        workspace_id=actor.workspace_id,
        space_id=space.id,
        actor_kind="user",
        actor_id=actor.actor_id,
        action="space.create",
        detail=f"tier={payload.tier}",
    )
    db.commit()
    db.refresh(space)
    return _space_to_out(db, space)


def archive_space(db: Session, actor: SpaceActor, space_id: str) -> None:
    _require_enabled()
    if actor.kind != "user":
        raise HTTPException(403, "Only workspace user can delete spaces")
    space = _owned_space(db, actor.workspace_id, space_id)
    now = utcnow()
    space.archived_at = now
    space.updated_at = now
    # 立即吊销该空间所有活跃 Token
    tokens = list(db.scalars(select(SpaceToken).where(SpaceToken.space_id == space.id, SpaceToken.revoked_at.is_(None))))
    for tk in tokens:
        tk.revoked_at = now
    _record_audit(
        db,
        workspace_id=actor.workspace_id,
        space_id=space.id,
        actor_kind="user",
        actor_id=actor.actor_id,
        action="space.archive",
    )
    db.commit()


# ---------------- E2EE KeyEnvelope 改密与 Epoch 轮换 ----------------


def get_envelope(db: Session, actor: SpaceActor, space_id: str, epoch: int | None = None) -> SpaceEnvelopeOut:
    _require_enabled()
    if actor.kind != "user":
        raise HTTPException(403, "API tokens cannot access E2EE envelopes")
    space = _owned_space(db, actor.workspace_id, space_id)
    if space.tier != "e2ee":
        raise HTTPException(400, "Only E2EE spaces have a KeyEnvelope")
    target_epoch = epoch if epoch is not None else int(space.active_epoch)
    env = db.scalar(
        select(SpaceKeyEnvelope).where(SpaceKeyEnvelope.space_id == space.id, SpaceKeyEnvelope.epoch == target_epoch)
    )
    if env is None:
        raise HTTPException(404, "KeyEnvelope not found for epoch")
    return SpaceEnvelopeOut(
        spaceId=space.id,
        epoch=int(env.epoch),
        envelopeVersion=int(env.envelope_version),
        envelope=dict(env.envelope_json),
        updatedAt=iso_utc(env.updated_at),
    )


def update_envelope_cas(
    db: Session,
    actor: SpaceActor,
    space_id: str,
    payload: SpaceEnvelopeUpdateInput,
) -> SpaceEnvelopeOut:
    """常规改密：保持 active_epoch 不变，按 envelope_version CAS 更新 KeyEnvelope。"""
    _require_enabled()
    if actor.kind != "user":
        raise HTTPException(403, "Only workspace user can update KeyEnvelope")
    space = _owned_space(db, actor.workspace_id, space_id)
    if space.tier != "e2ee":
        raise HTTPException(400, "Only E2EE spaces support KeyEnvelope updates")
    if int(space.envelope_version) != payload.expectedEnvelopeVersion:
        raise HTTPException(409, "Envelope version conflict; reload and retry")

    _validate_e2ee_envelope_structure(payload.envelope, expected_epoch=int(space.active_epoch))
    env = db.scalar(
        select(SpaceKeyEnvelope).where(
            SpaceKeyEnvelope.space_id == space.id,
            SpaceKeyEnvelope.epoch == space.active_epoch,
        )
    )
    if env is None:
        raise HTTPException(404, "Active KeyEnvelope not found")

    now = utcnow()
    next_ver = int(space.envelope_version) + 1
    env.envelope_json = payload.envelope
    env.envelope_version = next_ver
    env.updated_at = now
    space.envelope_version = next_ver
    space.updated_at = now

    _record_change(
        db,
        workspace_id=space.workspace_id,
        space_id=space.id,
        entry_id=None,
        revision=next_ver,
        epoch=int(space.active_epoch),
        change_type="envelope_updated",
    )
    _record_audit(
        db,
        workspace_id=space.workspace_id,
        space_id=space.id,
        actor_kind="user",
        actor_id=actor.actor_id,
        action="space.envelope.rewrap",
        detail=f"epoch={space.active_epoch},ver={next_ver}",
    )
    db.commit()
    return SpaceEnvelopeOut(
        spaceId=space.id,
        epoch=int(env.epoch),
        envelopeVersion=next_ver,
        envelope=dict(env.envelope_json),
        updatedAt=iso_utc(now),
    )


def rotate_epoch(
    db: Session,
    actor: SpaceActor,
    space_id: str,
    payload: SpaceRotateEpochInput,
) -> SpaceEnvelopeOut:
    """泄露/撤销轮换：原子递增 active_epoch 并登记新 KeyEnvelope，后续拒绝旧 epoch 写入。"""
    _require_enabled()
    if actor.kind != "user":
        raise HTTPException(403, "Only workspace user can rotate epoch")
    space = _owned_space(db, actor.workspace_id, space_id)
    if space.tier != "e2ee":
        raise HTTPException(400, "Only E2EE spaces support epoch rotation")
    if int(space.active_epoch) != payload.expectedActiveEpoch:
        raise HTTPException(409, "Active epoch conflict; reload and retry")

    next_epoch = int(space.active_epoch) + 1
    _validate_e2ee_envelope_structure(payload.envelope, expected_epoch=next_epoch)
    now = utcnow()
    next_ver = int(space.envelope_version) + 1

    env = SpaceKeyEnvelope(
        id=str(uuid4()),
        workspace_id=space.workspace_id,
        space_id=space.id,
        epoch=next_epoch,
        envelope_version=next_ver,
        envelope_json=payload.envelope,
        created_at=now,
        updated_at=now,
    )
    db.add(env)
    space.active_epoch = next_epoch
    space.envelope_version = next_ver
    space.updated_at = now

    _record_change(
        db,
        workspace_id=space.workspace_id,
        space_id=space.id,
        entry_id=None,
        revision=next_ver,
        epoch=next_epoch,
        change_type="epoch_rotated",
    )
    _record_audit(
        db,
        workspace_id=space.workspace_id,
        space_id=space.id,
        actor_kind="user",
        actor_id=actor.actor_id,
        action="space.epoch.rotate",
        detail=f"epoch={next_epoch}",
    )
    db.commit()
    return SpaceEnvelopeOut(
        spaceId=space.id,
        epoch=next_epoch,
        envelopeVersion=next_ver,
        envelope=dict(env.envelope_json),
        updatedAt=iso_utc(now),
    )


def change_protected_password(
    db: Session,
    actor: SpaceActor,
    space_id: str,
    payload: ProtectedPasswordChangeInput,
) -> SpaceOut:
    """修改 protected 档空间的 UI 按次访问密码。"""
    _require_enabled()
    if actor.kind != "user":
        raise HTTPException(403, "Only workspace user can change space password")
    space = _owned_space(db, actor.workspace_id, space_id)
    if space.tier != "protected" or not space.password_verifier:
        raise HTTPException(400, "Only protected spaces support password change via this endpoint")
    if not crypto.verify_space_password(payload.oldPassword, space.password_verifier):
        _record_audit(
            db,
            workspace_id=space.workspace_id,
            space_id=space.id,
            actor_kind="user",
            actor_id=actor.actor_id,
            action="space.password.change",
            outcome="denied",
            detail="Old password mismatch",
        )
        db.commit()
        raise HTTPException(403, "Incorrect space password")

    space.password_verifier = crypto.hash_space_password(payload.newPassword)
    space.updated_at = utcnow()
    _record_audit(
        db,
        workspace_id=space.workspace_id,
        space_id=space.id,
        actor_kind="user",
        actor_id=actor.actor_id,
        action="space.password.change",
    )
    db.commit()
    return _space_to_out(db, space)


# ---------------- 分块文件暂存上传与下载 ----------------


def _blob_to_out(blob: SpaceBlob) -> SpaceBlobOut:
    uploaded = sorted(int(k) for k in (blob.chunks_json or {}).keys())
    return SpaceBlobOut(
        id=blob.id,
        spaceId=blob.space_id,
        chunkSize=int(blob.chunk_size),
        chunkCount=int(blob.chunk_count),
        totalSize=int(blob.total_size),
        uploadedChunks=uploaded,
        committedAt=iso_utc(blob.committed_at) if blob.committed_at else None,
        createdAt=iso_utc(blob.created_at),
    )


def init_blob(db: Session, actor: SpaceActor, space_id: str, payload: SpaceBlobInitInput) -> SpaceBlobOut:
    _require_enabled()
    space = _owned_space(db, actor.workspace_id, space_id)
    _enforce_token_space_access(db, actor, space, required_scope="write", action="blob.init")

    max_bytes = _max_file_bytes()
    if payload.totalSize > max_bytes:
        raise HTTPException(413, f"File exceeds max allowed size ({max_bytes} bytes)")
    if int(space.used_bytes) + payload.totalSize > int(space.quota_bytes):
        raise HTTPException(413, "Space storage quota exceeded")

    blob = SpaceBlob(
        id=str(uuid4()),
        workspace_id=space.workspace_id,
        space_id=space.id,
        chunk_size=payload.chunkSize,
        chunk_count=payload.chunkCount,
        total_size=payload.totalSize,
        chunks_json={},
        created_at=utcnow(),
    )
    db.add(blob)
    db.commit()
    db.refresh(blob)
    return _blob_to_out(blob)


def upload_blob_chunk(
    db: Session,
    actor: SpaceActor,
    space_id: str,
    blob_id: str,
    chunk_index: int,
    data: bytes,
    expected_sha256: str | None = None,
) -> SpaceBlobOut:
    _require_enabled()
    space = _owned_space(db, actor.workspace_id, space_id)
    _enforce_token_space_access(db, actor, space, required_scope="write", action="blob.chunk.put")

    try:
        bid = valid_uuid(blob_id)
    except ValueError as exc:
        raise HTTPException(404, "Space blob not found") from exc

    blob = db.scalar(select(SpaceBlob).where(SpaceBlob.id == bid, SpaceBlob.space_id == space.id))
    if blob is None:
        raise HTTPException(404, "Space blob not found")
    if blob.committed_at is not None:
        raise HTTPException(409, "Space blob is already committed")
    if chunk_index < 0 or chunk_index >= int(blob.chunk_count):
        raise HTTPException(422, "Chunk index out of range")
    if len(data) > int(blob.chunk_size) + crypto.NONCE_BYTES + crypto.TAG_BYTES:
        raise HTTPException(413, "Chunk exceeds declared chunkSize")

    digest, size_bytes = storage.write_chunk_bytes(
        workspace_id=space.workspace_id,
        space_id=space.id,
        blob_id=blob.id,
        chunk_index=chunk_index,
        data=data,
        expected_sha256=expected_sha256,
    )
    chunks = dict(blob.chunks_json or {})
    chunks[str(chunk_index)] = {"sha256": digest, "size": size_bytes}
    blob.chunks_json = chunks
    db.commit()
    db.refresh(blob)
    return _blob_to_out(blob)


def download_blob_chunk(
    db: Session,
    actor: SpaceActor,
    space_id: str,
    blob_id: str,
    chunk_index: int,
) -> tuple[bytes, str]:
    """下载原始分块（e2ee 客户端拉密文块；standard 拉文件块；protected 禁止绕过门禁直拉原始块）。"""
    _require_enabled()
    space = _owned_space(db, actor.workspace_id, space_id, standard_only=actor.kind == "device")
    if space.tier == "protected":
        raise HTTPException(403, "Protected space blobs must be downloaded via authenticated unlock or Vault Token")
    _enforce_token_space_access(db, actor, space, required_scope="read", action="blob.chunk.get")

    try:
        bid = valid_uuid(blob_id)
    except ValueError as exc:
        raise HTTPException(404, "Space blob not found") from exc

    blob = db.scalar(select(SpaceBlob).where(SpaceBlob.id == bid, SpaceBlob.space_id == space.id))
    if blob is None:
        raise HTTPException(404, "Space blob not found")
    meta = (blob.chunks_json or {}).get(str(chunk_index))
    if not isinstance(meta, dict):
        raise HTTPException(404, "Space blob chunk not found")
    data = storage.read_chunk_bytes(
        workspace_id=space.workspace_id,
        space_id=space.id,
        blob_id=blob.id,
        chunk_index=chunk_index,
    )
    return data, str(meta.get("sha256", ""))


# ---------------- 条目读写与三档门禁 ----------------


def _require_protected_password(db: Session, actor: SpaceActor, space: SharedSpace, password: str | None, *, entry_id: str | None, action: str) -> None:
    if not password or not space.password_verifier or not crypto.verify_space_password(password, space.password_verifier):
        _record_audit(
            db,
            workspace_id=space.workspace_id,
            space_id=space.id,
            actor_kind=actor.kind,
            actor_id=actor.actor_id,
            action=action,
            outcome="denied",
            entry_id=entry_id,
            detail="Invalid or missing space password",
        )
        db.commit()
        raise HTTPException(403, "Invalid space password")


def _extract_plaintext_bytes(
    content_text: str | None,
    content_base64: str | None,
    *,
    allow_file_note: bool = False,
) -> tuple[bytes, bool]:
    """解析请求中提交的文本或 Base64 二进制内容，返回 (raw_bytes, is_text)。"""
    if content_text is not None and content_base64 is not None and not allow_file_note:
        raise HTTPException(422, "Provide either contentText or contentBase64, not both")
    if content_base64 is not None:
        try:
            return base64.b64decode(content_base64, validate=True), False
        except Exception as exc:
            raise HTTPException(422, "Invalid contentBase64 payload") from exc
    if content_text is not None:
        return content_text.encode("utf-8"), True
    return b"", True


def _normalize_file_note(note: str | None) -> str | None:
    if note is None:
        return None
    cleaned = note.strip()
    return cleaned or None


def _store_protected_encrypted_payload(
    db: Session,
    *,
    space: SharedSpace,
    entry_id: str,
    revision: int,
    raw_bytes: bytes,
    note_text: str | None = None,
) -> tuple[SpaceBlob, dict[str, Any], str | None, int, str]:
    """为 protected 档条目生成独立 DEK，服务端信封加密分块落盘，绝不写明文入库。"""
    ws_key = _require_vault_workspace_key(space.workspace_id)
    chunk_size = crypto.DEFAULT_CHUNK_SIZE
    dek = secrets.token_bytes(crypto.KEY_BYTES)
    wrapped_dek = crypto.wrap_dek(
        wrapping_key=ws_key,
        dek=dek,
        workspace_id=space.workspace_id,
        space_id=space.id,
        entry_id=entry_id,
        revision=revision,
        epoch=int(space.active_epoch),
    )

    encrypted_manifest_b64: str | None = None
    cleaned_note = _normalize_file_note(note_text)
    if cleaned_note is not None:
        encrypted_manifest_b64 = crypto.encrypt_manifest(
            dek=dek,
            manifest={"summary": cleaned_note},
            workspace_id=space.workspace_id,
            space_id=space.id,
            entry_id=entry_id,
            revision=revision,
            epoch=int(space.active_epoch),
        )

    chunks_raw = [raw_bytes[i : i + chunk_size] for i in range(0, len(raw_bytes), chunk_size)] or [b""]
    blob_id = str(uuid4())
    chunks_meta: dict[str, Any] = {}
    total_ct_size = 0
    for idx, pt_chunk in enumerate(chunks_raw):
        ct = crypto.encrypt_chunk(
            dek=dek,
            plaintext=pt_chunk,
            workspace_id=space.workspace_id,
            space_id=space.id,
            entry_id=entry_id,
            revision=revision,
            chunk_index=idx,
            epoch=int(space.active_epoch),
        )
        digest, sz = storage.write_chunk_bytes(
            workspace_id=space.workspace_id,
            space_id=space.id,
            blob_id=blob_id,
            chunk_index=idx,
            data=ct,
        )
        chunks_meta[str(idx)] = {"sha256": digest, "size": sz}
        total_ct_size += sz

    now = utcnow()
    blob = SpaceBlob(
        id=blob_id,
        workspace_id=space.workspace_id,
        space_id=space.id,
        chunk_size=chunk_size,
        chunk_count=len(chunks_raw),
        total_size=total_ct_size,
        chunks_json=chunks_meta,
        committed_at=now,
        created_at=now,
    )
    db.add(blob)
    db.flush()
    return blob, wrapped_dek, encrypted_manifest_b64, total_ct_size, crypto.sha256_hex(raw_bytes)


def _decrypt_protected_revision_payload(space: SharedSpace, entry: SpaceEntry, rev: SpaceEntryRevision) -> tuple[bytes, str | None]:
    """解密 protected 档修订的二进制载荷以及可选的加密文件备注。"""
    if rev.wrapped_dek_json is None or rev.blob_id is None:
        return b"", None
    ws_key = _require_vault_workspace_key(space.workspace_id)
    dek = crypto.unwrap_dek(
        wrapping_key=ws_key,
        wrapped_dek=rev.wrapped_dek_json,
        workspace_id=space.workspace_id,
        space_id=space.id,
        entry_id=entry.id,
        revision=int(rev.revision),
        expected_epoch=int(rev.epoch),
    )
    out = bytearray()
    for idx in range(int(rev.chunk_count)):
        ct = storage.read_chunk_bytes(
            workspace_id=space.workspace_id,
            space_id=space.id,
            blob_id=rev.blob_id,
            chunk_index=idx,
        )
        out.extend(
            crypto.decrypt_chunk(
                dek=dek,
                ciphertext_chunk=ct,
                workspace_id=space.workspace_id,
                space_id=space.id,
                entry_id=entry.id,
                revision=int(rev.revision),
                chunk_index=idx,
                epoch=int(rev.epoch),
            )
        )
    note_text: str | None = None
    if rev.encrypted_manifest_b64:
        manifest = crypto.decrypt_manifest(
            dek=dek,
            encrypted_manifest_b64=rev.encrypted_manifest_b64,
            workspace_id=space.workspace_id,
            space_id=space.id,
            entry_id=entry.id,
            revision=int(rev.revision),
            epoch=int(rev.epoch),
        )
        raw_note = manifest.get("summary")
        if isinstance(raw_note, str) and raw_note.strip():
            note_text = raw_note
    return bytes(out), note_text


def _decrypt_protected_revision_bytes(space: SharedSpace, entry: SpaceEntry, rev: SpaceEntryRevision) -> bytes:
    raw, _note = _decrypt_protected_revision_payload(space, entry, rev)
    return raw


def _finalize_staged_blob(db: Session, space: SharedSpace, blob_id: str) -> SpaceBlob:
    try:
        bid = valid_uuid(blob_id)
    except ValueError as exc:
        raise HTTPException(422, "Invalid blobId") from exc
    blob = db.scalar(select(SpaceBlob).where(SpaceBlob.id == bid, SpaceBlob.space_id == space.id))
    if blob is None:
        raise HTTPException(404, "Staged blob not found")
    uploaded = blob.chunks_json or {}
    if len(uploaded) != int(blob.chunk_count):
        raise HTTPException(422, "Not all blob chunks have been uploaded")
    actual_total = sum(int(meta["size"]) for meta in uploaded.values())
    if int(space.used_bytes) + actual_total > int(space.quota_bytes):
        raise HTTPException(413, "Space storage quota exceeded")
    blob.total_size = actual_total
    if blob.committed_at is None:
        blob.committed_at = utcnow()
    return blob


def _entry_summary(db: Session, space: SharedSpace, entry: SpaceEntry, latest_rev: SpaceEntryRevision | None) -> SpaceEntrySummaryOut:
    has_conflict = bool(
        db.scalar(
            select(func.count(SpaceEntryRevision.id)).where(
                SpaceEntryRevision.entry_id == entry.id,
                SpaceEntryRevision.is_conflict.is_(True),
            )
        )
    )
    if space.tier == "standard" and not has_conflict:
        has_conflict = db.scalar(select(SpaceSyncCandidate.id).where(
            SpaceSyncCandidate.space_id == space.id,
            SpaceSyncCandidate.entry_id == entry.id,
            SpaceSyncCandidate.resolved_at.is_(None),
        ).limit(1)) is not None
    return SpaceEntrySummaryOut(
        id=entry.id,
        spaceId=entry.space_id,
        tier=space.tier,  # type: ignore[arg-type]
        entryType=entry.entry_type,  # type: ignore[arg-type]
        currentRevision=int(entry.current_revision),
        activeEpoch=int(entry.active_epoch),
        title=None if space.tier == "e2ee" else entry.title,
        fileName=None if space.tier == "e2ee" else entry.file_name,
        mime="application/octet-stream" if space.tier == "e2ee" else entry.mime,
        tags=[] if space.tier == "e2ee" else list(entry.tags_json or []),
        sizeBytes=int(entry.size_bytes),
        hasConflict=has_conflict,
        deletedAt=iso_utc(entry.deleted_at) if entry.deleted_at else None,
        createdAt=iso_utc(entry.created_at),
        updatedAt=iso_utc(entry.updated_at),
        wrappedDek=latest_rev.wrapped_dek_json if (space.tier == "e2ee" and latest_rev) else None,
        encryptedManifestB64=latest_rev.encrypted_manifest_b64 if (space.tier == "e2ee" and latest_rev) else None,
        blobId=latest_rev.blob_id if latest_rev else None,
        chunkCount=int(latest_rev.chunk_count) if latest_rev else 0,
        chunkSize=int(latest_rev.chunk_size) if latest_rev else crypto.DEFAULT_CHUNK_SIZE,
    )


def _entry_detail(
    db: Session,
    space: SharedSpace,
    entry: SpaceEntry,
    rev: SpaceEntryRevision,
    *,
    content_text: str | None = None,
    content_base64: str | None = None,
    locked: bool = False,
) -> SpaceEntryDetailOut:
    summary = _entry_summary(db, space, entry, rev)
    conflict_revs = list(
        db.scalars(
            select(SpaceEntryRevision.revision)
            .where(SpaceEntryRevision.entry_id == entry.id, SpaceEntryRevision.is_conflict.is_(True))
            .order_by(SpaceEntryRevision.revision.asc())
        )
    )
    return SpaceEntryDetailOut(
        **summary.model_dump(),
        revision=int(rev.revision),
        epoch=int(rev.epoch),
        contentSha256=rev.content_sha256,
        contentText=content_text,
        contentBase64=content_base64,
        locked=locked,
        conflictRevisions=[int(r) for r in conflict_revs],
    )


def list_entries(
    db: Session,
    actor: SpaceActor,
    space_id: str,
    *,
    search: str | None = None,
    entry_type: str | None = None,
    include_deleted: bool = False,
    limit: int | None = None,
    offset: int = 0,
) -> list[SpaceEntrySummaryOut]:
    _require_enabled()
    space = _owned_space(db, actor.workspace_id, space_id)
    _enforce_token_space_access(db, actor, space, required_scope="read", action="entry.list")

    query = select(SpaceEntry).where(SpaceEntry.space_id == space.id)
    if not include_deleted:
        query = query.where(SpaceEntry.deleted_at.is_(None))
    if entry_type:
        query = query.where(SpaceEntry.entry_type == entry_type)
    if actor.token is not None and actor.token.entry_ids_json is not None:
        allowed_ids = list(actor.token.entry_ids_json)
        if not allowed_ids:
            return []
        query = query.where(SpaceEntry.id.in_(allowed_ids))

    entries = list(db.scalars(query.order_by(SpaceEntry.updated_at.desc())))
    if search and space.tier != "e2ee":
        needle = search.strip().lower()
        entries = [
            e
            for e in entries
            if needle in (e.title or "").lower()
            or needle in (e.file_name or "").lower()
            or any(needle in str(t).lower() for t in (e.tags_json or []))
        ]

    if offset or limit is not None:
        end = offset + limit if limit is not None else None
        entries = entries[offset:end]

    out: list[SpaceEntrySummaryOut] = []
    for entry in entries:
        rev = db.scalar(
            select(SpaceEntryRevision).where(
                SpaceEntryRevision.entry_id == entry.id,
                SpaceEntryRevision.revision == entry.current_revision,
            )
        )
        out.append(_entry_summary(db, space, entry, rev))
    return out


def create_entry(
    db: Session,
    actor: SpaceActor,
    space_id: str,
    payload: SpaceEntryCreateInput,
) -> SpaceEntryDetailOut:
    _require_enabled()
    space = _owned_space(db, actor.workspace_id, space_id)
    _enforce_token_space_access(db, actor, space, required_scope="write", action="entry.create")

    if payload.mutationId:
        existing_receipt = db.scalar(
            select(SpaceMutationReceipt).where(
                SpaceMutationReceipt.workspace_id == space.workspace_id,
                SpaceMutationReceipt.space_id == space.id,
                SpaceMutationReceipt.mutation_id == payload.mutationId,
            )
        )
        if existing_receipt is not None:
            return SpaceEntryDetailOut.model_validate(existing_receipt.response_json)

    now = utcnow()
    if payload.id is not None:
        try:
            entry_id = valid_uuid(payload.id)
        except ValueError as exc:
            raise HTTPException(422, "Invalid entry id") from exc
        if db.get(SpaceEntry, entry_id) is not None:
            raise HTTPException(409, "Entry id already exists")
    else:
        entry_id = str(uuid4())
    revision = 1

    if space.tier == "e2ee":
        # 严格禁止任何明文字段落入 e2ee 条目表
        if payload.title or payload.fileName or payload.tags or payload.contentText is not None or payload.contentBase64 is not None:
            raise HTTPException(422, "E2EE entries must not send plaintext title, tags or content")
        if payload.wrappedDek is None or not payload.encryptedManifestB64:
            raise HTTPException(422, "E2EE entry requires wrappedDek and encryptedManifestB64")
        target_epoch = payload.epoch if payload.epoch is not None else int(space.active_epoch)
        if target_epoch != int(space.active_epoch):
            raise HTTPException(409, f"Stale epoch: expected {space.active_epoch}")
        _validate_wrapped_dek_structure(payload.wrappedDek, expected_epoch=int(space.active_epoch))

        blob: SpaceBlob | None = None
        if payload.blobId:
            blob = _finalize_staged_blob(db, space, payload.blobId)
        ct_size = int(blob.total_size) if blob else 0

        entry = SpaceEntry(
            id=entry_id,
            workspace_id=space.workspace_id,
            space_id=space.id,
            entry_type=payload.entryType,
            current_revision=revision,
            active_epoch=int(space.active_epoch),
            title=None,
            file_name=None,
            mime="application/octet-stream",
            tags_json=[],
            size_bytes=ct_size,
            created_at=now,
            updated_at=now,
        )
        rev = SpaceEntryRevision(
            id=str(uuid4()),
            workspace_id=space.workspace_id,
            space_id=space.id,
            entry_id=entry_id,
            revision=revision,
            epoch=int(space.active_epoch),
            wrapped_dek_json=payload.wrappedDek,
            encrypted_manifest_b64=payload.encryptedManifestB64,
            plaintext_text=None,
            blob_id=blob.id if blob else None,
            chunk_count=int(blob.chunk_count) if blob else 0,
            chunk_size=int(blob.chunk_size) if blob else crypto.DEFAULT_CHUNK_SIZE,
            ciphertext_size=ct_size,
            plaintext_size=payload.plaintextSize,
            content_sha256=payload.contentSha256,
            created_by=f"{actor.kind}:{actor.actor_id}",
            created_at=now,
        )
        space.used_bytes = int(space.used_bytes) + ct_size
        detail_kwargs: dict[str, Any] = {"locked": True}

    elif space.tier == "protected":
        if actor.kind == "user":
            _require_protected_password(db, actor, space, payload.password, entry_id=entry_id, action="entry.create")
        if not payload.title:
            raise HTTPException(422, "Title is required for protected entry")
        is_file_entry = payload.entryType == "file"
        raw_bytes, _is_text = _extract_plaintext_bytes(
            payload.contentText,
            payload.contentBase64,
            allow_file_note=is_file_entry,
        )
        if len(raw_bytes) > _max_file_bytes():
            raise HTTPException(413, "Entry exceeds max allowed size")
        if int(space.used_bytes) + len(raw_bytes) > int(space.quota_bytes):
            raise HTTPException(413, "Space storage quota exceeded")

        file_note = _normalize_file_note(payload.contentText) if is_file_entry else None
        blob, wrapped_dek, encrypted_manifest_b64, ct_size, pt_sha = _store_protected_encrypted_payload(
            db,
            space=space,
            entry_id=entry_id,
            revision=revision,
            raw_bytes=raw_bytes,
            note_text=file_note,
        )
        entry = SpaceEntry(
            id=entry_id,
            workspace_id=space.workspace_id,
            space_id=space.id,
            entry_type=payload.entryType,
            current_revision=revision,
            active_epoch=int(space.active_epoch),
            title=payload.title.strip(),
            file_name=payload.fileName,
            mime=payload.mime,
            tags_json=list(payload.tags),
            size_bytes=len(raw_bytes),
            created_at=now,
            updated_at=now,
        )
        rev = SpaceEntryRevision(
            id=str(uuid4()),
            workspace_id=space.workspace_id,
            space_id=space.id,
            entry_id=entry_id,
            revision=revision,
            epoch=int(space.active_epoch),
            wrapped_dek_json=wrapped_dek,
            encrypted_manifest_b64=encrypted_manifest_b64,
            plaintext_text=None,  # protected 档数据库严禁落明文
            blob_id=blob.id,
            chunk_count=int(blob.chunk_count),
            chunk_size=int(blob.chunk_size),
            ciphertext_size=ct_size,
            plaintext_size=len(raw_bytes),
            content_sha256=pt_sha,
            created_by=f"{actor.kind}:{actor.actor_id}",
            created_at=now,
        )
        space.used_bytes = int(space.used_bytes) + ct_size
        detail_kwargs = {"locked": True}

    else:
        # standard 普通共享档
        if not payload.title:
            raise HTTPException(422, "Title is required for standard entry")
        blob = None
        is_file_entry = payload.entryType == "file"
        plaintext_text: str | None = _normalize_file_note(payload.contentText) if is_file_entry else None
        size_bytes = 0
        sha = payload.contentSha256
        if payload.blobId:
            blob = _finalize_staged_blob(db, space, payload.blobId)
            size_bytes = int(blob.total_size)
        else:
            raw_bytes, is_text = _extract_plaintext_bytes(
                payload.contentText,
                payload.contentBase64,
                allow_file_note=is_file_entry,
            )
            if len(raw_bytes) > _max_file_bytes():
                raise HTTPException(413, "Entry exceeds max allowed size")
            if int(space.used_bytes) + len(raw_bytes) > int(space.quota_bytes):
                raise HTTPException(413, "Space storage quota exceeded")
            size_bytes = len(raw_bytes)
            sha = crypto.sha256_hex(raw_bytes)
            if is_text and not is_file_entry:
                plaintext_text = payload.contentText or ""
            else:
                # 二进制文件分块存入 space_blobs（可选文件备注保留在 plaintext_text）
                chunk_size = crypto.DEFAULT_CHUNK_SIZE
                parts = [raw_bytes[i : i + chunk_size] for i in range(0, len(raw_bytes), chunk_size)] or [b""]
                bid = str(uuid4())
                cmeta: dict[str, Any] = {}
                for idx, part in enumerate(parts):
                    dg, sz = storage.write_chunk_bytes(
                        workspace_id=space.workspace_id,
                        space_id=space.id,
                        blob_id=bid,
                        chunk_index=idx,
                        data=part,
                    )
                    cmeta[str(idx)] = {"sha256": dg, "size": sz}
                blob = SpaceBlob(
                    id=bid,
                    workspace_id=space.workspace_id,
                    space_id=space.id,
                    chunk_size=chunk_size,
                    chunk_count=len(parts),
                    total_size=size_bytes,
                    chunks_json=cmeta,
                    committed_at=now,
                    created_at=now,
                )
                db.add(blob)
                db.flush()

        entry = SpaceEntry(
            id=entry_id,
            workspace_id=space.workspace_id,
            space_id=space.id,
            entry_type=payload.entryType,
            current_revision=revision,
            active_epoch=int(space.active_epoch),
            title=payload.title.strip(),
            file_name=payload.fileName,
            mime=payload.mime,
            tags_json=list(payload.tags),
            size_bytes=size_bytes,
            created_at=now,
            updated_at=now,
        )
        rev = SpaceEntryRevision(
            id=str(uuid4()),
            workspace_id=space.workspace_id,
            space_id=space.id,
            entry_id=entry_id,
            revision=revision,
            epoch=int(space.active_epoch),
            wrapped_dek_json=None,
            encrypted_manifest_b64=None,
            plaintext_text=plaintext_text,
            blob_id=blob.id if blob else None,
            chunk_count=int(blob.chunk_count) if blob else 0,
            chunk_size=int(blob.chunk_size) if blob else crypto.DEFAULT_CHUNK_SIZE,
            ciphertext_size=size_bytes,
            plaintext_size=size_bytes,
            content_sha256=sha,
            created_by=f"{actor.kind}:{actor.actor_id}",
            created_at=now,
        )
        space.used_bytes = int(space.used_bytes) + size_bytes
        detail_kwargs = {"content_text": plaintext_text, "locked": False}

    db.add(entry)
    db.flush()
    db.add(rev)
    space.updated_at = now
    _record_change(
        db,
        workspace_id=space.workspace_id,
        space_id=space.id,
        entry_id=entry.id,
        revision=revision,
        epoch=int(space.active_epoch),
        change_type="upsert",
    )
    _record_audit(
        db,
        workspace_id=space.workspace_id,
        space_id=space.id,
        actor_kind=actor.kind,
        actor_id=actor.actor_id,
        action="entry.create",
        entry_id=entry.id,
        detail=f"tier={space.tier},type={entry.entry_type}",
    )
    db.flush()
    response = _entry_detail(db, space, entry, rev, **detail_kwargs)

    if payload.mutationId:
        db.add(
            SpaceMutationReceipt(
                id=str(uuid4()),
                workspace_id=space.workspace_id,
                space_id=space.id,
                mutation_id=payload.mutationId,
                entry_id=entry.id,
                result_revision=revision,
                response_json=response.model_dump(mode="json"),
                created_at=now,
            )
        )
    db.commit()
    return response


def _owned_entry(db: Session, space: SharedSpace, entry_id: str) -> SpaceEntry:
    try:
        eid = valid_uuid(entry_id)
    except ValueError as exc:
        raise HTTPException(404, "Entry not found") from exc
    entry = db.scalar(
        select(SpaceEntry).where(
            SpaceEntry.id == eid,
            SpaceEntry.space_id == space.id,
            SpaceEntry.deleted_at.is_(None),
        )
    )
    if entry is None:
        raise HTTPException(404, "Entry not found")
    return entry


def _entry_revision(db: Session, entry: SpaceEntry, revision: int | None = None) -> SpaceEntryRevision:
    target = revision if revision is not None else int(entry.current_revision)
    rev = db.scalar(
        select(SpaceEntryRevision).where(
            SpaceEntryRevision.entry_id == entry.id,
            SpaceEntryRevision.revision == target,
        )
    )
    if rev is None:
        raise HTTPException(404, "Entry revision not found")
    return rev


def get_entry(
    db: Session,
    actor: SpaceActor,
    space_id: str,
    entry_id: str,
    *,
    revision: int | None = None,
) -> SpaceEntryDetailOut:
    _require_enabled()
    space = _owned_space(db, actor.workspace_id, space_id)
    entry = _owned_entry(db, space, entry_id)
    _enforce_token_space_access(db, actor, space, required_scope="read", entry_id=entry.id, action="entry.get")
    rev = _entry_revision(db, entry, revision)

    if space.tier == "standard":
        content_text = rev.plaintext_text
        content_b64: str | None = None
        if content_text is None and rev.blob_id and entry.entry_type != "file":
            raw = b"".join(
                storage.read_chunk_bytes(
                    workspace_id=space.workspace_id,
                    space_id=space.id,
                    blob_id=rev.blob_id,
                    chunk_index=i,
                )
                for i in range(int(rev.chunk_count))
            )
            content_b64 = base64.b64encode(raw).decode("ascii")
        if actor.kind == "standard_token":
            _record_audit(
                db,
                workspace_id=space.workspace_id,
                space_id=space.id,
                actor_kind=actor.kind,
                actor_id=actor.actor_id,
                action="entry.read",
                entry_id=entry.id,
            )
            db.commit()
        return _entry_detail(db, space, entry, rev, content_text=content_text, content_base64=content_b64, locked=False)

    if space.tier == "protected":
        # 仅细粒度 sv_live_ 可通过 GET 直读明文；UI(JWT) GET 仅返回锁定元数据，必须 POST /unlock 输密
        if actor.kind == "vault_token":
            raw, note_text = _decrypt_protected_revision_payload(space, entry, rev)
            _record_audit(
                db,
                workspace_id=space.workspace_id,
                space_id=space.id,
                actor_kind="vault_token",
                actor_id=actor.actor_id,
                action="entry.vault_read",
                entry_id=entry.id,
                detail=f"rev={rev.revision}",
            )
            db.commit()
            if entry.entry_type == "file":
                return _entry_detail(
                    db,
                    space,
                    entry,
                    rev,
                    content_text=note_text,
                    content_base64=base64.b64encode(raw).decode("ascii"),
                    locked=False,
                )
            return _entry_detail(
                db,
                space,
                entry,
                rev,
                content_text=raw.decode("utf-8", errors="replace"),
                locked=False,
            )
        return _entry_detail(db, space, entry, rev, locked=True)

    # e2ee：仅返回密文修订与加密 manifest，Core 永远不触碰明文
    return _entry_detail(db, space, entry, rev, locked=True)


def unlock_protected_entry(
    db: Session,
    actor: SpaceActor,
    space_id: str,
    entry_id: str,
    *,
    password: str,
    revision: int | None = None,
) -> SpaceEntryDetailOut:
    """UI 端按次提交空间密码解密读取 protected 档条目。"""
    _require_enabled()
    if actor.kind != "user":
        raise HTTPException(403, "Use Vault Token GET endpoint for API access")
    space = _owned_space(db, actor.workspace_id, space_id)
    if space.tier != "protected":
        raise HTTPException(400, "Unlock endpoint is only for protected spaces")
    entry = _owned_entry(db, space, entry_id)
    _require_protected_password(db, actor, space, password, entry_id=entry.id, action="entry.unlock")
    rev = _entry_revision(db, entry, revision)
    raw, note_text = _decrypt_protected_revision_payload(space, entry, rev)

    _record_audit(
        db,
        workspace_id=space.workspace_id,
        space_id=space.id,
        actor_kind="user",
        actor_id=actor.actor_id,
        action="entry.unlock",
        entry_id=entry.id,
        detail=f"rev={rev.revision}",
    )
    db.commit()

    if entry.entry_type == "file":
        return _entry_detail(
            db,
            space,
            entry,
            rev,
            content_text=note_text,
            content_base64=base64.b64encode(raw).decode("ascii"),
            locked=False,
        )
    return _entry_detail(
        db,
        space,
        entry,
        rev,
        content_text=raw.decode("utf-8", errors="replace"),
        locked=False,
    )


def download_entry_bytes(
    db: Session,
    actor: SpaceActor,
    space_id: str,
    entry_id: str,
    *,
    password: str | None = None,
    revision: int | None = None,
) -> tuple[bytes, str, str]:
    """下载 standard（随时）或 protected（凭密码或 sv_live_）的完整字节流，返回 (data, mime, file_name)。"""
    _require_enabled()
    space = _owned_space(db, actor.workspace_id, space_id, standard_only=actor.kind == "device")
    if space.tier == "e2ee":
        raise HTTPException(400, "E2EE entries must download ciphertext chunks and decrypt locally")
    entry = _owned_entry(db, space, entry_id)
    _enforce_token_space_access(db, actor, space, required_scope="read", entry_id=entry.id, action="entry.download")
    rev = _entry_revision(db, entry, revision)

    if space.tier == "protected":
        if actor.kind == "user":
            _require_protected_password(db, actor, space, password, entry_id=entry.id, action="entry.download")
        raw = _decrypt_protected_revision_bytes(space, entry, rev)
        _record_audit(
            db,
            workspace_id=space.workspace_id,
            space_id=space.id,
            actor_kind=actor.kind,
            actor_id=actor.actor_id,
            action="entry.download",
            entry_id=entry.id,
            detail=f"rev={rev.revision}",
        )
        db.commit()
    else:
        if rev.blob_id and (entry.entry_type == "file" or rev.plaintext_text is None):
            raw = b"".join(
                storage.read_chunk_bytes(
                    workspace_id=space.workspace_id,
                    space_id=space.id,
                    blob_id=rev.blob_id,
                    chunk_index=i,
                )
                for i in range(int(rev.chunk_count))
            )
        elif rev.plaintext_text is not None:
            raw = rev.plaintext_text.encode("utf-8")
        else:
            raw = b""
        if actor.kind == "standard_token":
            _record_audit(
                db,
                workspace_id=space.workspace_id,
                space_id=space.id,
                actor_kind=actor.kind,
                actor_id=actor.actor_id,
                action="entry.download",
                entry_id=entry.id,
            )
            db.commit()

    file_name = entry.file_name or f"{entry.title or entry.id}.txt"
    return raw, entry.mime or "application/octet-stream", file_name


def update_entry(
    db: Session,
    actor: SpaceActor,
    space_id: str,
    entry_id: str,
    payload: SpaceEntryUpdateInput,
    *,
    commit: bool = True,
    file_revision: int | None = None,
) -> SpaceEntryDetailOut:
    _require_enabled()
    space = _owned_space(db, actor.workspace_id, space_id)
    if space.tier == "standard":
        _lock_standard_entry(db, space, entry_id)
    entry = _owned_entry(db, space, entry_id)
    _enforce_token_space_access(db, actor, space, required_scope="write", entry_id=entry.id, action="entry.update")

    if payload.mutationId:
        existing_receipt = db.scalar(
            select(SpaceMutationReceipt).where(
                SpaceMutationReceipt.workspace_id == space.workspace_id,
                SpaceMutationReceipt.space_id == space.id,
                SpaceMutationReceipt.mutation_id == payload.mutationId,
            )
        )
        if existing_receipt is not None:
            return SpaceEntryDetailOut.model_validate(existing_receipt.response_json)

    is_conflict = False
    if payload.baseRevision != int(entry.current_revision):
        if not payload.allowConflictFork:
            raise HTTPException(409, f"Revision conflict: expected {entry.current_revision}")
        is_conflict = True

    now = utcnow()
    next_rev_num = int(
        db.scalar(select(func.max(SpaceEntryRevision.revision)).where(SpaceEntryRevision.entry_id == entry.id)) or entry.current_revision
    ) + 1

    if space.tier == "e2ee":
        if payload.title or payload.fileName or payload.tags or payload.contentText is not None or payload.contentBase64 is not None:
            raise HTTPException(422, "E2EE entries must not send plaintext fields")
        if payload.wrappedDek is None or not payload.encryptedManifestB64:
            raise HTTPException(422, "E2EE update requires wrappedDek and encryptedManifestB64")
        target_epoch = payload.epoch if payload.epoch is not None else int(space.active_epoch)
        if target_epoch != int(space.active_epoch):
            raise HTTPException(409, f"Stale epoch: expected {space.active_epoch}")
        _validate_wrapped_dek_structure(payload.wrappedDek, expected_epoch=int(space.active_epoch))

        blob = _finalize_staged_blob(db, space, payload.blobId) if payload.blobId else None
        ct_size = int(blob.total_size) if blob else 0
        rev = SpaceEntryRevision(
            id=str(uuid4()),
            workspace_id=space.workspace_id,
            space_id=space.id,
            entry_id=entry.id,
            revision=next_rev_num,
            epoch=int(space.active_epoch),
            wrapped_dek_json=payload.wrappedDek,
            encrypted_manifest_b64=payload.encryptedManifestB64,
            plaintext_text=None,
            blob_id=blob.id if blob else None,
            chunk_count=int(blob.chunk_count) if blob else 0,
            chunk_size=int(blob.chunk_size) if blob else crypto.DEFAULT_CHUNK_SIZE,
            ciphertext_size=ct_size,
            plaintext_size=payload.plaintextSize or 0,
            content_sha256=payload.contentSha256 or "",
            is_conflict=is_conflict,
            base_revision=payload.baseRevision,
            created_by=f"{actor.kind}:{actor.actor_id}",
            created_at=now,
        )
        space.used_bytes = int(space.used_bytes) + ct_size
        if not is_conflict:
            entry.current_revision = next_rev_num
            entry.active_epoch = int(space.active_epoch)
            entry.size_bytes = ct_size
        detail_kwargs: dict[str, Any] = {"locked": True}

    elif space.tier == "protected":
        if actor.kind == "user":
            _require_protected_password(db, actor, space, payload.password, entry_id=entry.id, action="entry.update")
        is_file_entry = entry.entry_type == "file"
        file_note = _normalize_file_note(payload.contentText) if is_file_entry else None
        if is_file_entry and payload.contentBase64 is None:
            previous = _entry_revision(db, entry, payload.baseRevision)
            raw_bytes, previous_note = _decrypt_protected_revision_payload(space, entry, previous)
            if "contentText" not in payload.model_fields_set:
                file_note = previous_note
        else:
            raw_bytes, _is_text = _extract_plaintext_bytes(
                payload.contentText,
                payload.contentBase64,
                allow_file_note=is_file_entry,
            )
        if len(raw_bytes) > _max_file_bytes():
            raise HTTPException(413, "Entry exceeds max allowed size")
        if int(space.used_bytes) + len(raw_bytes) > int(space.quota_bytes):
            raise HTTPException(413, "Space storage quota exceeded")
        blob, wrapped_dek, encrypted_manifest_b64, ct_size, pt_sha = _store_protected_encrypted_payload(
            db,
            space=space,
            entry_id=entry.id,
            revision=next_rev_num,
            raw_bytes=raw_bytes,
            note_text=file_note,
        )
        rev = SpaceEntryRevision(
            id=str(uuid4()),
            workspace_id=space.workspace_id,
            space_id=space.id,
            entry_id=entry.id,
            revision=next_rev_num,
            epoch=int(space.active_epoch),
            wrapped_dek_json=wrapped_dek,
            encrypted_manifest_b64=encrypted_manifest_b64,
            plaintext_text=None,
            blob_id=blob.id,
            chunk_count=int(blob.chunk_count),
            chunk_size=int(blob.chunk_size),
            ciphertext_size=ct_size,
            plaintext_size=len(raw_bytes),
            content_sha256=pt_sha,
            is_conflict=is_conflict,
            base_revision=payload.baseRevision,
            created_by=f"{actor.kind}:{actor.actor_id}",
            created_at=now,
        )
        space.used_bytes = int(space.used_bytes) + ct_size
        if not is_conflict:
            entry.current_revision = next_rev_num
            if payload.title is not None:
                entry.title = payload.title.strip()
            if payload.fileName is not None:
                entry.file_name = payload.fileName
            if payload.mime is not None:
                entry.mime = payload.mime
            if payload.tags is not None:
                entry.tags_json = list(payload.tags)
            entry.size_bytes = len(raw_bytes)
        detail_kwargs = {"locked": True}

    else:
        is_file_entry = entry.entry_type == "file"
        blob = _finalize_staged_blob(db, space, payload.blobId) if payload.blobId else None
        if is_file_entry and blob is None and payload.contentBase64 is None:
            # 仅更新普通文件的标题、标签或备注，复用原有文件二进制分块
            prev_rev = _entry_revision(db, entry, file_revision if file_revision is not None else payload.baseRevision)
            plaintext_text = prev_rev.plaintext_text
            if "contentText" in payload.model_fields_set:
                plaintext_text = _normalize_file_note(payload.contentText)
            reused_blob_id = prev_rev.blob_id
            reused_chunk_count = int(prev_rev.chunk_count)
            reused_chunk_size = int(prev_rev.chunk_size)
            size_bytes = int(prev_rev.plaintext_size)
            sha = prev_rev.content_sha256
            added_bytes = 0
        else:
            raw_bytes, is_text = _extract_plaintext_bytes(
                payload.contentText,
                payload.contentBase64,
                allow_file_note=is_file_entry,
            )
            plaintext_text = (
                _normalize_file_note(payload.contentText)
                if is_file_entry
                else (payload.contentText if (blob is None and is_text) else None)
            )
            size_bytes = int(blob.total_size) if blob else len(raw_bytes)
            sha = payload.contentSha256 or crypto.sha256_hex(raw_bytes)
            if blob is None and (is_file_entry or plaintext_text is None) and raw_bytes:
                chunk_size = crypto.DEFAULT_CHUNK_SIZE
                parts = [raw_bytes[i : i + chunk_size] for i in range(0, len(raw_bytes), chunk_size)]
                bid = str(uuid4())
                cmeta: dict[str, Any] = {}
                for idx, part in enumerate(parts):
                    dg, sz = storage.write_chunk_bytes(
                        workspace_id=space.workspace_id,
                        space_id=space.id,
                        blob_id=bid,
                        chunk_index=idx,
                        data=part,
                    )
                    cmeta[str(idx)] = {"sha256": dg, "size": sz}
                blob = SpaceBlob(
                    id=bid,
                    workspace_id=space.workspace_id,
                    space_id=space.id,
                    chunk_size=chunk_size,
                    chunk_count=len(parts),
                    total_size=size_bytes,
                    chunks_json=cmeta,
                    committed_at=now,
                    created_at=now,
                )
                db.add(blob)
                db.flush()
            reused_blob_id = blob.id if blob else None
            reused_chunk_count = int(blob.chunk_count) if blob else 0
            reused_chunk_size = int(blob.chunk_size) if blob else crypto.DEFAULT_CHUNK_SIZE
            added_bytes = size_bytes

        rev = SpaceEntryRevision(
            id=str(uuid4()),
            workspace_id=space.workspace_id,
            space_id=space.id,
            entry_id=entry.id,
            revision=next_rev_num,
            epoch=int(space.active_epoch),
            wrapped_dek_json=None,
            encrypted_manifest_b64=None,
            plaintext_text=plaintext_text,
            blob_id=reused_blob_id,
            chunk_count=reused_chunk_count,
            chunk_size=reused_chunk_size,
            ciphertext_size=size_bytes,
            plaintext_size=size_bytes,
            content_sha256=sha,
            is_conflict=is_conflict,
            base_revision=payload.baseRevision,
            created_by=f"{actor.kind}:{actor.actor_id}",
            created_at=now,
        )
        space.used_bytes = int(space.used_bytes) + added_bytes
        if not is_conflict:
            entry.current_revision = next_rev_num
            if payload.title is not None:
                entry.title = payload.title.strip()
            if payload.fileName is not None:
                entry.file_name = payload.fileName
            if payload.mime is not None:
                entry.mime = payload.mime
            if payload.tags is not None:
                entry.tags_json = list(payload.tags)
            entry.size_bytes = size_bytes
        detail_kwargs = {"content_text": plaintext_text, "locked": False}

    entry.updated_at = now
    space.updated_at = now
    db.add(rev)
    _record_change(
        db,
        workspace_id=space.workspace_id,
        space_id=space.id,
        entry_id=entry.id,
        revision=next_rev_num,
        epoch=int(space.active_epoch),
        change_type="upsert",
    )
    _record_audit(
        db,
        workspace_id=space.workspace_id,
        space_id=space.id,
        actor_kind=actor.kind,
        actor_id=actor.actor_id,
        action="entry.update",
        entry_id=entry.id,
        detail=f"rev={next_rev_num},conflict={is_conflict}",
    )
    db.flush()
    response = _entry_detail(db, space, entry, rev, **detail_kwargs)
    if payload.mutationId:
        db.add(
            SpaceMutationReceipt(
                id=str(uuid4()),
                workspace_id=space.workspace_id,
                space_id=space.id,
                mutation_id=payload.mutationId,
                entry_id=entry.id,
                result_revision=next_rev_num,
                response_json=response.model_dump(mode="json"),
                created_at=now,
            )
        )
    if commit:
        db.commit()
    return response


def delete_entry(db: Session, actor: SpaceActor, space_id: str, entry_id: str, *, commit: bool = True) -> None:
    _require_enabled()
    space = _owned_space(db, actor.workspace_id, space_id)
    if space.tier == "standard":
        _lock_standard_entry(db, space, entry_id)
    entry = _owned_entry(db, space, entry_id)
    _enforce_token_space_access(db, actor, space, required_scope="write", entry_id=entry.id, action="entry.delete")

    now = utcnow()
    entry.deleted_at = now
    entry.updated_at = now
    space.updated_at = now
    _record_change(
        db,
        workspace_id=space.workspace_id,
        space_id=space.id,
        entry_id=entry.id,
        revision=int(entry.current_revision),
        epoch=int(space.active_epoch),
        change_type="delete",
    )
    _record_audit(
        db,
        workspace_id=space.workspace_id,
        space_id=space.id,
        actor_kind=actor.kind,
        actor_id=actor.actor_id,
        action="entry.delete",
        entry_id=entry.id,
    )
    if commit:
        db.commit()


def _lock_standard_entry(db: Session, space: SharedSpace, entry_id: str) -> SpaceEntry:
    try:
        eid = valid_uuid(entry_id)
    except ValueError as exc:
        raise HTTPException(404, "Entry not found") from exc
    scope = (SpaceEntry.id == eid, SpaceEntry.space_id == space.id, SpaceEntry.workspace_id == space.workspace_id)
    if db.get_bind().dialect.name == "sqlite":
        # SQLite has no row-level SELECT FOR UPDATE. Reserve the write lock before comparing.
        db.execute(update(SpaceEntry).where(*scope).values(updated_at=SpaceEntry.updated_at))
    entry = db.scalar(select(SpaceEntry).where(*scope).with_for_update().execution_options(populate_existing=True))
    if entry is None:
        raise HTTPException(404, "Entry not found")
    return entry


def _standard_sync_space(db: Session, actor: SpaceActor, space_id: str) -> SharedSpace:
    _require_enabled()
    space = _owned_space(db, actor.workspace_id, space_id)
    if space.tier != "standard" or actor.kind != "user":
        raise HTTPException(403, "Standard-space sync requires a workspace user")
    return space


def standard_space_snapshot(db: Session, actor: SpaceActor, space_id: str) -> SpaceStandardSnapshot:
    space = _standard_sync_space(db, actor, space_id)
    # Anchor first. Any writes after the anchor will be picked up by the next pull.
    cursor = db.scalar(select(func.max(SpaceChange.seq)).where(SpaceChange.space_id == space.id)) or 0
    return SpaceStandardSnapshot(cursor=cursor, entries=list_entries(db, actor, space.id))


def sync_standard_entry(
    db: Session, actor: SpaceActor, space_id: str, entry_id: str, payload: SpaceStandardMutation,
) -> SpaceStandardMutationOut:
    space = _standard_sync_space(db, actor, space_id)
    entry = _lock_standard_entry(db, space, entry_id)
    mid = str(payload.mutationId)
    receipt = db.scalar(select(SpaceMutationReceipt).where(
        SpaceMutationReceipt.space_id == space.id, SpaceMutationReceipt.mutation_id == mid,
    ))
    if receipt is not None:
        saved = receipt.response_json
        if saved.get("entryId") != entry.id or "result" not in saved:
            raise HTTPException(409, "Mutation ID is already in use")
        return SpaceStandardMutationOut.model_validate(saved["result"])
    if (payload.operation == "edit") != (payload.edit is not None):
        raise HTTPException(422, "Edit fields are required only for edits")
    fields = payload.edit.model_dump() if payload.edit else {}
    if payload.edit and not payload.edit.title.strip():
        raise HTTPException(422, "Title is required")
    if payload.edit and len(payload.edit.contentText.encode("utf-8")) > _max_file_bytes():
        raise HTTPException(413, "Entry exceeds max allowed size")
    _entry_revision(db, entry, payload.baseRevision)
    if payload.baseRevision != entry.current_revision or entry.deleted_at is not None:
        existing = db.scalar(select(SpaceSyncCandidate).where(
            SpaceSyncCandidate.space_id == space.id, SpaceSyncCandidate.mutation_id == mid,
        ))
        if existing is not None:
            if existing.entry_id != entry.id:
                raise HTTPException(409, "Mutation ID is already in use")
            return SpaceStandardMutationOut(
                status="resolved" if existing.resolved_at else "conflict",
                revision=existing.result_revision or entry.current_revision, candidateId=existing.id,
            )
        candidate = SpaceSyncCandidate(
            id=str(uuid4()), space_id=space.id, entry_id=entry.id, mutation_id=mid,
            base_revision=payload.baseRevision, device_label=payload.deviceLabel,
            operation=payload.operation, edited_fields=fields,
        )
        db.add(candidate)
        _record_change(db, workspace_id=space.workspace_id, space_id=space.id, entry_id=entry.id,
                       revision=entry.current_revision, epoch=space.active_epoch,
                       change_type="upsert" if entry.deleted_at is None else "delete")
        result = SpaceStandardMutationOut(status="conflict", revision=entry.current_revision, candidateId=candidate.id)
        db.commit()
        return result

    if payload.operation == "delete":
        delete_entry(db, actor, space.id, entry.id, commit=False)
        revision = entry.current_revision
    else:
        updated = update_entry(
            db, actor, space.id, entry.id,
            SpaceEntryUpdateInput(baseRevision=entry.current_revision, **fields), commit=False,
        )
        revision = updated.currentRevision
    result = SpaceStandardMutationOut(status="applied", revision=revision)
    db.add(SpaceMutationReceipt(
        id=str(uuid4()), workspace_id=space.workspace_id, space_id=space.id, mutation_id=mid, entry_id=entry.id,
        result_revision=revision, response_json={"entryId": entry.id, "result": result.model_dump()},
    ))
    db.commit()
    return result


def list_standard_conflicts(db: Session, actor: SpaceActor, space_id: str) -> list[SpaceStandardCandidateOut]:
    space = _standard_sync_space(db, actor, space_id)
    rows = db.execute(
        select(SpaceSyncCandidate, SpaceEntry)
        .join(SpaceEntry, SpaceEntry.id == SpaceSyncCandidate.entry_id)
        .where(SpaceSyncCandidate.space_id == space.id, SpaceSyncCandidate.resolved_at.is_(None))
        .order_by(SpaceSyncCandidate.created_at, SpaceSyncCandidate.id)
    )
    items = []
    for candidate, entry in rows:
        current = _entry_revision(db, entry)
        items.append(SpaceStandardCandidateOut(
            id=candidate.id, entryId=entry.id, deviceLabel=candidate.device_label,
            operation=candidate.operation, edit=candidate.edited_fields or None,
            baseRevision=candidate.base_revision, createdAt=iso_utc(candidate.created_at),
            current=_entry_detail(db, space, entry, current, content_text=current.plaintext_text),
        ))
    return items


def resolve_standard_conflict(
    db: Session, actor: SpaceActor, space_id: str, candidate_id: str, payload: SpaceStandardResolution,
) -> SpaceStandardMutationOut:
    space = _standard_sync_space(db, actor, space_id)
    candidate = db.get(SpaceSyncCandidate, candidate_id)
    if candidate is None or candidate.space_id != space.id:
        raise HTTPException(404, "Conflict not found")
    entry = _lock_standard_entry(db, space, candidate.entry_id)
    db.refresh(candidate)
    if candidate.resolved_at is not None:
        if candidate.resolution != payload.strategy:
            raise HTTPException(409, "Conflict was already resolved")
        return SpaceStandardMutationOut(status="resolved", revision=candidate.result_revision, candidateId=candidate.id)
    deleted = entry.deleted_at is not None
    if entry.current_revision != payload.expectedRevision or deleted != payload.expectedDeleted:
        raise HTTPException(409, "Core version changed. Refresh and review the conflict again.")

    revision = entry.current_revision
    if payload.strategy == "candidate" and candidate.operation == "edit":
        if deleted:
            entry.deleted_at = None
            db.flush()
        updated = update_entry(
            db, actor, space.id, entry.id,
            SpaceEntryUpdateInput(baseRevision=revision, **candidate.edited_fields),
            commit=False, file_revision=candidate.base_revision,
        )
        revision = updated.currentRevision
    elif payload.strategy == "candidate" and not deleted:
        delete_entry(db, actor, space.id, entry.id, commit=False)
    candidate.resolved_at = utcnow()
    candidate.resolution = payload.strategy
    candidate.result_revision = revision
    if payload.strategy == "core":
        _record_change(db, workspace_id=space.workspace_id, space_id=space.id, entry_id=entry.id,
                       revision=revision, epoch=space.active_epoch, change_type="delete" if deleted else "upsert")
    _record_audit(
        db, workspace_id=space.workspace_id, space_id=space.id, actor_kind=actor.kind,
        actor_id=actor.actor_id, action="entry.sync.resolve", entry_id=entry.id, detail=payload.strategy,
    )
    db.commit()
    return SpaceStandardMutationOut(status="resolved", revision=revision, candidateId=candidate_id)


# ---------------- 隔离增量游标拉取 ----------------


def list_changes(
    db: Session,
    actor: SpaceActor,
    space_id: str,
    *,
    since_seq: int = 0,
    limit: int = 100,
) -> SpaceChangesPageOut:
    _require_enabled()
    space = _owned_space(db, actor.workspace_id, space_id)
    _enforce_token_space_access(db, actor, space, required_scope="read", action="space.changes")
    if space.tier == "standard" and since_seq:
        latest = db.scalar(select(func.max(SpaceChange.seq)).where(SpaceChange.space_id == space.id)) or 0
        if since_seq > latest:
            raise HTTPException(409, "space_resync_required")
    capped = max(1, min(limit, 500))
    rows = list(
        db.scalars(
            select(SpaceChange)
            .where(SpaceChange.space_id == space.id, SpaceChange.seq > since_seq)
            .order_by(SpaceChange.seq.asc())
            .limit(capped + 1)
        )
    )
    has_more = len(rows) > capped
    page = rows[:capped]
    next_seq = int(page[-1].seq) if page else since_seq
    return SpaceChangesPageOut(
        spaceId=space.id,
        sinceSeq=since_seq,
        nextSeq=next_seq,
        hasMore=has_more,
        activeEpoch=int(space.active_epoch),
        envelopeVersion=int(space.envelope_version),
        changes=[
            SpaceChangeOut(
                seq=int(row.seq),
                spaceId=row.space_id,
                entryId=row.entry_id,
                revision=int(row.revision),
                epoch=int(row.epoch),
                changeType=row.change_type,
                createdAt=iso_utc(row.created_at),
            )
            for row in page
        ],
    )


# ---------------- 专用 Token（ss_live_ / sv_live_）与审计 ----------------


def _token_to_out(item: SpaceToken) -> SpaceTokenOut:
    return SpaceTokenOut(
        id=item.id,
        spaceId=item.space_id,
        tokenKind=item.token_kind,  # type: ignore[arg-type]
        name=item.name,
        tokenLast4=item.token_last4,
        scopes=list(item.scopes_json or []),
        entryIds=list(item.entry_ids_json) if item.entry_ids_json is not None else None,
        expiresAt=iso_utc(item.expires_at) if item.expires_at else None,
        lastUsedAt=iso_utc(item.last_used_at) if item.last_used_at else None,
        revokedAt=iso_utc(item.revoked_at) if item.revoked_at else None,
        createdAt=iso_utc(item.created_at),
    )


def list_tokens(db: Session, actor: SpaceActor, space_id: str) -> list[SpaceTokenOut]:
    _require_enabled()
    if actor.kind != "user":
        raise HTTPException(403, "Only workspace user can list space tokens")
    space = _owned_space(db, actor.workspace_id, space_id)
    rows = list(
        db.scalars(
            select(SpaceToken).where(SpaceToken.space_id == space.id).order_by(SpaceToken.created_at.desc())
        )
    )
    return [_token_to_out(r) for r in rows]


def create_token(
    db: Session,
    actor: SpaceActor,
    space_id: str,
    payload: SpaceTokenCreateInput,
) -> SpaceTokenCreatedOut:
    _require_enabled()
    if actor.kind != "user":
        raise HTTPException(403, "Only workspace user can create space tokens")
    space = _owned_space(db, actor.workspace_id, space_id)
    if space.tier == "e2ee":
        raise HTTPException(400, "E2EE spaces do not support direct API tokens")

    if space.tier == "protected":
        _require_protected_password(db, actor, space, payload.password, entry_id=None, action="token.create")
        token_kind = "vault"
        prefix = VAULT_TOKEN_PREFIX
    else:
        token_kind = "standard"
        prefix = STANDARD_TOKEN_PREFIX

    normalized_entries: list[str] | None = None
    if payload.entryIds is not None:
        normalized_entries = [valid_uuid(eid) for eid in payload.entryIds]

    raw_token = f"{prefix}{secrets.token_urlsafe(32)}"
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    now = utcnow()
    expires_at = now + timedelta(days=payload.expiresInDays) if payload.expiresInDays else None

    record = SpaceToken(
        id=str(uuid4()),
        user_id=actor.user_id,
        workspace_id=space.workspace_id,
        space_id=space.id,
        token_kind=token_kind,
        name=payload.name.strip(),
        token_hash=token_hash,
        token_last4=raw_token[-4:],
        scopes_json=sorted(set(payload.scopes)),
        entry_ids_json=normalized_entries,
        expires_at=expires_at,
        created_at=now,
    )
    db.add(record)
    _record_audit(
        db,
        workspace_id=space.workspace_id,
        space_id=space.id,
        actor_kind="user",
        actor_id=actor.actor_id,
        action="token.create",
        detail=f"kind={token_kind},scopes={','.join(record.scopes_json)},last4={record.token_last4}",
    )
    db.commit()
    db.refresh(record)
    return SpaceTokenCreatedOut(**_token_to_out(record).model_dump(), token=raw_token)


def revoke_token(db: Session, actor: SpaceActor, space_id: str, token_id: str) -> None:
    _require_enabled()
    if actor.kind != "user":
        raise HTTPException(403, "Only workspace user can revoke space tokens")
    space = _owned_space(db, actor.workspace_id, space_id)
    try:
        tid = valid_uuid(token_id)
    except ValueError as exc:
        raise HTTPException(404, "Token not found") from exc
    token = db.scalar(select(SpaceToken).where(SpaceToken.id == tid, SpaceToken.space_id == space.id))
    if token is None:
        raise HTTPException(404, "Token not found")
    token.revoked_at = utcnow()
    _record_audit(
        db,
        workspace_id=space.workspace_id,
        space_id=space.id,
        actor_kind="user",
        actor_id=actor.actor_id,
        action="token.revoke",
        detail=f"kind={token.token_kind},last4={token.token_last4}",
    )
    db.commit()


def list_audit_logs(db: Session, actor: SpaceActor, space_id: str, limit: int = 100) -> list[SpaceAuditLogOut]:
    _require_enabled()
    if actor.kind != "user":
        raise HTTPException(403, "Only workspace user can view audit logs")
    space = _owned_space(db, actor.workspace_id, space_id)
    capped = max(1, min(limit, 500))
    rows = list(
        db.scalars(
            select(SpaceAccessAuditLog)
            .where(SpaceAccessAuditLog.space_id == space.id)
            .order_by(SpaceAccessAuditLog.created_at.desc())
            .limit(capped)
        )
    )
    return [
        SpaceAuditLogOut(
            id=row.id,
            spaceId=row.space_id,
            entryId=row.entry_id,
            actorKind=row.actor_kind,
            actorId=row.actor_id,
            action=row.action,
            outcome=row.outcome,
            detail=row.detail,
            createdAt=iso_utc(row.created_at),
        )
        for row in rows
    ]


# ---------------- Agent Data Actions 白名单（仅 standard 档只读） ----------------


def _owner_workspace_id(db: Session, user: Any) -> tuple[str, str]:
    ws_id = getattr(user, "workspace_id", None)
    uid = getattr(user, "user_id", getattr(user, "id", ""))
    if ws_id:
        return str(ws_id), str(uid)
    ws = get_personal_workspace(db, user)
    return ws.id, str(uid)


def agent_list_standard_spaces(*, db: Session, user: Any) -> list[dict[str, Any]]:
    """供 Agent Data Actions（显式开启 space:read 白名单时）仅列出 standard 空间。"""
    _require_enabled()
    workspace_id, _uid = _owner_workspace_id(db, user)
    rows = list(
        db.scalars(
            select(SharedSpace)
            .where(
                SharedSpace.workspace_id == workspace_id,
                SharedSpace.tier == "standard",
                SharedSpace.archived_at.is_(None),
            )
            .order_by(SharedSpace.created_at.desc())
        )
    )
    return [
        {
            "id": sp.id,
            "name": sp.name,
            "description": sp.description,
            "tier": "standard",
            "updatedAt": iso_utc(sp.updated_at),
        }
        for sp in rows
    ]


def agent_list_standard_entries(*, db: Session, user: Any, spaceId: str) -> list[dict[str, Any]]:
    """供 Agent Data Actions 仅列出指定 standard 空间条目；对 protected/e2ee 严格拒绝 403。"""
    _require_enabled()
    workspace_id, _uid = _owner_workspace_id(db, user)
    space = _owned_space(db, workspace_id, spaceId)
    if space.tier != "standard":
        raise HTTPException(403, {"code": "permission_denied"})
    entries = list(
        db.scalars(
            select(SpaceEntry)
            .where(SpaceEntry.space_id == space.id, SpaceEntry.deleted_at.is_(None))
            .order_by(SpaceEntry.updated_at.desc())
        )
    )
    return [
        {
            "id": e.id,
            "spaceId": e.space_id,
            "entryType": e.entry_type,
            "title": e.title,
            "fileName": e.file_name,
            "mime": e.mime,
            "tags": list(e.tags_json or []),
            "sizeBytes": int(e.size_bytes),
            "updatedAt": iso_utc(e.updated_at),
        }
        for e in entries
    ]


def agent_get_standard_entry(*, db: Session, user: Any, spaceId: str, id: str) -> dict[str, Any]:
    """供 Agent Data Actions 仅读取指定 standard 空间条目正文；对 protected/e2ee 严格拒绝 403。"""
    _require_enabled()
    workspace_id, uid = _owner_workspace_id(db, user)
    space = _owned_space(db, workspace_id, spaceId)
    if space.tier != "standard":
        raise HTTPException(403, {"code": "permission_denied"})
    entry = _owned_entry(db, space, id)
    rev = _entry_revision(db, entry)
    _record_audit(
        db,
        workspace_id=workspace_id,
        space_id=space.id,
        actor_kind="agent",
        actor_id=uid,
        action="agent.entry.get",
        entry_id=entry.id,
    )
    return {
        "id": entry.id,
        "spaceId": entry.space_id,
        "entryType": entry.entry_type,
        "title": entry.title,
        "fileName": entry.file_name,
        "mime": entry.mime,
        "tags": list(entry.tags_json or []),
        "revision": int(rev.revision),
        "contentText": rev.plaintext_text,
        "sizeBytes": int(entry.size_bytes),
        "updatedAt": iso_utc(entry.updated_at),
    }
