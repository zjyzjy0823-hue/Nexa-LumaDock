"""Data records carry their own tenant ownership (062-03 S1)."""
import os
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys

import pytest
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import DataCollection, DataRecord, User, Workspace
from app.sync.adapters import get_adapter
from app.sync.adapters.data import RecordData

BACKEND = Path(__file__).parents[1]
ROOT = "/api/v1/data"


def session(client) -> Session:
    return next(client.app.dependency_overrides[get_db]())


def collection_for(client, headers, name="Servers"):
    response = client.post(f"{ROOT}/collections", headers=headers, json={"name": name})
    assert response.status_code == 201
    return response.json()["id"]


def record_for(client, headers, collection_id, name="Mac mini"):
    response = client.post(f"{ROOT}/collections/{collection_id}/records", headers=headers, json={"name": name})
    assert response.status_code == 201
    return response.json()["id"]


def test_created_record_inherits_collection_tenancy(client, users):
    owner, _ = users
    collection_id = collection_for(client, owner)
    record_id = record_for(client, owner, collection_id)

    db = session(client)
    collection = db.get(DataCollection, collection_id)
    record = db.get(DataRecord, record_id)
    assert record.user_id == collection.user_id
    assert record.workspace_id == collection.workspace_id
    assert db.get(Workspace, record.workspace_id).owner_user_id == collection.user_id
    db.close()


def test_sync_adapter_create_writes_parent_tenancy(client, users):
    owner, _ = users
    collection_id = collection_for(client, owner)

    db = session(client)
    collection = db.get(DataCollection, collection_id)
    adapter = get_adapter("data.record")
    data = RecordData(collectionId=collection_id, name="Synced")
    # The parent collection stays authoritative: routing arguments cannot
    # place a child in a different tenant than the collection it belongs to.
    item = adapter.create(db, "record-from-sync", 0, "workspace-from-sync", data)
    adapter.apply_data(item, data)
    db.add(item)
    db.flush()
    assert item.user_id == collection.user_id
    assert item.workspace_id == collection.workspace_id
    assert adapter.workspace_id(db, item) == collection.workspace_id
    db.rollback()
    db.close()


def test_other_workspace_cannot_reach_record(client, users):
    owner, stranger = users
    collection_id = collection_for(client, owner)
    record_id = record_for(client, owner, collection_id)

    assert client.get(f"{ROOT}/records/{record_id}", headers=stranger).status_code == 404
    assert client.get(f"{ROOT}/collections/{collection_id}/records", headers=stranger).status_code == 404
    assert client.patch(f"{ROOT}/records/{record_id}", headers=stranger,
                        json={"name": "hijack"}).status_code == 404
    assert client.delete(f"{ROOT}/records/{record_id}", headers=stranger).status_code == 404

    # A record whose own tenant column disagrees with the collection is not
    # served on the strength of the collection lookup alone.
    db = session(client)
    record = db.get(DataRecord, record_id)
    other_workspace = db.scalar(select(Workspace).join(User, User.id == Workspace.owner_user_id)
                                .where(User.username == "owner_b"))
    assert other_workspace is not None
    record.workspace_id = other_workspace.id
    db.commit()
    db.close()

    assert client.get(f"{ROOT}/records/{record_id}", headers=owner).status_code == 404

    db = session(client)
    db.get(DataRecord, record_id).workspace_id = db.get(DataCollection, collection_id).workspace_id
    db.commit()
    db.close()
    assert client.get(f"{ROOT}/records/{record_id}", headers=owner).status_code == 200


def migrate(database: Path, direction: str, revision: str):
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", direction, revision],
        cwd=BACKEND,
        env={**os.environ, "DATABASE_URL": f"sqlite:///{database}", "STUDIOLO_MODE": "local"},
        capture_output=True,
        text=True,
    )


def upgrade(database: Path, revision: str):
    result = migrate(database, "upgrade", revision)
    assert result.returncode == 0, result.stderr
    return result


