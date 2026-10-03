"""Explicit decisions on durable replicas, HTTP isolation, and safe failure paths."""
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select, event, update

from app.database import get_db
from app.main import app
from app.models import LedgerTransaction, LocalMutation, User, utcnow
from app.sync.adapters import get_adapter
from app.sync.conflicts import get_conflict, list_conflicts, resolve_conflict
from app.sync.engine import _lock_for
from app.sync.local import record_local_upsert, queued_entries
from app.sync.notifications import register_coordinator, unregister_coordinator
from app.sync.publisher import prepare_write, publish
from app.utils.time import iso_utc
from test_sync_engine import (network, create_transaction, create_category, edit, delete)
from test_multi_entity_sync import create as create_entity, edit as edit_entity


ROOT = "/api/v1/sync/conflicts"


def owner(local, entity_id):
    with local.factory() as db:
        return db.scalar(select(LocalMutation).where(
            LocalMutation.entity_id == entity_id, LocalMutation.status == "conflict"))


def resolve(local, conflict, strategy, revision=None):
    with local.factory() as db:
        return resolve_conflict(db, local.user_id, local.workspace_id, conflict.id,
                                strategy, revision)


def conflict(n, *, remote_deleted=False, local_deleted=False):
    entity_id = create_transaction(n.a)
    n.sync(n.a, n.ta)
    n.sync(n.b, n.tb)
    delete(n.a, entity_id) if remote_deleted else edit(n.a, entity_id, "Core 42")
    delete(n.b, entity_id) if local_deleted else edit(n.b, entity_id, "Local 38")
    assert n.sync(n.a, n.ta)["status"] == "ok"
    assert n.sync(n.b, n.tb)["conflicts"] == 1
    return entity_id, owner(n.b, entity_id)


def live(local, entity_id):
    with local.factory() as db:
        return db.scalars(select(LocalMutation).where(
            LocalMutation.entity_id == entity_id, LocalMutation.status != "resolved")).all()


def session():
    iterator = app.dependency_overrides[get_db]()
    return iterator, next(iterator)


@pytest.fixture
def api_conflict(client, users):
    auth, other = users
    response = client.post("/api/v1/ledger/transactions", headers=auth, json={
        "type": "expense", "amount": "38.00", "description": "Local Coffee",
        "occurred_at": "2026-10-03T08:30:00Z"})
    entity_id = response.json()["id"]
    iterator, db = session()
    try:
        item = db.get(LedgerTransaction, entity_id)
        item.sync_revision = 1
        entry = db.scalar(select(LocalMutation).where(LocalMutation.entity_id == entity_id))
        remote = {**get_adapter("ledger.transaction").serialize(item),
                  "description": "Core Coffee", "amount": "42.00"}
        entry.status, entry.base_revision, entry.result_revision = "conflict", 1, 2
        entry.conflict_json = {"currentRevision": 2, "current": remote, "deleted": False}
        db.commit()
        return auth, other, entity_id, entry.id, item.workspace_id
    finally:
        iterator.close()


def test_listing_detail_status_and_latest_local_tail(client, api_conflict):
    auth, _, entity_id, conflict_id, _ = api_conflict
    client.patch(f"/api/v1/ledger/transactions/{entity_id}", headers=auth,
                 json={"description": "Latest local tail"})
    response = client.get(ROOT, headers=auth)
    assert response.status_code == 200
    entries = response.json()["conflicts"]
    assert len(entries) == 1
    detail = client.get(f"{ROOT}/{conflict_id}", headers=auth).json()
    assert entries[0] == detail
    assert detail["entityType"] == "ledger.transaction" and detail["entityId"] == entity_id
    assert detail["local"]["description"] == "Latest local tail"
    assert detail["remote"]["amount"] == "42.00" and detail["remoteRevision"] == 2
    assert detail["hasPendingTail"] and not detail["localDeleted"] and not detail["remoteDeleted"]
    assert detail["createdAt"] and detail["detectedAt"] and detail["updatedAt"]
    assert not {"payload_json", "conflict_json", "workspace_id", "user_id", "last_error"} & detail.keys()
    assert client.get("/api/v1/sync/status", headers=auth).json()["conflicts"] == 1
    result = client.post(f"{ROOT}/{conflict_id}/resolve", headers=auth,
                         json={"strategy": "remote", "expectedRemoteRevision": 2})
    assert result.status_code == 200
    assert client.get("/api/v1/sync/status", headers=auth).json()["conflicts"] == 0
    assert client.get(ROOT, headers=auth).json() == {"conflicts": []}
    assert client.get(f"{ROOT}/{conflict_id}", headers=auth).status_code == 404
    assert client.get(f"/api/v1/ledger/transactions/{entity_id}", headers=auth).json()["description"] == "Core Coffee"


