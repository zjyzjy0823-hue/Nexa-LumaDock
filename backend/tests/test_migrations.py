import os
from pathlib import Path
import subprocess
import sys

from sqlalchemy import create_engine, inspect, text
from sqlalchemy import MetaData, Table
from datetime import datetime, timezone
from uuid import UUID

from app.database import Base
from app import models  # noqa: F401


def test_fresh_install_schema(tmp_path: Path):
    database = tmp_path / "fresh.db"
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{database}"}
    result = subprocess.run([sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"],
                            cwd=Path(__file__).parents[1], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    engine = create_engine(f"sqlite:///{database}")
    with engine.connect() as conn:
        inspector = inspect(conn)
        assert set(Base.metadata.tables).issubset(set(inspector.get_table_names()))
        for name, table in Base.metadata.tables.items():
            columns = [column["name"] for column in inspector.get_columns(name)]
            assert len(columns) == len(set(columns))
            assert set(columns) == set(table.columns.keys())
            indexes = [index["name"] for index in inspector.get_indexes(name)]
            assert len(indexes) == len(set(indexes))
            assert {index.name for index in table.indexes} == set(indexes)
            actual_fks = {(tuple(fk["constrained_columns"]), fk["referred_table"], tuple(fk["referred_columns"]))
                          for fk in inspector.get_foreign_keys(name)}
            expected_fks = {(tuple(fk.column_keys), fk.referred_table.name,
                             tuple(element.column.name for element in fk.elements)) for fk in table.foreign_key_constraints}
            assert actual_fks == expected_fks
        runtime_columns = {"token_hash", "token_last4", "token_created_at", "hostname", "os", "os_version",
                           "architecture", "cpu_name", "memory_total", "memory_used", "disk_total", "disk_used",
                           "uptime_seconds", "local_ip", "client_version"}
        assert runtime_columns.issubset({column["name"] for column in inspector.get_columns("devices")})
        for name in ("dashboards", "website_categories", "websites", "devices", "agents",
                     "data_collections", "automation_workflows", "ledger_categories", "ledger_transactions"):
            column = next(column for column in inspector.get_columns(name) if column["name"] == "workspace_id")
            assert not column["nullable"]
        assert any(set(constraint["column_names"]) == {"workspace_id", "installation_id"}
                   for constraint in inspector.get_unique_constraints("clients"))
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0010_client_auth"
        client_columns = {column["name"]: column for column in inspector.get_columns("clients")}
        assert {"token_hash", "token_last4", "token_created_at"}.issubset(client_columns)
        assert all(client_columns[name]["nullable"] for name in ("token_hash", "token_last4", "token_created_at"))
    engine.dispose()


def test_upgrade_0007_to_0008_preserves_agents(tmp_path: Path):
    database = tmp_path / "upgrade.db"
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{database}"}
    backend = Path(__file__).parents[1]

    def upgrade(revision):
        result = subprocess.run([sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", revision],
                                cwd=backend, env=env, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr

    upgrade("0007_device_kind_laptop")
    engine = create_engine(f"sqlite:///{database}")
    now = datetime.now(timezone.utc)
    with engine.begin() as conn:
        metadata = MetaData()
        for name, values in (
            ("users", dict(id=1, username="old", email="old@example.test", password_hash="hash",
                           created_at=now, updated_at=now)),
            ("agents", dict(id="agent-1", user_id=1, name="Old Agent", role="assistant", description="",
                            model="old", workspace="default", avatar="spark", enabled=True,
                            runtime_status="idle", created_at=now, updated_at=now)),
            ("agent_tasks", dict(id="task-1", agent_id="agent-1", title="Old task", description="",
                                 status="queued", created_at=now, updated_at=now)),
            ("agent_events", dict(id="event-1", agent_id="agent-1", level="info",
                                  message="Old event", created_at=now)),
        ):
            conn.execute(Table(name, metadata, autoload_with=conn).insert().values(**values))
    engine.dispose()
    upgrade("head")
    engine = create_engine(f"sqlite:///{database}")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT name, token_hash, runtime_type FROM agents")).one() == ("Old Agent", None, None)
        assert conn.execute(text("SELECT title, claimed_at, result_json FROM agent_tasks")).one() == ("Old task", None, None)
        assert conn.execute(text("SELECT message, task_id, event_type FROM agent_events")).one() == ("Old event", None, None)
    engine.dispose()


def test_upgrade_0008_backfills_workspace_ownership_without_data_loss(tmp_path: Path):
    database = tmp_path / "existing.db"
    backend = Path(__file__).parents[1]
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{database}"}

    def upgrade(revision):
        result = subprocess.run([sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", revision],
                                cwd=backend, env=env, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr

    upgrade("0008_agent_runtime")
    engine = create_engine(f"sqlite:///{database}")
    now = datetime.now(timezone.utc)
    metadata = MetaData()

    def insert(conn, table_name, **values):
        conn.execute(Table(table_name, metadata, autoload_with=conn).insert().values(**values))

    with engine.begin() as conn:
        for user_id in (1, 2):
            insert(conn, "users", id=user_id, username=f"owner_{user_id}",
                   email=f"owner_{user_id}@example.test", password_hash="hash",
                   created_at=now, updated_at=now)
        insert(conn, "dashboards", id=1, user_id=1, name="Old dashboard", layout_json={},
               created_at=now, updated_at=now)
        insert(conn, "website_categories", id="category-1", user_id=1, name="Old category", order=0,
               created_at=now, updated_at=now)
        insert(conn, "websites", id="website-1", user_id=1, category_id="category-1", name="Old website",
               url="https://example.com", favorite=False, order=0, created_at=now, updated_at=now)
        insert(conn, "websites", id="website-2", user_id=2, name="Another owner", url="https://example.org",
               favorite=False, order=0, created_at=now, updated_at=now)
        insert(conn, "devices", id="device-1", user_id=1, name="Old device", system="Windows", kind="desktop",
               ip="127.0.0.1", location="", cpu=0, memory=0, disk=0, activity_json=[],
               created_at=now, updated_at=now)
        insert(conn, "agents", id="agent-1", user_id=1, name="Old agent", role="assistant", description="",
               model="old", workspace="Legacy workspace label", avatar="spark", enabled=True,
               runtime_status="idle", created_at=now, updated_at=now)
        insert(conn, "agent_tasks", id="task-1", agent_id="agent-1", title="Old task", description="",
               status="queued", created_at=now, updated_at=now)
        insert(conn, "data_collections", id="collection-1", user_id=1, name="Old data", description="",
               icon="custom", tone="blue", created_at=now, updated_at=now)
        insert(conn, "automation_workflows", id="workflow-1", user_id=1, name="Old workflow", description="",
               enabled=True, trigger_type="manual", trigger_config_json={}, workflow_json=[],
               created_at=now, updated_at=now)
        insert(conn, "ledger_categories", id="ledger-category-1", user_id=1, name="Old ledger category",
               type="expense", icon="shopping", created_at=now)
        insert(conn, "ledger_transactions", id="transaction-1", user_id=1,
               category_id="ledger-category-1", type="expense", amount=12, description="Old transaction",
               merchant="", note="", occurred_at=now, created_at=now, updated_at=now)
    engine.dispose()

    upgrade("head")
    engine = create_engine(f"sqlite:///{database}")
    with engine.connect() as conn:
        workspaces = conn.execute(text("SELECT id, owner_user_id, kind FROM workspaces ORDER BY owner_user_id")).all()
        assert len(workspaces) == 2
        assert [row.owner_user_id for row in workspaces] == [1, 2]
        assert all(row.kind == "personal" and str(UUID(row.id)) == row.id for row in workspaces)
        ownership = {row.owner_user_id: row.id for row in workspaces}
        for name in ("dashboards", "website_categories", "websites", "devices", "agents",
                     "data_collections", "automation_workflows", "ledger_categories", "ledger_transactions"):
            rows = conn.execute(text(f"SELECT user_id, workspace_id FROM {name}")).all()
            assert rows
            assert all(row.workspace_id == ownership[row.user_id] for row in rows)
        assert conn.scalar(text("SELECT name FROM dashboards WHERE id=1")) == "Old dashboard"
        assert conn.scalar(text("SELECT workspace FROM agents WHERE id='agent-1'")) == "Legacy workspace label"
        assert conn.scalar(text("SELECT count(*) FROM agent_tasks WHERE id='task-1'")) == 1
        assert conn.scalar(text("SELECT amount FROM ledger_transactions WHERE id='transaction-1'")) == 12
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == "0010_client_auth"
    engine.dispose()


def test_upgrade_0009_to_0010_preserves_existing_client(tmp_path: Path):
    database = tmp_path / "client-upgrade.db"
    backend = Path(__file__).parents[1]
    env = {**os.environ, "NEXA_MODE": "local", "DATABASE_URL": f"sqlite:///{database}"}

    def upgrade(revision):
        result = subprocess.run([sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", revision],
                                cwd=backend, env=env, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr

    upgrade("0009_workspace_clients")
    engine = create_engine(f"sqlite:///{database}")
    now = datetime.now(timezone.utc)
    with engine.begin() as conn:
        metadata = MetaData()
        conn.execute(Table("users", metadata, autoload_with=conn).insert().values(
            id=1, username="old-client-owner", email="old@example.test", password_hash="hash",
            created_at=now, updated_at=now))
        conn.execute(Table("workspaces", metadata, autoload_with=conn).insert().values(
            id="workspace-old", owner_user_id=1, name="Personal", kind="personal",
            created_at=now, updated_at=now))
        conn.execute(Table("clients", metadata, autoload_with=conn).insert().values(
            id="client-old", workspace_id="workspace-old", installation_id="installation-old",
            name="Old desktop", platform="windows", app_version="0.5.2",
            created_at=now, updated_at=now))
    engine.dispose()
    upgrade("head")
    engine = create_engine(f"sqlite:///{database}")
    with engine.connect() as conn:
        row = conn.execute(text("SELECT name, workspace_id, token_hash, token_last4, token_created_at "
                                "FROM clients WHERE id='client-old'")).one()
        assert row == ("Old desktop", "workspace-old", None, None, None)
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == "0010_client_auth"
    engine.dispose()


def test_create_admin_initializes_personal_workspace(tmp_path: Path):
    database = tmp_path / "admin.db"
    backend = Path(__file__).parents[1]
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{database}",
           "JWT_SECRET": "test-secret-for-admin", "NEXA_MODE": "local"}
    script = ("import builtins; from app import create_admin; "
              "builtins.input = lambda _: 'admin_owner'; "
              "create_admin.getpass = lambda _: 'password123'; create_admin.main()")
    result = subprocess.run([sys.executable, "-c", script], cwd=backend, env=env,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    engine = create_engine(f"sqlite:///{database}")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT u.username, w.kind, w.name FROM users u "
                                 "JOIN workspaces w ON w.owner_user_id=u.id")).one() == (
            "admin_owner", "personal", "个人工作区"
        )
    engine.dispose()
