import hashlib
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from app.database import get_db
from app.main import app
from app.models import (Agent, ApiKey, AutomationWorkflow, DataCollection, Device,
                        LedgerCategory, User, Website)


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
    with Session(engine) as session:
        session.add(User(id=1, username="owner", email="owner@example.test", password_hash="hash"))
        session.add(Device(id="device-1", user_id=1, name="Old PC", system="Windows", kind="desktop",
                           ip="127.0.0.1", cpu=12, memory=34, disk=56))
        session.add(Website(id="site-1", user_id=1, name="Site", url="https://example.com"))
        session.add(Agent(id="agent-1", user_id=1, name="Agent"))
        session.add(DataCollection(id="data-1", user_id=1, name="Data"))
        session.add(AutomationWorkflow(id="auto-1", user_id=1, name="Auto"))
        session.add(LedgerCategory(id="ledger-1", user_id=1, name="Food", type="expense"))
        session.add(ApiKey(id="key-1", user_id=1, token_hash="a" * 64, name="Key", last4="1234", scopes=[]))
        session.commit()
    with engine.begin() as conn:
        conn.execute(text("DROP INDEX ix_devices_token_hash"))
        for column in ("token_hash", "token_last4", "token_created_at", "hostname", "os", "os_version",
                       "architecture", "cpu_name", "memory_total", "memory_used", "disk_total", "disk_used",
                       "uptime_seconds", "local_ip", "client_version"):
            conn.execute(text(f"ALTER TABLE devices DROP COLUMN {column}"))
    engine.dispose()
    upgrade("head")
    engine = create_engine(f"sqlite:///{db_file}")
    with engine.connect() as conn:
        assert {"token_hash", "hostname", "memory_total", "client_version"}.issubset(
            {column["name"] for column in inspect(conn).get_columns("devices")})
        for table in ("users", "websites", "devices", "agents", "data_collections",
                      "automation_workflows", "ledger_categories", "api_keys"):
            assert conn.execute(text(f"SELECT count(*) FROM {table}")).scalar() == 1
        assert conn.execute(text("SELECT name, cpu, memory, disk, token_hash FROM devices WHERE id='device-1'")).one() == ("Old PC", 12, 34, 56, None)
    engine.dispose()