@pytest.mark.parametrize("tail", [False, True])
def test_remote_existing_discards_entire_tail_without_push(network, tail):
    n = network
    entity_id, entry = conflict(n)
    if tail:
        edit(n.b, entity_id, "Newest discarded local edit")
    sent = len(n.tb.sent)
    receipt = resolve(n.b, entry, "remote", 2)
    assert receipt["mutationId"] is None and live(n.b, entity_id) == []
    with n.b.factory() as db:
        item = db.get(LedgerTransaction, entity_id)
        assert item.description == "Core 42" and item.sync_revision == 2
    assert n.sync(n.b, n.tb)["conflicts"] == 0
    assert len(n.tb.sent) == sent


def test_remote_deleted_hides_entity(network):
    n = network
    entity_id, entry = conflict(n, remote_deleted=True)
    with n.b.factory() as db:
        assert get_conflict(db, n.b.workspace_id, entry.id)["remoteDeleted"]
    resolve(n.b, entry, "remote")
    with n.b.factory() as db:
        item = db.get(LedgerTransaction, entity_id)
        assert item.deleted_at is not None and item.sync_revision == 2
    assert not live(n.b, entity_id)
    assert n.sync(n.b, n.tb)["conflicts"] == 0


@pytest.mark.parametrize("tail", [False, True])
def test_local_preserves_latest_business_row_and_rebases_once(network, tail):
    n = network
    entity_id, entry = conflict(n)
    chosen = "Latest Local B" if tail else "Local 38"
    if tail:
        edit(n.b, entity_id, chosen)
    receipt = resolve(n.b, entry, "local", 2)
    pending = live(n.b, entity_id)
    assert len(pending) == 1 and pending[0].base_revision == 2
    assert pending[0].payload_json["description"] == chosen
    assert pending[0].depends_on_mutation_id is None and pending[0].attempt_count == 0
    assert pending[0].mutation_id == receipt["mutationId"] != entry.mutation_id
    assert n.sync(n.b, n.tb)["pushed"] == 1
    assert n.sync(n.a, n.ta)["status"] == "ok"
    for local in (n.a, n.b, n.core):
        with local.factory() as db:
            item = db.get(LedgerTransaction, entity_id)
            assert item.description == chosen and item.sync_revision == 3


def test_keep_local_restores_after_remote_delete(network):
    n = network
    entity_id, entry = conflict(n, remote_deleted=True)
    resolve(n.b, entry, "local", 2)
    pending = live(n.b, entity_id)[0]
    assert pending.operation == "upsert" and pending.base_revision == 2
    assert n.sync(n.b, n.tb)["pushed"] == 1
    n.sync(n.a, n.ta)
    for local in (n.a, n.b, n.core):
        with local.factory() as db:
            item = db.get(LedgerTransaction, entity_id)
            assert item.deleted_at is None and item.description == "Local 38" and item.sync_revision == 3


@pytest.mark.parametrize("strategy", ["local", "remote"])
def test_local_delete_vs_remote_edit(network, strategy):
    n = network
    entity_id, entry = conflict(n, local_deleted=True)
    with n.b.factory() as db:
        detail = get_conflict(db, n.b.workspace_id, entry.id)
        assert detail["localDeleted"] and detail["local"] is None
        assert detail["remote"]["description"] == "Core 42"
    resolve(n.b, entry, strategy, 2)
    if strategy == "local":
        pending = live(n.b, entity_id)[0]
        assert pending.operation == "delete" and pending.base_revision == 2 and pending.payload_json is None
    n.sync(n.b, n.tb)
    n.sync(n.a, n.ta)
    for local in (n.a, n.b, n.core):
        with local.factory() as db:
            assert (db.get(LedgerTransaction, entity_id).deleted_at is not None) == (strategy == "local")


