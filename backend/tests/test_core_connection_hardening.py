"""Recovery after remote enrollment and strict Local connection persistence."""

import json
from datetime import datetime, timezone
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app import core_connection
from app.credential_store import FileCredentialStore
from app.database import get_db
from app.main import app
from app.models import Client
from app.runtime_mode import require_core_mode


def register(test_client, name):
    response = test_client.post("/api/v1/auth/register", json={
        "username": name, "password": "password123"})
    assert response.status_code == 201, response.text
    return {"Authorization": "Bearer " + response.json()["access_token"]}


def proxy_core(test_client, monkeypatch, calls, tokens):
    """Mock only the transport; remote requests still use actual Core routes and DB."""
    def handle(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        response = test_client.request(request.method, request.url.path,
                                       headers=dict(request.headers), content=request.content)
        if request.url.path in ("/api/v1/clients/enroll",) or request.url.path.endswith("/credential"):
            if response.status_code in (200, 201):
                tokens.append(response.json()["credential"])
        return httpx.Response(response.status_code, content=response.content, headers=dict(response.headers))

    monkeypatch.setattr(core_connection, "_http_client", lambda: httpx.Client(
        transport=httpx.MockTransport(handle), timeout=core_connection.TIMEOUT,
        follow_redirects=False))


def connect_payload():
    return {"coreUrl": "https://core.example", "username": "remote_owner",
            "password": "password123", "clientName": "Windows PC", "platform": "windows",
            "appVersion": "0.5.2"}


def test_failed_local_save_recovers_with_explicit_rotation(client, monkeypatch, tmp_path, caplog):
    app.dependency_overrides[require_core_mode] = lambda: None
    installation_id = str(uuid4())
    monkeypatch.setenv("NEXA_INSTALLATION_ID", installation_id)
    monkeypatch.setenv("NEXA_DATA_DIR", str(tmp_path))
    remote_headers = register(client, "remote_owner")
    local_headers = register(client, "local_owner")
    calls, tokens = [], []
    proxy_core(client, monkeypatch, calls, tokens)
    store = core_connection.credential_store
    original_stage = store.stage

    def fail_first_write(_user_id, _credential):
        monkeypatch.setattr(store, "stage", original_stage)
        raise OSError("simulated disk failure")

    monkeypatch.setattr(store, "stage", fail_first_write)
    first = client.post("/api/v1/core/connect", headers=local_headers, json=connect_payload())
    assert first.status_code == 500
    assert first.json()["detail"] == "Local Core connection could not be saved"
    assert client.get("/api/v1/core/connection", headers=local_headers).json() == {"connected": False}
    assert len(tokens) == 1
    assert not (tmp_path / "core-connections" / "2" / "credential").exists()

    db_iterator = app.dependency_overrides[get_db]()
    db = next(db_iterator)
    try:
        old_hash = db.scalar(select(Client.token_hash).where(Client.installation_id == installation_id))
        assert old_hash is not None
    finally:
        db_iterator.close()

    calls.clear()
    second = client.post("/api/v1/core/connect", headers=local_headers, json=connect_payload())
    assert second.status_code == 200, second.text
    assert second.json()["installationId"] == installation_id
    assert ("GET", "/api/v1/clients") in calls
    assert any(method == "POST" and path.endswith("/credential") for method, path in calls)
    assert len(tokens) == 2 and tokens[0] != tokens[1]
    assert client.get("/api/v1/client/me", headers={"Authorization": "Bearer " + tokens[0]}).status_code == 401
    assert client.get("/api/v1/client/me", headers={"Authorization": "Bearer " + tokens[1]}).status_code == 200
    db_iterator = app.dependency_overrides[get_db]()
    db = next(db_iterator)
    try:
        assert db.scalar(select(Client.token_hash).where(Client.installation_id == installation_id)) != old_hash
    finally:
        db_iterator.close()
    directory = tmp_path / "core-connections" / "2"
    assert (directory / "credential").read_text(encoding="ascii") == tokens[1]
    metadata = json.loads((directory / "connection.json").read_text(encoding="utf-8"))
    assert metadata["schemaVersion"] == 1
    assert metadata["installationId"] == installation_id
    assert tokens[0] not in json.dumps(metadata) and tokens[1] not in json.dumps(metadata)
    assert "password123" not in json.dumps(metadata)
    assert client.post("/api/v1/core/connection/test", headers=local_headers).json() == {
        "connected": True, "status": "connected"}
    assert client.post("/api/v1/core/connect", headers=local_headers, json=connect_payload()).status_code == 409
    core_connection.credential_store.delete(2)
    assert client.post("/api/v1/core/connection/test", headers=local_headers).json() == {
        "connected": False, "status": "unauthorized"}
    assert client.post("/api/v1/core/connect", headers=local_headers, json=connect_payload()).status_code == 409
    for secret in tokens:
        assert secret not in caplog.text
    assert "password123" not in caplog.text
    assert client.get("/api/v1/clients", headers=remote_headers).status_code == 200


def test_revoked_client_cannot_be_recovered(client, monkeypatch, tmp_path):
    app.dependency_overrides[require_core_mode] = lambda: None
    installation_id = str(uuid4())
    monkeypatch.setenv("NEXA_INSTALLATION_ID", installation_id)
    monkeypatch.setenv("NEXA_DATA_DIR", str(tmp_path))
    remote_headers = register(client, "remote_owner")
    local_headers = register(client, "local_owner")
    enrolled = client.post("/api/v1/clients/enroll", headers=remote_headers, json={
        "installationId": installation_id, "name": "PC", "platform": "windows", "appVersion": "0.5.2"})
    assert enrolled.status_code == 201
    client_id = enrolled.json()["client"]["id"]
    assert client.post(f"/api/v1/clients/{client_id}/revoke", headers=remote_headers).status_code == 200
    calls, tokens = [], []
    proxy_core(client, monkeypatch, calls, tokens)
    response = client.post("/api/v1/core/connect", headers=local_headers, json=connect_payload())
    assert response.status_code == 409
    assert response.json()["detail"] == "Core Client is revoked"
    assert ("GET", "/api/v1/clients") in calls
    assert not any(path.endswith("/credential") for _, path in calls)
    assert not tokens
    assert client.get(f"/api/v1/clients/{client_id}", headers=remote_headers).json()["revokedAt"] is not None
    assert client.get("/api/v1/core/connection", headers=local_headers).json() == {"connected": False}


def test_unmatched_enrollment_conflict_never_rotates(client, monkeypatch, tmp_path):
    monkeypatch.setenv("NEXA_INSTALLATION_ID", str(uuid4()))
    monkeypatch.setenv("NEXA_DATA_DIR", str(tmp_path))
    local_headers = register(client, "local_owner")
    calls = []
    workspace_id = str(uuid4())

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/api/health":
            return httpx.Response(200, json={"status": "ok", "service": "nexa"})
        if request.url.path == "/api/v1/auth/login":
            return httpx.Response(200, json={"access_token": "short-lived-jwt"})
        if request.url.path == "/api/v1/workspace":
            return httpx.Response(200, json={"id": workspace_id})
        if request.url.path == "/api/v1/clients/enroll":
            return httpx.Response(409, json={"detail": "Client is already enrolled"})
        if request.url.path == "/api/v1/clients":
            return httpx.Response(200, json=[{"id": str(uuid4()), "installationId": str(uuid4()),
                                             "revokedAt": None}])
        raise AssertionError("Unexpected credential rotation")

    monkeypatch.setattr(core_connection, "_http_client", lambda: httpx.Client(
        transport=httpx.MockTransport(handle), follow_redirects=False))
    response = client.post("/api/v1/core/connect", headers=local_headers, json=connect_payload())
    assert response.status_code == 409
    assert response.json()["detail"] == "Core enrollment state is inconsistent"
    assert "/api/v1/clients" in calls
    assert not any(path.endswith("/credential") for path in calls)
    assert not (tmp_path / "core-connections").exists()


def test_core_http_error_has_structured_private_details():
    def conflict(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"detail": "remote detail must stay private"})

    with httpx.Client(transport=httpx.MockTransport(conflict)) as remote:
        with pytest.raises(core_connection.CoreRequestError) as error:
            core_connection._json_request(remote, "POST", "https://core.example",
                                          "/api/v1/clients/enroll", json={})
    assert error.value.status_code == 409
    assert error.value.endpoint == "/api/v1/clients/enroll"
    assert error.value.detail == "remote detail must stay private"
    assert "remote detail" not in str(error.value)


