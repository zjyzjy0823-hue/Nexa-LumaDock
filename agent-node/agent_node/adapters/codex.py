"""OpenAI Codex CLI 适配器：通过 `codex app-server` 双向 JSON-RPC 驱动，强制人工审批。"""

import asyncio
from pathlib import Path
import time
from typing import Any
from uuid import uuid4

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
    safe_token_int,
)
from .jsonrpc import StdioJsonRpcProcess


def _map_plan_status(raw: Any) -> str:
    val = str(raw or "").strip().lower().replace("-", "_")
    if val in ("completed", "done"):
        return "completed"
    if val in ("in_progress", "inprogress", "running", "active"):
        return "in_progress"
    if val in ("cancelled", "canceled", "skipped"):
        return "cancelled"
    return "pending"


def _parse_unified_diff_text(diff_text: str) -> dict[str, Any]:
    """将 Codex `turn/diff/updated` 返回的统一 diff 文本解析为结构化文件差异摘要（与 workspace_tools 格式对齐）。"""
    files: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    total_add = 0
    total_del = 0
    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            if cur is not None:
                cur["patch"] = "\n".join(cur.pop("_lines"))
                files.append(cur)
            parts = line.split(" b/", 1)
            path = parts[1].strip() if len(parts) == 2 else line[11:].strip()
            cur = {"path": path, "status": "M", "additions": 0, "deletions": 0, "_lines": [line]}
        elif cur is not None:
            cur["_lines"].append(line)
            if line.startswith("new file mode"):
                cur["status"] = "A"
            elif line.startswith("deleted file mode"):
                cur["status"] = "D"
            elif line.startswith("+") and not line.startswith("+++"):
                cur["additions"] += 1
                total_add += 1
            elif line.startswith("-") and not line.startswith("---"):
                cur["deletions"] += 1
                total_del += 1
    if cur is not None:
        cur["patch"] = "\n".join(cur.pop("_lines"))
        files.append(cur)
    return {
        "files": files,
        "summary": {"filesChanged": len(files), "additions": total_add, "deletions": total_del},
        "isGitRepo": True,
    }


def _quota_windows(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, dict):
        return []
    primary = raw.get("rateLimits")
    buckets = raw.get("rateLimitsByLimitId")
    by_id = {}
    if isinstance(primary, dict):
        key = primary.get("limitId")
        by_id[key if isinstance(key, str) and key else "codex"] = primary
    if isinstance(buckets, dict):
        by_id.update((key, value) for key, value in buckets.items() if isinstance(value, dict))
    windows = []
    for key, bucket in list(by_id.items())[:8]:
        name = bucket.get("limitName")
        group = name.strip() if isinstance(name, str) and name.strip() else ("Codex" if key == "codex" else key)
        for kind in ("primary", "secondary"):
            item = bucket.get(kind)
            if not isinstance(item, dict):
                continue
            used = item.get("usedPercent")
            if type(used) not in (int, float) or not 0 <= used <= 100:
                continue
            duration = item.get("windowDurationMins")
            resets_at = item.get("resetsAt")
            windows.append({
                "group": group[:100], "kind": kind, "remainingPercent": 100 - used,
                "windowMinutes": duration if type(duration) is int and 0 < duration <= 1_000_000 else None,
                "resetsAt": resets_at if type(resets_at) is int and 0 < resets_at <= 253402300799 else None,
            })
    return windows