def test_resolution_race_returns_new_conflict_without_hidden_retry(network):
    n = network
    entity_id, original = conflict(n)
    edit(n.a, entity_id, "New authoritative rev 3")
    n.sync(n.a, n.ta)
    receipt = resolve(n.b, original, "local", 2)
    assert live(n.b, entity_id)[0].base_revision == 2
    result = n.sync(n.b, n.tb)
    assert result["conflicts"] == 1 and result["pushed"] == 0
    raced = owner(n.b, entity_id)
    assert raced.mutation_id == receipt["mutationId"]
    assert raced.conflict_json["currentRevision"] == 3 and raced.base_revision == 2
    for _ in range(2):
        assert n.sync(n.b, n.tb)["conflicts"] == 1
    with n.b.factory() as db:
        assert db.get(LedgerTransaction, entity_id).description == "Local 38"
    with n.core.factory() as db:
        assert db.get(LedgerTransaction, entity_id).description == "New authoritative rev 3"


def test_core_rejects_resolution_racing_after_pull(network, monkeypatch):
    n = network
    entity_id, entry = conflict(n)
    receipt = resolve(n.b, entry, "local", 2)
    push = n.tb.push_mutation
    attempted = []
    def race(request):
        attempted.append(request)
        edit(n.a, entity_id, "Changed between pull and push")
        n.sync(n.a, n.ta)
        return push(request)
    monkeypatch.setattr(n.tb, "push_mutation", race)
    result = n.sync(n.b, n.tb)
    assert result["conflicts"] == 1 and result["pushed"] == 0 and len(attempted) == 1
    assert attempted[0]["mutationId"] == receipt["mutationId"] and attempted[0]["baseRevision"] == 2
    latest = owner(n.b, entity_id)
    assert latest.conflict_json["currentRevision"] == 3
    with n.b.factory() as db:
        assert db.get(LedgerTransaction, entity_id).description == "Local 38"


def test_changed_displayed_snapshot_requires_new_decision(network):
    n = network
    entity_id, entry = conflict(n)
    initial_detected = entry.conflict_json["detectedAt"]
    edit(n.a, entity_id, "New revision")
    n.sync(n.a, n.ta)
    n.sync(n.b, n.tb)
    with pytest.raises(HTTPException) as exc:
        resolve(n.b, entry, "local", 2)
    assert exc.value.detail == "conflict_snapshot_changed"
    updated = owner(n.b, entity_id)
    assert updated.conflict_json["currentRevision"] == 3
    assert updated.conflict_json["detectedAt"] == initial_detected
    assert len(live(n.b, entity_id)) == 1


def test_legacy_detected_timestamp_is_preserved_on_snapshot_refresh(network):
    n = network
    entity_id, entry = conflict(n)
    with n.b.factory() as db:
        legacy = db.get(LocalMutation, entry.id)
        legacy.conflict_json = {key: value for key, value in legacy.conflict_json.items() if key != "detectedAt"}
        db.commit()
        fallback = iso_utc(legacy.updated_at)
    edit(n.a, entity_id, "Refresh legacy conflict")
    n.sync(n.a, n.ta)
    n.sync(n.b, n.tb)
    assert owner(n.b, entity_id).conflict_json["detectedAt"] == fallback


def test_resolution_wakes_background_only_after_successful_local_commit(network):
    n = network
    entity_id, entry = conflict(n)
    class Observer:
        def __init__(self):
            self.requests = []
        def request_sync(self, workspace_id):
            with n.b.factory() as db:
                assert db.get(LocalMutation, entry.id).status == "resolved"
                assert len(live(n.b, entity_id)) == 1
            self.requests.append(workspace_id)
    observer = Observer()
    register_coordinator(n.b.engine, observer)
    try:
        with pytest.raises(HTTPException):
            resolve(n.b, entry, "local", 99)
        assert observer.requests == []
        resolve(n.b, entry, "local", 2)
        assert observer.requests == [n.b.workspace_id]
        resolve(n.b, entry, "local", 2)
        assert observer.requests == [n.b.workspace_id]
    finally:
        unregister_coordinator(n.b.engine, observer)


