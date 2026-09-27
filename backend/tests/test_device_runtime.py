import hashlib
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import MetaData, Table, create_engine, inspect, text
from sqlalchemy.orm import Session

from app.database import get_db
from app.main import app
from app.models import Device


def make_device(client, headers):
    response = client.post("/api/v1/devices", headers=headers,
                           json={"name": "Windows PC", "system": "Windows 11", "ip": "192.168.1.2"})
    assert response.status_code == 201
    return response.json()["id"]


def generate(client, headers, device_id):
    response = client.post(f"/api/v1/devices/{device_id}/token", headers=headers)
    assert response.status_code == 201
    assert response.headers["Cache-Control"] == "no-store"
    return response.json()


def payload(**changes):
    result = {"hostname": "DESKTOP-TEST", "os": "Windows", "osVersion": "Windows 11",
              "architecture": "AMD64", "cpuName": "Example CPU", "cpu": 23.5,
              "memory": 62.1, "memoryTotal": 34359738368, "memoryUsed": 21345992704,
              "disk": 48.2, "diskTotal": 1000204886016, "diskUsed": 482343000000,
              "battery": None, "uptimeSeconds": 92131, "localIp": "192.168.1.15",
              "clientVersion": "0.1.0"}
    result.update(changes)
    return result


def test_device_token_heartbeat_isolation_and_lifecycle(client, users):
    owner, other = users
    device_id = make_device(client, owner)
    other_device_id = make_device(client, other)
    assert client.post(f"/api/v1/devices/{device_id}/token", headers=other).status_code == 404
    first = generate(client, owner, device_id)
    assert first["token"].startswith("nd_live_")
    assert first["last4"] == first["token"][-4:]
    db_iter = app.dependency_overrides[get_db]()
    db = next(db_iter)
    try:
        item = db.get(Device, device_id)
        assert item.token_hash == hashlib.sha256(first["token"].encode()).hexdigest()
        assert first["token"] not in repr(item.__dict__)
    finally:
        db_iter.close()
    headers = {"Authorization": f"Bearer {first['token']}"}
    assert client.post("/api/device/heartbeat", json=payload()).status_code == 401
    assert client.post("/api/device/heartbeat", headers={"Authorization": "Bearer nd_live_invalid"}, json=payload()).status_code == 401
    heartbeat = client.post("/api/device/heartbeat", headers=headers, json=payload())
    assert heartbeat.status_code == 200
    assert heartbeat.json()["deviceId"] == device_id
    assert heartbeat.json()["online"] is True
    record = client.get(f"/api/v1/devices/{device_id}", headers=owner).json()
    assert record["hostname"] == "DESKTOP-TEST"
    assert (record["cpu"], record["memory"], record["disk"], record["battery"]) == (24, 62, 48, None)
    assert record["memoryTotal"] == 34359738368
    assert record["diskUsed"] == 482343000000
    assert record["lastSeenAt"] is not None
    assert record["tokenLast4"] == first["last4"]
    for field in ("lastSeenAt", "createdAt", "tokenCreatedAt"):
        assert record[field].endswith("+00:00")
    assert "token" not in record
    assert client.get(f"/api/v1/devices/{other_device_id}", headers=other).json()["lastSeenAt"] is None
    for path in ("/api/v1/devices", "/api/v1/settings", "/api/v1/agents",
                 "/api/v1/ledger/summary", "/api/devices", "/api/api-keys"):
        assert client.get(path, headers=headers).status_code == 401
    assert client.delete(f"/api/v1/devices/{device_id}", headers=headers).status_code == 401
    assert client.patch(f"/api/v1/devices/{device_id}", headers=headers, json={"name": "bad"}).status_code == 401
    assert client.post("/api/api-keys", headers=headers,
                       json={"name": "bad", "scopes": ["Devices"]}).status_code == 401
    assert client.patch("/api/v1/settings", headers=headers, json={"theme": "dark"}).status_code == 401
    second = generate(client, owner, device_id)
    assert second["token"] != first["token"]
    assert client.post("/api/device/heartbeat", headers=headers, json=payload()).status_code == 401
    second_headers = {"Authorization": f"Bearer {second['token']}"}
    assert client.post("/api/device/heartbeat", headers=second_headers, json=payload()).status_code == 200
    assert client.delete(f"/api/v1/devices/{device_id}/token", headers=owner).status_code == 204
    assert client.post("/api/device/heartbeat", headers=second_headers, json=payload()).status_code == 401
    third = generate(client, owner, device_id)
    assert client.delete(f"/api/v1/devices/{device_id}", headers=owner).status_code == 204
    assert client.post("/api/device/heartbeat", headers={"Authorization": f"Bearer {third['token']}"}, json=payload()).status_code == 401


