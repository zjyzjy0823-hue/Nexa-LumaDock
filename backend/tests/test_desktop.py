import os
from pathlib import Path
from uuid import UUID

from sqlalchemy import create_engine, text

from desktop_entry import prepare_desktop


def test_desktop_config_and_persistence(tmp_path: Path):
    data_dir = tmp_path / "Nexa Data"
    original = {key: os.environ.get(key) for key in ("NEXA_MODE", "DATABASE_URL", "JWT_SECRET",
                                                    "CORS_ORIGINS", "NEXA_INSTALLATION_ID", "NEXA_DATA_DIR")}
    try:
        first = prepare_desktop(data_dir)
        assert first["NEXA_MODE"] == "local"
        assert os.environ["NEXA_MODE"] == "local"
        assert first["NEXA_DATA_DIR"] == str(data_dir.resolve())
        assert os.environ["NEXA_DATA_DIR"] == str(data_dir.resolve())
        assert data_dir.is_dir()
        assert (data_dir / "logs").is_dir()
        assert (data_dir / "secret.key").is_file()
        assert (data_dir / "installation.id").is_file()
        assert str(UUID(first["NEXA_INSTALLATION_ID"])) == first["NEXA_INSTALLATION_ID"]
        assert (data_dir / "installation.id").read_text(encoding="ascii") == first["NEXA_INSTALLATION_ID"]
        assert first["DATABASE_URL"].startswith("sqlite:///")
        assert "http://tauri.localhost" in first["CORS_ORIGINS"]
        assert len(bytes.fromhex(first["JWT_SECRET"])) >= 32
        engine = create_engine(first["DATABASE_URL"])
        with engine.begin() as db:
            db.execute(text("CREATE TABLE desktop_test (value TEXT)"))
            db.execute(text("INSERT INTO desktop_test VALUES ('persisted')"))
        engine.dispose()
        second = prepare_desktop(data_dir)
        assert second["JWT_SECRET"] == first["JWT_SECRET"]
        assert second["NEXA_INSTALLATION_ID"] == first["NEXA_INSTALLATION_ID"]
        assert second["NEXA_DATA_DIR"] == first["NEXA_DATA_DIR"]
        with create_engine(second["DATABASE_URL"]).connect() as db:
            assert db.scalar(text("SELECT value FROM desktop_test")) == "persisted"
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_health_is_public(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "nexa", "version": "0.5.5"}


def test_desktop_cors_origin(monkeypatch):
    from importlib import reload
    from app import main

    monkeypatch.setenv("CORS_ORIGINS", "http://tauri.localhost,http://localhost:5173")
    reloaded = reload(main)
    from fastapi.testclient import TestClient
    with TestClient(reloaded.app) as client:
        response = client.options("/api/health", headers={
            "Origin": "http://tauri.localhost",
            "Access-Control-Request-Method": "GET",
        })
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "http://tauri.localhost"
        denied = client.options("/api/health", headers={
            "Origin": "http://untrusted.localhost",
            "Access-Control-Request-Method": "GET",
        })
        assert denied.status_code == 400
