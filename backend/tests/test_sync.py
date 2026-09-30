from dataclasses import replace
from uuid import uuid4

from sqlalchemy import select

from app.api import ledger
from app.database import get_db
from app.main import app
from app.models import LedgerCategory, LedgerTransaction, SyncChange, SyncMutation, SyncWorkspaceState, Workspace, utcnow
from app.runtime_mode import require_core_mode


ROOT = "/api/v1/sync"


def user(client, name):
    response = client.post("/api/v1/auth/register", json={"username": name, "password": "password123"})
    assert response.status_code == 201, response.text
    return {"Authorization": "Bearer " + response.json()["access_token"]}


def enroll(client, auth):
    response = client.post("/api/v1/clients/enroll", headers=auth, json={
        "installationId": str(uuid4()), "name": "Test client", "platform": "linux", "appVersion": "0.5.3"})
    assert response.status_code == 201, response.text
    return {"Authorization": "Bearer " + response.json()["credential"]}


def mutation(entity_type="ledger.transaction", entity_id=None, base=0, operation="upsert", data=None, mid=None):
    if data is None and operation == "upsert":
        data = {"categoryId": None, "type": "expense", "amount": "38.00", "description": "Coffee",
                "merchant": "", "note": "", "occurredAt": "2026-09-28T12:00:00Z"}
    return {"mutationId": mid or str(uuid4()), "entityType": entity_type,
            "entityId": entity_id or str(uuid4()), "operation": operation,
            "baseRevision": base, "data": data}


def push(client, auth, *mutations):
    response = client.post(f"{ROOT}/mutations", headers=auth,
                           json={"protocolVersion": 2, "mutations": list(mutations)})
    assert response.status_code == 200, response.text
    return response.json()["results"]


def db_session():
    iterator = app.dependency_overrides[get_db]()
    return iterator, next(iterator)


def test_core_only_and_credentials(client):
    assert client.get(f"{ROOT}/changes?protocolVersion=2", headers={"Authorization": "Bearer nc_live_fake"}).status_code == 404
    assert client.post(f"{ROOT}/mutations", headers={"Authorization": "Bearer nc_live_fake"},
                       json={"mutations": [mutation()]}).status_code == 404
    app.dependency_overrides[require_core_mode] = lambda: None
    auth = user(client, "sync_auth")
    for headers in (auth, {"Authorization": "Bearer sk_live_fake"},
                    {"Authorization": "Bearer nd_live_fake"},
                    {"Authorization": "Bearer na_live_fake"}):
        assert client.get(f"{ROOT}/changes?protocolVersion=2", headers=headers).status_code == 401
    credential = enroll(client, auth)
    assert client.get(f"{ROOT}/changes?protocolVersion=2", headers=credential).json() == {
        "protocolVersion": 2, "changes": [], "cursor": 0, "hasMore": False, "workspaceRevision": 0}
    assert client.get(f"{ROOT}/changes?protocolVersion=2&cursor=1", headers=credential).status_code == 400
    assert client.get(f"{ROOT}/changes?protocolVersion=2&cursor=-1", headers=credential).status_code == 422
    assert client.post(f"{ROOT}/mutations", headers=credential, json={"mutations": []}).status_code == 422


