"""Core device credential reads and Shared Space access boundaries."""

import base64
from contextlib import contextmanager
from dataclasses import replace
from hashlib import sha256
from uuid import uuid4

import pytest
from sqlalchemy import select

from app import runtime_mode
from app.api import client_space_reads
from app.database import get_db
from app.main import app
from app.models import SharedSpace, SpaceAccessAuditLog, SpaceDeviceGrant, User, utcnow


READS = "/api/v1/client/space-reads"
SPACES = "/api/v1/spaces"


@pytest.fixture(autouse=True)
def _core_space_env(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime_mode, "runtime_config", replace(runtime_mode.runtime_config, mode="core"))
    monkeypatch.setenv("STUDIOLO_SHARED_SPACE_ENABLED", "1")
    monkeypatch.setenv("STUDIOLO_SPACE_DEVICE_READS", "1")
    monkeypatch.delenv("STUDIOLO_SPACE_DEVICE_DEFAULT_GRANT", raising=False)
    monkeypatch.setenv("STUDIOLO_SPACE_BLOB_DIR", str(tmp_path / "space-blobs"))


@pytest.fixture
def db(client):
    with contextmanager(app.dependency_overrides[get_db])() as session:
        yield session


def _enroll(client, owner):
    response = client.post("/api/v1/clients/enroll", headers=owner, json={
        "installationId": str(uuid4()), "name": "Laptop", "platform": "macos", "appVersion": "0.8.0",
    })
    assert response.status_code == 201, response.text
    body = response.json()
    return body["client"], {"Authorization": f"Bearer {body['credential']}"}


@pytest.fixture
def device(client, users):
    return _enroll(client, users[0])


def _create_space(client, owner):
    response = client.post(SPACES, headers=owner, json={"name": "Device notes", "tier": "standard"})
    assert response.status_code == 201, response.text
    return response.json()


def _create_entry(client, owner, space_id, **data):
    response = client.post(f"{SPACES}/{space_id}/entries", headers=owner, json=data)
    assert response.status_code == 201, response.text
    return response.json()


def _grant(db, item, space_id, *, can_read=True, revoked_at=None):
    db.add(SpaceDeviceGrant(
        id=str(uuid4()), workspace_id=item["workspaceId"], space_id=space_id, client_id=item["id"],
        can_read=can_read, can_write=True, revoked_at=revoked_at,
    ))
    db.commit()


def _space_read_paths(space_id):
    space = f"{READS}/spaces/{space_id}"
    entry = f"{space}/entries/{uuid4()}"
    return [space, f"{space}/entries", entry, f"{entry}/download", f"{space}/blobs/{uuid4()}/chunks/0"]


def test_no_grant_with_default_disabled(client, users, device, db, monkeypatch):
    monkeypatch.setenv("STUDIOLO_SPACE_DEVICE_DEFAULT_GRANT", "0")
    item, headers = device
    _create_space(client, users[0])

    status = client.get(f"{READS}/status", headers=headers)
    assert status.status_code == 200
    assert status.json() == {"status": "no_grant", "workspaceId": item["workspaceId"], "spaceCount": 0}
    spaces = client.get(f"{READS}/spaces", headers=headers)
    assert spaces.status_code == 200
    assert spaces.json() == []
    assert db.scalars(select(SpaceAccessAuditLog).where(SpaceAccessAuditLog.action == "device.read")).all() == []


