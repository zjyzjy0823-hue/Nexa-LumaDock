"""Exercise the shared Core app against an already migrated PostgreSQL database."""

from uuid import uuid4
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
    assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0008_agent_runtime"
    inspector = inspect(connection)
    assert set(Base.metadata.tables).issubset(set(inspector.get_table_names()))
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
    dashboard = client.get("/api/dashboard", headers={"Authorization": f"Bearer {token}"})
    assert dashboard.status_code == 200, dashboard.text

with TestClient(app) as client:
    logged_in = client.post("/api/v1/auth/login", json={
        "username": username, "password": "smoke-test-password",
    })
    assert logged_in.status_code == 200, logged_in.text

print("PostgreSQL migration, ORM, FastAPI startup, health, registration, dashboard, login: PASS")
