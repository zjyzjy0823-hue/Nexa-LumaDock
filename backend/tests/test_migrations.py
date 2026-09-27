import os
from pathlib import Path
import subprocess
import sys

from sqlalchemy import create_engine, inspect, text

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
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0007_device_kind_laptop"
    engine.dispose()
