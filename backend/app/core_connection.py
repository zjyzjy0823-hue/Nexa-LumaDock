"""Local-only Core enrollment, recovery, and connection metadata."""

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Literal
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

import httpx
from fastapi import HTTPException
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError, field_validator

from .credential_store import CredentialStore, FileCredentialStore, connection_directory, stage_file


TIMEOUT = httpx.Timeout(10.0, connect=5.0)
logger = logging.getLogger(__name__)
credential_store: CredentialStore = FileCredentialStore()


def _normalize_core_url(value: str) -> str:
    try:
        parts = urlsplit(value.strip())
        _ = parts.port
    except ValueError:
        raise ValueError("Invalid Core URL") from None
    if (parts.scheme not in ("http", "https") or not parts.hostname or
            parts.username is not None or parts.password is not None or
            parts.query or parts.fragment or parts.path not in ("", "/") or
            any(char.isspace() for char in value)):
        raise ValueError("Invalid Core URL")
    return urlunsplit((parts.scheme, parts.netloc, "", "", ""))


def validate_core_url(value: str) -> str:
    try:
        return _normalize_core_url(value)
    except ValueError:
        raise HTTPException(422, "Invalid Core URL") from None


class CoreConnectionMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schemaVersion: Literal[1]
    coreUrl: str
    clientId: str
    workspaceId: str
    installationId: str
    clientName: str = Field(min_length=1, max_length=120)
    platform: Literal["windows", "macos", "linux", "android", "ios", "web"]
    appVersion: str = Field(min_length=1, max_length=40)
    connectedAt: AwareDatetime

    @field_validator("schemaVersion", mode="before")
    @classmethod
    def exact_version(cls, value):
        if type(value) is not int or value != 1:
            raise ValueError("Unsupported connection schema version")
        return value

    @field_validator("coreUrl")
    @classmethod
    def valid_origin(cls, value: str) -> str:
        return _normalize_core_url(value)

    @field_validator("clientId", "workspaceId", "installationId")
    @classmethod
    def valid_id(cls, value: str) -> str:
        return str(UUID(value))

    @field_validator("clientName", "appVersion")
    @classmethod
    def nonempty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Value cannot be empty")
        return value

    @field_validator("connectedAt", mode="before")
    @classmethod
    def timestamp_string(cls, value):
        if not isinstance(value, str):
            raise ValueError("connectedAt must be an ISO timestamp")
        return value


class CoreRequestError(Exception):
    """Private HTTP failure details; its public message never contains response data."""

    def __init__(self, status_code: int, endpoint: str, detail: str | None):
        self.status_code = status_code
        self.endpoint = endpoint
        self.detail = detail
        super().__init__("Core request failed")


def _http_client() -> httpx.Client:
    return httpx.Client(timeout=TIMEOUT, follow_redirects=False, trust_env=False)


def _json_request(client: httpx.Client, method: str, origin: str, endpoint: str,
                  *, expect_list: bool = False, **kwargs) -> dict | list:
    try:
        response = client.request(method, origin + endpoint, **kwargs)
        if response.is_redirect:
            raise HTTPException(502, "Core redirect is not allowed")
        if response.status_code >= 400:
            try:
                body = response.json()
                detail = body.get("detail") if isinstance(body, dict) else None
                if not isinstance(detail, str):
                    detail = None
            except ValueError:
                detail = None
            raise CoreRequestError(response.status_code, endpoint, detail)
        result = response.json()
        if not isinstance(result, list if expect_list else dict):
            raise ValueError("Invalid Core response")
        return result
    except httpx.RequestError:
        raise HTTPException(502, "Core is unreachable") from None
    except (ValueError, UnicodeError):
        raise HTTPException(502, "Invalid Core response") from None


