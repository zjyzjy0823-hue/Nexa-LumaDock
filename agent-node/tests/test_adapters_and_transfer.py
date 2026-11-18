"""适配器协议映射（Codex/Hermes/OpenCode）与 Core Blob 分块传输集成测试。"""

import asyncio
import base64
import json
import os
from pathlib import Path
import sys

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
import httpx

from agent_node.adapters.codex import CodexAdapter
from agent_node.adapters.hermes import HermesAdapter
from agent_node.adapters.jsonrpc import StdioJsonRpcProcess
from agent_node.adapters.opencode import OpenCodeAdapter
from agent_node.config import canonicalize_roots
from agent_node.crypto_chunks import generate_file_key
from agent_node.transfer import download_and_decrypt_artifact, publish_file_artifact


CODEX_MOCK_SCRIPT = """
import sys, json
for line in sys.stdin:
    if not line.strip():
        continue
    msg = json.loads(line)
    m = msg.get('method')
    mid = msg.get('id')
    if m == 'initialize':
        sys.stdout.write(json.dumps({'jsonrpc': '2.0', 'id': mid, 'result': {'capabilities': {}}}) + '\\n')
    elif m == 'thread/start':
        sys.stdout.write(json.dumps({'jsonrpc': '2.0', 'id': mid, 'result': {'thread': {'id': 'thr-1', 'preview': 'Fix bug'}}}) + '\\n')
    elif m == 'model/list':
        print(json.dumps({'jsonrpc': '2.0', 'id': mid, 'result': {'data': [{'model': 'demo', 'displayName': 'Demo', 'supportedReasoningEfforts': [{'reasoningEffort': 'high'}]}]}}))
    elif m == 'turn/start':
        assert msg['params']['model'] == 'demo'
        assert msg['params']['effort'] == 'high'
        assert any(p.get('type') == 'localImage' and str(p.get('path', '')).endswith('shot.png') for p in msg['params']['input'])
        sys.stdout.write(json.dumps({'jsonrpc': '2.0', 'id': mid, 'result': {'turn': {'id': 'turn-1'}}}) + '\\n')
        sys.stdout.write(json.dumps({'jsonrpc': '2.0', 'method': 'item/reasoning/summaryTextDelta', 'params': {'threadId': 'thr-1', 'delta': 'checking files'}}) + '\\n')
        sys.stdout.write(json.dumps({'jsonrpc': '2.0', 'id': 9001, 'method': 'item/commandExecution/requestApproval', 'params': {'threadId': 'thr-1', 'itemId': 'call-1', 'command': 'pytest -q'}}) + '\\n')
        sys.stdout.flush()
        reply = json.loads(sys.stdin.readline())
        dec = reply.get('result', {}).get('decision', '')
        sys.stdout.write(json.dumps({'jsonrpc': '2.0', 'method': 'item/agentMessage/delta', 'params': {'threadId': 'thr-1', 'delta': f'approved:{dec}'}}) + '\\n')
        sys.stdout.write(json.dumps({'jsonrpc': '2.0', 'method': 'thread/tokenUsage/updated', 'params': {'threadId': 'thr-1', 'turnId': 'turn-1', 'tokenUsage': {'modelContextWindow': 200000, 'total': {'inputTokens': 600, 'cachedInputTokens': 150, 'outputTokens': 90, 'reasoningOutputTokens': 20, 'totalTokens': 690}, 'last': {'inputTokens': 600, 'cachedInputTokens': 150, 'outputTokens': 90, 'reasoningOutputTokens': 20, 'totalTokens': 690}}}}) + '\\n')
        sys.stdout.write(json.dumps({'jsonrpc': '2.0', 'method': 'turn/completed', 'params': {'threadId': 'thr-1', 'turn': {'id': 'turn-1'}}}) + '\\n')
    elif m == 'thread/list':
        sys.stdout.write(json.dumps({'jsonrpc': '2.0', 'id': mid, 'result': {'data': [{'id': 'thr-1', 'preview': 'Fix bug', 'cwd': '.'}]}}) + '\\n')
    sys.stdout.flush()
"""