def test_create_retry_conflict_delete_and_changes(client):
    app.dependency_overrides[require_core_mode] = lambda: None
    user_auth = user(client, "sync_owner")
    a, b = enroll(client, user_auth), enroll(client, user_auth)
    created = mutation()
    first = push(client, a, created)[0]
    assert first["status"] == "applied" and first["revision"] == 1
    assert push(client, a, created)[0] == first
    assert push(client, b, created)[0]["status"] == "conflict"
    iterator, db = db_session()
    try:
        item = db.get(LedgerTransaction, created["entityId"])
        assert item.sync_revision == 1 and item.workspace_id
        assert db.query(SyncChange).count() == 1
        assert db.query(SyncMutation).count() == 2
        assert db.get(SyncWorkspaceState, item.workspace_id).current_revision == 1
    finally:
        iterator.close()

    update = mutation(entity_id=created["entityId"], base=1)
    update["data"]["description"] = "Tea"
    assert push(client, a, update)[0]["revision"] == 2
    stale = mutation(entity_id=created["entityId"], base=1)
    conflict = push(client, b, stale)[0]
    assert conflict["status"] == "conflict" and conflict["currentRevision"] == 2
    assert conflict["current"]["description"] == "Tea"
    assert "workspaceId" not in str(conflict) and "userId" not in str(conflict)
    deletion = mutation(entity_id=created["entityId"], base=2, operation="delete")
    assert push(client, a, deletion)[0]["revision"] == 3
    assert push(client, a, deletion)[0]["revision"] == 3
    assert client.get(f"/api/v1/ledger/transactions/{created['entityId']}", headers=user_auth).status_code == 404
    assert client.get("/api/v1/ledger/transactions", headers=user_auth).json() == []
    tombstone = push(client, b, mutation(entity_id=created["entityId"], base=2, operation="delete"))[0]
    assert tombstone["status"] == "conflict" and tombstone["currentRevision"] == 3
    assert tombstone["current"] is None and tombstone["deleted"] is True
    changes = client.get(f"{ROOT}/changes?protocolVersion=2&cursor=0&limit=2", headers=a).json()
    assert [row["revision"] for row in changes["changes"]] == [1, 2]
    assert changes["cursor"] == 2 and changes["hasMore"] is True and changes["workspaceRevision"] == 3
    assert changes["changes"][0]["data"]["amount"] == "38.00"
    assert "workspaceId" not in str(changes) and "userId" not in str(changes)
    tail = client.get(f"{ROOT}/changes?protocolVersion=2&cursor=2&limit=2", headers=a).json()
    assert tail["changes"][0]["operation"] == "delete" and tail["changes"][0]["data"] is None
    assert tail["cursor"] == 3 and tail["hasMore"] is False


def test_validation_isolation_and_independent_batch(client):
    app.dependency_overrides[require_core_mode] = lambda: None
    user_a, user_b = user(client, "sync_a"), user(client, "sync_b")
    a, b = enroll(client, user_a), enroll(client, user_b)
    cat_b = mutation("ledger.category", data={"name": "Private", "type": "expense", "icon": "shopping"})
    assert push(client, b, cat_b)[0]["revision"] == 1
    assert client.get(f"{ROOT}/changes?protocolVersion=2", headers=a).json()["changes"] == []
    cross = mutation()
    cross["data"]["categoryId"] = cat_b["entityId"]
    forged = mutation()
    forged["data"]["workspaceId"] = "forged"
    forged["data"]["userId"] = 999
    invalid_amount = mutation()
    invalid_amount["data"]["amount"] = 38.0
    unknown = mutation("ledger.device")
    good = mutation()
    results = push(client, a, cross, forged, invalid_amount, unknown, good)
    assert [row["status"] for row in results] == ["rejected"] * 4 + ["applied"]
    assert [row.get("reason") for row in results[:4]] == [
        "category_not_found", "invalid_data", "invalid_data", "unknown_entity_type"]
    assert results[-1]["revision"] == 1
    assert push(client, a, mutation("ledger.category", entity_id=cat_b["entityId"],
                                    data={"name": "Hijack", "type": "expense"}))[0]["status"] == "rejected"
    assert client.get(f"{ROOT}/changes?protocolVersion=2", headers=a).json()["workspaceRevision"] == 1
    assert client.get(f"{ROOT}/changes?protocolVersion=2", headers=b).json()["workspaceRevision"] == 1


def test_category_tombstone_and_core_ordinary_ledger(client, monkeypatch):
    app.dependency_overrides[require_core_mode] = lambda: None
    monkeypatch.setattr(ledger, "runtime_config", replace(ledger.runtime_config, mode="core"))
    from app.sync import publisher
    monkeypatch.setattr(publisher, "runtime_config", replace(publisher.runtime_config, mode="core"))
    auth = user(client, "sync_web")
    credential = enroll(client, auth)
    category = client.post("/api/v1/ledger/categories", headers=auth,
                           json={"name": "Food", "type": "expense"}).json()
    assert category["id"]
    transaction = client.post("/api/v1/ledger/transactions", headers=auth, json={
        "category_id": category["id"], "type": "expense", "amount": "7.50",
        "description": "Lunch", "occurred_at": "2026-09-28T12:00:00Z"}).json()
    assert client.delete(f"/api/v1/ledger/categories/{category['id']}", headers=auth).status_code == 204
    assert client.get("/api/v1/ledger/categories", headers=auth).json() == []
    assert client.get(f"/api/v1/ledger/transactions/{transaction['id']}", headers=auth).json()["categoryId"] == category["id"]
    patched = client.patch(f"/api/v1/ledger/transactions/{transaction['id']}", headers=auth,
                           json={"description": "Later lunch"})
    assert patched.status_code == 200 and patched.json()["description"] == "Later lunch"
    assert push(client, credential, mutation(entity_id=str(uuid4()), data={
        "categoryId": category["id"], "type": "expense", "amount": "1.00",
        "description": "Bad", "occurredAt": "2026-09-28T12:00:00Z"}))[0]["reason"] == "category_not_found"
    changes = client.get(f"{ROOT}/changes?protocolVersion=2", headers=credential).json()
    assert [row["revision"] for row in changes["changes"]] == [1, 2, 3, 4]
    assert changes["changes"][2]["operation"] == "delete"
    assert changes["changes"][1]["data"]["categoryId"] == category["id"]
    iterator, db = db_session()
    try:
        assert db.get(LedgerCategory, category["id"]).deleted_at is not None
        assert db.get(LedgerTransaction, transaction["id"]).category_id == category["id"]
    finally:
        iterator.close()


