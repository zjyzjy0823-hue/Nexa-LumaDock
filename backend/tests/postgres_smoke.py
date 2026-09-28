"""Exercise the shared Core app against an already migrated PostgreSQL database."""

from uuid import uuid4
import hashlib
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from sqlalchemy import inspect, text

from app.database import Base, engine
from app.main import app
from app import models  # noqa: F401


assert engine.dialect.name == "postgresql", "Core smoke requires PostgreSQL"
with engine.connect() as connection:
    assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0010_client_auth"
    inspector = inspect(connection)
    assert set(Base.metadata.tables).issubset(set(inspector.get_table_names()))
    assert {"workspaces", "clients"}.issubset(set(inspector.get_table_names()))
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
    assert health.json() == {"status": "ok", "service": "nexa", "version": "0.5.1"}
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

print("PostgreSQL 0010 migration, client credential lifecycle, FastAPI startup and login: PASS")
