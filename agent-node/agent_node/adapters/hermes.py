"""Hermes Agent 适配器：本机优先走 `hermes acp` 标准 ACP 协议，亦支持远端授权 `hermes serve` Gateway。"""

import asyncio
from collections import OrderedDict, deque
from copy import deepcopy
from pathlib import Path
import time
from typing import Any
from urllib.parse import quote
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


_HISTORY_LIMIT = 500
_HISTORY_SESSIONS = 32


def _gateway_history(items: list[Any]) -> list[dict[str, Any]]:
    history: list[dict[str, Any]] = []
    calls: dict[str, dict[str, Any]] = {}

    def content_text(value: Any) -> str:
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            return "".join(str(part.get("text", "")) for part in value
                           if isinstance(part, dict) and part.get("type") in ("text", "output_text"))
        return ""

    for raw in items:
        if not isinstance(raw, dict):
            continue
        role = raw.get("role")
        content = raw.get("content", raw.get("text"))
        if role == "tool":
            call = calls.get(str(raw.get("tool_call_id") or raw.get("callId") or ""))
            if call is not None:
                call["output"] = content_text(content)
                call["status"] = "error" if raw.get("error") else "completed"
                if raw.get("error"):
                    call["error"] = str(raw["error"])
                continue
        role = role if role in ("user", "assistant", "system") else "assistant"
        text = content_text(content)
        row: dict[str, Any] = {"role": role, "text": text}
        for key in ("id", "runId", "requestId"):
            if raw.get(key) is not None:
                row[key] = str(raw[key])
        created = raw.get("createdAt", raw.get("created_at", raw.get("timestamp")))
        if type(created) in (int, float):
            row["createdAt"] = created * 1000 if created < 1e12 else created
        if role != "assistant":
            history.append(row)
            continue

        tools: dict[str, dict[str, Any]] = {}
        source_tools = raw.get("toolCalls") or raw.get("tool_calls") or []
        if not isinstance(source_tools, list):
            source_tools = []
        if isinstance(content, list):
            source_tools = [*source_tools, *(part for part in content if isinstance(part, dict) and part.get("type") in ("tool", "tool_use"))]
        for item in source_tools:
            if not isinstance(item, dict):
                continue
            call_id = str(item.get("callId") or item.get("toolCallId") or item.get("id") or "")
            if not call_id:
                continue
            function = item.get("function") if isinstance(item.get("function"), dict) else {}
            tool = {"callId": call_id, "name": item.get("name") or function.get("name") or "tool"}
            tool.update({key: item[key] for key in ("title", "detail", "output", "error", "durationMs", "subagentSessionId", "media") if key in item})
            tool["input"] = item.get("input", function.get("arguments"))
            status = item.get("status")
            tool["status"] = "error" if status in ("error", "failed", "cancelled") else "running" if status in ("running", "in_progress") else "completed"
            tools[call_id] = tool
            calls[call_id] = tool

        thought = raw.get("thought") or raw.get("reasoning_content")
        parts = []
        for part in raw.get("parts") or (content if isinstance(content, list) else []):
            if not isinstance(part, dict):
                continue
            kind = part.get("type")
            if kind in ("thought", "reasoning", "text", "output_text") and part.get("text"):
                parts.append({"type": "thought" if kind in ("thought", "reasoning") else "text", "text": str(part["text"])})
            elif kind in ("tool", "tool_use"):
                call_id = str(part.get("callId") or part.get("id") or "")
                if call_id in tools:
                    parts.append({"type": "tool", "callId": call_id})
        if isinstance(thought, str) and thought and not any(part["type"] == "thought" for part in parts):
            parts.insert(0, {"type": "thought", "text": thought})
        seen = {part["callId"] for part in parts if part["type"] == "tool"}
        parts.extend({"type": "tool", "callId": key} for key in tools if key not in seen)
        if text and not any(part["type"] == "text" for part in parts):
            parts.append({"type": "text", "text": text})
        row["text"] = "".join(part["text"] for part in parts if part["type"] == "text")
        reasoning = "".join(part["text"] for part in parts if part["type"] == "thought")
        if reasoning:
            row["thought"] = reasoning
        if tools:
            row["toolCalls"] = list(tools.values())
        if reasoning or tools:
            row["parts"] = parts
        history.append(row)
    return history


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
        self._history_updated: dict[str, asyncio.Event] = {}
        self._history: OrderedDict[str, deque[dict[str, Any]]] = OrderedDict()
        self._turns: dict[str, tuple[str, EventEmitter]] = {}
        self._approvals: dict[str, ApprovalCallback] = {}
        self._tool_starts: dict[tuple[str, str], float] = {}
        # ACP 只在会话响应里给出模型清单（SessionModelState），所以把最近一次读到的缓存下来，
        # 供“模型选择器”（models.list）使用；current 与 ACP 的真实当前模型保持一致。
        self._picker_models: list[dict[str, Any]] | None = None
        self._current_model: str | None = None
        self._current_effort: str | None = None
        self._effort_levels: list[str] = []

    async def _ensure_acp(self) -> StdioJsonRpcProcess:
        async with self._init_lock:
            if self._proc is not None and self._proc.started and not self._proc.is_alive():
                # 子进程死了/管道断了就换一个：否则会拿着死句柄一直抛空错误的
                # node_execution_error，app 上直接显示"发不出去"。
                await self._proc.stop()
                self._proc = None
            if self._proc is None:
                self._proc = StdioJsonRpcProcess(
                    [self.command, "acp"],
                    cwd=self.allowed_roots[0],
                    on_notification=self._on_acp_update,
                    on_request=self._on_acp_request,
                    auto_start=False,
                )
            if await self._proc.start():
                self._initialized = False
                self._loaded_sessions.clear()
            if not self._initialized:
                await self._proc.call("initialize", {"protocolVersion": 1, "clientInfo": {"name": "studiolo", "version": "0.8.0"}})
                self._initialized = True
            return self._proc

    async def probe(self) -> AdapterProbe:
        caps = ("chat", "history", "approval", "worktree", "models", "cron", "files", "diff", "checkpoints", "todos")
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
        messages: deque[dict[str, Any]] = deque(maxlen=_HISTORY_LIMIT)
        updated = asyncio.Event()
        self._history_replays[sid] = messages
        self._history_updated[sid] = updated
        try:
            response = await proc.call("session/load", {"sessionId": sid, "cwd": str(cwd), "mcpServers": []})
            # Replay notifications may continue arriving after the RPC response.
            try:
                if not messages:
                    await asyncio.wait_for(updated.wait(), timeout=0.45)
                async with asyncio.timeout(0.6):
                    while True:
                        updated.clear()
                        await asyncio.wait_for(updated.wait(), timeout=0.12)
            except TimeoutError:
                pass
            self._remember_models(response)
            self._save_history(sid, messages)
        finally:
            self._history_replays.pop(sid, None)
            self._history_updated.pop(sid, None)
        self._loaded_sessions.add(sid)

    def _save_history(self, sid: str, messages: deque[dict[str, Any]]) -> None:
        self._history[sid] = messages
        self._history.move_to_end(sid)
        while len(self._history) > _HISTORY_SESSIONS:
            oldest = next((key for key in self._history if key not in self._turns and key != sid), None)
            if oldest is None:
                break
            del self._history[oldest]

    async def _get_models_from_session(self, proc: StdioJsonRpcProcess, sid: str) -> None:
        async with self._history_lock:
            if self._picker_models is None and sid not in self._turns:
                await self._load_acp_session(proc, sid)

    def _remember_models(self, response: dict[str, Any] | None) -> None:
        """缓存 ACP 会话响应里的 SessionModelState（availableModels / currentModelId）。

        思考档位不在 ModelInfo 里：ACP 把可选项放在会话响应的 ``configOptions`` 中
        （id=reasoning_effort，category=thought_level）。所以档位取自那里，同一组值
        用于所有模型——和 Zed 等编辑器看到的一致。
        """
        if not isinstance(response, dict):
            return
        effort_levels: list[str] = []
        for option in response.get("configOptions") or []:
            if not isinstance(option, dict):
                continue
            if str(option.get("id") or "") != "reasoning_effort":
                continue
            for choice in option.get("options") or []:
                if isinstance(choice, dict):
                    value = str(choice.get("value") or "").strip().lower()
                    if value and value != "default":
                        effort_levels.append(value)
        if not effort_levels:
            effort_levels = self._effort_levels_from_meta(response.get("models") or {})
        self._effort_levels = effort_levels
        state = response.get("models") or {}
        if not isinstance(state, dict):
            return
        current = state.get("currentModelId") or state.get("current_model_id")
        if current:
            self._current_model = str(current)
        rows = state.get("availableModels") or state.get("available_models") or []
        models: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            model_id = str(row.get("modelId") or row.get("model_id") or "")
            if not model_id:
                continue
            meta = row.get("_meta") if isinstance(row.get("_meta"), dict) else {}
            hermes_meta = meta.get("hermes") if isinstance(meta.get("hermes"), dict) else {}
            raw_efforts = hermes_meta.get("efforts") if isinstance(hermes_meta.get("efforts"), list) else []
            efforts = effort_levels or [str(level).strip().lower() for level in raw_efforts if str(level).strip()]
            models.append({
                "id": model_id,
                "label": str(row.get("name") or model_id),
                "provider": model_id.split(":", 1)[0] if ":" in model_id else "",
                # FleetModel 契约要求 efforts 必填；这里给出该会话真实可选的思考档位。
                "efforts": efforts,
                "description": row.get("description"),
            })
        if models:
            self._picker_models = models

    @staticmethod
    def _effort_levels_from_meta(state: dict[str, Any]) -> list[str]:
        """旧后端兼容：没有 configOptions 时退回 ModelInfo._meta.hermes.efforts。"""
        rows = state.get("availableModels") or state.get("available_models") or []
        for row in rows:
            if not isinstance(row, dict):
                continue
            meta = row.get("_meta") if isinstance(row.get("_meta"), dict) else {}
            hermes_meta = meta.get("hermes") if isinstance(meta.get("hermes"), dict) else {}
            raw = hermes_meta.get("efforts") if isinstance(hermes_meta.get("efforts"), list) else []
            levels = [str(level).strip().lower() for level in raw if str(level).strip()]
            if levels:
                return levels
        return []


    async def list_models(self) -> list[dict[str, Any]]:
        """ACP 没有独立的模型清单接口：优先复用已知会话，其次最近一个会话，都没有才新开一个。"""
        if self._picker_models is not None:
            return self._picker_models
        if self.mode == "gateway" and self.serve_url:
            return []
        proc = await self._ensure_acp()
        sid = next(iter(self._session_cwds), None)
        cwd = self._session_cwds.get(sid) if sid else None
        if sid and cwd is not None:
            try:
                await self._get_models_from_session(proc, sid)
            except Exception:
                pass
        else:
            try:
                rows = await self.list_sessions(limit=1)
            except Exception:
                rows = []
            candidate = rows[0] if rows else None
            if candidate and candidate.get("cwd"):
                try:
                    await self._get_models_from_session(proc, candidate["sessionId"])
                except Exception:
                    pass
        if self._picker_models is None:
            res = await proc.call("session/new", {"cwd": str(self.allowed_roots[0]), "mcpServers": []})
            self._remember_models(res)
            new_sid = str((res or {}).get("sessionId") or "")
            if new_sid:
                self._session_cwds.setdefault(new_sid, self.allowed_roots[0])
                self._loaded_sessions.add(new_sid)
                self._save_history(new_sid, deque(maxlen=_HISTORY_LIMIT))
        return self._picker_models or []

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
            async with self._history_lock:
                if sid not in self._turns:
                    self._session_cwds[sid] = eff_cwd
                    await self._load_acp_session(proc, sid)
                else:
                    eff_cwd = self._session_cwds.get(sid) or eff_cwd
        else:
            res = await proc.call("session/new", {"cwd": str(eff_cwd), "mcpServers": []})
            sid = str((res or {}).get("sessionId") or sid_seed)
            self._session_cwds[sid] = eff_cwd
            self._loaded_sessions.add(sid)
            self._save_history(sid, deque(maxlen=_HISTORY_LIMIT))
            self._remember_models(res)
        return {"sessionId": sid, "provider": self.provider, "cwd": str(eff_cwd), "worktreePath": wt_path, "title": f"Hermes ({eff_cwd.name})"}

    async def get_history(self, *, session_id: str, limit: int = 50) -> list[dict[str, Any]]:
        limit = max(1, min(limit, _HISTORY_LIMIT))
        if self.mode == "gateway" and self.serve_url:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get(
                    f"{self.serve_url}/api/sessions/{quote(session_id, safe='')}/messages",
                    headers=self._gateway_headers(),
                    params={"limit": _HISTORY_LIMIT, "order": "latest", "include_compacted": "true", "inline_images": "false"},
                )
                if not res.is_success:
                    raise RuntimeError(f"Hermes Gateway 历史读取失败（HTTP {res.status_code}）")
                data = res.json()
                items = data.get("messages") if isinstance(data, dict) else data
                if not isinstance(items, list):
                    raise ValueError("Hermes Gateway 返回了无法识别的历史格式")
                return _gateway_history(items)[-limit:]
        proc = await self._ensure_acp()
        async with self._history_lock:
            if session_id not in self._turns:
                await self._load_acp_session(proc, session_id)
        return deepcopy(list(self._history.get(session_id, ()))[-limit:])

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
            if self.mode != "gateway" and (session_id not in self._loaded_sessions or session_id not in self._history):
                await self._load_acp_session(proc, session_id)
            self._turns[session_id] = (request_id, emit)
            self._approvals[session_id] = request_approval
        try:
            prompt_text = merge_prompt_with_attachments(text, attachments)
            requested_model = str((options or {}).get("model") or "")
            if requested_model and requested_model != self._current_model and self.mode != "gateway":
                # ACP 的模型切换是会话级的（session/set_model），必须在空闲且发送 prompt 之前完成。
                await proc.call("session/set_model", {"sessionId": session_id, "modelId": requested_model})
                self._current_model = requested_model
                self._current_effort = None  # 换模型会重建 agent，档位需按新路由重设
            requested_effort = str((options or {}).get("effort") or "").strip().lower()
            if requested_effort and requested_effort != self._current_effort and self.mode != "gateway":
                # 思考档位同样走会话级 config option（Hermes ACP 侧已经实现 reasoning_effort）。
                await proc.call(
                    "session/set_config_option",
                    {"sessionId": session_id, "configId": "reasoning_effort", "value": requested_effort},
                )
                self._current_effort = requested_effort
            messages = self._history.get(session_id, deque(maxlen=_HISTORY_LIMIT))
            self._save_history(session_id, messages)
            messages.append({"role": "user", "text": text, "runId": request_id})
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
            if isinstance(prompt_res, dict) and prompt_res.get("stopReason") in ("cancelled", "canceled"):
                await emit({"type": "Failed", "sessionId": session_id, "runId": request_id, "requestId": request_id,
                            "code": "cancelled", "message": "已中断当前 Hermes 任务"})
            else:
                await emit({"type": "Completed", "sessionId": session_id, "runId": request_id, "requestId": request_id})
        finally:
            self._turns.pop(session_id, None)
            self._approvals.pop(session_id, None)
            for key in [key for key in self._tool_starts if key[0] == session_id]:
                self._tool_starts.pop(key, None)

    async def cancel(self, *, session_id: str, run_id: str | None = None) -> None:
        if self._proc is not None:
            await self._proc.notify("session/cancel", {"sessionId": session_id})

    @staticmethod
    def _record_history_update(
        messages: deque[dict[str, Any]], kind: Any, text: Any,
        tool: dict[str, Any] | None, run_id: str | None,
    ) -> bool:
        if kind in ("user_message_chunk", "agent_message_chunk", "agent_thought_chunk"):
            if not isinstance(text, str) or not text or (kind == "user_message_chunk" and run_id):
                return False
            role = "user" if kind == "user_message_chunk" else "assistant"
        elif tool:
            role = "assistant"
        else:
            return False

        # Updates can arrive out of order across parallel tools. Keep the original call position.
        if kind == "tool_call_update" and tool:
            for message in reversed(messages):
                if message["role"] == "user":
                    break
                for call in message.get("toolCalls", []):
                    if call["callId"] == tool["callId"]:
                        call.update({k: v for k, v in tool.items() if v is not None})
                        return True

        if not messages or messages[-1]["role"] != role or messages[-1].get("runId") != run_id:
            message = {"role": role, "text": ""}
            if run_id:
                message["runId"] = run_id
            messages.append(message)
        message = messages[-1]
        if role == "user":
            message["text"] += text
            return True

        parts = message.setdefault("parts", [])
        if tool:
            message.setdefault("toolCalls", []).append({k: v for k, v in tool.items() if v is not None})
            parts.append({"type": "tool", "callId": tool["callId"]})
        else:
            part_type = "thought" if kind == "agent_thought_chunk" else "text"
            message[part_type] = message.get(part_type, "") + text
            if parts and parts[-1]["type"] == part_type:
                parts[-1]["text"] += text
            else:
                parts.append({"type": part_type, "text": text})
        return True

    async def _on_acp_update(self, method: str, params: dict[str, Any]) -> None:
        if method != "session/update":
            return
        sid = str(params.get("sessionId") or params.get("session_id") or "")
        replay = self._history_replays.get(sid)
        turn = self._turns.get(sid)
        upd = params.get("update")
        if (replay is None and turn is None) or not isinstance(upd, dict):
            return
        kind = upd.get("sessionUpdate") or upd.get("session_update")
        content = upd.get("content")
        text = content.get("text") if isinstance(content, dict) else None
        tool = None
        if kind in ("tool_call", "tool_call_update"):
            call_id = str(upd.get("toolCallId") or upd.get("tool_call_id") or uuid4().hex[:8])
            raw_status = str(upd.get("status") or "").lower()
            status = {"failed": "error", "error": "error", "completed": "completed"}.get(raw_status)
            if kind == "tool_call" and replay is None:
                self._tool_starts[sid, call_id] = time.monotonic()
            started = self._tool_starts.pop((sid, call_id), None) if status and replay is None else None
            output = None
            if isinstance(content, list):
                blocks = [block.get("content", block) for block in content if isinstance(block, dict)]
                output = "\n".join(str(block["text"]) for block in blocks if isinstance(block, dict) and block.get("text")) or None
            raw_output = upd.get("rawOutput", upd.get("raw_output"))
            if output is None and raw_output is not None:
                output = str(raw_output)
            tool = {
                "callId": call_id,
                "name": upd.get("title") or ("tool" if kind == "tool_call" else None),
                "status": status or ("running" if raw_status or kind == "tool_call" else None),
                "input": upd.get("rawInput", upd.get("raw_input")),
                "output": output,
                "durationMs": int((time.monotonic() - started) * 1000) if started is not None else None,
            }

        if replay is not None:
            if self._record_history_update(replay, kind, text, tool, None):
                self._history_updated[sid].set()
            return
        assert turn is not None
        request_id, send = turn
        messages = self._history.get(sid)
        if messages is not None:
            self._record_history_update(messages, kind, text, tool, request_id)

        async def emit(event: dict[str, Any]) -> None:
            await send({**event, "runId": request_id, "requestId": request_id})

        if kind in ("agent_thought_chunk", "agent_message_chunk") and text:
            event_type = "ThoughtDelta" if kind == "agent_thought_chunk" else "TextDelta"
            await emit({"type": event_type, "sessionId": sid, "text": text})
        elif tool:
            if kind == "tool_call":
                await emit({"type": "ToolCall", "sessionId": sid, "callId": tool["callId"], "name": tool["name"]})
            await emit(build_tool_call_update(
                session_id=sid, call_id=tool["callId"], name=tool["name"] or "tool",
                status=tool["status"] or "running", tool_input=tool["input"],
                output=tool["output"], duration_ms=tool["durationMs"],
            ))
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
