"""Studiolo Edge Blob Relay — 公网 VPS 无明文盲盒密文中继服务。

职责边界：
- 仅校验 Core 签发的短期作用域票据 (`typ=studiolo_edge_blob`, `bid=blob_id`)，不接入数据库、不保存用户账户。
- 仅缓存客户端/AgentNode 分块上传的 AES-256-GCM 密文与 SHA-256 校验值，支持 RFC 9110 Range 断点续传与 TTL 自动清扫。
- 严禁依赖 Core 上行带宽转发大文件：公网下载直接命中 VPS 出口带宽。
"""

from contextlib import asynccontextmanager
import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import jwt
from pydantic import BaseModel, Field


MAX_CHUNK_BYTES = 8 * 1024 * 1024
MAX_CHUNK_COUNT = 8192
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class EdgeCommitInput(BaseModel):
    digest: str = Field(min_length=64, max_length=64)
    ciphertextSize: int = Field(ge=1, le=2 * 1024 * 1024 * 1024)
    chunkCount: int = Field(ge=1, le=MAX_CHUNK_COUNT)


def _valid_blob_id(raw: str) -> str:
    try:
        return str(UUID(raw))
    except ValueError as exc:
        raise HTTPException(400, "Invalid blob id") from exc


def prune_expired_blobs(root_dir: Path) -> int:
    """清理超过 TTL 的临时密文缓存目录。"""
    if not root_dir.exists():
        return 0
    now = datetime.now(timezone.utc)
    removed = 0
    for child in root_dir.iterdir():
        if not child.is_dir():
            continue
        meta_file = child / ".meta.json"
        try:
            if meta_file.exists():
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                exp = datetime.fromisoformat(meta["expiresAt"])
                if exp <= now:
                    shutil.rmtree(child, ignore_errors=True)
                    removed += 1
            else:
                # 超过 1 小时未完成提交的游离目录同样回收
                mtime = datetime.fromtimestamp(child.stat().st_mtime, tz=timezone.utc)
                if mtime + timedelta(hours=1) <= now:
                    shutil.rmtree(child, ignore_errors=True)
                    removed += 1
        except Exception:
            continue
    return removed


