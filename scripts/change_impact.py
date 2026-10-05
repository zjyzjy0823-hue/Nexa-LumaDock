"""Small, conservative boundary rules and Git inputs; standard library only."""
import argparse
import fnmatch
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PROTECTED = {"sync", "conflict", "protocol", "database", "identity", "connection",
             "sidecar", "desktop", "packaging", "windows-packaging", "macos-packaging"}
# Specific rules precede ordinary service/presentation fallbacks.
RULES = [
    ("protocol", ["backend/app/sync/protocol.py", "backend/app/sync/schemas.py"]),
    ("conflict", ["backend/app/sync/conflicts.py", "src/*/*conflict*", "src/*/*Conflict*", "src/components/settings/ConflictCenter.vue"]),
    ("sync", ["backend/app/sync/*", "backend/app/api/sync.py", "src/api/sync.ts", "src/composables/useCoreSync.ts", "src/services/coreSyncErrors.ts"]),
    ("database", ["backend/migrations/*", "backend/alembic.ini", "backend/app/database.py", "backend/app/models.py"]),
    ("identity", ["backend/app/security.py", "backend/app/workspaces.py", "backend/app/client_credentials.py", "backend/app/credential_store.py", "backend/app/api/auth.py", "backend/app/api/clients.py", "backend/app/api/client_runtime.py", "backend/app/api/workspace.py", "src/stores/auth.ts"]),
    ("connection", ["backend/app/core_connection.py", "backend/app/config.py", "backend/app/runtime_mode.py", "backend/app/api/core.py", "src/api/core.ts", "src/api/client.ts", "src/components/settings/SyncSettings.vue"]),
    ("sidecar", ["backend/desktop_entry.py", "backend/core_entry.py", "backend/app/main.py", "backend/app/resources.py", "src-tauri/src/backend_startup.rs"]),
    ("windows-packaging", ["src-tauri/tauri.windows.conf.json", "scripts/build-backend-sidecar.ps1"]),
    ("macos-packaging", ["src-tauri/tauri.macos.conf.json"]),
    ("packaging", ["src-tauri/Cargo.*", "src-tauri/tauri.conf.json", "src-tauri/build.rs", "src-tauri/capabilities/*", "backend/nexa-backend.spec", "backend/requirements*.txt", "scripts/*sidecar*.py", "scripts/desktop*", "package*.json", "vite.config.ts"]),
    ("desktop", ["src-tauri/*", "src/desktop/*"]),
]
VERSION_FILES = {"package.json", "package-lock.json", "src-tauri/Cargo.toml", "src-tauri/Cargo.lock", "src-tauri/tauri.conf.json", "backend/app/main.py"}


def git(*args, root=ROOT):
    result = subprocess.run(["git", *args], cwd=root, capture_output=True)
    if result.returncode:
        raise ValueError(result.stderr.decode("utf-8", errors="replace").strip())
    return result.stdout.decode("utf-8", errors="surrogateescape")


def changed_paths(base, head, worktree=False, root=ROOT):
    paths = set(filter(None, git("diff", "--no-renames", "--name-only", "-z", base, head, root=root).split("\0")))
    if worktree:
        paths.update(filter(None, git("diff", "--no-renames", "--name-only", "-z", head, root=root).split("\0")))
        paths.update(filter(None, git("ls-files", "--others", "--exclude-standard", "-z", root=root).split("\0")))
    return sorted(paths)


