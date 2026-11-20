"""Hermes Agent 适配器：本机优先走 `hermes acp` 标准 ACP 协议，亦支持远端授权 `hermes serve` Gateway。"""

import asyncio
from collections import deque
from pathlib import Path
import time
from typing import Any
from uuid import uuid4

import httpx

from ..config import PathOutsideAllowedRootsError, ensure_allowed_path
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
        self._init_lock = asyncio.Lock()
        self._history_lock = asyncio.Lock()
        self._session_cwds: dict[str, Path | None] = {}
        self._loaded_sessions: set[str] = set()
        self._history_replays: dict[str, deque[dict[str, Any]]] = {}
        self._turns: dict[str, tuple[str, EventEmitter]] = {}
        self._approvals: dict[str, ApprovalCallback] = {}
        self._tool_starts: dict[tuple[str, str], float] = {}

    async def _ensure_acp(self) -> StdioJsonRpcProcess:
        async with self._init_lock:
            if self._proc is None:
                self._proc = StdioJsonRpcProcess(
                    [self.command, "acp"],
                    cwd=self.allowed_roots[0],
                    on_notification=self._on_acp_update,
                    on_request=self._on_acp_request,
                )
            if await self._proc.start():
                self._initialized = False
                self._loaded_sessions.clear()
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
        limit = min(100, max(1, limit))
        offset = (min(100, max(1, page)) - 1) * limit
        if self.mode == "gateway" and self.serve_url:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get(f"{self.serve_url}/api/sessions", params={"offset": offset, "limit": limit},
                                       headers=self._gateway_headers())
                res.raise_for_status()
                data = res.json()
            items = data if isinstance(data, list) else data.get("sessions", [])
            return self._session_summaries(items[:limit])

        proc = await self._ensure_acp()
        cursor = None
        seen_cursors = set()
        sessions = []
        while len(sessions) < offset + limit:
            response = await proc.call("session/list", {"cursor": cursor} if cursor else {})
            sessions.extend(self._session_summaries((response or {}).get("sessions") or []))
            cursor = (response or {}).get("nextCursor")
            if not cursor or cursor in seen_cursors:
                break
            seen_cursors.add(cursor)
        return sessions[offset:offset + limit]

    def _session_summaries(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        sessions = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            sid = row.get("sessionId") or row.get("id")
            if not isinstance(sid, str) or not sid:
                continue
            cwd = row.get("cwd")
            if isinstance(cwd, str) and cwd:
                try:
                    self._session_cwds[sid] = ensure_allowed_path(cwd, self.allowed_roots)
                except PathOutsideAllowedRootsError:
                    self._session_cwds[sid] = None
            session_cwd = self._session_cwds.get(sid)
            sessions.append({
                "sessionId": sid, "provider": self.provider, "title": row.get("title") or sid,
                "cwd": str(session_cwd) if session_cwd is not None else "",
                "model": row.get("model"),
                "updatedAt": row.get("updatedAt") or row.get("last_active") or row.get("updated_at"),
            })
        return sessions

    async def _load_acp_session(self, proc: StdioJsonRpcProcess, sid: str) -> None:
        if sid not in self._session_cwds:
            await self.list_sessions(limit=100)
        if sid not in self._session_cwds:
            raise ValueError("Hermes 会话不在节点的对话列表中")
        cwd = self._session_cwds[sid]
        if cwd is None:
            raise PathOutsideAllowedRootsError("Hermes 会话目录不在节点允许范围内")
        cwd = ensure_allowed_path(cwd, self.allowed_roots)
        await proc.call("session/load", {"sessionId": sid, "cwd": str(cwd), "mcpServers": []})
        self._loaded_sessions.add(sid)

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
            sid = session_id
            self._session_cwds[sid] = eff_cwd
            async with self._history_lock:
                await self._load_acp_session(proc, sid)
        else:
            res = await proc.call("session/new", {"cwd": str(eff_cwd), "mcpServers": []})
            sid = str((res or {}).get("sessionId") or sid_seed)
            self._session_cwds[sid] = eff_cwd
            self._loaded_sessions.add(sid)
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
        proc = await self._ensure_acp()
        async with self._history_lock:
            if session_id in self._turns:
                return []
            messages: deque[dict[str, Any]] = deque(maxlen=max(1, min(limit, 500)))
            self._history_replays[session_id] = messages
            try:
                await self._load_acp_session(proc, session_id)
                return list(messages)
            finally:
                self._history_replays.pop(session_id, None)

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
        proc = await self._ensure_acp()
        async with self._history_lock:
            if session_id in self._turns:
                raise ValueError("当前会话已有任务运行中")
            if session_id not in self._loaded_sessions and self.mode != "gateway":
                await self._load_acp_session(proc, session_id)
            self._turns[session_id] = (request_id, emit)
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
            self._turns.pop(session_id, None)
            self._approvals.pop(session_id, None)
            for key in [key for key in self._tool_starts if key[0] == session_id]:
                self._tool_starts.pop(key, None)

    async def cancel(self, *, session_id: str, run_id: str | None = None) -> None:
        if self._proc is not None:
            await self._proc.notify("session/cancel", {"sessionId": session_id})

    async def _on_acp_update(self, method: str, params: dict[str, Any]) -> None:
        if method != "session/update":
            return
        sid = str(params.get("sessionId") or "")
        upd = params.get("update") or {}
        kind = upd.get("sessionUpdate")
        replay = self._history_replays.get(sid)
        if replay is not None:
            role = {"user_message_chunk": "user", "agent_message_chunk": "assistant"}.get(kind)
            text = (upd.get("content") or {}).get("text")
            if role and isinstance(text, str) and text:
                if replay and replay[-1]["role"] == role:
                    replay[-1]["text"] += text
                else:
                    replay.append({"role": role, "text": text})
            return
        turn = self._turns.get(sid)
        if not turn:
            return
        request_id, send = turn

        async def emit(event: dict[str, Any]) -> None:
            await send({**event, "runId": request_id, "requestId": request_id})

        if kind == "agent_thought_chunk":
            await emit({"type": "ThoughtDelta", "sessionId": sid, "text": str((upd.get("content") or {}).get("text") or "")})
        elif kind == "agent_message_chunk":
            await emit({"type": "TextDelta", "sessionId": sid, "text": str((upd.get("content") or {}).get("text") or "")})
        elif kind == "tool_call":
            call_id = str(upd.get("toolCallId") or uuid4().hex[:8])
            title = str(upd.get("title") or "tool")
            self._tool_starts[sid, call_id] = time.monotonic()
            await emit({"type": "ToolCall", "sessionId": sid, "callId": call_id, "name": title})
            await emit(
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
            started = self._tool_starts.pop((sid, call_id), None) if st != "running" else None
            dur = int((time.monotonic() - started) * 1000) if isinstance(started, (int, float)) else None
            out_content = upd.get("content")
            out_text = (
                "\n".join(str(c.get("content", {}).get("text") or c.get("text") or "") for c in out_content if isinstance(c, dict))
                if isinstance(out_content, list)
                else str(out_content) if out_content else None
            )
            await emit(
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
            await emit(build_todo_updated_event(session_id=sid, items=upd["entries"]))

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

    # ---------------- Hermes Gateway/Dashboard 原生 CronPort 适配 ----------------

    def _gateway_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    def cron_capabilities(self) -> dict[str, Any]:
        gateway_ready = bool(self.serve_url)
        return {
            "supported": gateway_ready,
            "canCreate": gateway_ready,
            "canUpdate": gateway_ready,
            "canDelete": gateway_ready,
            "canPause": gateway_ready,
            "canRunNow": gateway_ready,
            "historyMode": "recent_only" if gateway_ready else "unavailable",
            "supportsProfiles": gateway_ready,
        }

    def _require_gateway(self) -> str:
        if not self.serve_url:
            raise RuntimeError("Hermes CronPort requires gateway serve_url configuration")
        return self.serve_url

    def _normalize_cron_job(self, raw: dict[str, Any], default_profile: str = "default") -> dict[str, Any]:
        paused = bool(raw.get("paused", False))
        enabled = bool(raw.get("enabled", not paused)) and not paused
        schedule_val = raw.get("schedule") or raw.get("cron") or raw.get("interval") or ""
        if isinstance(schedule_val, dict):
            kind = str(schedule_val.get("kind") or schedule_val.get("type") or "cron")
            expr = str(schedule_val.get("expr") or schedule_val.get("cron") or schedule_val.get("interval") or "")
        else:
            kind = str(raw.get("schedule_type") or raw.get("scheduleKind") or "cron")
            expr = str(schedule_val)
        return {
            "nativeJobId": str(raw.get("id") or raw.get("job_id") or ""),
            "ownerProfile": str(raw.get("profile") or default_profile or "default"),
            "name": str(raw.get("name") or raw.get("title") or raw.get("id") or "Hermes Cron"),
            "description": str(raw.get("description") or ""),
            "enabled": enabled,
            "scheduleKind": kind,
            "scheduleExpression": expr,
            "timezone": str(raw.get("timezone") or raw.get("tz") or "UTC"),
            "nextRunAt": raw.get("next_run_at") or raw.get("nextRunAt"),
            "lastRunAt": raw.get("last_run_at") or raw.get("lastRunAt"),
            "lastStatus": str(raw.get("last_status") or raw.get("lastStatus") or "unknown"),
            "nativeRevision": str(raw.get("revision") or raw.get("updated_at") or ""),
            "capabilities": self.cron_capabilities(),
        }

    async def cron_list(self, *, profile: str | None = None) -> list[dict[str, Any]]:
        base = self._require_gateway()
        params = {"profile": profile} if profile else None
        async with httpx.AsyncClient(timeout=8.0) as client:
            res = await client.get(f"{base}/api/cron/jobs", params=params, headers=self._gateway_headers())
            res.raise_for_status()
            data = res.json()
        rows = data if isinstance(data, list) else (data or {}).get("jobs") or []
        return [self._normalize_cron_job(j, default_profile=profile or "default") for j in rows if isinstance(j, dict)]

    async def cron_create(self, payload: dict[str, Any]) -> dict[str, Any]:
        base = self._require_gateway()
        profile = str(payload.get("ownerProfile") or "default")
        body = {
            "name": str(payload.get("name") or "").strip(),
            "description": str(payload.get("description") or ""),
            "schedule": str(payload.get("scheduleExpression") or ""),
            "timezone": str(payload.get("timezone") or "Asia/Shanghai"),
            "enabled": bool(payload.get("enabled", True)),
            "prompt": str(payload.get("prompt") or ""),
            "profile": profile,
        }
        async with httpx.AsyncClient(timeout=8.0) as client:
            res = await client.post(f"{base}/api/cron/jobs", json=body, headers=self._gateway_headers())
            res.raise_for_status()
            data = res.json()
        job = data.get("job", data) if isinstance(data, dict) else {}
        return self._normalize_cron_job(job if isinstance(job, dict) else {}, default_profile=profile)

    async def cron_update(self, *, native_job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        base = self._require_gateway()
        profile = str(payload.get("ownerProfile") or "default")
        body: dict[str, Any] = {"profile": profile}
        if payload.get("name") is not None:
            body["name"] = payload["name"]
        if payload.get("description") is not None:
            body["description"] = payload["description"]
        if payload.get("scheduleExpression") is not None:
            body["schedule"] = payload["scheduleExpression"]
        if payload.get("timezone") is not None:
            body["timezone"] = payload["timezone"]
        if payload.get("enabled") is not None:
            body["enabled"] = bool(payload["enabled"])
        if payload.get("prompt") is not None:
            body["prompt"] = payload["prompt"]
        async with httpx.AsyncClient(timeout=8.0) as client:
            res = await client.patch(f"{base}/api/cron/jobs/{native_job_id}", json=body, headers=self._gateway_headers())
            res.raise_for_status()
            data = res.json()
        job = data.get("job", data) if isinstance(data, dict) else {"id": native_job_id}
        return self._normalize_cron_job(job if isinstance(job, dict) else {"id": native_job_id}, default_profile=profile)

    async def cron_delete(self, *, native_job_id: str, profile: str | None = None) -> None:
        base = self._require_gateway()
        params = {"profile": profile} if profile else None
        async with httpx.AsyncClient(timeout=8.0) as client:
            res = await client.delete(f"{base}/api/cron/jobs/{native_job_id}", params=params, headers=self._gateway_headers())
            res.raise_for_status()

    async def cron_pause(self, *, native_job_id: str, paused: bool, profile: str | None = None) -> dict[str, Any]:
        base = self._require_gateway()
        action = "pause" if paused else "resume"
        params = {"profile": profile} if profile else None
        async with httpx.AsyncClient(timeout=8.0) as client:
            res = await client.post(
                f"{base}/api/cron/jobs/{native_job_id}/{action}",
                params=params,
                headers=self._gateway_headers(),
            )
            res.raise_for_status()
            data = res.json() if res.content else {"id": native_job_id, "enabled": not paused, "paused": paused}
        job = data.get("job", data) if isinstance(data, dict) else {"id": native_job_id, "enabled": not paused}
        return self._normalize_cron_job(job if isinstance(job, dict) else {"id": native_job_id}, default_profile=profile or "default")

    async def cron_run_now(
        self,
        *,
        native_job_id: str,
        request_id: str,
        profile: str | None = None,
    ) -> dict[str, Any]:
        base = self._require_gateway()
        params = {"profile": profile} if profile else None
        async with httpx.AsyncClient(timeout=8.0) as client:
            res = await client.post(
                f"{base}/api/cron/jobs/{native_job_id}/trigger",
                params=params,
                json={"request_id": request_id},
                headers=self._gateway_headers(),
            )
            res.raise_for_status()
            data = res.json() if res.content else {}
        return {
            "nativeRunId": str(data.get("run_id") or data.get("runId") or request_id),
            "status": str(data.get("status") or "queued"),
            "nativeStatus": str(data.get("status") or "queued"),
            "startedAt": data.get("started_at") or data.get("startedAt"),
            "finishedAt": data.get("finished_at") or data.get("finishedAt"),
            "summary": str(data.get("summary") or ""),
        }

    async def cron_list_runs(
        self,
        *,
        native_job_id: str,
        limit: int = 20,
        profile: str | None = None,
    ) -> list[dict[str, Any]]:
        base = self._require_gateway()
        capped = max(1, min(int(limit), 100))
        params: dict[str, Any] = {"limit": capped}
        if profile:
            params["profile"] = profile
        async with httpx.AsyncClient(timeout=8.0) as client:
            res = await client.get(
                f"{base}/api/cron/jobs/{native_job_id}/runs",
                params=params,
                headers=self._gateway_headers(),
            )
            if res.status_code == 404:
                return []
            res.raise_for_status()
            data = res.json()
        rows = data if isinstance(data, list) else (data or {}).get("runs") or []
        out: list[dict[str, Any]] = []
        for row in rows[:capped]:
            if not isinstance(row, dict):
                continue
            raw_st = str(row.get("status") or "unknown").lower()
            norm_st = (
                "succeeded" if raw_st in ("ok", "success", "succeeded", "completed")
                else "failed" if raw_st in ("error", "failed")
                else "running" if raw_st in ("running", "in_progress")
                else "queued" if raw_st in ("queued", "pending")
                else "unknown"
            )
            out.append(
                {
                    "nativeRunId": str(row.get("run_id") or row.get("id") or ""),
                    "scheduledAt": row.get("scheduled_at") or row.get("scheduledAt"),
                    "startedAt": row.get("started_at") or row.get("startedAt"),
                    "finishedAt": row.get("finished_at") or row.get("finishedAt"),
                    "status": norm_st,
                    "nativeStatus": raw_st,
                    "summary": str(row.get("summary") or row.get("error") or ""),
                }
            )
        return out
