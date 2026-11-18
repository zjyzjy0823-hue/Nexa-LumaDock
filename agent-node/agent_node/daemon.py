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
from .terminal_session import TerminalManager
from .transfer import (
    DirectArtifactStore,
    create_direct_transfer_app,
    download_and_decrypt_artifact,
    publish_file_artifact,
)
from .workspace_tools import (
    create_git_checkpoint,
    get_workspace_diff,
    git_commit_changes,
    list_workspace_files,
    list_workspace_tree,
    load_workspace_rules,
    merge_worktree_to_base,
    read_workspace_file,
    restore_git_checkpoint,
    revert_diff_hunk,
    revert_workspace_files,
)
from .worktree import remove_session_worktree


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
        self.terminal_manager = TerminalManager(config.allowed_roots)
        self._pending_approvals: dict[str, asyncio.Future[str]] = {}
        self._pending_approval_cmds: dict[str, str] = {}
        self._session_always_allow: set[tuple[str, str]] = set()
        self._trust_file = self.staging_dir / "trust-allowlist.json"
        self._trust_patterns: list[str] = self._load_trust_patterns()
        self._session_cwds: dict[tuple[str, str], Path] = {}
        self._session_worktrees: dict[tuple[str, str], tuple[Path, Path]] = {}
        self._checkpoints: dict[tuple[str, str, str], dict[str, Any]] = {}
        self._checkpoint_order: dict[tuple[str, str], list[str]] = {}
        self._active_runs: set[tuple[str, str]] = set()
        self._run_buffers: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self._send_lock = asyncio.Lock()

    def _load_trust_patterns(self) -> list[str]:
        try:
            if self._trust_file.is_file():
                data = json.loads(self._trust_file.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    return [str(x).strip() for x in data if isinstance(x, str) and x.strip()][:100]
        except Exception:
            pass
        return []

    def _save_trust_patterns(self) -> None:
        try:
            self.staging_dir.mkdir(parents=True, exist_ok=True)
            self._trust_file.write_text(json.dumps(self._trust_patterns, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    @staticmethod
    def _derive_trust_prefix(command: str) -> str:
        clean = " ".join(str(command or "").strip().split())
        if not clean or any(tok in clean for tok in ("&&", "||", ";", "|", "$(", "`", "\n", "\r", ">", "<")):
            return ""
        parts = clean.split(" ")
        head = parts[0].lower()
        if head in ("npm", "pnpm", "yarn", "git", "python", "python3", "cargo", "go") and len(parts) >= 2:
            return f"{parts[0]} {parts[1]}"
        return parts[0]

    def _is_command_trusted(self, command: str) -> bool:
        clean = " ".join(str(command or "").strip().split())
        if not clean or not self._trust_patterns:
            return False
        if any(tok in clean for tok in ("&&", "||", ";", "|", "$(", "`", "\n", "\r", ">", "<")):
            return False
        lower_cmd = clean.lower()
        for pat in self._trust_patterns:
            p = " ".join(pat.strip().lower().split())
            if not p:
                continue
            if lower_cmd == p or lower_cmd.startswith(f"{p} "):
                return True
        return False

    def _resolve_session_dir(
        self,
        provider: str,
        session_id: str | None = None,
        fallback_cwd: Any = None,
    ) -> Path:
        if session_id and (provider, session_id) in self._session_cwds:
            return ensure_allowed_path(self._session_cwds[(provider, session_id)], self.config.allowed_roots)
        if fallback_cwd:
            return ensure_allowed_path(str(fallback_cwd), self.config.allowed_roots)
        return ensure_allowed_path(self.config.allowed_roots[0], self.config.allowed_roots)

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
        if risk != "high" and self._is_command_trusted(command):
            return "allow_once"
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[str] = loop.create_future()
        self._pending_approvals[call_id] = fut
        self._pending_approval_cmds[call_id] = command
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
            self._pending_approval_cmds.pop(call_id, None)
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
            if decision == "allow_trust":
                raw_pat = str(frame.get("trustPattern") or "") or self._derive_trust_prefix(
                    self._pending_approval_cmds.get(call_id, "")
                )
                clean_pat = " ".join(raw_pat.strip().split())
                if clean_pat and not any(tok in clean_pat for tok in ("&&", "||", ";", "|", "$(", "`", "\n", "\r", ">", "<")):
                    if clean_pat not in self._trust_patterns:
                        self._trust_patterns = [*self._trust_patterns, clean_pat][-100:]
                        self._save_trust_patterns()
                        await self._send_ws(ws, {"type": "TrustPolicySnapshot", "patterns": list(self._trust_patterns)})
                decision = "allow_once"
            elif decision not in ("allow_once", "allow_session", "deny"):
                decision = "deny"
            fut = self._pending_approvals.get(call_id)
            if fut and not fut.done():
                fut.set_result(decision)
            return

        if cmd == "trust.list":
            await send_back({"type": "TrustPolicySnapshot", "patterns": list(self._trust_patterns)})
            return
        if cmd == "trust.add":
            pat = " ".join(str(frame.get("pattern") or "").strip().split())
            if not pat or any(tok in pat for tok in ("&&", "||", ";", "|", "$(", "`", "\n", "\r", ">", "<")):
                await send_back({"type": "Failed", "code": "invalid_trust_pattern", "message": "安全策略不允许包含管道或连接符的白名单前缀"})
                return
            if pat not in self._trust_patterns:
                self._trust_patterns = [*self._trust_patterns, pat][-100:]
                self._save_trust_patterns()
            await self._send_ws(ws, {"type": "TrustPolicySnapshot", "patterns": list(self._trust_patterns)})
            return
        if cmd == "trust.remove":
            pat = " ".join(str(frame.get("pattern") or "").strip().split())
            self._trust_patterns = [p for p in self._trust_patterns if p != pat]
            self._save_trust_patterns()
            await self._send_ws(ws, {"type": "TrustPolicySnapshot", "patterns": list(self._trust_patterns)})
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
            elif cmd == "agents.list":
                agents = await adapter.list_agents()
                await send_back({"type": "AgentsSnapshot", "provider": provider, "agents": agents})
            elif cmd == "mcp.list":
                servers = await adapter.list_mcp_servers()
                await send_back({"type": "McpSnapshot", "provider": provider, "servers": servers})
            elif cmd == "rules.list":
                sid = str(frame.get("sessionId") or "")
                target_dir = self._resolve_session_dir(provider, sid or None, frame.get("cwd"))
                rules = await asyncio.to_thread(load_workspace_rules, target_dir, self.config.allowed_roots)
                await send_back(
                    {
                        "type": "RulesSnapshot",
                        "provider": provider,
                        **({"sessionId": sid} if sid else {}),
                        "cwd": str(target_dir),
                        "rules": rules,
                    }
                )
            elif cmd == "file.read":
                sid = str(frame.get("sessionId") or "")
                rel_path = str(frame.get("path") or "").strip()
                if not rel_path:
                    raise ValueError("文件路径不能为空")
                target_dir = self._resolve_session_dir(provider, sid or None, frame.get("cwd"))
                file_data = await asyncio.to_thread(
                    read_workspace_file, target_dir, self.config.allowed_roots, rel_path
                )
                await send_back(
                    {
                        "type": "FileContentSnapshot",
                        "provider": provider,
                        **({"sessionId": sid} if sid else {}),
                        **file_data,
                    }
                )
            elif cmd == "session.subscribe":
                sid = str(frame.get("sessionId") or "")
                key = (provider, sid)
                is_active = key in self._active_runs
                buffered = list(self._run_buffers.get(key, [])) if is_active else []
                await send_back(
                    {
                        "type": "SessionStreamReplay",
                        "provider": provider,
                        "sessionId": sid,
                        "active": is_active,
                        "events": buffered,
                    }
                )
            elif cmd == "form.reply":
                sid = str(frame.get("sessionId") or "")
                form_id = str(frame.get("formId") or "")
                if not sid or not form_id:
                    raise ValueError("缺少表单 ID 或会话 ID")
                cancelled = bool(frame.get("cancelled", False))
                reply_res = await adapter.reply_form(
                    session_id=sid,
                    form_id=form_id,
                    answer=frame.get("answer") if isinstance(frame.get("answer"), dict) else None,
                    cancel=cancelled,
                )
                await self._send_ws(
                    ws,
                    {
                        "type": "FormResolved",
                        "provider": provider,
                        "sessionId": sid,
                        "formId": form_id,
                        "cancelled": cancelled,
                        **(reply_res or {}),
                    },
                )
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
                if opened_sid and meta.get("worktreePath"):
                    self._session_worktrees[(provider, opened_sid)] = (
                        ensure_allowed_path(cwd, self.config.allowed_roots),
                        Path(str(meta["worktreePath"])),
                    )
                await send_back({"type": "SessionOpened", **meta})
            elif cmd == "session.history":
                sid = str(frame.get("sessionId") or "")
                msgs = await adapter.get_history(session_id=sid, limit=int(frame.get("limit") or 50))
                await send_back({"type": "SessionHistory", "provider": provider, "sessionId": sid, "messages": msgs})
            elif cmd == "files.list":
                sid = str(frame.get("sessionId") or "")
                target_dir = self._resolve_session_dir(provider, sid or None, frame.get("cwd"))
                query = str(frame.get("query") or "")
                limit = min(200, max(1, int(frame.get("limit") or 60)))
                files = await asyncio.to_thread(
                    list_workspace_files, target_dir, self.config.allowed_roots, query=query, limit=limit
                )
                await send_back(
                    {
                        "type": "FilesSnapshot",
                        "provider": provider,
                        **({"sessionId": sid} if sid else {}),
                        "cwd": str(target_dir),
                        "files": files,
                    }
                )
            elif cmd == "files.tree":
                sid = str(frame.get("sessionId") or "")
                target_dir = self._resolve_session_dir(provider, sid or None, frame.get("cwd"))
                rel_dir = str(frame.get("relDir") or "")
                tree_data = await asyncio.to_thread(
                    list_workspace_tree, target_dir, self.config.allowed_roots, rel_dir=rel_dir
                )
                await send_back(
                    {
                        "type": "FilesTreeSnapshot",
                        "provider": provider,
                        **({"sessionId": sid} if sid else {}),
                        "cwd": str(target_dir),
                        **tree_data,
                    }
                )
            elif cmd == "session.diff":
                sid = str(frame.get("sessionId") or "")
                target_dir = self._resolve_session_dir(provider, sid or None, frame.get("cwd"))
                cp_id = str(frame.get("checkpointId") or "")
                cp = self._checkpoints.get((provider, sid, cp_id)) if cp_id else None
                base_tree = cp["beforeTree"] if cp else None
                target_tree = cp["afterTree"] if cp else None
                if cp:
                    target_dir = ensure_allowed_path(cp["cwd"], self.config.allowed_roots)
                diff_data = await asyncio.to_thread(
                    get_workspace_diff,
                    target_dir,
                    self.config.allowed_roots,
                    base_tree=base_tree,
                    target_tree=target_tree,
                )
                await send_back(
                    {
                        "type": "DiffSnapshot",
                        "provider": provider,
                        **({"sessionId": sid} if sid else {}),
                        "cwd": str(target_dir),
                        "perTurn": bool(cp_id),
                        **diff_data,
                    }
                )
            elif cmd == "checkpoint.revert":
                sid = str(frame.get("sessionId") or "")
                cp_id = str(frame.get("checkpointId") or "")
                if not cp_id:
                    order = self._checkpoint_order.get((provider, sid), [])
                    cp_id = order[-1] if order else ""
                cp = self._checkpoints.get((provider, sid, cp_id)) if cp_id else None
                if cp is None:
                    raise ValueError("未找到可回滚的检查点（可能为非 Git 目录或本轮未产生文件修改）")
                cp_dir = ensure_allowed_path(cp["cwd"], self.config.allowed_roots)
                restored_files = await asyncio.to_thread(
                    restore_git_checkpoint, cp_dir, self.config.allowed_roots, str(cp["beforeTree"])
                )
                await send_back(
                    {
                        "type": "CheckpointReverted",
                        "provider": provider,
                        "sessionId": sid,
                        "checkpointId": cp["checkpointId"],
                        "restoredFiles": restored_files,
                    }
                )
                diff_after = await asyncio.to_thread(get_workspace_diff, cp_dir, self.config.allowed_roots)
                await self._send_ws(
                    ws,
                    {
                        "type": "DiffSnapshot",
                        "provider": provider,
                        "sessionId": sid,
                        "cwd": str(cp_dir),
                        "perTurn": False,
                        **diff_after,
                    },
                )
            elif cmd == "files.revert":
                sid = str(frame.get("sessionId") or "")
                raw_paths = frame.get("paths")
                if not isinstance(raw_paths, list) or not raw_paths:
                    raise ValueError("请指定要撤销的文件路径")
                paths = [str(p) for p in raw_paths if isinstance(p, str) and p.strip()]
                cp_id = str(frame.get("checkpointId") or "")
                cp = self._checkpoints.get((provider, sid, cp_id)) if cp_id else None
                target_dir = (
                    ensure_allowed_path(cp["cwd"], self.config.allowed_roots)
                    if cp
                    else self._resolve_session_dir(provider, sid or None, frame.get("cwd"))
                )
                restored_files = await asyncio.to_thread(
                    revert_workspace_files,
                    target_dir,
                    self.config.allowed_roots,
                    paths,
                    checkpoint_tree=str(cp["beforeTree"]) if cp else None,
                )
                await send_back(
                    {
                        "type": "CheckpointReverted",
                        "provider": provider,
                        "sessionId": sid,
                        "checkpointId": cp["checkpointId"] if cp else "head",
                        "restoredFiles": restored_files,
                    }
                )
                diff_after = await asyncio.to_thread(get_workspace_diff, target_dir, self.config.allowed_roots)
                await self._send_ws(
                    ws,
                    {
                        "type": "DiffSnapshot",
                        "provider": provider,
                        "sessionId": sid,
                        "cwd": str(target_dir),
                        "perTurn": False,
                        **diff_after,
                    },
                )
            elif cmd == "diff.revert_hunk":
                sid = str(frame.get("sessionId") or "")
                rel_path = str(frame.get("path") or "")
                hunk_patch = str(frame.get("patch") or "")
                target_dir = self._resolve_session_dir(provider, sid or None, frame.get("cwd"))
                restored_files = await asyncio.to_thread(
                    revert_diff_hunk, target_dir, self.config.allowed_roots, rel_path, hunk_patch
                )
                await send_back(
                    {
                        "type": "CheckpointReverted",
                        "provider": provider,
                        "sessionId": sid,
                        "checkpointId": "hunk",
                        "restoredFiles": restored_files,
                    }
                )
                diff_after = await asyncio.to_thread(get_workspace_diff, target_dir, self.config.allowed_roots)
                await self._send_ws(
                    ws,
                    {
                        "type": "DiffSnapshot",
                        "provider": provider,
                        "sessionId": sid,
                        "cwd": str(target_dir),
                        "perTurn": False,
                        **diff_after,
                    },
                )
            elif cmd == "git.commit":
                sid = str(frame.get("sessionId") or "")
                commit_msg = str(frame.get("message") or "").strip()
                raw_paths = frame.get("paths") if isinstance(frame.get("paths"), list) else None
                target_dir = self._resolve_session_dir(provider, sid or None, frame.get("cwd"))
                commit_res = await asyncio.to_thread(
                    git_commit_changes,
                    target_dir,
                    self.config.allowed_roots,
                    commit_msg,
                    paths=[str(p) for p in raw_paths] if raw_paths else None,
                )
                await send_back(
                    {
                        "type": "GitCommitted",
                        "provider": provider,
                        "sessionId": sid,
                        **commit_res,
                    }
                )
                diff_after = await asyncio.to_thread(get_workspace_diff, target_dir, self.config.allowed_roots)
                await self._send_ws(
                    ws,
                    {
                        "type": "DiffSnapshot",
                        "provider": provider,
                        "sessionId": sid,
                        "cwd": str(target_dir),
                        "perTurn": False,
                        **diff_after,
                    },
                )
            elif cmd == "terminal.open":
                sid = str(frame.get("sessionId") or "")
                target_dir = self._resolve_session_dir(provider, sid or None, frame.get("cwd"))

                async def _term_emit(evt: dict[str, Any]) -> None:
                    await self._send_ws(ws, {"provider": provider, **evt})

                opened = await self.terminal_manager.open_terminal(
                    cwd=target_dir, session_id=sid, emit=_term_emit
                )
                await send_back({"type": "TerminalOpened", "provider": provider, **opened})
            elif cmd == "terminal.input":
                tid = str(frame.get("terminalId") or "")
                data = str(frame.get("data") or "")
                await self.terminal_manager.send_input(tid, data)
            elif cmd == "terminal.close":
                tid = str(frame.get("terminalId") or "")
                sid = str(frame.get("sessionId") or "")
                if await self.terminal_manager.close_terminal(tid):
                    await self._send_ws(
                        ws, {"type": "TerminalClosed", "provider": provider, "sessionId": sid, "terminalId": tid}
                    )
            elif cmd == "worktree.merge":
                sid = str(frame.get("sessionId") or "")
                pair = self._session_worktrees.get((provider, sid))
                if pair is None:
                    raise ValueError("当前会话未使用独立 Git Worktree 沙箱")
                base_dir, wt_dir = pair
                merge_res = await asyncio.to_thread(
                    merge_worktree_to_base, base_dir, wt_dir, self.config.allowed_roots
                )
                await send_back(
                    {
                        "type": "WorktreeMerged",
                        "provider": provider,
                        "sessionId": sid,
                        **merge_res,
                    },
                )
                diff_after = await asyncio.to_thread(get_workspace_diff, base_dir, self.config.allowed_roots)
                await self._send_ws(
                    ws,
                    {
                        "type": "DiffSnapshot",
                        "provider": provider,
                        "sessionId": sid,
                        "cwd": str(base_dir),
                        "perTurn": False,
                        **diff_after,
                    },
                )
            elif cmd == "session.rename":
                sid = str(frame.get("sessionId") or "")
                title = str(frame.get("title") or "").strip()
                if not sid or not title:
                    raise ValueError("会话 ID 与标题不能为空")
                renamed = await adapter.rename_session(session_id=sid, title=title)
                await send_back(
                    {
                        "type": "SessionRenamed",
                        "provider": provider,
                        "sessionId": sid,
                        "title": str((renamed or {}).get("title") or title),
                    }
                )
            elif cmd == "session.delete":
                sid = str(frame.get("sessionId") or "")
                if not sid:
                    raise ValueError("缺少会话 ID")
                await adapter.delete_session(session_id=sid)
                wt_pair = self._session_worktrees.pop((provider, sid), None)
                if wt_pair is not None:
                    try:
                        await asyncio.to_thread(
                            remove_session_worktree, wt_pair[0], wt_pair[1], self.config.allowed_roots
                        )
                    except Exception:
                        pass
                self._session_cwds.pop((provider, sid), None)
                self._session_always_allow.discard((provider, sid))
                await send_back({"type": "SessionDeleted", "provider": provider, "sessionId": sid})
            elif cmd == "session.compact":
                sid = str(frame.get("sessionId") or "")
                if not sid:
                    raise ValueError("缺少会话 ID")
                res = await adapter.compact_session(session_id=sid)
                await send_back(
                    {
                        "type": "SessionCompacted",
                        "provider": provider,
                        "sessionId": sid,
                        **(res or {"supported": False}),
                    }
                )
            elif cmd in ("prompt.send", "handoff.send"):
                sid = str(frame.get("sessionId") or "")
                options = frame.get("options") or {}
                if options.get("readOnly") and provider not in ("codex", "mock"):
                    raise ValueError("当前适配器不支持只读沙箱")
                runtime = {k: options[k] for k in ("model", "effort", "readOnly", "agent") if options.get(k)}

                if cmd == "prompt.send":
                    text = str(frame.get("text") or "")
                    raw_atts = frame.get("attachments") if isinstance(frame.get("attachments"), list) else None
                    atts = await self._materialize_attachments(provider, sid, raw_atts)
                else:
                    # 将上一节点/Agent 生成的摘要及 ArtifactRef 票据转交给当前节点执行，有密钥时同步解密落盘
                    text = str(frame.get("summary") or frame.get("text") or "")
                    raw_art = frame.get("artifact") if isinstance(frame.get("artifact"), dict) else None
                    atts = await self._materialize_attachments(provider, sid, [raw_art] if raw_art else None)
                    if raw_art and not (atts and atts[0].get("localPath")):
                        text += f"\n\n[Handoff Artifact: {raw_art.get('fileName')} id={raw_art.get('artifactId')}]"

                eff_req_id = str(req_id or uuid4().hex)
                session_dir = self._resolve_session_dir(provider, sid or None, frame.get("cwd"))
                before_tree = await asyncio.to_thread(
                    create_git_checkpoint, session_dir, self.config.allowed_roots
                )
                base_emit, on_approval = self._build_run_callbacks(ws, provider=provider, options=options)
                turn_state: dict[str, Any] = {"runId": None, "checkpointed": False}
                run_key = (provider, sid)
                self._active_runs.add(run_key)
                self._run_buffers[run_key] = []

                async def wrapped_emit(evt: dict[str, Any]) -> None:
                    if evt.get("runId"):
                        turn_state["runId"] = str(evt["runId"])
                    # 缓存最近 250 帧流式事件，供前端断线重连或刷新页面后无缝续接输出
                    buf = self._run_buffers.get(run_key)
                    if buf is not None:
                        buf.append(dict(evt))
                        if len(buf) > 250:
                            del buf[: len(buf) - 250]
                    if evt.get("type") == "Completed" and not turn_state["checkpointed"]:
                        turn_state["checkpointed"] = True
                        if before_tree and not options.get("readOnly"):
                            after_tree = await asyncio.to_thread(
                                create_git_checkpoint, session_dir, self.config.allowed_roots
                            )
                            if after_tree and after_tree != before_tree:
                                cp_id = f"cp-{uuid4().hex[:8]}"
                                diff_data = await asyncio.to_thread(
                                    get_workspace_diff,
                                    session_dir,
                                    self.config.allowed_roots,
                                    base_tree=before_tree,
                                    target_tree=after_tree,
                                )
                                run_id_eff = turn_state["runId"] or str(evt.get("runId") or "")
                                self._checkpoints[(provider, sid, cp_id)] = {
                                    "checkpointId": cp_id,
                                    "provider": provider,
                                    "sessionId": sid,
                                    "cwd": str(session_dir),
                                    "beforeTree": before_tree,
                                    "afterTree": after_tree,
                                    "runId": run_id_eff,
                                    "requestId": eff_req_id,
                                    "summary": diff_data.get("summary") or {},
                                }
                                self._checkpoint_order.setdefault((provider, sid), []).append(cp_id)
                                await base_emit(
                                    {
                                        "type": "CheckpointCreated",
                                        "sessionId": sid,
                                        "checkpointId": cp_id,
                                        **({"runId": run_id_eff} if run_id_eff else {}),
                                        "requestId": eff_req_id,
                                        "summary": diff_data.get("summary") or {},
                                    }
                                )
                                await base_emit(
                                    {
                                        "type": "DiffSnapshot",
                                        "sessionId": sid,
                                        **({"runId": run_id_eff} if run_id_eff else {}),
                                        "cwd": str(session_dir),
                                        "perTurn": True,
                                        **diff_data,
                                    }
                                )
                    await base_emit(evt)

                extra_kwargs = {"options": runtime} if runtime else {}
                try:
                    await adapter.send_prompt(
                        session_id=sid,
                        text=text,
                        request_id=eff_req_id,
                        emit=wrapped_emit,
                        request_approval=on_approval,
                        attachments=atts,
                        **extra_kwargs,
                    )
                finally:
                    self._active_runs.discard(run_key)
                    self._run_buffers.pop(run_key, None)
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
            await self.terminal_manager.close_all()
            await asyncio.gather(*(a.close() for a in self.adapters.values()), return_exceptions=True)
            if direct_server is not None:
                direct_server.should_exit = True
            if direct_task is not None:
                await direct_task