def version_only(path, base, head, worktree, root=ROOT):
    if path not in VERSION_FILES and path != ".github/workflows/ci.yml":
        return False
    # Compare complete files, so dependency edits/deletion cannot hide in a version bump.
    before = git("show", f"{base}:{path}", root=root)
    after = (root / path).read_text(encoding="utf-8") if worktree else git("show", f"{head}:{path}", root=root)
    if path == ".github/workflows/ci.yml":
        # Changes outside the packaged Windows job do not invalidate Desktop.
        job = lambda value: re.search(r"^  desktop-windows:\n.*?(?=^  [\w-]+:|\Z)", value.replace("\r\n", "\n"), re.M | re.S)
        old_job, new_job = job(before), job(after)
        return bool(old_job and new_job and old_job.group() == new_job.group())
    if path.endswith(".json"):
        old, new = json.loads(before), json.loads(after)
        for data in (old, new):
            data.pop("version", None)
            if path == "package-lock.json":
                data.get("packages", {}).get("", {}).pop("version", None)
        return old == new
    if path == "backend/app/main.py":
        scrub = lambda value: re.sub(r'^APP_VERSION = "[0-9]+\.[0-9]+\.[0-9]+"$', 'APP_VERSION = "VERSION"', value, flags=re.M)
    elif path.endswith("Cargo.lock"):
        scrub = lambda value: re.sub(r'(name = "nexa-desktop"\nversion = )"[0-9]+\.[0-9]+\.[0-9]+"', r'\1"VERSION"', value)
    else:
        scrub = lambda value: re.sub(r'^version = "[0-9]+\.[0-9]+\.[0-9]+"$', 'version = "VERSION"', value, count=1, flags=re.M)
    return scrub(before.replace("\r\n", "\n")) == scrub(after.replace("\r\n", "\n"))


def classify(path, metadata=False):
    if metadata:
        return "MEDIUM", "validation-tooling" if path.startswith(".github/") else "release-metadata"
    if path.startswith(("docs/",)) or path.endswith(".md"):
        return "LOW", "documentation"
    if path.startswith(("backend/tests/", "tests/", "device-client/tests/", "agent-adapters/openclaw/tests/")) or path == "scripts/smoke-backend-sidecar.py":
        return "MEDIUM", "tests"
    for boundary, patterns in RULES:
        if any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns):
            return "HIGH", boundary
    if path.startswith(".github/workflows/"):
        return "HIGH", "packaging"
    if path in {".gitignore", ".validation-baseline.json", "scripts/change_impact.py", "scripts/detect-change-impact.py", "scripts/validate-release.py"}:
        return "MEDIUM", "validation-tooling"
    if path.startswith("backend/app/"):
        return "MEDIUM", "diagnostics" if "diagnostics" in path else "backend-service"
    if path.startswith(("src/api/", "src/types/", "src/stores/")):
        return "MEDIUM", "frontend-contract"
    if path.startswith("src/") or path.startswith("public/"):
        return "LOW", "diagnostics-presentation" if "Diagnostics" in path or "diagnostics" in path else "frontend-presentation"
    if path.startswith(("device-client/", "agent-adapters/")):
        return "MEDIUM", "client-service"
    return "HIGH", "unknown"


def analyze(paths, baseline, inherited_paths=None, metadata=(), inherited_metadata=()):
    classified = [classify(path, path in metadata) for path in paths]
    boundaries = {boundary for _, boundary in classified}
    inheritance = {classify(path, path in inherited_metadata)[1] for path in (paths if inherited_paths is None else inherited_paths)}
    if "unknown" in inheritance:
        inheritance.update(PROTECTED)
    statuses = {name: "REUSED" if value["status"] == "PASS" and not inheritance.intersection(value["boundaries"]) else "INVALIDATED"
                for name, value in baseline["validations"].items()}
    risk = max((level for level, _ in classified), key={"LOW": 0, "MEDIUM": 1, "HIGH": 2}.get, default="LOW")
    required = set()
    if paths:
        required.add("github-ci")
    if any(path.startswith("src/") or path in VERSION_FILES for path in paths):
        required.update(["frontend-targeted", "frontend-build"])
    if any(path.startswith("backend/") for path in paths):
        required.add("backend-targeted")
    if boundaries.intersection({"validation-tooling", "tests", "release-metadata"}):
        required.add("tooling-targeted")
    if any(path.startswith("device-client/") for path in paths):
        required.add("device-client-targeted")
    if any(path.startswith("agent-adapters/") for path in paths):
        required.add("openclaw-targeted")
    if risk == "HIGH":
        required.add("integration-tests")
    if boundaries.intersection({"sidecar", "packaging", "windows-packaging", "macos-packaging", "desktop", "unknown"}):
        required.add("packaged-smoke")
    invalid = sorted(name for name, status in statuses.items() if status == "INVALIDATED")
    required.update("physical:" + name for name in invalid)
    return {"risk": risk, "changedFiles": sorted(paths), "changedAreas": sorted({path.split("/")[0] for path in paths}),
            "changedBoundaries": sorted(boundaries), "inheritanceBoundaries": sorted(inheritance),
            "requiredValidation": sorted(required), "validations": statuses,
            "reusedValidation": sorted(name for name, status in statuses.items() if status == "REUSED"),
            "invalidatedValidation": invalid,
            "fullCrossDeviceE2ERequired": bool(set(invalid).intersection({"offline-recovery", "keep-local", "keep-remote"}))}


