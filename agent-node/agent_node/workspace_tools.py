"""工作区安全工具：文件模糊搜索、统一 Git Diff 抽取以及基于 Git Tree 快照的无损检查点/回滚。"""

import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any

from .config import ensure_allowed_path


_SKIP_DIRS = frozenset({
    ".git",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".venv",
    "venv",
    "dist",
    "build",
    "target",
    ".studiolo-worktrees",
    ".studiolo-inbox",
})
_EMPTY_GIT_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


def _run_git_raw(cwd: Path, *args: str, env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=15.0,
    )


def _is_git_repo(cwd: Path) -> bool:
    try:
        res = _run_git_raw(cwd, "rev-parse", "--is-inside-work-tree")
        return res.returncode == 0 and res.stdout.strip().lower() == "true"
    except Exception:
        return False


def list_workspace_files(
    cwd: str | Path,
    allowed_roots: tuple[Path, ...],
    *,
    query: str = "",
    limit: int = 60,
) -> list[str]:
    """在 allowedRoots 约束下遍历工作区文件并按模糊匹配排序返回相对 POSIX 路径。"""
    safe_cwd = ensure_allowed_path(cwd, allowed_roots)
    if not safe_cwd.is_dir():
        return []
    q = query.strip().lower()
    candidates: list[tuple[int, str]] = []
    scanned = 0
    max_scan = 2500

    for root, dirs, files in os.walk(safe_cwd):
        dirs[:] = sorted(d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".studiolo-"))
        rel_dir = Path(root).relative_to(safe_cwd)
        for name in sorted(files):
            scanned += 1
            if scanned > max_scan:
                break
            rel = (rel_dir / name).as_posix() if rel_dir != Path(".") else name
            if q:
                low_rel = rel.lower()
                low_name = name.lower()
                if q not in low_rel:
                    continue
                score = 0 if low_name.startswith(q) else 1 if q in low_name else 2
            else:
                score = 0
            candidates.append((score, rel))
        if scanned > max_scan:
            break

    candidates.sort(key=lambda item: (item[0], len(item[1]), item[1]))
    return [rel for _, rel in candidates[: max(1, min(limit, 200))]]


def create_git_checkpoint(cwd: str | Path, allowed_roots: tuple[Path, ...]) -> str | None:
    """使用隔离临时索引写入 Git Tree 对象作为检查点（零副作用、不修改 HEAD 与暂存区）。"""
    safe_cwd = ensure_allowed_path(cwd, allowed_roots)
    if not _is_git_repo(safe_cwd):
        return None
    fd, tmp_idx = tempfile.mkstemp(prefix="studiolo-idx-")
    os.close(fd)
    Path(tmp_idx).unlink(missing_ok=True)
    try:
        env = {"GIT_INDEX_FILE": tmp_idx}
        head = _run_git_raw(safe_cwd, "rev-parse", "--verify", "HEAD")
        if head.returncode == 0 and head.stdout.strip():
            _run_git_raw(safe_cwd, "read-tree", head.stdout.strip(), env_extra=env)
        add_res = _run_git_raw(
            safe_cwd,
            "add",
            "-A",
            "--",
            ".",
            ":!.studiolo-inbox",
            ":!.studiolo-worktrees",
            env_extra=env,
        )
        if add_res.returncode != 0:
            return None
        tree_res = _run_git_raw(safe_cwd, "write-tree", env_extra=env)
        if tree_res.returncode != 0:
            return None
        return tree_res.stdout.strip() or None
    finally:
        Path(tmp_idx).unlink(missing_ok=True)


def _diff_trees(
    safe_cwd: Path,
    base_tree: str,
    target_tree: str,
    *,
    limit_files: int = 40,
    max_patch_chars: int = 6000,
) -> dict[str, Any]:
    numstat = _run_git_raw(safe_cwd, "diff", "--numstat", base_tree, target_tree)
    name_status = _run_git_raw(safe_cwd, "diff", "--name-status", base_tree, target_tree)
    status_map: dict[str, str] = {}
    for line in name_status.stdout.splitlines():
        parts = line.split("\t", 1)
        if len(parts) == 2:
            status_map[parts[1].strip()] = parts[0].strip()[:1] or "M"

    files: list[dict[str, Any]] = []
    total_add = 0
    total_del = 0
    for line in numstat.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        add_raw, del_raw, path = parts[0], parts[1], parts[2]
        adds = int(add_raw) if add_raw.isdigit() else 0
        dels = int(del_raw) if del_raw.isdigit() else 0
        total_add += adds
        total_del += dels
        if len(files) >= limit_files:
            continue
        patch_res = _run_git_raw(safe_cwd, "diff", "-U3", base_tree, target_tree, "--", path)
        patch_txt = patch_res.stdout
        if len(patch_txt) > max_patch_chars:
            patch_txt = patch_txt[:max_patch_chars] + "\n... [diff truncated]"
        files.append({
            "path": path,
            "status": status_map.get(path, "M"),
            "additions": adds,
            "deletions": dels,
            "patch": patch_txt,
        })

    return {
        "files": files,
        "summary": {
            "filesChanged": len(files) if len(numstat.stdout.splitlines()) <= limit_files else len(numstat.stdout.splitlines()),
            "additions": total_add,
            "deletions": total_del,
        },
        "isGitRepo": True,
    }


