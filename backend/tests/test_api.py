import os
import subprocess
import sys
from pathlib import Path

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["JWT_SECRET"] = "test-secret-for-nexa"
os.environ["ALLOW_REGISTRATION"] = "true"

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app


def register(client: TestClient, username: str) -> str:
    response = client.post("/api/v1/auth/register", json={"username": username, "password": "password123"})
    assert response.status_code == 201
    return response.json()["access_token"]


def test_auth_dashboard_and_isolation():
    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(test_engine)

    def test_db():
        with Session(test_engine) as db:
            yield db

    app.dependency_overrides[get_db] = test_db
    with TestClient(app) as client:
        assert client.get("/api/dashboard").status_code == 401
        first = register(client, "first")
        second = register(client, "second")
        headers = {"Authorization": f"Bearer {first}"}
        other_headers = {"Authorization": f"Bearer {second}"}
        assert client.get("/api/auth/me", headers=headers).json()["username"] == "first"
        assert client.post("/api/v1/auth/login", json={"username": "first", "password": "bad"}).status_code == 401
        assert client.post("/api/v1/auth/login", json={"username": "first", "password": "password123"}).status_code == 200
        assert client.get("/api/auth/me", headers={"Authorization": "Bearer invalid"}).status_code == 401
        assert client.post("/api/v1/auth/register", json={"username": "first", "password": "password123"}).status_code == 409
        layout = client.get("/api/dashboard", headers=headers).json()["layout_json"]
        assert len(layout["widgets"]) == 9
        layout["widgets"][0]["position"]["x"] = 42
        saved = client.put("/api/dashboard/layout", json=layout, headers=headers)
        assert saved.status_code == 200
        assert saved.json()["layout_json"]["widgets"][0]["position"]["x"] == 42
        assert client.get("/api/dashboard", headers=other_headers).json()["layout_json"]["widgets"][0]["position"]["x"] == 0
        layout["widgets"][1]["id"] = layout["widgets"][0]["id"]
        assert client.put("/api/dashboard/layout", json=layout, headers=headers).status_code == 422
        for route in ("devices", "agents", "data", "automation"):
            assert client.get(f"/api/{route}", headers=headers).status_code == 200
    app.dependency_overrides.clear()
    test_engine.dispose()


def test_websites_crud_categories_and_ownership():
    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(test_engine)

    def test_db():
        with Session(test_engine) as db:
            yield db

    app.dependency_overrides[get_db] = test_db
    with TestClient(app) as client:
        first = {"Authorization": f"Bearer {register(client, 'website_first')}"}
        second = {"Authorization": f"Bearer {register(client, 'website_second')}"}
        assert client.post("/api/v1/auth/login", json={"username": "website_first", "password": "password123"}).status_code == 200
        assert client.get("/api/v1/auth/me", headers=first).json()["username"] == "website_first"
        category = client.post("/api/v1/website-categories", headers=first, json={"name": "工作", "order": 1})
        assert category.status_code == 201
        category_id = category.json()["id"]
        assert client.patch(f"/api/v1/website-categories/{category_id}", headers=first, json={"name": "工作资料"}).json()["name"] == "工作资料"
        created = client.post("/api/v1/websites", headers=first, json={"name": "Nexa", "url": "https://example.com", "categoryId": category_id, "favorite": True, "order": 2})
        assert created.status_code == 201
        website_id = created.json()["id"]
        assert client.get("/api/v1/websites", headers=first).json()[0]["id"] == website_id
        assert client.get("/api/v1/websites", headers=second).json() == []
        assert created.json()["lastVisitedAt"] is None
        assert client.post(f"/api/v1/websites/{website_id}/visit", headers=second).status_code == 404
        visited = client.post(f"/api/v1/websites/{website_id}/visit", headers=first)
        assert visited.status_code == 200 and visited.json()["lastVisitedAt"]
        assert client.get("/api/v1/websites?sort=recent", headers=first).json()[0]["id"] == website_id
        assert len(client.get("/api/v1/websites?search=nex&favorite=true&sort=name", headers=first).json()) == 1
        other_read = client.get(f"/api/v1/websites/{website_id}", headers=second)
        assert other_read.status_code == 404
        assert other_read.json()["error"]["code"] == "request_error"
        assert client.patch(f"/api/v1/websites/{website_id}", headers=second, json={"name": "Other"}).status_code == 404
        assert client.delete(f"/api/v1/websites/{website_id}", headers=second).status_code == 404
        assert client.post("/api/v1/websites", headers=second, json={"name": "X", "url": "https://example.com", "categoryId": category_id}).status_code == 404
        assert client.patch(f"/api/v1/websites/{website_id}", headers=first, json={"name": "Updated"}).json()["name"] == "Updated"
        assert client.post("/api/v1/websites", headers=first, json={"name": "Bad", "url": "javascript:alert(1)"}).status_code == 422
        assert client.delete(f"/api/v1/website-categories/{category_id}", headers=second).status_code == 404
        assert client.delete(f"/api/v1/website-categories/{category_id}", headers=first).status_code == 204
        assert client.get(f"/api/v1/websites/{website_id}", headers=first).json()["categoryId"] is None
        assert client.delete(f"/api/v1/websites/{website_id}", headers=first).status_code == 204
        assert client.get("/api/v1/websites", headers=first).json() == []
    app.dependency_overrides.clear()
    test_engine.dispose()