def test_http_user_isolation_and_missing_conflict(client, api_conflict):
    auth, other, _, conflict_id, _ = api_conflict
    assert client.get(ROOT).status_code == 401
    assert client.get(ROOT, headers=other).json() == {"conflicts": []}
    assert client.get(f"{ROOT}/{conflict_id}", headers=other).status_code == 404
    assert client.post(f"{ROOT}/{conflict_id}/resolve", headers=other,
                       json={"strategy": "remote"}).status_code == 404
    assert client.get(f"{ROOT}/{uuid4()}", headers=auth).status_code == 404


@pytest.mark.parametrize("snapshot", [None, [], {},
    {"currentRevision": True, "current": None, "deleted": False},
    {"currentRevision": 2, "current": None, "deleted": False},
    {"currentRevision": 2, "current": {"password": "private"}, "deleted": True},
    {"currentRevision": 2, "current": {"bearer": "private"}, "deleted": False},
    {"currentRevision": 2, "current": None, "deleted": True, "detectedAt": "password=private"},
    {"currentRevision": -1, "current": None, "deleted": True}])
def test_malformed_snapshot_controlled_and_atomic(client, api_conflict, snapshot):
    auth, _, entity_id, conflict_id, _ = api_conflict
    iterator, db = session()
    try:
        db.get(LocalMutation, conflict_id).conflict_json = snapshot
        db.commit()
    finally:
        iterator.close()
    for method, url in ((client.get, ROOT), (client.get, f"{ROOT}/{conflict_id}")):
        response = method(url, headers=auth)
        assert response.status_code == 409 and response.json()["detail"] == "invalid_conflict_snapshot"
        assert "private" not in response.text
    result = client.post(f"{ROOT}/{conflict_id}/resolve", headers=auth, json={"strategy": "remote"})
    assert result.status_code == 409
    iterator, db = session()
    try:
        assert db.get(LocalMutation, conflict_id).status == "conflict"
        assert db.get(LedgerTransaction, entity_id).description == "Local Coffee"
    finally:
        iterator.close()


def test_unknown_entity_and_untrusted_request_are_safe(client, api_conflict):
    auth, _, _, conflict_id, _ = api_conflict
    iterator, db = session()
    try:
        db.get(LocalMutation, conflict_id).entity_type = "unknown"
        db.commit()
    finally:
        iterator.close()
    assert client.get(ROOT, headers=auth).json()["detail"] == "unknown_entity_type"
    for payload in ({"strategy": "merged"}, {"strategy": "password=private"},
                    {"strategy": "remote", "credential": "nc_live_private"},
                    {"strategy": "remote", "expectedRemoteRevision": True},
                    {"strategy": "remote", "expectedRemoteRevision": "nc_live_private"}):
        response = client.post(f"{ROOT}/{conflict_id}/resolve", headers=auth, json=payload)
        assert response.status_code == 422 and response.json()["detail"] == "invalid_conflict_resolution"
        assert "private" not in response.text


@pytest.mark.parametrize("field,value", [("remoteRevision", "nc_live_private"),
    ("remoteRevision", True), ("mutationId", "nc_live_private"),
    ("resolvedAt", "password=private"), ("id", "nc_live_private"),
    ("strategy", "private"), ("password=private", "private")])
def test_tampered_resolution_receipt_never_leaks(client, api_conflict, field, value):
    auth, _, _, conflict_id, _ = api_conflict
    assert client.post(f"{ROOT}/{conflict_id}/resolve", headers=auth,
                       json={"strategy": "remote"}).status_code == 200
    iterator, db = session()
    try:
        entry = db.get(LocalMutation, conflict_id)
        entry.conflict_json = {**entry.conflict_json, field: value}
        db.commit()
    finally:
        iterator.close()
    response = client.post(f"{ROOT}/{conflict_id}/resolve", headers=auth, json={"strategy": "remote"})
    assert response.status_code == 409 and response.json()["detail"] == "invalid_resolution_receipt"
    assert "private" not in response.text


