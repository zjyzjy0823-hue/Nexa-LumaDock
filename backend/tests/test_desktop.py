import os
import json
import re
import subprocess
import sys
from urllib.parse import urlsplit
from pathlib import Path
from uuid import UUID

from sqlalchemy import create_engine, text
import pytest

from desktop_entry import DESKTOP_ORIGINS, desktop_parent_alive, prepare_desktop


@pytest.mark.skipif(os.name == "nt", reason="Unix desktop process ownership")
def test_desktop_detects_exited_process_owner():
    assert desktop_parent_alive(None)
    assert desktop_parent_alive(os.getpid())
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait(timeout=10)
    assert not desktop_parent_alive(child.pid)


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
        if os.name != "nt":
            assert (data_dir / "secret.key").stat().st_mode & 0o777 == 0o600
            assert data_dir.stat().st_mode & 0o777 == 0o700
        assert (data_dir / "core-connections").is_dir()
        assert (data_dir / "installation.id").is_file()
        assert str(UUID(first["NEXA_INSTALLATION_ID"])) == first["NEXA_INSTALLATION_ID"]
        assert (data_dir / "installation.id").read_text(encoding="ascii") == first["NEXA_INSTALLATION_ID"]
        assert first["DATABASE_URL"].startswith("sqlite:///")
        assert "http://tauri.localhost" in first["CORS_ORIGINS"]
        assert "tauri://localhost" in first["CORS_ORIGINS"].split(",")
        assert len(bytes.fromhex(first["JWT_SECRET"])) >= 32
        engine = create_engine(first["DATABASE_URL"])
        with engine.begin() as db:
            db.execute(text("CREATE TABLE desktop_test (value TEXT)"))
            db.execute(text("INSERT INTO desktop_test VALUES ('persisted')"))
        engine.dispose()
        if os.name != "nt":
            (data_dir / "secret.key").chmod(0o644)
        second = prepare_desktop(data_dir)
        if os.name != "nt":
            assert (data_dir / "secret.key").stat().st_mode & 0o777 == 0o600
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
    assert response.json() == {"status": "ok", "service": "nexa", "version": "0.6.1"}


def test_desktop_csp_allows_weather_service_origins():
    root = Path(__file__).resolve().parents[2]
    service = (root / "src/services/weather.ts").read_text(encoding="utf-8")
    origins = {f"{urlsplit(url).scheme}://{urlsplit(url).netloc}"
               for url in re.findall(r"https://[^'\"]+", service)}
    config = json.loads((root / "src-tauri/tauri.conf.json").read_text(encoding="utf-8"))
    for mode in ("csp", "devCsp"):
        allowed = config["app"]["security"][mode]["connect-src"].split()
        assert origins <= set(allowed), f"{mode} blocks weather origins: {origins - set(allowed)}"


@pytest.mark.parametrize("origin", ["http://tauri.localhost", "tauri://localhost"])
def test_desktop_cors_origin(monkeypatch, origin):
    from importlib import reload
    from app import main

    monkeypatch.setenv("CORS_ORIGINS", DESKTOP_ORIGINS)
    reloaded = reload(main)
    from fastapi.testclient import TestClient
    with TestClient(reloaded.app) as client:
        response = client.options("/api/health", headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
        })
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == origin
        denied = client.options("/api/health", headers={
            "Origin": "http://untrusted.localhost",
            "Access-Control-Request-Method": "GET",
        })
        assert denied.status_code == 400