def arguments(description):
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--base", help="diff base; defaults to HEAD for the working tree")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--include-worktree", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def plan(args, root=ROOT):
    baseline = json.loads((root / ".validation-baseline.json").read_text(encoding="utf-8"))
    if not baseline.get("validations") or any(value.get("status") not in {"PASS", "FAIL", "NOT_RUN"} or not value.get("boundaries") or set(value["boundaries"]) - PROTECTED for value in baseline["validations"].values()):
        raise ValueError("Invalid validation baseline")
    head = git("rev-parse", "--verify", args.head + "^{commit}", root=root).strip()
    base = git("rev-parse", "--verify", (args.base or args.head) + "^{commit}", root=root).strip()
    previous = baseline["baselineCommit"]
    git("merge-base", "--is-ancestor", previous, head, root=root)
    worktree = args.include_worktree or args.base is None
    if worktree and head != git("rev-parse", "HEAD", root=root).strip():
        raise ValueError("Working tree analysis requires --head HEAD")
    paths = changed_paths(base, head, worktree, root)
    inherited = changed_paths(previous, head, worktree, root)
    def metadata_paths(files, start):
        result = []
        for path in files:
            try:
                if version_only(path, start, head, worktree, root):
                    result.append(path)
            except (ValueError, OSError):
                pass  # Added/deleted/invalid metadata remains conservative.
        return result
    result = analyze(paths, baseline, inherited, metadata_paths(paths, base), metadata_paths(inherited, previous))
    # An earlier core change still requires validation, even when this selected diff is UI-only.
    if result["invalidatedValidation"]:
        result["requiredValidation"] = sorted(set(result["requiredValidation"]) | {"github-ci", "integration-tests"})
    if set(result["inheritanceBoundaries"]).intersection({"sidecar", "packaging", "windows-packaging", "macos-packaging", "desktop", "unknown"}):
        result["requiredValidation"] = sorted(set(result["requiredValidation"]) | {"packaged-smoke"})
    result.update(head=head, baseline=previous, baselineVersion=baseline["baselineVersion"], base=base, includesWorktree=worktree)
    return result


def human(result, title="NEXA_CHANGE_IMPACT"):
    lines = [title]
    for key in ("head", "baseline", "risk", "changedAreas", "changedBoundaries", "requiredValidation", "reusedValidation", "invalidatedValidation", "fullCrossDeviceE2ERequired"):
        value = result[key]
        label = "FULL_CROSS_DEVICE_E2E_REQUIRED" if key == "fullCrossDeviceE2ERequired" else re.sub(r"(?<!^)(?=[A-Z])", "_", key).upper()
        lines.append(f"{label}=" + ("\n- " + "\n- ".join(value) if isinstance(value, list) and value else "NONE" if isinstance(value, list) else "YES" if value is True else "NO" if value is False else str(value)))
    return "\n".join(lines)
