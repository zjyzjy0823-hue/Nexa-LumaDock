"""Verify 0008 user data survives the 0009 PostgreSQL migration."""

import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import MetaData, Table, create_engine, text
from sqlalchemy.engine import make_url


BACKEND = Path(__file__).resolve().parents[1]
DATABASE_NAME = f"nexa_upgrade_{uuid4().hex[:12]}"
base_url = make_url(os.environ["DATABASE_URL"])
assert base_url.drivername == "postgresql+psycopg"
admin_engine = create_engine(base_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
upgrade_url = base_url.set(database=DATABASE_NAME)


def upgrade(revision: str) -> None:
    env = {**os.environ, "DATABASE_URL": upgrade_url.render_as_string(hide_password=False)}
    result = subprocess.run([sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", revision],
                            cwd=BACKEND, env=env, capture_output=True, text=True)
    if result.returncode:
        details = result.stderr
        if base_url.password:
            details = details.replace(base_url.password, "[redacted]")
        raise RuntimeError(f"PostgreSQL Alembic upgrade to {revision} failed: "
                           + details)


try:
    with admin_engine.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{DATABASE_NAME}"'))

    upgrade("0008_agent_runtime")
    engine = create_engine(upgrade_url)
    metadata = MetaData()
    now = datetime.now(timezone.utc)
    try:
        with engine.begin() as connection:
            def insert(table_name: str, **values):
                connection.execute(Table(table_name, metadata, autoload_with=connection).insert().values(**values))

            insert("users", id=1, username="upgrade_owner", email="upgrade@example.test",
                   password_hash="hash", created_at=now, updated_at=now)
            insert("dashboards", id=1, user_id=1, name="Old dashboard", layout_json={},
                   created_at=now, updated_at=now)
            insert("websites", id="website-1", user_id=1, name="Old site", url="https://example.com",
                   favorite=False, order=0, created_at=now, updated_at=now)
            insert("devices", id="device-1", user_id=1, name="Old device", system="Windows", kind="desktop",
                   ip="127.0.0.1", location="", cpu=0, memory=0, disk=0, activity_json=[],
                   created_at=now, updated_at=now)
            insert("agents", id="agent-1", user_id=1, name="Old agent", role="assistant", description="",
                   model="old", workspace="Legacy label", avatar="spark", enabled=True,
                   runtime_status="idle", created_at=now, updated_at=now)
            insert("data_collections", id="collection-1", user_id=1, name="Old data", description="",
                   icon="custom", tone="blue", created_at=now, updated_at=now)
            insert("automation_workflows", id="workflow-1", user_id=1, name="Old workflow", description="",
                   enabled=True, trigger_type="manual", trigger_config_json={}, workflow_json=[],
                   created_at=now, updated_at=now)
            insert("ledger_categories", id="ledger-category-1", user_id=1, name="Food", type="expense",
                   icon="shopping", created_at=now)
            insert("ledger_transactions", id="transaction-1", user_id=1,
                   category_id="ledger-category-1", type="expense", amount=12, description="Old transaction",
                   merchant="", note="", occurred_at=now, created_at=now, updated_at=now)
    finally:
        engine.dispose()

    upgrade("0009_workspace_clients")
    engine = create_engine(upgrade_url)
    try:
        with engine.begin() as connection:
            workspace_id = connection.scalar(text("SELECT id FROM workspaces WHERE owner_user_id=1 AND kind='personal'"))
            assert workspace_id
            for name in ("dashboards", "websites", "devices", "agents", "data_collections",
                         "automation_workflows", "ledger_categories", "ledger_transactions"):
                assert connection.scalar(text(f"SELECT count(*) FROM {name} WHERE workspace_id=:id"),
                                         {"id": workspace_id}) == 1
            assert connection.scalar(text("SELECT workspace FROM agents WHERE id='agent-1'")) == "Legacy label"
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0009_workspace_clients"
            connection.execute(Table("clients", MetaData(), autoload_with=connection).insert().values(
                id="old-client", workspace_id=workspace_id, installation_id=str(uuid4()),
                name="Existing installation", platform="windows", app_version="0.5.2",
                created_at=now, updated_at=now))
    finally:
        engine.dispose()
    upgrade("0010_client_auth")
    engine = create_engine(upgrade_url)
    try:
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0010_client_auth"
            assert connection.scalar(text("SELECT count(*) FROM ledger_transactions WHERE id='transaction-1'")) == 1
    finally:
        engine.dispose()
    upgrade("head")
    engine = create_engine(upgrade_url)
    try:
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0011_sync_foundation"
            for name in ("ledger_categories", "ledger_transactions"):
                assert connection.execute(text(f"SELECT sync_revision, deleted_at FROM {name}")).one() == (0, None)
            assert connection.execute(text("SELECT name, token_hash, token_last4, token_created_at "
                                           "FROM clients WHERE id='old-client'")).one() == (
                "Existing installation", None, None, None)
            assert connection.scalar(text("SELECT count(*) FROM websites WHERE id='website-1'")) == 1
    finally:
        engine.dispose()
    print("PostgreSQL 0008 -> 0011 upgrade, Client and Ledger preservation: PASS")
finally:
    with admin_engine.connect() as connection:
        connection.execute(text(f'DROP DATABASE IF EXISTS "{DATABASE_NAME}" WITH (FORCE)'))
    admin_engine.dispose()