@pytest.mark.parametrize("entity_type,parent_type,parent_key", [
    ("website", "website.category", "categoryId"),
    ("data.record", "data.collection", "collectionId")])
def test_remote_parent_validation_rolls_back(network, entity_type, parent_type, parent_key):
    n = network
    parent_id = create_entity(n.a, parent_type)
    entity_id = create_entity(n.a, entity_type, parent_id)
    n.sync(n.a, n.ta)
    n.sync(n.b, n.tb)
    edit_entity(n.a, entity_type, entity_id, name="Core")
    edit_entity(n.b, entity_type, entity_id, name="Local")
    n.sync(n.a, n.ta)
    n.sync(n.b, n.tb)
    entry = owner(n.b, entity_id)
    with n.b.factory() as db:
        current = db.get(LocalMutation, entry.id)
        current.conflict_json = {**current.conflict_json,
            "current": {**current.conflict_json["current"], parent_key: str(uuid4())}}
        db.commit()
    with pytest.raises(HTTPException) as exc:
        resolve(n.b, entry, "remote")
    assert exc.value.detail in ("category_not_found", "collection_not_found")
    with n.b.factory() as db:
        assert db.get(get_adapter(entity_type).model, entity_id).name == "Local"
        assert db.get(LocalMutation, entry.id).status == "conflict"


@pytest.mark.parametrize("strategy", ["local", "remote"])
def test_durable_resolution_replay_and_future_edit(network, strategy):
    n = network
    entity_id, entry = conflict(n)
    first = resolve(n.b, entry, strategy, 2)
    n.sync(n.b, n.tb)
    assert resolve(n.b, entry, strategy, 2) == first
    with pytest.raises(HTTPException) as exc:
        resolve(n.b, entry, "remote" if strategy == "local" else "local")
    assert exc.value.detail == "conflict_already_resolved"
    with n.b.factory() as db:
        receipt = db.get(LocalMutation, entry.id)
        assert receipt.payload_json is None and receipt.conflict_json == first
        assert "current" not in receipt.conflict_json
    edit(n.b, entity_id, "Fresh edit after resolution")
    assert live(n.b, entity_id)[0].depends_on_mutation_id is None
    assert n.sync(n.b, n.tb)["pushed"] == 1


@pytest.mark.parametrize("parent_type,child_type", [
    ("ledger.category", "ledger.transaction"), ("website.category", "website"),
    ("data.collection", "data.record")])
def test_resolved_receipts_allow_parent_pull_and_child_push(network, parent_type, child_type):
    n = network
    parent_id = create_category(n.a) if parent_type == "ledger.category" else create_entity(n.a, parent_type)
    n.sync(n.a, n.ta)
    n.sync(n.b, n.tb)
    edit_entity(n.a, parent_type, parent_id, name="Core parent")
    edit_entity(n.b, parent_type, parent_id, name="Local parent")
    n.sync(n.a, n.ta)
    n.sync(n.b, n.tb)
    entry = owner(n.b, parent_id)
    resolve(n.b, entry, "remote")
    child_id = create_transaction(n.b, parent_id) if child_type == "ledger.transaction" else create_entity(n.b, child_type, parent_id)
    assert n.sync(n.b, n.tb)["pushed"] == 1
    assert not live(n.b, child_id)
    edit_entity(n.a, parent_type, parent_id, name="New authoritative parent")
    n.sync(n.a, n.ta)
    assert n.sync(n.b, n.tb)["conflicts"] == 0
    with n.b.factory() as db:
        assert db.get(get_adapter(parent_type).model, parent_id).name == "New authoritative parent"
        assert queued_entries(db, db.get(get_adapter(parent_type).model, parent_id)) == []


