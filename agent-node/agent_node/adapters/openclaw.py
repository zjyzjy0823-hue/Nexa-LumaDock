"""OpenClaw Gateway 对话与会话适配器（通过 WebSocket 与网关交互，不持久化历史正文）。"""

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import websockets

from .base import (
    AdapterProbe,
    AgentAdapter,
    ApprovalCallback,
    EventEmitter,
    build_tool_call_update,
    merge_prompt_with_attachments,
    prepare_session_dir,
)


class OpenClawAdapter(AgentAdapter):
    provider = "openclaw"

    def __init__(
        self,
        allowed_roots: tuple[Path, ...],
        *,
        gateway_url: str = "ws://127.0.0.1:18789",
        token: str | None = None,
    ) -> None:
        self.allowed_roots = allowed_roots
        self.gateway_url = gateway_url
        self.token = token

    async def probe(self) -> AdapterProbe:
        caps = ("chat", "history", "cron", "files", "diff", "checkpoints")
        try:
            async with websockets.connect(self.gateway_url, open_timeout=2.0):
                return AdapterProbe(provider=self.provider, version="gateway-ws", status="ready", capabilities=caps)
        except Exception:
            return AdapterProbe(provider=self.provider, version="", status="unavailable", capabilities=caps)

    async def _rpc(self, method: str, params: dict[str, Any]) -> Any:
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else None
        async with websockets.connect(self.gateway_url, additional_headers=headers, open_timeout=4.0) as ws:
            req_id = str(uuid4())
            await ws.send(json.dumps({"type": "req", "id": req_id, "method": method, "params": params}))
            while True:
                raw = await ws.recv()
                frame = json.loads(raw)
                if frame.get("type") == "res" and frame.get("id") == req_id:
                    if not frame.get("ok"):
                        raise RuntimeError(str(frame.get("error") or "OpenClaw Gateway error"))
                    return frame.get("payload")

    async def list_sessions(self, *, page: int = 1, limit: int = 30) -> list[dict[str, Any]]:
        res = await self._rpc("sessions.list", {"limit": limit})
        rows = (res or {}).get("sessions") or []
        return [{"sessionId": s.get("key") or s.get("id"), "provider": self.provider, "title": s.get("title") or s.get("key")} for s in rows]

    async def open_session(self, *, cwd: str, session_id: str | None = None, use_worktree: bool = False) -> dict[str, Any]:
        sid = session_id or f"main-{uuid4().hex[:6]}"
        eff_cwd, wt = prepare_session_dir(cwd, self.allowed_roots, session_id=sid, use_worktree=use_worktree)
        return {"sessionId": sid, "provider": self.provider, "cwd": str(eff_cwd), "worktreePath": wt, "title": f"OpenClaw ({sid})"}

    async def get_history(self, *, session_id: str, limit: int = 50) -> list[dict[str, Any]]:
        res = await self._rpc("chat.history", {"sessionKey": session_id, "limit": limit})
        msgs = (res or {}).get("messages") or []
        return [{"role": m.get("role", "assistant"), "text": m.get("text", "")} for m in msgs[-limit:]]

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
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else None
        async with websockets.connect(self.gateway_url, additional_headers=headers, open_timeout=5.0) as ws:
            req_id = str(uuid4())
            await ws.send(json.dumps({
                "type": "req",
                "id": req_id,
                "method": "chat.send",
                "params": {"sessionKey": session_id, "text": merge_prompt_with_attachments(text, attachments), "idempotencyKey": request_id},
            }))
            await emit({"type": "Accepted", "sessionId": session_id, "runId": request_id, "requestId": request_id, "provider": self.provider})
            while True:
                frame = json.loads(await ws.recv())
                if frame.get("type") == "event":
                    payload = frame.get("payload") or {}
                    ev_name = frame.get("event")
                    if ev_name == "chat.delta":
                        await emit({"type": "TextDelta", "sessionId": session_id, "runId": request_id, "text": str(payload.get("delta") or "")})
                    elif ev_name in ("tool.started", "tool.completed", "tool.failed"):
                        st = "error" if ev_name == "tool.failed" else "completed" if ev_name == "tool.completed" else "running"
                        await emit(
                            build_tool_call_update(
                                session_id=session_id,
                                call_id=str(payload.get("callId") or payload.get("id") or uuid4().hex[:8]),
                                name=str(payload.get("name") or "tool"),
                                status=st,
                                run_id=request_id,
                                request_id=request_id,
                                tool_input=payload.get("input"),
                                output=str(payload.get("output")) if payload.get("output") is not None else None,
                                error=str(payload.get("error")) if payload.get("error") else None,
                            )
                        )
                    elif ev_name == "chat.completed":
                        await emit({"type": "Completed", "sessionId": session_id, "runId": request_id, "requestId": request_id})
                        return

    async def cancel(self, *, session_id: str, run_id: str | None = None) -> None:
        await self._rpc("chat.abort", {"sessionKey": session_id})
