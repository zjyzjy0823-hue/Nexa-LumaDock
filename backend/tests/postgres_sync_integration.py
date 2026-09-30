"""Real Core HTTP/PostgreSQL plus two independent Local SQLite API replicas.

Run against an isolated, migrated test database with DATABASE_URL and JWT_SECRET
set as in backend-postgres CI. No transport mocks or direct Core service calls.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
from uuid import uuid4

import httpx
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker


BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
CORE_ENV = {**os.environ, "NEXA_MODE": "core", "ALLOW_REGISTRATION": "true"}
CORE_URL = CORE_ENV["DATABASE_URL"]
assert CORE_URL.startswith("postgresql+psycopg://"), "Integration requires PostgreSQL"
# Local APIs run in this process; Core gets its own process and configuration.
os.environ.update(NEXA_MODE="local", DATABASE_URL="sqlite://", JWT_SECRET=secrets.token_hex(32))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app.api import ledger, sync, websites
from app.api.data import routes as data_routes  # noqa: E402
from app.core_connection import CoreConnectionMetadata, _persist_connection  # noqa: E402
from app.database import get_db  # noqa: E402
from app.models import LedgerCategory, LedgerTransaction, LocalMutation, User, Workspace, Website, WebsiteCategory, DataCollection, DataRecord  # noqa: E402
from app.security import create_access_token  # noqa: E402


def checked(client, method, path, *, expected=200, **kwargs):
    response = client.request(method, path, **kwargs)
    # Never include request headers, credentials or response bodies in diagnostics.
    assert response.status_code == expected, f"{method} {path}: HTTP {response.status_code}"
    return response.json() if expected != 204 else None


@contextmanager
def core_server(directory, port=None):
    if port is None:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"
    with (directory / "core.log").open("ab") as log:
        process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
             "--port", str(port), "--no-access-log"], cwd=BACKEND, env=CORE_ENV,
            stdout=log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        try:
            with httpx.Client(base_url=origin, trust_env=False, follow_redirects=False,
                              timeout=2) as client:
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise RuntimeError("Core integration server exited before readiness")
                    try:
                        health = client.get("/api/health")
                        if health.status_code == 200:
                            assert health.json() == {"status": "ok", "service": "nexa", "version": "0.5.4"}
                            break
                    except httpx.RequestError:
                        pass
                    time.sleep(0.1)
                else:
                    raise RuntimeError("Core integration server readiness timeout")
                yield client, origin, port
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


class Replica:
    def __init__(self, directory, name, user_id):
        self.directory = directory / name
        self.directory.mkdir()
        self.user_id = user_id
        self.workspace_id = str(uuid4())
        self.installation_id = str(uuid4())
        (self.directory / "installation.id").write_text(self.installation_id, encoding="ascii")
        database_url = "sqlite:///" + (self.directory / "nexa.db").as_posix()
        migration = subprocess.run(
            [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"],
            cwd=BACKEND, env={**os.environ, "DATABASE_URL": database_url}, capture_output=True)
        assert migration.returncode == 0, "Local integration migration failed"
        self.engine = create_engine(database_url, connect_args={"check_same_thread": False})
        self.factory = sessionmaker(bind=self.engine, autoflush=False, expire_on_commit=False)
        with self.factory() as db:
            db.add(User(id=user_id, username=name, email=f"{name}@example.test", password_hash="unused"))
            db.add(Workspace(id=self.workspace_id, owner_user_id=user_id, name="Personal", kind="personal"))
            db.commit()
        app = FastAPI()
        app.include_router(ledger.router)
        app.include_router(sync.router)
        app.include_router(websites.router)
        app.include_router(data_routes.v1_router)
        app.include_router(data_routes.router)

        def database():
            with self.factory() as db:
                yield db

        app.dependency_overrides[get_db] = database
        self.api = TestClient(app)
        self.api.headers["Authorization"] = "Bearer " + create_access_token(user_id)

    def request(self, method, path, **kwargs):
        os.environ["NEXA_DATA_DIR"] = str(self.directory)
        return checked(self.api, method, path, **kwargs)

    def connect(self, core, origin, headers):
        enrolled = checked(core, "POST", "/api/v1/clients/enroll", expected=201, headers=headers, json={
            "installationId": self.installation_id, "name": self.directory.name,
            "platform": "windows", "appVersion": "0.5.4"})
        self.client_id = enrolled["client"]["id"]
        self.core_workspace_id = enrolled["client"]["workspaceId"]
        metadata = CoreConnectionMetadata.model_validate({
            "schemaVersion": 1, "coreUrl": origin, "clientId": self.client_id,
            "workspaceId": self.core_workspace_id, "installationId": self.installation_id,
            "clientName": self.directory.name, "platform": "windows", "appVersion": "0.5.4",
            "connectedAt": datetime.now(timezone.utc).isoformat()})
        os.environ["NEXA_DATA_DIR"] = str(self.directory)
        _persist_connection(self.user_id, metadata, enrolled["credential"])
        return enrolled["credential"]

    def run(self, status="ok"):
        result = self.request("POST", "/api/v1/sync/run")
        assert result["status"] == status, f"Sync failed: {result.get('lastError')}"
        return result

    def transaction(self, description, category_id=None):
        return self.request("POST", "/api/v1/ledger/transactions", expected=201, json={
            "category_id": category_id, "type": "expense", "amount": "38.00",
            "description": description, "occurred_at": "2026-09-28T12:00:00Z"})["id"]

    def edit(self, entity_id, description, amount=None):
        data = {"description": description}
        if amount is not None:
            data["amount"] = amount
        return self.request("PATCH", f"/api/v1/ledger/transactions/{entity_id}", json=data)

    def close(self):
        self.api.close()
        self.engine.dispose()


def main():
    core_engine = create_engine(CORE_URL)
    core_factory = sessionmaker(bind=core_engine)
    with core_engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0014_multi_entity_sync"
    with TemporaryDirectory(prefix="nexa-http-sync-") as temporary:
        directory = Path(temporary)
        a, b = Replica(directory, "local-a", 100001), Replica(directory, "local-b", 100002)
        try:
            with core_server(directory) as (core, origin, port):
                registration = checked(core, "POST", "/api/v1/auth/register", expected=201, json={
                    "username": "http_sync_" + uuid4().hex[:12], "password": secrets.token_urlsafe(24)})
                headers = {"Authorization": "Bearer " + registration["access_token"]}
                core_user_id = checked(core, "GET", "/api/v1/auth/me", headers=headers)["id"]
                credential_a = a.connect(core, origin, headers)
                credential_b = b.connect(core, origin, headers)
                assert credential_a != credential_b and a.client_id != b.client_id
                assert a.core_workspace_id == b.core_workspace_id
                assert len({a.workspace_id, b.workspace_id, a.core_workspace_id}) == 3
                assert len({a.user_id, b.user_id, core_user_id}) == 3
                assert a.installation_id != b.installation_id

                category_id = a.request("POST", "/api/v1/ledger/categories", expected=201,
                                        json={"name": "Food", "type": "expense"})["id"]
                coffee_id = a.transaction("Coffee38", category_id)
                assert a.run()["pushed"] == 2
                b.run()
                with core_factory() as db:
                    assert db.get(LedgerCategory, category_id).workspace_id == a.core_workspace_id
                    item = db.get(LedgerTransaction, coffee_id)
                    assert item.workspace_id == a.core_workspace_id and item.user_id == core_user_id
                with b.factory() as db:
                    item = db.get(LedgerTransaction, coffee_id)
                    assert item.workspace_id == b.workspace_id and item.user_id == b.user_id
                    assert item.description == "Coffee38" and item.category_id == category_id
                    assert db.get(LedgerCategory, category_id).workspace_id == b.workspace_id
                b.edit(coffee_id, "Coffee42", "42.00")
                b.run()
                a.run()
                for replica in (a, b):
                    assert replica.request("GET", f"/api/v1/ledger/transactions/{coffee_id}")["amount"] == "42.00"
                with core_factory() as db:
                    assert db.get(LedgerTransaction, coffee_id).amount == Decimal("42.00")
                a.request("DELETE", f"/api/v1/ledger/transactions/{coffee_id}", expected=204)
                a.run()
                b.run()
                for replica in (a, b):
                    response = replica.api.get(f"/api/v1/ledger/transactions/{coffee_id}")
                    assert response.status_code == 404
                    summary = replica.request("GET", "/api/v1/ledger/summary?month=2026-09")
                    assert Decimal(summary["expense"]) == 0
                with core_factory() as db:
                    assert db.get(LedgerTransaction, coffee_id).deleted_at is not None

                x, y = a.transaction("X"), a.transaction("Y")
                a.run()
                b.run()
                a.edit(x, "X latest")
                b.edit(y, "Y latest")
                a.run()
                assert b.run()["conflicts"] == 0
                assert a.run()["conflicts"] == 0
                for factory in (a.factory, b.factory, core_factory):
                    with factory() as db:
                        assert db.get(LedgerTransaction, x).description == "X latest"
                        assert db.get(LedgerTransaction, y).description == "Y latest"

                with b.factory() as db:
                    base = db.get(LedgerTransaction, x).sync_revision
                a.edit(x, "Remote40")
                b.edit(x, "Local42")
                remote_revision = a.run()["workspaceRevision"]
                assert b.run()["conflicts"] == 1
                for description in ("Remote40", "Remote45", None):
                    if description == "Remote45":
                        a.edit(x, description)
                        remote_revision = a.run()["workspaceRevision"]
                    elif description is None:
                        a.request("DELETE", f"/api/v1/ledger/transactions/{x}", expected=204)
                        remote_revision = a.run()["workspaceRevision"]
                    assert b.run()["cursor"] == remote_revision
                    with b.factory() as db:
                        item = db.get(LedgerTransaction, x)
                        assert item.description == "Local42" and item.sync_revision == base
                        assert item.deleted_at is None
                        entry = db.scalar(select(LocalMutation).where(LocalMutation.entity_id == x))
                        assert entry.status == "conflict" and entry.result_revision == remote_revision
                        snapshot = entry.conflict_json
                        assert snapshot["currentRevision"] == remote_revision
                        assert snapshot["deleted"] == (description is None)
                        assert snapshot["current"] is None if description is None else snapshot["current"]["description"] == description

                # Website/Data use the same production HTTP transport and isolated ownership.
                wc = a.request("POST", "/api/v1/website-categories", expected=201, json={"name": "Sites"})["id"]
                site = a.request("POST", "/api/v1/websites", expected=201, json={"name": "Example", "url": "https://example.com", "categoryId": wc, "favorite": True, "order": 2})["id"]
                dc = a.request("POST", "/api/v1/data/collections", expected=201, json={"name": "Inventory"})["id"]
                dr = a.request("POST", f"/api/v1/data/collections/{dc}/records", expected=201, json={"name": "Record", "data_json": {"value": 42}})["id"]
                a.run(); b.run()
                for replica, owner, workspace in ((a, a.user_id, a.workspace_id), (b, b.user_id, b.workspace_id)):
                    with replica.factory() as db:
                        assert db.get(Website, site).workspace_id == workspace
                        assert db.get(WebsiteCategory, wc).user_id == owner
                        assert db.get(DataCollection, dc).workspace_id == workspace
                        assert db.get(DataRecord, dr).collection_id == dc
                with core_factory() as db:
                    assert db.get(Website, site).workspace_id == a.core_workspace_id
                    assert db.get(DataCollection, dc).user_id == core_user_id
                    assert db.get(DataRecord, dr).collection_id == dc
                b.request("PATCH", f"/api/v1/websites/{site}", json={"favorite": False, "order": 9})
                visited = b.request("POST", f"/api/v1/websites/{site}/visit")["lastVisitedAt"]
                b.request("PATCH", f"/api/v1/data/records/{dr}", json={"name": "B edit", "data_json": {"value": 99}})
                b.run(); a.run()
                assert a.request("GET", f"/api/v1/websites/{site}")["lastVisitedAt"] == visited
                assert a.request("GET", f"/api/v1/data/collections/{dc}/records")[0]["dataJson"] == {"value": 99}
                a.request("DELETE", f"/api/v1/website-categories/{wc}", expected=204)
                a.request("DELETE", f"/api/v1/data/collections/{dc}", expected=204)
                a.run(); b.run()
                assert b.request("GET", f"/api/v1/websites/{site}")["categoryId"] is None
                assert b.request("GET", "/api/v1/data/collections") == []
                assert b.request("GET", "/api/data")["totalRecords"] == 0
                with core_factory() as db:
                    assert db.get(DataRecord, dr).deleted_at is not None
                    assert db.get(DataCollection, dc).deleted_at is not None
                core_site = checked(core, "POST", "/api/v1/websites", expected=201, headers=headers, json={"name": "Core site", "url": "https://core.example"})["id"]
                core_data = checked(core, "POST", "/api/v1/data/collections", expected=201, headers=headers, json={"name": "Core collection"})["id"]
                a.run(); b.run()
                assert b.request("GET", f"/api/v1/websites/{core_site}")["name"] == "Core site"
                assert b.request("GET", f"/api/v1/data/collections/{core_data}")["name"] == "Core collection"

                ordinary = checked(core, "POST", "/api/v1/ledger/transactions", expected=201,
                    headers=headers, json={"type": "expense", "amount": "7.00", "description": "Core ordinary",
                                          "occurred_at": "2026-09-28T12:00:00Z"})["id"]
                a.run()
                b.run()
                assert b.request("GET", f"/api/v1/ledger/transactions/{ordinary}")["description"] == "Core ordinary"

            # Core is really stopped. Local API writes remain durable and readable.
            offline = a.transaction("Offline create")
            a.edit(offline, "Offline edit")
            transient = a.transaction("Offline transient")
            a.request("DELETE", f"/api/v1/ledger/transactions/{transient}", expected=204)
            assert a.run("error")["lastError"] == "unreachable"
            assert a.request("GET", f"/api/v1/ledger/transactions/{offline}")["description"] == "Offline edit"
            with core_server(directory, port) as (core, _, _):
                assert a.run()["pending"] == 0
                b.run()
                assert b.request("GET", f"/api/v1/ledger/transactions/{offline}")["description"] == "Offline edit"
                a.edit(y, "Preserve after revoke")
                before = a.request("GET", "/api/v1/sync/status")
                checked(core, "POST", f"/api/v1/clients/{a.client_id}/revoke", headers=headers)
                result = a.run("error")
                assert result["lastError"] == "unauthorized"
                assert result["cursor"] == before["cursor"] and result["pending"] == before["pending"]
                assert a.request("GET", f"/api/v1/ledger/transactions/{y}")["description"] == "Preserve after revoke"
            with core_factory() as db:
                assert db.scalar(select(LocalMutation.id)) is None, "Core must not use the Local outbox"
        finally:
            a.close()
            b.close()
            core_engine.dispose()
    print("Real HTTP/PostgreSQL/two-SQLite create, update, delete, merge, conflict refresh, offline recovery and revoke: PASS")


if __name__ == "__main__":
    main()
