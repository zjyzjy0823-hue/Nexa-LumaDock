import os

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["JWT_SECRET"] = "test-secret"

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app


def register(client: TestClient, username: str) -> str:
    response = client.post("/api/auth/register", json={"username": username, "email": f"{username}@example.com", "password": "password123"})
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
        assert client.post("/api/auth/login", json={"email": "first@example.com", "password": "bad"}).status_code == 401
        assert client.post("/api/auth/login", json={"email": "first@example.com", "password": "password123"}).status_code == 200
        assert client.get("/api/auth/me", headers={"Authorization": "Bearer invalid"}).status_code == 401
        assert client.post("/api/auth/register", json={"username": "first", "email": "another@example.com", "password": "password123"}).status_code == 409
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