def test_devices_crud_heartbeat_and_ownership():
    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(test_engine)

    def test_db():
        with Session(test_engine) as db:
            yield db

    app.dependency_overrides[get_db] = test_db
    with TestClient(app) as client:
        first = {"Authorization": f"Bearer {register(client, 'device_first')}"}
        second = {"Authorization": f"Bearer {register(client, 'device_second')}"}
        created = client.post("/api/v1/devices", headers=first, json={
            "name": "工作电脑", "system": "Linux", "ip": "192.168.1.10", "kind": "desktop", "location": "书房"})
        assert created.status_code == 201
        device_id = created.json()["id"]
        assert created.json()["online"] is False
        assert created.json()["lastSeenAt"] is None
        assert client.get("/api/v1/devices", headers=second).json() == []
        for response in (
            client.get(f"/api/v1/devices/{device_id}", headers=second),
            client.patch(f"/api/v1/devices/{device_id}", headers=second, json={"name": "非法修改"}),
            client.post(f"/api/v1/devices/{device_id}/heartbeat", headers=second, json={"cpu": 1, "memory": 2, "disk": 3}),
            client.delete(f"/api/v1/devices/{device_id}", headers=second),
        ):
            assert response.status_code == 404
        assert client.patch(f"/api/v1/devices/{device_id}", headers=first, json={"name": "主机"}).json()["name"] == "主机"
        assert client.post(f"/api/v1/devices/{device_id}/heartbeat", headers=first,
                           json={"cpu": 101, "memory": 20, "disk": 30}).status_code == 422
        heartbeat = client.post(f"/api/v1/devices/{device_id}/heartbeat", headers=first,
                                json={"cpu": 24, "memory": 40, "disk": 55, "battery": 80})
        assert heartbeat.status_code == 200
        assert heartbeat.json()["online"] is True
        assert heartbeat.json()["activity"] == [24]
        assert client.get(f"/api/v1/devices/{device_id}", headers=first).json()["battery"] == 80
        assert client.delete(f"/api/v1/devices/{device_id}", headers=first).status_code == 204
        assert client.get("/api/v1/devices", headers=first).json() == []
    app.dependency_overrides.clear()
    test_engine.dispose()