HERMES_ACP_SCRIPT = """
import sys, json
for line in sys.stdin:
    if not line.strip():
        continue
    msg = json.loads(line)
    m = msg.get('method')
    mid = msg.get('id')
    if m == 'initialize':
        sys.stdout.write(json.dumps({'jsonrpc': '2.0', 'id': mid, 'result': {'protocolVersion': 1}}) + '\\n')
    elif m == 'session/new':
        sys.stdout.write(json.dumps({'jsonrpc': '2.0', 'id': mid, 'result': {'sessionId': 'herm-1'}}) + '\\n')
    elif m == 'session/prompt':
        sys.stdout.write(json.dumps({'jsonrpc': '2.0', 'method': 'session/update', 'params': {'sessionId': 'herm-1', 'update': {'sessionUpdate': 'agent_thought_chunk', 'content': {'text': 'plan step'}}}}) + '\\n')
        sys.stdout.write(json.dumps({'jsonrpc': '2.0', 'method': 'session/update', 'params': {'sessionId': 'herm-1', 'update': {'sessionUpdate': 'tool_call', 'title': 'read_file'}}}) + '\\n')
        sys.stdout.write(json.dumps({'jsonrpc': '2.0', 'id': 77, 'method': 'session/request_permission', 'params': {'sessionId': 'herm-1', 'toolCall': {'toolCallId': 'tc-77', 'title': 'Run shell'}, 'options': [{'optionId': 'opt-once', 'kind': 'allow_once'}, {'optionId': 'opt-always', 'kind': 'allow_always'}, {'optionId': 'opt-no', 'kind': 'reject_once'}]}}) + '\\n')
        sys.stdout.flush()
        reply = json.loads(sys.stdin.readline())
        opt = reply.get('result', {}).get('outcome', {}).get('optionId')
        sys.stdout.write(json.dumps({'jsonrpc': '2.0', 'method': 'session/update', 'params': {'sessionId': 'herm-1', 'update': {'sessionUpdate': 'agent_message_chunk', 'content': {'text': f'choice={opt}'}}}}) + '\\n')
        sys.stdout.write(json.dumps({'jsonrpc': '2.0', 'id': mid, 'result': {'stopReason': 'end_turn', 'usage': {'inputTokens': 240, 'outputTokens': 55}}}) + '\\n')
    sys.stdout.flush()
"""


def test_codex_and_hermes_jsonrpc_adapters(tmp_path):
    async def _run():
        roots = canonicalize_roots([str(tmp_path)])

        # 1. Codex app-server 适配器验证
        codex = CodexAdapter(roots)
        codex._proc = StdioJsonRpcProcess(
            [sys.executable, "-c", CODEX_MOCK_SCRIPT],
            cwd=tmp_path,
            on_notification=codex._on_notification,
            on_request=codex._on_server_request,
        )
        opened = await codex.open_session(cwd=str(tmp_path))
        assert opened["sessionId"] == "thr-1"
        events: list[dict] = []

        async def emit(ev: dict) -> None:
            events.append(ev)

        async def approve(sid: str, cid: str, cmd: str, risk: str) -> str:
            assert cmd == "pytest -q"
            return "allow_once"

        assert await codex.list_models() == [{"id": "demo", "label": "Demo", "efforts": ["high"]}]
        await codex.send_prompt(
            options={"model": "demo", "effort": "high"},
            session_id="thr-1",
            text="run",
            request_id="r-codex",
            emit=emit,
            request_approval=approve,
            attachments=[{"fileName": "shot.png", "mime": "image/png", "localPath": str(tmp_path / "shot.png")}],
        )
        assert any(e["type"] == "ThoughtDelta" and e["text"] == "checking files" for e in events)
        assert any(e["type"] == "TextDelta" and e["text"] == "approved:accept" for e in events)
        codex_usage = next(e for e in events if e["type"] == "TokenUsage")
        assert codex_usage["scope"] == "cumulative"
        assert codex_usage["totalTokens"] == 690
        assert codex_usage["cachedInputTokens"] == 150
        assert codex_usage["lastTotalTokens"] == 690
        assert codex_usage["contextWindow"] == 200000
        assert codex_usage["source"] == "exact"
        assert any(e["type"] == "Completed" for e in events)
        await codex._proc.stop()

        # 2. Hermes ACP 适配器验证
        hermes = HermesAdapter(roots, mode="acp")
        hermes._proc = StdioJsonRpcProcess(
            [sys.executable, "-c", HERMES_ACP_SCRIPT],
            cwd=tmp_path,
            on_notification=hermes._on_acp_update,
            on_request=hermes._on_acp_request,
        )
        h_opened = await hermes.open_session(cwd=str(tmp_path))
        assert h_opened["sessionId"] == "herm-1"
        h_events: list[dict] = []

        async def h_emit(ev: dict) -> None:
            h_events.append(ev)

        async def h_approve(sid: str, cid: str, cmd: str, risk: str) -> str:
            return "allow_session"

        await hermes.send_prompt(session_id="herm-1", text="hi", request_id="r-hermes", emit=h_emit, request_approval=h_approve)
        assert any(e["type"] == "ThoughtDelta" and e["text"] == "plan step" for e in h_events)
        assert any(e["type"] == "ToolCall" and e["name"] == "read_file" for e in h_events)
        assert any(e["type"] == "TextDelta" and e["text"] == "choice=opt-always" for e in h_events)
        hermes_usage = next(e for e in h_events if e["type"] == "TokenUsage")
        assert hermes_usage["inputTokens"] == 240 and hermes_usage["outputTokens"] == 55
        assert hermes_usage["totalTokens"] == 295
        assert any(e["type"] == "Completed" for e in h_events)
        await hermes._proc.stop()

    asyncio.run(_run())