class CodexAdapter(AgentAdapter):
    provider = "codex"

    def __init__(self, allowed_roots: tuple[Path, ...], *, command: str = "codex") -> None:
        self.allowed_roots = allowed_roots
        self.command = command
        self._proc: StdioJsonRpcProcess | None = None
        self._emit: EventEmitter | None = None
        self._approvals: dict[str, ApprovalCallback] = {}
        self._defaults: dict[str, dict[str, Any]] = {}
        self._turn_done: dict[str, asyncio.Future[None]] = {}
        self._active_meta: dict[str, dict[str, str]] = {}
        self._tool_meta: dict[str, dict[str, Any]] = {}
        self._turn_usage_seen: set[str] = set()
        self._initialized = False
        self._init_lock = asyncio.Lock()
        self._quota_lock = asyncio.Lock()
        self._quota_cache: tuple[float, dict[str, Any]] | None = None

    async def _ensure_proc(self) -> StdioJsonRpcProcess:
        async with self._init_lock:
            if self._proc is None:
                self._proc = StdioJsonRpcProcess(
                    [self.command, "app-server"],
                    cwd=self.allowed_roots[0],
                    on_notification=self._on_notification,
                    on_request=self._on_server_request,
                )
            await self._proc.start()
            if not self._initialized:
                await self._proc.call(
                    "initialize",
                    {"clientInfo": {"name": "studiolo-agent-node", "version": "0.7.0"}},
                )
                await self._proc.notify("initialized")
                self._initialized = True
            return self._proc

    async def probe(self) -> AdapterProbe:
        return probe_cli_binary(
            self.provider,
            self.command,
            ("chat", "history", "approval", "worktree", "models", "read-only", "files", "diff", "checkpoints", "todos", "subscription-quota"),
        )

    async def read_subscription_quota(self) -> dict[str, Any]:
        async with self._quota_lock:
            if self._quota_cache and time.monotonic() - self._quota_cache[0] < 60:
                return self._quota_cache[1]
            try:
                async with asyncio.timeout(8):
                    proc = await self._ensure_proc()
                    raw = await proc.call("account/rateLimits/read", timeout=6)
                windows = _quota_windows(raw)
            except (OSError, RuntimeError, TimeoutError):
                windows = []
                status = "unavailable"
            else:
                status = "ready" if windows else "no_data"
            result = {"status": status, "windows": windows, "checkedAt": int(time.time())}
            self._quota_cache = (time.monotonic(), result)
            return result

    async def list_models(self) -> list[dict[str, Any]]:
        proc = await self._ensure_proc()
        result = await proc.call("model/list", {"limit": 100})
        return [{"id": row["model"], "label": row.get("displayName") or row["model"],
                 "efforts": [e["reasoningEffort"] for e in row.get("supportedReasoningEfforts", [])]}
                for row in result.get("data", []) if row.get("model") and not row.get("hidden")]

    async def list_sessions(self, *, page: int = 1, limit: int = 30) -> list[dict[str, Any]]:
        proc = await self._ensure_proc()
        res = await proc.call("thread/list", {"limit": limit})
        threads = res.get("data", []) if isinstance(res, dict) else []
        return [
            {
                "sessionId": t.get("id"),
                "provider": self.provider,
                "title": t.get("preview") or t.get("id"),
                "cwd": t.get("cwd", ""),
            }
            for t in threads
            if isinstance(t, dict) and t.get("id")
        ]

    async def open_session(
        self,
        *,
        cwd: str,
        session_id: str | None = None,
        use_worktree: bool = False,
    ) -> dict[str, Any]:
        sid_seed = session_id or f"codex-{uuid4().hex[:8]}"
        eff_cwd, wt_path = prepare_session_dir(
            cwd, self.allowed_roots, session_id=sid_seed, use_worktree=use_worktree
        )
        proc = await self._ensure_proc()
        if session_id:
            res = await proc.call("thread/resume", {"threadId": session_id, "cwd": str(eff_cwd), "approvalPolicy": "on-request"})
        else:
            res = await proc.call("thread/start", {"cwd": str(eff_cwd), "approvalPolicy": "on-request"})
        thread = (res or {}).get("thread") or {}
        tid = str(thread.get("id") or sid_seed)
        self._defaults[tid] = {param: res[field] for param, field in (
            ("model", "model"), ("effort", "reasoningEffort"), ("sandboxPolicy", "sandbox"),
            ("approvalPolicy", "approvalPolicy")) if res and res.get(field) is not None}
        return {
            "sessionId": tid,
            "provider": self.provider,
            "cwd": str(eff_cwd),
            "worktreePath": wt_path,
            "title": thread.get("preview") or f"Codex ({eff_cwd.name})",
        }

    async def get_history(self, *, session_id: str, limit: int = 50) -> list[dict[str, Any]]:
        proc = await self._ensure_proc()
        res = await proc.call("thread/read", {"threadId": session_id, "includeTurns": True})
        turns = ((res or {}).get("thread") or {}).get("turns") or []
        messages: list[dict[str, Any]] = []
        for turn in turns[-limit:]:
            pending_thought: list[str] = []
            pending_tools: list[dict[str, Any]] = []
            pending_text: list[str] = []

            def _flush_assistant() -> None:
                if not pending_thought and not pending_tools and not pending_text:
                    return
                entry: dict[str, Any] = {"role": "assistant", "text": "".join(pending_text)}
                if pending_thought:
                    entry["thought"] = "\n".join(pending_thought)
                if pending_tools:
                    entry["toolCalls"] = list(pending_tools)
                messages.append(entry)
                pending_thought.clear()
                pending_tools.clear()
                pending_text.clear()

            for item in turn.get("items") or []:
                itype = item.get("type")
                if itype == "userMessage":
                    _flush_assistant()
                    text = "".join(p.get("text", "") for p in item.get("content") or [] if isinstance(p, dict))
                    messages.append({"role": "user", "text": text})
                elif itype in ("reasoning", "reasoningSummary"):
                    summary = item.get("summary")
                    chunk = (
                        "\n".join(str(s) for s in summary if s)
                        if isinstance(summary, list)
                        else str(item.get("text") or summary or "")
                    )
                    if chunk:
                        pending_thought.append(chunk)
                elif itype in ("commandExecution", "fileChange", "mcpToolCall"):
                    st_raw = str(item.get("status") or "").lower()
                    st = (
                        "error"
                        if st_raw in ("failed", "error", "declined")
                        else "running"
                        if st_raw in ("inprogress", "in_progress", "running")
                        else "completed"
                    )
                    pending_tools.append(
                        {
                            "callId": str(item.get("id") or uuid4().hex[:8]),
                            "name": str(item.get("tool") or itype),
                            "title": str(item.get("command") or item.get("tool") or item.get("server") or itype),
                            "status": st,
                            "input": item.get("command") or item.get("arguments") or item.get("changes"),
                            "output": str(item.get("aggregatedOutput") or item.get("output") or ""),
                            "error": str(item["error"]) if item.get("error") else None,
                        }
                    )
                elif itype == "agentMessage":
                    pending_text.append(str(item.get("text") or ""))
            _flush_assistant()
        return messages[-limit:]

    async def send_prompt(
        self,
        *,
        session_id: str,
        text: str,
        request_id: str,
        emit: EventEmitter,
        request_approval: ApprovalCallback,
        attachments: list[dict[str, Any]] | None = None,
        options: dict[str, str] | None = None,
    ) -> None:
        self._emit = emit
        proc = await self._ensure_proc()
        options = options or {}
        settings = dict(self._defaults.get(session_id, {}))
        settings.update({k: options[k] for k in ("model", "effort") if options.get(k)})
        if options.get("readOnly"):
            settings.update(sandboxPolicy={"type": "readOnly"}, approvalPolicy="never")
        if session_id in self._turn_done:
            raise ValueError("当前会话已有任务运行中")
        done = asyncio.get_running_loop().create_future()
        self._turn_done[session_id] = done
        self._approvals[session_id] = request_approval
        self._active_meta[session_id] = {
            "requestId": request_id,
            "model": str(settings.get("model") or ""),
        }
        try:
            image_inputs: list[dict[str, Any]] = []
            extra_attachments: list[dict[str, Any]] = []
            for att in attachments or []:
                lp = att.get("localPath") if isinstance(att, dict) else None
                mime = str(att.get("mime") or "") if isinstance(att, dict) else ""
                if lp and mime.startswith("image/"):
                    image_inputs.append({"type": "localImage", "path": str(lp)})
                else:
                    extra_attachments.append(att)
            prompt_text = merge_prompt_with_attachments(text, extra_attachments)
            input_items: list[dict[str, Any]] = [{"type": "text", "text": prompt_text}, *image_inputs]
            turn_res = await proc.call("turn/start", {
                **settings, "threadId": session_id, "input": input_items,
            })
            run_id = str(((turn_res or {}).get("turn") or {}).get("id") or request_id)
            self._active_meta[session_id]["runId"] = run_id
            await emit({"type": "Accepted", "sessionId": session_id, "runId": run_id, "requestId": request_id, "provider": self.provider})
            await asyncio.wait_for(done, timeout=300.0)
        finally:
            self._turn_done.pop(session_id, None)
            self._approvals.pop(session_id, None)
            self._active_meta.pop(session_id, None)

    async def cancel(self, *, session_id: str, run_id: str | None = None) -> None:
        if self._proc is None:
            return
        await self._proc.call("turn/interrupt", {"threadId": session_id, **({"turnId": run_id} if run_id else {})})

    async def rename_session(self, *, session_id: str, title: str) -> dict[str, Any]:
        try:
            proc = await self._ensure_proc()
            await proc.call("thread/name/set", {"threadId": session_id, "name": title})
        except Exception:
            pass
        return {"sessionId": session_id, "title": title}

    async def delete_session(self, *, session_id: str) -> None:
        try:
            proc = await self._ensure_proc()
            await proc.call("thread/archive", {"threadId": session_id})
        except Exception:
            pass

    async def compact_session(self, *, session_id: str) -> dict[str, Any]:
        try:
            proc = await self._ensure_proc()
            await proc.call("thread/compact/start", {"threadId": session_id})
            return {"supported": True, "message": "已通知 Codex 压缩上下文"}
        except Exception:
            return {"supported": False}

    async def _on_notification(self, method: str, params: dict[str, Any]) -> None:
        if method == "account/updated":
            self._quota_cache = None
        emit = self._emit
        if emit is None:
            return
        thread_id = str(params.get("threadId") or "")
        meta = self._active_meta.get(thread_id, {})
        run_id_active = meta.get("runId") or None
        req_id_active = meta.get("requestId") or None
        if method == "item/agentMessage/delta":
            await emit({"type": "TextDelta", "sessionId": thread_id, "text": str(params.get("delta") or "")})
        elif method == "item/reasoning/summaryTextDelta":
            await emit({"type": "ThoughtDelta", "sessionId": thread_id, "text": str(params.get("delta") or "")})
        elif method == "item/started":
            item = params.get("item") or {}
            itype = str(item.get("type") or "")
            if itype in ("commandExecution", "fileChange", "mcpToolCall"):
                call_id = str(item.get("id") or uuid4().hex[:8])
                name = str(item.get("tool") or itype)
                title = str(item.get("command") or item.get("tool") or item.get("server") or itype)
                self._tool_meta[call_id] = {"name": name, "title": title, "started": time.monotonic()}
                tool_input = item.get("command") or item.get("arguments") or item.get("changes")
                await emit(
                    build_tool_call_update(
                        session_id=thread_id,
                        call_id=call_id,
                        name=name,
                        status="running",
                        run_id=run_id_active,
                        request_id=req_id_active,
                        title=title,
                        tool_input=tool_input,
                    )
                )
        elif method in ("item/commandExecution/outputDelta", "item/fileChange/outputDelta", "item/outputDelta"):
            call_id = str(params.get("itemId") or params.get("callId") or "")
            delta = str(params.get("delta") or "")
            if call_id and delta:
                tmeta = self._tool_meta.get(call_id, {})
                await emit(
                    build_tool_call_update(
                        session_id=thread_id,
                        call_id=call_id,
                        name=str(tmeta.get("name") or "tool"),
                        status="running",
                        run_id=run_id_active,
                        request_id=req_id_active,
                        title=tmeta.get("title"),
                        delta_output=delta,
                    )
                )
        elif method == "item/completed":
            item = params.get("item") or {}
            itype = str(item.get("type") or "")
            if itype in ("commandExecution", "fileChange", "mcpToolCall"):
                call_id = str(item.get("id") or uuid4().hex[:8])
                tmeta = self._tool_meta.pop(call_id, {})
                started = tmeta.get("started")
                duration_ms = int((time.monotonic() - started) * 1000) if isinstance(started, (int, float)) else None
                raw_status = str(item.get("status") or "").lower()
                failed = raw_status in ("failed", "error", "declined") or (
                    item.get("exitCode") not in (None, 0)
                )
                name = str(item.get("tool") or tmeta.get("name") or itype)
                title = str(item.get("command") or tmeta.get("title") or name)
                out_text = item.get("aggregatedOutput") or item.get("output")
                err_text = str(item["error"]) if item.get("error") else ("Execution failed" if failed and not out_text else None)
                await emit(
                    build_tool_call_update(
                        session_id=thread_id,
                        call_id=call_id,
                        name=name,
                        status="error" if failed else "completed",
                        run_id=run_id_active,
                        request_id=req_id_active,
                        title=title,
                        tool_input=item.get("command") or item.get("arguments") or item.get("changes"),
                        output=str(out_text) if out_text is not None else None,
                        error=err_text,
                        duration_ms=duration_ms,
                    )
                )
        elif method == "turn/plan/updated":
            raw_plan = params.get("plan") or params.get("steps") or []
            if isinstance(raw_plan, list):
                items = [
                    {
                        "id": str(s.get("id") or idx),
                        "content": str(s.get("step") or s.get("content") or s.get("title") or ""),
                        "status": _map_plan_status(s.get("status")),
                    }
                    for idx, s in enumerate(raw_plan)
                    if isinstance(s, dict) and str(s.get("step") or s.get("content") or s.get("title") or "").strip()
                ]
                await emit(build_todo_updated_event(session_id=thread_id, items=items, run_id=run_id_active, request_id=req_id_active))
        elif method == "turn/diff/updated":
            diff_text = str(params.get("diff") or "")
            if diff_text.strip():
                parsed = _parse_unified_diff_text(diff_text)
                await emit(
                    {
                        "type": "DiffSnapshot",
                        "sessionId": thread_id,
                        **({"runId": run_id_active} if run_id_active else {}),
                        "perTurn": True,
                        **parsed,
                    }
                )
        elif method == "thread/tokenUsage/updated":
            usage_root = params.get("tokenUsage") or params.get("token_usage") or {}
            if not isinstance(usage_root, dict):
                return
            meta = self._active_meta.get(thread_id, {})
            turn_id = str(params.get("turnId") or params.get("turn_id") or usage_root.get("turnId") or meta.get("runId") or "")
            total_raw = usage_root.get("total") or usage_root.get("total_token_usage") or usage_root
            last_raw = usage_root.get("last") or usage_root.get("last_token_usage") or {}
            total_c = extract_usage_counts(total_raw if isinstance(total_raw, dict) else {})
            last_c = extract_usage_counts(last_raw) if isinstance(last_raw, dict) and last_raw else {}
            ctx_win = safe_token_int(usage_root.get("modelContextWindow") or usage_root.get("model_context_window")) or None
            if sum(total_c.values()) > 0 or sum(last_c.values()) > 0:
                self._turn_usage_seen.add(turn_id or thread_id)
                await emit(
                    build_token_usage_event(
                        session_id=thread_id,
                        run_id=turn_id or None,
                        request_id=meta.get("requestId") or None,
                        scope="cumulative",
                        input_tokens=total_c["inputTokens"],
                        cached_input_tokens=total_c["cachedInputTokens"],
                        output_tokens=total_c["outputTokens"],
                        reasoning_tokens=total_c["reasoningTokens"],
                        total_tokens=total_c["totalTokens"],
                        last_input_tokens=last_c["inputTokens"] if last_c else None,
                        last_cached_input_tokens=last_c["cachedInputTokens"] if last_c else None,
                        last_output_tokens=last_c["outputTokens"] if last_c else None,
                        last_reasoning_tokens=last_c["reasoningTokens"] if last_c else None,
                        last_total_tokens=last_c["totalTokens"] if last_c else None,
                        context_window=ctx_win,
                        model=meta.get("model") or None,
                        source="exact",
                    )
                )
        elif method == "turn/completed":
            turn = params.get("turn") or {}
            meta = self._active_meta.get(thread_id, {})
            run_id = str(turn.get("id") or meta.get("runId") or "")
            usage_raw = turn.get("usage") or params.get("usage")
            seen_key = run_id or thread_id
            if isinstance(usage_raw, dict) and seen_key not in self._turn_usage_seen:
                c = extract_usage_counts(usage_raw)
                ctx_win = safe_token_int(usage_raw.get("modelContextWindow") or params.get("modelContextWindow")) or None
                if sum(c.values()) > 0:
                    await emit(
                        build_token_usage_event(
                            session_id=thread_id,
                            run_id=run_id or None,
                            request_id=meta.get("requestId") or None,
                            scope="turn",
                            input_tokens=c["inputTokens"],
                            cached_input_tokens=c["cachedInputTokens"],
                            output_tokens=c["outputTokens"],
                            reasoning_tokens=c["reasoningTokens"],
                            total_tokens=c["totalTokens"],
                            context_window=ctx_win,
                            model=meta.get("model") or None,
                            source="exact",
                        )
                    )
            self._turn_usage_seen.discard(run_id)
            self._turn_usage_seen.discard(thread_id)
            await emit({"type": "Completed", "sessionId": thread_id, "runId": run_id})
            fut = self._turn_done.get(thread_id)
            if fut and not fut.done():
                fut.set_result(None)

    async def _on_server_request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        sid = str(params.get("threadId") or "")
        approve = self._approvals.get(sid)
        if "requestApproval" in method and approve:
            call_id = str(params.get("itemId") or uuid4().hex)
            cmd = str(params.get("command") or params.get("reason") or method)
            decision = await approve(sid, call_id, cmd, "high")
            mapped = "accept" if decision == "allow_once" else "acceptForSession" if decision == "allow_session" else "decline"
            return {"decision": mapped}
        return {"decision": "decline"}