def test_agents_tasks_heartbeat_and_ownership():
    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(test_engine)

    def test_db():
        with Session(test_engine) as db:
            yield db

    app.dependency_overrides[get_db] = test_db
    with TestClient(app) as client:
        first = {"Authorization": f"Bearer {register(client, 'agent_first')}"}
        second = {"Authorization": f"Bearer {register(client, 'agent_second')}"}
        created = client.post("/api/v1/agents", headers=first, json={
            "name": "Nova", "role": "整理资料", "model": "本地模型", "description": "测试"})
        assert created.status_code == 201
        agent_id = created.json()["id"]
        assert created.json()["status"] == "idle"
        assert client.get("/api/v1/agents", headers=second).json() == []
        assert client.get(f"/api/v1/agents/{agent_id}", headers=second).status_code == 404
        assert client.patch(f"/api/v1/agents/{agent_id}", headers=second, json={"name": "非法修改"}).status_code == 404
        assert client.post(f"/api/v1/agents/{agent_id}/heartbeat", headers=second, json={"status": "running"}).status_code == 404
        assert client.delete(f"/api/v1/agents/{agent_id}", headers=second).status_code == 404
        assert client.patch(f"/api/v1/agents/{agent_id}", headers=first, json={"enabled": False}).json()["status"] == "offline"
        assert client.post(f"/api/v1/agents/{agent_id}/heartbeat", headers=first, json={"status": "running"}).status_code == 409
        assert client.patch(f"/api/v1/agents/{agent_id}", headers=first, json={"enabled": True, "name": "Nova 2"}).json()["name"] == "Nova 2"
        assert client.post(f"/api/v1/agents/{agent_id}/heartbeat", headers=first,
                           json={"status": "running"}).json()["status"] == "running"
        task = client.post(f"/api/v1/agents/{agent_id}/tasks", headers=first,
                           json={"title": "整理报告", "description": "周报"})
        assert task.status_code == 201
        task_id = task.json()["id"]
        assert client.patch(f"/api/v1/agents/{agent_id}/tasks/{task_id}", headers=second,
                            json={"status": "completed"}).status_code == 404
        assert client.delete(f"/api/v1/agents/{agent_id}/tasks/{task_id}", headers=second).status_code == 404
        updated = client.patch(f"/api/v1/agents/{agent_id}/tasks/{task_id}", headers=first,
                               json={"status": "completed"})
        assert updated.json()["status"] == "completed"
        persisted = client.get(f"/api/v1/agents/{agent_id}", headers=first).json()
        assert persisted["tasks"][0]["title"] == "整理报告"
        assert persisted["successRate"] == "100%"
        assert persisted["logs"]
        assert client.delete(f"/api/v1/agents/{agent_id}/tasks/{task_id}", headers=first).status_code == 204
        assert client.delete(f"/api/v1/agents/{agent_id}", headers=first).status_code == 204
        assert client.get("/api/v1/agents", headers=first).json() == []
    app.dependency_overrides.clear()
    test_engine.dispose()


def test_migration_upgrades_existing_users(tmp_path: Path):
    database_file = tmp_path / "legacy.db"
    old_engine = create_engine(f"sqlite:///{database_file}")
    with old_engine.begin() as connection:
        connection.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR(80), email VARCHAR(255), password_hash VARCHAR(255), avatar VARCHAR(500), created_at DATETIME)"))
        connection.execute(text("INSERT INTO users (id, username, email, password_hash, created_at) VALUES (1, 'legacy', 'legacy@example.com', 'hash', '2024-01-01')"))
    old_engine.dispose()
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{database_file}"}
    result = subprocess.run([sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"],
                            cwd=Path(__file__).parents[1], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    upgraded = create_engine(f"sqlite:///{database_file}")
    assert {"websites", "website_categories", "user_preferences", "devices", "agents", "agent_tasks", "agent_events"}.issubset(inspect(upgraded).get_table_names())
    with upgraded.connect() as connection:
        assert connection.execute(text("SELECT updated_at FROM users WHERE id = 1")).scalar() is not None
    upgraded.dispose()


def test_websocket_ping_pong():
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as socket:
            socket.send_json({"type": "ping", "payload": {"id": 1}})
            event = socket.receive_json()
            assert event["type"] == "pong"
            assert event["source"] == "nexa"
            assert event["payload"] == {"id": 1}
            assert event["timestamp"]