def test_unresolved_conflict_survives_engine_restart(network):
    n = network
    entity_id, entry = conflict(n)
    n.b.engine.dispose()
    with n.b.factory() as db:
        detail = get_conflict(db, n.b.workspace_id, entry.id)
        assert detail["remoteRevision"] == 2 and detail["local"]["description"] == "Local 38"
    assert n.sync(n.b, n.tb)["conflicts"] == 1
    assert owner(n.b, entity_id).id == entry.id


def test_resolution_rejects_active_sync_without_mutating(network):
    n = network
    entity_id, entry = conflict(n)
    lock = _lock_for(str(n.b.engine.url), n.b.workspace_id)
    lock.acquire()
    try:
        with pytest.raises(HTTPException) as exc:
            resolve(n.b, entry, "remote")
        assert exc.value.detail == "sync_in_progress"
    finally:
        lock.release()
    assert owner(n.b, entity_id).id == entry.id


@pytest.mark.parametrize("strategy,local_deleted", [("remote", False), ("local", False), ("local", True)])
def test_core_absent_revision_zero_resolution(client, api_conflict, strategy, local_deleted):
    auth, _, entity_id, conflict_id, _ = api_conflict
    iterator, db = session()
    try:
        entry = db.get(LocalMutation, conflict_id)
        entry.result_revision = 0
        entry.conflict_json = {"currentRevision": 0, "current": None, "deleted": False}
        if local_deleted:
            db.get(LedgerTransaction, entity_id).deleted_at = utcnow()
        db.commit()
    finally:
        iterator.close()
    result = client.post(f"{ROOT}/{conflict_id}/resolve", headers=auth,
                         json={"strategy": strategy, "expectedRemoteRevision": 0})
    assert result.status_code == 200
    iterator, db = session()
    try:
        entries = queued_entries(db, db.get(LedgerTransaction, entity_id))
        if strategy == "local" and not local_deleted:
            assert len(entries) == 1 and entries[0].base_revision == 0 and entries[0].operation == "upsert"
        else:
            assert entries == [] and db.get(LedgerTransaction, entity_id).deleted_at is not None
    finally:
        iterator.close()


@pytest.mark.parametrize("entity_type", ["ledger.category", "ledger.transaction",
    "website.category", "website", "data.collection", "data.record"])
@pytest.mark.parametrize("strategy", ["local", "remote"])
def test_all_adapter_resolutions_share_registry(network, entity_type, strategy):
    n = network
    parent = {"ledger.transaction": "ledger.category", "website": "website.category",
              "data.record": "data.collection"}.get(entity_type)
    parent_id = (create_category(n.a) if parent == "ledger.category" else
                 create_entity(n.a, parent)) if parent else None
    if entity_type == "ledger.category":
        entity_id = create_category(n.a)
    elif entity_type == "ledger.transaction":
        entity_id = create_transaction(n.a, parent_id)
    else:
        entity_id = create_entity(n.a, entity_type, parent_id)
    n.sync(n.a, n.ta)
    n.sync(n.b, n.tb)
    field = "description" if entity_type == "ledger.transaction" else "name"
    edit_entity(n.a, entity_type, entity_id, **{field: "Core decision"})
    edit_entity(n.b, entity_type, entity_id, **{field: "Local decision"})
    n.sync(n.a, n.ta)
    assert n.sync(n.b, n.tb)["conflicts"] == 1
    entry = owner(n.b, entity_id)
    with n.b.factory() as db:
        detail = list_conflicts(db, n.b.workspace_id)["conflicts"][0]
        assert detail["local"][field] == "Local decision" and detail["remote"][field] == "Core decision"
    resolve(n.b, entry, strategy, detail["remoteRevision"])
    assert n.sync(n.b, n.tb)["conflicts"] == 0
    n.sync(n.a, n.ta)
    expected = "Local decision" if strategy == "local" else "Core decision"
    for local in (n.a, n.b, n.core):
        with local.factory() as db:
            assert getattr(db.get(get_adapter(entity_type).model, entity_id), field) == expected


