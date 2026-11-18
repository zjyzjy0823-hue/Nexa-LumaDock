"""节点侧高速文件数据面：加密分块发布、LAN 直传端点服务与自适应多路下载。"""

import hashlib
import os
from pathlib import Path
import tempfile
from typing import Any
from urllib.parse import urlsplit

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
import httpx
import jwt

from .config import ensure_allowed_path
from .crypto_chunks import (
    DEFAULT_CHUNK_SIZE,
    decrypt_chunk,
    encode_key_b64,
    iter_encrypted_file_chunks,
)


class DirectArtifactStore:
    """仅托管会话期间已加密分块的只读局域网/xtcp 端点（不暴露任意目录浏览）。"""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        # 记录每个 artifact 允许下载的总块数与共享密钥签名校验（可选）
        self.artifacts: dict[str, dict[str, Any]] = {}

    def stage_encrypted_chunks(self, artifact_id: str, chunks: list[bytes], *, transfer_token: str) -> None:
        folder = self.root / artifact_id
        folder.mkdir(parents=True, exist_ok=True)
        for idx, data in enumerate(chunks):
            fd, tmp = tempfile.mkstemp(prefix=".chunk-", dir=folder)
            try:
                with os.fdopen(fd, "wb") as fh:
                    fh.write(data)
                os.replace(tmp, folder / f"{idx:06d}.enc")
            except BaseException:
                Path(tmp).unlink(missing_ok=True)
                raise
        self.artifacts[artifact_id] = {"chunkCount": len(chunks), "token": transfer_token}


def create_direct_transfer_app(store: DirectArtifactStore) -> FastAPI:
    """创建极轻量节点直传 HTTP 应用（仅接受合法节点签发票据访问已暂存密文分块）。"""
    from fastapi.middleware.cors import CORSMiddleware

    direct_app = FastAPI(title="Studiolo Node Direct Transfer", docs_url=None, redoc_url=None)
    direct_app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["GET", "OPTIONS"],
        allow_headers=["Authorization", "X-Transfer-Token", "Range"],
        expose_headers=["Content-Range", "Accept-Ranges", "Content-Length"],
    )

    @direct_app.get("/health")
    def health():
        return {"status": "ok", "service": "studiolo-node-direct"}

    @direct_app.get("/artifacts/{artifact_id}/chunks/{index}")
    def get_direct_chunk(
        artifact_id: str,
        index: int,
        authorization: str | None = Header(default=None),
        x_transfer_token: str | None = Header(default=None),
        range_header: str | None = Header(default=None, alias="Range"),
    ):
        meta = store.artifacts.get(artifact_id)
        if meta is None or index < 0 or index >= meta["chunkCount"]:
            raise HTTPException(404, "Direct artifact chunk not found")
        supplied = x_transfer_token or (
            authorization[7:].strip() if authorization and authorization.lower().startswith("bearer ") else ""
        )
        if not supplied or supplied != meta["token"]:
            raise HTTPException(401, "Invalid transfer token")

        target = store.root / artifact_id / f"{index:06d}.enc"
        if not target.is_file():
            raise HTTPException(404, "Chunk file missing")
        total = target.stat().st_size
        start, end, status = 0, total - 1, 200
        if range_header and range_header.startswith("bytes="):
            part = range_header[6:].split("-", 1)
            start = int(part[0]) if part[0] else 0
            end = int(part[1]) if len(part) > 1 and part[1] else total - 1
            if start >= total or end < start:
                raise HTTPException(416, "Range Not Satisfiable")
            end = min(end, total - 1)
            status = 206
        length = end - start + 1

        def iter_slice():
            rem = length
            with target.open("rb") as fh:
                fh.seek(start)
                while rem > 0:
                    piece = fh.read(min(65536, rem))
                    if not piece:
                        break
                    rem -= len(piece)
                    yield piece

        headers = {"Accept-Ranges": "bytes", "Content-Length": str(length), "Cache-Control": "no-store"}
        if status == 206:
            headers["Content-Range"] = f"bytes {start}-{end}/{total}"
        return StreamingResponse(iter_slice(), status_code=status, media_type="application/octet-stream", headers=headers)

    return direct_app


