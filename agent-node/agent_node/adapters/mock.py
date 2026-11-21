"""确定性 Mock 适配器：用于 CI 无外网/无 CLI 环境测试及离线交互验证。"""

import asyncio
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..config import ensure_allowed_path
from ..worktree import create_session_worktree
from .base import (
    AdapterProbe,
    AgentAdapter,
    ApprovalCallback,
    EventEmitter,
    build_todo_updated_event,
    build_token_usage_event,
    build_tool_call_update,
    compaction_frame,
    compaction_record,
    estimate_tokens,
)


MOCK_MODELS = (
    ("mock-fast", "Mock Fast", ("low", "medium")),
    ("mock-balanced", "Mock Balanced", ("low", "medium", "high")),
    ("mock-deep", "Mock Deep", ("medium", "high", "xhigh")),
)
MOCK_CONTEXT_WINDOWS = {
    "mock-deep": 200000,
    "mock-balanced": 128000,
    "mock-fast": 64000,
    "mock-lite": 32000,
}


class MockAdapter(AgentAdapter):
    provider = "mock"

    def __init__(self, allowed_roots: tuple[Path, ...]) -> None:
        self.allowed_roots = allowed_roots
        self._sessions: dict[str, dict[str, Any]] = {}
        self._histories: dict[str, list[dict[str, Any]]] = {}
        self._context_start: dict[str, int] = {}
        self._active_runs: dict[str, asyncio.Event] = {}

    async def probe(self) -> AdapterProbe:
        return AdapterProbe(
            provider=self.provider,
            version="mock-1.1",
            status="ready",
            capabilities=(
                "chat",
                "history",
                "approval",
                "worktree",
                "artifacts",
                "models",
                "read-only",
                "files",
                "diff",
                "checkpoints",
                "todos",
            ),
        )

    async def list_models(self) -> list[dict[str, Any]]:
        return [{"id": model_id, "label": label, "efforts": list(efforts)} for model_id, label, efforts in MOCK_MODELS]

    async def list_sessions(self, *, page: int = 1, limit: int = 30) -> list[dict[str, Any]]:
        items = list(self._sessions.values())
        start = max(0, (page - 1) * limit)
        return items[start : start + limit]

    async def open_session(
        self,
        *,
        cwd: str,
        session_id: str | None = None,
        use_worktree: bool = False,
    ) -> dict[str, Any]:
        safe_cwd = ensure_allowed_path(cwd, self.allowed_roots)
        sid = session_id or f"mock-{uuid4().hex[:8]}"
        effective_cwd = safe_cwd
        worktree_path: str | None = None
        if use_worktree:
            wt = create_session_worktree(safe_cwd, sid, self.allowed_roots)
            effective_cwd = wt
            worktree_path = str(wt)
        meta = {
            "sessionId": sid,
            "provider": self.provider,
            "cwd": str(effective_cwd),
            "worktreePath": worktree_path,
            "title": f"Mock Session ({effective_cwd.name})",
        }
        self._sessions[sid] = meta
        self._histories.setdefault(sid, [])
        return meta

    async def get_history(self, *, session_id: str, limit: int = 50) -> list[dict[str, Any]]:
        items = self._histories.get(session_id, [])
        return items[-limit:]

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
        settings = options or {}
        model_id = settings.get("model") or "mock-balanced"
        model = next((entry for entry in MOCK_MODELS if entry[0] == model_id), None)
        if model is None:
            raise ValueError("未知的 Mock 模型")
        effort = settings.get("effort")
        if effort and effort not in model[2]:
            raise ValueError("所选 Mock 模型不支持该思考强度")

        run_id = f"run-{uuid4().hex[:8]}"
        cancel_ev = asyncio.Event()
        self._active_runs[run_id] = cancel_ev
        try:
            thought_text = "Inspecting workspace constraints..."
            history = self._histories.get(session_id, [])
            hist_tokens = sum(
                estimate_tokens(str(item["systemEvents"][0]["detail"].get("summary", ""))) if item.get("systemEvents")
                else estimate_tokens(str(item.get("text") or ""))
                for item in history[self._context_start.get(session_id, 0):]
            )
            input_tokens = max(12, hist_tokens + estimate_tokens(text) + len(attachments or []) * 120)
            reasoning_tokens = estimate_tokens(thought_text)
            ctx_win = MOCK_CONTEXT_WINDOWS.get(model_id, 128000)

            self._histories.setdefault(session_id, []).append({"role": "user", "text": text, "requestId": request_id})
            history_tools: list[dict[str, Any]] = []
            await emit({"type": "Accepted", "sessionId": session_id, "runId": run_id, "requestId": request_id, "provider": self.provider})
            await emit({"type": "ThoughtDelta", "sessionId": session_id, "runId": run_id, "text": thought_text})

            async def _finish_with_reply(reply_text: str) -> None:
                out_tokens = max(8, estimate_tokens(reply_text)) + reasoning_tokens
                entry: dict[str, Any] = {
                    "role": "assistant",
                    "text": reply_text,
                    "thought": thought_text,
                    "runId": run_id,
                }
                if history_tools:
                    entry["toolCalls"] = history_tools
                self._histories[session_id].append(entry)
                await emit({"type": "TextDelta", "sessionId": session_id, "runId": run_id, "text": reply_text})
                await emit(
                    build_token_usage_event(
                        session_id=session_id,
                        run_id=run_id,
                        request_id=request_id,
                        scope="turn",
                        input_tokens=input_tokens,
                        output_tokens=out_tokens,
                        reasoning_tokens=reasoning_tokens,
                        total_tokens=input_tokens + out_tokens,
                        context_window=ctx_win,
                        model=model_id,
                        source="estimated",
                    )
                )
                await emit({"type": "Completed", "sessionId": session_id, "runId": run_id, "requestId": request_id})

            if text.lstrip().startswith("/plan") or "TODO" in text or "TOOL_DEMO" in text:
                plan_items = [
                    {"id": "step-1", "content": "梳理工作区上下文与变更范围", "status": "completed"},
                    {"id": "step-2", "content": "验证核心逻辑与边界条件", "status": "in_progress"},
                    {"id": "step-3", "content": "输出结论与可复用建议", "status": "pending"},
                ]
                await emit(build_todo_updated_event(session_id=session_id, items=plan_items, run_id=run_id, request_id=request_id))
                inspect_id = f"tool-{uuid4().hex[:6]}"
                await emit(
                    build_tool_call_update(
                        session_id=session_id,
                        call_id=inspect_id,
                        name="workspace_scan",
                        status="running",
                        run_id=run_id,
                        request_id=request_id,
                        title="扫描工作区文件结构",
                        tool_input={"query": "*.md, src/", "limit": 20},
                    )
                )
                await emit(
                    build_tool_call_update(
                        session_id=session_id,
                        call_id=inspect_id,
                        name="workspace_scan",
                        status="completed",
                        run_id=run_id,
                        request_id=request_id,
                        title="扫描工作区文件结构",
                        tool_input={"query": "*.md, src/", "limit": 20},
                        output="Scanned workspace files successfully (0 errors).",
                        duration_ms=24,
                    )
                )
                history_tools.append(
                    {
                        "callId": inspect_id,
                        "name": "workspace_scan",
                        "title": "扫描工作区文件结构",
                        "status": "completed",
                        "input": {"query": "*.md, src/", "limit": 20},
                        "output": "Scanned workspace files successfully (0 errors).",
                        "durationMs": 24,
                    }
                )
                if "TOOL_DEMO" not in text:
                    plan_items[1]["status"] = "completed"
                    plan_items[2]["status"] = "completed"
                    await emit(build_todo_updated_event(session_id=session_id, items=plan_items, run_id=run_id, request_id=request_id))

            if "MOCK_EDIT" in text and not settings.get("readOnly"):
                sess_cwd = (self._sessions.get(session_id) or {}).get("cwd") or str(self.allowed_roots[0])
                safe_dir = ensure_allowed_path(sess_cwd, self.allowed_roots)
                target_file = ensure_allowed_path(safe_dir / "mock_demo.txt", self.allowed_roots)
                edit_id = f"edit-{uuid4().hex[:6]}"
                await emit(
                    build_tool_call_update(
                        session_id=session_id,
                        call_id=edit_id,
                        name="edit_file",
                        status="running",
                        run_id=run_id,
                        request_id=request_id,
                        title="写入 mock_demo.txt",
                        tool_input={"path": "mock_demo.txt", "mode": "append"},
                    )
                )
                prev = target_file.read_text(encoding="utf-8") if target_file.is_file() else ""
                updated = prev + f"# Edit by {run_id}\n{text}\n"
                target_file.write_text(updated, encoding="utf-8")
                out_msg = f"Updated {target_file.name} ({len(updated)} bytes)"
                await emit(
                    build_tool_call_update(
                        session_id=session_id,
                        call_id=edit_id,
                        name="edit_file",
                        status="completed",
                        run_id=run_id,
                        request_id=request_id,
                        title="写入 mock_demo.txt",
                        tool_input={"path": "mock_demo.txt", "mode": "append"},
                        output=out_msg,
                        duration_ms=16,
                    )
                )
                history_tools.append(
                    {
                        "callId": edit_id,
                        "name": "edit_file",
                        "title": "写入 mock_demo.txt",
                        "status": "completed",
                        "input": {"path": "mock_demo.txt", "mode": "append"},
                        "output": out_msg,
                        "durationMs": 16,
                    }
                )

            if "RUN_CMD" in text:
                call_id = f"call-{uuid4().hex[:6]}"
                await emit(
                    build_tool_call_update(
                        session_id=session_id,
                        call_id=call_id,
                        name="shell",
                        status="running",
                        run_id=run_id,
                        request_id=request_id,
                        title="git status && pytest -q",
                        tool_input={"command": "git status && pytest -q"},
                    )
                )
                decision = await request_approval(session_id, call_id, "git status && pytest -q", "medium")
                if cancel_ev.is_set():
                    await emit({"type": "Failed", "sessionId": session_id, "runId": run_id, "requestId": request_id,
                                "code": "cancelled", "message": "已中断当前 Mock 任务"})
                    return
                await emit({"type": "ToolCall", "sessionId": session_id, "runId": run_id, "callId": call_id, "name": "shell", "decision": decision})
                if decision == "deny":
                    await emit(
                        build_tool_call_update(
                            session_id=session_id,
                            call_id=call_id,
                            name="shell",
                            status="error",
                            run_id=run_id,
                            request_id=request_id,
                            title="git status && pytest -q",
                            error="用户拒绝执行该命令",
                        )
                    )
                    history_tools.append(
                        {
                            "callId": call_id,
                            "name": "shell",
                            "title": "git status && pytest -q",
                            "status": "error",
                            "input": {"command": "git status && pytest -q"},
                            "error": "用户拒绝执行该命令",
                        }
                    )
                    await _finish_with_reply("已按指令拒绝执行命令。")
                    return
                await emit(
                    build_tool_call_update(
                        session_id=session_id,
                        call_id=call_id,
                        name="shell",
                        status="completed",
                        run_id=run_id,
                        request_id=request_id,
                        title="git status && pytest -q",
                        output="On branch main\n12 passed in 0.42s",
                        duration_ms=42,
                    )
                )
                history_tools.append(
                    {
                        "callId": call_id,
                        "name": "shell",
                        "title": "git status && pytest -q",
                        "status": "completed",
                        "input": {"command": "git status && pytest -q"},
                        "output": "On branch main\n12 passed in 0.42s",
                        "durationMs": 42,
                    }
                )

            if cancel_ev.is_set():
                await emit({"type": "Failed", "sessionId": session_id, "runId": run_id, "code": "cancelled", "message": "Cancelled by user"})
                return

            att_note = f" (attachments={len(attachments)})" if attachments else ""
            selection = ""
            if settings:
                selection = f" · {model[1]} / {effort or 'default'}"
                if settings.get("readOnly"):
                    selection += " / read-only"
            await _finish_with_reply(f"[mock{selection}] Echo: {text}{att_note}")
        finally:
            self._active_runs.pop(run_id, None)

    async def cancel(self, *, session_id: str, run_id: str | None = None) -> None:
        if run_id and run_id in self._active_runs:
            self._active_runs[run_id].set()
        else:
            for ev in self._active_runs.values():
                ev.set()

    async def rename_session(self, *, session_id: str, title: str) -> dict[str, Any]:
        if session_id in self._sessions:
            self._sessions[session_id]["title"] = title
        return {"sessionId": session_id, "title": title}

    async def delete_session(self, *, session_id: str) -> None:
        self._sessions.pop(session_id, None)
        self._histories.pop(session_id, None)
        self._context_start.pop(session_id, None)

    async def compact_session(self, *, session_id: str) -> dict[str, Any]:
        hist = self._histories.get(session_id, [])
        start = self._context_start.get(session_id, 0)
        turns = [index for index in range(start, len(hist)) if hist[index]["role"] == "user"]
        if len(turns) <= 1:
            return {"supported": True, "message": "上下文已保持精简，无需进一步压缩"}
        summary = "\n".join(f"- {' '.join(hist[index]['text'].split())[:160]}" for index in turns[:-1])
        row = compaction_record(uuid4().hex, summary=f"早先 {len(turns) - 1} 轮讨论的主题\n{summary}", retained_turns=1)
        hist.append(row)
        self._context_start[session_id] = turns[-1]
        return compaction_frame(row)