def sample_metadata() -> dict:
    return {"schemaVersion": 1, "coreUrl": "https://core.example", "clientId": str(uuid4()),
            "workspaceId": str(uuid4()), "installationId": str(uuid4()),
            "clientName": "PC", "platform": "windows", "appVersion": "0.5.2",
            "connectedAt": datetime.now(timezone.utc).isoformat()}


def test_metadata_validation_and_legacy_upgrade(client, monkeypatch, tmp_path):
    monkeypatch.setenv("NEXA_DATA_DIR", str(tmp_path))
    headers = register(client, "metadata_owner")
    path = tmp_path / "core-connections" / "1" / "connection.json"
    path.parent.mkdir(parents=True)
    valid = sample_metadata()
    path.write_text(json.dumps(valid), encoding="utf-8")
    response = client.get("/api/v1/core/connection", headers=headers)
    assert response.status_code == 200
    assert response.json()["workspaceId"] == valid["workspaceId"]
    assert "schemaVersion" not in response.json()

    legacy = {key: value for key, value in valid.items() if key != "schemaVersion"}
    path.write_text(json.dumps(legacy), encoding="utf-8")
    assert client.get("/api/v1/core/connection", headers=headers).status_code == 200
    assert json.loads(path.read_text(encoding="utf-8"))["schemaVersion"] == 1

    invalids = ["{broken", json.dumps({key: value for key, value in valid.items() if key != "clientId"})]
    for field, value in (("workspaceId", "not-uuid"), ("platform", "watchos"),
                         ("coreUrl", "file:///private"), ("schemaVersion", 2),
                         ("connectedAt", "not-a-time"), ("connectedAt", 123456789)):
        invalids.append(json.dumps({**valid, field: value}))
    for value in invalids:
        path.write_text(value, encoding="utf-8")
        response = client.get("/api/v1/core/connection", headers=headers)
        assert response.status_code == 500
        assert response.json()["detail"] == "Local Core connection is invalid"
    assert "password" not in path.read_text(encoding="utf-8")


