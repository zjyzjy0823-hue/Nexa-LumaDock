from dataclasses import replace
import socket
from uuid import uuid4
import pytest
from sqlalchemy import select
from app.automation import webhook
from app.automation.schemas import Action, Schedule
from app.api.automation import routes
from app.database import get_db
from app.models import AutomationExecution
from app.runtime_mode import require_core_mode
from app.sync import publisher


@pytest.mark.parametrize("url", ["file:///etc/passwd", "http://example.com", "ftp://example.com", "https://localhost", "https://127.0.0.1", "https://[::1]", "https://169.254.169.254/latest", "https://10.1.1.1", "https://192.168.1.1", "https://172.16.0.1", "https://[::ffff:127.0.0.1]", "https://user:password@example.com", "https://example.com:8443"])
def test_webhook_rejects_unsafe_urls(url):
    with pytest.raises(ValueError):
        webhook.validate_url(url)


@pytest.mark.parametrize("address", ["127.0.0.1", "::1", "169.254.169.254", "10.0.0.1", "192.168.0.1", "224.0.0.1", "::ffff:10.0.0.1"])
def test_dns_private_and_mixed_answers_rejected(monkeypatch, address):
    monkeypatch.setattr(webhook.socket, "getaddrinfo", lambda *args, **kwargs: [(2, 1, 6, '', ("8.8.8.8", 443)), (2, 1, 6, '', (address, 443))])
    with pytest.raises(webhook.ActionError, match="webhook_private_address"):
        webhook.resolve_public("public.example")


@pytest.mark.parametrize("config", [
    {"url": "https://example.com", "headers": {"Authorization": "FAKE_ONLY"}},
    {"url": "https://example.com", "headers": {"X-Api-Key": "FAKE_ONLY"}},
    {"url": "https://example.com", "headers": {"Accept": "abc\r\nInjected: x"}},
    {"url": "https://example.com", "body": {"password": "FAKE_ONLY"}},
    {"url": "https://example.com", "body": {"nested": [{"api_key": "FAKE_ONLY"}]}},
    {"url": "https://example.com/?token=FAKE_ONLY"},
    {"url": "https://example.com", "body": {"note": "Bearer FAKE_ONLY"}},
])
def test_secret_fields_never_sync(config):
    with pytest.raises(ValueError):
        Action(type="webhook.post", config=config)


@pytest.mark.parametrize("status,length,body,error,retry", [(200, 0, b'', None, False), (302, 0, b'', "webhook_redirect", False),
    (503, 0, b'', "webhook_http_error", True), (400, 0, b'', "webhook_http_error", False),
    (200, 65537, b'', "webhook_response_too_large", False), (200, None, b'x' * 65537, "webhook_response_too_large", False)], ids=["success", "redirect", "retryable", "permanent", "large-length", "large-stream"])
def test_webhook_bounded_post_safe_summary_idempotency(monkeypatch, status, length, body, error, retry):
    captured = {}
    class Response:
        def __init__(self):
            self.status, self.length, self.body = status, length, body
        def read1(self, count):
            chunk, self.body = self.body[:count], self.body[count:]
            return chunk
    class Connection:
        sock = None
        def __init__(self, host, address, timeout):
            captured.update(host=host, address=address, timeout=timeout)
        def request(self, method, path, body, headers):
            captured.update(method=method, path=path, headers=headers)
        def getresponse(self):
            return Response()
        def close(self):
            captured["closed"] = True
    monkeypatch.setattr(webhook, "resolve_public", lambda *args: "8.8.8.8")
    monkeypatch.setattr(webhook, "PinnedHTTPSConnection", Connection)
    config = Action(type="webhook.post", config={"url": "https://example.com/hook?a=1", "body": {"safe": True}}).config
    if error:
        with pytest.raises(webhook.ActionError) as caught:
            webhook.post(config, "execution-test")
        assert caught.value.code == error and caught.value.retryable == retry
    else:
        assert webhook.post(config, "execution-test") == {"statusCode": 200}
    assert captured["headers"]["Idempotency-Key"] == "execution-test"
    assert captured["method"] == "POST" and captured["address"] == "8.8.8.8" and captured["closed"]


def test_webhook_timeout_classification(monkeypatch):
    class TimeoutConnection:
        sock = None
        def __init__(self, *args):
            pass
        def request(self, *args):
            raise socket.timeout()
        def close(self):
            pass
    monkeypatch.setattr(webhook, "resolve_public", lambda *args: "8.8.8.8")
    monkeypatch.setattr(webhook, "PinnedHTTPSConnection", TimeoutConnection)
    with pytest.raises(webhook.ActionError) as caught:
        webhook.post({"url": "https://example.com", "headers": {}, "body": {}, "timeout": 1}, "execution-test")
    assert caught.value.retryable and caught.value.code == "webhook_network"


def test_manual_runtime_api_replay_permissions_and_local_fallback(client, users, monkeypatch):
    owner, other = users
    root = "/api/v1/automations"
    value = {"name": "Runtime API", "workflow_json": [{"kind": "DO", "action": {"type": "ledger.create", "config": {"type": "expense", "amount": "10", "description": "API", "occurred_at": "2030-01-01T00:00:00Z"}}}]}
    created = client.post(root, headers=owner, json=value); assert created.status_code == 201
    wid = created.json()["id"]
    assert client.post(f"{root}/{wid}/run", headers=owner).status_code == 503
    assert client.get(f"{root}/{wid}/executions?runtime=true", headers=owner).status_code == 503
    assert client.patch(f"{root}/{wid}", headers=owner, json={"description": "Offline edit"}).status_code == 200
    monkeypatch.setattr(routes, "runtime_config", replace(routes.runtime_config, mode="core"))
    request_id = str(uuid4())
    runs = [client.post(f"{root}/{wid}/run", headers=owner, json={"request_id": request_id}) for _ in range(2)]
    assert all(run.status_code == 201 for run in runs)
    eid = runs[0].json()["id"]; assert eid == runs[1].json()["id"]
    assert client.post(f"{root}/{wid}/run", headers=owner).json()["id"] != client.post(f"{root}/{wid}/run", headers=owner).json()["id"]
    assert client.get(f"{root}/{wid}/executions/{eid}", headers=owner).json()["action"]["type"] == "ledger.create"
    for path, method in (("run", "post"), ("executions", "get"), (f"executions/{eid}", "get"), ("runtime", "get")):
        assert getattr(client, method)(f"{root}/{wid}/{path}", headers=other).status_code == 404
    app = client.app; app.dependency_overrides[require_core_mode] = lambda: None
    enrollment = client.post("/api/v1/clients/enroll", headers=owner, json={"installationId": str(uuid4()), "name": "Runtime Client", "platform": "windows", "appVersion": "0.6.0"})
    assert enrollment.status_code == 201
    headers = {"Authorization": "Bearer " + enrollment.json()["credential"]}
    assert client.get(f"/api/v1/client/automations/{wid}/executions", headers=headers).status_code == 200
    assert client.post(f"{root}/{wid}/run", headers=headers).status_code == 401  # Client cannot edit/manage
    assert client.post(f"/api/v1/client/automations/{wid}/run", headers=headers, json={"request_id": request_id}).json()["id"] == eid


def test_local_engine_cannot_start():
    from app.automation.engine import AutomationEngine
    with pytest.raises(RuntimeError, match="Core-only"):
        AutomationEngine(None).start()
