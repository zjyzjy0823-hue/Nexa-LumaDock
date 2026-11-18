"""通用非交互/半结构化 CLI Harness 适配器基类（Antigravity `agy` / `dsh` 共用）。"""

import asyncio
from pathlib import Path
from typing import Any
from uuid import uuid4

from .base import (
    AdapterProbe,
    AgentAdapter,
    ApprovalCallback,
    EventEmitter,
    merge_prompt_with_attachments,
    prepare_session_dir,
    probe_cli_binary,
)


class SubprocessCliAdapter(AgentAdapter):
    """通过隔离工作目录 + 默认高危操作前置审批驱动单轮/恢复 CLI 进程。"""

    def __init__(
        self,
        provider: str,
        allowed_roots: tuple[Path, ...],
        *,
        command: str,
        args_template: tuple[str, ...] = (),
        requires_approval: bool = True,
    ) -> None:
        self.provider = provider
        self.allowed_roots = allowed_roots
        self.command = command
        self.args_template = args_template
        self.requires_approval = requires_approval
        self._sessions: dict[str, dict[str, Any]] = {}
        self._procs: dict[str, asyncio.subprocess.Process] = {}

    async def probe(self) -> AdapterProbe:
        return probe_cli_binary(self.provider, self.command, ("chat", "approval", "worktree"))

    async def list_sessions(self, *, page: int = 1, limit: int = 30) -> list[dict[str, Any]]:
        return list(self._sessions.values())[:limit]

    async def open_session(
        self,
        *,
        cwd: str,
        session_id: str | None = None,
        use_worktree: bool = False,
    ) -> dict[str, Any]:
        sid = session_id or f"{self.provider}-{uuid4().hex[:8]}"
        eff_cwd, wt_path = prepare_session_dir(cwd, self.allowed_roots, session_id=sid, use_worktree=use_worktree)
        meta = {
            "sessionId": sid,
            "provider": self.provider,
            "cwd": str(eff_cwd),
            "worktreePath": wt_path,
            "title": f"{self.provider} ({eff_cwd.name})",
        }
        self._sessions[sid] = meta
        return meta

    async def get_history(self, *, session_id: str, limit: int = 50) -> list[dict[str, Any]]:
        return []

    async def send_prompt(
        self,
        *,
        session_id: str,
        text: str,
        request_id: str,
        emit: EventEmitter,
        request_approval: ApprovalCallback,
        attachments: list[dict[str, Any]] | None = None,
    ) -> None:
        meta = self._sessions.get(session_id)
        if meta is None:
            raise RuntimeError(f"Unknown session {session_id}; open session first")
        run_id = request_id
        await emit({"type": "Accepted", "sessionId": session_id, "runId": run_id, "requestId": request_id, "provider": self.provider})

        if self.requires_approval:
            dec = await request_approval(session_id, f"cli-{uuid4().hex[:6]}", f"{self.command} run in {meta['cwd']}", "medium")
            if dec == "deny":
                await emit({"type": "TextDelta", "sessionId": session_id, "runId": run_id, "text": "已拒绝本轮 CLI 执行。"})
                await emit({"type": "Completed", "sessionId": session_id, "runId": run_id, "requestId": request_id})
                return

        cmd = [self.command, *self.args_template, merge_prompt_with_attachments(text, attachments)]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=meta["cwd"],
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        self._procs[run_id] = proc
        try:
            assert proc.stdout
            while True:
                chunk = await proc.stdout.readline()
                if not chunk:
                    break
                await emit({"type": "TextDelta", "sessionId": session_id, "runId": run_id, "text": chunk.decode("utf-8", errors="replace")})
            rc = await proc.wait()
            if rc != 0:
                await emit({"type": "Failed", "sessionId": session_id, "runId": run_id, "code": "cli_exit_error", "message": f"{self.command} exited with {rc}"})
            else:
                await emit({"type": "Completed", "sessionId": session_id, "runId": run_id, "requestId": request_id})
        finally:
            self._procs.pop(run_id, None)

    async def cancel(self, *, session_id: str, run_id: str | None = None) -> None:
        if run_id and run_id in self._procs:
            self._procs[run_id].terminate()
        else:
            for proc in list(self._procs.values()):
                proc.terminate()