@pytest.mark.parametrize("strategy", ["local", "remote"])
def test_writer_serialization_uses_committed_latest_local_version(network, strategy):
    n = network
    entity_id, entry = conflict(n)
    writer_ready, allow_commit, resolver_started = Event(), Event(), Event()
    def business_writer():
        with n.b.factory() as db:
            db.execute(update(LedgerTransaction).where(LedgerTransaction.id == entity_id)
                       .values(description="Concurrent latest local"))
            record_local_upsert(db, db.get(LedgerTransaction, entity_id))
            writer_ready.set()
            assert allow_commit.wait(5)
            db.commit()
    def before_cursor(_conn, _cursor, statement, _parameters, _context, _many):
        if statement.startswith("UPDATE local_mutation_queue SET updated_at=local_mutation_queue.updated_at"):
            resolver_started.set()
    event.listen(n.b.engine, "before_cursor_execute", before_cursor)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            writer = pool.submit(business_writer)
            assert writer_ready.wait(5)
            resolver = pool.submit(resolve, n.b, entry, strategy, 2)
            try:
                assert resolver_started.wait(5)
                assert not resolver.done()
            finally:
                allow_commit.set()
            writer.result(timeout=5)
            resolver.result(timeout=5)
    finally:
        allow_commit.set()
        event.remove(n.b.engine, "before_cursor_execute", before_cursor)
    with n.b.factory() as db:
        assert db.get(LedgerTransaction, entity_id).description == (
            "Concurrent latest local" if strategy == "local" else "Core 42")
    entries = live(n.b, entity_id)
    if strategy == "local":
        assert len(entries) == 1 and entries[0].payload_json["description"] == "Concurrent latest local"
    else:
        assert entries == []


def test_local_publisher_refreshes_preexisting_reads_after_remote_resolution(network):
    n = network
    entity_id = create_transaction(n.a)
    n.sync(n.a, n.ta)
    n.sync(n.b, n.tb)
    edit_entity(n.a, "ledger.transaction", entity_id, description="Core version", amount=Decimal("42.00"))
    edit(n.b, entity_id, "Local version")
    n.sync(n.a, n.ta)
    n.sync(n.b, n.tb)
    entry = owner(n.b, entity_id)
    resolver_locked, publisher_waiting, allow_resolution = Event(), Event(), Event()
    def after_cursor(_conn, _cursor, statement, _parameters, _context, _many):
        if statement.startswith("UPDATE local_mutation_queue SET updated_at=local_mutation_queue.updated_at"):
            resolver_locked.set()
            assert publisher_waiting.wait(5)
            assert allow_resolution.wait(5)
    def before_cursor(_conn, _cursor, statement, _parameters, _context, _many):
        if statement.startswith("UPDATE local_sync_state SET updated_at=local_sync_state.updated_at"):
            publisher_waiting.set()
    def business_writer():
        with n.b.factory() as db:
            # Simulate authentication/other dependencies having cached business
            # data before the request reaches its shared write preparation.
            cached = db.get(LedgerTransaction, entity_id)
            assert str(cached.amount) == "38.00"
            assert resolver_locked.wait(5)
            prepare_write(db, db.get(User, n.b.user_id))
            item = db.get(LedgerTransaction, entity_id)
            assert str(item.amount) == "42.00" and item.sync_revision == 2
            item.description = "Edit after explicit Core decision"
            publish(db, item)
            db.commit()
    event.listen(n.b.engine, "after_cursor_execute", after_cursor)
    event.listen(n.b.engine, "before_cursor_execute", before_cursor)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            writer = pool.submit(business_writer)
            resolver = pool.submit(resolve, n.b, entry, "remote", 2)
            try:
                assert resolver_locked.wait(5) and publisher_waiting.wait(5)
                assert not writer.done()
            finally:
                allow_resolution.set()
            resolver.result(timeout=5)
            writer.result(timeout=5)
    finally:
        allow_resolution.set()
        event.remove(n.b.engine, "after_cursor_execute", after_cursor)
        event.remove(n.b.engine, "before_cursor_execute", before_cursor)
    pending = live(n.b, entity_id)
    assert len(pending) == 1 and pending[0].base_revision == 2
    assert pending[0].payload_json["amount"] == "42.00"
    assert pending[0].payload_json["description"] == "Edit after explicit Core decision"
