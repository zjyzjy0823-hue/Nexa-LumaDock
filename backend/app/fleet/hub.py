"""纯内存 Multi-Device Fleet Relay Hub（零聊天正文持久化，只存连接路由与有界幂等键）。"""

import asyncio
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from fastapi import WebSocket


MAX_DEDUP_KEYS = 2048
ALLOWED_CLIENT_COMMANDS = frozenset({
    "sessions.list",
    "models.list",
    "agents.list",
    "mcp.list",
    "rules.list",
    "skills.list",
    "files.list",
    "files.tree",
    "file.read",
    "file.write",
    "file.blame",
    "files.revert",
    "diff.revert_hunk",
    "git.commit",
    "trust.list",
    "trust.add",
    "trust.remove",
    "terminal.open",
    "terminal.preview",
    "terminal.input",
    "terminal.signal",
    "terminal.resize",
    "terminal.close",
    "session.open",
    "session.history",
    "session.diff",
    "session.compact",
    "session.rename",
    "session.delete",
    "session.subscribe",
    "checkpoint.revert",
    "worktree.merge",
    "workspace.open_external",
    "form.reply",
    "prompt.send",
    "prompt.cancel",
    "permission.respond",
    "handoff.send",
    "node.ping",
    "cron.list",
    "cron.create",
    "cron.update",
    "cron.delete",
    "cron.pause",
    "cron.run",
    "cron.runs",
})
ALLOWED_NODE_EVENTS = frozenset({
    "Accepted",
    "ThoughtDelta",
    "TextDelta",
    "ToolCall",
    "ToolCallUpdate",
    "TodoUpdated",
    "PermissionRequest",
    "FormRequest",
    "FormResolved",
    "ArtifactOffered",
    "TokenUsage",
    "SessionsSnapshot",
    "ModelsSnapshot",
    "AgentsSnapshot",
    "McpSnapshot",
    "RulesSnapshot",
    "SkillsSnapshot",
    "FilesSnapshot",
    "FilesTreeSnapshot",
    "FileContentSnapshot",
    "FileWritten",
    "FileBlameSnapshot",
    "DiffSnapshot",
    "GitCommitted",
    "TrustPolicySnapshot",
    "TerminalOpened",
    "TerminalOutput",
    "TerminalClosed",
    "CheckpointCreated",
    "CheckpointReverted",
    "WorktreeMerged",
    "ExternalOpened",
    "SessionOpened",
    "SessionHistory",
    "SessionStreamReplay",
    "SessionCompacted",
    "TerminalPreview",
    "RunStopStatus",
    "SessionRenamed",
    "SessionDeleted",
    "DuplicateIgnored",
    "Completed",
    "Failed",
    "NodeHeartbeat",
    "CronRpcResult",
    "SubscriptionQuotaResult",
})


@dataclass
class ConnectedNode:
    node_id: str
    workspace_id: str
    user_id: int
    name: str
    platform: str
    websocket: WebSocket
    adapters: list[dict[str, Any]] = field(default_factory=list)
    allowed_roots: list[str] = field(default_factory=list)
    transfer_endpoints: list[dict[str, Any]] = field(default_factory=list)


