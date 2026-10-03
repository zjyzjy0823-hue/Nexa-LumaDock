"""Real background-only Local A/SQLite <-> Core/PostgreSQL <-> Local B/SQLite.

Run after Alembic upgrade against an isolated PostgreSQL DATABASE_URL. Each Local
uses the production desktop entry point, its own process, data directory, secret
and SQLite database. No transport mocks, frontend timers or manual sync calls.
"""

from dataclasses import dataclass
from contextlib import closing
import os
from pathlib import Path
import secrets
import socket
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
from uuid import uuid4

import httpx
from sqlalchemy import create_engine, text


BACKEND = Path(__file__).resolve().parents[1]
TABLES = ("ledger_categories", "ledger_transactions", "website_categories",
          "websites", "data_collections", "data_records")
TEST_TIMING = {"NEXA_SYNC_INITIAL_DELAY_SECONDS": "0.2",
               "NEXA_SYNC_DEBOUNCE_SECONDS": "0.1",
               "NEXA_SYNC_PERIOD_SECONDS": "1",
               "NEXA_SYNC_RETRY_SECONDS": "0.5,1,2"}


def free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def checked(client, method, path, *, expected=200, **kwargs):
    assert path != "/api/v1/sync/run", "This regression must never invoke manual sync"
    response = client.request(method, path, **kwargs)
    # Do not print response bodies, headers, credentials or raw HTTP exceptions.
    assert response.status_code == expected, f"{method} {path}: HTTP {response.status_code}"
    return response.json() if expected != 204 else None


def eventually(check, label, timeout=45):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        time.sleep(0.1)
    raise AssertionError(f"Timed out: {label}")


class Server:
    def __init__(self, directory, name, *, core_env=None):
        self.directory = directory / name
        self.directory.mkdir()
        self.core_env = core_env
        self.port = free_port()
        self.client = httpx.Client(base_url=f"http://127.0.0.1:{self.port}",
                                   trust_env=False, follow_redirects=False, timeout=5)
        self.process = None
        self.log = None

    @property
    def origin(self):
        return str(self.client.base_url).rstrip("/")

    def start(self):
        assert self.process is None
        env = {**os.environ, **TEST_TIMING, "ALLOW_REGISTRATION": "true"}
        if self.core_env is None:
            packaged = os.environ.get("NEXA_BACKGROUND_SIDECAR")
            if packaged:
                binary = Path(packaged).expanduser().resolve()
                assert binary.is_file(), "NEXA_BACKGROUND_SIDECAR executable is missing"
                entry = [str(binary)]
            else:
                entry = [sys.executable, "desktop_entry.py"]
            arguments = [*entry, "--data-dir", str(self.directory), "--port", str(self.port)]
        else:
            env.update(self.core_env)
            arguments = [sys.executable, "-m", "uvicorn", "app.main:app", "--host",
                         "127.0.0.1", "--port", str(self.port), "--no-access-log"]
        self.log = (self.directory / "process.log").open("ab")
        self.process = subprocess.Popen(arguments, cwd=BACKEND, env=env,
            stdout=self.log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)

        def ready():
            assert self.process.poll() is None, "Integration backend exited before readiness"
            try:
                response = self.client.get("/api/health")
                return response.status_code == 200 and response.json().get("status") == "ok"
            except httpx.RequestError:
                return False

        eventually(ready, "backend readiness")

    def stop(self):
        if self.process is None:
            return
        process = self.process
        try:
            if self.core_env is None:
                (self.directory / "backend.shutdown").write_text("quit", encoding="ascii")
            else:
                process.terminate()
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
                raise AssertionError("Backend failed bounded graceful shutdown") from None
            if self.core_env is None:
                assert process.returncode == 0, "Local lifespan shutdown failed"
            with socket.socket() as listener:
                assert listener.connect_ex(("127.0.0.1", self.port)) != 0, "Backend port leaked"
        finally:
            self.process = None
            self.log.close()
            self.log = None

    def close(self):
        self.stop()
        self.client.close()

    def request(self, method, path, **kwargs):
        return checked(self.client, method, path, **kwargs)

    def status(self):
        return self.request("GET", "/api/v1/sync/status")

    def register(self, username, password):
        result = self.request("POST", "/api/v1/auth/register", expected=201,
                              json={"username": username, "password": password})
        self.client.headers["Authorization"] = "Bearer " + result["access_token"]
        return result["access_token"]

    def rows(self, table, entity_id):
        assert table in TABLES
        with closing(sqlite3.connect(self.directory / "nexa.db")) as db:
            return db.execute(f"SELECT sync_revision FROM {table} WHERE id=?", (entity_id,)).fetchall()


@dataclass
class Group:
    ids: dict[str, str]
    prefix: str


