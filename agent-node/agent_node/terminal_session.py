"""受控工作区交互式终端会话管理器（隔离限定在 allowedRoots 内，POSIX 优先使用真 PTY，Windows 兼容增强并支持中断信号）。"""

import asyncio
from collections.abc import Awaitable, Callable
import os
from pathlib import Path
import shutil
import signal
from typing import Any
from uuid import uuid4

from .config import ensure_allowed_path


TerminalEmitFn = Callable[[dict[str, Any]], Awaitable[None]]

try:  # POSIX 环境下启用真 PTY，支持 TUI/交互式命令行
    import fcntl as _fcntl
    import pty as _pty
    import struct as _struct
    import termios as _termios
except ImportError:  # Windows 下优雅降级为受控子进程管道
    _fcntl = None
    _pty = None
    _struct = None
    _termios = None


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
    for exe in ("zsh", "bash", "sh"):
        resolved = shutil.which(exe)
        if resolved:
            return [resolved, "-i"] if exe != "sh" else [resolved]
    return ["/bin/sh"]


class WorkspaceTerminalSession:
    """运行在受控允许目录中的单个异步终端子进程（POSIX 支持真 PTY 与窗口 resize）。"""

    def __init__(
        self,
        terminal_id: str,
        cwd: Path,
        session_id: str,
        emit: TerminalEmitFn,
        *,
        cols: int = 100,
        rows: int = 28,
    ) -> None:
        self.terminal_id = terminal_id
        self.cwd = cwd
        self.session_id = session_id
        self._emit = emit
        self._cols = max(20, min(300, int(cols)))
        self._rows = max(6, min(120, int(rows)))
        self._proc: asyncio.subprocess.Process | None = None
        self._pty_master_fd: int | None = None
        self._reader_tasks: list[asyncio.Task[None]] = []
        self._closed = False

    def _apply_pty_size(self, fd: int, cols: int, rows: int) -> None:
        if _fcntl is None or _struct is None or _termios is None:
            return
        try:
            winsize = _struct.pack("HHHH", rows, cols, 0, 0)
            _fcntl.ioctl(fd, _termios.TIOCSWINSZ, winsize)
        except Exception:
            pass

    async def start(self) -> None:
        argv = _resolve_shell_argv()
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        env.setdefault("TERM", "xterm-256color")

        if os.name != "nt" and _pty is not None:
            master_fd, slave_fd = _pty.openpty()
            self._apply_pty_size(master_fd, self._cols, self._rows)
            try:
                self._proc = await asyncio.create_subprocess_exec(
                    *argv,
                    cwd=str(self.cwd),
                    env=env,
                    stdin=slave_fd,
                    stdout=slave_fd,
                    stderr=slave_fd,
                    start_new_session=True,
                )
            except Exception:
                os.close(master_fd)
                os.close(slave_fd)
                raise
            os.close(slave_fd)
            self._pty_master_fd = master_fd
            self._reader_tasks.append(asyncio.create_task(self._pump_pty()))
            return

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

    async def _pump_pty(self) -> None:
        fd = self._pty_master_fd
        proc = self._proc
        if fd is None or proc is None:
            return
        try:
            while not self._closed:
                try:
                    chunk = await asyncio.to_thread(os.read, fd, 4096)
                except OSError:
                    break
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
            await self._finalize_exit(proc)

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
            await self._finalize_exit(proc)

    async def _finalize_exit(self, proc: asyncio.subprocess.Process) -> None:
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
        if self._closed or self._proc is None:
            raise RuntimeError("终端会话已关闭")
        text = str(data or "")
        if not text:
            return
        if self._pty_master_fd is not None:
            await asyncio.to_thread(os.write, self._pty_master_fd, text.encode("utf-8", errors="replace"))
            return
        if self._proc.stdin is None:
            raise RuntimeError("终端标准输入不可用")
        if os.name == "nt":
            text = text.replace("\r\n", "\n").replace("\r", "\n")
        self._proc.stdin.write(text.encode("utf-8", errors="replace"))
        await self._proc.stdin.drain()

    async def send_signal(self, sig_name: str = "SIGINT") -> None:
        """向终端子进程发送控制信号（如 Ctrl+C 中断当前前台命令）。"""
        if self._closed or self._proc is None:
            return
        clean = str(sig_name or "SIGINT").upper()
        if self._pty_master_fd is not None and clean == "SIGINT":
            # 在真 PTY 下写入 ETX (\x03) 触发前台进程组 SIGINT 而不杀掉整个 shell
            await asyncio.to_thread(os.write, self._pty_master_fd, b"\x03")
            return
        if os.name != "nt":
            sig = signal.SIGINT if clean == "SIGINT" else signal.SIGTERM
            try:
                os.killpg(os.getpgid(self._proc.pid), sig)
                return
            except Exception:
                pass
        if self._proc.returncode is None:
            try:
                if clean == "SIGINT" and hasattr(signal, "CTRL_C_EVENT"):
                    # Windows 管道模式下直接发送换行提示避免误杀父进程组，必要时用 terminate
                    if self._proc.stdin is not None:
                        self._proc.stdin.write(b"\x03\n")
                        await self._proc.stdin.drain()
                else:
                    self._proc.terminate()
            except Exception:
                pass

    def resize(self, cols: int, rows: int) -> None:
        self._cols = max(20, min(300, int(cols)))
        self._rows = max(6, min(120, int(rows)))
        if self._pty_master_fd is not None:
            self._apply_pty_size(self._pty_master_fd, self._cols, self._rows)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for task in self._reader_tasks:
            task.cancel()
        if self._pty_master_fd is not None:
            fd = self._pty_master_fd
            self._pty_master_fd = None
            try:
                os.close(fd)
            except OSError:
                pass
        proc = self._proc
        self._proc = None
        if proc is not None and proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=2.0)
            except Exception:
                proc.kill()