def _request_or_error(client: httpx.Client, method: str, origin: str, endpoint: str, **kwargs) -> dict | list:
    try:
        return _json_request(client, method, origin, endpoint, **kwargs)
    except CoreRequestError as error:
        if endpoint == "/api/v1/auth/login" and error.status_code in (400, 401, 403):
            raise HTTPException(401, "Core login failed") from None
        raise HTTPException(502, "Core request failed") from None


def _enroll_or_recover(client: httpx.Client, origin: str, headers: dict,
                       installation_id: str, client_name: str, platform: str,
                       app_version: str) -> dict:
    endpoint = "/api/v1/clients/enroll"
    try:
        return _json_request(client, "POST", origin, endpoint, headers=headers,
                             json={"installationId": installation_id, "name": client_name,
                                   "platform": platform, "appVersion": app_version})
    except CoreRequestError as error:
        if error.status_code != 409 or error.endpoint != endpoint:
            raise HTTPException(502, "Core enrollment failed") from None

    # Core scopes this list to the logged-in user's Personal Workspace.
    clients = _request_or_error(client, "GET", origin, "/api/v1/clients",
                                headers=headers, expect_list=True)
    matches = [item for item in clients if isinstance(item, dict) and
               item.get("installationId") == installation_id]
    if len(matches) != 1:
        raise HTTPException(409, "Core enrollment state is inconsistent")
    match = matches[0]
    if match.get("revokedAt") is not None:
        raise HTTPException(409, "Core Client is revoked")
    try:
        client_id = str(UUID(match["id"]))
    except (KeyError, TypeError, ValueError):
        raise HTTPException(502, "Invalid Core Client response") from None
    return _request_or_error(client, "POST", origin, f"/api/v1/clients/{client_id}/credential",
                             headers=headers)


def load_connection(user_id: int) -> CoreConnectionMetadata | None:
    path = connection_directory(user_id) / "connection.json"
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        # Phase 3 metadata predates schemaVersion. Accept only the exact legacy shape.
        legacy_fields = set(CoreConnectionMetadata.model_fields) - {"schemaVersion"}
        legacy = isinstance(raw, dict) and set(raw) == legacy_fields
        if legacy:
            raw = {**raw, "schemaVersion": 1}
        metadata = CoreConnectionMetadata.model_validate(raw)
        if legacy:
            staged = stage_file(path, metadata.model_dump_json().encode("utf-8"))
            try:
                staged.commit()
            finally:
                staged.discard()
        return metadata
    except (OSError, ValueError, UnicodeError, ValidationError):
        raise HTTPException(500, "Local Core connection is invalid") from None


def public_connection(metadata: CoreConnectionMetadata | None) -> dict:
    if metadata is None:
        return {"connected": False}
    return {"connected": True, **metadata.model_dump(mode="json", exclude={"schemaVersion"})}