def write_group(replica, prefix):
    category = replica.request("POST", "/api/v1/ledger/categories", expected=201,
        json={"name": prefix + " ledger category", "type": "expense"})
    ledger = replica.request("POST", "/api/v1/ledger/transactions", expected=201,
        json={"category_id": category["id"], "type": "expense", "amount": "38.00",
              "description": prefix + " ledger", "occurred_at": "2026-10-02T09:00:00Z"})
    website_category = replica.request("POST", "/api/v1/website-categories", expected=201,
        json={"name": prefix + " website category"})
    website = replica.request("POST", "/api/v1/websites", expected=201,
        json={"name": prefix + " website", "url": "https://example.com",
              "categoryId": website_category["id"]})
    collection = replica.request("POST", "/api/v1/data/collections", expected=201,
        json={"name": prefix + " collection"})
    record = replica.request("POST", f"/api/v1/data/collections/{collection['id']}/records", expected=201,
        json={"name": prefix + " record", "data_json": {"value": prefix}})
    return Group(dict(zip(TABLES, (category["id"], ledger["id"], website_category["id"],
                                  website["id"], collection["id"], record["id"]))), prefix)


def received(replica, group):
    ledger = replica.request("GET", "/api/v1/ledger/transactions")
    websites = replica.request("GET", "/api/v1/websites")
    collections = replica.request("GET", "/api/v1/data/collections")
    if not (any(row["id"] == group.ids["ledger_transactions"] for row in ledger)
            and any(row["id"] == group.ids["websites"] for row in websites)
            and any(row["id"] == group.ids["data_collections"] for row in collections)):
        return False
    records = replica.request("GET", f"/api/v1/data/collections/{group.ids['data_collections']}/records")
    record = next((row for row in records if row["id"] == group.ids["data_records"]), None)
    if record is None:
        return False
    transaction = next(row for row in ledger if row["id"] == group.ids["ledger_transactions"])
    website = next(row for row in websites if row["id"] == group.ids["websites"])
    collection = next(row for row in collections if row["id"] == group.ids["data_collections"])
    assert transaction["description"] == group.prefix + " ledger" and transaction["amount"] == "38.00"
    assert transaction["categoryId"] == group.ids["ledger_categories"]
    assert transaction["categoryName"] == group.prefix + " ledger category"
    assert website["name"] == group.prefix + " website" and website["categoryId"] == group.ids["website_categories"]
    assert collection["name"] == group.prefix + " collection"
    assert record["name"] == group.prefix + " record" and record["dataJson"] == {"value": group.prefix}
    assert record["collectionId"] == group.ids["data_collections"]
    return True


def drained(replica):
    status = replica.status()
    return (status["enabled"] and not status["running"] and status["pending"] == 0
            and status["inFlight"] == 0 and status["lastError"] is None
            and status["lastSuccessAt"] is not None)


def offline_retry(replica):
    status = replica.status()
    return status if (status["lastError"] == "unreachable" and not status["running"]
                      and status["nextRetryAt"] is not None) else None


def verify_converged(core_engine, replicas, groups):
    for group in groups:
        for table, entity_id in group.ids.items():
            with core_engine.connect() as db:
                rows = db.execute(text(f"SELECT sync_revision FROM {table} WHERE id=:id"),
                                  {"id": entity_id}).all()
            assert len(rows) == 1 and rows[0][0] > 0, "Core UUID/revision/duplicate invariant"
            for replica in replicas:
                assert replica.rows(table, entity_id) == [(rows[0][0],)], "Replica UUID/revision invariant"
    cursors = [replica.status()["cursor"] for replica in replicas]
    assert min(cursors) > 0 and len(set(cursors)) == 1, "Durable cursors did not converge"


