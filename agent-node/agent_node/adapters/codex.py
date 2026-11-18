"""OpenAI Codex CLI 适配器：通过 `codex app-server` 双向 JSON-RPC 驱动，强制人工审批。"""

import asyncio
from pathlib import Path
from typing import Any
from uuid import uuid4

from .base import (
    AdapterProbe,
    AgentAdapter,
    ApprovalCallback,
    EventEmitter,
    build_token_usage_event,
    extract_usage_counts,
    merge_prompt_with_attachments,
    prepare_session_dir,
    probe_cli_binary,
    safe_token_int,
)
from .jsonrpc import StdioJsonRpcProcess


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
        self._turn_usage_seen: set[str] = set()
        self._initialized = False

    async def _ensure_proc(self) -> StdioJsonRpcProcess:
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
        return probe_cli_binary(self.provider, self.command, ("chat", "history", "approval", "worktree", "models", "read-only"))

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
            for item in turn.get("items") or []:
                itype = item.get("type")
                if itype == "userMessage":
                    text = "".join(p.get("text", "") for p in item.get("content") or [] if isinstance(p, dict))
                    messages.append({"role": "user", "text": text})
                elif itype == "agentMessage":
                    messages.append({"role": "assistant", "text": item.get("text", "")})
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

    async def _on_notification(self, method: str, params: dict[str, Any]) -> None:
        emit = self._emit
        if emit is None:
            return
        thread_id = str(params.get("threadId") or "")
        if method == "item/agentMessage/delta":
            await emit({"type": "TextDelta", "sessionId": thread_id, "text": str(params.get("delta") or "")})
        elif method == "item/reasoning/summaryTextDelta":
            await emit({"type": "ThoughtDelta", "sessionId": thread_id, "text": str(params.get("delta") or "")})
        elif method == "item/started":
            item = params.get("item") or {}
            if item.get("type") in ("commandExecution", "fileChange", "mcpToolCall"):
                await emit({"type": "ToolCall", "sessionId": thread_id, "name": item.get("type"), "detail": item.get("command") or ""})
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
