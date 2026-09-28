"""Exercise the packaged Windows backend without importing the source app."""

import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from contextlib import closing
from pathlib import Path
from uuid import UUID


ROOT = Path(__file__).resolve().parents[1]
SIDECAR = ROOT / "src-tauri" / "binaries" / "nexa-backend-x86_64-pc-windows-msvc.exe"
BASE = "http://127.0.0.1:17800"


def request(path: str, payload: dict | None = None, token: str | None = None) -> dict:
    body = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with urllib.request.urlopen(urllib.request.Request(
        BASE + path, data=body, headers=headers,
        method="POST" if body is not None else "GET"), timeout=2) as response:
        return json.load(response)


def launch(data_dir: Path) -> subprocess.Popen:
    clean_env = os.environ.copy()
    clean_env["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
    clean_env.pop("PYTHONPATH", None)
    clean_env.pop("PYTHONHOME", None)
    process = subprocess.Popen([str(SIDECAR), "--data-dir", str(data_dir)],
                               creationflags=subprocess.CREATE_NO_WINDOW, env=clean_env)
    for _ in range(120):
        if process.poll() is not None:
            log_path = data_dir / "logs" / "backend.log"
            log = log_path.read_text(encoding="utf-8") if log_path.exists() else "No backend log was created"
            raise RuntimeError(f"Sidecar exited before readiness: {process.returncode}\n{log[-4000:]}")
        try:
            if request("/api/health")["status"] == "ok":
                return process
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            time.sleep(0.25)
    process.kill()
    raise RuntimeError("Sidecar readiness timeout")


def stop(process: subprocess.Popen, data_dir: Path) -> None:
    (data_dir / "backend.shutdown").write_text("quit", encoding="ascii")
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def main() -> None:
    data_dir = Path(tempfile.mkdtemp(prefix="NexaDesktopSmoke-")).resolve()
    try:
        first = launch(data_dir)
        try:
            with urllib.request.urlopen(urllib.request.Request(BASE + "/api/health", headers={
                "Origin": "http://tauri.localhost",
            }), timeout=2) as response:
                assert response.headers["Access-Control-Allow-Origin"] == "http://tauri.localhost"
            result = request("/api/v1/auth/register", {"username": "desktop_smoke", "password": "password123"})
            assert result["access_token"]
            token = result["access_token"]
            website = request("/api/v1/websites", {"name": "Smoke Site", "url": "https://example.com"}, token)
            device = request("/api/v1/devices", {"name": "Smoke Device", "kind": "desktop", "system": "Windows", "ip": "127.0.0.1"}, token)
            agent = request("/api/v1/agents", {"name": "Smoke Agent"}, token)
        finally:
            stop(first, data_dir)
        assert (data_dir / "nexa.db").is_file()
        assert (data_dir / "secret.key").is_file()
        installation_id = (data_dir / "installation.id").read_text(encoding="ascii")
        assert str(UUID(installation_id)) == installation_id
        assert (data_dir / "logs" / "backend.log").is_file()
        with closing(sqlite3.connect(data_dir / "nexa.db")) as connection:
            assert connection.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0011_sync_foundation"
        second = launch(data_dir)
        try:
            assert (data_dir / "installation.id").read_text(encoding="ascii") == installation_id
            result = request("/api/v1/auth/login", {"username": "desktop_smoke", "password": "password123"})
            assert result["access_token"]
            assert any(item["id"] == website["id"] for item in request("/api/v1/websites", token=token))
            assert any(item["id"] == device["id"] for item in request("/api/v1/devices", token=token))
            assert any(item["id"] == agent["id"] for item in request("/api/v1/agents", token=token))
        finally:
            stop(second, data_dir)
        assert token not in (data_dir / "logs" / "backend.log").read_text(encoding="utf-8")
        print("Packaged sidecar: health, registration, website/device/agent persistence, login PASS")
    finally:
        temp_root = Path(tempfile.gettempdir()).resolve()
        if data_dir.parent != temp_root or not data_dir.name.startswith("NexaDesktopSmoke-"):
            raise RuntimeError("Refusing to clean up unexpected smoke test directory")
        for attempt in range(15):
            try:
                shutil.rmtree(data_dir)
                break
            except PermissionError:
                if attempt == 14:
                    raise
                time.sleep(0.3)


if __name__ == "__main__":
    main()
