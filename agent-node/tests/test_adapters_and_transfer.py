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
import pytest

from agent_node.adapters.codex import CodexAdapter
from agent_node.adapters.hermes import HermesAdapter
from agent_node.adapters.jsonrpc import JsonRpcError, StdioJsonRpcProcess
from agent_node.adapters.opencode import OpenCodeAdapter
from agent_node.config import PathOutsideAllowedRootsError, canonicalize_roots
from agent_node.crypto_chunks import generate_file_key
from agent_node.transfer import download_and_decrypt_artifact, publish_file_artifact


def test_codex_routes_early_and_concurrent_events_to_their_own_turn(tmp_path):
    async def run():
        adapter = CodexAdapter((tmp_path,))
        events = {"a": [], "b": []}
        accepted = {thread: asyncio.Event() for thread in events}

        class Process:
            async def call(self, method, params):
                assert method == "turn/start"
                thread = params["threadId"]
                await adapter._on_notification("item/agentMessage/delta", {
                    "threadId": thread, "turnId": "turn-" + thread, "delta": "early-" + thread,
                })
                return {"turn": {"id": "turn-" + thread}}

        async def ensure():
            return Process()

        async def send(thread):
            async def emit(event):
                events[thread].append(event)
                if event["type"] == "Accepted":
                    accepted[thread].set()
            await adapter.send_prompt(session_id=thread, text="Hello", request_id="req-" + thread,
                                      emit=emit, request_approval=lambda *_: asyncio.sleep(0, result="deny"))

        adapter._ensure_proc = ensure
        a = asyncio.create_task(send("a"))
        b = asyncio.create_task(send("b"))
        await asyncio.wait_for(asyncio.gather(*(signal.wait() for signal in accepted.values())), 2)
        for thread in ("b", "a"):
            await adapter._on_notification("turn/completed", {"threadId": thread, "turn": {"id": "old-turn"}})
            await adapter._on_notification("item/started", {"threadId": thread, "turnId": "turn-" + thread,
                                           "item": {"type": "commandExecution", "id": "same-call", "command": thread}})
            await adapter._on_notification("turn/completed", {"threadId": thread, "turn": {"id": "turn-" + thread}})
        await asyncio.wait_for(asyncio.gather(a, b), 2)
        for thread, captured in events.items():
            assert [evt["type"] for evt in captured] == ["Accepted", "TextDelta", "ToolCallUpdate", "Completed"]
            assert all((evt["sessionId"], evt["runId"], evt["requestId"]) == (thread, "turn-" + thread, "req-" + thread)
                       for evt in captured)
            assert captured[1]["text"] == "early-" + thread

    asyncio.run(run())


def test_codex_resumes_unloaded_thread_and_retries_prompt_once(tmp_path):
    async def run():
        adapter = CodexAdapter((tmp_path,))
        calls = []
        events = []

        class Process:
            async def call(self, method, params):
                calls.append((method, params))
                if method == "thread/read":
                    assert params == {"threadId": "existing", "includeTurns": False}
                    return {"thread": {"id": "existing", "cwd": str(tmp_path)}}
                if method == "thread/resume":
                    assert params == {"threadId": "existing", "cwd": str(tmp_path),
                                      "approvalPolicy": "on-request", "excludeTurns": True}
                    return {"thread": {"id": "existing"}, "model": "resumed-model"}
                if len(calls) == 1:
                    raise JsonRpcError(-32600, "thread not found: existing")
                assert method == "turn/start" and params["model"] == "resumed-model"
                assert params["approvalPolicy"] == "never"
                assert params["input"] == calls[0][1]["input"]
                await adapter._on_notification("turn/completed", {"threadId": "existing", "turn": {"id": "turn-1"}})
                return {"turn": {"id": "turn-1"}}

        async def ensure():
            return Process()

        async def emit(event):
            events.append(event)

        adapter._ensure_proc = ensure
        await adapter.send_prompt(session_id="existing", text="QA", request_id="req", emit=emit,
                                  request_approval=lambda *_: asyncio.sleep(0, result="deny"),
                                  attachments=[{"mime": "image/png", "localPath": str(tmp_path / "shot.png")}],
                                  options={"readOnly": "true"})
        assert [method for method, _ in calls] == ["turn/start", "thread/read", "thread/resume", "turn/start"]
        assert [event["type"] for event in events] == ["Accepted", "Completed"]

    asyncio.run(run())


