"""Production Local A/B Conflict Center against an isolated PostgreSQL Core.

Run after Alembic upgrade with DATABASE_URL=postgresql+psycopg://... . Uses
real Local processes, business/Conflict HTTP APIs and background synchronization;
never invokes /sync/run. Set NEXA_BACKGROUND_SIDECAR to repeat with the native
packaged backend. Disconnecting B makes same-base edits and stale races precise.
"""

from contextlib import closing
import json
import os
import secrets
import sqlite3
from tempfile import TemporaryDirectory
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, text

from postgres_background_sync_integration import Server, drained, eventually


TRANSACTIONS = "/api/v1/ledger/transactions"
CONFLICTS = "/api/v1/sync/conflicts"


def transaction(replica, entity_id):
    response = replica.client.get(f"{TRANSACTIONS}/{entity_id}")
    assert response.status_code in (200, 404), "Transaction read failed safely"
    return response.json() if response.status_code == 200 else None


def matches(replica, entity_id, description):
    item = transaction(replica, entity_id)
    return item is None if description is None else item is not None and item["description"] == description


def queue(replica, entity_id):
    with closing(sqlite3.connect(replica.directory / "nexa.db")) as db:
        db.row_factory = sqlite3.Row
        return [dict(row) for row in db.execute(
            "SELECT id, mutation_id, status, operation, base_revision, payload_json, "
            "depends_on_mutation_id, result_revision, conflict_json, attempt_count "
            "FROM local_mutation_queue WHERE entity_id=? "
            "AND status IN ('pending', 'in_flight', 'conflict', 'rejected') ORDER BY created_at, id",
            (entity_id,)).fetchall()]


def receipt(replica, snapshot, expected):
    with closing(sqlite3.connect(replica.directory / "nexa.db")) as db:
        db.row_factory = sqlite3.Row
        row = db.execute("SELECT entity_type, entity_id, status, payload_json, "
            "conflict_json, depends_on_mutation_id, last_error FROM local_mutation_queue WHERE id=?",
            (snapshot["id"],)).fetchone()
    assert row is not None and row["status"] == "resolved", "Resolution audit receipt was not durable"
    assert row["entity_type"] == snapshot["entityType"] and row["entity_id"] == snapshot["entityId"]
    payload = json.loads(row["payload_json"]) if row["payload_json"] is not None else None
    assert payload is None and row["last_error"] is None and row["depends_on_mutation_id"] is None
    audit = json.loads(row["conflict_json"])
    assert set(audit) == {"id", "strategy", "status", "remoteRevision", "mutationId", "resolvedAt"}
    assert audit == expected and audit["resolvedAt"]
    assert audit["remoteRevision"] == snapshot["remoteRevision"]
    assert not {"local", "remote", "current", "data", "credential", "password", "token", "headers"} & audit.keys()
    return audit


def local_row(replica, entity_id):
    with closing(sqlite3.connect(replica.directory / "nexa.db")) as db:
        db.row_factory = sqlite3.Row
        row = db.execute("SELECT description, sync_revision, deleted_at "
                         "FROM ledger_transactions WHERE id=?", (entity_id,)).fetchone()
    assert row is not None, "Local tombstone must retain entity identity"
    return dict(row)


def core_row(engine, entity_id):
    with engine.connect() as db:
        row = db.execute(text("SELECT description, sync_revision, deleted_at "
                              "FROM ledger_transactions WHERE id=:id"), {"id": entity_id}).mappings().one()
    return dict(row)


def conflict(replica, entity_id):
    items = replica.request("GET", CONFLICTS)["conflicts"]
    item = next((item for item in items if item["entityId"] == entity_id), None)
    if item is None:
        return None
    detail = replica.request("GET", f"{CONFLICTS}/{item['id']}")
    assert detail == item, "Conflict list/detail snapshots must agree while remote is stable"
    assert detail["entityType"] == "ledger.transaction"
    assert not {"credential", "password", "token", "workspaceId", "userId", "conflict_json"} & detail.keys()
    return detail


def disconnect(replica):
    assert replica.request("DELETE", "/api/v1/core/connection")["connected"] is False
    eventually(lambda: not replica.status()["connected"] and not replica.status()["running"],
               "disconnected scheduler stopped")


def connect(replica, core, username, password):
    value = replica.request("POST", "/api/v1/core/connect", json={
        "coreUrl": core.origin, "username": username, "password": password,
        "clientName": replica.directory.name, "platform": "windows" if os.name == "nt" else "linux",
        "appVersion": core.request("GET", "/api/health")["version"]})
    assert value["connected"]
    return value["clientId"]


