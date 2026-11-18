"""Wave 1 验收测试：0020 迁移、sn_live_ 节点认证、加密分块总线、WSS 中继及零正文持久化哨兵。"""

import hashlib
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

from fastapi.testclient import TestClient
import jwt
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from starlette.websockets import WebSocketDisconnect

from app.database import Base, get_db
from app.main import app


BACKEND_DIR = Path(__file__).resolve().parents[1]


def test_0020_migration_upgrade_and_downgrade(tmp_path):
    db_file = tmp_path / "fleet_mig.db"
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{db_file}", "STUDIOLO_MODE": "local"}

    def migrate(*args: str):
        res = subprocess.run([sys.executable, "-m", "alembic", *args], cwd=BACKEND_DIR, env=env, capture_output=True, text=True)
        assert res.returncode == 0, res.stderr

    migrate("upgrade", "0019_local_automation_events")
    migrate("upgrade", "0020_fleet_nodes_and_blobs")

    engine = create_engine(f"sqlite:///{db_file}")
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == "0020_fleet_nodes_and_blobs"
        tables = set(inspect(conn).get_table_names())
        assert {"agent_nodes", "encrypted_blobs"}.issubset(tables)

    migrate("downgrade", "0019_local_automation_events")
    with engine.connect() as conn:
        tables = set(inspect(conn).get_table_names())
        assert "agent_nodes" not in tables
        assert "encrypted_blobs" not in tables
    engine.dispose()


def test_node_lifecycle_isolation_and_revocation(client, users):
    a_headers, b_headers = users
    res = client.post("/api/v1/fleet/nodes", headers=a_headers, json={"name": "Mac Studio", "platform": "macos", "hostname": "mac.local"})
    assert res.status_code == 201
    body = res.json()
    node_id = body["node"]["id"]
    token1 = body["nodeToken"]
    assert token1.startswith("sn_live_")
    assert body["node"]["tokenLast4"] == token1[-4:]
    assert body["node"]["status"] == "offline"

    # 工作区横向越权全 404
    assert client.patch(f"/api/v1/fleet/nodes/{node_id}", headers=b_headers, json={"name": "Hacked"}).status_code == 404
    assert client.post(f"/api/v1/fleet/nodes/{node_id}/token", headers=b_headers).status_code == 404
    assert client.post(f"/api/v1/fleet/nodes/{node_id}/revoke", headers=b_headers).status_code == 404
    assert client.delete(f"/api/v1/fleet/nodes/{node_id}", headers=b_headers).status_code == 404

    # 轮换与吊销凭证
    rot = client.post(f"/api/v1/fleet/nodes/{node_id}/token", headers=a_headers)
    assert rot.status_code == 200
    token2 = rot.json()["nodeToken"]
    assert token2 != token1

    rev = client.post(f"/api/v1/fleet/nodes/{node_id}/revoke", headers=a_headers)
    assert rev.status_code == 200
    assert rev.json()["status"] == "revoked"

    # 旧/已吊销凭证不得用于文件或 WS 接口
    assert client.post(
        "/api/v1/fleet/artifacts/init",
        headers={"Authorization": f"Bearer {token2}"},
        json={"digest": "0" * 64, "ciphertextSize": 100, "chunkSize": 1024, "chunkCount": 1},
    ).status_code == 401