def seed_historical_records(database: Path):
    """Historical 0017 rows: data_records has no tenancy columns yet."""
    engine = create_engine(f"sqlite:///{database}")
    now = datetime.now(timezone.utc)
    with engine.begin() as conn:
        for user_id, workspace_id, collection_id, record_id in (
            (1, "workspace-1", "collection-1", "record-1"),
            (2, "workspace-2", "collection-2", "record-2"),
        ):
            conn.execute(text("INSERT INTO users (id, username, email, password_hash, created_at, updated_at) "
                              "VALUES (:id, :name, :mail, 'hash', :now, :now)"),
                         {"id": user_id, "name": f"owner_{user_id}", "mail": f"owner_{user_id}@example.test",
                          "now": now})
            conn.execute(text("INSERT INTO workspaces (id, owner_user_id, name, kind, created_at, updated_at) "
                              "VALUES (:id, :owner, 'Personal', 'personal', :now, :now)"),
                         {"id": workspace_id, "owner": user_id, "now": now})
            conn.execute(text("INSERT INTO data_collections (id, user_id, workspace_id, name, description, icon, "
                              "tone, created_at, updated_at) VALUES (:id, :owner, :workspace, :name, '', 'custom', "
                              "'blue', :now, :now)"),
                         {"id": collection_id, "owner": user_id, "workspace": workspace_id,
                          "name": f"Collection {user_id}", "now": now})
            conn.execute(text("INSERT INTO data_records (id, collection_id, name, status, category, data_json, "
                              "created_at, updated_at) VALUES (:id, :collection, :name, 'active', '', '{}', :now, :now)"),
                         {"id": record_id, "collection": collection_id, "name": f"Record {user_id}", "now": now})
    engine.dispose()


def test_upgrade_0017_to_0018_backfills_record_tenancy(tmp_path):
    database = tmp_path / "record-tenancy.db"
    upgrade(database, "0017_automation_engine")
    seed_historical_records(database)
    upgrade(database, "head")

    engine = create_engine(f"sqlite:///{database}")
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == "0020_fleet_nodes_and_blobs"
        rows = conn.execute(text("SELECT r.id, r.user_id, r.workspace_id, c.user_id, c.workspace_id "
                                 "FROM data_records r JOIN data_collections c ON c.id = r.collection_id "
                                 "ORDER BY r.id")).all()
        assert rows == [("record-1", 1, "workspace-1", 1, "workspace-1"),
                        ("record-2", 2, "workspace-2", 2, "workspace-2")]
        columns = {column["name"]: column for column in inspect(conn).get_columns("data_records")}
        assert not columns["user_id"]["nullable"] and not columns["workspace_id"]["nullable"]
        assert {tuple(fk["constrained_columns"]) for fk in inspect(conn).get_foreign_keys("data_records")} == {
            ("collection_id",), ("user_id",), ("workspace_id",)}
        indexes = {index["name"] for index in inspect(conn).get_indexes("data_records")}
        assert {"ix_data_records_user_id", "ix_data_records_workspace_id"} <= indexes
    with engine.connect() as conn:
        with pytest.raises(IntegrityError):
            conn.execute(text("INSERT INTO data_records (id, collection_id, name, status, category, data_json, "
                              "created_at, updated_at) VALUES ('record-3', 'collection-1', 'New', 'active', '', "
                              "'{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"))
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM data_records")) == 2
    engine.dispose()

    result = migrate(database, "downgrade", "0017_automation_engine")
    assert result.returncode == 0, result.stderr
    engine = create_engine(f"sqlite:///{database}")
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == "0017_automation_engine"
        assert "user_id" not in {column["name"] for column in inspect(conn).get_columns("data_records")}
        assert conn.scalar(text("SELECT count(*) FROM data_records")) == 2
        assert conn.scalar(text("SELECT name FROM data_records WHERE id='record-1'")) == "Record 1"
    engine.dispose()
    upgrade(database, "head")


def test_upgrade_refuses_orphaned_records(tmp_path):
    database = tmp_path / "record-orphan.db"
    upgrade(database, "0017_automation_engine")
    seed_historical_records(database)
    engine = create_engine(f"sqlite:///{database}")
    with engine.begin() as conn:
        assert conn.scalar(text("PRAGMA foreign_keys")) == 0
        conn.execute(text("DELETE FROM data_collections WHERE id='collection-2'"))
    engine.dispose()

    result = migrate(database, "upgrade", "head")
    assert result.returncode != 0
    assert "no matching data_collections row" in result.stderr
    assert "1 rows" in result.stderr


def test_downgrade_refuses_diverged_tenancy(tmp_path):
    database = tmp_path / "record-diverged.db"
    upgrade(database, "0017_automation_engine")
    seed_historical_records(database)
    upgrade(database, "head")
    engine = create_engine(f"sqlite:///{database}")
    with engine.begin() as conn:
        conn.execute(text("UPDATE data_records SET workspace_id='workspace-1' WHERE id='record-2'"))
    engine.dispose()

    result = migrate(database, "downgrade", "0017_automation_engine")
    assert result.returncode != 0
    assert "export it before downgrading" in result.stderr