def edit(replica, entity_id, description):
    if description is None:
        replica.request("DELETE", f"{TRANSACTIONS}/{entity_id}", expected=204)
    else:
        replica.request("PATCH", f"{TRANSACTIONS}/{entity_id}", json={"description": description})


def create_shared(a, b, core, label):
    item = a.request("POST", TRANSACTIONS, expected=201, json={
        "type": "expense", "amount": "38.00", "description": label,
        "occurred_at": "2026-10-03T08:30:00Z"})
    entity_id = item["id"]
    eventually(lambda: drained(a) and drained(b) and matches(core, entity_id, label)
               and matches(b, entity_id, label), "initial shared authoritative transaction")
    assert a.rows("ledger_transactions", entity_id) == b.rows("ledger_transactions", entity_id)
    return entity_id


def establish(a, b, core, engine, username, password, entity_id, local, remote):
    """B and A write from the same revision; A uploads before reconnecting B."""
    base = local_row(b, entity_id)["sync_revision"]
    disconnect(b)
    edit(b, entity_id, local)
    edit(a, entity_id, remote)
    eventually(lambda: drained(a) and matches(core, entity_id, remote), "A authoritative competing write")
    revision = core_row(engine, entity_id)["sync_revision"]
    assert revision > base
    connect(b, core, username, password)
    snapshot = eventually(lambda: conflict(b, entity_id), "B detects explicit conflict")
    assert snapshot["remoteRevision"] == revision
    assert snapshot["remoteDeleted"] is (remote is None)
    assert snapshot["localDeleted"] is (local is None)
    assert matches(b, entity_id, local), "Conflict silently replaced Local business data"
    assert local_row(b, entity_id)["sync_revision"] == base
    assert b.status()["conflicts"] == 1
    entries = queue(b, entity_id)
    assert len(entries) == 1 and entries[0]["status"] == "conflict" and entries[0]["base_revision"] == base
    return snapshot


def submit_resolution(replica, snapshot, strategy):
    def attempt():
        response = replica.client.post(f"{CONFLICTS}/{snapshot['id']}/resolve", json={
            "strategy": strategy, "expectedRemoteRevision": snapshot["remoteRevision"]})
        if response.status_code == 409:
            assert response.json().get("detail") in ("sync_in_progress", "conflict_busy"), "Unexpected controlled resolution failure"
            return None
        assert response.status_code == 200, "Conflict resolution HTTP request failed safely"
        return response.json()
    return eventually(attempt, "explicit resolution acquires Local sync lock")


def resolve(replica, snapshot, strategy):
    value = submit_resolution(replica, snapshot, strategy)
    assert value["status"] == "resolved"
    assert replica.status()["conflicts"] == 0, "Conflict count must update immediately"
    assert receipt(replica, snapshot, value) == value
    assert submit_resolution(replica, snapshot, strategy) == value, "Same resolution request did not replay exactly"
    return value


def background_cycles(replica, count=2):
    """Wait for actual completed cycles, allowing assertions after later pulls."""
    for _ in range(count):
        before = replica.status()["lastSuccessAt"]
        eventually(lambda: not replica.status()["running"] and replica.status()["lastSuccessAt"] != before,
                   "subsequent production background cycle")


def converged(a, b, core, engine, entity_id, description):
    if not (drained(a) and drained(b) and all(matches(replica, entity_id, description)
                                               for replica in (a, b, core))):
        return False
    authoritative = core_row(engine, entity_id)
    for replica in (a, b):
        local = local_row(replica, entity_id)
        if local["sync_revision"] != authoritative["sync_revision"]:
            return False
        assert (local["deleted_at"] is not None) is (description is None)
        assert not queue(replica, entity_id)
        assert replica.status()["conflicts"] == 0 and replica.status()["rejected"] == 0
    return True


def assert_resolution_mutation(engine, client_id, entity_id, base, operation):
    with engine.connect() as db:
        rows = db.execute(text("SELECT base_revision, operation, result_revision FROM sync_mutations "
            "WHERE client_id=:client AND entity_id=:entity AND status='applied' ORDER BY result_revision"),
            {"client": client_id, "entity": entity_id}).mappings().all()
    assert rows, "Keep Local never reached Core through background sync"
    newest = rows[-1]
    assert newest["base_revision"] == base and newest["operation"] == operation
    assert newest["result_revision"] > base


