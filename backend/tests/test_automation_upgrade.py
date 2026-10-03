"""Real v0.5.9 SQLite history survives the new runtime migration."""
from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4
from sqlalchemy import create_engine, text, inspect


def test_upgrade_simulation_history_and_execution_constraint(tmp_path):
    url = "sqlite:///" + (tmp_path / "old.db").as_posix()
    env = {**os.environ, "DATABASE_URL": url, "NEXA_MODE": "local"}
    def migrate(revision):
        result = subprocess.run([sys.executable, "-m", "alembic", "upgrade", revision], cwd=Path(__file__).parents[1], env=env, capture_output=True)
        assert result.returncode == 0
    migrate("0016_personal_state_sync")
    engine = create_engine(url)
    wid, workspace, execution = [str(uuid4()) for _ in range(3)]
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with engine.begin() as db:
        db.execute(text("INSERT INTO users(id,username,email,password_hash,created_at,updated_at) VALUES(1,'upgrade','upgrade@example.test','FAKE_HASH_ONLY',:now,:now)"), {"now": now})
        db.execute(text("INSERT INTO workspaces(id,owner_user_id,name,kind,created_at,updated_at) VALUES(:id,1,'Personal','personal',:now,:now)"), {"id": workspace, "now": now})
        db.execute(text("INSERT INTO automation_workflows(id,user_id,workspace_id,name,description,enabled,trigger_type,trigger_config_json,workflow_json,sync_revision,created_at,updated_at) VALUES(:id,1,:ws,'Old definition','',1,'manual','{}','[]',7,:now,:now)"), {"id": wid, "ws": workspace, "now": now})
        db.execute(text("INSERT INTO automation_executions(id,workflow_id,status,started_at,finished_at,message,result_json) VALUES(:id,:wid,'success',:now,:now,'Safe simulation',:result)"), {"id": execution, "wid": wid, "now": now, "result": '{"simulated":true}'})
    migrate("head")
    with engine.connect() as db:
        row = db.execute(text("SELECT * FROM automation_executions")).mappings().one()
        assert row["id"] == execution and row["status"] == "success" and row["workspace_id"] == workspace
        assert row["trigger_type"] == "simulation" and row["trigger_instance_id"] is None and row["attempt"] == 0
        assert db.scalar(text("SELECT sync_revision FROM automation_workflows")) == 7
        assert db.scalar(text("SELECT version_num FROM alembic_version")) == "0017_automation_engine"
        assert any(set(value["column_names"]) == {"workspace_id", "workflow_id", "trigger_instance_id"} for value in inspect(db).get_unique_constraints("automation_executions"))
    engine.dispose()