def test_opencode_http_sse_adapter(tmp_path):
    async def _run():
        roots = canonicalize_roots([str(tmp_path)])
        fake_oc = FastAPI()
        perm_responses: list[str] = []

        @fake_oc.get("/session")
        def _list():
            return [{"id": "oc-1", "title": "OC Demo", "directory": str(tmp_path)}]

        @fake_oc.post("/session")
        def _create():
            return {"id": "oc-1", "title": "OC Demo"}

        @fake_oc.post("/session/{sid}/prompt_async")
        async def _prompt(sid: str, request: Request):
            body = await request.json()
            assert body["model"] == {"providerID": "local", "modelID": "demo"}
            assert body["variant"] == "high"
            assert any(p.get("type") == "file" and p.get("filename") == "diff.patch" and str(p.get("url", "")).startswith("file://") for p in body["parts"])
            return {"accepted": True}

        @fake_oc.post("/session/{sid}/permissions/{pid}")
        async def _perm(sid: str, pid: str, request: Request):
            body = await request.json()
            perm_responses.append(body.get("response", ""))
            return {"ok": True}

        @fake_oc.get("/event")
        async def _sse():
            async def gen():
                yield f"data: {json.dumps({'type': 'permission.asked', 'properties': {'sessionID': 'oc-1', 'id': 'perm-9', 'title': 'Edit app.py'}})}\n\n"
                yield f"data: {json.dumps({'type': 'message.part.updated', 'properties': {'part': {'sessionID': 'oc-1', 'type': 'text'}, 'delta': 'patched!'}})}\n\n"
                yield f"data: {json.dumps({'type': 'message.updated', 'properties': {'info': {'id': 'msg-oc-1', 'sessionID': 'oc-1', 'role': 'assistant', 'modelID': 'demo', 'tokens': {'input': 820, 'output': 140, 'reasoning': 30, 'cache': {'read': 400, 'write': 0}}}}})}\n\n"
                yield f"data: {json.dumps({'type': 'session.idle', 'properties': {'sessionID': 'oc-1'}})}\n\n"

            return StreamingResponse(gen(), media_type="text/event-stream")

        adapter = OpenCodeAdapter(roots, serve_url="http://opencode.local")
        adapter._client = lambda: httpx.AsyncClient(  # type: ignore[method-assign]
            transport=httpx.ASGITransport(app=fake_oc),
            base_url="http://opencode.local",
        )
        probe = await adapter.probe()
        assert probe.status == "ready"
        sess = await adapter.open_session(cwd=str(tmp_path))
        assert sess["sessionId"] == "oc-1"

        events: list[dict] = []

        async def emit(ev: dict) -> None:
            events.append(ev)

        async def approve(sid: str, cid: str, cmd: str, risk: str) -> str:
            return "allow_once"

        await adapter.send_prompt(
            options={"model": "local/demo", "effort": "high"},
            session_id="oc-1",
            text="patch",
            request_id="r-oc",
            emit=emit,
            request_approval=approve,
            attachments=[{"fileName": "diff.patch", "mime": "text/x-diff", "localPath": str(tmp_path / "diff.patch")}],
        )
        assert perm_responses == ["once"]
        assert any(e["type"] == "TextDelta" and e["text"] == "patched!" for e in events)
        oc_usage = next(e for e in events if e["type"] == "TokenUsage")
        assert oc_usage["messageId"] == "msg-oc-1"
        assert oc_usage["inputTokens"] == 820 and oc_usage["cachedInputTokens"] == 400
        assert oc_usage["outputTokens"] == 140 and oc_usage["reasoningTokens"] == 30
        assert oc_usage["totalTokens"] == 990
        assert oc_usage["source"] == "exact"
        assert any(e["type"] == "Completed" for e in events)

    asyncio.run(_run())


