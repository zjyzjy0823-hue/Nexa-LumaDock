"""All adapters share the proven engine with independent ownership on each replica."""
from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models import (WebsiteCategory, Website, DataCollection, DataRecord,
                        LocalMutation, LocalSyncState, SyncChange, SyncWorkspaceState, utcnow)
from app.sync.adapters import REGISTRY, get_adapter
from app.sync.engine import _apply_change, _freeze
from app.sync.local import record_local_upsert, record_local_delete, seed_local_queue
from app.sync.remote import SyncRemoteError
from app.sync.service import apply_mutation, ensure_core_sync_initialized, record_ordinary_change
from app.sync import publisher
from app.api import websites
from app.api.data import routes as data_routes
from app.runtime_mode import require_core_mode
from app.main import app
from test_sync_engine import network, queue
from test_sync import user, enroll, db_session, ROOT


def create(local, entity_type, parent_id=None, name="First"):
    adapter = get_adapter(entity_type)
    item_id = str(uuid4())
    fields = dict(name=name, sync_revision=0)
    if entity_type == "website.category":
        fields.update(order=2)
    elif entity_type == "website":
        fields.update(category_id=parent_id, url="https://example.com", favorite=True,
                      order=3, created_at=utcnow(), updated_at=utcnow())
    elif entity_type == "data.collection":
        fields.update(description="Collection", icon="custom", tone="blue")
    else:
        fields.update(collection_id=parent_id, status="active", category="test", data_json={"value": 42})
    if entity_type != "data.record":
        fields.update(user_id=local.user_id, workspace_id=local.workspace_id)
    with local.factory() as db:
        item = adapter.model(id=item_id, **fields)
        db.add(item)
        db.flush()
        record_local_upsert(db, item)
        db.commit()
    return item_id


def edit(local, entity_type, item_id, **fields):
    with local.factory() as db:
        item = db.get(get_adapter(entity_type).model, item_id)
        for key, value in fields.items():
            setattr(item, key, value)
        db.flush()
        record_local_upsert(db, item)
        db.commit()


def delete(local, entity_type, item_id):
    with local.factory() as db:
        item = db.get(get_adapter(entity_type).model, item_id)
        item.deleted_at = utcnow()
        record_local_delete(db, item)
        db.commit()


def test_registry_contract():
    assert set(REGISTRY) == {"ledger.category", "ledger.transaction", "website.category", "website",
                             "data.collection", "data.record", "user.preferences", "dashboard.layout", "automation.definition"}
    for parent, child in (("ledger.category", "ledger.transaction"),
                          ("website.category", "website"), ("data.collection", "data.record")):
        assert get_adapter(parent).push_priority("upsert") < get_adapter(child).push_priority("upsert")
        assert get_adapter(child).push_priority("delete") < get_adapter(parent).push_priority("delete")
    for unknown in ("invalid", None, [], {}):
        with pytest.raises(SyncRemoteError, match="unknown_entity_type"):
            get_adapter(unknown)


@pytest.mark.parametrize("parent_type,child_type", [("website.category", "website"),
                                                     ("data.collection", "data.record")])
def test_offline_bidirectional_merge_and_cascade(network, parent_type, child_type):
    n = network
    parent_id = create(n.a, parent_type)
    item_id = create(n.a, child_type, parent_id)
    assert n.sync(n.a, n.ta)["pushed"] == 2
    assert [row["entityType"] for row in n.ta.sent] == [parent_type, child_type]
    assert n.sync(n.b, n.tb)["status"] == "ok"
    for local in (n.a, n.b, n.core):
        with local.factory() as db:
            adapter = get_adapter(child_type)
            item = db.get(adapter.model, item_id)
            assert adapter.workspace_id(db, item) == local.workspace_id
            assert db.get(get_adapter(parent_type).model, parent_id).user_id == local.user_id
            assert "userId" not in adapter.serialize(item) and "workspaceId" not in adapter.serialize(item)
    changes = {"name": "B edited"}
    changes.update(favorite=False, order=9, last_visited_at=utcnow()) if child_type == "website" else changes.update(data_json={"edited": True}, status="done")
    edit(n.b, child_type, item_id, **changes)
    assert n.sync(n.b, n.tb)["status"] == "ok"
    assert n.sync(n.a, n.ta)["status"] == "ok"
    with n.a.factory() as db:
        row = db.get(get_adapter(child_type).model, item_id)
        assert row.name == "B edited"
        if child_type == "website":
            assert row.favorite is False and row.order == 9 and row.last_visited_at is not None
        else:
            assert row.data_json == {"edited": True} and row.status == "done"
    second_id = create(n.a, child_type, parent_id, "Second")
    n.sync(n.a, n.ta); n.sync(n.b, n.tb)
    edit(n.a, child_type, item_id, name="A independent")
    edit(n.b, child_type, second_id, name="B independent")
    n.sync(n.a, n.ta); n.sync(n.b, n.tb); n.sync(n.a, n.ta)
    with n.a.factory() as db:
        assert db.get(get_adapter(child_type).model, second_id).name == "B independent"
    delete(n.a, child_type, second_id)
    n.sync(n.a, n.ta); n.sync(n.b, n.tb)
    delete(n.a, parent_type, parent_id)
    assert n.sync(n.a, n.ta)["status"] == "ok"
    assert n.sync(n.b, n.tb)["status"] == "ok"
    for local in (n.a, n.b, n.core):
        with local.factory() as db:
            assert db.get(get_adapter(parent_type).model, parent_id).deleted_at is not None
            row = db.get(get_adapter(child_type).model, item_id)
            if child_type == "website":
                assert row.deleted_at is None and row.category_id is None
            else:
                assert row.deleted_at is not None