async def publish_file_artifact(
    *,
    core_url: str,
    node_token: str,
    file_path: Path,
    allowed_roots: tuple[Path, ...],
    key: bytes,
    mime: str = "application/octet-stream",
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    direct_store: DirectArtifactStore | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """将白名单内本地文件在节点端分块 AES-GCM 加密并发布（优先 Edge Relay / Core 分块接口，同时登记直传缓存）。"""
    import secrets
    from uuid import uuid4

    safe_file = ensure_allowed_path(file_path, allowed_roots)
    if not safe_file.is_file():
        raise FileNotFoundError(f"Not a regular file: {safe_file}")

    # 使用确定性的占位 UUID 生成 AAD 前缀或先初始化元数据后再使用 server id —— 为使每块 AAD 绑定真实 artifact_id，
    # 若预先无法获知 Core ID，采用两步法：先用临时 key/envelope 初始化或分两段：先读取明文元数据尺寸？
    # 更简洁方案：预读总块数？Wait：密文每块仅增 NONCE(12)+TAG(16)=28 字节！因此提前在客户端选定 client_blob_id 或直接分块写入后以 Core 返回的 ID 加密？
    # 若要先拿到 Core 分配的 `artifact_id` 作为 AAD，先 init_placeholder？不行：init 需要真实密文 digest！
    # 因此采用：AAD 绑定随机 `keyId` (UUID，随信封返回并参与鉴权) 或先用 Core/Edge 分片摘要预生成 —— 等一下！
    # 最优兼容方案：如果 `init` 一次即锁定 `artifactId`，我们在节点本地先用 `bundle_id = str(uuid4())` 做密文分块与 digest（或 Core 允许客户端传入可选 id，或信封携带 `aadContext: bundle_id`）；
    # 实际上把 `aadContext` 放进 manifest（并在加解密统一校验 `studiolo:blob:{aadContext}:{index}`），就能既保留随机不可伪造 AAD，又让流式 SHA-256 计算只需遍历文件一次！
    # Wait：前面 crypto_chunks.py 用的是 `artifact_id`；我们先保持 `aad_id` 与服务器 `artifact_id` 分离还是兼容？
    # 检查！如果先用 temp `aad_id = str(uuid4())` 加密各分块，算出总 ciphertextSize 与 sha256，在 manifest 里记录 `{"aadContext": aad_id, "fileName": ..., "mime": ...}`，
    # 那么无论传到 Core、Edge Relay 还是节点直传，加解密字节只需读一次、零二次重加密！
    aad_id = str(uuid4())
    chunks: list[bytes] = []
    chunk_digests: list[str] = []
    hasher = hashlib.sha256()
    total_cipher_bytes = 0
    for _idx, cipher_bytes, c_digest in iter_encrypted_file_chunks(
        safe_file, key=key, artifact_id=aad_id, chunk_size=chunk_size
    ):
        chunks.append(cipher_bytes)
        chunk_digests.append(c_digest)
        hasher.update(cipher_bytes)
        total_cipher_bytes += len(cipher_bytes)

    full_digest = hasher.hexdigest()
    per_chunk_max = max(len(c) for c in chunks)
    manifest = {
        "alg": "AES-256-GCM",
        "aadContext": aad_id,
        "fileName": safe_file.name,
        "mime": mime,
        "plaintextSize": safe_file.stat().st_size,
    }
    headers = {"Authorization": f"Bearer {node_token}"}

    own_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0))
    try:
        init_res = await client.post(
            f"{core_url}/api/v1/fleet/artifacts/init",
            headers=headers,
            json={
                "purpose": "fleet_artifact",
                "digest": full_digest,
                "ciphertextSize": total_cipher_bytes,
                "chunkSize": max(1024, per_chunk_max),
                "chunkCount": len(chunks),
                "storageRole": "core",
                "manifest": manifest,
            },
        )
        init_res.raise_for_status()
        init_data = init_res.json()
        artifact_id = init_data["blob"]["id"]
        endpoints = init_data.get("endpoints") or []

        # 若本节点开启直传缓存，同步在本地保留密文分块，方便同局域网设备直接拉取
        direct_token = secrets.token_urlsafe(24) if direct_store is not None else None
        if direct_store is not None and direct_token is not None:
            direct_store.stage_encrypted_chunks(artifact_id, chunks, transfer_token=direct_token)

        # 优先尝试上传至公网 VPS Edge Relay（减轻 Mac Core 宽带压力），不可达则回退至 Core 分块接口
        uploaded_role = "core"
        edge_ep = next((ep for ep in endpoints if ep.get("kind") == "edge_relay" and ep.get("ticket")), None)
        if edge_ep is not None:
            try:
                edge_headers = {"Authorization": f"Bearer {edge_ep['ticket']}"}
                for idx, (c_bytes, c_dig) in enumerate(zip(chunks, chunk_digests)):
                    put_res = await client.put(
                        f"{edge_ep['url']}/chunks/{idx}",
                        headers={**edge_headers, "X-Chunk-Sha256": c_dig},
                        content=c_bytes,
                    )
                    put_res.raise_for_status()
                commit_edge = await client.post(
                    f"{edge_ep['url']}/commit",
                    headers=edge_headers,
                    json={"digest": full_digest, "ciphertextSize": total_cipher_bytes, "chunkCount": len(chunks)},
                )
                commit_edge.raise_for_status()
                uploaded_role = "edge_relay"
            except Exception:
                uploaded_role = "core"

        if uploaded_role == "core":
            for idx, (c_bytes, c_dig) in enumerate(zip(chunks, chunk_digests)):
                put_res = await client.put(
                    f"{core_url}/api/v1/fleet/artifacts/{artifact_id}/chunks/{idx}",
                    headers={**headers, "X-Chunk-Sha256": c_dig},
                    content=c_bytes,
                )
                put_res.raise_for_status()

        commit_res = await client.post(
            f"{core_url}/api/v1/fleet/artifacts/{artifact_id}/commit",
            headers=headers,
            json={"storageRole": uploaded_role, "manifest": manifest},
        )
        commit_res.raise_for_status()
        return {
            "artifactId": artifact_id,
            "aadContext": aad_id,
            "fileName": safe_file.name,
            "mime": mime,
            "plaintextSize": manifest["plaintextSize"],
            "ciphertextSize": total_cipher_bytes,
            "chunkCount": len(chunks),
            "digest": full_digest,
            "keyB64": encode_key_b64(key),
            "directToken": direct_token,
            "storageRole": uploaded_role,
        }
    finally:
        if own_client:
            await client.aclose()


