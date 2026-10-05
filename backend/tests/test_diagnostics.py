from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select

from app.api import diagnostics
from app.database import get_db
from app.main import app
from app.models import LocalMutation, LocalSyncState
from app.runtime_mode import require_core_mode


def test_diagnostics_auth_disconnected_and_user_scope(client, users, monkeypatch):
    monkeypatch.setattr(diagnostics.core_connection, "load_connection", lambda _: None)
    assert client.get("/api/v1/settings/diagnostics").status_code == 401
    assert client.get("/api/v1/client/diagnostics").status_code == 404  # Existing Local/Core boundary.
    app.dependency_overrides[require_core_mode] = lambda: None
    assert client.get("/api/v1/client/diagnostics").status_code == 401
    assert client.get("/api/v1/client/diagnostics", headers=users[0]).status_code == 401
    a, b = users
    result = client.get("/api/v1/settings/diagnostics", headers=a)
    assert result.status_code == 200
    assert result.headers["cache-control"] == "no-store"
    body = result.json()
    assert body["backend"] == "healthy"
    assert body["database"] == {"kind": "sqlite", "status": "ok"}
    assert body["core"]["status"] == "disconnected"
    assert body["protocol"] == {"local": 3, "core": None, "compatible": None}
    assert body["automation"]["local"] == {"scheduler": False, "worker": False}
    assert body["workspaceId"] != client.get("/api/v1/settings/diagnostics", headers=b).json()["workspaceId"]
    with next(app.dependency_overrides[get_db]()) as db:
        assert db.scalar(select(LocalSyncState)) is None  # Diagnostics does not seed sync.


def test_counts_and_error_redaction(client, users, monkeypatch):
    monkeypatch.setattr(diagnostics.core_connection, "load_connection", lambda _: None)
    a, b = users
    workspace_id = client.get("/api/v1/workspace", headers=a).json()["id"]
    with next(app.dependency_overrides[get_db]()) as db:
        db.add(LocalSyncState(workspace_id=workspace_id, last_error="Bearer secret-jwt password=secret-password cookie=secret-cookie"))
        for status in ("pending", "pending", "conflict", "in_flight", "rejected"):
            db.add(LocalMutation(id=str(uuid4()), mutation_id=str(uuid4()), workspace_id=workspace_id, entity_type="ledger.entry",
                   entity_id=str(uuid4()), operation="upsert", payload_json={}, base_revision=0, status=status))
        db.commit()
    result = client.get("/api/v1/settings/diagnostics", headers=a)
    assert result.status_code == 200, result.text
    assert result.json()["sync"] == {"pending": 2, "rejected": 1, "conflicts": 1, "inFlight": 1, "lastSuccessAt": None, "lastError": "internal_error"}
    assert "secret-" not in result.text
    assert client.get("/api/v1/settings/diagnostics", headers=b).json()["sync"]["pending"] == 0


@pytest.mark.parametrize("protocol", [3, 4, None])
def test_connected_protocol_runtime_and_allowlist(client, users, monkeypatch, protocol):
    metadata = SimpleNamespace(coreUrl="https://core.example", clientId=str(uuid4()), workspaceId=str(uuid4()))
    secret = "nc_live_do-not-export-this-token"
    monkeypatch.setattr(diagnostics.core_connection, "load_connection", lambda _: metadata)
    monkeypatch.setattr(diagnostics.core_connection.credential_store, "load", lambda _: secret)
    monkeypatch.setattr(diagnostics.core_connection, "test_connection", lambda _: {"status": "connected"})
    def remote(request):
        assert request.headers["authorization"] == "Bearer " + secret
        return httpx.Response(200, json={"protocol": protocol, "clientId": metadata.clientId,
            "workspaceId": metadata.workspaceId, "automation": {"scheduler": True, "worker": True, "password": secret},
            "authorization": secret, "JWT": secret, "cookie": secret, "requestBody": {"secret": secret}})
    monkeypatch.setattr(diagnostics.core_connection, "_http_client", lambda: httpx.Client(transport=httpx.MockTransport(remote)))
    result = client.get("/api/v1/settings/diagnostics", headers=users[0])
    assert result.status_code == 200, result.text
    assert result.json()["protocol"]["compatible"] is (None if protocol is None else protocol == 3)
    assert result.json()["automation"]["core"] == {"scheduler": True, "worker": True}
    assert result.json()["core"]["tokenConfigured"] is True
    for forbidden in (secret, "authorization", "JWT", "cookie", "password", "requestBody"):
        assert forbidden not in result.text


def test_probe_errors_and_bad_origins_cannot_leak(client, users, monkeypatch):
    monkeypatch.setattr(diagnostics.core_connection, "load_connection", lambda _: (_ for _ in ()).throw(RuntimeError("password=secret token=secret")))
    result = client.get("/api/v1/settings/diagnostics", headers=users[0])
    assert result.json()["core"]["status"] == "unavailable"
    assert "secret" not in result.text
    monkeypatch.setattr(diagnostics.core_connection, "load_connection", lambda _: SimpleNamespace(coreUrl="https://name:secret@core.example/?token=secret"))
    result = client.get("/api/v1/settings/diagnostics", headers=users[0])
    assert result.json()["core"]["url"] is None
    assert "secret" not in result.text


@pytest.mark.parametrize("code,status", [(404, "connected"), (401, "unauthorized"), (503, "unreachable"), (302, "unreachable")])
def test_older_core_and_remote_failures_are_unverified(client, users, monkeypatch, code, status):
    metadata = SimpleNamespace(coreUrl="https://core.example", clientId=str(uuid4()), workspaceId=str(uuid4()))
    monkeypatch.setattr(diagnostics.core_connection, "load_connection", lambda _: metadata)
    monkeypatch.setattr(diagnostics.core_connection.credential_store, "load", lambda _: "secret-token")
    monkeypatch.setattr(diagnostics.core_connection, "test_connection", lambda _: {"status": "connected"})
    monkeypatch.setattr(diagnostics.core_connection, "_http_client", lambda: httpx.Client(transport=httpx.MockTransport(
        lambda _: httpx.Response(code, json={"detail": "password=secret-password credential=secret-token"}))))
    result = client.get("/api/v1/settings/diagnostics", headers=users[0])
    assert result.json()["core"]["status"] == status
    assert result.json()["protocol"]["compatible"] is None
    assert result.json()["automation"]["core"]["scheduler"] is None
    assert "secret-" not in result.text


def test_core_client_runtime_uses_actual_task_and_existing_auth(client, users, monkeypatch):
    item = SimpleNamespace(id=str(uuid4()), workspace_id=str(uuid4()))
    app.dependency_overrides[diagnostics.client_from_token] = lambda: item
    monkeypatch.setattr(app.state, "automation_engine", SimpleNamespace(task=SimpleNamespace(done=lambda: False)), raising=False)
    response = client.get("/api/v1/client/diagnostics")
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {"protocol": 3, "clientId": item.id, "workspaceId": item.workspace_id,
                              "automation": {"scheduler": True, "worker": True}}