@pytest.mark.parametrize("entity_type", ["website.category", "website", "data.collection", "data.record"])
def test_generic_conflict_latest_snapshot_and_response_loss(network, entity_type):
    n = network
    parent_id = create(n.a, "data.collection") if entity_type == "data.record" else None
    item_id = create(n.a, entity_type, parent_id)
    n.ta.drop_once = True
    assert n.sync(n.a, n.ta)["lastError"] == "timeout"
    frozen = n.ta.sent[-1]
    assert n.sync(n.a, n.ta)["status"] == "ok"
    assert n.ta.sent[1] == frozen
    with n.core.factory() as db:
        assert len(db.scalars(select(SyncChange).where(SyncChange.entity_id == frozen["entityId"])).all()) == 1
    n.sync(n.b, n.tb)
    edit(n.a, entity_type, item_id, name="A wins")
    edit(n.b, entity_type, item_id, name="B preserved")
    n.sync(n.a, n.ta)
    assert n.sync(n.b, n.tb)["conflicts"] == 1
    edit(n.a, entity_type, item_id, name="A latest")
    n.sync(n.a, n.ta); n.sync(n.b, n.tb)
    with n.b.factory() as db:
        assert db.get(get_adapter(entity_type).model, item_id).name == "B preserved"
        entry = db.scalar(select(LocalMutation).where(LocalMutation.entity_id == item_id))
        assert entry.conflict_json["current"]["name"] == "A latest"
    delete(n.a, entity_type, item_id)
    n.sync(n.a, n.ta); n.sync(n.b, n.tb)
    with n.b.factory() as db:
        entry = db.scalar(select(LocalMutation).where(LocalMutation.entity_id == item_id))
        assert entry.conflict_json["current"] is None and entry.conflict_json["deleted"]


def test_protocol_mismatch_preserves_frozen_queue_and_cursor(network):
    n = network
    item_id = create(n.a, "website")
    mid = queue(n.a, item_id)[0][0]
    _freeze(n.a.factory, n.a.workspace_id, mid)
    before = queue(n.a, item_id)
    n.ta.get_changes = lambda cursor, limit: {"protocolVersion": 1}
    result = n.sync(n.a, n.ta)
    assert result["lastError"] == "protocol_mismatch" and result["cursor"] == 0
    assert queue(n.a, item_id) == before and n.ta.sent == []


def test_missing_dependency_does_not_advance_cursor(network):
    n = network
    with pytest.raises(SyncRemoteError, match="collection_not_found"):
        _apply_change(n.b.factory, n.b.user_id, n.b.workspace_id, dict(revision=1,
            entityType="data.record", entityId=str(uuid4()), operation="upsert",
            data={"collectionId": str(uuid4()), "name": "Missing"}))
    with n.b.factory() as db:
        state = db.get(LocalSyncState, n.b.workspace_id)
        assert state is None or state.cursor == 0


