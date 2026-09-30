"""Phase 2 Local outbox behavior with no Core connection or network calls."""

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
import os
import subprocess
import sys

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import MetaData, Table, create_engine, select
from sqlalchemy.orm import Session

from app.api import ledger
from app.database import get_db
from app.main import app
from app.models import LedgerCategory, LedgerTransaction, LocalMutation, LocalSyncState, utcnow
from app.sync.local import bind_local_sync_state, ordered_pending_mutations, seed_local_ledger_queue


LEDGER = "/api/v1/ledger"


def workspace(client, auth):
    return client.get("/api/v1/workspace", headers=auth).json()["id"]


def db_session():
    iterator = app.dependency_overrides[get_db]()
    return iterator, next(iterator)


def transaction_data(category_id=None):
    return {"category_id": category_id, "type": "expense", "amount": "38.00",
            "description": "Coffee", "merchant": "", "note": "",
            "occurred_at": "2026-09-28T12:00:00Z"}


def test_offline_create_compaction_and_unsynced_delete(client, users, monkeypatch):
    def no_network(*_args, **_kwargs):
        raise AssertionError("Local Ledger must not open a network client")

    monkeypatch.setattr(httpx, "Client", no_network)
    from app import core_connection
    monkeypatch.setattr(core_connection.credential_store, "load", no_network)
    auth, _ = users
    assert client.get("/api/dashboard", headers=auth).status_code == 200
    created = client.post(f"{LEDGER}/transactions", headers=auth, json=transaction_data())
    assert created.status_code == 201, created.text
    entity_id = created.json()["id"]
    local_workspace = workspace(client, auth)
    iterator, db = db_session()
    try:
        item = db.get(LedgerTransaction, entity_id)
        entry = db.scalar(select(LocalMutation).where(LocalMutation.entity_id == entity_id))
        state = db.get(LocalSyncState, local_workspace)
        assert item.sync_revision == 0 and item.workspace_id == local_workspace
        assert state.cursor == 0 and state.remote_core_url is None
        assert state.remote_workspace_id is None and state.remote_client_id is None
        assert entry.status == "pending" and entry.operation == "upsert" and entry.base_revision == 0
        assert entry.payload_json["amount"] == "38.00"
        assert not {"user_id", "workspace_id", "userId", "workspaceId"} & set(entry.payload_json)
        mutation_id = entry.mutation_id
    finally:
        iterator.close()
    for description in ("A", "B", "C"):
        response = client.patch(f"{LEDGER}/transactions/{entity_id}", headers=auth,
                                json={"description": description})
        assert response.status_code == 200, response.text
    iterator, db = db_session()
    try:
        entries = db.scalars(select(LocalMutation).where(LocalMutation.workspace_id == local_workspace)).all()
        assert len(entries) == 1
        assert entries[0].mutation_id == mutation_id and entries[0].base_revision == 0
        assert entries[0].payload_json["description"] == "C"
        assert db.get(LedgerTransaction, entity_id).sync_revision == 0
    finally:
        iterator.close()
    assert client.get("/api/v1/sync/status", headers=auth).json() == {
        "pending": 1, "inFlight": 0, "conflicts": 0, "rejected": 0,
        "cursor": 0, "queueSeeded": True, "lastSuccessAt": None, "lastError": None}
    assert client.delete(f"{LEDGER}/transactions/{entity_id}", headers=auth).status_code == 204
    assert client.get(f"{LEDGER}/transactions/{entity_id}", headers=auth).status_code == 404
    iterator, db = db_session()
    try:
        assert db.get(LedgerTransaction, entity_id).deleted_at is not None
        assert db.scalar(select(LocalMutation).where(LocalMutation.entity_id == entity_id)) is None
    finally:
        iterator.close()


def test_synced_update_delete_and_conflict_tail(client, users):
    auth, _ = users
    entity_id = client.post(f"{LEDGER}/transactions", headers=auth,
                            json=transaction_data()).json()["id"]
    iterator, db = db_session()
    try:
        db.get(LedgerTransaction, entity_id).sync_revision = 10
        db.delete(db.scalar(select(LocalMutation).where(LocalMutation.entity_id == entity_id)))
        db.commit()
    finally:
        iterator.close()
    for description in ("First edit", "Second edit"):
        assert client.patch(f"{LEDGER}/transactions/{entity_id}", headers=auth,
                            json={"description": description}).status_code == 200
    iterator, db = db_session()
    try:
        entry = db.scalar(select(LocalMutation).where(LocalMutation.entity_id == entity_id))
        assert entry.operation == "upsert" and entry.base_revision == 10
        assert entry.payload_json["description"] == "Second edit"
        mutation_id = entry.mutation_id
        assert db.get(LedgerTransaction, entity_id).sync_revision == 10
    finally:
        iterator.close()
    assert client.delete(f"{LEDGER}/transactions/{entity_id}", headers=auth).status_code == 204
    iterator, db = db_session()
    try:
        entry = db.scalar(select(LocalMutation).where(LocalMutation.entity_id == entity_id))
        assert entry.mutation_id == mutation_id and entry.base_revision == 10
        assert entry.operation == "delete" and entry.payload_json is None
        assert db.get(LedgerTransaction, entity_id).sync_revision == 10
    finally:
        iterator.close()

    other_id = client.post(f"{LEDGER}/transactions", headers=auth,
                           json=transaction_data()).json()["id"]
    iterator, db = db_session()
    try:
        entry = db.scalar(select(LocalMutation).where(LocalMutation.entity_id == other_id))
        old_id = entry.mutation_id
        entry.status = "conflict"
        db.commit()
    finally:
        iterator.close()
    assert client.patch(f"{LEDGER}/transactions/{other_id}", headers=auth,
                        json={"description": "Resolved"}).status_code == 200
    iterator, db = db_session()
    try:
        entries = db.scalars(select(LocalMutation).where(LocalMutation.entity_id == other_id)).all()
        assert len(entries) == 2
        frozen = next(entry for entry in entries if entry.mutation_id == old_id)
        tail = next(entry for entry in entries if entry.mutation_id != old_id)
        assert frozen.status == "conflict" and tail.status == "pending"
        assert tail.depends_on_mutation_id == old_id and tail.base_revision == 0
    finally:
        iterator.close()


