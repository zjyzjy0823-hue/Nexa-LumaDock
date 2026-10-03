"""Transaction and HTTP wiring; scheduler timing is tested separately."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app import core_connection
from app.database import get_db
from app.main import app
from app.models import LedgerTransaction, LocalMutation, LocalSyncState
from app.sync.local import record_local_upsert
from app.sync.notifications import register_coordinator, unregister_coordinator


class Observer:
    def __init__(self):
        self.requests = []
        self.connections = []
        self.manual_calls = []

    def request_sync(self, workspace_id):
        self.requests.append(workspace_id)

    def connection_changed(self, user_id, workspace_id, connected):
        self.connections.append((user_id, workspace_id, connected))

    def snapshot(self, workspace_id):
        return {"enabled": True, "running": True, "connected": True, "blocked": False,
                "lastAttemptAt": "2026-10-02T12:00:00Z", "nextRetryAt": None}

    async def manual(self, user_id, workspace_id):
        self.manual_calls.append((user_id, workspace_id))
        return {"status": "ok", "pushed": 0, "pulled": 0}


@pytest.fixture
def observer(client, users):
    iterator = app.dependency_overrides[get_db]()
    db = next(iterator)
    engine = db.get_bind()
    iterator.close()
    instance = Observer()
    register_coordinator(engine, instance)
    try:
        yield instance
    finally:
        unregister_coordinator(engine, instance)


def database():
    iterator = app.dependency_overrides[get_db]()
    return iterator, next(iterator)


def transaction(client, auth):
    response = client.post("/api/v1/ledger/transactions", headers=auth, json={
        "type": "expense", "amount": "38.00", "description": "offline",
        "occurred_at": "2026-10-02T12:00:00Z"})
    assert response.status_code == 201
    return response.json()["id"]


def test_committed_business_write_wakes_only_its_workspace(client, users, observer):
    first, second = users
    one = transaction(client, first)
    two = transaction(client, second)
    iterator, db = database()
    try:
        ws_one = db.get(LedgerTransaction, one).workspace_id
        ws_two = db.get(LedgerTransaction, two).workspace_id
        assert observer.requests == [ws_one, ws_two]
        observer.requests.clear()
        item = db.get(LedgerTransaction, one)
        item.description = "not yet committed"
        record_local_upsert(db, item)
        assert observer.requests == []
        db.rollback()
        db.commit()
        assert observer.requests == []
        item = db.get(LedgerTransaction, one)
        item.description = "committed"
        record_local_upsert(db, item)
        db.commit()
        assert observer.requests == [ws_one]
        assert db.scalar(select(LocalMutation).where(LocalMutation.entity_id == one)).payload_json["description"] == "committed"
    finally:
        iterator.close()


def test_connection_and_manual_routes_notify_same_coordinator(client, users, observer, monkeypatch):
    auth, _ = users
    monkeypatch.setattr(core_connection, "connect", lambda *_args: {"connected": True})
    monkeypatch.setattr(core_connection, "disconnect", lambda *_args: {"connected": False})
    response = client.post("/api/v1/core/connect", headers=auth, json={
        "coreUrl": "https://core.example", "username": "owner", "password": "temporary",
        "clientName": "test", "platform": "windows", "appVersion": "0.5.6"})
    assert response.status_code == 200
    assert observer.connections[0][2] is True
    monkeypatch.setattr(core_connection, "load_connection", lambda *_args: SimpleNamespace())
    monkeypatch.setattr(core_connection.credential_store, "load", lambda *_args: "nc_live_private")
    assert client.post("/api/v1/sync/run", headers=auth).json()["status"] == "ok"
    assert observer.manual_calls == [observer.connections[0][:2]]
    assert client.delete("/api/v1/core/connection", headers=auth).status_code == 200
    assert observer.connections[1] == (*observer.connections[0][:2], False)


def test_status_is_safe_user_scoped_and_reports_scheduler(client, users, observer, monkeypatch):
    auth, other = users
    entity_id = transaction(client, auth)
    monkeypatch.setattr(core_connection, "load_connection", lambda *_args: SimpleNamespace())
    iterator, db = database()
    try:
        ws = db.get(LedgerTransaction, entity_id).workspace_id
        state = db.get(LocalSyncState, ws)
        state.last_error = "Authorization: Bearer nc_live_private traceback password"
        db.commit()
    finally:
        iterator.close()
    status = client.get("/api/v1/sync/status", headers=auth)
    assert status.status_code == 200
    assert status.json()["pending"] == 1
    assert status.json()["enabled"] and status.json()["running"]
    assert status.json()["lastError"] == "internal_error"
    assert "nc_live_" not in status.text and "password" not in status.text
    assert client.get("/api/v1/sync/status", headers=other).json()["pending"] == 0


def test_unregister_stops_notifications_without_changing_outbox(client, users, observer):
    auth, _ = users
    iterator, db = database()
    engine = db.get_bind()
    iterator.close()
    unregister_coordinator(engine, observer)
    entity_id = transaction(client, auth)
    assert observer.requests == []
    iterator, db = database()
    try:
        assert db.get(LedgerTransaction, entity_id) is not None
        assert db.scalar(select(LocalMutation).where(LocalMutation.entity_id == entity_id)).status == "pending"
    finally:
        iterator.close()


def test_failed_wakeup_cannot_fail_local_write(client, users, observer, monkeypatch):
    def unavailable(_workspace):
        raise RuntimeError("event loop already stopped")
    monkeypatch.setattr(observer, "request_sync", unavailable)
    entity_id = transaction(client, users[0])
    iterator, db = database()
    try:
        assert db.get(LedgerTransaction, entity_id) is not None
        assert db.scalar(select(LocalMutation).where(LocalMutation.entity_id == entity_id)).status == "pending"
    finally:
        iterator.close()


def test_invalid_saved_connection_is_safe_attention_state(client, users, observer, monkeypatch):
    def invalid(_user_id):
        raise HTTPException(500, "private credential traceback")
    monkeypatch.setattr(core_connection, "load_connection", invalid)
    status = client.get("/api/v1/sync/status", headers=users[0])
    assert status.status_code == 200
    assert status.json()["blocked"] and not status.json()["enabled"]
    assert not status.json()["connected"]
    assert status.json()["lastError"] == "invalid_connection"
    assert "private" not in status.text and "traceback" not in status.text
