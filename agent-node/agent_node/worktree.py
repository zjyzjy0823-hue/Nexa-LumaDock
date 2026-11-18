"""同仓库多 Agent 并发执行的 Git Worktree 沙箱管理器。"""

import os
from pathlib import Path
import re
import subprocess

from .config import PathOutsideAllowedRootsError, ensure_allowed_path


_SAFE_ID_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _run_git(cwd: Path, *args: str) -> str:
    res = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(res.stderr.strip() or f"git {' '.join(args)} failed")
    return res.stdout.strip()


def resolve_repo_root(target: str | Path, allowed_roots: tuple[Path, ...]) -> Path:
    safe_target = ensure_allowed_path(target, allowed_roots)
    top = _run_git(safe_target, "rev-parse", "--show-toplevel")
    return ensure_allowed_path(top, allowed_roots)


def create_session_worktree(repo_path: str | Path, session_id: str, allowed_roots: tuple[Path, ...]) -> Path:
    """在 allowedRoots 范围内为并发会话创建隔离的分离头 Git Worktree。"""
    repo_root = resolve_repo_root(repo_path, allowed_roots)
    safe_id = _SAFE_ID_RE.sub("-", session_id).strip("-") or "session"
    worktree_dir = repo_root / ".studiolo-worktrees" / safe_id
    # 先校验 worktree 目标路径本身不逃出 allowedRoots
    ensure_allowed_path(worktree_dir, allowed_roots)
    worktree_dir.parent.mkdir(parents=True, exist_ok=True)
    if (worktree_dir / ".git").exists():
        return Path(os.path.realpath(worktree_dir))
    _run_git(repo_root, "worktree", "add", "--detach", str(worktree_dir))
    return ensure_allowed_path(worktree_dir, allowed_roots)


def remove_session_worktree(repo_path: str | Path, worktree_path: str | Path, allowed_roots: tuple[Path, ...]) -> None:
    repo_root = resolve_repo_root(repo_path, allowed_roots)
    safe_wt = ensure_allowed_path(worktree_path, allowed_roots)
    expected_parent = Path(os.path.realpath(repo_root / ".studiolo-worktrees"))
    if safe_wt.parent != expected_parent and (
        os.name != "nt" or str(safe_wt.parent).lower() != str(expected_parent).lower()
    ):
        raise PathOutsideAllowedRootsError("Refusing to remove directory outside .studiolo-worktrees")
    _run_git(repo_root, "worktree", "remove", "--force", str(safe_wt))
