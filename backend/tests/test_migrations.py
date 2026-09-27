import os
from pathlib import Path
import subprocess
import sys

from sqlalchemy import create_engine, inspect, text
from sqlalchemy import MetaData, Table
from datetime import datetime, timezone

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
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0008_agent_runtime"
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
