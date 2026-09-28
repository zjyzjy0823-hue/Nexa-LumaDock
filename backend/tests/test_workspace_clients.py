from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.api import auth
from app.database import get_db
from app.main import app
from app.models import (Agent, AutomationWorkflow, Dashboard, DataCollection, Device, LedgerCategory,
                        LedgerTransaction, User, Website, WebsiteCategory, Workspace)


def register(client, username):
    response = client.post("/api/v1/auth/register", json={"username": username, "password": "password123"})
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_registration_and_all_new_resources_have_personal_workspace(client):
    headers = register(client, "workspace_owner")
    workspace = client.get("/api/v1/workspace", headers=headers)
    assert workspace.status_code == 200
    assert workspace.json()["kind"] == "personal"
    workspace_id = workspace.json()["id"]
    assert str(UUID(workspace_id)) == workspace_id

    category = client.post("/api/v1/website-categories", headers=headers, json={"name": "Work"})
    assert category.status_code == 201, category.text
    website = client.post("/api/v1/websites", headers=headers, json={
        "name": "Site", "url": "https://example.com", "categoryId": category.json()["id"],
    })
    assert website.status_code == 201, website.text
    device = client.post("/api/v1/devices", headers=headers, json={
        "name": "Laptop", "system": "Windows", "ip": "127.0.0.1",
    })
    assert device.status_code == 201, device.text
    agent = client.post("/api/v1/agents", headers=headers, json={
        "name": "Agent", "workspace": "Legacy UI label",
    })
    assert agent.status_code == 201, agent.text
    collection = client.post("/api/v1/data/collections", headers=headers, json={"name": "Data"})
    assert collection.status_code == 201, collection.text
    workflow = client.post("/api/v1/automations", headers=headers, json={"name": "Workflow"})
    assert workflow.status_code == 201, workflow.text
    ledger_category = client.post("/api/v1/ledger/categories", headers=headers,
                                  json={"name": "Food", "type": "expense"})
    assert ledger_category.status_code == 201, ledger_category.text
    transaction = client.post("/api/v1/ledger/transactions", headers=headers, json={
        "category_id": ledger_category.json()["id"], "type": "expense", "amount": "12.50",
        "description": "Lunch", "occurred_at": "2026-09-28T12:00:00Z",
    })
    assert transaction.status_code == 201, transaction.text

    db_iterator = app.dependency_overrides[get_db]()
    db = next(db_iterator)
    try:
        user = db.scalar(select(User).where(User.username == "workspace_owner"))
        assert user is not None
        assert db.scalar(select(Workspace).where(Workspace.owner_user_id == user.id)).id == workspace_id
        for model in (Dashboard, WebsiteCategory, Website, Device, Agent, DataCollection,
                      AutomationWorkflow, LedgerCategory, LedgerTransaction):
            items = db.scalars(select(model).where(model.user_id == user.id)).all()
            assert items and all(item.workspace_id == workspace_id for item in items)
        assert db.get(Agent, agent.json()["id"]).workspace == "Legacy UI label"
    finally:
        db_iterator.close()


def test_workspace_rename_is_user_scoped(client):
    first = register(client, "workspace_first")
    second = register(client, "workspace_second")
    first_id = client.get("/api/v1/workspace", headers=first).json()["id"]
    second_id = client.get("/api/v1/workspace", headers=second).json()["id"]
    assert first_id != second_id
    renamed = client.patch("/api/v1/workspace", headers=first, json={"name": "  My Space  "})
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "My Space"
    assert renamed.json()["id"] == first_id
    assert client.get("/api/v1/workspace", headers=second).json()["name"] == "个人工作区"
    assert client.patch("/api/v1/workspace", headers=first, json={"kind": "project"}).status_code == 422
    assert client.get("/api/v1/workspace").status_code == 401


def test_registration_rolls_back_user_and_workspace_on_initialization_failure(client, monkeypatch):
    def fail_dashboard(*_args, **_kwargs):
        raise RuntimeError("dashboard initialization failed")

    monkeypatch.setattr(auth, "ensure_dashboard", fail_dashboard)
    with pytest.raises(RuntimeError, match="dashboard initialization failed"):
        client.post("/api/v1/auth/register", json={"username": "rollback_owner", "password": "password123"})
    db_iterator = app.dependency_overrides[get_db]()
    db = next(db_iterator)
    try:
        assert db.scalar(select(User).where(User.username == "rollback_owner")) is None
        assert db.scalars(select(Workspace)).all() == []
    finally:
        db_iterator.close()


def test_client_identity_idempotency_isolation_and_revoke(client):
    first = register(client, "client_first")
    second = register(client, "client_second")
    installation_id = str(uuid4())
    payload = {"installationId": installation_id, "name": "Windows PC",
               "platform": "windows", "appVersion": "0.5.1"}
    assert client.get("/api/v1/clients").status_code == 401
    created = client.post("/api/v1/clients", headers=first, json=payload)
    assert created.status_code == 201, created.text
    first_id = created.json()["id"]
    assert str(UUID(first_id)) == first_id
    assert created.json()["installationId"] == installation_id
    assert created.json()["revokedAt"] is None
    assert created.json()["lastSeenAt"] is not None
    updated = client.post("/api/v1/clients", headers=first, json={**payload, "name": "Renamed PC",
                                                                      "appVersion": "0.5.2"})
    assert updated.status_code == 200, updated.text
    assert updated.json()["id"] == first_id
    assert updated.json()["name"] == "Renamed PC"
    assert updated.json()["appVersion"] == "0.5.2"
    assert len(client.get("/api/v1/clients", headers=first).json()) == 1
    assert client.get(f"/api/v1/clients/{first_id}", headers=first).status_code == 200

    other = client.post("/api/v1/clients", headers=second, json=payload)
    assert other.status_code == 201, other.text
    assert other.json()["id"] != first_id
    assert client.get(f"/api/v1/clients/{first_id}", headers=second).status_code == 404
    assert client.post(f"/api/v1/clients/{first_id}/revoke", headers=second).status_code == 404

    revoked = client.post(f"/api/v1/clients/{first_id}/revoke", headers=first)
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["revokedAt"] is not None
    assert client.post("/api/v1/clients", headers=first, json=payload).status_code == 409
    assert client.get(f"/api/v1/clients/{first_id}", headers=first).json()["revokedAt"] is not None
    assert client.post("/api/v1/clients", headers=first,
                       json={**payload, "platform": "watchos"}).status_code == 422
    assert client.post("/api/v1/clients", headers=first,
                       json={**payload, "installationId": "not-a-uuid"}).status_code == 422
