"""DeepSeek Harness (dsh) 适配器：在 allowedRoots 与人工审批保护下通过 dsh CLI 执行会话。"""

from pathlib import Path
from .cli_base import SubprocessCliAdapter


class DshAdapter(SubprocessCliAdapter):
    def __init__(self, allowed_roots: tuple[Path, ...], *, command: str = "dsh") -> None:
        super().__init__("dsh", allowed_roots, command=command, args_template=("-p",))