def main():
    core_url = os.environ["DATABASE_URL"]
    assert core_url.startswith("postgresql+psycopg://"), "Conflict integration requires isolated PostgreSQL"
    engine = create_engine(core_url)
    with engine.connect() as db:
        assert db.scalar(text("SELECT version_num FROM alembic_version")) == "0015_agent_data_actions"
    core_secret, password = secrets.token_hex(32), secrets.token_urlsafe(24)
    with TemporaryDirectory(prefix="nexa-conflict-sync-") as temporary:
        directory = Path(temporary)
        core = Server(directory, "core", core_env={"NEXA_MODE": "core", "DATABASE_URL": core_url,
            "JWT_SECRET": core_secret, "CORS_ORIGINS": "http://localhost:5173"})
        a, b = Server(directory, "local-a"), Server(directory, "local-b")
        secrets_to_check = [core_secret, password]
        servers = (a, b, core)
        try:
            for server in (core, a, b):
                server.start()
            secrets_to_check.extend((replica.directory / "secret.key").read_text(encoding="ascii")
                                    for replica in (a, b))
            username = "conflict_core_" + uuid4().hex[:12]
            secrets_to_check.append(core.register(username, password))
            secrets_to_check.append(a.register("conflict_a", password))
            unrelated_token = b.register("conflict_b_unrelated", password)
            secrets_to_check.append(unrelated_token)
            secrets_to_check.append(b.register("conflict_b", password))
            connect(a, core, username, password)
            client_b = connect(b, core, username, password)
            eventually(lambda: drained(a) and drained(b), "initial background enrollment")

            entity_id = create_shared(a, b, core, "Remote resolution coffee")
            snapshot = establish(a, b, core, engine, username, password, entity_id, "B local 38", "A remote 42")
            unrelated = {"Authorization": "Bearer " + unrelated_token}
            assert b.request("GET", CONFLICTS, headers=unrelated)["conflicts"] == []
            b.request("GET", f"{CONFLICTS}/{snapshot['id']}", headers=unrelated, expected=404)
            b.request("POST", f"{CONFLICTS}/{snapshot['id']}/resolve", headers=unrelated,
                      expected=404, json={"strategy": "remote"})
            edit(b, entity_id, "B later edit must be discarded")
            snapshot = conflict(b, entity_id)
            assert snapshot["hasPendingTail"] and snapshot["local"]["description"] == "B later edit must be discarded"
            before_queue = queue(b, entity_id)
            frozen = next(item for item in before_queue if item["status"] == "conflict")
            background_cycles(b)
            assert next(item for item in queue(b, entity_id) if item["status"] == "conflict")["attempt_count"] == frozen["attempt_count"], "Frozen conflict was retried automatically"
            identity = (b.directory / "installation.id").read_bytes()
            secret = (b.directory / "secret.key").read_bytes()
            b.stop()
            b.start()
            eventually(lambda: not b.status()["running"] and b.status()["conflicts"] == 1,
                       "unresolved conflict restored after production Local restart")
            assert (b.directory / "installation.id").read_bytes() == identity
            assert (b.directory / "secret.key").read_bytes() == secret
            assert queue(b, entity_id) == before_queue
            snapshot = conflict(b, entity_id)
            assert snapshot["hasPendingTail"] and snapshot["local"]["description"] == "B later edit must be discarded"
            revision = snapshot["remoteRevision"]
            resolve(b, snapshot, "remote")
            assert matches(b, entity_id, "A remote 42") and not queue(b, entity_id)
            eventually(lambda: converged(a, b, core, engine, entity_id, "A remote 42"), "Keep Remote convergence")
            background_cycles(b)
            assert core_row(engine, entity_id)["sync_revision"] == revision and matches(core, entity_id, "A remote 42"), "Discarded pending tail later overwrote Core"
            print("Keep Remote: explicit conflict, restart persistence, discarded tail, no later stale push: PASS", flush=True)

            entity_id = create_shared(a, b, core, "Local resolution coffee")
            snapshot = establish(a, b, core, engine, username, password, entity_id, "B first local edit", "A competing edit")
            old_mutation = queue(b, entity_id)[0]["mutation_id"]
            edit(b, entity_id, "B latest editable tail")
            snapshot = conflict(b, entity_id)
            assert snapshot["hasPendingTail"]
            resolve(b, snapshot, "local")
            eventually(lambda: converged(a, b, core, engine, entity_id, "B latest editable tail"),
                       "Keep Local wakes background push and A periodic pull")
            assert_resolution_mutation(engine, client_b, entity_id, snapshot["remoteRevision"], "upsert")
            with engine.connect() as db:
                applied_id = db.scalar(text("SELECT mutation_id FROM sync_mutations WHERE client_id=:client "
                    "AND entity_id=:entity AND status='applied' ORDER BY result_revision DESC LIMIT 1"),
                    {"client": client_b, "entity": entity_id})
            assert applied_id != old_mutation, "Resolution must use a new mutation ID"
            print("Keep Local: latest tail, fresh mutation/latest base, automatic push and peer convergence: PASS", flush=True)

            entity_id = create_shared(a, b, core, "Race coffee")
            snapshot = establish(a, b, core, engine, username, password, entity_id, "B chosen local", "A revision R")
            disconnect(b)
            edit(a, entity_id, "A revision R plus one")
            eventually(lambda: drained(a) and matches(core, entity_id, "A revision R plus one"), "new Core revision before stale resolution")
            newer_revision = core_row(engine, entity_id)["sync_revision"]
            assert newer_revision > snapshot["remoteRevision"]
            race_receipt = resolve(b, snapshot, "local")
            entries = queue(b, entity_id)
            assert len(entries) == 1 and entries[0]["status"] == "pending"
            assert entries[0]["base_revision"] == snapshot["remoteRevision"]
            assert entries[0]["depends_on_mutation_id"] is None
            assert json.loads(entries[0]["payload_json"])["description"] == "B chosen local"
            resolution_id = entries[0]["mutation_id"]
            assert race_receipt["mutationId"] == resolution_id
            connect(b, core, username, password)
            renewed = eventually(lambda: conflict(b, entity_id), "stale resolution returns to explicit conflict")
            assert renewed["remoteRevision"] == newer_revision and renewed["remote"]["description"] == "A revision R plus one"
            assert renewed["local"]["description"] == "B chosen local"
            assert renewed["id"] != snapshot["id"]
            frozen = queue(b, entity_id)[0]
            assert frozen["mutation_id"] == resolution_id and frozen["base_revision"] == snapshot["remoteRevision"]
            background_cycles(b)
            assert core_row(engine, entity_id)["sync_revision"] == newer_revision and matches(core, entity_id, "A revision R plus one"), "Stale resolution silently force-overwrote Core"
            assert queue(b, entity_id)[0]["attempt_count"] == frozen["attempt_count"]
            live_queue = queue(b, entity_id)
            assert submit_resolution(b, snapshot, "local") == race_receipt
            assert receipt(b, snapshot, race_receipt) == race_receipt
            assert queue(b, entity_id) == live_queue and b.status()["conflicts"] == 1, "Replayed old resolution altered a newer conflict"
            resolve(b, renewed, "remote")
            eventually(lambda: converged(a, b, core, engine, entity_id, "A revision R plus one"), "race acknowledged explicitly")
            print("Resolution race: stale base conflicts again, latest snapshot, no hidden retry/overwrite: PASS", flush=True)

            for local_deleted, strategy in ((False, "remote"), (False, "local"), (True, "local"), (True, "remote")):
                entity_id = create_shared(a, b, core, "Delete combination coffee")
                local = None if local_deleted else "B restore chosen locally"
                remote = "A remotely edited entity" if local_deleted else None
                snapshot = establish(a, b, core, engine, username, password, entity_id, local, remote)
                revision = snapshot["remoteRevision"]
                resolve(b, snapshot, strategy)
                winner = local if strategy == "local" else remote
                eventually(lambda: converged(a, b, core, engine, entity_id, winner), "edit/delete conflict convergence")
                if strategy == "local":
                    assert_resolution_mutation(engine, client_b, entity_id, revision,
                                               "delete" if local_deleted else "upsert")
                else:
                    assert core_row(engine, entity_id)["sync_revision"] == revision
            print("Delete conflicts: remote tombstone acceptance, Local restore, Local delete and remote restore: PASS", flush=True)

            for replica in (a, b):
                assert replica.request("GET", CONFLICTS)["conflicts"] == []
                assert replica.status()["conflicts"] == 0
            eventually(lambda: drained(a) and drained(b) and a.status()["cursor"] == b.status()["cursor"],
                       "durable authoritative cursors converge")
            assert a.status()["cursor"] > 0
        finally:
            shutdown_failed = False
            for server in servers:
                try:
                    server.close()
                except Exception:
                    shutdown_failed = True
            engine.dispose()
            assert not shutdown_failed, "Conflict integration lifecycle cleanup failed"
        for log in directory.rglob("*.log"):
            contents = log.read_text(encoding="utf-8", errors="replace")
            assert all(value not in contents for value in secrets_to_check), "Secret appeared in conflict integration log"
            assert "nc_live_" not in contents and "Bearer " not in contents, "Bearer credential appeared in conflict integration log"
            assert "authorization:" not in contents.lower(), "Authorization header appeared in conflict integration log"
        mode = "Packaged Local" if os.environ.get("NEXA_BACKGROUND_SIDECAR") else "Source Local"
        print(mode + " Conflict Center A/B HTTP/SQLite/PostgreSQL, lifecycle and credential scan: PASS", flush=True)


if __name__ == "__main__":
    main()