class FleetRelayHub:
    """维护活跃 AgentNode 与客户端 WebSocket 连接，无磁盘消息落库。"""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._nodes: dict[tuple[str, str], ConnectedNode] = {}
        self._clients: dict[str, dict[str, WebSocket]] = {}
        self._seen_requests: OrderedDict[tuple[str, str, str], bool] = OrderedDict()
        self._forwarding_requests: dict[tuple[str, str, str], asyncio.Future[bool]] = {}
        # Core REST -> AgentNode 同步 RPC 挂起表（纯内存，不落盘）
        self._pending_rpcs: dict[str, tuple[str, str, asyncio.Future[dict[str, Any]]]] = {}

    async def register_node(self, conn: ConnectedNode) -> None:
        async with self._lock:
            self._nodes[(conn.workspace_id, conn.node_id)] = conn
        await self.broadcast_workspace(
            conn.workspace_id,
            {
                "type": "NodePresence",
                "nodeId": conn.node_id,
                "name": conn.name,
                "platform": conn.platform,
                "status": "online",
                "adapters": conn.adapters,
                "allowedRoots": conn.allowed_roots,
                "transferEndpoints": conn.transfer_endpoints,
            },
        )

    async def unregister_node(self, workspace_id: str, node_id: str, websocket: WebSocket | None = None) -> None:
        removed: ConnectedNode | None = None
        stale_futs: list[asyncio.Future[dict[str, Any]]] = []
        async with self._lock:
            current = self._nodes.get((workspace_id, node_id))
            if current is not None and (websocket is None or current.websocket is websocket):
                removed = self._nodes.pop((workspace_id, node_id))
                stale_ids = [
                    rid for rid, (ws_id, n_id, _) in self._pending_rpcs.items()
                    if ws_id == workspace_id and n_id == node_id
                ]
                for rid in stale_ids:
                    stale_futs.append(self._pending_rpcs.pop(rid)[2])
        for fut in stale_futs:
            if not fut.done():
                fut.set_result({"ok": False, "code": "node_disconnected", "error": "Target device node disconnected"})
        if removed is not None:
            await self.broadcast_workspace(
                workspace_id,
                {
                    "type": "NodePresence",
                    "nodeId": node_id,
                    "name": removed.name,
                    "platform": removed.platform,
                    "status": "offline",
                },
            )

    async def kick_node(self, workspace_id: str, node_id: str, reason: str = "revoked") -> None:
        """吊销或删除节点时立即断开活跃 WSS 会话，防止遗留长连接继续收发。"""
        async with self._lock:
            current = self._nodes.get((workspace_id, node_id))
        if current is None:
            return
        try:
            await current.websocket.close(code=4401, reason=reason)
        except Exception:
            pass
        await self.unregister_node(workspace_id, node_id, current.websocket)

    async def register_client(self, workspace_id: str, websocket: WebSocket) -> str:
        conn_id = str(uuid4())
        async with self._lock:
            self._clients.setdefault(workspace_id, {})[conn_id] = websocket
            online_snapshot = [
                {
                    "nodeId": n.node_id,
                    "name": n.name,
                    "platform": n.platform,
                    "status": "online",
                    "adapters": n.adapters,
                    "allowedRoots": n.allowed_roots,
                    "transferEndpoints": n.transfer_endpoints,
                }
                for (ws_id, _), n in self._nodes.items()
                if ws_id == workspace_id
            ]
        await websocket.send_json({"type": "FleetSnapshot", "nodes": online_snapshot})
        return conn_id

    async def unregister_client(self, workspace_id: str, conn_id: str) -> None:
        async with self._lock:
            clients = self._clients.get(workspace_id)
            if clients:
                clients.pop(conn_id, None)
                if not clients:
                    self._clients.pop(workspace_id, None)

    async def get_online_node(self, workspace_id: str, node_id: str) -> ConnectedNode | None:
        async with self._lock:
            return self._nodes.get((workspace_id, node_id))

    async def call_node_rpc(
        self,
        workspace_id: str,
        node_id: str,
        frame: dict[str, Any],
        *,
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        """向工作区内目标在线 AgentNode 发送一次性控制 RPC 并等待回执。"""
        node = await self.get_online_node(workspace_id, node_id)
        if node is None:
            return {"ok": False, "code": "node_offline", "error": "Target device node is offline"}

        rpc_id = str(uuid4())
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[dict[str, Any]] = loop.create_future()
        async with self._lock:
            self._pending_rpcs[rpc_id] = (workspace_id, node_id, fut)

        outbound = {**frame, "_rpcId": rpc_id}
        try:
            await node.websocket.send_json(outbound)
        except Exception:
            async with self._lock:
                self._pending_rpcs.pop(rpc_id, None)
            await self.unregister_node(workspace_id, node_id, node.websocket)
            return {"ok": False, "code": "node_disconnected", "error": "Target device node disconnected"}

        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            return {"ok": False, "code": "rpc_timeout", "error": "Remote node did not respond in time"}
        finally:
            async with self._lock:
                self._pending_rpcs.pop(rpc_id, None)

    async def resolve_node_rpc(self, workspace_id: str, node_id: str, rpc_id: str, payload: dict[str, Any]) -> bool:
        """收到节点回执时唤醒等待中的 Core REST 调用。"""
        async with self._lock:
            entry = self._pending_rpcs.get(rpc_id)
            if entry is None:
                return False
            ws_id, n_id, fut = entry
            if ws_id != workspace_id or n_id != node_id:
                return False
            self._pending_rpcs.pop(rpc_id, None)
        if not fut.done():
            fut.set_result(payload)
        return True

    async def list_online_endpoints(self, workspace_id: str) -> list[dict[str, Any]]:
        async with self._lock:
            out: list[dict[str, Any]] = []
            for (ws_id, _), conn in self._nodes.items():
                if ws_id == workspace_id:
                    for ep in conn.transfer_endpoints:
                        out.append({"nodeId": conn.node_id, **ep})
            return out

    async def _begin_forward(self, key: tuple[str, str, str]) -> bool:
        while True:
            async with self._lock:
                if key in self._seen_requests:
                    self._seen_requests.move_to_end(key)
                    return False
                pending = self._forwarding_requests.get(key)
                if pending is None:
                    self._forwarding_requests[key] = asyncio.get_running_loop().create_future()
                    return True
            if await asyncio.shield(pending):
                return False

    def _finish_forward(self, key: tuple[str, str, str], delivered: bool) -> None:
        if delivered:
            self._seen_requests[key] = True
            while len(self._seen_requests) > MAX_DEDUP_KEYS:
                self._seen_requests.popitem(last=False)
        self._forwarding_requests.pop(key).set_result(delivered)

    async def forward_client_command(
        self,
        workspace_id: str,
        client_conn_id: str,
        frame: dict[str, Any],
    ) -> dict[str, Any] | None:
        """将前端指令校验并路由至工作区内的目标在线 AgentNode，返回即时错误帧或 None。"""
        cmd_type = str(frame.get("type") or "")
        if cmd_type not in ALLOWED_CLIENT_COMMANDS:
            return {"type": "Error", "code": "unsupported_command", "message": f"Unsupported command: {cmd_type}"}

        if cmd_type == "node.ping":
            return {"type": "Pong", "requestId": frame.get("requestId")}

        target_node_id = str(frame.get("nodeId") or "").strip()
        if not target_node_id:
            return {"type": "Error", "code": "missing_node_id", "message": "nodeId is required"}

        node = await self.get_online_node(workspace_id, target_node_id)
        command_id = str(frame.get("commandId") or frame.get("requestId") or "").strip()
        request_id = str(frame.get("requestId") or command_id).strip()
        if node is None:
            return {
                "type": "NodeUnavailable",
                "code": "node_offline",
                "nodeId": target_node_id,
                "requestId": request_id or None,
                "message": "Target device node is offline",
            }

        key = None
        if cmd_type in ("prompt.send", "handoff.send") and command_id:
            if len(command_id) > 128:
                return {"type": "Error", "code": "invalid_command_id", "requestId": request_id}
            key = (workspace_id, target_node_id, command_id)
            if not await self._begin_forward(key):
                return {"type": "DuplicateIgnored", "nodeId": target_node_id, "requestId": request_id, "commandId": command_id}

        forwarded = {**frame, "_clientConnId": client_conn_id}
        if key:
            forwarded.update(requestId=request_id, commandId=command_id)
        delivered = False
        try:
            await node.websocket.send_json(forwarded)
            delivered = True
        except Exception:
            await self.unregister_node(workspace_id, target_node_id, node.websocket)
            return {
                "type": "NodeUnavailable",
                "code": "node_disconnected",
                "nodeId": target_node_id,
                "requestId": request_id or None,
                "message": "Target device node disconnected",
            }
        finally:
            if key:
                self._finish_forward(key, delivered)
        return None

    async def broadcast_workspace(
        self,
        workspace_id: str,
        frame: dict[str, Any],
        *,
        target_client_id: str | None = None,
    ) -> None:
        async with self._lock:
            clients = dict(self._clients.get(workspace_id, {}))
        if not clients:
            return
        targets = (
            [(target_client_id, clients[target_client_id])]
            if target_client_id and target_client_id in clients
            else list(clients.items())
        )
        stale: list[str] = []
        for cid, ws in targets:
            try:
                await ws.send_json(frame)
            except Exception:
                stale.append(cid)
        if stale:
            async with self._lock:
                bucket = self._clients.get(workspace_id, {})
                for cid in stale:
                    bucket.pop(cid, None)


fleet_hub = FleetRelayHub()
