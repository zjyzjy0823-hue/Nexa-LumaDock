"""Upgrade an already seeded v0.5.3 database without reseeding Ledger."""
from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

from sqlalchemy import create_engine, MetaData, Table, select, text
from sqlalchemy.orm import sessionmaker
import pytest

from app.models import LocalMutation, SyncChange, LedgerCategory
from app.sync.local import seed_local_queue
from app.sync.service import ensure_core_sync_initialized


def verify_upgrade(database_url, backend, mode):
    def upgrade(revision):
        env = {**os.environ, "DATABASE_URL": database_url,
               "NEXA_MODE": "core" if database_url.startswith("postgresql") else "local"}
        result = subprocess.run([sys.executable, "-m", "alembic", "upgrade", revision],
                                cwd=backend, env=env, capture_output=True)
        assert result.returncode == 0, "Multi-entity migration failed"

    upgrade("0013_sync_engine")
    engine = create_engine(database_url)
    now = datetime.now(timezone.utc)
    workspace_id, category_id, website_id, collection_id, record_id, ledger_id = [str(uuid4()) for _ in range(6)]
    with engine.begin() as conn:
        metadata = MetaData()
        def add(table_name, **values):
            conn.execute(Table(table_name, metadata, autoload_with=conn).insert().values(**values))
        add("users", id=1, username="upgrade", email="upgrade@example.test", password_hash="hash", created_at=now, updated_at=now)
        add("workspaces", id=workspace_id, owner_user_id=1, name="Personal", kind="personal", created_at=now, updated_at=now)
        add("ledger_categories", id=ledger_id, user_id=1, workspace_id=workspace_id, name="Ledger", type="expense", icon="shopping", created_at=now, sync_revision=7)
        add("website_categories", id=category_id, user_id=1, workspace_id=workspace_id, name="Sites", order=2, created_at=now, updated_at=now)
        add("websites", id=website_id, user_id=1, workspace_id=workspace_id, category_id=category_id, name="Old site", url="https://example.com", favorite=True, order=3, created_at=now, updated_at=now)
        add("data_collections", id=collection_id, user_id=1, workspace_id=workspace_id, name="Collection", description="old", icon="custom", tone="blue", created_at=now, updated_at=now)
        add("data_records", id=record_id, collection_id=collection_id, name="Record", status="active", category="", data_json={"old": True}, created_at=now, updated_at=now)
        add("local_sync_state", workspace_id=workspace_id, cursor=7, queue_seeded_at=now, created_at=now, updated_at=now)
        add("sync_workspace_state", workspace_id=workspace_id, current_revision=7, initialized_at=now, created_at=now, updated_at=now)
        add("sync_changes", id=str(uuid4()), workspace_id=workspace_id, revision=7, entity_type="ledger.category", entity_id=ledger_id, operation="upsert", payload_json={"name": "Ledger", "type": "expense", "icon": "shopping"}, created_at=now)
    engine.dispose()
    upgrade("head")
    engine = create_engine(database_url)
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == "0015_agent_data_actions"
        assert conn.scalar(text("SELECT queue_seed_version FROM local_sync_state")) == 1
        assert conn.scalar(text("SELECT bootstrap_version FROM sync_workspace_state")) == 1
        for name in ("website_categories", "websites", "data_collections", "data_records"):
            assert conn.execute(text(f"SELECT sync_revision, deleted_at FROM {name}")).one() == (0, None)
        assert conn.scalar(text("SELECT name FROM websites")) == "Old site"
        assert conn.scalar(text("SELECT collection_id FROM data_records")) == collection_id
        assert conn.scalar(text("SELECT sync_revision FROM ledger_categories")) == 7
    factory = sessionmaker(bind=engine, autoflush=False)
    with factory() as db:
        # A rollback at the seed boundary must leave it recoverable.
        state = seed_local_queue(db, workspace_id) if mode == "local" else ensure_core_sync_initialized(db, workspace_id)
        db.rollback()
        for _ in range(2):
            state = seed_local_queue(db, workspace_id) if mode == "local" else ensure_core_sync_initialized(db, workspace_id)
            db.commit()
        expected = {"website.category", "website", "data.collection", "data.record"}
        if mode == "local":
            entries = db.scalars(select(LocalMutation)).all()
            assert len(entries) == 4 and {entry.entity_type for entry in entries} == expected
            assert state.queue_seed_version == 2 and state.cursor == 7
        else:
            changes = db.scalars(select(SyncChange).where(SyncChange.revision > 7).order_by(SyncChange.revision)).all()
            assert len(changes) == 4 and {row.entity_type for row in changes} == expected
            assert [row.revision for row in changes] == [8, 9, 10, 11]
            assert state.bootstrap_version == 2 and state.current_revision == 11
        assert db.get(LedgerCategory, ledger_id).sync_revision == 7
    engine.dispose()


@pytest.mark.parametrize("mode", ["local", "core"])
def test_upgrade_0013_preserves_rows_and_adds_only_new_generations(tmp_path, mode):
    verify_upgrade("sqlite:///" + (tmp_path / (mode + ".db")).as_posix(), Path(__file__).parents[1], mode)
