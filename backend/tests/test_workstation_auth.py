from dataclasses import replace

from fastapi import HTTPException

from app.api import auth as auth_api
from app.config import load_runtime_config


def test_non_workstation_disables_workstation_endpoints(client):
    status = client.get("/api/v1/auth/status")
    assert status.status_code == 200
    assert status.json()["workstation"] is False
    assert status.json()["setupRequired"] is False
    assert client.post("/api/v1/auth/workstation/setup", json={"mode": "offline"}).status_code == 404
    assert client.post("/api/v1/auth/workstation/session").status_code == 404


def test_core_mode_never_enables_local_workstation():
    config = load_runtime_config({
        "STUDIOLO_MODE": "core",
        "STUDIOLO_LOCAL_WORKSTATION": "true",
        "DATABASE_URL": "postgresql+psycopg://studiolo:password@postgres:5432/studiolo",
        "JWT_SECRET": "test-secret-for-studiolo-core",
    })
    assert config.local_workstation is False


def test_workstation_offline_setup_and_auto_session(client, monkeypatch):
    monkeypatch.setattr(auth_api, "runtime_config", replace(auth_api.runtime_config, local_workstation=True))

    initial = client.get("/api/v1/auth/status")
    assert initial.status_code == 200
    assert initial.json()["workstation"] is True
    assert initial.json()["setupRequired"] is True
    assert client.post("/api/v1/auth/workstation/session").status_code == 404

    setup = client.post("/api/v1/auth/workstation/setup", json={"mode": "offline"})
    assert setup.status_code == 201
    token = setup.json()["access_token"]
    assert token

    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["username"] == "local"

    after = client.get("/api/v1/auth/status")
    assert after.json()["setupRequired"] is False
    assert client.post("/api/v1/auth/workstation/setup", json={"mode": "offline"}).status_code == 409

    resumed = client.post("/api/v1/auth/workstation/session")
    assert resumed.status_code == 200
    resumed_me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {resumed.json()['access_token']}"})
    assert resumed_me.status_code == 200
    assert resumed_me.json()["id"] == me.json()["id"]


def test_workstation_core_setup_rolls_back_on_failure_and_succeeds(client, monkeypatch):
    monkeypatch.setattr(auth_api, "runtime_config", replace(auth_api.runtime_config, local_workstation=True))

    def fail_connect(*_args, **_kwargs):
        raise HTTPException(401, "Core login failed")

    monkeypatch.setattr(auth_api.core_connection, "disconnect", lambda _uid: {"connected": False})
    monkeypatch.setattr(auth_api.core_connection, "connect", fail_connect)

    core_payload = {
        "mode": "core",
        "coreUrl": "https://core.example.com",
        "username": "alice",
        "password": "wrong-password",
        "clientName": "Studiolo Windows",
        "platform": "windows",
        "appVersion": "0.7.0",
    }
    failed = client.post("/api/v1/auth/workstation/setup", json=core_payload)
    assert failed.status_code == 401
    assert client.get("/api/v1/auth/status").json()["setupRequired"] is True

    connected_calls = []

    class FakeCoordinator:
        def connection_changed(self, user_id, workspace_id, connected):
            connected_calls.append((user_id, workspace_id, connected))

    monkeypatch.setattr(
        auth_api.core_connection,
        "connect",
        lambda uid, *_args: {"connected": True, "coreUrl": "https://core.example.com", "clientId": "c1", "workspaceId": "w1"},
    )
    monkeypatch.setattr(auth_api, "get_coordinator", lambda _bind: FakeCoordinator())

    ok = client.post("/api/v1/auth/workstation/setup", json={**core_payload, "password": "right-password"})
    assert ok.status_code == 201
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {ok.json()['access_token']}"})
    assert me.status_code == 200
    assert me.json()["username"] == "alice"
    assert len(connected_calls) == 1 and connected_calls[0][2] is True


def test_workstation_session_rejects_multi_user_db(client, monkeypatch):
    assert client.post("/api/v1/auth/register", json={"username": "user_one", "password": "password123"}).status_code == 201
    assert client.post("/api/v1/auth/register", json={"username": "user_two", "password": "password123"}).status_code == 201
    monkeypatch.setattr(auth_api, "runtime_config", replace(auth_api.runtime_config, local_workstation=True))
    resumed = client.post("/api/v1/auth/workstation/session")
    assert resumed.status_code == 409
