"""Run the impact plan locally and report verified results; never publish a release."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from change_impact import ROOT, arguments, git, human, plan


def fingerprint(result):
    digest = hashlib.sha256(json.dumps(json.loads((ROOT / ".validation-baseline.json").read_text()), sort_keys=True).encode())
    for path in result["changedFiles"]:
        digest.update(path.encode("utf-8", errors="surrogateescape"))
        if result["includesWorktree"]:
            file = ROOT / path
            # Git's clean filters normalize Windows line endings just as commit does.
            blob = git("hash-object", "--path", path, path, root=ROOT).strip() if file.is_file() else "DELETED"
        else:
            try:
                blob = git("rev-parse", "--verify", f'{result["head"]}:{path}', root=ROOT).strip()
            except ValueError:
                blob = "DELETED"
        digest.update(blob.encode())
    return digest.hexdigest()


def commands(result):
    required = result["requiredValidation"]
    selected = {}
    if "tooling-targeted" in required:
        selected["tooling-targeted"] = [(ROOT, [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_validation_tooling.py"])]
    if "frontend-targeted" in required:
        selected["frontend-targeted"] = [(ROOT, ["node", "--test", "tests/diagnostics.test.mjs", "tests/automation.test.mjs", "tests/core-sync.test.mjs"])]
    if "frontend-build" in required:
        selected["frontend-build"] = [(ROOT, ["node", "node_modules/vue-tsc/bin/vue-tsc.js", "--noEmit"]),
                                      (ROOT, ["node", "node_modules/vite/bin/vite.js", "build"]),
                                      (ROOT, ["node", "node_modules/vite/bin/vite.js", "build", "--mode", "desktop"])]
    if "backend-targeted" in required:
        # Map ordinary services to existing tests; diagnostics touches Settings and health metadata.
        tests = {"tests/test_diagnostics.py", "tests/test_settings.py", "tests/test_desktop.py"}
        for path in result["changedFiles"]:
            if path.startswith("backend/tests/test_") and path.endswith(".py"):
                tests.add(path.removeprefix("backend/"))
            if path.startswith("backend/app/"):
                for name in ("ledger", "data", "websites", "automation", "agents", "devices", "dashboard"):
                    if name in path:
                        candidate = ROOT / "backend/tests" / f"test_{name if name != 'websites' else 'api'}.py"
                        if candidate.exists():
                            tests.add("tests/" + candidate.name)
        selected["backend-targeted"] = [(ROOT / "backend", [sys.executable, "-m", "pytest", "-q", *sorted(tests)])]
    if "integration-tests" in required:
        selected["integration-tests"] = [(ROOT / "backend", [sys.executable, "-m", "pytest", "-q", "tests/test_background_sync_integration.py", "tests/test_conflicts.py", "tests/test_core_connection_hardening.py", "tests/test_migrations.py"])]
    if "device-client-targeted" in required:
        selected["device-client-targeted"] = [(ROOT, [sys.executable, "-m", "pytest", "-q", "device-client/tests"])]
    if "openclaw-targeted" in required:
        selected["openclaw-targeted"] = [(ROOT / "agent-adapters/openclaw", [sys.executable, "-m", "pytest", "-q"])]
    return selected


def ci_status(run_id, head):
    if not run_id:
        return {"status": "NOT_RUN", "runId": None, "url": None}
    response = subprocess.run(["gh", "run", "view", run_id, "--json", "headSha,status,conclusion,url,jobs"], cwd=ROOT, capture_output=True, text=True)
    if response.returncode:
        raise ValueError("Unable to verify GitHub CI run")
    run = json.loads(response.stdout)
    if run["headSha"] != head:
        raise ValueError("CI run belongs to a different commit")
    passed = run["conclusion"] == "success" and all(job["conclusion"] == "success" for job in run["jobs"])
    return {"status": "PASS" if passed else "PENDING" if run["status"] != "completed" else "FAIL", "runId": run_id, "url": run["url"]}


def main():
    parser = arguments(__doc__)
    parser.add_argument("--run-local", action="store_true", help="execute supported required checks; physical/smoke checks remain NOT_RUN")
    parser.add_argument("--evidence", type=Path, help="save or reuse command results for the same tree (local trusted evidence)")
    parser.add_argument("--ci-run", help="verify this exact HEAD against a GitHub Actions run")
    args = parser.parse_args()
    # Release reports always cover all changes from the physical validation baseline.
    args.base = json.loads((ROOT / ".validation-baseline.json").read_text())["baselineCommit"]
    result = plan(args)
    if args.run_local and (not result["includesWorktree"] or result["head"] != git("rev-parse", "HEAD").strip()):
        raise ValueError("--run-local requires --head HEAD --include-worktree")
    tree = fingerprint(result)
    checks = {}
    if args.run_local:
        for name, entries in commands(result).items():
            checks[name] = "PASS"
            for cwd, command in entries:
                print(f"Running {name}: {' '.join(command)}", file=sys.stderr)
                completed = subprocess.run(command, cwd=cwd, stdout=sys.stderr, stderr=sys.stderr)
                if completed.returncode:
                    checks[name] = "FAIL"
                    break
        if args.evidence:
            if fingerprint(plan(args)) != tree:
                raise ValueError("Working tree changed during validation; evidence was not saved")
            args.evidence.write_text(json.dumps({"fingerprint": tree, "testedHead": result["head"], "checks": checks}, indent=2), encoding="utf-8")
    elif args.evidence:
        evidence = json.loads(args.evidence.read_text(encoding="utf-8"))
        if evidence["fingerprint"] != tree:
            raise ValueError("Validation evidence is stale for the current tree")
        checks = evidence["checks"]
    ci = ci_status(args.ci_run, result["head"])
    local = {name: checks.get(name, "NOT_RUN") for name in result["requiredValidation"] if name != "github-ci"}
    clean = not bool(git("status", "--porcelain").strip())
    ready = all(value == "PASS" for value in local.values()) and ci["status"] == "PASS" and clean
    result.update(version=json.loads((ROOT / "package.json").read_text())["version"], localValidation=local, ci=ci,
                  worktreeClean=clean, releaseReady=ready)
    print(json.dumps(result, indent=2) if args.json else human(result, "NEXA_VALIDATION_REPORT") +
          f'\nVERSION={result["version"]}\n' + "\n".join(f"{name.upper().replace('-', '_')}={status}" for name, status in local.items()) +
          f'\nCI={ci["status"]}\nWORKTREE_CLEAN={"YES" if clean else "NO"}\nRELEASE_READY={"YES" if ready else "NO"}')
    return 1 if "FAIL" in local.values() or ci["status"] == "FAIL" else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(f"Release validation failed: {error}", file=sys.stderr)
        sys.exit(1)