def _persist_connection(user_id: int, metadata: CoreConnectionMetadata, credential: str) -> None:
    """Stage and fsync both files before replacing the credential, then metadata."""
    metadata_path = connection_directory(user_id) / "connection.json"
    staged_credential = None
    staged_metadata = None
    try:
        previous_credential = credential_store.load(user_id) if metadata_path.exists() else None
    except OSError:
        raise HTTPException(500, "Local Core connection could not be saved") from None
    credential_committed = False
    try:
        staged_credential = credential_store.stage(user_id, credential)
        staged_metadata = stage_file(metadata_path, metadata.model_dump_json().encode("utf-8"))
        staged_credential.commit()
        credential_committed = True
        staged_metadata.commit()
    except OSError:
        # A newly enrolled remote Client can be recovered by explicit rotation.
        # Never leave an orphan local credential without matching metadata.
        if credential_committed:
            try:
                if previous_credential is None:
                    credential_store.delete(user_id)
                else:
                    credential_store.save(user_id, previous_credential)
            except OSError:
                logger.warning("Local Core credential rollback failed for user %s", user_id)
        raise HTTPException(500, "Local Core connection could not be saved") from None
    finally:
        if staged_credential is not None:
            staged_credential.discard()
        if staged_metadata is not None:
            staged_metadata.discard()


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
        health = _request_or_error(client, "GET", origin, "/api/health")
        if health.get("service") != "nexa" or health.get("status") != "ok":
            raise HTTPException(502, "Target is not Nexa Core")
        login = _request_or_error(client, "POST", origin, "/api/v1/auth/login",
                                  json={"username": username, "password": password})
        jwt = login.get("access_token")
        if not isinstance(jwt, str) or not jwt:
            raise HTTPException(502, "Invalid Core login response")
        headers = {"Authorization": "Bearer " + jwt}
        workspace = _request_or_error(client, "GET", origin, "/api/v1/workspace", headers=headers)
        try:
            workspace_id = str(UUID(workspace["id"]))
        except (KeyError, TypeError, ValueError):
            raise HTTPException(502, "Invalid Core workspace response") from None
        enrolled = _enroll_or_recover(client, origin, headers, installation_id,
                                      client_name, platform, app_version)
        credential = enrolled.get("credential")
        remote_client = enrolled.get("client")
        if (not isinstance(credential, str) or re.fullmatch(r"nc_live_[A-Za-z0-9_-]{40,}", credential) is None or
                not isinstance(remote_client, dict) or remote_client.get("workspaceId") != workspace_id or
                remote_client.get("installationId") != installation_id):
            raise HTTPException(502, "Invalid Core enrollment response")
        me = _request_or_error(client, "GET", origin, "/api/v1/client/me",
                               headers={"Authorization": "Bearer " + credential})
        if (me.get("clientId") != remote_client.get("id") or me.get("workspaceId") != workspace_id or
                me.get("installationId") != installation_id or me.get("revoked") is not False):
            raise HTTPException(502, "Core credential verification failed")
    try:
        metadata = CoreConnectionMetadata.model_validate({
            "schemaVersion": 1, "coreUrl": origin, "clientId": remote_client["id"],
            "workspaceId": workspace_id, "installationId": installation_id,
            "clientName": client_name, "platform": platform, "appVersion": app_version,
            "connectedAt": datetime.now(timezone.utc).isoformat(),
        })
    except (KeyError, TypeError, ValueError, ValidationError):
        raise HTTPException(502, "Invalid Core enrollment response") from None
    _persist_connection(user_id, metadata, credential)
    return public_connection(metadata)


def test_connection(user_id: int) -> dict:
    metadata = load_connection(user_id)
    if metadata is None:
        return {"connected": False, "status": "disconnected"}
    try:
        credential = credential_store.load(user_id)
    except OSError:
        return {"connected": False, "status": "unauthorized"}
    if not credential or not credential.startswith("nc_live_"):
        return {"connected": False, "status": "unauthorized"}
    try:
        with _http_client() as client:
            response = client.get(metadata.coreUrl + "/api/v1/client/me",
                                  headers={"Authorization": "Bearer " + credential})
        if response.status_code == 401:
            return {"connected": False, "status": "unauthorized"}
        if response.is_redirect or response.status_code >= 400:
            return {"connected": False, "status": "unreachable"}
        me = response.json()
        if (not isinstance(me, dict) or me.get("clientId") != metadata.clientId or
                me.get("workspaceId") != metadata.workspaceId or
                me.get("installationId") != metadata.installationId or me.get("revoked") is not False):
            return {"connected": False, "status": "unauthorized"}
        return {"connected": True, "status": "connected"}
    except (httpx.RequestError, ValueError, AttributeError, TypeError):
        return {"connected": False, "status": "unreachable"}


def disconnect(user_id: int) -> dict:
    try:
        credential_store.delete(user_id)
        (connection_directory(user_id) / "connection.json").unlink(missing_ok=True)
    except OSError:
        raise HTTPException(500, "Local Core connection could not be removed") from None
    return {"connected": False}