def test_e2e_publish_and_download_against_backend_app(tmp_path, monkeypatch):
    # 使用独立临时库加载真实 Studiolo Core FastAPI 应用，验证 Wave 1 + Wave 2 分块 E2EE 端到端链路
    backend_root = Path(__file__).resolve().parents[2] / "backend"
    if str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'core.db').as_posix()}")
    monkeypatch.setenv("STUDIOLO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("STUDIOLO_MODE", "local")
    monkeypatch.setenv("STUDIOLO_LOCAL_WORKSTATION", "false")
    monkeypatch.setenv("JWT_SECRET", "t" * 64)

    from alembic import command
    from alembic.config import Config
    from fastapi.testclient import TestClient

    cfg = Config(str(backend_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_root / "migrations"))
    cfg.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"])
    command.upgrade(cfg, "head")

    from app.main import app

    with TestClient(app) as tc:
        reg = tc.post("/api/v1/auth/register", json={"username": "fleetuser", "password": "password-1234"})
        assert reg.status_code == 201
        user_jwt = reg.json()["access_token"]
        node_reg = tc.post(
            "/api/v1/fleet/nodes",
            headers={"Authorization": f"Bearer {user_jwt}"},
            json={"name": "Mac-Mini", "platform": "macos"},
        )
        assert node_reg.status_code == 201
        node_token = node_reg.json()["nodeToken"]

        node_b_reg = tc.post(
            "/api/v1/fleet/nodes",
            headers={"Authorization": f"Bearer {user_jwt}"},
            json={"name": "Windows-WS", "platform": "windows"},
        )
        assert node_b_reg.status_code == 201
        node_b_token = node_b_reg.json()["nodeToken"]

    async def _transfer():
        src_dir = tmp_path / "allowed"
        src_dir.mkdir()
        roots = canonicalize_roots([str(src_dir)])
        src_file = src_dir / "artifact.bin"
        raw_payload = (b"Studiolo E2EE Payload\n" * 600) + bytes(range(256))
        src_file.write_bytes(raw_payload)
        key = generate_file_key()

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://127.0.0.1:48197",
        ) as client:
            ref = await publish_file_artifact(
                core_url="http://127.0.0.1:48197",
                node_token=node_token,
                file_path=src_file,
                allowed_roots=roots,
                key=key,
                mime="application/octet-stream",
                chunk_size=4096,
                client=client,
            )
            assert ref["chunkCount"] >= 3
            assert ref["keyB64"]

            ep_res = await client.get(
                f"http://127.0.0.1:48197/api/v1/fleet/artifacts/{ref['artifactId']}/endpoints",
                headers={"Authorization": f"Bearer {node_b_token}"},
            )
            assert ep_res.status_code == 200
            ep_payload = ep_res.json()
            # 核实 Core 响应与数据库中绝不存有 E2EE 密钥或明文
            assert ref["keyB64"] not in json.dumps(ep_payload)
            assert ref["keyB64"].encode("utf-8") not in (tmp_path / "core.db").read_bytes()
            assert b"Studiolo E2EE Payload" not in (tmp_path / "core.db").read_bytes()

            dest_file = src_dir / "downloaded.bin"
            out = await download_and_decrypt_artifact(
                core_url="http://127.0.0.1:48197",
                node_token=node_b_token,
                artifact_ref=ref,
                destination=dest_file,
                allowed_roots=roots,
                client=client,
            )
            assert out.read_bytes() == raw_payload

    asyncio.run(_transfer())
