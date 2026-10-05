import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from change_impact import analyze, classify, plan

spec = importlib.util.spec_from_file_location("release", ROOT / "scripts/validate-release.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)
BASELINE = json.loads((ROOT / ".validation-baseline.json").read_text())


class ImpactTests(unittest.TestCase):
    def test_low_medium_high_and_multiple(self):
        for path, risk in [("src/components/automation/Workflow.vue", "LOW"), ("src/styles/app.css", "LOW"),
                           ("backend/app/api/ledger.py", "MEDIUM"), ("backend/app/sync/engine.py", "HIGH")]:
            with self.subTest(path=path):
                self.assertEqual(analyze([path], BASELINE)["risk"], risk)
        result = analyze(["src/styles/app.css", "backend/app/api/ledger.py"], BASELINE)
        self.assertEqual(result["risk"], "MEDIUM")
        self.assertEqual(result["changedAreas"], ["backend", "src"])

    def test_unchanged_and_automation_ui_inherit(self):
        for paths in ([], ["src/components/automation/Workflow.vue"]):
            result = analyze(paths, BASELINE)
            self.assertFalse(result["invalidatedValidation"])
            self.assertFalse(result["fullCrossDeviceE2ERequired"])

    def test_sync_conflict_and_migration_invalidate(self):
        for path in ("backend/app/sync/engine.py", "backend/app/sync/conflicts.py", "backend/migrations/versions/0018.py"):
            result = analyze([path], BASELINE)
            self.assertIn("keep-local", result["invalidatedValidation"])
            self.assertIn("keep-remote", result["invalidatedValidation"])
            self.assertTrue(result["fullCrossDeviceE2ERequired"])
        self.assertIn("offline-recovery", analyze(["backend/app/sync/engine.py"], BASELINE)["invalidatedValidation"])

    def test_platform_specific_packaging(self):
        result = analyze(["src-tauri/tauri.windows.conf.json"], BASELINE)
        self.assertEqual(result["invalidatedValidation"], ["windows-desktop"])
        self.assertIn("macos-desktop", result["reusedValidation"])
        self.assertIn("keep-local", result["reusedValidation"])
        result = analyze(["src-tauri/tauri.macos.conf.json"], BASELINE)
        self.assertEqual(result["invalidatedValidation"], ["macos-desktop"])

    def test_identity_unknown_and_failed_baseline_are_conservative(self):
        for path in ("backend/app/security.py", "unexpected/new-file"):
            self.assertTrue(analyze([path], BASELINE)["invalidatedValidation"])
        baseline = json.loads(json.dumps(BASELINE))
        baseline["validations"]["keep-local"]["status"] = "FAIL"
        self.assertEqual(analyze([], baseline)["validations"]["keep-local"], "INVALIDATED")

    def test_selected_range_does_not_hide_earlier_sync_changes(self):
        result = analyze(["src/foo.css"], BASELINE, ["src/foo.css", "backend/app/sync/engine.py"])
        self.assertIn("offline-recovery", result["invalidatedValidation"])

    def test_version_only_is_metadata_but_dependency_changes_are_high(self):
        self.assertEqual(classify("package.json", metadata=True), ("MEDIUM", "release-metadata"))
        self.assertEqual(classify("package.json"), ("HIGH", "packaging"))

    def test_git_inputs_staged_untracked_deleted_renamed_and_version_diff(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def git(*args):
                return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
            git("init")
            git("config", "user.name", "Test")
            git("config", "user.email", "test@example.invalid")
            (root / "backend/app/sync").mkdir(parents=True)
            engine = root / "backend/app/sync/engine.py"
            engine.write_text("original")
            (root / "package.json").write_text('{"version":"0.6.0","dependencies":{}}')
            git("add", ".")
            git("commit", "-m", "baseline")
            baseline = json.loads(json.dumps(BASELINE))
            baseline["baselineCommit"] = git("rev-parse", "HEAD").stdout.decode().strip()
            (root / ".validation-baseline.json").write_text(json.dumps(baseline))
            (root / "package.json").write_text('{"version":"0.6.1","dependencies":{}}')
            git("add", "package.json")
            (root / "docs").mkdir()
            (root / "docs/a.md").write_text("untracked")
            args = argparse.Namespace(base=None, head="HEAD", include_worktree=False)
            result = plan(args, root)
            self.assertIn("docs/a.md", result["changedFiles"])
            self.assertEqual(result["risk"], "MEDIUM")
            self.assertFalse(result["invalidatedValidation"])
            (root / "package.json").write_text('{"version":"0.6.1","dependencies":{"new":"1"}}')
            self.assertIn("packaging", plan(args, root)["changedBoundaries"])
            git("mv", "backend/app/sync/engine.py", "backend/app/renamed.py")
            result = plan(args, root)
            self.assertIn("sync", result["changedBoundaries"])
            self.assertIn("offline-recovery", result["invalidatedValidation"])
            (root / "docs/a.md").write_bytes(b"Windows\r\nline endings\r\n")
            with patch.object(release, "ROOT", root):
                before_commit = release.fingerprint(plan(args, root))
            git("add", ".")
            git("commit", "-m", "rename")
            args.base = baseline["baselineCommit"]
            args.include_worktree = False
            self.assertIn("sync", plan(args, root)["changedBoundaries"])
            with patch.object(release, "ROOT", root):
                self.assertEqual(before_commit, release.fingerprint(plan(args, root)))
                (root / "docs/a.md").write_text("changed after test")
                args.include_worktree = True
                self.assertNotEqual(before_commit, release.fingerprint(plan(args, root)))

    def test_report_never_claims_unexecuted_smoke(self):
        result = analyze(["src-tauri/src/backend_startup.rs"], BASELINE)
        self.assertIn("packaged-smoke", result["requiredValidation"])
        self.assertNotIn("packaged-smoke", release.commands(result))
        self.assertEqual(release.ci_status(None, "head")["status"], "NOT_RUN")

    def test_ci_requires_exact_commit_and_all_jobs_success(self):
        run = {"headSha": "current", "workflowName": "CI", "status": "completed", "conclusion": "success", "url": "https://example.invalid",
               "jobs": [{"name": name, "conclusion": "success"} for name in ("frontend", "backend", "backend-postgres", "device-client", "openclaw-adapter", "desktop-windows", "validation-impact")]}
        with patch.object(release.subprocess, "run", return_value=SimpleResult(json.dumps(run))):
            self.assertEqual(release.ci_status("123", "current")["status"], "PASS")
            with self.assertRaises(ValueError):
                release.ci_status("123", "other")
        run["jobs"][0]["conclusion"] = "skipped"
        with patch.object(release.subprocess, "run", return_value=SimpleResult(json.dumps(run))):
            self.assertEqual(release.ci_status("123", "current")["status"], "FAIL")
        run.update(status="in_progress", conclusion="")
        with patch.object(release.subprocess, "run", return_value=SimpleResult(json.dumps(run))):
            self.assertEqual(release.ci_status("123", "current")["status"], "PENDING")
        run["workflowName"] = "Other workflow"
        with patch.object(release.subprocess, "run", return_value=SimpleResult(json.dumps(run))):
            with self.assertRaises(ValueError):
                release.ci_status("123", "current")
        run.update(workflowName="CI", status="completed", conclusion="success", jobs=[])
        with patch.object(release.subprocess, "run", return_value=SimpleResult(json.dumps(run))):
            self.assertEqual(release.ci_status("123", "current")["status"], "FAIL")


class SimpleResult:
    def __init__(self, stdout):
        self.stdout, self.returncode = stdout, 0


if __name__ == "__main__":
    unittest.main()