def get_workspace_diff(
    cwd: str | Path,
    allowed_roots: tuple[Path, ...],
    *,
    base_tree: str | None = None,
    target_tree: str | None = None,
    limit_files: int = 40,
) -> dict[str, Any]:
    """读取工作区当前相对 HEAD（或指定前后 Tree）的文件改动统计与统一 Patch。"""
    safe_cwd = ensure_allowed_path(cwd, allowed_roots)
    if not _is_git_repo(safe_cwd):
        return {
            "files": [],
            "summary": {"filesChanged": 0, "additions": 0, "deletions": 0},
            "isGitRepo": False,
        }
    end_tree = target_tree or create_git_checkpoint(safe_cwd, allowed_roots)
    if not end_tree:
        return {"files": [], "summary": {"filesChanged": 0, "additions": 0, "deletions": 0}, "isGitRepo": True}

    start_tree = base_tree
    if not start_tree:
        head = _run_git_raw(safe_cwd, "rev-parse", "--verify", "HEAD^{tree}")
        start_tree = head.stdout.strip() if head.returncode == 0 and head.stdout.strip() else _EMPTY_GIT_TREE
    if start_tree == end_tree:
        return {"files": [], "summary": {"filesChanged": 0, "additions": 0, "deletions": 0}, "isGitRepo": True}
    return _diff_trees(safe_cwd, start_tree, end_tree, limit_files=limit_files)


def restore_git_checkpoint(
    cwd: str | Path,
    allowed_roots: tuple[Path, ...],
    checkpoint_tree: str,
) -> list[str]:
    """将工作区原子恢复至指定 Git Tree 检查点，返回被恢复/清理的文件列表。"""
    safe_cwd = ensure_allowed_path(cwd, allowed_roots)
    if not _is_git_repo(safe_cwd):
        raise RuntimeError("当前会话目录不是 Git 仓库，无法执行检查点回滚")
    verify = _run_git_raw(safe_cwd, "cat-file", "-t", checkpoint_tree)
    if verify.returncode != 0 or verify.stdout.strip() != "tree":
        raise ValueError("无效或已失效的检查点标识")

    current_tree = create_git_checkpoint(safe_cwd, allowed_roots)
    changed_res = _run_git_raw(safe_cwd, "diff", "--name-only", checkpoint_tree, current_tree) if current_tree else None
    changed_files = [ln.strip() for ln in (changed_res.stdout.splitlines() if changed_res else []) if ln.strip()]

    # 删除检查点之后新增的多余文件
    if current_tree:
        added_res = _run_git_raw(safe_cwd, "diff", "--name-only", "--diff-filter=A", checkpoint_tree, current_tree)
        for rel in added_res.stdout.splitlines():
            clean_rel = rel.strip()
            if not clean_rel or clean_rel.startswith(".studiolo-"):
                continue
            target_path = ensure_allowed_path(safe_cwd / clean_rel, allowed_roots)
            if target_path.is_file():
                target_path.unlink(missing_ok=True)

    # 通过隔离临时索引检出检查点快照中的所有文件
    fd, tmp_idx = tempfile.mkstemp(prefix="studiolo-restore-")
    os.close(fd)
    Path(tmp_idx).unlink(missing_ok=True)
    try:
        env = {"GIT_INDEX_FILE": tmp_idx}
        rd = _run_git_raw(safe_cwd, "read-tree", checkpoint_tree, env_extra=env)
        if rd.returncode != 0:
            raise RuntimeError(rd.stderr.strip() or "读取检查点快照失败")
        co = _run_git_raw(safe_cwd, "checkout-index", "-a", "-f", env_extra=env)
        if co.returncode != 0:
            raise RuntimeError(co.stderr.strip() or "检出检查点文件失败")
    finally:
        Path(tmp_idx).unlink(missing_ok=True)

    return changed_files