def test_unsynced_category_delete_repairs_transactions(client, users):
    auth, _ = users
    category_id = client.post(f"{LEDGER}/categories", headers=auth,
                              json={"name": "Food", "type": "expense"}).json()["id"]
    transaction_id = client.post(f"{LEDGER}/transactions", headers=auth,
                                 json=transaction_data(category_id)).json()["id"]
    assert client.delete(f"{LEDGER}/categories/{category_id}", headers=auth).status_code == 204
    assert client.get(f"{LEDGER}/transactions/{transaction_id}", headers=auth).json()["categoryId"] is None
    iterator, db = db_session()
    try:
        assert db.scalar(select(LocalMutation).where(LocalMutation.entity_id == category_id)) is None
        transaction = db.get(LedgerTransaction, transaction_id)
        assert transaction.category_id is None and transaction.sync_revision == 0
        entry = db.scalar(select(LocalMutation).where(LocalMutation.entity_id == transaction_id))
        assert entry.payload_json["categoryId"] is None
        assert db.get(LedgerCategory, category_id).deleted_at is not None
    finally:
        iterator.close()


def test_synced_category_delete_preserves_reference_and_anomaly_rejected(client, users):
    auth, _ = users
    category_id = client.post(f"{LEDGER}/categories", headers=auth,
                              json={"name": "Known", "type": "expense"}).json()["id"]
    transaction_id = client.post(f"{LEDGER}/transactions", headers=auth,
                                 json=transaction_data(category_id)).json()["id"]
    iterator, db = db_session()
    try:
        db.get(LedgerCategory, category_id).sync_revision = 5
        db.delete(db.scalar(select(LocalMutation).where(LocalMutation.entity_id == category_id)))
        db.commit()
    finally:
        iterator.close()
    assert client.delete(f"{LEDGER}/categories/{category_id}", headers=auth).status_code == 204
    iterator, db = db_session()
    try:
        entry = db.scalar(select(LocalMutation).where(LocalMutation.entity_id == category_id))
        assert entry.operation == "delete" and entry.base_revision == 5
        assert db.get(LedgerTransaction, transaction_id).category_id == category_id
    finally:
        iterator.close()

    bad_category = client.post(f"{LEDGER}/categories", headers=auth,
                               json={"name": "Unknown", "type": "expense"}).json()["id"]
    bad_transaction = client.post(f"{LEDGER}/transactions", headers=auth,
                                  json=transaction_data(bad_category)).json()["id"]
    iterator, db = db_session()
    try:
        db.get(LedgerTransaction, bad_transaction).sync_revision = 10
        db.commit()
    finally:
        iterator.close()
    response = client.delete(f"{LEDGER}/categories/{bad_category}", headers=auth)
    assert response.status_code == 409
    iterator, db = db_session()
    try:
        assert db.get(LedgerCategory, bad_category).deleted_at is None
        assert db.get(LedgerTransaction, bad_transaction).category_id == bad_category
    finally:
        iterator.close()


def test_queue_failure_rolls_back_business_and_status_isolated(client, users, monkeypatch):
    a, b = users
    def fail_queue(*_args):
        raise RuntimeError("simulated queue failure")

    from app.sync import publisher
    monkeypatch.setattr(publisher, "record_local_upsert", fail_queue)
    with pytest.raises(RuntimeError, match="simulated queue failure"):
        client.post(f"{LEDGER}/transactions", headers=a, json=transaction_data())
    iterator, db = db_session()
    try:
        assert db.scalars(select(LedgerTransaction)).all() == []
        assert db.scalars(select(LocalMutation)).all() == []
    finally:
        iterator.close()
    monkeypatch.undo()
    assert client.post(f"{LEDGER}/transactions", headers=a, json=transaction_data()).status_code == 201
    assert client.get("/api/v1/sync/status", headers=a).json()["pending"] == 1
    assert client.get("/api/v1/sync/status", headers=b).json()["pending"] == 0


