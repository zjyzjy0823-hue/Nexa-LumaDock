"""跨客户端与 Edge Blob Relay 共用的加密分块文件仓储、校验与断点下载核。"""

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
import hashlib
import os
from pathlib import Path
import re
import shutil
from uuid import UUID, uuid4

from fastapi import HTTPException
from fastapi.responses import Response, StreamingResponse
import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..credential_store import stage_file
from ..models import EncryptedBlob, utcnow
from ..security import JWT_ALGORITHM, JWT_SECRET
from ..utils.time import iso_utc
from .schemas import (
    BlobCommitInput,
    BlobInitInput,
    BlobOut,
    MAX_CHUNK_BYTES,
    ResolvedEndpoint,
    TransferEndpoint,
    validate_endpoint_url,
)

_RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")


def fleet_blobs_root() -> Path:
    """定位密文分块存储目录（优先使用 STUDIOLO_DATA_DIR）。"""
    data_dir = os.environ.get("STUDIOLO_DATA_DIR")
    if data_dir:
        return Path(data_dir).resolve() / "fleet-blobs"
    return Path("./studiolo-blobs").resolve()


def _validate_blob_id(blob_id: str) -> str:
    try:
        return str(UUID(blob_id))
    except ValueError as exc:
        raise HTTPException(422, "Invalid artifact ID") from exc


def blob_directory(workspace_id: str, blob_id: str) -> Path:
    ws_id = str(UUID(workspace_id))
    b_id = _validate_blob_id(blob_id)
    return fleet_blobs_root() / ws_id / b_id


def chunk_path(workspace_id: str, blob_id: str, index: int) -> Path:
    if index < 0:
        raise HTTPException(422, "Invalid chunk index")
    return blob_directory(workspace_id, blob_id) / f"{index:06d}.enc"


def blob_to_out(item: EncryptedBlob) -> BlobOut:
    return BlobOut(
        id=item.id,
        workspaceId=item.workspace_id,
        uploaderKind=item.uploader_kind,
        uploaderId=item.uploader_id,
        purpose=item.purpose,  # type: ignore[arg-type]
        digest=item.digest,
        ciphertextSize=int(item.ciphertext_size),
        chunkSize=int(item.chunk_size),
        chunkCount=int(item.chunk_count),
        storageRole=item.storage_role,
        storageLocation=item.storage_location,
        manifest=item.manifest_json,
        committedAt=iso_utc(item.committed_at) if item.committed_at else None,
        expiresAt=iso_utc(item.expires_at) if item.expires_at else None,
        createdAt=iso_utc(item.created_at),
    )


