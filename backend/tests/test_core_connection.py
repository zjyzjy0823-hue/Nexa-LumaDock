"""Local Core enrollment uses HTTP and never persists the user's login secrets."""

import json
from uuid import uuid4

import httpx

from app import core_connection


def test_connect_status_disconnect_and_secret_storage(client, monkeypatch, tmp_path):
    installation_id = str(uuid4())
    monkeypatch.setenv("NEXA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NEXA_INSTALLATION_ID", installation_id)
    calls = []
    revoked = False

    def core(request: httpx.Request) -> httpx.Response:
        nonlocal revoked
        calls.append((request.method, request.url.path))
        path = request.url.path
        if path == "/api/health":
            return httpx.Response(200, json={"status": "ok", "service": "nexa", "version": "0.5.3"})
        if path == "/api/v1/auth/login":
            assert json.loads(request.content) == {"username": "remote_user", "password": "remote-password"}
            return httpx.Response(200, json={"access_token": "temporary-core-jwt"})
        if path == "/api/v1/workspace":
            assert request.headers["authorization"] == "Bearer temporary-core-jwt"
            return httpx.Response(200, json={"id": workspace_id, "kind": "personal"})
        if path == "/api/v1/clients/enroll":
            assert request.headers["authorization"] == "Bearer temporary-core-jwt"
            assert json.loads(request.content)["installationId"] == installation_id
            return httpx.Response(201, json={"client": {"id": remote_client_id,
                "workspaceId": workspace_id, "installationId": installation_id}, "credential": credential})
        if path == "/api/v1/client/me":
            assert request.headers["authorization"] == "Bearer " + credential
            if revoked:
                return httpx.Response(401, json={"detail": "Invalid client credential"})
            return httpx.Response(200, json={"clientId": remote_client_id,
                                             "workspaceId": workspace_id, "installationId": installation_id,
                                             "revoked": False})
        raise AssertionError(path)

    workspace_id = str(uuid4())
    remote_client_id = str(uuid4())
    credential = "nc_live_" + "a" * 43
    monkeypatch.setattr(core_connection, "_http_client", lambda: httpx.Client(
        transport=httpx.MockTransport(core), timeout=core_connection.TIMEOUT, follow_redirects=False))
    registration = client.post("/api/v1/auth/register", json={"username": "local_owner", "password": "password123"})
    assert registration.status_code == 201
    headers = {"Authorization": "Bearer " + registration.json()["access_token"]}
    payload = {"coreUrl": "http://192.168.1.10:8000/", "username": "remote_user",
               "password": "remote-password", "clientName": "Windows PC",
               "platform": "windows", "appVersion": "0.5.2"}
    connected = client.post("/api/v1/core/connect", headers=headers, json=payload)
    assert connected.status_code == 200, connected.text
    assert connected.json()["coreUrl"] == "http://192.168.1.10:8000"
    assert connected.json()["clientId"] == remote_client_id
    assert connected.json()["installationId"] == installation_id
    assert "credential" not in connected.text
    assert calls == [("GET", "/api/health"), ("POST", "/api/v1/auth/login"),
                     ("GET", "/api/v1/workspace"), ("POST", "/api/v1/clients/enroll"),
                     ("GET", "/api/v1/client/me")]
    connection = client.get("/api/v1/core/connection", headers=headers)
    assert connection.status_code == 200
    assert connection.json()["connected"] is True
    another = client.post("/api/v1/auth/register", json={"username": "another_local_owner", "password": "password123"})
    another_headers = {"Authorization": "Bearer " + another.json()["access_token"]}
    assert client.get("/api/v1/core/connection", headers=another_headers).json() == {"connected": False}
    assert client.post("/api/v1/core/connection/test", headers=another_headers).json()["status"] == "disconnected"
    directory = tmp_path / "core-connections" / "1"
    metadata = (directory / "connection.json").read_text(encoding="utf-8")
    assert (directory / "credential").read_text(encoding="ascii") == credential
    assert credential not in metadata
    for secret in ("remote-password", "temporary-core-jwt"):
        assert secret not in metadata
        assert secret not in (directory / "credential").read_text(encoding="ascii")
    assert client.post("/api/v1/core/connection/test", headers=headers).json() == {
        "connected": True, "status": "connected"}
    revoked = True
    assert client.post("/api/v1/core/connection/test", headers=headers).json() == {
        "connected": False, "status": "unauthorized"}
    assert client.delete("/api/v1/core/connection", headers=headers).json() == {"connected": False}
    assert not (directory / "credential").exists()
    assert not (directory / "connection.json").exists()
    assert client.get("/api/v1/core/connection", headers=headers).json() == {"connected": False}
    assert client.post("/api/v1/core/connection/test", headers=headers).json() == {
        "connected": False, "status": "disconnected"}


def test_core_url_rejects_unsafe_forms():
    from fastapi import HTTPException
    for url in ("file:///etc/passwd", "ftp://host", "javascript:alert(1)",
                "https://user:pass@host", "https://host/?x=1", "https://host/#f",
                "https://host/path", "https://host:bad"):
        try:
            core_connection.validate_core_url(url)
        except HTTPException as exc:
            assert exc.status_code == 422
        else:
            raise AssertionError(url)


def test_failed_core_connection_does_not_save_secrets(client, monkeypatch, tmp_path):
    monkeypatch.setenv("NEXA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NEXA_INSTALLATION_ID", str(uuid4()))

    def redirect(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "https://other.example/"})

    monkeypatch.setattr(core_connection, "_http_client", lambda: httpx.Client(
        transport=httpx.MockTransport(redirect), follow_redirects=False, timeout=core_connection.TIMEOUT))
    registration = client.post("/api/v1/auth/register", json={"username": "failed_connect", "password": "password123"})
    headers = {"Authorization": "Bearer " + registration.json()["access_token"]}
    payload = {"coreUrl": "https://core.example", "username": "remote", "password": "private-password",
               "clientName": "PC", "platform": "windows", "appVersion": "0.5.2"}
    response = client.post("/api/v1/core/connect", headers=headers, json=payload)
    assert response.status_code == 502
    assert "private-password" not in response.text
    assert not (tmp_path / "core-connections").exists()
