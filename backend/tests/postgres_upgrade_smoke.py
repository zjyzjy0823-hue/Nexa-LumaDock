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
    upgrade("0011_sync_foundation")
    engine = create_engine(upgrade_url)
    try:
        with engine.begin() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0011_sync_foundation"
            assert connection.scalar(text("SELECT sync_revision FROM ledger_transactions")) == 0
            old_state = Table("sync_workspace_state", MetaData(), autoload_with=connection)
            old_change = Table("sync_changes", MetaData(), autoload_with=connection)
            old_mutation = Table("sync_mutations", MetaData(), autoload_with=connection)
            connection.execute(old_state.insert().values(workspace_id=workspace_id, current_revision=1,
                                                         created_at=now, updated_at=now))
            connection.execute(old_change.insert().values(
                id=str(uuid4()), workspace_id=workspace_id, revision=1,
                entity_type="ledger.category", entity_id="ledger-category-1", operation="upsert",
                payload_json={"name": "Food", "type": "expense", "icon": "shopping"},
                origin_client_id="old-client", created_at=now))
            connection.execute(old_mutation.insert().values(
                id=str(uuid4()), workspace_id=workspace_id, client_id="old-client", mutation_id=str(uuid4()),
                entity_type="ledger.category", entity_id="ledger-category-1", operation="upsert",
                base_revision=0, result_revision=1, status="applied",
                result_json={"status": "applied", "revision": 1}, created_at=now))
    finally:
        engine.dispose()
    upgrade("0012_local_sync_queue")
    engine = create_engine(upgrade_url)
    outbox_payload = {"categoryId": "ledger-category-1", "type": "expense",
                      "amount": "12.00", "description": "Old transaction",
                      "merchant": "", "note": "", "occurredAt": now.isoformat()}
    try:
        with engine.begin() as connection:
            connection.execute(Table("local_mutation_queue", MetaData(), autoload_with=connection).insert().values(
                id="old-outbox", mutation_id="old-mutation", workspace_id=workspace_id,
                entity_type="ledger.transaction", entity_id="transaction-1", operation="upsert",
                base_revision=0, payload_json=outbox_payload,
                status="pending", attempt_count=0, created_at=now, updated_at=now))
    finally:
        engine.dispose()
    upgrade("head")
    engine = create_engine(upgrade_url)
    try:
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0014_multi_entity_sync"
            assert connection.execute(text("SELECT mutation_id, base_revision, status, depends_on_mutation_id "
                                           "FROM local_mutation_queue")).one() == ("old-mutation", 0, "pending", None)
            assert connection.scalar(text("SELECT payload_json FROM local_mutation_queue")) == outbox_payload
            for name in ("ledger_categories", "ledger_transactions"):
                assert connection.execute(text(f"SELECT sync_revision, deleted_at FROM {name}")).one() == (0, None)
            assert connection.execute(text("SELECT current_revision, initialized_at FROM sync_workspace_state")).one() == (1, None)
            assert connection.scalar(text("SELECT count(*) FROM sync_changes")) == 1
            assert connection.scalar(text("SELECT count(*) FROM sync_mutations")) == 1
            assert connection.execute(text("SELECT name, token_hash, token_last4, token_created_at "
                                           "FROM clients WHERE id='old-client'")).one() == (
                "Existing installation", None, None, None)
            assert connection.scalar(text("SELECT count(*) FROM websites WHERE id='website-1'")) == 1
    finally:
        engine.dispose()
    # Exercise the already initialized 0013 -> 0014 path on real PostgreSQL too.
    sys.path.insert(0, str(BACKEND / "tests"))
    sys.path.insert(0, str(BACKEND))
    from test_multi_entity_upgrade import verify_upgrade
    for mode in ("local", "core"):
        multi_database = "nexa_multi_upgrade_" + uuid4().hex[:12]
        with admin_engine.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{multi_database}"'))
        try:
            verify_upgrade(base_url.set(database=multi_database).render_as_string(hide_password=False), BACKEND, mode)
        finally:
            with admin_engine.connect() as connection:
                connection.execute(text(f'DROP DATABASE "{multi_database}" WITH (FORCE)'))
    print("PostgreSQL 0008 -> 0014 upgrade, Client, Ledger and Sync history preservation: PASS")
finally:
    with admin_engine.connect() as connection:
        connection.execute(text(f'DROP DATABASE IF EXISTS "{DATABASE_NAME}" WITH (FORCE)'))
    admin_engine.dispose()
