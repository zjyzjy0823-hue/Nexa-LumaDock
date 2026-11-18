"""受控工作区交互式终端会话管理器（隔离限定在 allowedRoots 内，支持 Windows/POSIX）。"""

import asyncio
from collections.abc import Awaitable, Callable
import os
from pathlib import Path
import shutil
from typing import Any
from uuid import uuid4

from .config import ensure_allowed_path


TerminalEmitFn = Callable[[dict[str, Any]], Awaitable[None]]


def _resolve_shell_argv() -> list[str]:
    if os.name == "nt":
        for exe in ("pwsh.exe", "powershell.exe", "cmd.exe"):
            resolved = shutil.which(exe)
            if resolved:
                if "cmd" in Path(resolved).name.lower():
                    return [resolved, "/Q"]
                return [
                    resolved,
                    "-NoLogo",
                    "-NoProfile",
                    "-NoExit",
                    "-Command",
                    "-",
                ]
        return ["cmd.exe", "/Q"]
    for exe in ("bash", "zsh", "sh"):
        resolved = shutil.which(exe)
        if resolved:
            return [resolved, "-i"] if exe != "sh" else [resolved]
    return ["/bin/sh"]


class WorkspaceTerminalSession:
    """运行在受控允许目录中的单个异步终端子进程。"""

    def __init__(
        self,
        terminal_id: str,
        cwd: Path,
        session_id: str,
        emit: TerminalEmitFn,
    ) -> None:
        self.terminal_id = terminal_id
        self.cwd = cwd
        self.session_id = session_id
        self._emit = emit
        self._proc: asyncio.subprocess.Process | None = None
        self._reader_tasks: list[asyncio.Task[None]] = []
        self._closed = False

    async def start(self) -> None:
        argv = _resolve_shell_argv()
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        if os.name == "nt":
            # Windows PowerShell 确保以 UTF-8 输出避免中文乱码
            pass
        self._proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(self.cwd),
            env=env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        if os.name == "nt" and ("powershell" in Path(argv[0]).name.lower() or "pwsh" in Path(argv[0]).name.lower()):
            await self.write_input(
                "[Console]::InputEncoding=[System.Text.Encoding]::UTF8;"
                "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8\n"
            )
        self._reader_tasks.append(asyncio.create_task(self._pump_stdout()))

    async def _pump_stdout(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        try:
            while not self._closed:
                chunk = await proc.stdout.read(4096)
                if not chunk:
                    break
                text = chunk.decode("utf-8", errors="replace")
                if text:
                    await self._emit(
                        {
                            "type": "TerminalOutput",
                            "terminalId": self.terminal_id,
                            "sessionId": self.session_id,
                            "data": text,
                        }
                    )
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        finally:
            code = proc.returncode
            if code is None:
                try:
                    code = await asyncio.wait_for(proc.wait(), timeout=1.0)
                except Exception:
                    code = -1
            if not self._closed:
                self._closed = True
                await self._emit(
                    {
                        "type": "TerminalClosed",
                        "terminalId": self.terminal_id,
                        "sessionId": self.session_id,
                        "exitCode": code,
                    }
                )

    async def write_input(self, data: str) -> None:
        if self._closed or self._proc is None or self._proc.stdin is None:
            raise RuntimeError("终端会话已关闭")
        text = str(data or "")
        if not text:
            return
        if os.name == "nt":
            text = text.replace("\r\n", "\n").replace("\r", "\n")
        self._proc.stdin.write(text.encode("utf-8", errors="replace"))
        await self._proc.stdin.drain()

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for task in self._reader_tasks:
            task.cancel()
        proc = self._proc
        self._proc = None
        if proc is not None and proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=2.0)
            except Exception:
                proc.kill()


class TerminalManager:
    """管理当前 Node 上最多 4 个并发终端会话。"""

    def __init__(self, allowed_roots: tuple[Path, ...], max_sessions: int = 4) -> None:
        self.allowed_roots = allowed_roots
        self.max_sessions = max_sessions
        self._sessions: dict[str, WorkspaceTerminalSession] = {}

    async def open_terminal(
        self,
        *,
        cwd: str | Path,
        session_id: str,
        emit: TerminalEmitFn,
    ) -> dict[str, Any]:
        safe_cwd = ensure_allowed_path(cwd, self.allowed_roots)
        if not safe_cwd.is_dir():
            raise FileNotFoundError(f"工作目录不存在: {safe_cwd}")
        # 超出上限时优先清理最老或已退出的会话
        dead_ids = [tid for tid, s in self._sessions.items() if s._closed]
        for tid in dead_ids:
            self._sessions.pop(tid, None)
        while len(self._sessions) >= self.max_sessions:
            oldest = next(iter(self._sessions))
            old_sess = self._sessions.pop(oldest)
            await old_sess.close()

        tid = f"term-{uuid4().hex[:8]}"
        sess = WorkspaceTerminalSession(tid, safe_cwd, session_id, emit)
        self._sessions[tid] = sess
        await sess.start()
        return {
            "terminalId": tid,
            "sessionId": session_id,
            "cwd": str(safe_cwd),
        }

    async def send_input(self, terminal_id: str, data: str) -> None:
        sess = self._sessions.get(terminal_id)
        if sess is None or sess._closed:
            raise KeyError("未找到活跃终端会话")
        await sess.write_input(data)

    async def close_terminal(self, terminal_id: str) -> bool:
        sess = self._sessions.pop(terminal_id, None)
        if sess is None:
            return False
        await sess.close()
        return True

    async def close_all(self) -> None:
        items = list(self._sessions.values())
        self._sessions.clear()
        await asyncio.gather(*(s.close() for s in items), return_exceptions=True)
