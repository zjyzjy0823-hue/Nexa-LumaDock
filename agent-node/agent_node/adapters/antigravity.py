"""Google Antigravity 适配器：优先复用 google-antigravity SDK（若已安装），否则回退到 agy CLI。"""

from pathlib import Path
from typing import Any

from .base import AdapterProbe, ApprovalCallback, EventEmitter, probe_cli_binary
from .cli_base import SubprocessCliAdapter


class AntigravityAdapter(SubprocessCliAdapter):
    def __init__(self, allowed_roots: tuple[Path, ...], *, command: str = "agy") -> None:
        super().__init__("antigravity", allowed_roots, command=command, args_template=("run",))

    async def probe(self) -> AdapterProbe:
        try:
            import google_antigravity  # type: ignore  # noqa: F401
            sdk_ready = True
        except ImportError:
            sdk_ready = False
        cli_probe = probe_cli_binary(self.provider, self.command, ("chat", "approval", "worktree"))
        if sdk_ready and cli_probe.status != "ready":
            return AdapterProbe(provider=self.provider, version="python-sdk", status="ready", capabilities=cli_probe.capabilities)
        return cli_probe

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
        await super().send_prompt(
            session_id=session_id,
            text=text,
            request_id=request_id,
            emit=emit,
            request_approval=request_approval,
            attachments=attachments,
        )
