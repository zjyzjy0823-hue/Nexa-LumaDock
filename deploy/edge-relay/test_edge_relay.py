"""Edge Blob Relay 单元测试：受限作用域 HS256 票据校验、分块 SHA-256、Range 206 与 TTL 过期清扫。"""

from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
import jwt

from edge_relay import create_edge_app


SECRET = "edge-relay-test-secret-key-32-chars-minimum"


def _make_ticket(blob_id: str, *, ttl_seconds: int = 300, secret: str = SECRET) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "typ": "studiolo_edge_blob",
            "sub": "node-1",
            "ws": "ws-1",
            "bid": blob_id,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()),
        },
        secret,
        algorithm="HS256",
    )


def test_edge_relay_ticket_chunks_range_and_ttl(tmp_path: Path):
    app = create_edge_app(edge_secret=SECRET, data_dir=tmp_path / "blobs", ttl_seconds=120)
    blob_a = str(uuid4())
    blob_b = str(uuid4())
    ticket_a = _make_ticket(blob_a)
    ticket_b = _make_ticket(blob_b)

    c0 = b"ENCRYPTED-CHUNK-0-" + b"A" * 512
    c1 = b"ENCRYPTED-CHUNK-1-" + b"B" * 256
    full_sha = hashlib.sha256(c0 + c1).hexdigest()

    with TestClient(app) as tc:
        assert tc.get("/health").json()["status"] == "ok"

        # 跨 blob 票据越权必须返回 403
        bad_scope = tc.put(
            f"/api/edge/blobs/{blob_a}/chunks/0",
            headers={"Authorization": f"Bearer {ticket_b}"},
            content=c0,
        )
        assert bad_scope.status_code == 403

        # 篡改分块 SHA-256 返回 422
        bad_hash = tc.put(
            f"/api/edge/blobs/{blob_a}/chunks/0",
            headers={"Authorization": f"Bearer {ticket_a}", "X-Chunk-Sha256": "0" * 64},
            content=c0,
        )
        assert bad_hash.status_code == 422

        # 正常分块上传 + 提交
        for idx, chunk in enumerate((c0, c1)):
            r = tc.put(
                f"/api/edge/blobs/{blob_a}/chunks/{idx}",
                headers={"Authorization": f"Bearer {ticket_a}", "X-Chunk-Sha256": hashlib.sha256(chunk).hexdigest()},
                content=chunk,
            )
            assert r.status_code == 200

        cm = tc.post(
            f"/api/edge/blobs/{blob_a}/commit",
            headers={"Authorization": f"Bearer {ticket_a}"},
            json={"digest": full_sha, "ciphertextSize": len(c0) + len(c1), "chunkCount": 2},
        )
        assert cm.status_code == 200

        # HTTP Range 206 分段下载
        r_partial = tc.get(
            f"/api/edge/blobs/{blob_a}/chunks/0",
            headers={"Authorization": f"Bearer {ticket_a}", "Range": "bytes=0-17"},
        )
        assert r_partial.status_code == 206
        assert r_partial.content == b"ENCRYPTED-CHUNK-0-"

        # DELETE 清理密文目录
        assert tc.delete(f"/api/edge/blobs/{blob_a}", headers={"Authorization": f"Bearer {ticket_a}"}).status_code == 204
        assert not (tmp_path / "blobs" / blob_a).exists()


def test_edge_relay_expired_ttl_returns_410_and_cleans(tmp_path: Path):
    app = create_edge_app(edge_secret=SECRET, data_dir=tmp_path / "blobs", ttl_seconds=-5)
    blob_id = str(uuid4())
    ticket = _make_ticket(blob_id)
    chunk = b"TTL-EXPIRED-BYTES"

    with TestClient(app) as tc:
        tc.put(f"/api/edge/blobs/{blob_id}/chunks/0", headers={"Authorization": f"Bearer {ticket}"}, content=chunk)
        r = tc.get(f"/api/edge/blobs/{blob_id}/chunks/0", headers={"Authorization": f"Bearer {ticket}"})
        assert r.status_code == 410
        assert not (tmp_path / "blobs" / blob_id).exists()