def test_default_grant_reads_standard_space_and_audits(client, users, device, db):
    owner, _ = users
    item, headers = device
    space_id = _create_space(client, owner)["id"]
    note = _create_entry(client, owner, space_id, title="Deploy notes", contentText="Standard plaintext")
    _create_entry(client, owner, space_id, title="Checklist", tags=["deploy"], contentText="Checklist")
    data = b"\x00\x01file content"
    file = _create_entry(
        client, owner, space_id, title="Deploy artifact", entryType="file", fileName="产物.bin",
        mime="application/octet-stream", contentBase64=base64.b64encode(data).decode("ascii"),
    )

    status = client.get(f"{READS}/status", headers=headers)
    assert status.status_code == 200
    assert status.json() == {"status": "ready", "workspaceId": item["workspaceId"], "spaceCount": 1}
    spaces = client.get(f"{READS}/spaces", headers=headers)
    assert spaces.status_code == 200
    current_space = client.get(f"{SPACES}/{space_id}", headers=owner).json()
    assert spaces.json() == [current_space]

    path = f"{READS}/spaces/{space_id}"
    detail = client.get(path, headers=headers)
    assert detail.status_code == 200
    assert detail.json() == current_space

    filters = {"search": "DEPLOY", "entryType": "text"}
    legacy_entries = client.get(f"{SPACES}/{space_id}/entries", headers=owner, params=filters).json()
    assert len(legacy_entries) == 2
    entries = client.get(f"{path}/entries", headers=headers, params={**filters, "limit": 1, "offset": 1})
    assert entries.status_code == 200
    assert entries.json() == legacy_entries[1:2]

    entry = client.get(f"{path}/entries/{note['id']}", headers=headers)
    assert entry.status_code == 200
    assert entry.json() == note
    assert entry.json()["contentText"] == "Standard plaintext"
    assert entry.json()["locked"] is False

    suffix = f"/entries/{file['id']}/download"
    download = client.get(path + suffix, headers=headers)
    legacy_download = client.get(f"{SPACES}/{space_id}" + suffix, headers=owner)
    assert download.status_code == 200
    assert download.content == data
    for header in ("content-type", "content-disposition", "cache-control"):
        assert download.headers[header] == legacy_download.headers[header]

    chunk = client.get(f"{path}/blobs/{file['blobId']}/chunks/0", headers=headers)
    assert chunk.status_code == 200
    assert chunk.content == data
    assert chunk.headers["content-type"] == "application/octet-stream"
    assert chunk.headers["x-chunk-sha256"] == sha256(data).hexdigest()
    assert chunk.headers["cache-control"] == "no-store"

    audit = db.scalars(select(SpaceAccessAuditLog).where(SpaceAccessAuditLog.action == "device.read")).all()
    assert len(audit) == 5
    assert {(row.space_id, row.workspace_id, row.actor_kind, row.actor_id, row.outcome, row.detail) for row in audit} == {
        (space_id, item["workspaceId"], "device", f"client:{item['id']}", "allowed", ""),
    }


@pytest.mark.parametrize("tier", ["protected", "e2ee"])
def test_nonstandard_space_hidden_even_with_explicit_grant(client, device, db, tier):
    item, headers = device
    space_id = str(uuid4())
    db.add(SharedSpace(
        id=space_id, user_id=db.scalar(select(User.id).where(User.username == "owner_a")),
        workspace_id=item["workspaceId"], name="Hidden space", tier=tier,
    ))
    db.commit()
    _grant(db, item, space_id)

    assert client.get(f"{READS}/status", headers=headers).json()["status"] == "no_grant"
    assert client.get(f"{READS}/spaces", headers=headers).json() == []
    for path in _space_read_paths(space_id):
        response = client.get(path, headers=headers)
        assert response.status_code == 404, path
        assert response.json()["detail"] == "Space not found"
    assert client.get(f"{READS}/spaces/{space_id}/entries?limit=0", headers=headers).status_code == 404


def test_cross_workspace_space_hidden_even_with_mismatched_grant(client, users, device, db):
    item, headers = device
    other_space = _create_space(client, users[1])
    _grant(db, item, other_space["id"])

    assert client.get(f"{READS}/spaces", headers=headers).json() == []
    for path in _space_read_paths(other_space["id"]):
        assert client.get(path, headers=headers).status_code == 404, path
    assert db.scalars(select(SpaceAccessAuditLog).where(SpaceAccessAuditLog.action == "device.read")).all() == []


