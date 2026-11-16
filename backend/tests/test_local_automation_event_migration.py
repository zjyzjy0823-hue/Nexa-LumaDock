import os
from pathlib import Path
import subprocess
import sys

from sqlalchemy import create_engine, inspect, text


def test_0019_creates_local_event_outbox_and_can_downgrade(tmp_path):
    url = f"sqlite:///{tmp_path / 'migration.db'}"
    env = {**os.environ, "DATABASE_URL": url, "NEXA_MODE": "local"}
    def migrate(direction, revision):
        result = subprocess.run([sys.executable, "-m", "alembic", direction, revision],
                                cwd=Path(__file__).parents[1], env=env, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
    migrate("upgrade", "0018_data_record_tenancy")
    migrate("upgrade", "0019_local_automation_events")
    engine = create_engine(url)
    schema = inspect(engine)
    assert {column["name"] for column in schema.get_columns("local_automation_events")} == {
        "id", "workspace_id", "event_id", "type", "agent_id", "task_id", "payload_json",
        "created_at", "delivered_at", "attempts", "last_error"}
    assert ["event_id"] in [constraint["column_names"] for constraint in schema.get_unique_constraints("local_automation_events")]
    with engine.connect() as db:
        assert db.scalar(text("SELECT version_num FROM alembic_version")) == "0019_local_automation_events"
    engine.dispose()
    migrate("downgrade", "0018_data_record_tenancy")
    engine = create_engine(url)
    assert "local_automation_events" not in inspect(engine).get_table_names()
    engine.dispose()
