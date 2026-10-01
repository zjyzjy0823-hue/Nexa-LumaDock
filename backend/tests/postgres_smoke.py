"""Exercise the shared Core app against an already migrated PostgreSQL database."""

from uuid import uuid4
import hashlib
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from sqlalchemy import inspect, text

from app.database import Base, SessionLocal, engine
from app.main import app
from app import models  # noqa: F401
from app.sync.service import apply_mutation


assert engine.dialect.name == "postgresql", "Core smoke requires PostgreSQL"
with engine.connect() as connection:
    assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0015_agent_data_actions"
    inspector = inspect(connection)
    assert set(Base.metadata.tables).issubset(set(inspector.get_table_names()))
    assert {"workspaces", "clients"}.issubset(set(inspector.get_table_names()))
    assert {"sync_workspace_state", "sync_changes", "sync_mutations",
            "local_sync_state", "local_mutation_queue"}.issubset(set(inspector.get_table_names()))
    assert "initialized_at" in {column["name"] for column in inspector.get_columns("sync_workspace_state")}
    assert {"depends_on_mutation_id", "result_revision", "conflict_json"}.issubset(
        {column["name"] for column in inspector.get_columns("local_mutation_queue")})
    assert not any(set(item["column_names"]) == {"workspace_id", "entity_type", "entity_id"}
                   for item in inspector.get_unique_constraints("local_mutation_queue"))
    queue_indexes = {item["name"]: item for item in inspector.get_indexes("local_mutation_queue")}
    assert queue_indexes["uq_local_mutation_pending_entity"]["unique"]
    assert queue_indexes["uq_local_mutation_frozen_entity"]["unique"]
    assert any(set(item["column_names"]) == {"workspace_id", "revision"}
               for item in inspector.get_unique_constraints("sync_changes"))
    assert any(set(item["column_names"]) == {"client_id", "mutation_id"}
               for item in inspector.get_unique_constraints("sync_mutations"))
    assert any(set(constraint["column_names"]) == {"workspace_id", "installation_id"}
               for constraint in inspector.get_unique_constraints("clients"))
    assert any(fk["referred_table"] == "workspaces" and fk["constrained_columns"] == ["workspace_id"]
               for fk in inspector.get_foreign_keys("clients"))
    assert {"token_hash", "token_last4", "token_created_at"}.issubset(
        {column["name"] for column in inspector.get_columns("clients")})
    assert any(index["name"] == "ix_clients_token_hash" and index["unique"]
               for index in inspector.get_indexes("clients"))
    for name in ("dashboards", "website_categories", "websites", "devices", "agents",
                 "data_collections", "automation_workflows", "ledger_categories", "ledger_transactions"):
        assert not next(column for column in inspector.get_columns(name)
                        if column["name"] == "workspace_id")["nullable"]
        assert connection.scalar(text(f"SELECT count(*) FROM {name} WHERE workspace_id IS NULL")) == 0
    ledger_columns = {column["name"]: column for column in inspector.get_columns("ledger_transactions")}
    assert ledger_columns["amount"]["type"].precision == 14
    assert ledger_columns["amount"]["type"].scale == 2
    assert ledger_columns["occurred_at"]["type"].timezone
    assert any(fk["referred_table"] == "users" for fk in inspector.get_foreign_keys("ledger_transactions"))
    assert any(index["name"] == "ix_users_username" and index["unique"]
               for index in inspector.get_indexes("users"))

username = f"core_smoke_{uuid4().hex[:12]}"
with TestClient(app) as client:
    health = client.get("/api/health")
    assert health.status_code == 200, health.text
    assert health.json() == {"status": "ok", "service": "nexa", "version": "0.5.6"}
    registered = client.post("/api/v1/auth/register", json={
        "username": username, "password": "smoke-test-password",
    })
    assert registered.status_code == 201, registered.text
    token = registered.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    workspace = client.get("/api/v1/workspace", headers=headers)
    assert workspace.status_code == 200, workspace.text
    assert workspace.json()["kind"] == "personal"
    dashboard = client.get("/api/dashboard", headers={"Authorization": f"Bearer {token}"})
    assert dashboard.status_code == 200, dashboard.text
    installation_id = str(uuid4())
    created_client = client.post("/api/v1/clients", headers=headers, json={
        "installationId": installation_id, "name": "Core smoke installation",
        "platform": "linux", "appVersion": "0.5.2",
    })
    assert created_client.status_code == 201, created_client.text
    clients = client.get("/api/v1/clients", headers=headers)
    assert clients.status_code == 200, clients.text
    assert any(item["id"] == created_client.json()["id"] for item in clients.json())
    enrolled = client.post("/api/v1/clients/enroll", headers=headers, json={
        "installationId": installation_id, "name": "Core smoke installation",
        "platform": "linux", "appVersion": "0.5.2",
    })
    assert enrolled.status_code == 201, enrolled.text
    assert enrolled.headers["cache-control"] == "no-store"
    assert enrolled.json()["client"]["id"] == created_client.json()["id"]
    credential_a = enrolled.json()["credential"]
    assert credential_a.startswith("nc_live_")
    with engine.connect() as connection:
        row = connection.execute(text("SELECT token_hash, token_last4 FROM clients WHERE id=:id"),
                                 {"id": created_client.json()["id"]}).one()
        assert row.token_hash == hashlib.sha256(credential_a.encode()).hexdigest()
        assert row.token_hash != credential_a
        assert row.token_last4 == credential_a[-4:]
    auth_a = {"Authorization": "Bearer " + credential_a}
    assert client.get("/api/v1/client/me", headers=auth_a).json()["workspaceId"] == workspace.json()["id"]
    heartbeat = client.post("/api/v1/client/heartbeat", headers=auth_a, json={"appVersion": "0.5.3"})
    assert heartbeat.status_code == 200, heartbeat.text
    assert heartbeat.json()["appVersion"] == "0.5.3"
    rotated = client.post(f"/api/v1/clients/{created_client.json()['id']}/credential", headers=headers)
    assert rotated.status_code == 200, rotated.text
    credential_b = rotated.json()["credential"]
    assert client.get("/api/v1/client/me", headers=auth_a).status_code == 401
    assert client.get("/api/v1/client/me", headers={"Authorization": "Bearer " + credential_b}).status_code == 200
    revoked = client.post(f"/api/v1/clients/{created_client.json()['id']}/revoke", headers=headers)
    assert revoked.status_code == 200, revoked.text
    assert client.get("/api/v1/client/me", headers={"Authorization": "Bearer " + credential_b}).status_code == 401

