"""Two durable Local replicas and one Core authority, each with its own SQLite DB."""

from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import (Client, LedgerCategory, LedgerTransaction, LocalMutation,
                        LocalSyncState, SyncChange, SyncWorkspaceState, User, Workspace, utcnow)
from app.sync.engine import _freeze, run_sync_cycle
from app.sync.local import record_local_delete, record_local_upsert
from app.sync.remote import SyncRemoteError
from app.sync.service import (apply_mutation, ensure_core_sync_initialized,
                              get_changes, record_ordinary_change)


def replica(tmp_path, name, owner_id):
    engine = create_engine(f"sqlite:///{tmp_path / (name + '.db')}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    workspace_id = str(uuid4())
    with factory() as db:
        db.add(User(id=owner_id, username=name, email=f"{name}@example.test", password_hash="hash"))
        db.add(Workspace(id=workspace_id, owner_user_id=owner_id,
                         name="Personal", kind="personal"))
        db.commit()
    return SimpleNamespace(engine=engine, factory=factory, user_id=owner_id,
                           workspace_id=workspace_id)


class CoreTransport:
    def __init__(self, core, client_id):
        self.core = core
        self.client_id = client_id
        self.drop_once = False
        self.unauthorized = False
        self.sent = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass

    def push_mutation(self, mutation):
        if self.unauthorized:
            raise SyncRemoteError("unauthorized")
        self.sent.append(dict(mutation))
        with self.core.factory() as db:
            result = apply_mutation(db, db.get(Client, self.client_id), mutation)
        if self.drop_once:
            self.drop_once = False
            raise SyncRemoteError("timeout")
        return result

    def get_changes(self, cursor, limit):
        if self.unauthorized:
            raise SyncRemoteError("unauthorized")
        with self.core.factory() as db:
            ensure_core_sync_initialized(db, self.core.workspace_id)
            db.commit()
            return get_changes(db, self.core.workspace_id, cursor, limit)


@pytest.fixture
def network(tmp_path):
    core = replica(tmp_path, "core_owner", 33)
    a = replica(tmp_path, "local_a", 11)
    b = replica(tmp_path, "local_b", 22)
    transports = []
    with core.factory() as db:
        for index in range(2):
            client_id = str(uuid4())
            db.add(Client(id=client_id, workspace_id=core.workspace_id,
                          installation_id=str(uuid4()), name=f"Client {index}",
                          platform="windows", app_version="0.5.3"))
            transports.append(CoreTransport(core, client_id))
        db.commit()

    def metadata(transport):
        return SimpleNamespace(coreUrl="https://core.example", workspaceId=core.workspace_id,
                               clientId=transport.client_id)

    def sync(local, transport):
        return run_sync_cycle(local.factory, local.user_id, local.workspace_id,
                              metadata(transport), "nc_live_test", transport)

    yield SimpleNamespace(core=core, a=a, b=b, ta=transports[0], tb=transports[1],
                          sync=sync)
    for database in (a, b, core):
        database.engine.dispose()


def create_category(local, name="Food"):
    item_id = str(uuid4())
    with local.factory() as db:
        item = LedgerCategory(id=item_id, user_id=local.user_id,
                              workspace_id=local.workspace_id, name=name,
                              type="expense", icon="shopping", sync_revision=0)
        db.add(item)
        record_local_upsert(db, item)
        db.commit()
    return item_id


def create_transaction(local, category_id=None, description="Coffee", amount="38.00"):
    item_id = str(uuid4())
    with local.factory() as db:
        item = LedgerTransaction(id=item_id, user_id=local.user_id,
                                 workspace_id=local.workspace_id, category_id=category_id,
                                 type="expense", amount=Decimal(amount),
                                 description=description, merchant="", note="",
                                 occurred_at=utcnow(), sync_revision=0)
        db.add(item)
        record_local_upsert(db, item)
        db.commit()
    return item_id


def edit(local, item_id, description):
    with local.factory() as db:
        item = db.get(LedgerTransaction, item_id)
        item.description = description
        record_local_upsert(db, item)
        db.commit()


def delete(local, item_id):
    with local.factory() as db:
        item = db.get(LedgerTransaction, item_id)
        item.deleted_at = utcnow()
        record_local_delete(db, item)
        db.commit()


def queue(local, item_id):
    with local.factory() as db:
        return [(entry.mutation_id, entry.status, entry.base_revision,
                 entry.operation, entry.payload_json, entry.depends_on_mutation_id)
                for entry in db.scalars(select(LocalMutation).where(LocalMutation.entity_id == item_id)).all()]


def test_two_replicas_bidirectional_merge_and_delete(network):
    n = network
    assert len({n.a.workspace_id, n.b.workspace_id, n.core.workspace_id}) == 3
    category_id = create_category(n.a)
    coffee_id = create_transaction(n.a, category_id)
    assert n.sync(n.a, n.ta)["status"] == "ok"
    assert n.sync(n.b, n.tb)["status"] == "ok"
    with n.b.factory() as db:
        coffee = db.get(LedgerTransaction, coffee_id)
        assert coffee.workspace_id == n.b.workspace_id and coffee.user_id == n.b.user_id
        assert coffee.description == "Coffee" and coffee.category_id == category_id
        assert db.get(LedgerCategory, category_id).workspace_id == n.b.workspace_id
    edit(n.b, coffee_id, "Coffee 42")
    assert n.sync(n.b, n.tb)["status"] == "ok"
    assert n.sync(n.a, n.ta)["status"] == "ok"
    with n.a.factory() as db:
        assert db.get(LedgerTransaction, coffee_id).description == "Coffee 42"
    other_id = create_transaction(n.a, description="Other")
    assert n.sync(n.a, n.ta)["status"] == "ok"
    assert n.sync(n.b, n.tb)["status"] == "ok"
    edit(n.a, coffee_id, "A changed")
    edit(n.b, other_id, "B changed")
    assert n.sync(n.a, n.ta)["status"] == "ok"
    assert n.sync(n.b, n.tb)["status"] == "ok"
    assert n.sync(n.a, n.ta)["status"] == "ok"
    with n.a.factory() as db:
        assert db.get(LedgerTransaction, other_id).description == "B changed"
    with n.b.factory() as db:
        assert db.get(LedgerTransaction, coffee_id).description == "A changed"
    delete(n.a, coffee_id)
    assert n.sync(n.a, n.ta)["status"] == "ok"
    assert n.sync(n.b, n.tb)["status"] == "ok"
    with n.b.factory() as db:
        assert db.get(LedgerTransaction, coffee_id).deleted_at is not None
    assert queue(n.a, coffee_id) == []


def test_same_record_offline_conflict_preserves_local_edit(network):
    n = network
    item_id = create_transaction(n.a)
    n.sync(n.a, n.ta)
    n.sync(n.b, n.tb)
    edit(n.a, item_id, "A 40")
    edit(n.b, item_id, "B 42")
    assert n.sync(n.a, n.ta)["status"] == "ok"
    result = n.sync(n.b, n.tb)
    assert result["conflicts"] == 1 and result["pending"] == 0
    with n.b.factory() as db:
        item = db.get(LedgerTransaction, item_id)
        conflict = db.scalar(select(LocalMutation).where(LocalMutation.entity_id == item_id))
        assert item.description == "B 42" and item.sync_revision == 1
        assert conflict.status == "conflict"
        assert conflict.conflict_json["current"]["description"] == "A 40"
        assert conflict.conflict_json["currentRevision"] == 2


def test_frozen_conflict_keeps_editable_tail_blocked(network):
    n = network
    item_id = create_transaction(n.a)
    n.sync(n.a, n.ta)
    n.sync(n.b, n.tb)
    edit(n.a, item_id, "Attempt A")
    mutation_id = queue(n.a, item_id)[0][0]
    _freeze(n.a.factory, n.a.workspace_id, mutation_id)
    edit(n.a, item_id, "Later local edit")
    edit(n.b, item_id, "B wins")
    n.sync(n.b, n.tb)
    result = n.sync(n.a, n.ta)
    assert result["status"] == "ok" and result["conflicts"] == 1 and result["pending"] == 1
    entries = queue(n.a, item_id)
    assert {entry[1] for entry in entries} == {"conflict", "pending"}
    assert next(entry for entry in entries if entry[1] == "pending")[5] == mutation_id
    with n.a.factory() as db:
        assert db.get(LedgerTransaction, item_id).description == "Later local edit"


def conflicted_transaction(n):
    item_id = create_transaction(n.a)
    assert n.sync(n.a, n.ta)["status"] == "ok"
    assert n.sync(n.b, n.tb)["status"] == "ok"
    edit(n.b, item_id, "Local 42")
    edit(n.a, item_id, "Remote 40")
    assert n.sync(n.a, n.ta)["status"] == "ok"
    assert n.sync(n.b, n.tb)["conflicts"] == 1
    return item_id


def test_conflict_snapshot_tracks_successive_remote_revisions(network):
    n = network
    item_id = conflicted_transaction(n)
    original = queue(n.b, item_id)
    for revision, description in ((3, "Remote 43"), (4, "Remote 45")):
        edit(n.a, item_id, description)
        assert n.sync(n.a, n.ta)["status"] == "ok"
        assert n.sync(n.b, n.tb)["cursor"] == revision
        with n.b.factory() as db:
            item = db.get(LedgerTransaction, item_id)
            conflict = db.scalar(select(LocalMutation).where(LocalMutation.entity_id == item_id))
            assert item.description == "Local 42" and item.sync_revision == 1
            assert item.deleted_at is None
            assert conflict.status == "conflict" and conflict.result_revision == revision
            assert conflict.conflict_json["currentRevision"] == revision
            assert conflict.conflict_json["current"]["description"] == description
            assert conflict.conflict_json["deleted"] is False
        assert queue(n.b, item_id) == original


def test_conflict_snapshot_tracks_remote_delete_and_restore(network):
    n = network
    item_id = conflicted_transaction(n)
    delete(n.a, item_id)
    assert n.sync(n.a, n.ta)["status"] == "ok"
    assert n.sync(n.b, n.tb)["cursor"] == 3
    with n.b.factory() as db:
        conflict = db.scalar(select(LocalMutation).where(LocalMutation.entity_id == item_id))
        assert conflict.result_revision == 3
        assert {key: value for key, value in conflict.conflict_json.items() if key != "detectedAt"} == {
            "currentRevision": 3, "current": None, "deleted": True}
        assert conflict.conflict_json["detectedAt"]
        item = db.get(LedgerTransaction, item_id)
        assert item.description == "Local 42" and item.sync_revision == 1
        assert item.deleted_at is None
    with n.a.factory() as db:
        item = db.get(LedgerTransaction, item_id)
        item.deleted_at = None
        item.description = "Remote restored"
        record_local_upsert(db, item)
        db.commit()
    assert n.sync(n.a, n.ta)["status"] == "ok"
    assert n.sync(n.b, n.tb)["cursor"] == 4
    with n.b.factory() as db:
        conflict = db.scalar(select(LocalMutation).where(LocalMutation.entity_id == item_id))
        assert conflict.result_revision == 4 and conflict.conflict_json["currentRevision"] == 4
        assert conflict.conflict_json["deleted"] is False
        assert conflict.conflict_json["current"]["description"] == "Remote restored"
        item = db.get(LedgerTransaction, item_id)
        assert item.description == "Local 42" and item.sync_revision == 1
        assert item.deleted_at is None


def test_conflict_snapshot_does_not_regress_while_catching_up(network, monkeypatch):
    from app.sync import engine

    n = network
    item_id = create_transaction(n.a)
    n.sync(n.a, n.ta)
    n.sync(n.b, n.tb)
    edit(n.b, item_id, "Local 42")
    _freeze(n.b.factory, n.b.workspace_id, queue(n.b, item_id)[0][0])
    for description in ("Remote first", "Remote latest"):
        edit(n.a, item_id, description)
        n.sync(n.a, n.ta)
    original_apply = engine._apply_change

    def stop_before_latest(factory, user_id, workspace_id, change):
        if change["revision"] == 3:
            raise SyncRemoteError("unreachable")
        return original_apply(factory, user_id, workspace_id, change)

    monkeypatch.setattr(engine, "_apply_change", stop_before_latest)
    # Retry receives conflict revision 3 before pull processes older revision 2.
    result = n.sync(n.b, n.tb)
    assert result["status"] == "error" and result["cursor"] == 2
    with n.b.factory() as db:
        entry = db.scalar(select(LocalMutation).where(LocalMutation.entity_id == item_id))
        assert entry.result_revision == 3 and entry.conflict_json["currentRevision"] == 3
        assert entry.conflict_json["current"]["description"] == "Remote latest"
        item = db.get(LedgerTransaction, item_id)
        assert item.description == "Local 42" and item.sync_revision == 1
    monkeypatch.setattr(engine, "_apply_change", original_apply)
    assert n.sync(n.b, n.tb)["cursor"] == 3


def test_conflict_refresh_preserves_frozen_request_and_pending_tail(network):
    n = network
    item_id = create_transaction(n.a)
    n.sync(n.a, n.ta)
    n.sync(n.b, n.tb)
    edit(n.b, item_id, "Frozen attempt")
    mutation_id = queue(n.b, item_id)[0][0]
    _freeze(n.b.factory, n.b.workspace_id, mutation_id)
    edit(n.b, item_id, "Editable tail")
    edit(n.a, item_id, "Remote first")
    n.sync(n.a, n.ta)
    assert n.sync(n.b, n.tb)["conflicts"] == 1
    original = queue(n.b, item_id)
    for revision, description in ((3, "Remote latest"), (4, None)):
        if description is None:
            delete(n.a, item_id)
        else:
            edit(n.a, item_id, description)
        n.sync(n.a, n.ta)
        result = n.sync(n.b, n.tb)
        assert result["cursor"] == revision and result["conflicts"] == 1 and result["pending"] == 1
        assert queue(n.b, item_id) == original
        with n.b.factory() as db:
            conflict = db.scalar(select(LocalMutation).where(LocalMutation.mutation_id == mutation_id))
            assert conflict.result_revision == revision
            assert conflict.conflict_json["currentRevision"] == revision
            assert conflict.conflict_json["deleted"] == (description is None)
            current = conflict.conflict_json["current"]
            assert current is None if description is None else current["description"] == description
            item = db.get(LedgerTransaction, item_id)
            assert item.description == "Editable tail" and item.sync_revision == 1
            assert item.deleted_at is None


def test_response_lost_freeze_tail_retry_and_idempotency(network):
    n = network
    item_id = create_transaction(n.a)
    n.ta.drop_once = True
    first = n.sync(n.a, n.ta)
    assert first["status"] == "error" and first["inFlight"] == 1
    with n.a.factory() as db:
        assert db.scalar(select(LocalMutation).where(LocalMutation.entity_id == item_id)).last_error == "timeout"
    frozen = queue(n.a, item_id)[0]
    assert frozen[1:4] == ("in_flight", 0, "upsert")
    with n.core.factory() as db:
        assert db.get(SyncWorkspaceState, n.core.workspace_id).current_revision == 1
    edit(n.a, item_id, "Coffee 42")
    entries = queue(n.a, item_id)
    assert len(entries) == 2 and entries[0] == frozen
    assert entries[1][1] == "pending" and entries[1][5] == frozen[0]
    assert n.sync(n.a, n.ta)["status"] == "ok"
    assert n.ta.sent[0] == n.ta.sent[1]
    with n.core.factory() as db:
        assert db.get(SyncWorkspaceState, n.core.workspace_id).current_revision == 2
        assert db.query(SyncChange).count() == 2
        assert db.get(LedgerTransaction, item_id).description == "Coffee 42"
    assert queue(n.a, item_id) == []


def test_delete_after_lost_create_retains_frozen_mutation(network):
    n = network
    item_id = create_transaction(n.a)
    n.ta.drop_once = True
    n.sync(n.a, n.ta)
    frozen = queue(n.a, item_id)[0]
    delete(n.a, item_id)
    entries = queue(n.a, item_id)
    assert len(entries) == 2 and entries[0] == frozen
    assert entries[1][3] == "delete" and entries[1][5] == frozen[0]
    assert n.sync(n.a, n.ta)["status"] == "ok"
    with n.core.factory() as db:
        assert db.get(SyncWorkspaceState, n.core.workspace_id).current_revision == 2
        assert db.get(LedgerTransaction, item_id).deleted_at is not None


def test_tail_inserted_after_ack_is_rebased(network):
    n = network
    item_id = create_transaction(n.a)
    old_mutation_id = queue(n.a, item_id)[0][0]
    assert n.sync(n.a, n.ta)["status"] == "ok"
    edit(n.a, item_id, "Late edit")
    with n.a.factory() as db:
        tail = db.scalar(select(LocalMutation).where(LocalMutation.entity_id == item_id))
        tail.depends_on_mutation_id = old_mutation_id
        tail.base_revision = 0
        db.commit()
    assert n.sync(n.a, n.ta)["status"] == "ok"
    assert queue(n.a, item_id) == []
    with n.core.factory() as db:
        assert db.get(LedgerTransaction, item_id).description == "Late edit"


def test_one_sync_cycle_per_local_workspace(network):
    n = network
    original = n.ta.get_changes

    def nested(cursor, limit):
        metadata = SimpleNamespace(coreUrl="https://core.example", workspaceId=n.core.workspace_id,
                                   clientId=n.ta.client_id)
        with pytest.raises(HTTPException) as error:
            run_sync_cycle(n.a.factory, n.a.user_id, n.a.workspace_id,
                           metadata, "nc_live_test", n.ta)
        assert error.value.status_code == 409
        return original(cursor, limit)

    n.ta.get_changes = nested
    assert n.sync(n.a, n.ta)["status"] == "ok"


def test_revoked_credential_and_offline_queue_survive(network):
    n = network
    item_id = create_transaction(n.a)
    n.ta.unauthorized = True
    result = n.sync(n.a, n.ta)
    assert result["status"] == "error" and result["lastError"] == "unauthorized"
    assert queue(n.a, item_id)[0][1] == "pending"
    n.a.engine.dispose()  # A new engine/session represents a Desktop restart.
    n.ta.unauthorized = False
    assert n.sync(n.a, n.ta)["status"] == "ok"
    with n.core.factory() as db:
        assert db.get(LedgerTransaction, item_id) is not None


def test_core_ordinary_write_and_legacy_bootstrap(network):
    n = network
    core_legacy_id, local_legacy_id = str(uuid4()), str(uuid4())
    with n.core.factory() as db:
        db.add(LedgerCategory(id=core_legacy_id, user_id=n.core.user_id,
                              workspace_id=n.core.workspace_id, name="Core legacy",
                              type="expense", icon="shopping", sync_revision=0))
        db.commit()
    with n.a.factory() as db:
        db.add(LedgerCategory(id=local_legacy_id, user_id=n.a.user_id,
                              workspace_id=n.a.workspace_id, name="Local legacy",
                              type="expense", icon="shopping", sync_revision=0))
        db.commit()
    assert n.sync(n.a, n.ta)["status"] == "ok"
    assert n.sync(n.b, n.tb)["status"] == "ok"
    with n.b.factory() as db:
        assert db.get(LedgerCategory, core_legacy_id).name == "Core legacy"
        assert db.get(LedgerCategory, local_legacy_id).name == "Local legacy"
    with n.core.factory() as db:
        category = db.get(LedgerCategory, core_legacy_id)
        category.name = "Core ordinary edit"
        record_ordinary_change(db, category, "upsert")
        db.commit()
    assert n.sync(n.a, n.ta)["status"] == "ok"
    with n.a.factory() as db:
        assert db.get(LedgerCategory, core_legacy_id).name == "Core ordinary edit"


def test_bootstrap_same_id_different_data_conflicts(network):
    n = network
    shared_id = str(uuid4())
    with n.core.factory() as db:
        db.add(LedgerCategory(id=shared_id, user_id=n.core.user_id,
                              workspace_id=n.core.workspace_id, name="Core name",
                              type="expense", icon="shopping", sync_revision=0))
        db.commit()
    with n.a.factory() as db:
        db.add(LedgerCategory(id=shared_id, user_id=n.a.user_id,
                              workspace_id=n.a.workspace_id, name="Local name",
                              type="expense", icon="shopping", sync_revision=0))
        db.commit()
    result = n.sync(n.a, n.ta)
    assert result["conflicts"] == 1
    with n.a.factory() as db:
        assert db.get(LedgerCategory, shared_id).name == "Local name"
        assert db.get(LedgerCategory, shared_id).sync_revision == 0


def test_rejected_and_missing_category_stop_cursor(network):
    n = network
    item_id = create_transaction(n.a)
    with n.a.factory() as db:
        entry = db.scalar(select(LocalMutation).where(LocalMutation.entity_id == item_id))
        entry.payload_json = {**entry.payload_json, "amount": 38.0}
        db.commit()
    result = n.sync(n.a, n.ta)
    assert result["status"] == "ok" and result["rejected"] == 1
    assert queue(n.a, item_id)[0][1] == "rejected"
    missing_category_id = str(uuid4())
    with n.core.factory() as db:
        item = LedgerTransaction(id=str(uuid4()), user_id=n.core.user_id,
                                 workspace_id=n.core.workspace_id,
                                 category_id=missing_category_id, type="expense",
                                 amount=Decimal("5.00"), description="Broken history",
                                 merchant="", note="", occurred_at=utcnow(), sync_revision=0)
        db.add(item)
        record_ordinary_change(db, item, "upsert")
        db.commit()
    before = result["cursor"]
    failed = n.sync(n.a, n.ta)
    assert failed["status"] == "error" and failed["lastError"] == "missing_category"
    assert failed["cursor"] == before


def test_manual_sync_api_status_and_secret_boundary(client, users, network, monkeypatch):
    from app import core_connection
    from app.sync import engine

    auth, _ = users
    n = network
    metadata = SimpleNamespace(coreUrl="https://core.example", workspaceId=n.core.workspace_id,
                               clientId=n.ta.client_id)
    monkeypatch.setattr(core_connection, "load_connection", lambda _user_id: metadata)
    monkeypatch.setattr(core_connection.credential_store, "load", lambda _user_id: "nc_live_test_secret")
    monkeypatch.setattr(engine, "SyncRemoteClient", lambda _url, _credential: n.ta)
    created = client.post("/api/v1/ledger/transactions", headers=auth, json={
        "category_id": None, "type": "expense", "amount": "38.00",
        "description": "API Coffee", "occurred_at": "2026-09-28T12:00:00Z"})
    assert created.status_code == 201, created.text
    result = client.post("/api/v1/sync/run", headers=auth)
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "ok" and result.json()["pushed"] == 1
    status = client.get("/api/v1/sync/status", headers=auth).json()
    assert status["pending"] == status["inFlight"] == 0
    assert status["cursor"] == 1 and status["lastSuccessAt"] is not None
    assert "nc_live_" not in str(status) and "nc_live_" not in result.text
    assert not {"workspaceId", "userId", "clientId"} & set(n.ta.sent[0])
    with n.core.factory() as db:
        assert db.get(LedgerTransaction, created.json()["id"]).workspace_id == n.core.workspace_id
