"""Shared Space 分块文件私有目录仓储（支持原子写入、SHA-256 校验与路径防穿越）。"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
from uuid import UUID

from fastapi import HTTPException

from ..credential_store import stage_file
from ..database import runtime_config


def space_blobs_root() -> Path:
    """定位 Shared Space 分块存储根目录（优先环境变量，便于容器与单测隔离）。"""
    env_dir = os.environ.get("STUDIOLO_SPACE_BLOB_DIR", "").strip()
    if env_dir:
        return Path(env_dir).resolve()
    if runtime_config.space_blob_dir:
        return Path(runtime_config.space_blob_dir).resolve()
    data_dir = os.environ.get("STUDIOLO_DATA_DIR", "").strip()
    if data_dir:
        return Path(data_dir).resolve() / "space-blobs"
    return Path("./studiolo-space-blobs").resolve()


def _safe_uuid(name: str, value: str) -> str:
    try:
        return str(UUID(value))
    except ValueError as exc:
        raise HTTPException(422, f"Invalid {name}") from exc


def blob_dir(workspace_id: str, space_id: str, blob_id: str) -> Path:
    ws = _safe_uuid("workspaceId", workspace_id)
    sp = _safe_uuid("spaceId", space_id)
    bl = _safe_uuid("blobId", blob_id)
    return space_blobs_root() / ws / sp / bl


def chunk_file_path(workspace_id: str, space_id: str, blob_id: str, chunk_index: int) -> Path:
    if chunk_index < 0:
        raise HTTPException(422, "Invalid chunk index")
    return blob_dir(workspace_id, space_id, blob_id) / f"{chunk_index:06d}.bin"


def write_chunk_bytes(
    *,
    workspace_id: str,
    space_id: str,
    blob_id: str,
    chunk_index: int,
    data: bytes,
    expected_sha256: str | None = None,
) -> tuple[str, int]:
    """校验 SHA-256 并原子写入分块文件，返回 (actual_sha256, size_bytes)。"""
    digest = hashlib.sha256(data).hexdigest()
    if expected_sha256 and digest != expected_sha256.strip().lower():
        raise HTTPException(400, "Chunk SHA-256 mismatch")
    target = chunk_file_path(workspace_id, space_id, blob_id, chunk_index)
    target.parent.mkdir(parents=True, exist_ok=True)
    stage_file(target, data).commit()
    return digest, len(data)


def read_chunk_bytes(*, workspace_id: str, space_id: str, blob_id: str, chunk_index: int) -> bytes:
    """读取已存储的分块字节，缺失时抛出 404。"""
    target = chunk_file_path(workspace_id, space_id, blob_id, chunk_index)
    if not target.is_file():
        raise HTTPException(404, "Space blob chunk not found")
    return target.read_bytes()


def delete_blob_dir(*, workspace_id: str, space_id: str, blob_id: str) -> None:
    target = blob_dir(workspace_id, space_id, blob_id)
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