_EXT_LANG_MAP = {
    ".ts": "ts",
    ".tsx": "tsx",
    ".js": "js",
    ".jsx": "jsx",
    ".mjs": "js",
    ".cjs": "js",
    ".vue": "vue",
    ".html": "html",
    ".css": "css",
    ".scss": "scss",
    ".py": "py",
    ".json": "json",
    ".md": "md",
    ".sh": "bash",
    ".ps1": "powershell",
    ".rs": "rust",
    ".go": "go",
    ".sql": "sql",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
}


def read_workspace_file(
    cwd: str | Path,
    allowed_roots: tuple[Path, ...],
    rel_path: str,
    *,
    max_bytes: int = 262144,
) -> dict[str, Any]:
    """在 allowedRoots 与当前目录隔离保护下读取只读文件预览内容。"""
    safe_cwd = ensure_allowed_path(cwd, allowed_roots)
    clean_rel = str(rel_path or "").strip().lstrip("/")
    if not clean_rel:
        raise ValueError("文件路径不能为空")
    target = ensure_allowed_path(safe_cwd / clean_rel, allowed_roots)
    if not target.is_file():
        raise FileNotFoundError(f"未找到文件: {clean_rel}")
    raw = target.read_bytes()
    size = len(raw)
    if b"\x00" in raw[:4096]:
        return {
            "path": clean_rel,
            "language": "",
            "content": "",
            "lineCount": 0,
            "truncated": False,
            "sizeBytes": size,
            "isBinary": True,
        }
    truncated = size > max_bytes
    text = raw[:max_bytes].decode("utf-8", errors="replace")
    lang = _EXT_LANG_MAP.get(target.suffix.lower(), target.suffix.lstrip(".").lower())
    return {
        "path": clean_rel,
        "language": lang,
        "content": text,
        "lineCount": text.count("\n") + (1 if text else 0),
        "truncated": truncated,
        "sizeBytes": size,
        "isBinary": False,
    }


def revert_workspace_files(
    cwd: str | Path,
    allowed_roots: tuple[Path, ...],
    paths: list[str],
    *,
    checkpoint_tree: str | None = None,
) -> list[str]:
    """按文件粒度精确回滚工作区改动（支持还原 HEAD 或指定检查点快照，或删除新增文件）。"""
    safe_cwd = ensure_allowed_path(cwd, allowed_roots)
    if not _is_git_repo(safe_cwd):
        raise RuntimeError("当前会话目录不是 Git 仓库，无法按文件回滚")
    if checkpoint_tree:
        verify = _run_git_raw(safe_cwd, "cat-file", "-t", checkpoint_tree)
        if verify.returncode != 0 or verify.stdout.strip() != "tree":
            raise ValueError("无效或已失效的检查点标识")
        base_tree = checkpoint_tree
    else:
        head = _run_git_raw(safe_cwd, "rev-parse", "--verify", "HEAD^{tree}")
        base_tree = head.stdout.strip() if head.returncode == 0 and head.stdout.strip() else _EMPTY_GIT_TREE

    clean_paths: list[str] = []
    for raw_p in paths:
        rel = str(raw_p or "").replace("\\", "/").strip().lstrip("/")
        if not rel or rel.startswith(".studiolo-"):
            continue
        ensure_allowed_path(safe_cwd / rel, allowed_roots)
        clean_paths.append(rel)
    if not clean_paths:
        return []

    fd, tmp_idx = tempfile.mkstemp(prefix="studiolo-frevert-")
    os.close(fd)
    Path(tmp_idx).unlink(missing_ok=True)
    reverted: list[str] = []
    try:
        env = {"GIT_INDEX_FILE": tmp_idx}
        _run_git_raw(safe_cwd, "read-tree", base_tree, env_extra=env)
        for rel in clean_paths:
            ls_res = _run_git_raw(safe_cwd, "ls-tree", "--name-only", base_tree, "--", rel)
            target_file = ensure_allowed_path(safe_cwd / rel, allowed_roots)
            if ls_res.returncode == 0 and ls_res.stdout.strip():
                co = _run_git_raw(safe_cwd, "checkout-index", "-f", "--", rel, env_extra=env)
                if co.returncode == 0:
                    reverted.append(rel)
            elif target_file.exists():
                if target_file.is_file():
                    target_file.unlink(missing_ok=True)
                    reverted.append(rel)
    finally:
        Path(tmp_idx).unlink(missing_ok=True)
    return reverted


