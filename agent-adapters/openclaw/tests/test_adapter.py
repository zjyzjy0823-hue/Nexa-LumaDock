import json
import subprocess

import httpx
import pytest

from config import load_config
from main import process_task, run_once
from nexa import FatalApiError, NexaClient
from openclaw import ExecutionResult, execute_task


def config():
    return {"serverUrl": "http://127.0.0.1:8000", "agentToken": "na_live_" + "x" * 43,
            "runtimeInstance": "desktop-test", "pollIntervalSeconds": 10,
            "executionTimeoutSeconds": 60}


class FakeApi:
    def __init__(self):
        self.calls = []
        self.queue = [{"id": "task-1", "title": "Inspect", "description": "Summarize"}]

    def heartbeat(self, status, instance, task_id=None):
        self.calls.append(("heartbeat", status, task_id))

    def tasks(self):
        self.calls.append(("tasks",))
        return self.queue

    def claim(self, task_id):
        self.calls.append(("claim", task_id))
        return {"id": task_id}

    def event(self, task_id, kind, message, level="info"):
        self.calls.append(("event", kind, level))

    def complete(self, task_id, text):
        self.calls.append(("complete", task_id, text))

    def fail(self, task_id, error):
        self.calls.append(("fail", task_id, error))


def test_heartbeat_poll_claim_execute_complete():
    api = FakeApi()
    run_once(api, config(), lambda title, description, timeout: ExecutionResult(f"{title}: {description}"))
    assert api.calls[0:4] == [("heartbeat", "idle", None), ("tasks",),
                              ("claim", "task-1"), ("heartbeat", "running", "task-1")]
    assert api.calls[-1] == ("complete", "task-1", "Inspect: Summarize")
    assert ("event", "task.log", "success") in api.calls


def test_executor_error_reports_failed_task():
    api = FakeApi()

    def broken(*_args):
        raise RuntimeError("OpenClaw unavailable")

    assert process_task(api, config(), api.queue[0], broken)
    assert api.calls[-1] == ("fail", "task-1", "OpenClaw unavailable")
    assert ("event", "task.log", "error") in api.calls


@pytest.mark.parametrize("code", [401, 422])
def test_rejected_credentials_and_payload_fail_fast(code):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(code, json={"detail": "rejected"})

    api = NexaClient(config(), httpx.MockTransport(handler))
    with pytest.raises(FatalApiError):
        api.tasks()
    assert len(requests) == 1
    api.close()


def test_network_retry(monkeypatch):
    monkeypatch.setattr("nexa.time.sleep", lambda _: None)
    count = 0

    def handler(request):
        nonlocal count
        count += 1
        if count < 3:
            raise httpx.ConnectError("offline")
        return httpx.Response(200, json=[])

    api = NexaClient(config(), httpx.MockTransport(handler))
    assert api.tasks() == []
    assert count == 3
    api.close()


def test_openclaw_prompt_is_stdin_and_result_checked(monkeypatch):
    seen = {}
    monkeypatch.setattr("openclaw.shutil.which", lambda _: "openclaw")

    def fake_run(argv, **kwargs):
        seen.update(argv=argv, kwargs=kwargs)
        return subprocess.CompletedProcess(argv, 0, json.dumps({"ok": True, "status": "ok", "final": "done"}), "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert execute_task("Inspect", "Summarize", 60).text == "done"
    assert seen["argv"] == ["openclaw", "agent", "exec", "--message-file", "-", "--json", "--timeout", "60"]
    assert seen["kwargs"]["input"] == "Task: Inspect\n\nInstructions:\nSummarize"
    assert "shell" not in seen["kwargs"]


@pytest.mark.parametrize("problem", ["missing", "timeout", "exit", "invalid"])
def test_openclaw_execution_failures(monkeypatch, problem):
    monkeypatch.setattr("openclaw.shutil.which", lambda _: "openclaw")
    def fake_run(argv, **kwargs):
        if problem == "missing":
            raise FileNotFoundError()
        if problem == "timeout":
            raise subprocess.TimeoutExpired(argv, 1)
        if problem == "exit":
            return subprocess.CompletedProcess(argv, 1, "", "failed")
        return subprocess.CompletedProcess(argv, 0, "not-json", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(RuntimeError):
        execute_task("Inspect", "", 60)


def test_config_https_policy_and_secret_validation(tmp_path):
    path = tmp_path / "config.json"
    settings = {"serverUrl": "http://example.com", "agentToken": "na_live_" + "x" * 43,
                "runtimeInstance": "test"}
    path.write_text(json.dumps(settings), encoding="utf-8")
    with pytest.raises(ValueError):
        load_config(path)
    settings["serverUrl"] = "https://example.com"
    path.write_text(json.dumps(settings), encoding="utf-8")
    assert load_config(path)["serverUrl"] == "https://example.com"
    settings["agentToken"] = "bad"
    path.write_text(json.dumps(settings), encoding="utf-8")
    with pytest.raises(ValueError):
        load_config(path)