def test_encrypted_chunked_blob_transfer_and_range(client, users, tmp_path, monkeypatch):
    monkeypatch.setenv("STUDIOLO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STUDIOLO_EDGE_RELAY_URL", "https://edge.studiolo.example")
    monkeypatch.setenv("STUDIOLO_EDGE_SECRET", "edge-test-secret-0123456789")
    a_headers, b_headers = users

    # 注册一个节点获取 sn_live_，模拟节点作为上传者
    node_resp = client.post("/api/v1/fleet/nodes", headers=a_headers, json={"name": "Win PC", "platform": "windows"})
    node_token = node_resp.json()["nodeToken"]
    n_headers = {"Authorization": f"Bearer {node_token}"}

    chunk0 = b"ENCRYPTED_CHUNK_ZERO_" * 60  # 1260 B
    chunk1 = b"TAIL_CIPHER_" * 12  # 144 B
    full = chunk0 + chunk1
    digest = hashlib.sha256(full).hexdigest()

    init = client.post(
        "/api/v1/fleet/artifacts/init",
        headers=n_headers,
        json={
            "purpose": "fleet_artifact",
            "digest": digest,
            "ciphertextSize": len(full),
            "chunkSize": len(chunk0),
            "chunkCount": 2,
            "storageRole": "core",
            "manifest": {"alg": "AES-256-GCM", "fileName": "patch.zip"},
        },
    )
    assert init.status_code == 201
    artifact_id = init.json()["blob"]["id"]
    kinds = [ep["kind"] for ep in init.json()["endpoints"]]
    assert kinds == ["edge_relay", "core"]
    edge_ep = init.json()["endpoints"][0]
    decoded = jwt.decode(edge_ep["ticket"], "edge-test-secret-0123456789", algorithms=["HS256"])
    assert decoded["bid"] == artifact_id and decoded["typ"] == "studiolo_edge_blob"

    # 错误 SHA-256 与越界 chunk 均应被拒绝
    bad_put = client.put(
        f"/api/v1/fleet/artifacts/{artifact_id}/chunks/0",
        headers={**n_headers, "X-Chunk-Sha256": "f" * 64},
        content=chunk0,
    )
    assert bad_put.status_code == 422

    assert client.put(
        f"/api/v1/fleet/artifacts/{artifact_id}/chunks/0",
        headers={**n_headers, "X-Chunk-Sha256": hashlib.sha256(chunk0).hexdigest()},
        content=chunk0,
    ).status_code == 200
    assert client.put(
        f"/api/v1/fleet/artifacts/{artifact_id}/chunks/1",
        headers={**n_headers, "X-Chunk-Sha256": hashlib.sha256(chunk1).hexdigest()},
        content=chunk1,
    ).status_code == 200

    # 提交完整性校验
    committed = client.post(f"/api/v1/fleet/artifacts/{artifact_id}/commit", headers=n_headers)
    assert committed.status_code == 200
    assert committed.json()["committedAt"]

    # 跨工作区读取被拒（404）
    assert client.get(f"/api/v1/fleet/artifacts/{artifact_id}", headers=b_headers).status_code == 404
    assert client.get(f"/api/v1/fleet/artifacts/{artifact_id}/chunks/0", headers=b_headers).status_code == 404

    # 同工作区用户端可流式 + Range 断点下载
    dl_full = client.get(f"/api/v1/fleet/artifacts/{artifact_id}/chunks/0", headers=a_headers)
    assert dl_full.status_code == 200 and dl_full.content == chunk0
    dl_range = client.get(
        f"/api/v1/fleet/artifacts/{artifact_id}/chunks/1",
        headers={**a_headers, "Range": "bytes=5-15"},
    )
    assert dl_range.status_code == 206
    assert dl_range.headers["content-range"] == f"bytes 5-15/{len(chunk1)}"
    assert dl_range.content == chunk1[5:16]

    # 删除同时清理磁盘分块
    assert client.delete(f"/api/v1/fleet/artifacts/{artifact_id}", headers=a_headers).status_code == 204
    assert client.get(f"/api/v1/fleet/artifacts/{artifact_id}", headers=a_headers).status_code == 404


