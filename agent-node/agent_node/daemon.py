"""AgentNode 守护进程主循环：连接 Core WSS、响应会话与审批指令、启动直传端点。"""

import asyncio
import json
import os
from pathlib import Path
import platform as py_platform
import re
import socket
import tempfile
from typing import Any
from uuid import uuid4

import uvicorn
import websockets

from .adapters.base import AgentAdapter, ApprovalCallback, EventEmitter
from .adapters.registry import build_adapter_registry
from .config import NodeConfig, PathOutsideAllowedRootsError, detect_lan_urls, ensure_allowed_path
from .crypto_chunks import generate_file_key
from .transfer import (
    DirectArtifactStore,
    create_direct_transfer_app,
    download_and_decrypt_artifact,
    publish_file_artifact,
)


class AgentNodeDaemon:
    """运行在每台受控机器上的轻量级节点守护进程（聊天正文仅驻留上游或内存）。"""

    def __init__(
        self,
        config: NodeConfig,
        *,
        adapters: dict[str, AgentAdapter] | None = None,
        staging_dir: Path | None = None,
    ) -> None:
        self.config = config
        self.adapters = adapters if adapters is not None else build_adapter_registry(config)
        self.staging_dir = staging_dir or (Path(tempfile.gettempdir()) / "studiolo-node-direct")
        self.direct_store = DirectArtifactStore(self.staging_dir) if config.direct.enabled else None
        self._pending_approvals: dict[str, asyncio.Future[str]] = {}
        self._session_always_allow: set[tuple[str, str]] = set()
        self._session_cwds: dict[tuple[str, str], Path] = {}
        self._send_lock = asyncio.Lock()

    async def probe_adapters(self) -> list[dict[str, Any]]:
        results = []
        for name, adapter in self.adapters.items():
            try:
                p = await adapter.probe()
                results.append({
                    "provider": p.provider,
                    "version": p.version,
                    "status": p.status,
                    "capabilities": [
                        *p.capabilities,
                        *(["deny-requests", "auto-approve"] if "approval" in p.capabilities else []),
                    ],
                })
            except Exception:
                results.append({"provider": name, "version": "", "status": "error", "capabilities": []})
        return results

    def build_transfer_endpoints(self) -> list[dict[str, Any]]:
        if not self.config.direct.enabled:
            return []
        eps: list[dict[str, Any]] = []
        for idx, url in enumerate(self.config.direct.advertise_urls):
            eps.append({"kind": "lan", "url": url.rstrip("/"), "priority": 5 + idx, "label": "Configured Direct"})
        for lan in detect_lan_urls(self.config.direct.port):
            eps.append({"kind": "lan", "url": lan, "priority": 15, "label": "LAN Direct"})
        return eps

    async def build_hello(self) -> dict[str, Any]:
        sys_map = {"Darwin": "macos", "Windows": "windows", "Linux": "linux"}
        return {
            "hostname": socket.gethostname(),
            "platform": sys_map.get(py_platform.system(), "linux"),
            "allowedRoots": [str(r) for r in self.config.allowed_roots],
            "adapters": await self.probe_adapters(),
            "transferEndpoints": self.build_transfer_endpoints(),
        }

    async def _send_ws(self, ws: Any, frame: dict[str, Any]) -> None:
        async with self._send_lock:
            await ws.send(json.dumps(frame, ensure_ascii=False))

    async def _request_approval(
        self,
        ws: Any,
        *,
        provider: str,
        session_id: str,
        call_id: str,
        command: str,
        risk: str,
    ) -> str:
        # 仅在同一节点本次活跃会话内允许用户显式选定的 "本会话允许"，默认全阻断审批
        if (provider, session_id) in self._session_always_allow:
            return "allow_session"
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[str] = loop.create_future()
        self._pending_approvals[call_id] = fut
        await self._send_ws(
            ws,
            {
                "type": "PermissionRequest",
                "provider": provider,
                "sessionId": session_id,
                "callId": call_id,
                "command": command,
                "risk": risk,
            },
        )
        try:
            decision = await asyncio.wait_for(fut, timeout=300.0)
        except asyncio.TimeoutError:
            decision = "deny"
        finally:
            self._pending_approvals.pop(call_id, None)
        if decision == "allow_session":
            self._session_always_allow.add((provider, session_id))
        return decision

    def _build_run_callbacks(
        self,
        ws: Any,
        *,
        provider: str,
        options: dict[str, Any],
    ) -> tuple[EventEmitter, ApprovalCallback]:
        async def on_event(evt: dict[str, Any]) -> None:
            await self._send_ws(ws, {"provider": provider, **evt})

        async def on_approval(s_id: str, call_id: str, command: str, risk: str) -> str:
            if options.get("denyRequests") or options.get("readOnly"):
                return "deny"
            if options.get("autoApprove"):
                return "allow_once"
            return await self._request_approval(
                ws, provider=provider, session_id=s_id, call_id=call_id, command=command, risk=risk
            )

        return on_event, on_approval

    async def _materialize_attachments(
        self,
        provider: str,
        session_id: str,
        attachments: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]] | None:
        """将前端上传并传入的 E2EE ArtifactRef 附件解密落盘至当前会话允许工作区下的 `.studiolo-inbox/`。"""
        if not attachments:
            return None
        base_dir = self._session_cwds.get((provider, session_id)) or self.config.allowed_roots[0]
        safe_base = ensure_allowed_path(base_dir, self.config.allowed_roots)
        inbox_dir = safe_base / ".studiolo-inbox"

        out: list[dict[str, Any]] = []
        for idx, raw in enumerate(attachments):
            if not isinstance(raw, dict):
                continue
            item = dict(raw)
            artifact_id = str(item.get("artifactId") or "")
            key_b64 = str(item.get("keyB64") or "")
            if artifact_id and key_b64:
                raw_name = Path(str(item.get("fileName") or f"attachment-{idx}")).name
                safe_name = re.sub(r"[^A-Za-z0-9._\-\u4e00-\u9fff]", "_", raw_name) or f"attachment-{idx}"
                prefix = re.sub(r"[^A-Za-z0-9_-]", "", artifact_id)[:8] or str(idx)
                dest = inbox_dir / f"{prefix}-{safe_name}"
                local_path = await download_and_decrypt_artifact(
                    core_url=self.config.core_url,
                    node_token=self.config.node_token,
                    artifact_ref=item,
                    destination=dest,
                    allowed_roots=self.config.allowed_roots,
                )
                item["localPath"] = str(local_path)
            out.append(item)
        return out or None

    async def publish_session_artifact(
        self,
        ws: Any,
        *,
        provider: str,
        session_id: str,
        file_path: Path,
        mime: str = "application/octet-stream",
        run_id: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """将节点工作区产物分块 AES-256-GCM 加密发布，并向控制台推送 `ArtifactOffered` 事件。"""
        key = generate_file_key()
        artifact_ref = await publish_file_artifact(
            core_url=self.config.core_url,
            node_token=self.config.node_token,
            file_path=file_path,
            allowed_roots=self.config.allowed_roots,
            key=key,
            mime=mime,
            direct_store=self.direct_store,
        )
        evt: dict[str, Any] = {
            "type": "ArtifactOffered",
            "provider": provider,
            "sessionId": session_id,
            "artifact": artifact_ref,
        }
        if run_id:
            evt["runId"] = run_id
        if request_id:
            evt["requestId"] = request_id
        await self._send_ws(ws, evt)
        return artifact_ref

    async def handle_command(self, ws: Any, frame: dict[str, Any]) -> None:
        cmd = str(frame.get("type") or "")
        req_id = frame.get("requestId")
        client_conn_id = frame.get("_clientConnId")
        provider = str(frame.get("provider") or "mock")
        adapter = self.adapters.get(provider)

        async def send_back(payload: dict[str, Any]) -> None:
            if client_conn_id and "_clientConnId" not in payload:
                payload["_clientConnId"] = client_conn_id
            if req_id and "requestId" not in payload:
                payload["requestId"] = req_id
            await self._send_ws(ws, payload)

        if cmd == "permission.respond":
            call_id = str(frame.get("callId") or "")
            decision = str(frame.get("decision") or "deny")
            if decision not in ("allow_once", "allow_session", "deny"):
                decision = "deny"
            fut = self._pending_approvals.get(call_id)
            if fut and not fut.done():
                fut.set_result(decision)
            return

        if adapter is None:
            await send_back({"type": "Failed", "code": "provider_unavailable", "message": f"Provider {provider} not enabled on node"})
            return

        try:
            if cmd == "models.list":
                try:
                    models = await adapter.list_models()
                    await send_back({"type": "ModelsSnapshot", "provider": provider, "models": models})
                except Exception:
                    await send_back({"type": "ModelsSnapshot", "provider": provider, "models": [], "message": "节点无法读取模型列表"})
            elif cmd == "sessions.list":
                items = await adapter.list_sessions(page=int(frame.get("page") or 1), limit=int(frame.get("limit") or 30))
                await send_back({"type": "SessionsSnapshot", "provider": provider, "sessions": items})
            elif cmd == "session.open":
                cwd = str(frame.get("cwd") or self.config.allowed_roots[0])
                meta = await adapter.open_session(
                    cwd=cwd,
                    session_id=frame.get("sessionId"),
                    use_worktree=bool(frame.get("useWorktree", False)),
                )
                opened_sid = str(meta.get("sessionId") or "")
                opened_dir = meta.get("worktreePath") or meta.get("cwd")
                if opened_sid and opened_dir:
                    self._session_cwds[(provider, opened_sid)] = Path(str(opened_dir))
                await send_back({"type": "SessionOpened", **meta})
            elif cmd == "session.history":
                sid = str(frame.get("sessionId") or "")
                msgs = await adapter.get_history(session_id=sid, limit=int(frame.get("limit") or 50))
                await send_back({"type": "SessionHistory", "provider": provider, "sessionId": sid, "messages": msgs})
            elif cmd == "prompt.send":
                sid = str(frame.get("sessionId") or "")
                text = str(frame.get("text") or "")
                raw_atts = frame.get("attachments") if isinstance(frame.get("attachments"), list) else None
                atts = await self._materialize_attachments(provider, sid, raw_atts)

                options = frame.get("options") or {}
                if options.get("readOnly") and provider not in ("codex", "mock"):
                    raise ValueError("当前适配器不支持只读沙箱")
                runtime = {k: options[k] for k in ("model", "effort", "readOnly") if options.get(k)}
                if runtime and provider not in ("opencode", "codex", "mock"):
                    raise ValueError("当前适配器不支持运行参数")

                on_event, on_approval = self._build_run_callbacks(ws, provider=provider, options=options)

                await adapter.send_prompt(
                    session_id=sid,
                    text=text,
                    request_id=str(req_id or uuid4().hex),
                    emit=on_event,
                    request_approval=on_approval,
                    attachments=atts,
                    **({"options": runtime} if runtime else {}),
                )
            elif cmd == "handoff.send":
                # 将上一节点/Agent 生成的摘要及 ArtifactRef 票据转交给当前节点执行，有密钥时同步解密落盘
                sid = str(frame.get("sessionId") or "")
                handoff_text = str(frame.get("summary") or frame.get("text") or "")
                raw_art = frame.get("artifact") if isinstance(frame.get("artifact"), dict) else None
                atts = await self._materialize_attachments(provider, sid, [raw_art] if raw_art else None)
                if raw_art and not (atts and atts[0].get("localPath")):
                    handoff_text += f"\n\n[Handoff Artifact: {raw_art.get('fileName')} id={raw_art.get('artifactId')}]"

                options = frame.get("options") or {}
                on_event, on_approval = self._build_run_callbacks(ws, provider=provider, options=options)
                await adapter.send_prompt(
                    session_id=sid,
                    text=handoff_text,
                    request_id=str(req_id or uuid4().hex),
                    emit=on_event,
                    request_approval=on_approval,
                    attachments=atts,
                )
            elif cmd == "prompt.cancel":
                await adapter.cancel(session_id=str(frame.get("sessionId") or ""), run_id=frame.get("runId"))
        except PathOutsideAllowedRootsError as err:
            await send_back({"type": "Failed", "code": "path_forbidden", "message": str(err)})
        except Exception as err:
            await send_back({"type": "Failed", "code": "node_execution_error", "provider": provider, "sessionId": frame.get("sessionId"), "message": str(err)})

    async def run_once(self) -> None:
        hello = await self.build_hello()
        async with websockets.connect(self.config.ws_url, open_timeout=10.0) as ws:
            await self._send_ws(ws, {"type": "auth", "token": self.config.node_token, "hello": hello})
            ready = json.loads(await ws.recv())
            if ready.get("type") != "NodeReady":
                raise RuntimeError(f"Unexpected handshake frame: {ready}")

            async def heartbeat_loop() -> None:
                while True:
                    await asyncio.sleep(30.0)
                    await self._send_ws(ws, {"type": "NodeHeartbeat", "adapters": await self.probe_adapters()})

            hb_task = asyncio.create_task(heartbeat_loop())
            bg_tasks: set[asyncio.Task[None]] = set()
            try:
                async for raw in ws:
                    frame = json.loads(raw)
                    if not isinstance(frame, dict):
                        continue
                    task = asyncio.create_task(self.handle_command(ws, frame))
                    bg_tasks.add(task)
                    task.add_done_callback(bg_tasks.discard)
            finally:
                hb_task.cancel()
                for t in list(bg_tasks):
                    t.cancel()

    async def run_forever(self) -> None:
        direct_server: uvicorn.Server | None = None
        direct_task: asyncio.Task[None] | None = None
        if self.direct_store is not None:
            app = create_direct_transfer_app(self.direct_store)
            uv_cfg = uvicorn.Config(
                app,
                host=self.config.direct.bind_host,
                port=self.config.direct.port,
                log_level="warning",
            )
            direct_server = uvicorn.Server(uv_cfg)
            direct_task = asyncio.create_task(direct_server.serve())

        backoff = 1.0
        try:
            while True:
                try:
                    await self.run_once()
                    backoff = 1.0
                except Exception:
                    await asyncio.sleep(backoff)
                    backoff = min(30.0, backoff * 2.0)
        finally:
            if direct_server is not None:
                direct_server.should_exit = True
            if direct_task is not None:
                await direct_task