async def download_and_decrypt_artifact(
    *,
    core_url: str,
    node_token: str,
    artifact_ref: dict[str, Any],
    destination: Path,
    allowed_roots: tuple[Path, ...],
    client: httpx.AsyncClient | None = None,
) -> Path:
    """按 直连 LAN -> Edge Relay -> Core 顺序拉取密文分块，验签并解密落盘至 allowedRoots。"""
    from .crypto_chunks import decode_key_b64

    safe_dest = ensure_allowed_path(destination, allowed_roots)
    safe_dest.parent.mkdir(parents=True, exist_ok=True)
    artifact_id = str(artifact_ref["artifactId"])
    aad_ctx = str(artifact_ref.get("aadContext") or artifact_id)
    key = decode_key_b64(str(artifact_ref["keyB64"]))
    direct_token = artifact_ref.get("directToken")

    auth_headers = {"Authorization": f"Bearer {node_token}"}
    own_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=2.0))
    try:
        ep_res = await client.get(f"{core_url}/api/v1/fleet/artifacts/{artifact_id}/endpoints", headers=auth_headers)
        ep_res.raise_for_status()
        ep_data = ep_res.json()
        chunk_count = int(ep_data["blob"]["chunkCount"])
        endpoints = ep_data["endpoints"]

        downloaded_chunks: list[bytes] | None = None
        for ep in endpoints:
            kind = ep.get("kind")
            base = str(ep["url"])
            if kind == "core" and base.startswith("/"):
                base = f"{core_url}{base}"
            ep_headers = (
                {"X-Transfer-Token": direct_token}
                if kind in ("lan", "xtcp") and direct_token
                else {"Authorization": f"Bearer {ep['ticket']}"}
                if kind == "edge_relay" and ep.get("ticket")
                else auth_headers
            )
            try:
                buf: list[bytes] = []
                for idx in range(chunk_count):
                    r = await client.get(f"{base}/chunks/{idx}", headers=ep_headers)
                    r.raise_for_status()
                    buf.append(r.content)
                downloaded_chunks = buf
                break
            except Exception:
                continue

        if downloaded_chunks is None:
            raise RuntimeError(f"Unable to fetch artifact {artifact_id} from any endpoint")

        fd, tmp = tempfile.mkstemp(prefix=".studiolo-dl-", dir=safe_dest.parent)
        try:
            with os.fdopen(fd, "wb") as fh:
                for idx, enc_bytes in enumerate(downloaded_chunks):
                    plain = decrypt_chunk(key, aad_ctx, idx, enc_bytes)
                    fh.write(plain)
            os.replace(tmp, safe_dest)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        return safe_dest
    finally:
        if own_client:
            await client.aclose()