def test_file_credential_store_and_staging_failure(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXA_DATA_DIR", str(tmp_path))
    store = FileCredentialStore()
    assert store.load(7) is None
    store.save(7, "nc_live_first")
    assert store.load(7) == "nc_live_first"
    store.save(7, "nc_live_second")
    assert store.load(7) == "nc_live_second"
    path = tmp_path / "core-connections" / "7" / "credential"
    if __import__("os").name != "nt":
        assert path.stat().st_mode & 0o077 == 0
    original_replace = __import__("os").replace

    def fail_replace(source, destination):
        if destination == path:
            raise OSError("simulated replace failure")
        return original_replace(source, destination)

    monkeypatch.setattr("app.credential_store.os.replace", fail_replace)
    with pytest.raises(OSError):
        store.save(7, "nc_live_third")
    assert store.load(7) == "nc_live_second"
    assert not list(path.parent.glob(".nexa-*"))
    store.delete(7)
    assert store.load(7) is None
    store.delete(7)


def test_both_files_staged_before_commit_and_existing_pair_survives_failure(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXA_DATA_DIR", str(tmp_path))
    store = FileCredentialStore()
    monkeypatch.setattr(core_connection, "credential_store", store)
    metadata_path = tmp_path / "core-connections" / "1" / "connection.json"
    old = core_connection.CoreConnectionMetadata.model_validate(sample_metadata())
    store.save(1, "nc_live_old")
    metadata_path.write_text(old.model_dump_json(), encoding="utf-8")
    replacement = core_connection.CoreConnectionMetadata.model_validate(sample_metadata())
    original_stage = core_connection.stage_file

    def fail_metadata_stage(path, content):
        assert store.load(1) == "nc_live_old"
        raise OSError("simulated metadata staging failure")

    monkeypatch.setattr(core_connection, "stage_file", fail_metadata_stage)
    with pytest.raises(HTTPException) as error:
        core_connection._persist_connection(1, replacement, "nc_live_new")
    assert error.value.status_code == 500
    assert store.load(1) == "nc_live_old"
    assert core_connection.load_connection(1) == old
    assert not list(metadata_path.parent.glob(".nexa-*"))
    monkeypatch.setattr(core_connection, "stage_file", original_stage)


def test_metadata_commit_failure_restores_previous_credential(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXA_DATA_DIR", str(tmp_path))
    store = FileCredentialStore()
    monkeypatch.setattr(core_connection, "credential_store", store)
    old = core_connection.CoreConnectionMetadata.model_validate(sample_metadata())
    metadata_path = tmp_path / "core-connections" / "1" / "connection.json"
    store.save(1, "nc_live_old")
    metadata_path.write_text(old.model_dump_json(), encoding="utf-8")
    replacement = core_connection.CoreConnectionMetadata.model_validate(sample_metadata())
    original_replace = __import__("os").replace

    def fail_metadata_replace(source, destination):
        if destination == metadata_path:
            raise OSError("simulated metadata replace failure")
        return original_replace(source, destination)

    monkeypatch.setattr("app.credential_store.os.replace", fail_metadata_replace)
    with pytest.raises(HTTPException) as error:
        core_connection._persist_connection(1, replacement, "nc_live_new")
    assert error.value.status_code == 500
    assert store.load(1) == "nc_live_old"
    assert core_connection.load_connection(1) == old
    assert not list(metadata_path.parent.glob(".nexa-*"))


def test_core_offline_keeps_local_dashboard_available(client, monkeypatch, tmp_path):
    monkeypatch.setenv("NEXA_DATA_DIR", str(tmp_path))
    headers = register(client, "offline_owner")
    metadata = core_connection.CoreConnectionMetadata.model_validate(sample_metadata())
    path = tmp_path / "core-connections" / "1" / "connection.json"
    path.parent.mkdir(parents=True)
    path.write_text(metadata.model_dump_json(), encoding="utf-8")
    FileCredentialStore().save(1, "nc_live_" + "a" * 43)

    def offline(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Core offline", request=request)

    monkeypatch.setattr(core_connection, "_http_client", lambda: httpx.Client(
        transport=httpx.MockTransport(offline), timeout=core_connection.TIMEOUT))
    assert client.post("/api/v1/core/connection/test", headers=headers).json() == {
        "connected": False, "status": "unreachable"}
    assert client.get("/api/dashboard", headers=headers).status_code == 200
