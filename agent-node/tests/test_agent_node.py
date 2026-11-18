"""Wave 2 验收测试：allowedRoots 沙箱、AES-GCM 分块加解密与直传端、Git Worktree 并发、JSON-RPC 与节点守护逻辑。"""

import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from cryptography.exceptions import InvalidTag
from fastapi.testclient import TestClient
import httpx
import pytest

from agent_node.adapters.jsonrpc import StdioJsonRpcProcess
from agent_node.adapters.mock import MockAdapter
from agent_node.config import (
    DirectTransferConfig,
    NodeConfig,
    PathOutsideAllowedRootsError,
    canonicalize_roots,
    ensure_allowed_path,
    validate_core_base_url,
)
from agent_node.crypto_chunks import decrypt_chunk, encrypt_chunk, generate_file_key, iter_encrypted_file_chunks
from agent_node.daemon import AgentNodeDaemon
from agent_node.transfer import DirectArtifactStore, create_direct_transfer_app
from agent_node.worktree import create_session_worktree, remove_session_worktree


def test_allowed_roots_and_non_loopback_tls(tmp_path):
    allowed = tmp_path / "workspace"
    allowed.mkdir()
    outside = tmp_path / "secrets"
    outside.mkdir()
    (outside / "id_rsa").write_text("secret")

    roots = canonicalize_roots([str(allowed)])
    inside = allowed / "project" / "main.py"
    inside.parent.mkdir()
    inside.write_text("print('ok')")

    assert ensure_allowed_path(inside, roots) == Path(os.path.realpath(inside))
    with pytest.raises(PathOutsideAllowedRootsError):
        ensure_allowed_path(allowed / ".." / "secrets" / "id_rsa", roots)
    with pytest.raises(PathOutsideAllowedRootsError):
        ensure_allowed_path(outside, roots)

    assert validate_core_base_url("http://127.0.0.1:17800/") == "http://127.0.0.1:17800"
    assert validate_core_base_url("https://core.example.com/") == "https://core.example.com"
    with pytest.raises(ValueError, match="https"):
        validate_core_base_url("http://core.example.com:8000")


def test_crypto_chunks_roundtrip_tamper_and_direct_server(tmp_path):
    src = tmp_path / "payload.bin"
    raw_data = os.urandom(1400)
    src.write_bytes(raw_data)

    key = generate_file_key()
    aad_id = "11111111-1111-1111-1111-111111111111"
    encrypted = list(iter_encrypted_file_chunks(src, key=key, artifact_id=aad_id, chunk_size=512))
    assert len(encrypted) == 3

    reconstructed = b"".join(decrypt_chunk(key, aad_id, idx, payload) for idx, payload, _ in encrypted)
    assert reconstructed == raw_data

    # 跨块索引错乱或篡改密文必须验签失败
    tampered = bytearray(encrypted[0][2 - 1])
    tampered[-1] ^= 0xFF
    with pytest.raises(InvalidTag):
        decrypt_chunk(key, aad_id, 0, bytes(tampered))
    with pytest.raises(InvalidTag):
        decrypt_chunk(key, aad_id, 1, encrypted[0][1])

    # Direct LAN HTTP 服务器检验令牌隔离、分块与断点 Range
    store = DirectArtifactStore(tmp_path / "staging")
    chunks_only = [item[1] for item in encrypted]
    store.stage_encrypted_chunks("art-1", chunks_only, transfer_token="dt_secret_abc")
    app = create_direct_transfer_app(store)
    with TestClient(app) as client:
        assert client.get("/artifacts/art-1/chunks/0").status_code == 401
        assert client.get("/artifacts/art-1/chunks/0", headers={"X-Transfer-Token": "wrong"}).status_code == 401
        res = client.get("/artifacts/art-1/chunks/0", headers={"X-Transfer-Token": "dt_secret_abc"})
        assert res.status_code == 200 and res.content == chunks_only[0]
        rng = client.get(
            "/artifacts/art-1/chunks/0",
            headers={"X-Transfer-Token": "dt_secret_abc", "Range": "bytes=0-15"},
        )
        assert rng.status_code == 206 and rng.content == chunks_only[0][:16]