def main():
    core_url = os.environ["DATABASE_URL"]
    assert core_url.startswith("postgresql+psycopg://"), "Integration requires isolated PostgreSQL"
    core_secret = secrets.token_hex(32)
    password = secrets.token_urlsafe(24)
    core_engine = create_engine(core_url)
    with core_engine.connect() as db:
        assert db.scalar(text("SELECT version_num FROM alembic_version")) == "0016_personal_state_sync"
    with TemporaryDirectory(prefix="nexa-background-sync-") as temporary:
        directory = Path(temporary)
        core = Server(directory, "core", core_env={"NEXA_MODE": "core", "DATABASE_URL": core_url,
            "JWT_SECRET": core_secret, "CORS_ORIGINS": "http://localhost:5173"})
        a, b = Server(directory, "local-a"), Server(directory, "local-b")
        servers = (a, b, core)
        secrets_to_check = [core_secret, password]
        try:
            for server in (core, a, b):
                server.start()
            secrets_to_check.extend((replica.directory / "secret.key").read_text(encoding="ascii")
                                    for replica in (a, b))
            username = "background_core_" + uuid4().hex[:12]
            secrets_to_check.append(core.register(username, password))
            secrets_to_check.append(a.register("background_a", password))
            secrets_to_check.append(b.register("background_b_unrelated", password))
            secrets_to_check.append(b.register("background_b", password))
            version = core.request("GET", "/api/health")["version"]
            for replica in (a, b):
                connected = replica.request("POST", "/api/v1/core/connect", json={
                    "coreUrl": core.origin, "username": username, "password": password,
                    "clientName": replica.directory.name, "platform": "windows", "appVersion": version})
                assert connected["connected"]
                eventually(lambda: drained(replica), "connect initial background sync")
            groups = [write_group(a, "A online")]
            eventually(lambda: drained(a) and received(b, groups[0]), "A wakeup -> Core -> B periodic pull")
            groups.append(write_group(b, "B online"))
            eventually(lambda: drained(b) and received(a, groups[1]), "B wakeup -> Core -> A periodic pull")
            eventually(lambda: drained(a) and drained(b), "online idle")
            verify_converged(core_engine, (a, b), groups)
            mode = "Packaged Local" if os.environ.get("NEXA_BACKGROUND_SIDECAR") else "Source Local"
            print(mode + " background-only A/B bidirectional six-entity HTTP/SQLite/PostgreSQL: PASS", flush=True)

            before = {replica: replica.status()["cursor"] for replica in (a, b)}
            core.stop()
            offline_a, offline_b = write_group(a, "A offline"), write_group(b, "B offline")
            groups.extend((offline_a, offline_b))
            for replica, group in ((a, offline_a), (b, offline_b)):
                assert received(replica, group), "Offline local business writes were rolled back"
                status = eventually(lambda: offline_retry(replica), "real Core offline failure")
                assert status["pending"] + status["inFlight"] == 6
                assert status["connected"] and status["nextRetryAt"] is not None
                assert status["cursor"] == before[replica], "Offline failure advanced cursor"
                attempt = status["lastAttemptAt"]
                eventually(lambda: replica.status()["lastAttemptAt"] != attempt, "automatic backoff retry")
                assert replica.status()["pending"] + replica.status()["inFlight"] == 6
            # Restart a real Local process while Core is still unavailable.
            installation = (a.directory / "installation.id").read_bytes()
            secret = (a.directory / "secret.key").read_bytes()
            with closing(sqlite3.connect(a.directory / "nexa.db")) as db:
                queue_before = db.execute("SELECT mutation_id, entity_id, base_revision, payload_json "
                    "FROM local_mutation_queue ORDER BY entity_id").fetchall()
            a.stop()
            a.start()
            assert (a.directory / "installation.id").read_bytes() == installation
            assert (a.directory / "secret.key").read_bytes() == secret
            eventually(lambda: offline_retry(a), "restart initial background attempt")
            assert received(a, offline_a)
            with closing(sqlite3.connect(a.directory / "nexa.db")) as db:
                assert db.execute("SELECT mutation_id, entity_id, base_revision, payload_json "
                    "FROM local_mutation_queue ORDER BY entity_id").fetchall() == queue_before
            print("Real Core stop: Local writes, retries, pending mutation IDs and Local restart preserved: PASS", flush=True)

            core.start()
            eventually(lambda: drained(a) and drained(b) and received(a, offline_b)
                       and received(b, offline_a), "automatic Core recovery without manual sync")
            verify_converged(core_engine, (a, b), groups)
            for replica in (a, b):
                status = replica.status()
                assert status["nextRetryAt"] is None and status["cursor"] > before[replica]
                assert status["conflicts"] == 0 and status["rejected"] == 0
            # A second restart after successful recovery preserves durable cursor.
            cursor = a.status()["cursor"]
            a.stop()
            a.start()
            eventually(lambda: drained(a), "restart successful initial sync")
            assert a.status()["cursor"] == cursor
            verify_converged(core_engine, (a, b), groups)
            print("Automatic recovery: zero pending, stable UUIDs, unique rows, matching revisions/cursors: PASS", flush=True)
        finally:
            shutdown_failed = False
            for server in servers:
                try:
                    server.close()
                except Exception:
                    # Always stop the other owned test processes, even when one
                    # lifecycle assertion failed. Never print a raw exception.
                    shutdown_failed = True
            core_engine.dispose()
            assert not shutdown_failed, "An integration process failed lifecycle cleanup"
        for log in directory.rglob("*.log"):
            contents = log.read_text(encoding="utf-8", errors="replace")
            assert all(value not in contents for value in secrets_to_check), "Credential appeared in integration log"
            assert "nc_live_" not in contents and "Bearer " not in contents, "Bearer credential appeared in integration log"
            assert "authorization:" not in contents.lower(), "Authorization header appeared in integration log"
        print("Production Local lifecycle graceful shutdown/port release and credential log scan: PASS", flush=True)


if __name__ == "__main__":
    main()