@pytest.mark.parametrize("child_type", ["website", "data.record"])
def test_lost_response_frozen_payload_and_editable_tail(network, child_type):
    n = network
    parent_id = create(n.a, "data.collection") if child_type == "data.record" else None
    n.sync(n.a, n.ta)
    item_id = create(n.a, child_type, parent_id)
    n.ta.drop_once = True
    assert n.sync(n.a, n.ta)["lastError"] == "timeout"
    frozen = n.ta.sent[-1]
    edit(n.a, child_type, item_id, name="Tail edit")
    assert len(queue(n.a, item_id)) == 2
    assert n.sync(n.a, n.ta)["pending"] == 0
    assert n.ta.sent[-2] == frozen and n.ta.sent[-1]["data"]["name"] == "Tail edit"
    assert n.ta.sent[-1]["baseRevision"] > frozen["baseRevision"]
    n.sync(n.b, n.tb)
    with n.b.factory() as db:
        assert db.get(get_adapter(child_type).model, item_id).name == "Tail edit"
    with n.core.factory() as db:
        assert len(db.scalars(select(SyncChange).where(SyncChange.entity_id == item_id)).all()) == 2


@pytest.mark.parametrize("parent_type,child_type", [("website.category", "website"),
                                                    ("data.collection", "data.record")])
def test_adapter_dependencies_and_ownership_payload_rejection(network, parent_type, child_type):
    n = network
    parent_id = create(n.a, parent_type)
    child_id = create(n.a, child_type, parent_id)
    n.sync(n.a, n.ta)
    with n.core.factory() as db:
        adapter = get_adapter(child_type)
        item = db.get(adapter.model, child_id)
        payload = adapter.serialize(item)
        parent = db.get(get_adapter(parent_type).model, parent_id)
        data = adapter.schema.model_validate(payload)
        assert adapter.dependency_error(db, n.core.workspace_id, data) is None
        assert adapter.dependency_error(db, n.a.workspace_id, data) in ("category_not_found", "collection_not_found")
        parent.deleted_at = utcnow()
        assert adapter.dependency_error(db, n.core.workspace_id, data) in ("category_not_found", "collection_not_found")
        db.rollback()
        from app.models import Client
        payload.update(userId=n.a.user_id, workspaceId=n.a.workspace_id)
        result = apply_mutation(db, db.get(Client, n.ta.client_id), dict(mutationId=str(uuid4()),
            entityType=child_type, entityId=str(uuid4()), operation="upsert", baseRevision=0, data=payload))
        assert result["status"] == "rejected" and result["reason"] == "invalid_data"


def test_untrusted_conflict_payload_cannot_enter_diagnostics(network):
    n = network
    item_id = create(n.b, "website.category")
    with pytest.raises(SyncRemoteError, match="invalid_response"):
        _apply_change(n.b.factory, n.b.user_id, n.b.workspace_id, dict(revision=1,
            entityType="website.category", entityId=item_id, operation="upsert",
            data={"name": "Remote", "Authorization": "nc_live_secret"}))
    assert queue(n.b, item_id)[0][1] == "pending"


def test_ledger_authoritative_update_keeps_historical_deleted_category(network):
    from test_sync_engine import create_category, create_transaction
    from app.models import LedgerCategory, LedgerTransaction
    n = network
    parent_id = create_category(n.a)
    item_id = create_transaction(n.a, parent_id)
    n.sync(n.a, n.ta); n.sync(n.b, n.tb)
    with n.core.factory() as db:
        parent = db.get(LedgerCategory, parent_id)
        parent.deleted_at = utcnow()
        record_ordinary_change(db, parent, "delete")
        item = db.get(LedgerTransaction, item_id)
        item.description = "Historical edit"
        record_ordinary_change(db, item, "upsert")
        db.commit()
    assert n.sync(n.b, n.tb)["status"] == "ok"
    with n.b.factory() as db:
        assert db.get(LedgerTransaction, item_id).category_id == parent_id
        assert db.get(LedgerTransaction, item_id).description == "Historical edit"
        assert db.get(LedgerCategory, parent_id).deleted_at is not None
    # Preserve the prior queue behavior too: Core explicitly rejects the write,
    # rather than leaving a historical transaction pending indefinitely.
    edit(n.b, "ledger.transaction", item_id, description="Local historical edit")
    assert n.sync(n.b, n.tb)["rejected"] == 1
    with n.b.factory() as db:
        entry = db.scalar(select(LocalMutation).where(LocalMutation.entity_id == item_id))
        assert entry.last_error == "category_not_found"