def test_binding_detects_changed_core_without_reset(client, users):
    auth, _ = users
    local_workspace = workspace(client, auth)
    iterator, db = db_session()
    try:
        first = SimpleNamespace(coreUrl="https://core-a.example", workspaceId=str(uuid4()), clientId=str(uuid4()))
        state = bind_local_sync_state(db, local_workspace, first)
        assert state.workspace_id != state.remote_workspace_id
        state.cursor = 7
        db.commit()
        assert bind_local_sync_state(db, local_workspace, first).cursor == 7
        second = SimpleNamespace(coreUrl="https://core-b.example", workspaceId=str(uuid4()), clientId=str(uuid4()))
        try:
            bind_local_sync_state(db, local_workspace, second)
            assert False, "expected a binding conflict"
        except HTTPException as error:
            assert error.status_code == 409
        db.rollback()
        assert db.get(LocalSyncState, local_workspace).cursor == 7
    finally:
        iterator.close()


def test_legacy_local_seed_after_0011_upgrade(tmp_path: Path):
    database = tmp_path / "legacy-local.db"
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{database}", "NEXA_MODE": "local"}
    backend = Path(__file__).parents[1]

    def upgrade(revision):
        result = subprocess.run([sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", revision],
                                cwd=backend, env=env, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr

    upgrade("0011_sync_foundation")
    engine = create_engine(f"sqlite:///{database}")
    now = datetime.now(timezone.utc)
    local_workspace = str(uuid4())
    category_ids = [str(uuid4()) for _ in range(3)]
    metadata = MetaData()
    with engine.begin() as conn:
        def add(table_name, **values):
            conn.execute(Table(table_name, metadata, autoload_with=conn).insert().values(**values))

        add("users", id=1, username="legacy", email="legacy@example.test", password_hash="hash",
            created_at=now, updated_at=now)
        add("workspaces", id=local_workspace, owner_user_id=1, name="Personal", kind="personal",
            created_at=now, updated_at=now)
        for index, category_id in enumerate(category_ids):
            add("ledger_categories", id=category_id, user_id=1, workspace_id=local_workspace,
                name=f"Category {index}", type="expense", icon="shopping", created_at=now)
        for index in range(20):
            add("ledger_transactions", id=str(uuid4()), user_id=1, workspace_id=local_workspace,
                category_id=category_ids[index % 3], type="expense", amount=38,
                description=f"Expense {index}", merchant="", note="", occurred_at=now,
                created_at=now, updated_at=now)
    engine.dispose()
    upgrade("head")
    engine = create_engine(f"sqlite:///{database}")
    with Session(engine) as db:
        state = seed_local_ledger_queue(db, local_workspace)
        db.commit()
        assert state.queue_seeded_at is not None and state.cursor == 0
        entries = db.scalars(select(LocalMutation)).all()
        assert len(entries) == 23
        assert {entry.operation for entry in entries} == {"upsert"}
        assert {entry.base_revision for entry in entries} == {0}
        assert {entry.payload_json["amount"] for entry in entries if entry.entity_type == "ledger.transaction"} == {"38.00"}
        assert [entry.entity_type for entry in ordered_pending_mutations(db, local_workspace)][:3] == [
            "ledger.category"] * 3
        seed_local_ledger_queue(db, local_workspace)
        db.commit()
        assert len(db.scalars(select(LocalMutation)).all()) == 23
    engine.dispose()


def test_legacy_tombstone_category_reference_is_repaired(client, users):
    auth, _ = users
    local_workspace = workspace(client, auth)
    category_id, transaction_id = str(uuid4()), str(uuid4())
    iterator, db = db_session()
    try:
        from app.models import Workspace
        owner_id = db.get(Workspace, local_workspace).owner_user_id
        db.add(LedgerCategory(id=category_id, user_id=owner_id, workspace_id=local_workspace,
                              name="Old deleted", type="expense", icon="shopping",
                              sync_revision=0, deleted_at=utcnow()))
        db.add(LedgerTransaction(id=transaction_id, user_id=owner_id, workspace_id=local_workspace,
                                 category_id=category_id, type="expense", amount="4.00",
                                 description="Old expense", merchant="", note="",
                                 occurred_at=utcnow(), sync_revision=0))
        db.commit()
    finally:
        iterator.close()
    assert client.get("/api/v1/sync/status", headers=auth).json()["pending"] == 1
    iterator, db = db_session()
    try:
        assert db.get(LedgerTransaction, transaction_id).category_id is None
        entry = db.scalar(select(LocalMutation).where(LocalMutation.entity_id == transaction_id))
        assert entry.payload_json["categoryId"] is None
        assert db.scalar(select(LocalMutation).where(LocalMutation.entity_id == category_id)) is None
    finally:
        iterator.close()


def test_status_is_local_only(client, users, monkeypatch):
    from app import runtime_mode
    monkeypatch.setattr(runtime_mode, "runtime_config", replace(runtime_mode.runtime_config, mode="core"))
    auth, _ = users
    assert client.get("/api/v1/sync/status", headers=auth).status_code == 404
    assert client.post("/api/v1/sync/run", headers=auth).status_code == 404
