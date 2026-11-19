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

    # ---------------- OpenClaw 原生 CronPort 适配 ----------------

    def cron_capabilities(self) -> dict[str, Any]:
        return {
            "supported": True,
            "canCreate": True,
            "canUpdate": True,
            "canDelete": True,
            "canPause": True,
            "canRunNow": True,
            "historyMode": "paginated",
            "supportsProfiles": False,
        }

    def _normalize_cron_job(self, raw: dict[str, Any]) -> dict[str, Any]:
        schedule_raw = raw.get("schedule") if isinstance(raw.get("schedule"), dict) else {}
        expr = str(raw.get("cron") or schedule_raw.get("expr") or schedule_raw.get("cron") or "")
        kind = str(schedule_raw.get("kind") or ("cron" if expr else "interval"))
        tz = str(raw.get("timezone") or schedule_raw.get("tz") or schedule_raw.get("timezone") or "UTC")
        return {
            "nativeJobId": str(raw.get("id") or raw.get("jobId") or ""),
            "ownerProfile": str(raw.get("profile") or "default"),
            "name": str(raw.get("name") or raw.get("title") or raw.get("id") or "OpenClaw Cron"),
            "description": str(raw.get("description") or ""),
            "enabled": bool(raw.get("enabled", True)) and not bool(raw.get("paused", False)),
            "scheduleKind": kind,
            "scheduleExpression": expr or str(schedule_raw.get("every") or schedule_raw.get("at") or ""),
            "timezone": tz,
            "nextRunAt": raw.get("nextRunAt") or raw.get("next_run_at"),
            "lastRunAt": raw.get("lastRunAt") or raw.get("last_run_at"),
            "lastStatus": str(raw.get("lastStatus") or raw.get("last_status") or "unknown"),
            "nativeRevision": str(raw.get("revision") or raw.get("version") or ""),
            "capabilities": self.cron_capabilities(),
        }

    async def cron_list(self, *, profile: str | None = None) -> list[dict[str, Any]]:
        res = await self._rpc("cron.list", {})
        items = res if isinstance(res, list) else (res or {}).get("jobs") or []
        return [self._normalize_cron_job(j) for j in items if isinstance(j, dict)]

    async def cron_create(self, payload: dict[str, Any]) -> dict[str, Any]:
        rpc_params = {
            "name": str(payload.get("name") or "").strip(),
            "description": str(payload.get("description") or ""),
            "enabled": bool(payload.get("enabled", True)),
            "schedule": {
                "kind": str(payload.get("scheduleKind") or "cron"),
                "expr": str(payload.get("scheduleExpression") or ""),
                "tz": str(payload.get("timezone") or "Asia/Shanghai"),
            },
            "prompt": str(payload.get("prompt") or ""),
        }
        res = await self._rpc("cron.add", rpc_params)
        job = res.get("job", res) if isinstance(res, dict) else {}
        return self._normalize_cron_job(job if isinstance(job, dict) else {})

    async def cron_update(self, *, native_job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        patch: dict[str, Any] = {"id": native_job_id}
        for key in ("name", "description", "enabled", "prompt"):
            if key in payload and payload[key] is not None:
                patch[key] = payload[key]
        if payload.get("scheduleExpression") or payload.get("timezone") or payload.get("scheduleKind"):
            patch["schedule"] = {
                "kind": str(payload.get("scheduleKind") or "cron"),
                "expr": str(payload.get("scheduleExpression") or ""),
                "tz": str(payload.get("timezone") or "Asia/Shanghai"),
            }
        if payload.get("expectedRevision"):
            patch["expectedRevision"] = str(payload["expectedRevision"])
        res = await self._rpc("cron.update", patch)
        job = res.get("job", res) if isinstance(res, dict) else {}
        return self._normalize_cron_job(job if isinstance(job, dict) else {"id": native_job_id})

    async def cron_delete(self, *, native_job_id: str, profile: str | None = None) -> None:
        await self._rpc("cron.remove", {"id": native_job_id})

    async def cron_pause(self, *, native_job_id: str, paused: bool, profile: str | None = None) -> dict[str, Any]:
        res = await self._rpc("cron.update", {"id": native_job_id, "enabled": not paused})
        job = res.get("job", res) if isinstance(res, dict) else {"id": native_job_id, "enabled": not paused}
        return self._normalize_cron_job(job if isinstance(job, dict) else {"id": native_job_id, "enabled": not paused})

    async def cron_run_now(
        self,
        *,
        native_job_id: str,
        request_id: str,
        profile: str | None = None,
    ) -> dict[str, Any]:
        res = await self._rpc("cron.run", {"id": native_job_id, "idempotencyKey": request_id})
        data = res if isinstance(res, dict) else {}
        return {
            "nativeRunId": str(data.get("runId") or data.get("id") or request_id),
            "status": str(data.get("status") or "queued"),
            "nativeStatus": str(data.get("status") or "queued"),
            "startedAt": data.get("startedAt"),
            "finishedAt": data.get("finishedAt"),
            "summary": str(data.get("summary") or ""),
        }

    async def cron_list_runs(
        self,
        *,
        native_job_id: str,
        limit: int = 20,
        profile: str | None = None,
    ) -> list[dict[str, Any]]:
        capped = max(1, min(int(limit), 100))
        res = await self._rpc("cron.runs", {"id": native_job_id, "limit": capped})
        rows = res if isinstance(res, list) else (res or {}).get("runs") or []
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
                    "nativeRunId": str(row.get("runId") or row.get("id") or ""),
                    "scheduledAt": row.get("scheduledAt") or row.get("scheduled_at"),
                    "startedAt": row.get("startedAt") or row.get("started_at"),
                    "finishedAt": row.get("finishedAt") or row.get("finished_at"),
                    "status": norm_st,
                    "nativeStatus": raw_st,
                    "summary": str(row.get("summary") or row.get("error") or ""),
                }
            )
        return out