@pytest.mark.parametrize("mode", ["local", "core"])
def test_ordinary_api_publication_and_tombstone_reads(client, monkeypatch, mode):
    monkeypatch.setattr(publisher, "runtime_config", replace(publisher.runtime_config, mode=mode))
    app.dependency_overrides[require_core_mode] = lambda: None
    auth = user(client, "multi_ordinary")
    credential = enroll(client, auth)
    category = client.post("/api/v1/website-categories", headers=auth, json={"name": "Sites"}).json()
    site = client.post("/api/v1/websites", headers=auth, json={"name": "Site", "url": "https://example.com", "categoryId": category["id"]}).json()
    assert client.post(f"/api/v1/websites/{site['id']}/visit", headers=auth).status_code == 200
    assert client.delete(f"/api/v1/website-categories/{category['id']}", headers=auth).status_code == 204
    assert client.get(f"/api/v1/websites/{site['id']}", headers=auth).json()["categoryId"] is None
    assert client.get("/api/v1/website-categories", headers=auth).json() == []
    collection = client.post("/api/v1/data/collections", headers=auth, json={"name": "Data"}).json()
    record = client.post(f"/api/v1/data/collections/{collection['id']}/records", headers=auth, json={"name": "Row"}).json()
    assert client.delete(f"/api/v1/data/records/{record['id']}", headers=auth).status_code == 204
    assert client.get(f"/api/v1/data/collections/{collection['id']}", headers=auth).json()["recordCount"] == 0
    assert client.get("/api/data", headers=auth).json()["totalRecords"] == 0
    client.post(f"/api/v1/data/collections/{collection['id']}/records", headers=auth, json={"name": "Cascade"})
    assert client.delete(f"/api/v1/data/collections/{collection['id']}", headers=auth).status_code == 204
    assert client.get("/api/v1/data/collections", headers=auth).json() == []
    assert client.get("/api/data", headers=auth).json()["totalCollections"] == 0
    assert client.delete(f"/api/v1/websites/{site['id']}", headers=auth).status_code == 204
    assert client.get("/api/v1/websites", headers=auth).json() == []
    if mode == "core":
        feed = client.get(ROOT + "/changes?protocolVersion=3", headers=credential).json()
        assert {row["entityType"] for row in feed["changes"]} == {"website.category", "website", "data.collection", "data.record"}
        assert len(feed["changes"]) == 12
        assert [row["revision"] for row in feed["changes"]] == list(range(1, 13))
    else:
        iterator, db = db_session()
        try:
            assert db.query(SyncChange).count() == 0
            assert db.get(Website, site["id"]).deleted_at is not None
            assert db.get(DataRecord, record["id"]).deleted_at is not None
        finally:
            iterator.close()


def test_old_client_is_rejected_before_core_bootstrap(client):
    app.dependency_overrides[require_core_mode] = lambda: None
    credential = enroll(client, user(client, "old_sync"))
    for params in ({}, {"protocolVersion": 1}):
        response = client.get(ROOT + "/changes", headers=credential, params=params)
        assert response.status_code == 409 and response.json()["detail"] == "sync_protocol_mismatch"
    response = client.post(ROOT + "/mutations", headers=credential, json={"protocolVersion": 1, "mutations": [{}]})
    assert response.status_code == 409
    iterator, db = db_session()
    try:
        assert db.query(SyncChange).count() == 0 and db.query(SyncWorkspaceState).count() == 0
    finally:
        iterator.close()


def test_core_ordinary_child_write_adopts_legacy_parent_before_history(client, monkeypatch):
    monkeypatch.setattr(publisher, "runtime_config", replace(publisher.runtime_config, mode="core"))
    app.dependency_overrides[require_core_mode] = lambda: None
    auth = user(client, "legacy_child_write")
    credential = enroll(client, auth)
    workspace_id = client.get("/api/v1/workspace", headers=auth).json()["id"]
    category_id, collection_id = str(uuid4()), str(uuid4())
    iterator, db = db_session()
    try:
        from app.models import Workspace
        owner = db.get(Workspace, workspace_id).owner_user_id
        db.add(SyncWorkspaceState(workspace_id=workspace_id, current_revision=0,
                                  initialized_at=utcnow(), bootstrap_version=1))
        db.add(WebsiteCategory(id=category_id, user_id=owner, workspace_id=workspace_id,
                               name="Legacy", order=0, sync_revision=0))
        db.add(DataCollection(id=collection_id, user_id=owner, workspace_id=workspace_id,
                              name="Legacy", sync_revision=0))
        db.commit()
    finally:
        iterator.close()
    assert client.post("/api/v1/websites", headers=auth, json={"name": "Child",
        "url": "https://example.com", "categoryId": category_id}).status_code == 201
    assert client.post(f"/api/v1/data/collections/{collection_id}/records", headers=auth,
                       json={"name": "Child"}).status_code == 201
    feed = client.get(ROOT + "/changes?protocolVersion=3", headers=credential).json()
    assert [row["entityType"] for row in feed["changes"]] == [
        "website.category", "data.collection", "website", "data.record"]
