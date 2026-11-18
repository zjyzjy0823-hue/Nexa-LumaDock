"""Hermes Agent 适配器：本机优先走 `hermes acp` 标准 ACP 协议，亦支持远端授权 `hermes serve` Gateway。"""

from pathlib import Path
import time
from typing import Any
from uuid import uuid4

import httpx

from .base import (
    AdapterProbe,
    AgentAdapter,
    ApprovalCallback,
    EventEmitter,
    build_todo_updated_event,
    build_token_usage_event,
    build_tool_call_update,
    extract_usage_counts,
    merge_prompt_with_attachments,
    prepare_session_dir,
    probe_cli_binary,
)
from .jsonrpc import StdioJsonRpcProcess


class HermesAdapter(AgentAdapter):
    provider = "hermes"

    def __init__(
        self,
        allowed_roots: tuple[Path, ...],
        *,
        command: str = "hermes",
        mode: str = "acp",
        serve_url: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self.allowed_roots = allowed_roots
        self.command = command
        self.mode = mode
        self.serve_url = serve_url.rstrip("/") if serve_url else None
        self.api_key = api_key
        self._proc: StdioJsonRpcProcess | None = None
        self._initialized = False
        self._emit: EventEmitter | None = None
        self._approvals: dict[str, ApprovalCallback] = {}
        self._tool_starts: dict[str, float] = {}

    async def _ensure_acp(self) -> StdioJsonRpcProcess:
        if self._proc is None:
            self._proc = StdioJsonRpcProcess(
                [self.command, "acp"],
                cwd=self.allowed_roots[0],
                on_notification=self._on_acp_update,
                on_request=self._on_acp_request,
            )
        await self._proc.start()
        if not self._initialized:
            await self._proc.call("initialize", {"protocolVersion": 1, "clientInfo": {"name": "studiolo", "version": "0.7.0"}})
            self._initialized = True
        return self._proc

    async def probe(self) -> AdapterProbe:
        caps = ("chat", "history", "approval", "worktree", "cron", "files", "diff", "checkpoints", "todos")
        if self.mode == "gateway" and self.serve_url:
            try:
                headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
                async with httpx.AsyncClient(timeout=3.0) as client:
                    res = await client.get(f"{self.serve_url}/api/sessions", headers=headers)
                    if res.status_code < 500:
                        return AdapterProbe(provider=self.provider, version="gateway", status="ready", capabilities=caps)
            except Exception:
                return AdapterProbe(provider=self.provider, version="gateway", status="unavailable", capabilities=caps)
        return probe_cli_binary(self.provider, self.command, caps)

    async def list_sessions(self, *, page: int = 1, limit: int = 30) -> list[dict[str, Any]]:
        if self.mode == "gateway" and self.serve_url:
            headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get(f"{self.serve_url}/api/sessions", headers=headers)
                res.raise_for_status()
                items = res.json() if isinstance(res.json(), list) else res.json().get("sessions", [])
                return [{"sessionId": s.get("id"), "provider": self.provider, "title": s.get("title") or s.get("id")} for s in items[:limit]]
        proc = await self._ensure_acp()
        res = await proc.call("session/list", {"limit": limit})
        sessions = (res or {}).get("sessions") or []
        return [{"sessionId": s.get("sessionId"), "provider": self.provider, "title": s.get("title") or s.get("sessionId")} for s in sessions]

    async def open_session(
        self,
        *,
        cwd: str,
        session_id: str | None = None,
        use_worktree: bool = False,
    ) -> dict[str, Any]:
        sid_seed = session_id or f"hermes-{uuid4().hex[:8]}"
        eff_cwd, wt_path = prepare_session_dir(cwd, self.allowed_roots, session_id=sid_seed, use_worktree=use_worktree)
        if self.mode == "gateway" and self.serve_url:
            return {"sessionId": sid_seed, "provider": self.provider, "cwd": str(eff_cwd), "worktreePath": wt_path, "title": f"Hermes ({eff_cwd.name})"}
        proc = await self._ensure_acp()
        if session_id:
            await proc.call("session/load", {"sessionId": session_id, "cwd": str(eff_cwd), "mcpServers": []})
            sid = session_id
        else:
            res = await proc.call("session/new", {"cwd": str(eff_cwd), "mcpServers": []})
            sid = str((res or {}).get("sessionId") or sid_seed)
        return {"sessionId": sid, "provider": self.provider, "cwd": str(eff_cwd), "worktreePath": wt_path, "title": f"Hermes ({eff_cwd.name})"}

    async def get_history(self, *, session_id: str, limit: int = 50) -> list[dict[str, Any]]:
        if self.mode == "gateway" and self.serve_url:
            headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get(f"{self.serve_url}/api/sessions/{session_id}/messages", headers=headers)
                if res.status_code == 200:
                    data = res.json()
                    items = data if isinstance(data, list) else data.get("messages", [])
                    return [{"role": m.get("role", "assistant"), "text": m.get("content", "")} for m in items[-limit:]]
        return []

    async def send_prompt(
        self,
        *,
        session_id: str,
        text: str,
        request_id: str,
        emit: EventEmitter,
        request_approval: ApprovalCallback,
        attachments: list[dict[str, Any]] | None = None,
        options: dict[str, Any] | None = None,
    ) -> None:
        self._emit = emit
        proc = await self._ensure_acp()
        if session_id in self._approvals:
            raise ValueError("当前会话已有任务运行中")
        self._approvals[session_id] = request_approval
        try:
            prompt_text = merge_prompt_with_attachments(text, attachments)
            await emit({"type": "Accepted", "sessionId": session_id, "runId": request_id, "requestId": request_id, "provider": self.provider})
            prompt_res = await proc.call("session/prompt", {"sessionId": session_id, "prompt": [{"type": "text", "text": prompt_text}]})
            if isinstance(prompt_res, dict) and isinstance(prompt_res.get("usage"), dict):
                c = extract_usage_counts(prompt_res["usage"])
                if sum(c.values()) > 0:
                    await emit(
                        build_token_usage_event(
                            session_id=session_id,
                            run_id=request_id,
                            request_id=request_id,
                            scope="turn",
                            input_tokens=c["inputTokens"],
                            cached_input_tokens=c["cachedInputTokens"],
                            output_tokens=c["outputTokens"],
                            reasoning_tokens=c["reasoningTokens"],
                            total_tokens=c["totalTokens"],
                            source="exact",
                        )
                    )
            await emit({"type": "Completed", "sessionId": session_id, "runId": request_id, "requestId": request_id})
        finally:
            self._approvals.pop(session_id, None)

    async def cancel(self, *, session_id: str, run_id: str | None = None) -> None:
        if self._proc is not None:
            await self._proc.notify("session/cancel", {"sessionId": session_id})

    async def _on_acp_update(self, method: str, params: dict[str, Any]) -> None:
        if method != "session/update" or self._emit is None:
            return
        sid = str(params.get("sessionId") or "")
        upd = params.get("update") or {}
        kind = upd.get("sessionUpdate")
        if kind == "agent_thought_chunk":
            await self._emit({"type": "ThoughtDelta", "sessionId": sid, "text": str((upd.get("content") or {}).get("text") or "")})
        elif kind == "agent_message_chunk":
            await self._emit({"type": "TextDelta", "sessionId": sid, "text": str((upd.get("content") or {}).get("text") or "")})
        elif kind == "tool_call":
            call_id = str(upd.get("toolCallId") or uuid4().hex[:8])
            title = str(upd.get("title") or "tool")
            self._tool_starts[call_id] = time.monotonic()
            await self._emit({"type": "ToolCall", "sessionId": sid, "callId": call_id, "name": title})
            await self._emit(
                build_tool_call_update(
                    session_id=sid,
                    call_id=call_id,
                    name=title,
                    status="running",
                    title=str(upd.get("rawInput") or title),
                    tool_input=upd.get("rawInput"),
                )
            )
        elif kind == "tool_call_update":
            call_id = str(upd.get("toolCallId") or "")
            raw_status = str(upd.get("status") or "").lower()
            st = "error" if raw_status in ("failed", "error") else "completed" if raw_status == "completed" else "running"
            started = self._tool_starts.pop(call_id, None) if st != "running" else None
            dur = int((time.monotonic() - started) * 1000) if isinstance(started, (int, float)) else None
            out_content = upd.get("content")
            out_text = (
                "\n".join(str(c.get("content", {}).get("text") or c.get("text") or "") for c in out_content if isinstance(c, dict))
                if isinstance(out_content, list)
                else str(out_content) if out_content else None
            )
            await self._emit(
                build_tool_call_update(
                    session_id=sid,
                    call_id=call_id or uuid4().hex[:8],
                    name=str(upd.get("title") or "tool"),
                    status=st,
                    output=out_text,
                    duration_ms=dur,
                )
            )
        elif kind == "plan" and isinstance(upd.get("entries"), list):
            await self._emit(build_todo_updated_event(session_id=sid, items=upd["entries"]))

    async def _on_acp_request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        sid = str(params.get("sessionId") or "")
        approve = self._approvals.get(sid)
        if method == "session/request_permission" and approve:
            tool_call = params.get("toolCall") or {}
            call_id = str(tool_call.get("toolCallId") or uuid4().hex)
            title = str(tool_call.get("title") or "tool action")
            decision = await approve(sid, call_id, title, "medium")
            options = params.get("options") or []
            wanted_kind = "allow_once" if decision == "allow_once" else "allow_always" if decision == "allow_session" else "reject_once"
            chosen = next((o.get("optionId") for o in options if o.get("kind") == wanted_kind), None)

            return {"outcome": {"outcome": "selected", "optionId": chosen}} if chosen else {"outcome": {"outcome": "cancelled"}}
        return {"outcome": {"outcome": "cancelled"}}
