"""Exercise the native packaged backend without importing the source app."""

import argparse
import json
import os
import platform
import shutil
import sqlite3
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from contextlib import closing
from pathlib import Path
from uuid import UUID

from desktop_target import require_native, resolve_target, sidecar_path


ROOT = Path(__file__).resolve().parents[1]
SIDECAR: Path
with socket.socket() as listener:
    listener.bind(("127.0.0.1", 0))
    PORT = listener.getsockname()[1]
BASE = f"http://127.0.0.1:{PORT}"


def request(path: str, payload: dict | None = None, token: str | None = None,
            method: str | None = None) -> dict | list | None:
    body = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with urllib.request.urlopen(urllib.request.Request(
        BASE + path, data=body, headers=headers,
        method=method or ("POST" if body is not None else "GET")), timeout=2) as response:
        return json.load(response) if response.status != 204 else None


def launch(data_dir: Path, parent_pid: int | None = None) -> subprocess.Popen:
    clean_env = os.environ.copy()
    clean_env["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32") if os.name == "nt" else "/usr/bin:/bin"
    clean_env.pop("PYTHONPATH", None)
    clean_env.pop("PYTHONHOME", None)
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    arguments = [str(SIDECAR), "--data-dir", str(data_dir), "--port", str(PORT)]
    if parent_pid is not None:
        arguments.extend(["--parent-pid", str(parent_pid)])
    process = subprocess.Popen(arguments,
                               env=clean_env, **options)
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
    global SIDECAR
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target")
    args = parser.parse_args()
    target = resolve_target(args.target)
    require_native(target)
    SIDECAR = sidecar_path(target)
    if not SIDECAR.is_file() or not os.access(SIDECAR, os.X_OK):
        parser.error(f"Build the executable sidecar first: {SIDECAR}")
    data_dir = Path(tempfile.mkdtemp(prefix="NexaDesktopSmoke-")).resolve()
    try:
        first = launch(data_dir)
        try:
            assert request("/api/health") == {"status": "ok", "service": "nexa", "version": "0.6.0"}
            for origin in ("http://tauri.localhost", "tauri://localhost"):
                with urllib.request.urlopen(urllib.request.Request(BASE + "/api/health", headers={
                    "Origin": origin,
                }), timeout=2) as response:
                    assert response.headers["Access-Control-Allow-Origin"] == origin
            result = request("/api/v1/auth/register", {"username": "desktop_smoke", "password": "password123"})
            assert result["access_token"]
            token = result["access_token"]
            website_category = request("/api/v1/website-categories", {"name": "Smoke Sites"}, token)
            website = request("/api/v1/websites", {"name": "Smoke Site", "url": "https://example.com",
                              "categoryId": website_category["id"]}, token)
            collection = request("/api/v1/data/collections", {"name": "Smoke Data"}, token)
            record = request(f"/api/v1/data/collections/{collection['id']}/records",
                             {"name": "Smoke Record", "data_json": {"value": 42}}, token)
            device = request("/api/v1/devices", {"name": "Smoke Device", "kind": "desktop", "system": platform.system(), "ip": "127.0.0.1"}, token)
            agent = request("/api/v1/agents", {"name": "Smoke Agent"}, token)
            assert agent["dataScopes"] == []
            request(f"/api/v1/agents/{agent['id']}", {"dataScopes": ["ledger:write", "ledger:read"]}, token, method="PATCH")
            agent_token = request(f"/api/v1/agents/{agent['id']}/token", {}, token)["token"]
            action = {"actionId": str(UUID("05505505-5055-4055-8055-055055055055")), "action": "ledger.transaction.create",
                      "arguments": {"type": "expense", "amount": "38.00", "description": "Agent coffee", "occurredAt": "2026-09-30T09:00:00Z"}}
            receipt = request("/api/agent/actions/execute", action, agent_token)
            assert not receipt["replayed"]
            assert request("/api/agent/actions/execute", action, agent_token)["replayed"]
            assert request("/api/agent/actions/catalog", token=agent_token)["dataScopes"] == ["ledger:write", "ledger:read"]
            assert request("/api/dashboard", token=token)["id"]
            preferences = request("/api/v1/settings", {"theme": "dark", "appearance": {"accent": "mint"}}, token, method="PATCH")
            assert preferences["theme"] == "dark"
            personal_layout = request("/api/dashboard", token=token)["layout_json"]
            personal_layout["widgets"] = personal_layout["widgets"][:3]
            request("/api/dashboard/layout", personal_layout, token, method="PUT")
            workflow = request("/api/v1/automations", {"name": "Packaged Daily Summary", "trigger_type": "schedule",
                "trigger_config_json": {"cron": "0 9 * * *"}, "workflow_json": [{"kind": "DO", "text": "Notify"}]}, token)
            category = request("/api/v1/ledger/categories", {"name": "Food", "type": "expense"}, token)
            transaction = request("/api/v1/ledger/transactions", {
                "category_id": category["id"], "type": "expense", "amount": "38.00",
                "description": "Offline lunch", "occurred_at": "2026-09-28T12:00:00Z"}, token)
            assert request("/api/v1/sync/status", token=token)["pending"] == 10
        finally:
            stop(first, data_dir)
        assert (data_dir / "nexa.db").is_file()
        assert (data_dir / "secret.key").is_file()
        secret_bytes = (data_dir / "secret.key").read_bytes()
        if os.name != "nt":
            assert (data_dir / "secret.key").stat().st_mode & 0o777 == 0o600
        installation_id = (data_dir / "installation.id").read_text(encoding="ascii")
        assert str(UUID(installation_id)) == installation_id
        assert (data_dir / "logs" / "backend.log").is_file()
        with closing(sqlite3.connect(data_dir / "nexa.db")) as connection:
            assert connection.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0017_automation_engine"
            assert connection.execute("SELECT count(*) FROM local_mutation_queue WHERE status='pending'").fetchone()[0] == 10
            assert {row[0] for row in connection.execute("SELECT entity_type FROM local_mutation_queue WHERE status='pending'")} >= {
                "user.preferences", "dashboard.layout", "automation.definition"}
            assert connection.execute("SELECT count(*) FROM agent_action_logs WHERE status='ok'").fetchone()[0] == 1
            assert connection.execute("SELECT queue_seed_version FROM local_sync_state").fetchone()[0] == 3
        second = launch(data_dir)
        try:
            assert (data_dir / "installation.id").read_text(encoding="ascii") == installation_id
            assert (data_dir / "secret.key").read_bytes() == secret_bytes
            result = request("/api/v1/auth/login", {"username": "desktop_smoke", "password": "password123"})
            assert result["access_token"]
            assert request("/api/v1/settings", token=token)["theme"] == "dark"
            assert request("/api/dashboard", token=token)["layout_json"] == personal_layout
            assert request(f"/api/v1/automations/{workflow['id']}", token=token)["name"] == "Packaged Daily Summary"
            assert any(item["id"] == website["id"] for item in request("/api/v1/websites", token=token))
            assert request(f"/api/v1/data/collections/{collection['id']}", token=token)["recordCount"] == 1
            assert request(f"/api/v1/data/collections/{collection['id']}/records", token=token)[0]["id"] == record["id"]
            assert request(f"/api/v1/websites/{website['id']}/visit", token=token, method="POST")["lastVisitedAt"]
            assert any(item["id"] == device["id"] for item in request("/api/v1/devices", token=token))
            assert any(item["id"] == agent["id"] for item in request("/api/v1/agents", token=token))
            assert any(item["id"] == transaction["id"] for item in request("/api/v1/ledger/transactions", token=token))
            edited = request(f"/api/v1/ledger/transactions/{transaction['id']}",
                             {"description": "Offline edited lunch"}, token, method="PATCH")
            assert edited["description"] == "Offline edited lunch"
            transient = request("/api/v1/ledger/transactions", {
                "type": "expense", "amount": "1.00", "description": "Transient",
                "occurred_at": "2026-09-28T12:00:00Z"}, token)
            request(f"/api/v1/ledger/transactions/{transient['id']}", token=token, method="DELETE")
            assert request("/api/v1/sync/status", token=token)["pending"] == 10
            request(f"/api/v1/website-categories/{website_category['id']}", token=token, method="DELETE")
            assert request(f"/api/v1/websites/{website['id']}", token=token)["categoryId"] is None
            request(f"/api/v1/data/collections/{collection['id']}", token=token, method="DELETE")
            assert request("/api/data", token=token)["totalRecords"] == 0
            request(f"/api/v1/websites/{website['id']}", token=token, method="DELETE")
            assert request("/api/v1/websites", token=token) == []
            assert request("/api/v1/sync/status", token=token)["pending"] == 6
        finally:
            stop(second, data_dir)
        with closing(sqlite3.connect(data_dir / "nexa.db")) as connection:
            rows = connection.execute("SELECT entity_type, entity_id, base_revision, payload_json "
                                      "FROM local_mutation_queue ORDER BY entity_type").fetchall()
            assert len(rows) == 6
            assert {row[1] for row in rows if row[0].startswith("ledger.")} == {
                category["id"], transaction["id"], receipt["data"]["entityId"]}
            assert {row[0] for row in rows if not row[0].startswith("ledger.")} == {
                "user.preferences", "dashboard.layout", "automation.definition"}
            assert all(row[2] == 0 for row in rows)
            assert json.loads(next(row[3] for row in rows if row[1] == transaction["id"]))["description"] == "Offline edited lunch"
            assert connection.execute("SELECT sync_revision FROM ledger_transactions WHERE id=?",
                                      (transaction["id"],)).fetchone()[0] == 0
        assert token not in (data_dir / "logs" / "backend.log").read_text(encoding="utf-8")
        assert agent_token not in (data_dir / "logs" / "backend.log").read_text(encoding="utf-8")
        if os.name != "nt":
            # The owner exits naturally on EOF; the frozen backend must stop itself.
            with subprocess.Popen([sys.executable, "-c", "import sys; sys.stdin.read()"], stdin=subprocess.PIPE) as owner:
                third = launch(data_dir, owner.pid)
                try:
                    owner.stdin.close()
                    owner.wait(timeout=5)
                    assert third.wait(timeout=15) == 0
                    with socket.socket() as listener:
                        assert listener.connect_ex(("127.0.0.1", PORT)) != 0
                finally:
                    if third.poll() is None:
                        stop(third, data_dir)
            print("Packaged sidecar: Unix desktop owner exit stops backend and releases port PASS")
        print("Packaged sidecar: Agent scopes/create/replay/audit, nine-entity offline outbox, tombstones, persistence, login PASS")
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
