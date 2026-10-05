"""Real 0015 schema upgrade; existing rows/history/queue/cursor stay intact."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, MetaData, Table, select, text
from sqlalchemy.orm import sessionmaker

from app.models import LocalMutation, SyncChange, UserPreference, Dashboard, AutomationWorkflow
from app.sync.local import seed_local_queue
from app.sync.service import ensure_core_sync_initialized
from app.sync.adapters.personal_state import CATALOG


def verify_personal_upgrade(database_url, backend, mode):
    def migrate(command, revision, succeeds=True):
        env = {**os.environ, "DATABASE_URL": database_url,
               "NEXA_MODE": "core" if database_url.startswith("postgresql") else "local"}
        result = subprocess.run([sys.executable, "-m", "alembic", command, revision],
                                cwd=backend, env=env, capture_output=True)
        assert (result.returncode == 0) == succeeds, "Personal state migration outcome"
    migrate("upgrade", "0015_agent_data_actions")
    engine = create_engine(database_url)
    now = datetime.now(timezone.utc)
    workspace_id, ledger_id, website_id, collection_id, automation_id, pending_id, conflict_id = [str(uuid4()) for _ in range(7)]
    immutable = ("ledger_categories", "websites", "data_collections", "local_mutation_queue", "sync_changes")
    layout = CATALOG.model_dump(); layout["widgets"] = layout["widgets"][:2]
    with engine.begin() as db:
        metadata = MetaData()
        def add(table_name, **values):
            db.execute(Table(table_name, metadata, autoload_with=db).insert().values(**values))
        add("users", id=37, username="personal_upgrade", email="upgrade@example.test", password_hash="FAKE_HASH_ONLY", created_at=now, updated_at=now)
        add("workspaces", id=workspace_id, owner_user_id=37, name="Personal", kind="personal", created_at=now, updated_at=now)
        add("ledger_categories", id=ledger_id, user_id=37, workspace_id=workspace_id, name="Old ledger", type="expense", icon="shopping", sync_revision=7, created_at=now)
        add("websites", id=website_id, user_id=37, workspace_id=workspace_id, name="Old website", url="https://example.test", favorite=False, order=1, sync_revision=8, created_at=now, updated_at=now)
        add("data_collections", id=collection_id, user_id=37, workspace_id=workspace_id, name="Old data", description="", icon="custom", tone="blue", sync_revision=9, created_at=now, updated_at=now)
        add("user_preferences", id=91, user_id=37, theme="dark", language="en-US", timezone="UTC", settings_json={"sync": {"serverUrl": "https://local.example"}})
        add("dashboards", id=92, user_id=37, workspace_id=workspace_id, name="Old Dashboard", layout_json=layout, created_at=now, updated_at=now)
        add("automation_workflows", id=automation_id, user_id=37, workspace_id=workspace_id, name="Old automation", description="", enabled=True, trigger_type="schedule", trigger_config_json={"cron": "0 9 * * *"}, workflow_json=[{"kind": "DO", "text": "Notify"}], created_at=now, updated_at=now)
        add("automation_executions", id=str(uuid4()), workflow_id=automation_id, status="success", started_at=now, finished_at=now, message="Old simulated history", result_json={"simulated": True})
        add("local_sync_state", workspace_id=workspace_id, cursor=9, queue_seed_version=2, queue_seeded_at=now, created_at=now, updated_at=now)
        add("sync_workspace_state", workspace_id=workspace_id, current_revision=9, bootstrap_version=2, initialized_at=now, created_at=now, updated_at=now)
        for identity, status in ((pending_id, "pending"), (conflict_id, "conflict")):
            add("local_mutation_queue", id=identity, mutation_id=str(uuid4()), workspace_id=workspace_id,
                entity_type="ledger.category", entity_id=ledger_id if status == "pending" else str(uuid4()),
                operation="upsert", base_revision=7, payload_json={"name": "Old edit", "type": "expense", "icon": "shopping"},
                status=status, attempt_count=0, conflict_json={"currentRevision": 9, "current": {"name": "Remote", "type": "expense", "icon": "shopping"}, "deleted": False} if status == "conflict" else None,
                created_at=now, updated_at=now)
        add("sync_changes", id=str(uuid4()), workspace_id=workspace_id, revision=9, entity_type="data.collection", entity_id=collection_id, operation="upsert", payload_json={"name": "Old data"}, created_at=now)
        before = {name: [dict(row) for row in db.execute(text(f'SELECT * FROM "{name}"')).mappings()] for name in immutable}
    migrate("upgrade", "0016_personal_state_sync")
    with engine.connect() as db:
        assert db.scalar(text("SELECT version_num FROM alembic_version")) == "0016_personal_state_sync"
        for name in immutable:
            assert [dict(row) for row in db.execute(text(f'SELECT * FROM "{name}"')).mappings()] == before[name]
        assert db.scalar(text("SELECT workspace_id FROM user_preferences")) == workspace_id
        for name in ("user_preferences", "dashboards", "automation_workflows"):
            assert db.execute(text(f"SELECT sync_revision, deleted_at FROM {name}")).one() == (0, None)
    factory = sessionmaker(engine, autoflush=False)
    with factory() as db:
        seed = seed_local_queue if mode == "local" else ensure_core_sync_initialized
        seed(db, workspace_id); db.rollback()
        for _ in range(2):
            state = seed(db, workspace_id); db.commit()
        if mode == "local":
            entries = db.scalars(select(LocalMutation).where(LocalMutation.id.not_in([pending_id, conflict_id]))).all()
            assert len(entries) == 3 and {entry.entity_type for entry in entries} == {"user.preferences", "dashboard.layout", "automation.definition"}
            assert state.queue_seed_version == 3 and state.cursor == 9
        else:
            changes = db.scalars(select(SyncChange).where(SyncChange.revision > 9).order_by(SyncChange.revision)).all()
            assert len(changes) == 3 and [row.revision for row in changes] == [10, 11, 12]
            assert state.bootstrap_version == 3 and state.current_revision == 12
        for name in immutable:
            for row in before[name]:
                after = db.execute(text(f'SELECT * FROM "{name}" WHERE id=:id'), {"id": row["id"]}).mappings().one()
                assert dict(after) == row
        assert db.get(UserPreference, 91).settings_json["sync"]["serverUrl"] == "https://local.example"
        assert db.get(Dashboard, 92).layout_json == layout
        assert db.get(AutomationWorkflow, automation_id).name == "Old automation"
        assert db.scalar(text("SELECT count(*) FROM automation_executions")) == 1
    migrate("downgrade", "0015_agent_data_actions", succeeds=False)
    with engine.connect() as db:
        assert db.scalar(text("SELECT version_num FROM alembic_version")) == "0016_personal_state_sync"
    engine.dispose()


@pytest.mark.parametrize("mode", ["local", "core"])
def test_generation_3_preserves_real_0058_database(tmp_path, mode):
    verify_personal_upgrade("sqlite:///" + (tmp_path / (mode + ".db")).as_posix(), Path(__file__).parents[1], mode)