def test_device_runtime_validation_and_offline_window(client, users):
    owner, _ = users
    device_id = make_device(client, owner)
    token = generate(client, owner, device_id)["token"]
    headers = {"Authorization": f"Bearer {token}"}
    for invalid in (payload(cpu=100.1), payload(memory=-1), payload(uptimeSeconds=-1),
                    payload(hostname="x" * 121), payload(deviceId="forbidden"),
                    payload(memoryTotal=-2)):
        assert client.post("/api/device/heartbeat", headers=headers, json=invalid).status_code == 422
    assert client.post("/api/device/heartbeat", headers=headers, json=payload(battery=None)).status_code == 200
    db_iter = app.dependency_overrides[get_db]()
    db = next(db_iter)
    try:
        item = db.get(Device, device_id)
        item.last_seen_at = datetime.now(timezone.utc) - timedelta(seconds=121)
        db.commit()
    finally:
        db_iter.close()
    assert client.get(f"/api/v1/devices/{device_id}", headers=owner).json()["online"] is False


def test_upgrade_from_0005_preserves_device_and_other_rows(tmp_path: Path):
    db_file = tmp_path / "before_runtime.db"
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{db_file}"}
    backend = Path(__file__).parents[1]

    def upgrade(target):
        result = subprocess.run([sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", target],
                                cwd=backend, env=env, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr

    upgrade("0005_persistent_pages")
    engine = create_engine(f"sqlite:///{db_file}")
    old_columns = {column["name"] for column in inspect(engine).get_columns("devices")}
    assert "token_hash" not in old_columns
    assert "hostname" not in old_columns
    old_schema = MetaData()
    def insert_old(conn, table_name, **values):
        table = Table(table_name, old_schema, autoload_with=conn)
        conn.execute(table.insert().values(**values))

    now = datetime.now(timezone.utc)
    with engine.begin() as conn:
        insert_old(conn, "users", id=1, username="owner", email="owner@example.test", password_hash="hash",
                   created_at=now, updated_at=now)
        insert_old(conn, "devices", id="device-1", user_id=1, name="Old PC", system="Windows", kind="mac",
                   ip="127.0.0.1", location="", cpu=12, memory=34, disk=56, activity_json=[],
                   created_at=now, updated_at=now)
        insert_old(conn, "websites", id="site-1", user_id=1, name="Site", url="https://example.com",
                   favorite=False, order=0, created_at=now, updated_at=now)
        insert_old(conn, "agents", id="agent-1", user_id=1, name="Agent", role="assistant", description="",
                   model="none", workspace="default", avatar="spark", enabled=True, runtime_status="idle",
                   created_at=now, updated_at=now)
        insert_old(conn, "agent_tasks", id="task-1", agent_id="agent-1", title="Old task",
                   description="", status="queued", created_at=now, updated_at=now)
        insert_old(conn, "agent_events", id="event-1", agent_id="agent-1", level="info",
                   message="Old event", created_at=now)
        insert_old(conn, "data_collections", id="data-1", user_id=1, name="Data", description="",
                   icon="custom", tone="blue", created_at=now, updated_at=now)
        insert_old(conn, "data_records", id="record-1", collection_id="data-1", name="Old record",
                   status="active", category="", data_json={}, created_at=now, updated_at=now)
        insert_old(conn, "automation_workflows", id="auto-1", user_id=1, name="Auto", description="",
                   enabled=True, trigger_type="manual", trigger_config_json={}, workflow_json=[],
                   created_at=now, updated_at=now)
        insert_old(conn, "automation_executions", id="execution-1", workflow_id="auto-1", status="success",
                   started_at=now, finished_at=now, message="", result_json={})
        insert_old(conn, "ledger_categories", id="ledger-1", user_id=1, name="Food", type="expense",
                   icon="shopping", created_at=now)
        insert_old(conn, "ledger_transactions", id="transaction-1", user_id=1, category_id="ledger-1",
                   type="expense", amount=12, description="Old purchase", merchant="", note="",
                   occurred_at=now, created_at=now, updated_at=now)
        insert_old(conn, "api_keys", id="key-1", user_id=1, token_hash="a" * 64, name="Key", last4="1234",
                   scopes=[], is_active=True, created_at=now)
    engine.dispose()
    upgrade("head")
    engine = create_engine(f"sqlite:///{db_file}")
    with engine.connect() as conn:
        assert {"token_hash", "hostname", "memory_total", "client_version"}.issubset(
            {column["name"] for column in inspect(conn).get_columns("devices")})
        for table in ("users", "websites", "devices", "agents", "agent_tasks", "agent_events",
                      "data_collections", "data_records", "automation_workflows", "automation_executions",
                      "ledger_categories", "ledger_transactions", "api_keys"):
            assert conn.execute(text(f"SELECT count(*) FROM {table}")).scalar() == 1
        assert conn.execute(text("SELECT name, kind, cpu, memory, disk, token_hash, hostname, memory_total, client_version FROM devices WHERE id='device-1'")).one() == ("Old PC", "laptop", 12, 34, 56, None, None, None, None)
    engine.dispose()