def load_workspace_rules(
    cwd: str | Path,
    allowed_roots: tuple[Path, ...],
) -> list[dict[str, str]]:
    """读取工作区内置规则/指令文件（AGENTS.md、CLAUDE.md、.studiolo/rules/）。"""
    safe_cwd = ensure_allowed_path(cwd, allowed_roots)
    rules: list[dict[str, str]] = []
    for fixed_name in ("AGENTS.md", "CLAUDE.md", "README.md"):
        p = safe_cwd / fixed_name
        if p.is_file() and fixed_name != "README.md":
            content = p.read_text(encoding="utf-8", errors="replace")[:8000].strip()
            if content:
                rules.append({
                    "id": f"rule:{fixed_name}",
                    "title": fixed_name,
                    "source": fixed_name,
                    "content": content,
                })
    rules_dir = safe_cwd / ".studiolo" / "rules"
    if rules_dir.is_dir():
        for entry in sorted(rules_dir.glob("*.md"))[:20]:
            if entry.is_file():
                content = entry.read_text(encoding="utf-8", errors="replace")[:8000].strip()
                if content:
                    rel = entry.relative_to(safe_cwd).as_posix()
                    rules.append({
                        "id": f"rule:{rel}",
                        "title": entry.stem,
                        "source": rel,
                        "content": content,
                    })
    return rules


def merge_worktree_to_base(
    base_cwd: str | Path,
    worktree_cwd: str | Path,
    allowed_roots: tuple[Path, ...],
) -> dict[str, Any]:
    """将隔离 Git Worktree 中的所有变更补丁合回主工作区。"""
    safe_base = ensure_allowed_path(base_cwd, allowed_roots)
    safe_wt = ensure_allowed_path(worktree_cwd, allowed_roots)
    if not _is_git_repo(safe_base) or not _is_git_repo(safe_wt):
        raise RuntimeError("主目录或 Worktree 不是有效的 Git 仓库")

    head_res = _run_git_raw(safe_base, "rev-parse", "--verify", "HEAD^{tree}")
    base_tree = head_res.stdout.strip() if head_res.returncode == 0 and head_res.stdout.strip() else _EMPTY_GIT_TREE
    wt_tree = create_git_checkpoint(safe_wt, allowed_roots)
    if not wt_tree or wt_tree == base_tree:
        return {"mergedFiles": [], "message": "Worktree 与主工作区代码一致，无需合并"}

    names_res = _run_git_raw(safe_wt, "diff", "--name-only", base_tree, wt_tree)
    merged_files = [ln.strip() for ln in names_res.stdout.splitlines() if ln.strip() and not ln.strip().startswith(".studiolo-")]
    if not merged_files:
        return {"mergedFiles": [], "message": "Worktree 无可合并的文件改动"}

    patch_res = subprocess.run(
        ["git", "-C", str(safe_wt), "diff", "--binary", base_tree, wt_tree, "--", *merged_files],
        capture_output=True,
        timeout=20.0,
    )
    if patch_res.returncode != 0 or not patch_res.stdout:
        raise RuntimeError("生成 Worktree 合并补丁失败")

    apply_res = subprocess.run(
        ["git", "-C", str(safe_base), "apply", "--whitespace=nowarn", "-"],
        input=patch_res.stdout,
        capture_output=True,
        timeout=20.0,
    )
    if apply_res.returncode != 0:
        err_msg = apply_res.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"合并 Worktree 补丁冲突：{err_msg or '请手动检查差异'}")

    return {"mergedFiles": merged_files, "message": f"已将 {len(merged_files)} 个文件改动合回主工作区"}