def create_edge_app(
    *,
    edge_secret: str | None = None,
    data_dir: Path | None = None,
    ttl_seconds: int | None = None,
    cors_origins: list[str] | None = None,
) -> FastAPI:
    resolved_secret = (edge_secret if edge_secret is not None else os.environ.get("STUDIOLO_EDGE_SECRET", "")).strip()
    if len(resolved_secret) < 16:
        raise RuntimeError("STUDIOLO_EDGE_SECRET must be at least 16 characters")

    storage_root = (
        data_dir
        if data_dir is not None
        else Path(os.environ.get("STUDIOLO_EDGE_DATA_DIR", "/data/edge-blobs")).expanduser()
    ).resolve()
    storage_root.mkdir(parents=True, exist_ok=True)

    ttl = ttl_seconds if ttl_seconds is not None else int(os.environ.get("STUDIOLO_EDGE_TTL_SECONDS", "3600"))
    if cors_origins is None:
        raw_cors = os.environ.get("STUDIOLO_EDGE_CORS_ORIGINS", "")
        origins = [o.strip() for o in raw_cors.split(",") if o.strip()]
    else:
        origins = cors_origins

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        stop_evt = asyncio.Event()

        async def gc_loop():
            while not stop_evt.is_set():
                prune_expired_blobs(storage_root)
                try:
                    await asyncio.wait_for(stop_evt.wait(), timeout=300.0)
                except asyncio.TimeoutError:
                    pass

        task = asyncio.create_task(gc_loop())
        try:
            yield
        finally:
            stop_evt.set()
            await task

    app = FastAPI(title="Studiolo Edge Blob Relay", version="0.7.0", docs_url=None, redoc_url=None, lifespan=lifespan)

    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_methods=["GET", "PUT", "POST", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "X-Chunk-Sha256", "Range"],
            expose_headers=["Content-Range", "Accept-Ranges", "Content-Length"],
        )

    def verify_ticket(blob_id: str, authorization: str | None = Header(default=None)) -> str:
        safe_id = _valid_blob_id(blob_id)
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(401, "Missing Bearer ticket")
        token = authorization[7:].strip()
        try:
            claims = jwt.decode(token, resolved_secret, algorithms=["HS256"])
        except jwt.InvalidTokenError as exc:
            raise HTTPException(401, "Invalid or expired edge ticket") from exc
        if claims.get("typ") != "studiolo_edge_blob" or claims.get("bid") != safe_id:
            raise HTTPException(403, "Ticket does not grant access to this blob")
        return safe_id

    @app.get("/health")
    def health():
        return {"status": "ok", "service": "studiolo-edge-relay"}

    @app.put("/api/edge/blobs/{blob_id}/chunks/{index}")
    async def put_chunk(
        blob_id: str,
        index: int,
        request: Request,
        x_chunk_sha256: str | None = Header(default=None),
        safe_id: str = Depends(verify_ticket),
    ):
        if index < 0 or index >= MAX_CHUNK_COUNT:
            raise HTTPException(422, "Chunk index out of range")
        raw = await request.body()
        if not raw or len(raw) > MAX_CHUNK_BYTES:
            raise HTTPException(413, "Chunk empty or exceeds 8 MiB limit")
        if x_chunk_sha256 is not None:
            norm = x_chunk_sha256.strip().lower()
            if not _SHA256_RE.match(norm) or hashlib.sha256(raw).hexdigest() != norm:
                raise HTTPException(422, "Chunk SHA-256 mismatch")

        blob_dir = storage_root / safe_id
        blob_dir.mkdir(parents=True, exist_ok=True)
        dest = blob_dir / f"chunk_{index:05d}.bin"
        fd, tmp = tempfile.mkstemp(prefix=".edge-chunk-", dir=blob_dir)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(raw)
            os.replace(tmp, dest)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

        meta_path = blob_dir / ".meta.json"
        if not meta_path.exists():
            exp = (datetime.now(timezone.utc) + timedelta(seconds=ttl)).isoformat()
            meta_path.write_text(json.dumps({"expiresAt": exp}), encoding="utf-8")

        return {"blobId": safe_id, "chunkIndex": index, "bytesWritten": len(raw)}

    @app.post("/api/edge/blobs/{blob_id}/commit")
    def commit_blob(blob_id: str, payload: EdgeCommitInput, safe_id: str = Depends(verify_ticket)):
        blob_dir = storage_root / safe_id
        if not blob_dir.exists():
            raise HTTPException(404, "No uploaded chunks for blob")
        norm_digest = payload.digest.strip().lower()
        if not _SHA256_RE.match(norm_digest):
            raise HTTPException(422, "Invalid digest")

        hasher = hashlib.sha256()
        total_size = 0
        for i in range(payload.chunkCount):
            chunk_path = blob_dir / f"chunk_{i:05d}.bin"
            if not chunk_path.is_file():
                raise HTTPException(422, f"Missing chunk #{i}")
            with chunk_path.open("rb") as fh:
                while True:
                    piece = fh.read(65536)
                    if not piece:
                        break
                    hasher.update(piece)
                    total_size += len(piece)

        if total_size != payload.ciphertextSize or hasher.hexdigest() != norm_digest:
            raise HTTPException(422, "Ciphertext size or SHA-256 digest mismatch")

        now = datetime.now(timezone.utc)
        exp = now + timedelta(seconds=ttl)
        meta = {"committedAt": now.isoformat(), "expiresAt": exp.isoformat(), "chunkCount": payload.chunkCount}
        (blob_dir / ".meta.json").write_text(json.dumps(meta), encoding="utf-8")
        return {"blobId": safe_id, "status": "committed", "expiresAt": meta["expiresAt"]}

    @app.get("/api/edge/blobs/{blob_id}/chunks/{index}")
    def get_chunk(
        blob_id: str,
        index: int,
        range_header: str | None = Header(default=None, alias="Range"),
        safe_id: str = Depends(verify_ticket),
    ):
        blob_dir = storage_root / safe_id
        meta_path = blob_dir / ".meta.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if datetime.fromisoformat(meta["expiresAt"]) <= datetime.now(timezone.utc):
                shutil.rmtree(blob_dir, ignore_errors=True)
                raise HTTPException(410, "Blob cache expired")

        chunk_path = blob_dir / f"chunk_{index:05d}.bin"
        if not chunk_path.is_file():
            raise HTTPException(404, "Chunk not found")

        size = chunk_path.stat().st_size
        start = 0
        end = size - 1
        status = 200
        if range_header and range_header.startswith("bytes="):
            spec = range_header[6:].strip().split(",", 1)[0]
            if "-" not in spec:
                raise HTTPException(416, "Invalid Range header")
            s_part, e_part = spec.split("-", 1)
            start = int(s_part) if s_part else 0
            end = int(e_part) if e_part else size - 1
            if start < 0 or end < start or start >= size:
                raise HTTPException(416, "Range Not Satisfiable")
            end = min(end, size - 1)
            status = 206
        length = end - start + 1

        def iter_bytes():
            rem = length
            with chunk_path.open("rb") as fh:
                fh.seek(start)
                while rem > 0:
                    piece = fh.read(min(65536, rem))
                    if not piece:
                        break
                    rem -= len(piece)
                    yield piece

        headers = {
            "Accept-Ranges": "bytes",
            "Content-Length": str(length),
            "Cache-Control": "no-store",
        }
        if status == 206:
            headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        return StreamingResponse(iter_bytes(), status_code=status, media_type="application/octet-stream", headers=headers)

    @app.delete("/api/edge/blobs/{blob_id}", status_code=204)
    def delete_blob(blob_id: str, safe_id: str = Depends(verify_ticket)):
        shutil.rmtree(storage_root / safe_id, ignore_errors=True)

    return app


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8090"))
    uvicorn.run(create_edge_app(), host="127.0.0.1", port=port)