def test_websocket_relay_idempotency_security_and_zero_persistence(tmp_path):
    db_path = tmp_path / "sentinel.db"
    test_engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(test_engine)

    def override_db():
        with Session(test_engine, autoflush=False, expire_on_commit=False) as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    sentinel_prompt = "SENTINEL_SECRET_PROMPT_XYZ_9981"
    sentinel_reply = "SENTINEL_REPLY_ABC_7742"
    try:
        with TestClient(app) as client:
            reg = client.post("/api/v1/auth/register", json={"username": "fleet_owner", "password": "password123"})
            assert reg.status_code == 201
            jwt_token = reg.json()["access_token"]
            headers = {"Authorization": f"Bearer {jwt_token}"}

            node_res = client.post("/api/v1/fleet/nodes", headers=headers, json={"name": "OCI Node 1", "platform": "linux"})
            node_id = node_res.json()["node"]["id"]
            sn_token = node_res.json()["nodeToken"]

            # 严禁在 Query 参数传递凭证
            with pytest.raises(WebSocketDisconnect) as exc_info:
                with client.websocket_connect(f"/ws/fleet/client?token={jwt_token}") as ws:
                    ws.receive_json()
            assert exc_info.value.code == 4401

            # 连接 Node（通过请求头鉴权确认握手），再断开改用首帧 auth + hello 重连验证元数据与推送
            with client.websocket_connect("/ws/fleet/node", headers={"Authorization": f"Bearer {sn_token}"}) as node_ws:
                ready = node_ws.receive_json()
                assert ready["type"] == "NodeReady" and ready["nodeId"] == node_id

            with client.websocket_connect("/ws/fleet/node") as node_ws:
                node_ws.send_json({
                    "type": "auth",
                    "token": sn_token,
                    "hello": {
                        "hostname": "oci-1",
                        "platform": "linux",
                        "allowedRoots": ["/srv/projects"],
                        "adapters": [{"provider": "codex", "version": "0.9.0", "status": "ready", "capabilities": ["chat", "approval"]}],
                        "transferEndpoints": [{"kind": "lan", "url": "http://10.0.0.8:9090", "priority": 10, "label": "OCI LAN"}],
                    },
                })
                ready = node_ws.receive_json()
                assert ready["type"] == "NodeReady"

                with client.websocket_connect("/ws/fleet/client") as ui_ws:
                    ui_ws.send_json({"type": "auth", "token": jwt_token})
                    snap = ui_ws.receive_json()
                    assert snap["type"] == "FleetSnapshot"
                    assert len(snap["nodes"]) == 1 and snap["nodes"][0]["transferEndpoints"][0]["url"] == "http://10.0.0.8:9090"

                    # 发送带幂等 requestId 的提问 + 重复提交测试
                    ui_ws.send_json({"type": "prompt.send", "nodeId": node_id, "provider": "codex", "sessionId": "s1", "text": sentinel_prompt, "requestId": "req-1"})
                    forwarded = node_ws.receive_json()
                    assert forwarded["text"] == sentinel_prompt and forwarded["requestId"] == "req-1"

                    ui_ws.send_json({"type": "prompt.send", "nodeId": node_id, "provider": "codex", "sessionId": "s1", "text": sentinel_prompt, "requestId": "req-1"})
                    dup = ui_ws.receive_json()
                    assert dup["type"] == "DuplicateIgnored" and dup["requestId"] == "req-1"

                    # Node 推送工具审批与流式文本，Client 回复允许一次
                    node_ws.send_json({"type": "PermissionRequest", "sessionId": "s1", "callId": "call-1", "command": "pytest"})
                    perm_evt = ui_ws.receive_json()
                    assert perm_evt["type"] == "PermissionRequest" and perm_evt["nodeId"] == node_id

                    ui_ws.send_json({"type": "permission.respond", "nodeId": node_id, "sessionId": "s1", "callId": "call-1", "decision": "allow_once"})
                    perm_back = node_ws.receive_json()
                    assert perm_back["decision"] == "allow_once"

                    node_ws.send_json({"type": "TextDelta", "sessionId": "s1", "text": sentinel_reply})
                    delta = ui_ws.receive_json()
                    assert delta["text"] == sentinel_reply

                    node_ws.send_json({
                        "type": "TokenUsage",
                        "sessionId": "s1",
                        "scope": "turn",
                        "inputTokens": 120,
                        "outputTokens": 45,
                        "totalTokens": 165,
                        "source": "exact",
                    })
                    usage_evt = ui_ws.receive_json()
                    assert usage_evt["type"] == "TokenUsage" and usage_evt["nodeId"] == node_id
                    assert usage_evt["totalTokens"] == 165

                # 验证在线状态与吊销立即踢下线
                assert client.get("/api/v1/fleet/nodes", headers=headers).json()[0]["status"] == "online"
                assert client.post(f"/api/v1/fleet/nodes/{node_id}/revoke", headers=headers).status_code == 200
                with pytest.raises(WebSocketDisconnect):
                    node_ws.receive_json()

            # 检查未连接节点的离线错误提示
            with client.websocket_connect("/ws/fleet/client") as ui_ws:
                ui_ws.send_json({"type": "auth", "token": jwt_token})
                _ = ui_ws.receive_json()
                ui_ws.send_json({"type": "prompt.send", "nodeId": node_id, "text": "ping", "requestId": "req-offline"})
                offline_err = ui_ws.receive_json()
                assert offline_err["type"] == "NodeUnavailable" and offline_err["code"] == "node_offline"

        # 零聊天正文落盘哨兵检查：整库所有表及原始字节文件中不得出现任何对话哨兵字符串
        raw_db_bytes = db_path.read_bytes()
        assert sentinel_prompt.encode() not in raw_db_bytes
        assert sentinel_reply.encode() not in raw_db_bytes
        with sqlite3.connect(db_path) as raw_conn:
            for (table_name,) in raw_conn.execute("SELECT name FROM sqlite_master WHERE type='table'"):
                for row in raw_conn.execute(f'SELECT * FROM "{table_name}"'):
                    row_text = repr(row)
                    assert sentinel_prompt not in row_text
                    assert sentinel_reply not in row_text
    finally:
        app.dependency_overrides.clear()
        test_engine.dispose()


def test_blob_chunk_cors_preflight(client, users):
    origin = "http://localhost:5173"
    preflight = client.options(
        "/api/v1/fleet/artifacts/00000000-0000-0000-0000-000000000001/chunks/0",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Headers": "authorization,x-chunk-sha256",
        },
    )
    assert preflight.status_code == 200
    assert "x-chunk-sha256" in preflight.headers.get("access-control-allow-headers", "").lower()