with engine.connect() as connection:
    assert connection.scalar(text("SELECT workspace_id FROM dashboards WHERE id = :id"),
                             {"id": dashboard.json()["id"]}) == workspace.json()["id"]
    assert connection.scalar(text("SELECT workspace_id FROM clients WHERE id = :id"),
                             {"id": created_client.json()["id"]}) == workspace.json()["id"]
    row = connection.execute(text("SELECT token_hash, token_last4 FROM clients WHERE id=:id"),
                             {"id": created_client.json()["id"]}).one()
    assert row.token_hash is None
    assert row.token_last4 == credential_b[-4:]
    assert connection.scalar(text("SELECT count(*) FROM clients WHERE token_hash=:hash"),
                             {"hash": hashlib.sha256(credential_a.encode()).hexdigest()}) == 0

with TestClient(app) as client:
    logged_in = client.post("/api/v1/auth/login", json={
        "username": username, "password": "smoke-test-password",
    })
    assert logged_in.status_code == 200, logged_in.text

def sync_mutation(entity_id, base=0, operation="upsert", description="Coffee"):
    return {"mutationId": str(uuid4()), "entityType": "ledger.transaction", "entityId": entity_id,
            "operation": operation, "baseRevision": base,
            "data": {"categoryId": None, "type": "expense", "amount": "38.00",
                     "description": description, "merchant": "", "note": "",
                     "occurredAt": "2026-09-28T12:00:00Z"} if operation == "upsert" else None}