def test_revoked_and_write_only_grants_do_not_allow_reads(client, users, device, db, monkeypatch):
    monkeypatch.setenv("STUDIOLO_SPACE_DEVICE_DEFAULT_GRANT", "0")
    item, headers = device
    revoked = _create_space(client, users[0])["id"]
    write_only = _create_space(client, users[0])["id"]
    _grant(db, item, revoked, revoked_at=utcnow())
    _grant(db, item, write_only, can_read=False)

    for space_id in (revoked, write_only):
        assert client.get(f"{READS}/spaces/{space_id}", headers=headers).status_code == 404
    assert client.get(f"{READS}/spaces", headers=headers).json() == []
    audit = db.scalars(select(SpaceAccessAuditLog).where(SpaceAccessAuditLog.action == "device.read")).all()
    assert {(row.space_id, row.outcome) for row in audit} == {(revoked, "denied"), (write_only, "denied")}


def test_active_explicit_grant_is_device_scoped_and_excludes_archived_spaces(client, users, device, db, monkeypatch):
    owner, _ = users
    item, headers = device
    _, other_headers = _enroll(client, owner)
    space_id = str(uuid4())
    db.add(SharedSpace(
        id=space_id, user_id=db.scalar(select(User.id).where(User.username == "owner_b")),
        workspace_id=item["workspaceId"], name="Space created by another member", tier="standard",
    ))
    db.commit()
    assert client.get(f"{READS}/spaces/{space_id}", headers=headers).status_code == 404

    monkeypatch.setenv("STUDIOLO_SPACE_DEVICE_DEFAULT_GRANT", "0")
    _grant(db, item, space_id)

    assert client.get(f"{READS}/status", headers=headers).json()["spaceCount"] == 1
    assert [space["id"] for space in client.get(f"{READS}/spaces", headers=headers).json()] == [space_id]
    assert client.get(f"{READS}/spaces/{space_id}", headers=headers).status_code == 200
    assert client.get(f"{READS}/spaces/{space_id}", headers=other_headers).status_code == 404

    assert client.delete(f"{SPACES}/{space_id}", headers=owner).status_code == 204
    monkeypatch.delenv("STUDIOLO_SPACE_DEVICE_DEFAULT_GRANT")
    assert client.get(f"{READS}/status", headers=headers).json()["spaceCount"] == 0
    assert client.get(f"{READS}/spaces", headers=headers).json() == []
    assert client.get(f"{READS}/spaces/{space_id}", headers=headers).status_code == 404


def test_device_credential_still_forbidden_on_direct_shared_space_api(client, device):
    _, headers = device
    assert client.get(SPACES, headers=headers).status_code == 403


def test_device_read_routes_have_no_write_methods(client, device):
    _, headers = device
    for path in [f"{READS}/status", f"{READS}/spaces", *_space_read_paths(uuid4())]:
        for method in ("POST", "PUT", "DELETE"):
            assert client.request(method, path, headers=headers).status_code in (404, 405), (method, path)


@pytest.mark.parametrize("flag", [None, "0"])
def test_feature_disabled_returns_404_for_all_reads(client, device, monkeypatch, flag):
    if flag is None:
        monkeypatch.delenv("STUDIOLO_SPACE_DEVICE_READS")
    else:
        monkeypatch.setenv("STUDIOLO_SPACE_DEVICE_READS", flag)
    _, headers = device
    for path in [f"{READS}/status", f"{READS}/spaces", *_space_read_paths(uuid4())]:
        assert client.get(path, headers=headers).status_code == 404, path
        assert client.get(path).status_code == 404, path


def test_reads_require_active_device_credentials(client, users, device):
    item, headers = device
    owner, _ = users
    assert client.get(f"{READS}/status", headers=owner).status_code == 401
    assert client.get(f"{READS}/status").status_code == 401
    assert client.post(f"/api/v1/clients/{item['id']}/revoke", headers=owner).status_code == 200
    assert client.get(f"{READS}/status", headers=headers).status_code == 401


def test_status_probe_returns_503_on_grant_lookup_failure(client, device, monkeypatch):
    _, headers = device

    def unavailable(*args):
        raise RuntimeError("Simulated lookup failure")

    monkeypatch.setattr(client_space_reads, "_granted_space_ids", unavailable)
    response = client.get(f"{READS}/status", headers=headers)
    assert response.status_code == 503
    assert response.json()["detail"] == "Device space status unavailable"