def list_workspace_tree(
    cwd: str | Path,
    allowed_roots: tuple[Path, ...],
    *,
    rel_dir: str = "",
    max_entries: int = 300,
) -> dict[str, Any]:
    """懒加载列出工作区内指定子目录的直接文件与文件夹，严格限制在 allowedRoots 内。"""
    safe_cwd = ensure_allowed_path(cwd, allowed_roots)
    clean_rel = str(rel_dir or "").replace("\\", "/").strip().strip("/")
    target_dir = ensure_allowed_path(safe_cwd / clean_rel if clean_rel else safe_cwd, allowed_roots)
    if not target_dir.is_dir():
        return {"relDir": clean_rel, "entries": []}

    entries: list[dict[str, Any]] = []
    try:
        items = sorted(target_dir.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except OSError:
        items = []

    for child in items:
        if child.name in _SKIP_DIRS or child.name.startswith(".studiolo-"):
            continue
        try:
            resolved_child = ensure_allowed_path(child, allowed_roots)
            rel_path = resolved_child.relative_to(safe_cwd).as_posix()
            is_dir = resolved_child.is_dir()
            size_bytes = 0 if is_dir else resolved_child.stat().st_size
            entries.append(
                {
                    "path": rel_path,
                    "name": child.name,
                    "isDir": is_dir,
                    "sizeBytes": size_bytes,
                }
            )
        except Exception:
            continue
        if len(entries) >= max_entries:
            break
    return {"relDir": clean_rel, "entries": entries}


def revert_diff_hunk(
    cwd: str | Path,
    allowed_roots: tuple[Path, ...],
    rel_path: str,
    hunk_patch: str,
) -> list[str]:
    """按单个 Diff Hunk 块粒度反向撤销指定文件中的某一段代码修改。"""
    safe_cwd = ensure_allowed_path(cwd, allowed_roots)
    if not _is_git_repo(safe_cwd):
        raise RuntimeError("当前目录不是 Git 仓库，无法按 Hunk 撤销")
    clean_rel = str(rel_path or "").replace("\\", "/").strip().lstrip("/")
    if not clean_rel or clean_rel.startswith(".studiolo-"):
        raise ValueError("非法的目标文件路径")
    ensure_allowed_path(safe_cwd / clean_rel, allowed_roots)

    patch_body = str(hunk_patch or "").replace("\r\n", "\n").strip("\n")
    if not patch_body.startswith("@@"):
        raise ValueError("Hunk 补丁格式无效，必须以 @@ 块头起始")

    full_patch = f"diff --git a/{clean_rel} b/{clean_rel}\n--- a/{clean_rel}\n+++ b/{clean_rel}\n{patch_body}\n"
    apply_res = subprocess.run(
        ["git", "-C", str(safe_cwd), "apply", "-R", "--unidiff-zero", "--whitespace=nowarn", "-"],
        input=full_patch.encode("utf-8"),
        capture_output=True,
        timeout=15.0,
    )
    if apply_res.returncode != 0:
        err_msg = apply_res.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"撤销 Hunk 失败：{err_msg or '补丁上下文与当前文件不匹配'}")
    return [clean_rel]


def git_commit_changes(
    cwd: str | Path,
    allowed_roots: tuple[Path, ...],
    message: str,
    *,
    paths: list[str] | None = None,
) -> dict[str, Any]:
    """在受控工作区中暂存指定文件（或全部变动）并执行 git commit。"""
    safe_cwd = ensure_allowed_path(cwd, allowed_roots)
    if not _is_git_repo(safe_cwd):
        raise RuntimeError("当前目录不是 Git 仓库，无法执行提交")
    clean_msg = str(message or "").strip()
    if not clean_msg:
        raise ValueError("提交说明（Commit Message）不能为空")

    staged_targets: list[str] = []
    if paths:
        for raw_p in paths:
            rel = str(raw_p or "").replace("\\", "/").strip().lstrip("/")
            if not rel or rel.startswith(".studiolo-"):
                continue
            ensure_allowed_path(safe_cwd / rel, allowed_roots)
            staged_targets.append(rel)

    if staged_targets:
        add_res = _run_git_raw(safe_cwd, "add", "-A", "--", *staged_targets)
    else:
        add_res = _run_git_raw(safe_cwd, "add", "-A", "--", ".", ":!.studiolo-*")
    if add_res.returncode != 0:
        raise RuntimeError(add_res.stderr.strip() or "git add 暂存失败")

    commit_res = _run_git_raw(safe_cwd, "commit", "-m", clean_msg)
    if commit_res.returncode != 0:
        err_txt = (commit_res.stderr or commit_res.stdout or "").strip()
        raise RuntimeError(err_txt or "git commit 失败（请检查是否配置 user.name / user.email 或无待提交变更）")

    rev_res = _run_git_raw(safe_cwd, "rev-parse", "--short", "HEAD")
    return {
        "commitHash": rev_res.stdout.strip() if rev_res.returncode == 0 else "",
        "message": clean_msg,
        "filesCommitted": staged_targets,
    }
