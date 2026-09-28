"""Core client credential lifecycle, separate from user and runtime tokens."""

import hashlib
from uuid import uuid4

from sqlalchemy import select

from app.database import get_db
from app.main import app
from app.models import Client
from app.runtime_mode import require_core_mode


def register(client, name):
    response = client.post("/api/v1/auth/register", json={"username": name, "password": "password123"})
    assert response.status_code == 201, response.text
    return {"Authorization": "Bearer " + response.json()["access_token"]}


def test_core_only_boundary(client):
    user = register(client, "local_boundary")
    payload = {"installationId": str(uuid4()), "name": "PC", "platform": "windows", "appVersion": "0.5.2"}
    assert client.post("/api/v1/clients/enroll", headers=user, json=payload).status_code == 404
    assert client.get("/api/v1/client/me", headers={"Authorization": "Bearer nc_live_fake"}).status_code == 404


def test_enrollment_rotation_revoke_and_isolation(client):
    app.dependency_overrides[require_core_mode] = lambda: None
    first = register(client, "client_auth_first")
    second = register(client, "client_auth_second")
    payload = {"installationId": str(uuid4()), "name": "Windows PC", "platform": "windows", "appVersion": "0.5.2"}
    enrolled = client.post("/api/v1/clients/enroll", headers=first, json=payload)
    assert enrolled.status_code == 201, enrolled.text
    assert enrolled.headers["cache-control"] == "no-store"
    item = enrolled.json()["client"]
    credential_a = enrolled.json()["credential"]
    assert credential_a.startswith("nc_live_")
    assert len(credential_a) > 40
    assert enrolled.json()["tokenLast4"] == credential_a[-4:]
    assert enrolled.json()["tokenCreatedAt"]
    assert item["workspaceId"] == client.get("/api/v1/workspace", headers=first).json()["id"]
    assert client.post("/api/v1/clients/enroll", headers=first, json=payload).status_code == 409
    assert credential_a not in client.get("/api/v1/clients", headers=first).text
    assert credential_a not in client.get(f"/api/v1/clients/{item['id']}", headers=first).text

    db_iterator = app.dependency_overrides[get_db]()
    db = next(db_iterator)
    try:
        stored = db.scalar(select(Client).where(Client.id == item["id"]))
        assert stored.token_hash == hashlib.sha256(credential_a.encode()).hexdigest()
        assert credential_a not in repr(stored)
    finally:
        db_iterator.close()

    auth_a = {"Authorization": "Bearer " + credential_a}
    me = client.get("/api/v1/client/me", headers=auth_a)
    assert me.status_code == 200, me.text
    assert me.json()["clientId"] == item["id"]
    assert me.json()["workspaceId"] == item["workspaceId"]
    assert me.json()["revoked"] is False
    assert client.get("/api/v1/client/me").status_code == 401
    for wrong in ("nc_live_wrong", "nd_live_wrong", "na_live_wrong", "sk_live_wrong"):
        invalid = client.get("/api/v1/client/me", headers={"Authorization": "Bearer " + wrong})
        assert invalid.status_code == 401
        assert invalid.json()["detail"] == "Invalid client credential"

    heartbeat = client.post("/api/v1/client/heartbeat", headers=auth_a, json={"appVersion": "0.5.3"})
    assert heartbeat.status_code == 200, heartbeat.text
    assert heartbeat.json()["appVersion"] == "0.5.3"
    assert client.post("/api/v1/client/heartbeat", headers=auth_a, json={"cpu": 1}).status_code == 422

    assert client.post(f"/api/v1/clients/{item['id']}/credential", headers=second).status_code == 404
    assert client.post(f"/api/v1/clients/{item['id']}/revoke", headers=second).status_code == 404
    rotated = client.post(f"/api/v1/clients/{item['id']}/credential", headers=first)
    assert rotated.status_code == 200, rotated.text
    assert rotated.headers["cache-control"] == "no-store"
    credential_b = rotated.json()["credential"]
    assert credential_b != credential_a
    assert client.get("/api/v1/client/me", headers=auth_a).status_code == 401
    auth_b = {"Authorization": "Bearer " + credential_b}
    assert client.get("/api/v1/client/me", headers=auth_b).status_code == 200
    assert client.post(f"/api/v1/clients/{item['id']}/revoke", headers=first).status_code == 200
    assert client.post(f"/api/v1/clients/{item['id']}/revoke", headers=first).status_code == 200
    assert client.get("/api/v1/client/me", headers=auth_b).status_code == 401
    assert client.post("/api/v1/clients/enroll", headers=first, json=payload).status_code == 409
    assert client.post(f"/api/v1/clients/{item['id']}/credential", headers=first).status_code == 409
    db_iterator = app.dependency_overrides[get_db]()
    db = next(db_iterator)
    try:
        stored = db.get(Client, item["id"])
        assert stored.token_hash is None
        assert stored.token_last4 == credential_b[-4:]
    finally:
        db_iterator.close()


def test_enroll_existing_identity_without_credential(client):
    app.dependency_overrides[require_core_mode] = lambda: None
    user = register(client, "client_auth_existing")
    payload = {"installationId": str(uuid4()), "name": "Mac", "platform": "macos", "appVersion": "0.5.2"}
    existing = client.post("/api/v1/clients", headers=user, json=payload)
    assert existing.status_code == 201
    enrolled = client.post("/api/v1/clients/enroll", headers=user, json=payload)
    assert enrolled.status_code == 201
    assert enrolled.json()["client"]["id"] == existing.json()["id"]


def test_core_rejects_local_connection_endpoints(client, monkeypatch):
    from dataclasses import replace
    from app import runtime_mode

    monkeypatch.setattr(runtime_mode, "runtime_config", replace(runtime_mode.runtime_config, mode="core"))
    user = register(client, "core_cannot_connect")
    assert client.get("/api/v1/core/connection", headers=user).status_code == 404