def test_git_worktree_concurrency_and_sandbox(tmp_path):
    allowed = tmp_path / "repos"
    repo = allowed / "demo"
    repo.mkdir(parents=True)
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@studiolo.local"], cwd=repo, check=True)
    (repo / "README.md").write_text("init\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)

    roots = canonicalize_roots([str(allowed)])
    wt1 = create_session_worktree(repo, "codex-task-1", roots)
    wt2 = create_session_worktree(repo, "hermes-task-2", roots)
    assert wt1 != wt2 and (wt1 / "README.md").is_file() and (wt2 / "README.md").is_file()

    outside_repo = tmp_path / "outside"
    outside_repo.mkdir()
    with pytest.raises(PathOutsideAllowedRootsError):
        create_session_worktree(outside_repo, "evil", roots)

    remove_session_worktree(repo, wt1, roots)
    remove_session_worktree(repo, wt2, roots)


def test_daemon_mock_approval_and_handoff_and_stdio_jsonrpc(tmp_path):
    async def _run():
        root = tmp_path / "work"
        root.mkdir()
        roots = canonicalize_roots([str(root)])
        cfg = NodeConfig(
            core_url="http://127.0.0.1:48197",
            node_token="sn_live_testnode_1234567890",
            allowed_roots=roots,
            direct=DirectTransferConfig(enabled=False),
            providers={"mock": {"enabled": True}},
        )
        daemon = AgentNodeDaemon(cfg, staging_dir=tmp_path / "stage")

        sent_frames: list[dict] = []

        class FakeWS:
            async def send(self, payload: str) -> None:
                sent_frames.append(json.loads(payload))

        ws = FakeWS()
        await daemon.handle_command(ws, {"type": "session.open", "provider": "mock", "cwd": str(root), "requestId": "open-1"})
        opened = next(f for f in sent_frames if f["type"] == "SessionOpened")
        sid = opened["sessionId"]

        # 越界 cwd 必须被 path_forbidden 拦住
        await daemon.handle_command(ws, {"type": "session.open", "provider": "mock", "cwd": str(tmp_path), "requestId": "open-bad"})
        bad = next(f for f in sent_frames if f.get("requestId") == "open-bad")
        assert bad["type"] == "Failed" and bad["code"] == "path_forbidden"

        # 带 RUN_CMD 会挂起等待 PermissionRequest 审批
        task = asyncio.create_task(
            daemon.handle_command(ws, {"type": "prompt.send", "provider": "mock", "sessionId": sid, "text": "please RUN_CMD now", "requestId": "p-1"})
        )
        for _ in range(40):
            if any(f["type"] == "PermissionRequest" for f in sent_frames):
                break
            await asyncio.sleep(0.02)
        perm = next(f for f in sent_frames if f["type"] == "PermissionRequest")
        await daemon.handle_command(ws, {"type": "permission.respond", "callId": perm["callId"], "decision": "allow_once"})
        await asyncio.wait_for(task, timeout=3.0)
        assert any(f["type"] == "TextDelta" and "Echo: please RUN_CMD now" in f["text"] for f in sent_frames)
        assert any(f["type"] == "Completed" and f["requestId"] == "p-1" for f in sent_frames)

        # 极速模式（autoApprove=True）：带 RUN_CMD 也不应发送 PermissionRequest，直接放行执行
        perm_count_before = sum(1 for f in sent_frames if f["type"] == "PermissionRequest")
        await daemon.handle_command(
            ws,
            {
                "type": "prompt.send",
                "provider": "mock",
                "sessionId": sid,
                "text": "turbo RUN_CMD fast",
                "options": {"autoApprove": True},
                "requestId": "p-turbo",
            },
        )
        assert sum(1 for f in sent_frames if f["type"] == "PermissionRequest") == perm_count_before
        assert any(f["type"] == "ToolCall" and f.get("decision") == "allow_once" for f in sent_frames)
        assert any(f["type"] == "TextDelta" and "Echo: turbo RUN_CMD fast" in f["text"] for f in sent_frames)

        # 验证节点侧对带路径穿越的 E2EE 附件会安全解密到 .studiolo-inbox，以及主动发布 ArtifactOffered 产物
        from agent_node import daemon as daemon_mod

        seen_dl: list[Path] = []
        orig_dl = daemon_mod.download_and_decrypt_artifact
        orig_pub = daemon_mod.publish_file_artifact

        async def fake_dl(*, core_url, node_token, artifact_ref, destination, allowed_roots, client=None):
            safe_d = ensure_allowed_path(destination, allowed_roots)
            safe_d.parent.mkdir(parents=True, exist_ok=True)
            safe_d.write_bytes(b"PNG_DATA")
            seen_dl.append(safe_d)
            return safe_d

        async def fake_pub(*, core_url, node_token, file_path, allowed_roots, key, mime="application/octet-stream", **kwargs):
            return {"artifactId": "art-pub-1", "fileName": file_path.name, "mime": mime, "plaintextSize": file_path.stat().st_size, "ciphertextSize": 64, "chunkCount": 1, "digest": "a" * 64, "aadContext": "ctx-1", "keyB64": "abc"}

        daemon_mod.download_and_decrypt_artifact = fake_dl
        daemon_mod.publish_file_artifact = fake_pub
        try:
            await daemon.handle_command(
                ws,
                {
                    "type": "prompt.send",
                    "provider": "mock",
                    "sessionId": sid,
                    "text": "check attachment",
                    "attachments": [{"artifactId": "art-in-99", "keyB64": "dummy", "fileName": "../../evil.png", "mime": "image/png"}],
                    "requestId": "p-att",
                },
            )
            assert len(seen_dl) == 1
            assert seen_dl[0].parent.name == ".studiolo-inbox"
            assert seen_dl[0].parent.parent == root.resolve()
            assert "evil.png" in seen_dl[0].name and ".." not in str(seen_dl[0])
            assert any(f["type"] == "TextDelta" and "(attachments=1)" in f["text"] for f in sent_frames)

            sample_out = root / "report.txt"
            sample_out.write_text("ok", encoding="utf-8")
            await daemon.publish_session_artifact(ws, provider="mock", session_id=sid, file_path=sample_out, mime="text/plain", request_id="p-att")
            offered = next(f for f in sent_frames if f["type"] == "ArtifactOffered")
            assert offered["artifact"]["fileName"] == "report.txt" and offered["provider"] == "mock"
        finally:
            daemon_mod.download_and_decrypt_artifact = orig_dl
            daemon_mod.publish_file_artifact = orig_pub

        # 再测试 @Handoff 携带 Artifact 票据转发
        await daemon.handle_command(
            ws,
            {
                "type": "handoff.send",
                "provider": "mock",
                "sessionId": sid,
                "summary": "Review generated bundle",
                "artifact": {"artifactId": "art-xyz", "fileName": "dist.zip"},
                "requestId": "h-1",
            },
        )
        assert any(f["type"] == "TextDelta" and "dist.zip" in f["text"] for f in sent_frames)

        # StdioJsonRpcProcess 验证与真实子进程 JSON-RPC 往返 + server approval request
        script = (
            "import sys, json\n"
            "for line in sys.stdin:\n"
            "  msg = json.loads(line)\n"
            "  if msg.get('method') == 'ping':\n"
            "    sys.stdout.write(json.dumps({'jsonrpc':'2.0','id':99,'method':'approve','params':{'cmd':'ls'}})+'\\n')\n"
            "    sys.stdout.flush()\n"
            "    reply = json.loads(sys.stdin.readline())\n"
            "    sys.stdout.write(json.dumps({'jsonrpc':'2.0','id':msg['id'],'result':{'ok': reply['result']['ok']}})+'\\n')\n"
            "    sys.stdout.flush()\n"
        )
        async def approve_handler(method: str, params: dict) -> dict:
            return {"ok": method == "approve" and params.get("cmd") == "ls"}

        rpc = StdioJsonRpcProcess([sys.executable, "-c", script], cwd=tmp_path, on_request=approve_handler)
        try:
            res = await rpc.call("ping", {}, timeout=5.0)
            assert res == {"ok": True}
        finally:
            await rpc.stop()

    asyncio.run(_run())