def test_codex_history_pages_and_falls_back_to_local_rollout(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    path = tmp_path / "sessions" / "rollout-qa-existing.jsonl"
    path.parent.mkdir()
    user = {"type": "user_message", "message": "first"}
    assistant = {"type": "agent_message", "message": "reply"}
    path.write_text("\n".join(json.dumps(row) for row in [
        {"type": "session_meta", "payload": {"id": "existing", "cwd": str(tmp_path)}},
        *({"type": "event_msg", "payload": event} for event in (
            {"type": "task_started"}, user, assistant,
            {"type": "item_completed", "item": {"type": "UserMessage", "content": [{"text": "first"}]}},
            {"type": "item_completed", "item": {"type": "AgentMessage", "content": [{"text": "reply"}]}},
        )),
    ]), encoding="utf-8")

    async def run():
        adapter = CodexAdapter((tmp_path,))
        path_for_metadata = path
        page_available = True

        class Process:
            async def call(self, method, params):
                if method == "thread/turns/list" and page_available:
                    assert params["itemsView"] == "full" and params["sortDirection"] == "desc"
                    older = params.get("cursor") == "next"
                    return {
                        "data": [{"items": [{"type": "agentMessage", "text": "older" if older else "newer"}]}],
                        "nextCursor": None if older else "next",
                    }
                if method == "thread/read" and not params["includeTurns"]:
                    return {"thread": {"id": "existing", "path": str(path_for_metadata), "cwd": str(tmp_path)}}
                raise JsonRpcError(-32601, "list_turns is not supported yet")

        async def ensure():
            return Process()

        adapter._ensure_proc = ensure
        assert [msg["text"] for msg in await adapter.get_history(session_id="existing", limit=2)] == ["older", "newer"]
        page_available = False
        assert await adapter.get_history(session_id="existing") == [
            {"role": "user", "text": "first"}, {"role": "assistant", "text": "reply"},
        ]
        path.unlink()
        assert await adapter.get_history(session_id="existing") == []
        path_for_metadata = tmp_path / path.name
        with pytest.raises(PathOutsideAllowedRootsError):
            await adapter.get_history(session_id="existing")

    asyncio.run(run())


def test_opencode_v1_recovers_short_reply_once_and_ignores_old_history(tmp_path):
    async def run():
        calls = []
        events = []
        old = {"info": {"id": "old", "role": "assistant", "parentID": "old-user", "time": {"completed": 1}},
               "parts": [{"type": "text", "text": "OLD"}]}

        def respond(request):
            path = request.url.path
            calls.append(path)
            if path == "/session":
                return httpx.Response(200, json=[])
            if path == "/session/session-1":
                return httpx.Response(200, json={"id": "session-1", "directory": str(tmp_path)})
            if path == "/event":
                events = [
                    {"type": "message.part.updated", "properties": {"part": {
                        "id": "p1", "messageID": "new", "sessionID": "session-1", "type": "text", "text": "",
                    }}},
                    {"type": "message.part.delta", "properties": {
                        "partID": "p1", "messageID": "new", "sessionID": "session-1", "field": "text", "delta": "Hel",
                    }},
                ]
                return httpx.Response(200, headers={"content-type": "text/event-stream"},
                                      text="".join("data: " + json.dumps(event) + "\n\n" for event in events))
            if path == "/session/session-1/prompt_async":
                assert request.url.params["directory"] == str(tmp_path)
                assert "/event" in calls
                return httpx.Response(204)
            if path == "/session/session-1/message":
                if "/session/session-1/prompt_async" not in calls:
                    return httpx.Response(200, json=[old])
                return httpx.Response(200, json=[old,
                    {"info": {"id": "user", "role": "user"}, "parts": [{"type": "text", "text": "Go"}]},
                    {"info": {"id": "new", "role": "assistant", "parentID": "user", "time": {"completed": 2}, "finish": "stop"},
                     "parts": [{"id": "p1", "type": "text", "text": "Hello"}]},
                ])
            raise AssertionError(path)

        adapter = OpenCodeAdapter((tmp_path,))
        adapter._client = lambda: httpx.AsyncClient(transport=httpx.MockTransport(respond))
        await asyncio.wait_for(adapter.send_prompt(
            session_id="session-1", text="Go", request_id="req", emit=lambda event: events.append(event) or asyncio.sleep(0),
            request_approval=lambda *_: asyncio.sleep(0, result="deny"),
        ), 3)
        assert calls.count("/session/session-1/prompt_async") == 1
        assert [e["type"] for e in events] == ["Accepted", "TextDelta", "TextDelta", "Completed"]
        assert "".join(e.get("text", "") for e in events) == "Hello"

    asyncio.run(run())


def test_opencode_merges_go_models_and_falls_back_from_html_mcp(tmp_path):
    async def run():
        def respond(request):
            path = request.url.path
            if path == "/api/mcp":
                return httpx.Response(200, headers={"content-type": "text/html"}, text="<html></html>")
            if path == "/mcp":
                return httpx.Response(200, json={"local": {"status": "connected"}})
            if path == "/provider":
                return httpx.Response(200, json={"connected": ["opencode-go"], "all": [{
                    "id": "opencode-go", "models": {"chat": {"name": "Go Chat"}},
                }]})
            if path == "/api/model":
                return httpx.Response(200, json={"data": [{"providerID": "opencode", "modelID": "chat"},
                                                        {"providerID": "opencode-go", "modelID": "chat"}]})
            raise AssertionError(path)

        adapter = OpenCodeAdapter((tmp_path,))
        adapter._client = lambda: httpx.AsyncClient(transport=httpx.MockTransport(respond))
        assert await adapter.list_mcp_servers() == [{"name": "local", "status": "connected"}]
        models = await adapter.list_models()
        assert [model["id"] for model in models] == ["opencode-go/chat", "opencode/chat"]
        assert models[0]["label"] == "opencode-go · Go Chat"

    asyncio.run(run())


def test_codex_quota_queries_the_official_rpc_once_and_filters_response(tmp_path, monkeypatch):
    calls = []

    class FixtureProcess:
        async def call(self, method, *, timeout):
            calls.append(method)
            return {
                "rateLimits": {"primary": {"usedPercent": 90}},
                "rateLimitsByLimitId": {"codex": {"primary": {"usedPercent": 25, "windowDurationMins": 300,
                                                             "resetsAt": 1795000000, "accountEmail": "sentinel@example.invalid"},
                                                   "secondary": {"usedPercent": 100}}},
                "credits": {"secret": "do-not-export"},
            }

    async def run():
        adapter = CodexAdapter((tmp_path,))

        async def ensure():
            return FixtureProcess()

        monkeypatch.setattr(adapter, "_ensure_proc", ensure)
        first, second = await asyncio.gather(adapter.read_subscription_quota(), adapter.read_subscription_quota())
        assert calls == ["account/rateLimits/read"]
        assert first == second and first["status"] == "ready"
        assert first["windows"] == [
            {"group": "Codex", "kind": "primary", "remainingPercent": 75, "windowMinutes": 300, "resetsAt": 1795000000},
            {"group": "Codex", "kind": "secondary", "remainingPercent": 0, "windowMinutes": None, "resetsAt": None},
        ]
        assert "sentinel" not in json.dumps(first) and "do-not-export" not in json.dumps(first)

    asyncio.run(run())


def test_opencode_go_quota_from_service_and_explicit_key(tmp_path, monkeypatch):
    async_client = httpx.AsyncClient
    paths = []

    def handle(request):
        paths.append(request.url.path)
        if request.url.host == "opencode.ai":
            assert request.headers["Authorization"] == "Bearer test-go-key"
            return httpx.Response(200, json={"usage": {
                "rolling": {"percent": 20, "status": "ok", "resetsAt": "2026-11-20T05:00:00Z"},
                "weekly": {"percent": 30, "status": "rate-limited"},
                "monthly": {"percent": 50},
            }})
        assert "Authorization" not in request.headers
        return httpx.Response(200, json={"data": {"workspace": {"id": "hidden-account"}, "go": {
            "rolling": {"percent": 20, "limited": False, "resetsAt": 1795150800000},
            "weekly": {"percent": 30, "limited": True},
            "monthly": {"percent": 50},
        }}})

    def mock_client(**kwargs):
        return async_client(transport=httpx.MockTransport(handle), **kwargs)

    async def run():
        monkeypatch.setattr(httpx, "AsyncClient", mock_client)
        monkeypatch.delenv("OPENCODE_GO_API_KEY", raising=False)
        monkeypatch.delenv("OPENCODE_SERVER_PASSWORD", raising=False)
        service = OpenCodeAdapter((tmp_path,), serve_url="http://127.0.0.1:4096")
        service_data = await service.read_subscription_quota()
        monkeypatch.setenv("OPENCODE_GO_API_KEY", "test-go-key")
        direct = OpenCodeAdapter((tmp_path,), serve_url="http://127.0.0.1:4096")
        direct_data, cached = await asyncio.gather(direct.read_subscription_quota(), direct.read_subscription_quota())
        assert paths == ["/api/experimental/usage/limits", "/zen/go/v1/usage"]
        assert service_data["status"] == direct_data["status"] == "ready"
        assert direct_data["windows"] == cached["windows"] == service_data["windows"]
        assert [item["remainingPercent"] for item in direct_data["windows"]] == [80, 0, 50]
        assert direct_data["windows"][2]["kind"] == "monthly"
        assert "hidden-account" not in json.dumps(service_data) and "test-go-key" not in json.dumps(direct_data)

    asyncio.run(run())


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
        sys.stdout.write(json.dumps({'jsonrpc': '2.0', 'method': 'turn/plan/updated', 'params': {'threadId': 'thr-1', 'plan': [{'step': 'Inspect code', 'status': 'completed'}, {'step': 'Run tests', 'status': 'inProgress'}]}}) + '\\n')
        sys.stdout.write(json.dumps({'jsonrpc': '2.0', 'method': 'item/started', 'params': {'threadId': 'thr-1', 'item': {'id': 'call-1', 'type': 'commandExecution', 'command': 'pytest -q'}}}) + '\\n')
        sys.stdout.write(json.dumps({'jsonrpc': '2.0', 'id': 9001, 'method': 'item/commandExecution/requestApproval', 'params': {'threadId': 'thr-1', 'itemId': 'call-1', 'command': 'pytest -q'}}) + '\\n')
        sys.stdout.flush()
        reply = json.loads(sys.stdin.readline())
        dec = reply.get('result', {}).get('decision', '')
        sys.stdout.write(json.dumps({'jsonrpc': '2.0', 'method': 'item/commandExecution/outputDelta', 'params': {'threadId': 'thr-1', 'itemId': 'call-1', 'delta': '12 passed\\n'}}) + '\\n')
        sys.stdout.write(json.dumps({'jsonrpc': '2.0', 'method': 'item/completed', 'params': {'threadId': 'thr-1', 'item': {'id': 'call-1', 'type': 'commandExecution', 'command': 'pytest -q', 'status': 'completed', 'exitCode': 0, 'aggregatedOutput': '12 passed\\n'}}}) + '\\n')
        sys.stdout.write(json.dumps({'jsonrpc': '2.0', 'method': 'turn/diff/updated', 'params': {'threadId': 'thr-1', 'diff': 'diff --git a/app.py b/app.py\\n--- a/app.py\\n+++ b/app.py\\n@@ -1 +1 @@\\n-old\\n+new\\n'}}) + '\\n')
        sys.stdout.write(json.dumps({'jsonrpc': '2.0', 'method': 'item/agentMessage/delta', 'params': {'threadId': 'thr-1', 'delta': f'approved:{dec}'}}) + '\\n')
        sys.stdout.write(json.dumps({'jsonrpc': '2.0', 'method': 'thread/tokenUsage/updated', 'params': {'threadId': 'thr-1', 'turnId': 'turn-1', 'tokenUsage': {'modelContextWindow': 200000, 'total': {'inputTokens': 600, 'cachedInputTokens': 150, 'outputTokens': 90, 'reasoningOutputTokens': 20, 'totalTokens': 690}, 'last': {'inputTokens': 600, 'cachedInputTokens': 150, 'outputTokens': 90, 'reasoningOutputTokens': 20, 'totalTokens': 690}}}}) + '\\n')
        sys.stdout.write(json.dumps({'jsonrpc': '2.0', 'method': 'turn/completed', 'params': {'threadId': 'thr-1', 'turn': {'id': 'turn-1'}}}) + '\\n')
    elif m == 'thread/read':
        sys.stdout.write(json.dumps({'jsonrpc': '2.0', 'id': mid, 'result': {'thread': {'id': 'thr-1', 'turns': [{'items': [{'type': 'userMessage', 'content': [{'text': 'run'}]}, {'type': 'reasoning', 'summary': ['checking files']}, {'type': 'commandExecution', 'id': 'call-1', 'command': 'pytest -q', 'status': 'completed', 'aggregatedOutput': '12 passed'}, {'type': 'agentMessage', 'text': 'approved:accept'}]}]}}}) + '\\n')
    elif m == 'thread/turns/list':
        print(json.dumps({'jsonrpc': '2.0', 'id': mid, 'error': {'code': -32601, 'message': 'Method not found'}}))
    elif m == 'thread/name/set':
        sys.stdout.write(json.dumps({'jsonrpc': '2.0', 'id': mid, 'result': {}}) + '\\n')
    elif m == 'thread/compact/start':
        sys.stdout.write(json.dumps({'jsonrpc': '2.0', 'id': mid, 'result': {}}) + '\\n')
    elif m == 'thread/list':
        sys.stdout.write(json.dumps({'jsonrpc': '2.0', 'id': mid, 'result': {'data': [{'id': 'thr-1', 'preview': 'Fix bug', 'cwd': '.'}]}}) + '\\n')
    sys.stdout.flush()
"""


HERMES_ACP_SCRIPT = """
import sys, json, os, time
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
    elif m == 'session/list':
        cursor = msg['params'].get('cursor')
        sid = 'herm-older' if cursor == 'herm-1' else 'herm-1'
        result = {'sessions': [{'sessionId': sid, 'cwd': os.getcwd(), 'title': 'Hermes private notes',
                                'updatedAt': '2026-11-19T16:00:00Z'}]}
        if not cursor:
            result['nextCursor'] = sid
        print(json.dumps({'jsonrpc': '2.0', 'id': mid, 'result': result}))
    elif m == 'session/load':
        sid = msg['params']['sessionId']
        assert msg['params']['cwd'] == os.getcwd()
        print(json.dumps({'jsonrpc': '2.0', 'id': mid, 'result': {}}), flush=True)
        time.sleep(0.02)
        for update in [
            {'session_update': 'user_message_chunk', 'content': {'type': 'text', 'text': 'Older question'}},
            {'session_update': 'agent_thought_chunk', 'content': {'type': 'text', 'text': 'check'}},
            {'session_update': 'tool_call', 'tool_call_id': 'old-tool', 'title': 'read_file'},
            {'session_update': 'tool_call_update', 'tool_call_id': 'old-tool', 'status': 'completed', 'raw_output': 'ok'},
            {'session_update': 'agent_message_chunk', 'content': {'type': 'text', 'text': 'Older answer'}},
        ]:
            print(json.dumps({'jsonrpc': '2.0', 'method': 'session/update', 'params': {
                'session_id': sid, 'update': update,
            }}))
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
        assert any(e["type"] == "ToolCallUpdate" and e.get("callId") == "call-1" and e.get("status") == "running" for e in events)
        assert any(e["type"] == "ToolCallUpdate" and e.get("callId") == "call-1" and e.get("deltaOutput") == "12 passed\n" for e in events)
        done_tool = next(e for e in events if e["type"] == "ToolCallUpdate" and e.get("status") == "completed")
        assert done_tool["output"] == "12 passed\n" and isinstance(done_tool["durationMs"], int)
        todo_ev = next(e for e in events if e["type"] == "TodoUpdated")
        assert todo_ev["items"] == [
            {"id": "0", "content": "Inspect code", "status": "completed"},
            {"id": "1", "content": "Run tests", "status": "in_progress"},
        ]
        diff_ev = next(e for e in events if e["type"] == "DiffSnapshot")
        assert diff_ev["perTurn"] is True and diff_ev["summary"] == {"filesChanged": 1, "additions": 1, "deletions": 1}
        assert diff_ev["files"][0]["path"] == "app.py" and "+new" in diff_ev["files"][0]["patch"]
        hist = await codex.get_history(session_id="thr-1")
        assert len(hist) == 2 and hist[1]["thought"] == "checking files"
        assert hist[1]["toolCalls"][0]["callId"] == "call-1"
        assert (await codex.rename_session(session_id="thr-1", title="New Title"))["title"] == "New Title"
        assert (await codex.compact_session(session_id="thr-1"))["supported"] is True
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
        listed = await hermes.list_sessions(limit=2)
        assert [entry["sessionId"] for entry in listed] == ["herm-1", "herm-older"]
        assert listed[1]["provider"] == "hermes" and listed[1]["cwd"] == str(tmp_path)
        assert listed[1]["updatedAt"] == "2026-11-19T16:00:00Z"
        assert await hermes.get_history(session_id="herm-older") == [
            {"role": "user", "text": "Older question"},
            {"role": "assistant", "text": "Older answer", "thought": "check",
             "parts": [{"type": "thought", "text": "check"}, {"type": "tool", "callId": "old-tool"},
                       {"type": "text", "text": "Older answer"}],
             "toolCalls": [{"callId": "old-tool", "name": "read_file", "status": "completed", "output": "ok"}]},
        ]
        outside = hermes._session_summaries([{"sessionId": "outside", "title": "Personal chat", "cwd": str(tmp_path.parent)}])
        assert outside[0]["title"] == "Personal chat" and outside[0]["cwd"] == ""
        with pytest.raises(PathOutsideAllowedRootsError):
            await hermes.get_history(session_id="outside")
        h_events: list[dict] = []

        async def h_emit(ev: dict) -> None:
            h_events.append(ev)

        async def h_approve(sid: str, cid: str, cmd: str, risk: str) -> str:
            history = await hermes.get_history(session_id=sid)
            assert history[0] == {"role": "user", "text": "hi", "runId": "r-hermes"}
            assert history[1]["thought"] == "plan step"
            assert history[1]["toolCalls"][0]["status"] == "running"
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

        @fake_oc.get("/session/{sid}")
        def _details(sid: str):
            return {"id": sid, "directory": str(tmp_path)}

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

            for key_b64 in (ref["keyB64"], ref["keyB64"].rstrip("=")):
                out = await download_and_decrypt_artifact(
                    core_url="http://127.0.0.1:48197",
                    node_token=node_b_token,
                    artifact_ref={**ref, "keyB64": key_b64},
                    destination=src_dir / "downloaded.bin",
                    allowed_roots=roots,
                    client=client,
                )
                assert out.read_bytes() == raw_payload

    asyncio.run(_transfer())


def test_opencode_sse_dedup_user_echo_tools_and_history(tmp_path):
    async def _run():
        roots = canonicalize_roots([str(tmp_path)])
        fake_oc = FastAPI()
        renamed_titles: list[str] = []
        deleted_ids: list[str] = []

        @fake_oc.post("/session")
        def _create():
            return {"id": "oc-rich", "title": "OC Rich"}

        @fake_oc.get("/session/{sid}")
        def _details(sid: str):
            return {"id": sid, "directory": str(tmp_path)}

        @fake_oc.post("/session/{sid}/prompt_async")
        async def _prompt(sid: str):
            return {"accepted": True}

        @fake_oc.patch("/session/{sid}")
        async def _rename(sid: str, request: Request):
            body = await request.json()
            renamed_titles.append(body.get("title", ""))
            return {"id": sid, "title": body.get("title", "")}

        @fake_oc.delete("/session/{sid}")
        async def _delete(sid: str):
            deleted_ids.append(sid)
            return {"ok": True}

        @fake_oc.post("/session/{sid}/summarize")
        async def _compact(sid: str):
            return {"ok": True}

        @fake_oc.get("/session/{sid}/message")
        async def _messages(sid: str):
            return [
                {"info": {"id": "m-u", "role": "user"}, "parts": [{"type": "text", "text": "fix tests"}]},
                {
                    "info": {"id": "m-a", "role": "assistant"},
                    "parts": [
                        {"type": "reasoning", "text": "check logs"},
                        {
                            "type": "tool",
                            "callID": "tc-1",
                            "tool": "bash",
                            "state": {
                                "status": "completed",
                                "title": "Run pytest",
                                "input": {"command": "pytest"},
                                "output": "ok",
                            },
                        },
                        {"type": "text", "text": "All fixed."},
                    ],
                },
            ]

        @fake_oc.get("/event")
        async def _sse():
            async def gen():
                # 1. user 回显应被 role 与正文去重过滤
                yield f"data: {json.dumps({'type': 'message.updated', 'properties': {'info': {'id': 'm-user-1', 'sessionID': 'oc-rich', 'role': 'user'}}})}\n\n"
                yield f"data: {json.dumps({'type': 'message.part.updated', 'properties': {'part': {'id': 'p-u1', 'messageID': 'm-user-1', 'sessionID': 'oc-rich', 'type': 'text', 'text': 'fix tests'}}})}\n\n"
                yield f"data: {json.dumps({'type': 'message.part.updated', 'properties': {'part': {'id': 'p-u2', 'messageID': 'm-u-unknown', 'sessionID': 'oc-rich', 'type': 'text', 'text': 'fix tests'}}})}\n\n"
                # 2. reasoning & text 混用累计快照和增量 delta 时不得重复
                yield f"data: {json.dumps({'type': 'message.updated', 'properties': {'info': {'id': 'm-asst-1', 'sessionID': 'oc-rich', 'role': 'assistant'}}})}\n\n"
                yield f"data: {json.dumps({'type': 'message.part.updated', 'properties': {'part': {'id': 'p-r1', 'messageID': 'm-asst-1', 'sessionID': 'oc-rich', 'type': 'reasoning', 'text': 'Think '}}})}\n\n"
                yield f"data: {json.dumps({'type': 'message.part.updated', 'properties': {'part': {'id': 'p-r1', 'messageID': 'm-asst-1', 'sessionID': 'oc-rich', 'type': 'reasoning', 'text': 'Think hard'}}})}\n\n"
                # 3. tool part & todowrite -> ToolCallUpdate + TodoUpdated
                yield f"data: {json.dumps({'type': 'message.part.updated', 'properties': {'part': {'id': 'p-t1', 'messageID': 'm-asst-1', 'sessionID': 'oc-rich', 'type': 'tool', 'callID': 'call-todo', 'tool': 'todowrite', 'state': {'status': 'completed', 'input': {'todos': [{'id': '1', 'content': 'Run suite', 'status': 'in_progress'}]}, 'output': 'saved'}}}})}\n\n"
                yield f"data: {json.dumps({'type': 'message.part.updated', 'properties': {'part': {'id': 'p-tx1', 'messageID': 'm-asst-1', 'sessionID': 'oc-rich', 'type': 'text', 'text': 'Hello '}}})}\n\n"
                yield f"data: {json.dumps({'type': 'message.part.updated', 'properties': {'part': {'id': 'p-tx1', 'messageID': 'm-asst-1', 'sessionID': 'oc-rich', 'type': 'text', 'text': 'Hello world'}, 'delta': 'world'}})}\n\n"
                yield f"data: {json.dumps({'type': 'session.idle', 'properties': {'sessionID': 'oc-rich'}})}\n\n"

            return StreamingResponse(gen(), media_type="text/event-stream")

        adapter = OpenCodeAdapter(roots, serve_url="http://opencode.local")
        adapter._client = lambda: httpx.AsyncClient(  # type: ignore[method-assign]
            transport=httpx.ASGITransport(app=fake_oc),
            base_url="http://opencode.local",
        )
        await adapter.open_session(cwd=str(tmp_path))
        events: list[dict] = []
        await adapter.send_prompt(
            session_id="oc-rich",
            text="fix tests",
            request_id="r-rich",
            emit=lambda ev: events.append(ev) or asyncio.sleep(0),
            request_approval=lambda *_: asyncio.sleep(0, result="allow_once"),
        )
        combined_text = "".join(e["text"] for e in events if e["type"] == "TextDelta")
        combined_thought = "".join(e["text"] for e in events if e["type"] == "ThoughtDelta")
        assert combined_text == "Hello world"
        assert combined_thought == "Think hard"
        assert any(e["type"] == "ToolCallUpdate" and e["callId"] == "call-todo" and e["status"] == "completed" for e in events)
        assert any(e["type"] == "TodoUpdated" and e["items"][0]["content"] == "Run suite" for e in events)

        hist = await adapter.get_history(session_id="oc-rich")
        assert hist[0] == {"role": "user", "text": "fix tests"}
        assert hist[1]["thought"] == "check logs"
        assert hist[1]["toolCalls"][0]["name"] == "bash"
        assert hist[1]["text"] == "All fixed."

        assert (await adapter.rename_session(session_id="oc-rich", title="Renamed OC"))["title"] == "Renamed OC"
        assert renamed_titles == ["Renamed OC"]
        assert (await adapter.compact_session(session_id="oc-rich"))["supported"] is True
        await adapter.delete_session(session_id="oc-rich")
        assert deleted_ids == ["oc-rich"]

    asyncio.run(_run())


def test_opencode_v2_protocol_adapter(tmp_path):
    async def _run():
        project = tmp_path / "project"
        project.mkdir()
        roots = canonicalize_roots([str(project)])
        fake_v2 = FastAPI()
        selected_models: list[dict] = []
        perm_decisions: list[str] = []
        history_requests: list[str] = []

        @fake_v2.get("/api/session")
        def _v2_list():
            return {"data": [
                {"id": "ses-outside", "location": {"directory": str(tmp_path / "project-other")}},
                {"id": "ses-unknown", "title": "Unknown workspace"},
                {"id": "ses-v2", "title": "V2 Demo", "location": {"directory": str(project)}},
            ]}

        @fake_v2.get("/api/session/{sid}")
        def _v2_details(sid: str):
            directory = project if sid == "ses-v2" else tmp_path / "project-other"
            return {"data": {"id": sid, "location": {"directory": str(directory)}}}

        @fake_v2.post("/api/session")
        async def _v2_create(request: Request):
            body = await request.json()
            assert body["location"]["directory"] == str(project.resolve())
            return {"data": {"id": "ses-v2", "title": "New V2"}}

        @fake_v2.get("/api/model")
        def _v2_models():
            return {
                "data": [
                    {
                        "id": "deepseek-v4.1-flash",
                        "modelID": "deepseek-v4.1-flash",
                        "providerID": "opencode-go",
                        "type": "chat",
                        "name": "DeepSeek V4.1 Flash 1017",
                        "enabled": True,
                        "variants": [{"id": "low"}, {"id": "high"}],
                        "limit": {"context": 1000000},
                    }
                ]
            }

        @fake_v2.post("/api/session/{sid}/model")
        async def _v2_set_model(sid: str, request: Request):
            selected_models.append(await request.json())
            return {}

        @fake_v2.post("/api/session/{sid}/prompt")
        async def _v2_prompt(sid: str, request: Request):
            body = await request.json()
            assert set(body) == {"prompt"} and isinstance(body["prompt"].get("text"), str)
            return {"data": {"id": "msg-u1", "sessionID": sid, "type": "user"}}

        @fake_v2.post("/api/session/{sid}/permission/{rid}/reply")
        async def _v2_perm(sid: str, rid: str, request: Request):
            perm_decisions.append((await request.json()).get("decision", ""))
            return {}

        @fake_v2.get("/api/event")
        async def _v2_sse():
            async def gen():
                yield f"data: {json.dumps({'type': 'server.connected', 'data': {}})}\n\n"
                yield f"data: {json.dumps({'type': 'session.reasoning.delta', 'data': {'sessionID': 'ses-v2', 'delta': 'checking'}})}\n\n"
                yield f"data: {json.dumps({'type': 'session.tool.input.started', 'data': {'sessionID': 'ses-v2', 'id': 'c1', 'name': 'read'}})}\n\n"
                yield f"data: {json.dumps({'type': 'session.tool.called', 'data': {'sessionID': 'ses-v2', 'id': 'c1', 'name': 'read', 'input': {'path': 'README.md'}}})}\n\n"
                yield f"data: {json.dumps({'type': 'permission.asked', 'data': {'sessionID': 'ses-v2', 'id': 'p-v2', 'title': 'Run bash'}})}\n\n"
                yield f"data: {json.dumps({'type': 'session.tool.success', 'data': {'sessionID': 'ses-v2', 'id': 'c1', 'content': [{'type': 'text', 'text': 'hello'}]}})}\n\n"
                yield f"data: {json.dumps({'type': 'session.text.started', 'data': {'sessionID': 'ses-v2'}})}\n\n"
                yield f"data: {json.dumps({'type': 'session.text.delta', 'data': {'sessionID': 'ses-v2', 'delta': 'done!'}})}\n\n"
                yield f"data: {json.dumps({'type': 'session.step.ended', 'data': {'sessionID': 'ses-v2', 'assistantMessageID': 'a1', 'tokens': {'input': 500, 'output': 80, 'reasoning': 10, 'cache': {'read': 100}}}})}\n\n"
                yield f"data: {json.dumps({'type': 'session.execution.succeeded', 'data': {'sessionID': 'ses-v2'}})}\n\n"

            return StreamingResponse(gen(), media_type="text/event-stream")

        @fake_v2.get("/api/session/{sid}/message")
        def _v2_history(sid: str):
            history_requests.append(sid)
            return {
                "data": [
                    {"id": "u1", "type": "user", "text": "hi"},
                    {
                        "id": "a1",
                        "type": "assistant",
                        "content": [
                            {"type": "reasoning", "text": "checking"},
                            {"type": "tool", "id": "c1", "name": "read", "state": {"status": "completed", "input": {"path": "README.md"}, "content": [{"type": "text", "text": "hello"}]}},
                            {"type": "text", "text": "done!"},
                        ],
                    },
                    {"id": "idle1", "type": "idle", "outcome": "succeeded"},
                ]
            }

        adapter = OpenCodeAdapter(roots, serve_url="http://opencode-v2.local")
        adapter._client = lambda: httpx.AsyncClient(  # type: ignore[method-assign]
            transport=httpx.ASGITransport(app=fake_v2),
            base_url="http://opencode-v2.local",
        )
        probe = await adapter.probe()
        assert probe.status == "ready" and probe.version == "serve-v2"
        models = await adapter.list_models()
        assert models[0]["id"] == "opencode-go/deepseek-v4.1-flash" and models[0]["label"] == "DeepSeek V4.1 Flash 1017"
        assert models[0]["efforts"] == ["low", "high"]
        assert [item["sessionId"] for item in await adapter.list_sessions(limit=1)] == ["ses-v2"]
        assert history_requests == []
        sess = await adapter.open_session(cwd=str(project))
        assert sess["sessionId"] == "ses-v2"

        events: list[dict] = []
        await adapter.send_prompt(
            session_id="ses-v2",
            text="hi",
            request_id="r-v2",
            options={"model": "opencode-go/deepseek-v4.1-flash", "effort": "high"},
            emit=lambda ev: events.append(ev) or asyncio.sleep(0),
            request_approval=lambda *_: asyncio.sleep(0, result="allow_session"),
        )
        assert selected_models == [{"model": {"providerID": "opencode-go", "id": "deepseek-v4.1-flash", "variant": "high"}}]
        assert perm_decisions == ["always"]
        assert any(e["type"] == "ToolCallUpdate" and e["status"] == "completed" and e["output"] == "hello" for e in events)
        assert "".join(e["text"] for e in events if e["type"] == "TextDelta") == "done!"
        usage = next(e for e in events if e["type"] == "TokenUsage")
        assert usage["contextWindow"] == 1000000 and usage["totalTokens"] == 590
        assert any(e["type"] == "Completed" for e in events)

        hist = await adapter.get_history(session_id="ses-v2")
        assert len(hist) == 2 and hist[1]["thought"] == "checking" and hist[1]["toolCalls"][0]["output"] == "hello"

    asyncio.run(_run())


def test_opencode_v2_agents_mcp_forms_files_and_hermes_acp_parity(tmp_path):
    async def _run():
        roots = canonicalize_roots([str(tmp_path)])
        fake_v2 = FastAPI()
        selected_agents: list[str] = []
        form_replies: list[dict] = []
        uploaded_files: list[dict] = []

        @fake_v2.get("/api/session")
        def _v2_sessions():
            return {"data": []}

        @fake_v2.get("/api/session/{sid}")
        def _details(sid: str):
            return {"data": {"id": sid, "location": {"directory": str(tmp_path)}}}

        @fake_v2.get("/api/agent")
        def _v2_agents():
            return {"data": [{"name": "build", "description": "Default builder", "mode": "primary"}, {"name": "plan", "description": "Planner"}]}

        @fake_v2.get("/api/mcp")
        def _v2_mcp():
            return {"data": [{"name": "context7", "status": "connected", "tools": ["resolve-library-id"]}]}

        @fake_v2.post("/api/session/{sid}/agent")
        async def _v2_set_agent(sid: str, request: Request):
            selected_agents.append(str((await request.json()).get("agent") or ""))
            return {}

        @fake_v2.post("/api/session/{sid}/prompt")
        async def _v2_prompt(sid: str, request: Request):
            body = await request.json()
            assert set(body) == {"prompt"}
            uploaded_files.extend(body["prompt"].get("files", []))
            return {"data": {"id": "u1"}}

        @fake_v2.post("/api/session/{sid}/form/{fid}/reply")
        async def _v2_form_reply(sid: str, fid: str, request: Request):
            form_replies.append({"sid": sid, "fid": fid, "body": await request.json()})
            return {"ok": True}

        @fake_v2.get("/api/event")
        async def _v2_sse():
            async def gen():
                yield f"data: {json.dumps({'type': 'server.connected', 'data': {}})}\n\n"
                yield f"data: {json.dumps({'type': 'form.created', 'data': {'sessionID': 'ses-f', 'form': {'id': 'frm-1', 'title': 'Choose target', 'fields': [{'key': 'env', 'type': 'string', 'options': [{'value': 'prod', 'label': 'Prod'}]}]}}})}\n\n"
                yield f"data: {json.dumps({'type': 'session.tool.called', 'data': {'sessionID': 'ses-f', 'id': 'call-sub', 'name': 'task', 'input': {'subagent': 'research', 'sessionID': 'ses-child-99'}}})}\n\n"
                yield f"data: {json.dumps({'type': 'session.execution.succeeded', 'data': {'sessionID': 'ses-f'}})}\n\n"

            return StreamingResponse(gen(), media_type="text/event-stream")

        att_file = tmp_path / "note.txt"
        att_file.write_text("hello attachment", encoding="utf-8")
        adapter = OpenCodeAdapter(roots, serve_url="http://opencode-v2.local")
        adapter._client = lambda: httpx.AsyncClient(  # type: ignore[method-assign]
            transport=httpx.ASGITransport(app=fake_v2),
            base_url="http://opencode-v2.local",
        )
        assert [a["id"] for a in await adapter.list_agents()] == ["build", "plan"]
        assert (await adapter.list_mcp_servers())[0]["name"] == "context7"

        events: list[dict] = []
        await adapter.send_prompt(
            session_id="ses-f",
            text="check form",
            request_id="r-form",
            options={"agent": "plan"},
            attachments=[{"fileName": "note.txt", "mime": "text/plain", "localPath": str(att_file)}],
            emit=lambda ev: events.append(ev) or asyncio.sleep(0),
            request_approval=lambda *_: asyncio.sleep(0, result="allow_once"),
        )
        assert selected_agents == ["plan"]
        assert uploaded_files == [{"name": "note.txt", "uri": att_file.as_uri()}]
        form_evt = next(e for e in events if e["type"] == "FormRequest")
        assert form_evt["formId"] == "frm-1" and form_evt["title"] == "Choose target"
        sub_evt = next(e for e in events if e["type"] == "ToolCallUpdate" and e["callId"] == "call-sub")
        assert sub_evt["subagentSessionId"] == "ses-child-99"
        rep = await adapter.reply_form(session_id="ses-f", form_id="frm-1", answer={"env": "prod"})
        assert rep["cancelled"] is False and form_replies[0]["body"] == {"answer": {"env": "prod"}}

        from agent_node.adapters.antigravity import AntigravityAdapter
        from agent_node.adapters.hermes import HermesAdapter

        ag_probe = await AntigravityAdapter(roots, command="definitely-missing-agy-binary").probe()
        assert ag_probe.provider == "antigravity" and ag_probe.status == "unavailable"
        hermes = HermesAdapter(roots)
        h_evts: list[dict] = []
        hermes._turns["h1"] = ("h1-run", lambda ev: h_evts.append(ev) or asyncio.sleep(0))
        await hermes._on_acp_update(
            "session/update",
            {
                "sessionId": "h1",
                "update": {
                    "sessionUpdate": "plan",
                    "entries": [{"content": "Inspect diff", "status": "in_progress"}],
                },
            },
        )
        assert h_evts[0]["type"] == "TodoUpdated" and h_evts[0]["items"][0]["content"] == "Inspect diff"
        assert h_evts[0]["runId"] == "h1-run"

    asyncio.run(_run())
