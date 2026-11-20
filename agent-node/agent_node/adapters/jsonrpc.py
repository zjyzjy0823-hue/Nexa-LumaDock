"""基于标准输入/输出流（stdio）的共用 JSON-RPC 2.0 异步子进程驱动（供 Codex / Hermes ACP 共用）。"""

import asyncio
from collections.abc import Awaitable, Callable
import json
from pathlib import Path
from typing import Any


NotificationHandler = Callable[[str, dict[str, Any]], Awaitable[None]]
ServerRequestHandler = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


class JsonRpcError(RuntimeError):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(f"JSON-RPC {code}: {message}")
        self.code = code
        self.message = message


class StdioJsonRpcProcess:
    """管理行分隔 JSON-RPC 2.0 长驻或单会话子进程，封装请求匹配、通知分发与服务端审批回调。"""

    def __init__(
        self,
        command: list[str],
        *,
        cwd: Path,
        on_notification: NotificationHandler | None = None,
        on_request: ServerRequestHandler | None = None,
        auto_start: bool = True,
    ) -> None:
        self.command = command
        self.cwd = cwd
        self.on_notification = on_notification
        self.on_request = on_request
        self.auto_start = auto_start
        self._proc: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._next_id = 1
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._write_lock = asyncio.Lock()
        self._start_lock = asyncio.Lock()

    async def start(self) -> bool:
        async with self._start_lock:
            if self._proc is not None and self._proc.returncode is None:
                return False
            self._fail_pending()
            proc = await asyncio.create_subprocess_exec(
                *self.command,
                cwd=str(self.cwd),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                limit=8 * 1024 * 1024,
            )
            self._proc = proc
            self._reader_task = asyncio.create_task(self._read_loop(proc))
            return True

    async def stop(self) -> None:
        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
            self._reader_task = None
        if self._proc is not None:
            if self._proc.returncode is None:
                self._proc.terminate()
                try:
                    await asyncio.wait_for(self._proc.wait(), timeout=3.0)
                except asyncio.TimeoutError:
                    self._proc.kill()
                    await self._proc.wait()
            self._proc = None
        self._fail_pending()

    def _fail_pending(self) -> None:
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(RuntimeError("JSON-RPC process closed"))
        self._pending.clear()

    async def call(self, method: str, params: dict[str, Any] | None = None, *, timeout: float = 60.0) -> Any:
        if self.auto_start:
            await self.start()
        req_id = self._next_id
        self._next_id += 1
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[Any] = loop.create_future()
        self._pending[req_id] = fut
        msg = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}}
        try:
            await self._write(msg)
            return await asyncio.wait_for(fut, timeout=timeout)
        finally:
            self._pending.pop(req_id, None)
            # Consume a transport error if the reader closed while drain() was failing.
            if fut.done() and not fut.cancelled():
                fut.exception()
            else:
                fut.cancel()

    async def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        if self.auto_start:
            await self.start()
        await self._write({"jsonrpc": "2.0", "method": method, "params": params or {}})

    async def _write(self, msg: dict[str, Any], proc: asyncio.subprocess.Process | None = None) -> None:
        proc = proc or self._proc
        async with self._write_lock:
            if not proc or self._proc is not proc or proc.returncode is not None or not proc.stdin:
                raise RuntimeError("JSON-RPC process closed")
            proc.stdin.write((json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8"))
            await proc.stdin.drain()

    async def _send_reply(self, proc: asyncio.subprocess.Process, req_id: Any, result: Any = None, error: dict[str, Any] | None = None) -> None:
        payload: dict[str, Any] = {"jsonrpc": "2.0", "id": req_id}
        if error is not None:
            payload["error"] = error
        else:
            payload["result"] = result
        try:
            await self._write(payload, proc)
        except (OSError, RuntimeError):
            pass

    async def _read_loop(self, proc: asyncio.subprocess.Process) -> None:
        try:
            await self._read_frames(proc)
        finally:
            if self._proc is proc:
                self._fail_pending()

    async def _read_frames(self, proc: asyncio.subprocess.Process) -> None:
        assert proc.stdout
        while self._proc is proc:
            raw = await proc.stdout.readline()
            if not raw or self._proc is not proc:
                break
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                frame = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(frame, dict):
                continue
            if "id" in frame and "method" not in frame:
                fut = self._pending.pop(frame["id"], None)
                if fut and not fut.done():
                    if "error" in frame and frame["error"]:
                        err = frame["error"]
                        fut.set_exception(JsonRpcError(int(err.get("code", -1)), str(err.get("message", "RPC Error"))))
                    else:
                        fut.set_result(frame.get("result"))
            elif "id" in frame and "method" in frame:
                asyncio.create_task(self._handle_server_request(proc, frame["id"], str(frame["method"]), frame.get("params") or {}))
            elif "method" in frame and self.on_notification is not None:
                await self.on_notification(str(frame["method"]), frame.get("params") or {})

    async def _handle_server_request(self, proc: asyncio.subprocess.Process, req_id: Any, method: str, params: dict[str, Any]) -> None:
        try:
            if self.on_request is None:
                await self._send_reply(proc, req_id, error={"code": -32601, "message": f"Unhandled request {method}"})
                return
            res = await self.on_request(method, params)
            await self._send_reply(proc, req_id, result=res)
        except Exception as exc:
            await self._send_reply(proc, req_id, error={"code": -32000, "message": str(exc)})