class TerminalManager:
    """管理当前 Node 上最多 8 个并发终端会话。"""

    def __init__(self, allowed_roots: tuple[Path, ...], max_sessions: int = 8) -> None:
        self.allowed_roots = allowed_roots
        self.max_sessions = max_sessions
        self._sessions: dict[str, WorkspaceTerminalSession] = {}

    def is_open_for(self, terminal_id: str, session_id: str) -> bool:
        terminal = self._sessions.get(terminal_id)
        return bool(terminal and not terminal._closed and terminal.session_id == session_id)

    async def open_terminal(
        self,
        *,
        cwd: str | Path,
        session_id: str,
        emit: TerminalEmitFn,
        cols: int = 100,
        rows: int = 28,
    ) -> dict[str, Any]:
        safe_cwd = ensure_allowed_path(cwd, self.allowed_roots)
        if not safe_cwd.is_dir():
            raise FileNotFoundError(f"工作目录不存在: {safe_cwd}")
        dead_ids = [tid for tid, s in self._sessions.items() if s._closed]
        for tid in dead_ids:
            self._sessions.pop(tid, None)
        while len(self._sessions) >= self.max_sessions:
            oldest = next(iter(self._sessions))
            old_sess = self._sessions.pop(oldest)
            await old_sess.close()

        tid = f"term-{uuid4().hex[:8]}"
        sess = WorkspaceTerminalSession(tid, safe_cwd, session_id, emit, cols=cols, rows=rows)
        self._sessions[tid] = sess
        await sess.start()
        return {
            "terminalId": tid,
            "sessionId": session_id,
            "cwd": str(safe_cwd),
            "pty": sess._pty_master_fd is not None,
        }

    async def send_input(self, terminal_id: str, data: str) -> None:
        sess = self._sessions.get(terminal_id)
        if sess is None or sess._closed:
            raise KeyError("未找到活跃终端会话")
        await sess.write_input(data)

    async def send_signal(self, terminal_id: str, sig_name: str = "SIGINT") -> None:
        sess = self._sessions.get(terminal_id)
        if sess is None or sess._closed:
            return
        await sess.send_signal(sig_name)

    def resize_terminal(self, terminal_id: str, cols: int, rows: int) -> None:
        sess = self._sessions.get(terminal_id)
        if sess is not None and not sess._closed:
            sess.resize(cols, rows)

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