with TestClient(app) as client:
    def new_user():
        response = client.post("/api/v1/auth/register", json={
            "username": "sync_smoke_" + uuid4().hex[:12], "password": "smoke-test-password"})
        assert response.status_code == 201, response.text
        return {"Authorization": "Bearer " + response.json()["access_token"]}

    def enroll(user_auth):
        response = client.post("/api/v1/clients/enroll", headers=user_auth, json={
            "installationId": str(uuid4()), "name": "Sync smoke", "platform": "linux", "appVersion": "0.5.3"})
        assert response.status_code == 201, response.text
        return response.json()["client"]["id"], {"Authorization": "Bearer " + response.json()["credential"]}

    owner, stranger = new_user(), new_user()
    client_a, auth_a = enroll(owner)
    client_b, auth_b = enroll(owner)
    _, auth_other = enroll(stranger)
    entity_id = str(uuid4())
    created = sync_mutation(entity_id)
    response = client.post("/api/v1/sync/mutations", headers=auth_a, json={"protocolVersion": 2, "mutations": [created]})
    assert response.status_code == 200, response.text
    first = response.json()["results"][0]
    assert first["status"] == "applied" and first["revision"] == 1
    retry = client.post("/api/v1/sync/mutations", headers=auth_a, json={"protocolVersion": 2, "mutations": [created]})
    assert retry.json()["results"][0] == first
    assert client.get("/api/v1/sync/changes?protocolVersion=2", headers=auth_other).json()["changes"] == []
    assert client.get("/api/v1/sync/changes?protocolVersion=2", headers=auth_b).json()["changes"][0]["revision"] == 1

    barrier = Barrier(2)

    def compete(client_id, payload):
        with SessionLocal() as db:
            item = db.get(models.Client, client_id)
            barrier.wait(timeout=10)
            return apply_mutation(db, item, payload)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(compete, client_a, sync_mutation(entity_id, 1, description="A")),
                   pool.submit(compete, client_b, sync_mutation(entity_id, 1, description="B"))]
        competing = [future.result(timeout=20) for future in futures]
    assert sorted(result["status"] for result in competing) == ["applied", "conflict"]
    assert next(result["revision"] for result in competing if result["status"] == "applied") == 2

    barrier = Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(compete, client_a, sync_mutation(str(uuid4()))),
                   pool.submit(compete, client_b, sync_mutation(str(uuid4())))]
        independent = [future.result(timeout=20) for future in futures]
    assert sorted(result["revision"] for result in independent) == [3, 4]

    deletion = sync_mutation(entity_id, 2, operation="delete")
    result = client.post("/api/v1/sync/mutations", headers=auth_a,
                         json={"protocolVersion": 2, "mutations": [deletion]}).json()["results"][0]
    assert result["status"] == "applied" and result["revision"] == 5
    assert client.post("/api/v1/sync/mutations", headers=auth_a,
                       json={"protocolVersion": 2, "mutations": [deletion]}).json()["results"][0] == result
    assert client.get(f"/api/v1/ledger/transactions/{entity_id}", headers=owner).status_code == 404
    changes = client.get("/api/v1/sync/changes?protocolVersion=2&cursor=2&limit=2", headers=auth_b).json()
    assert [row["revision"] for row in changes["changes"]] == [3, 4]
    assert changes["hasMore"] is True and changes["cursor"] == 4
    assert client.get("/api/v1/sync/changes?protocolVersion=2&cursor=4", headers=auth_b).json()["changes"][0]["operation"] == "delete"
    other_attempt = client.post("/api/v1/sync/mutations", headers=auth_other,
                                json={"protocolVersion": 2, "mutations": [sync_mutation(entity_id, 5)]}).json()["results"][0]
    assert other_attempt["status"] == "rejected" and other_attempt["reason"] == "entity_id_unavailable"
    ordinary = client.post("/api/v1/ledger/categories", headers=owner,
                           json={"name": "Web category", "type": "expense"})
    assert ordinary.status_code == 201, ordinary.text
    ordinary_change = client.get("/api/v1/sync/changes?protocolVersion=2&cursor=5", headers=auth_a).json()["changes"]
    assert len(ordinary_change) == 1 and ordinary_change[0]["revision"] == 6
    assert ordinary_change[0]["entityId"] == ordinary.json()["id"]
    assert ordinary_change[0]["data"] == {"name": "Web category", "type": "expense", "icon": "shopping"}

with TestClient(app) as client:
    legacy_user = client.post("/api/v1/auth/register", json={
        "username": "legacy_seed_" + uuid4().hex[:12], "password": "smoke-test-password"})
    assert legacy_user.status_code == 201, legacy_user.text
    user_auth = {"Authorization": "Bearer " + legacy_user.json()["access_token"]}
    workspace_id = client.get("/api/v1/workspace", headers=user_auth).json()["id"]

    def legacy_client():
        enrolled = client.post("/api/v1/clients/enroll", headers=user_auth, json={
            "installationId": str(uuid4()), "name": "Legacy pull", "platform": "linux", "appVersion": "0.5.3"})
        assert enrolled.status_code == 201, enrolled.text
        return {"Authorization": "Bearer " + enrolled.json()["credential"]}

    first_auth, second_auth = legacy_client(), legacy_client()
    category_id, transaction_id = str(uuid4()), str(uuid4())
    with SessionLocal() as db:
        owner_id = db.get(models.Workspace, workspace_id).owner_user_id
        db.add(models.LedgerCategory(id=category_id, user_id=owner_id, workspace_id=workspace_id,
                                     name="Legacy food", type="expense", icon="shopping", sync_revision=0))
        db.add(models.LedgerTransaction(id=transaction_id, user_id=owner_id, workspace_id=workspace_id,
                                        category_id=category_id, type="expense", amount="12.50",
                                        description="Legacy lunch", merchant="", note="",
                                        occurred_at=models.utcnow(), sync_revision=0))
        db.commit()
    barrier = Barrier(2)

    def first_pull(auth):
        barrier.wait(timeout=10)
        response = client.get("/api/v1/sync/changes?protocolVersion=2&cursor=0", headers=auth)
        assert response.status_code == 200, response.text
        return response.json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(first_pull, first_auth), pool.submit(first_pull, second_auth)]
        pulled = [future.result(timeout=20) for future in futures]
    assert pulled[0] == pulled[1]
    assert [(change["entityType"], change["revision"]) for change in pulled[0]["changes"]] == [
        ("ledger.category", 1), ("ledger.transaction", 2)]
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM sync_changes WHERE workspace_id=:id"),
                                 {"id": workspace_id}) == 2
        assert connection.scalar(text("SELECT current_revision FROM sync_workspace_state WHERE workspace_id=:id"),
                                 {"id": workspace_id}) == 2
        assert connection.scalar(text("SELECT initialized_at FROM sync_workspace_state WHERE workspace_id=:id"),
                                 {"id": workspace_id}) is not None
        assert connection.scalar(text("SELECT count(*) FROM local_mutation_queue")) == 0

print("PostgreSQL 0014 migration, sync, isolation, legacy seeding and concurrency: PASS")
