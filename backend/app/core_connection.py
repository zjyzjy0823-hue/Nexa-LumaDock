"""Local-only Core enrollment and per-user connection storage."""

import json
import os
import tempfile
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

import httpx
from fastapi import HTTPException


TIMEOUT = httpx.Timeout(10.0, connect=5.0)


def validate_core_url(value: str) -> str:
    try:
        parts = urlsplit(value.strip())
        _ = parts.port
    except ValueError:
        raise HTTPException(422, "Invalid Core URL") from None
    if (parts.scheme not in ("http", "https") or not parts.hostname or
            parts.username is not None or parts.password is not None or
            parts.query or parts.fragment or parts.path not in ("", "/") or
            any(char.isspace() for char in value)):
        raise HTTPException(422, "Invalid Core URL")
    return urlunsplit((parts.scheme, parts.netloc, "", "", ""))


def _http_client() -> httpx.Client:
    return httpx.Client(timeout=TIMEOUT, follow_redirects=False, trust_env=False)


def _json_request(client: httpx.Client, method: str, url: str, **kwargs) -> dict:
    try:
        response = client.request(method, url, **kwargs)
        if response.is_redirect:
            raise HTTPException(502, "Core redirect is not allowed")
        if response.status_code >= 400:
            if url.endswith("/auth/login") and response.status_code in (400, 401, 403):
                raise HTTPException(401, "Core login failed")
            if url.endswith("/clients/enroll") and response.status_code == 409:
                raise HTTPException(409, "Core Client is already enrolled or revoked")
            raise HTTPException(502, "Core request failed")
        result = response.json()
        if not isinstance(result, dict):
            raise ValueError("Invalid Core response")
        return result
    except httpx.RequestError:
        raise HTTPException(502, "Core is unreachable") from None
    except (ValueError, UnicodeError):
        raise HTTPException(502, "Invalid Core response") from None


def _connection_dir(user_id: int) -> Path:
    data_dir = os.environ.get("NEXA_DATA_DIR")
    if not data_dir:
        raise HTTPException(409, "Local data directory is not configured")
    return Path(data_dir) / "core-connections" / str(user_id)


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temp_name = tempfile.mkstemp(prefix=".nexa-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            os.chmod(temp_name, 0o600)
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp_name, path)
    finally:
        Path(temp_name).unlink(missing_ok=True)


def load_connection(user_id: int) -> dict | None:
    path = _connection_dir(user_id) / "connection.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        raise HTTPException(500, "Local Core connection is invalid") from None


def public_connection(metadata: dict | None) -> dict:
    if metadata is None:
        return {"connected": False}
    return {"connected": True, "coreUrl": metadata["coreUrl"], "clientId": metadata["clientId"],
            "workspaceId": metadata["workspaceId"], "installationId": metadata["installationId"],
            "clientName": metadata["clientName"], "platform": metadata["platform"],
            "appVersion": metadata["appVersion"], "connectedAt": metadata["connectedAt"]}


def connect(user_id: int, core_url: str, username: str, password: str,
            client_name: str, platform: str, app_version: str) -> dict:
    origin = validate_core_url(core_url)
    installation_id = os.environ.get("NEXA_INSTALLATION_ID", "")
    try:
        installation_id = str(UUID(installation_id))
    except ValueError:
        raise HTTPException(409, "Local installation ID is not configured") from None
    if load_connection(user_id) is not None:
        raise HTTPException(409, "Core connection already exists")
    with _http_client() as client:
        health = _json_request(client, "GET", origin + "/api/health")
        if health.get("service") != "nexa" or health.get("status") != "ok":
            raise HTTPException(502, "Target is not Nexa Core")
        login = _json_request(client, "POST", origin + "/api/v1/auth/login",
                              json={"username": username, "password": password})
        jwt = login.get("access_token")
        if not isinstance(jwt, str) or not jwt:
            raise HTTPException(502, "Invalid Core login response")
        headers = {"Authorization": "Bearer " + jwt}
        workspace = _json_request(client, "GET", origin + "/api/v1/workspace", headers=headers)
        try:
            workspace_id = str(UUID(workspace["id"]))
        except (KeyError, TypeError, ValueError):
            raise HTTPException(502, "Invalid Core workspace response") from None
        enrolled = _json_request(client, "POST", origin + "/api/v1/clients/enroll", headers=headers,
                                 json={"installationId": installation_id, "name": client_name,
                                       "platform": platform, "appVersion": app_version})
        credential = enrolled.get("credential")
        remote_client = enrolled.get("client")
        if (not isinstance(credential, str) or not credential.startswith("nc_live_") or
                not isinstance(remote_client, dict) or remote_client.get("workspaceId") != workspace_id or
                remote_client.get("installationId") != installation_id):
            raise HTTPException(502, "Invalid Core enrollment response")
        me = _json_request(client, "GET", origin + "/api/v1/client/me",
                           headers={"Authorization": "Bearer " + credential})
        if (me.get("clientId") != remote_client.get("id") or me.get("workspaceId") != workspace_id or
                me.get("installationId") != installation_id or me.get("revoked") is not False):
            raise HTTPException(502, "Core credential verification failed")
    from datetime import datetime, timezone
    metadata = {"coreUrl": origin, "clientId": remote_client["id"], "workspaceId": workspace_id,
                "installationId": installation_id, "clientName": client_name, "platform": platform,
                "appVersion": app_version, "connectedAt": datetime.now(timezone.utc).isoformat()}
    directory = _connection_dir(user_id)
    _atomic_write(directory / "credential", credential.encode("ascii"))
    _atomic_write(directory / "connection.json", json.dumps(metadata, ensure_ascii=False).encode("utf-8"))
    return public_connection(metadata)


def test_connection(user_id: int) -> dict:
    metadata = load_connection(user_id)
    if metadata is None:
        return {"connected": False, "status": "disconnected"}
    try:
        credential = (_connection_dir(user_id) / "credential").read_text(encoding="ascii")
    except (OSError, UnicodeError):
        return {"connected": False, "status": "unauthorized"}
    try:
        with _http_client() as client:
            response = client.get(metadata["coreUrl"] + "/api/v1/client/me",
                                  headers={"Authorization": "Bearer " + credential})
        if response.status_code == 401:
            return {"connected": False, "status": "unauthorized"}
        if response.is_redirect or response.status_code >= 400:
            return {"connected": False, "status": "unreachable"}
        me = response.json()
        if me.get("clientId") != metadata["clientId"] or me.get("workspaceId") != metadata["workspaceId"]:
            return {"connected": False, "status": "unauthorized"}
        return {"connected": True, "status": "connected"}
    except (httpx.RequestError, ValueError, AttributeError, TypeError):
        return {"connected": False, "status": "unreachable"}


def disconnect(user_id: int) -> dict:
    directory = _connection_dir(user_id)
    (directory / "credential").unlink(missing_ok=True)
    (directory / "connection.json").unlink(missing_ok=True)
    return {"connected": False}
