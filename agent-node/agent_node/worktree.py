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


def recover_session_worktree(cwd: Path, allowed_roots: tuple[Path, ...]) -> tuple[Path, Path] | None:
    worktree = next((path for path in (cwd, *cwd.parents) if path.parent.name == ".studiolo-worktrees"), None)
    if worktree is None or not (worktree / ".git").is_file():
        return None
    base = ensure_allowed_path(worktree.parent.parent, allowed_roots)
    base_git = _run_git(base, "rev-parse", "--path-format=absolute", "--git-common-dir")
    worktree_git = _run_git(worktree, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if Path(base_git).resolve() != Path(worktree_git).resolve():
        return None
    return base, worktree


def current_session_ref(cwd: Path) -> str:
    return _run_git(cwd, "branch", "--show-current") or _run_git(cwd, "rev-parse", "--short", "HEAD")


def create_session_worktree(
    repo_path: str | Path,
    session_id: str,
    allowed_roots: tuple[Path, ...],
    *,
    branch_name: str | None = None,
) -> Path:
    """在 allowedRoots 范围内为并发会话创建隔离的 Git Worktree（支持指定分支名或默认分离头）。"""
    repo_root = resolve_repo_root(repo_path, allowed_roots)
    safe_id = _SAFE_ID_RE.sub("-", session_id).strip("-") or "session"
    worktree_dir = repo_root / ".studiolo-worktrees" / safe_id
    # 先校验 worktree 目标路径本身不逃出 allowedRoots
    ensure_allowed_path(worktree_dir, allowed_roots)
    worktree_dir.parent.mkdir(parents=True, exist_ok=True)
    if (worktree_dir / ".git").exists():
        return Path(os.path.realpath(worktree_dir))
    clean_branch = _SAFE_ID_RE.sub("-", str(branch_name or "").strip()).strip("-.")
    if clean_branch:
        try:
            _run_git(repo_root, "worktree", "add", "-b", clean_branch, str(worktree_dir))
        except RuntimeError:
            _run_git(repo_root, "worktree", "add", "--detach", str(worktree_dir))
    else:
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