def init_blob(
    db: Session,
    *,
    user_id: int,
    workspace_id: str,
    uploader_kind: str,
    uploader_id: str,
    payload: BlobInitInput,
) -> EncryptedBlob:
    max_capacity = payload.chunkSize * payload.chunkCount
    min_capacity = payload.chunkSize * (payload.chunkCount - 1)
    if payload.ciphertextSize > max_capacity or payload.ciphertextSize <= min_capacity:
        raise HTTPException(422, "ciphertextSize does not match chunkSize and chunkCount")

    now = utcnow()
    expires_at = (
        None if payload.purpose == "shared_space" or payload.ttlSeconds is None
        else now + timedelta(seconds=payload.ttlSeconds)
    )
    record = EncryptedBlob(
        id=str(uuid4()),
        user_id=user_id,
        workspace_id=workspace_id,
        uploader_kind=uploader_kind,
        uploader_id=uploader_id,
        purpose=payload.purpose,
        digest=payload.digest,
        ciphertext_size=payload.ciphertextSize,
        chunk_size=payload.chunkSize,
        chunk_count=payload.chunkCount,
        storage_role=payload.storageRole,
        storage_location=payload.storageLocation,
        manifest_json=payload.manifest,
        expires_at=expires_at,
        created_at=now,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def get_workspace_blob(db: Session, workspace_id: str, blob_id: str) -> EncryptedBlob:
    valid_id = _validate_blob_id(blob_id)
    blob = db.scalar(
        select(EncryptedBlob).where(EncryptedBlob.id == valid_id, EncryptedBlob.workspace_id == workspace_id)
    )
    if blob is None:
        raise HTTPException(404, "Artifact not found")
    if blob.expires_at is not None:
        exp = blob.expires_at if blob.expires_at.tzinfo else blob.expires_at.replace(tzinfo=timezone.utc)
        if exp <= utcnow():
            raise HTTPException(410, "Artifact expired")
    return blob


def store_chunk(
    blob: EncryptedBlob,
    index: int,
    data: bytes,
    *,
    expected_sha256: str | None = None,
) -> int:
    """校验大小与分块 SHA-256 后，以原子临时文件写入密文分块。"""
    if index < 0 or index >= blob.chunk_count:
        raise HTTPException(422, f"Chunk index out of range (0..{blob.chunk_count - 1})")
    if not data or len(data) > min(blob.chunk_size, MAX_CHUNK_BYTES):
        raise HTTPException(422, "Chunk byte length exceeds declared chunkSize")
    if expected_sha256 is not None:
        actual = hashlib.sha256(data).hexdigest()
        if actual != expected_sha256.strip().lower():
            raise HTTPException(422, "Chunk SHA-256 digest mismatch")
    target = chunk_path(blob.workspace_id, blob.id, index)
    stage_file(target, data).commit()
    return len(data)


def commit_blob(db: Session, blob: EncryptedBlob, payload: BlobCommitInput | None = None) -> EncryptedBlob:
    """校验 Core 本地分块完整性，或登记由 Edge Relay / 直传节点提交的密文清单。"""
    role = (payload.storageRole if payload and payload.storageRole else blob.storage_role)
    if role == "core":
        hasher = hashlib.sha256()
        total = 0
        for idx in range(blob.chunk_count):
            p = chunk_path(blob.workspace_id, blob.id, idx)
            if not p.is_file():
                raise HTTPException(422, f"Missing chunk {idx}")
            raw = p.read_bytes()
            total += len(raw)
            hasher.update(raw)
        if total != blob.ciphertext_size:
            raise HTTPException(422, f"Committed size mismatch ({total} != {blob.ciphertext_size})")
        if hasher.hexdigest() != blob.digest:
            raise HTTPException(422, "Ciphertext SHA-256 digest mismatch")

    blob.storage_role = role
    if payload and payload.storageLocation is not None:
        blob.storage_location = payload.storageLocation
    if payload and payload.manifest is not None:
        blob.manifest_json = payload.manifest
    blob.committed_at = utcnow()
    db.commit()
    db.refresh(blob)
    return blob


def delete_blob(db: Session, blob: EncryptedBlob) -> None:
    folder = blob_directory(blob.workspace_id, blob.id)
    if folder.exists():
        shutil.rmtree(folder, ignore_errors=True)
    db.delete(blob)
    db.commit()


def _parse_range(range_header: str | None, total: int) -> tuple[int, int] | None:
    if not range_header:
        return None
    match = _RANGE_RE.match(range_header.strip())
    if not match:
        raise HTTPException(416, "Invalid Range header")
    start_s, end_s = match.groups()
    if not start_s and not end_s:
        raise HTTPException(416, "Invalid Range header")
    if start_s:
        start = int(start_s)
        end = int(end_s) if end_s else total - 1
    else:
        suffix = int(end_s)
        if suffix <= 0:
            raise HTTPException(416, "Invalid suffix length")
        start = max(0, total - suffix)
        end = total - 1
    if start >= total or end < start:
        raise HTTPException(416, "Range Not Satisfiable")
    return start, min(end, total - 1)


def stream_chunk_response(blob: EncryptedBlob, index: int, range_header: str | None = None) -> Response:
    """支持 RFC 9110 Range 断点续传的密文分块流响应。"""
    if index < 0 or index >= blob.chunk_count:
        raise HTTPException(422, "Chunk index out of range")
    target = chunk_path(blob.workspace_id, blob.id, index)
    if not target.is_file():
        raise HTTPException(404, "Chunk not stored on Core")
    size = target.stat().st_size
    byte_range = _parse_range(range_header, size)
    if byte_range is None:
        start, end = 0, size - 1
        status = 200
    else:
        start, end = byte_range
        status = 206

    length = end - start + 1

    def iter_bytes() -> Iterator[bytes]:
        remaining = length
        with target.open("rb") as fh:
            fh.seek(start)
            while remaining > 0:
                piece = fh.read(min(65536, remaining))
                if not piece:
                    break
                remaining -= len(piece)
                yield piece

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(length),
        "Cache-Control": "no-store",
    }
    if status == 206:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    return StreamingResponse(iter_bytes(), status_code=status, media_type="application/octet-stream", headers=headers)


def issue_edge_ticket(*, actor_id: str, workspace_id: str, blob_id: str, ttl_seconds: int = 600) -> str | None:
    """当部署了 Edge Blob Relay 时，为客户端/节点签发短期受限作用域票据。"""
    secret = os.environ.get("STUDIOLO_EDGE_SECRET", "").strip()
    if not secret:
        secret = JWT_SECRET
    relay_url = os.environ.get("STUDIOLO_EDGE_RELAY_URL", "").strip()
    if not relay_url:
        return None
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "typ": "studiolo_edge_blob",
            "sub": actor_id,
            "ws": workspace_id,
            "bid": blob_id,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()),
        },
        secret,
        algorithm=JWT_ALGORITHM,
    )


def build_resolved_endpoints(
    blob: EncryptedBlob,
    *,
    actor_id: str,
    peer_endpoints: list[TransferEndpoint] | None = None,
) -> list[ResolvedEndpoint]:
    """按 直连 LAN / xtcp P2P -> 云 VPS Edge Relay -> Core 兜底 生成有序下载端点清单。"""
    result: list[ResolvedEndpoint] = []
    if peer_endpoints:
        for ep in peer_endpoints:
            base = ep.url.rstrip("/")
            result.append(
                ResolvedEndpoint(
                    kind=ep.kind,
                    url=f"{base}/artifacts/{blob.id}",
                    priority=ep.priority,
                    label=ep.label or ep.kind.upper(),
                )
            )
    edge_url = os.environ.get("STUDIOLO_EDGE_RELAY_URL", "").strip()
    if edge_url:
        try:
            normalized = validate_endpoint_url(edge_url)
            ticket = issue_edge_ticket(actor_id=actor_id, workspace_id=blob.workspace_id, blob_id=blob.id)
            result.append(
                ResolvedEndpoint(
                    kind="edge_relay",
                    url=f"{normalized}/api/edge/blobs/{blob.id}",
                    priority=50,
                    label="VPS Edge Blob Relay",
                    ticket=ticket,
                )
            )
        except ValueError:
            pass
    result.append(
        ResolvedEndpoint(
            kind="core",
            url=f"/api/v1/fleet/artifacts/{blob.id}",
            priority=90,
            label="Studiolo Core Fallback",
        )
    )
    kind_order = {"lan": 0, "xtcp": 1, "edge_relay": 2, "core": 3}
    return sorted(result, key=lambda item: (kind_order.get(item.kind, 9), item.priority))