def test_core_legacy_seed_once_and_before_mutation(client):
    app.dependency_overrides[require_core_mode] = lambda: None
    auth = user(client, "core_legacy_seed")
    credential = enroll(client, auth)
    category_id, transaction_id, tombstone_id = str(uuid4()), str(uuid4()), str(uuid4())
    workspace_id = client.get("/api/v1/workspace", headers=auth).json()["id"]
    iterator, db = db_session()
    try:
        user_id = db.get(Workspace, workspace_id).owner_user_id
        db.add_all([
            LedgerCategory(id=category_id, user_id=user_id, workspace_id=workspace_id,
                           name="Old food", type="expense", icon="shopping", sync_revision=0),
            LedgerCategory(id=tombstone_id, user_id=user_id, workspace_id=workspace_id,
                           name="Deleted old", type="expense", icon="shopping",
                           sync_revision=0, deleted_at=utcnow()),
            LedgerTransaction(id=transaction_id, user_id=user_id, workspace_id=workspace_id,
                              category_id=category_id, type="expense", amount="12.50",
                              description="Old lunch", merchant="", note="", occurred_at=utcnow(),
                              sync_revision=0),
        ])
        db.commit()
    finally:
        iterator.close()
    first = client.get(f"{ROOT}/changes?protocolVersion=2&cursor=0", headers=credential).json()
    assert [(row["entityType"], row["revision"]) for row in first["changes"]] == [
        ("ledger.category", 1), ("ledger.transaction", 2)]
    assert first["changes"][1]["data"]["categoryId"] == category_id
    assert client.get(f"{ROOT}/changes?protocolVersion=2&cursor=0", headers=credential).json() == first
    iterator, db = db_session()
    try:
        assert db.get(LedgerCategory, category_id).sync_revision == 1
        assert db.get(LedgerTransaction, transaction_id).sync_revision == 2
        assert db.get(LedgerCategory, tombstone_id).sync_revision == 0
        assert db.get(SyncWorkspaceState, workspace_id).initialized_at is not None
        assert db.query(SyncChange).count() == 2
    finally:
        iterator.close()


def test_core_legacy_seed_after_existing_revision_and_post_first(client):
    app.dependency_overrides[require_core_mode] = lambda: None
    auth = user(client, "core_legacy_mixed")
    credential = enroll(client, auth)
    workspace_id = client.get("/api/v1/workspace", headers=auth).json()["id"]
    legacy_id = str(uuid4())
    iterator, db = db_session()
    try:
        user_id = db.get(Workspace, workspace_id).owner_user_id
        db.add(LedgerCategory(id=legacy_id, user_id=user_id, workspace_id=workspace_id,
                              name="Legacy", type="expense", icon="shopping", sync_revision=0))
        db.add(SyncWorkspaceState(workspace_id=workspace_id, current_revision=1))
        db.add(SyncChange(id=str(uuid4()), workspace_id=workspace_id, revision=1,
                          entity_type="ledger.category", entity_id=str(uuid4()), operation="upsert",
                          payload_json={"name": "Earlier", "type": "expense", "icon": "shopping"}))
        db.commit()
    finally:
        iterator.close()
    # A base-zero create cannot overwrite an unseeded legacy UUID.
    attempted = mutation("ledger.category", entity_id=legacy_id,
                         data={"name": "Overwrite", "type": "expense", "icon": "shopping"})
    result = push(client, credential, attempted)[0]
    assert result["status"] == "conflict" and result["currentRevision"] == 2
    changes = client.get(f"{ROOT}/changes?protocolVersion=2&cursor=0", headers=credential).json()
    assert [row["revision"] for row in changes["changes"]] == [1, 2]
    assert changes["changes"][1]["data"]["name"] == "Legacy"
