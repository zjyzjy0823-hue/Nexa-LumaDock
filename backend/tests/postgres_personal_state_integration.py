"""Background-only real SQLite A/B and isolated PostgreSQL Personal State E2E.

Repeat with NEXA_BACKGROUND_SIDECAR for the final packaged Windows backend.
No manual sync calls; process logs and actual PostgreSQL sync payloads are checked.
"""
from contextlib import closing
import json
import os
from pathlib import Path
import secrets
import sqlite3
from tempfile import TemporaryDirectory
from uuid import uuid4

from sqlalchemy import create_engine, text
from postgres_background_sync_integration import Server, drained, eventually
from postgres_conflict_integration import connect, disconnect

PREFERENCES = "/api/v1/settings"
DASHBOARD = "/api/dashboard"
AUTOMATIONS = "/api/v1/automations"
CONFLICTS = "/api/v1/sync/conflicts"


def read(replica, kind, automation_id):
    if kind == "user.preferences":
        return replica.request("GET", PREFERENCES)["theme"]
    if kind == "dashboard.layout":
        return replica.request("GET", DASHBOARD)["layout_json"]
    response = replica.client.get(f"{AUTOMATIONS}/{automation_id}")
    assert response.status_code in (200, 404)
    return response.json()["description"] if response.status_code == 200 else None


def edit(replica, kind, value, automation_id):
    if kind == "user.preferences":
        replica.request("PATCH", PREFERENCES, json={"theme": value})
    elif kind == "dashboard.layout":
        replica.request("PUT", DASHBOARD + "/layout", json=value)
    else:
        replica.request("PATCH", f"{AUTOMATIONS}/{automation_id}", json={"description": value})


def snapshot(replica, kind):
    return next((item for item in replica.request("GET", CONFLICTS)["conflicts"] if item["entityType"] == kind), None)


def queue(replica):
    with closing(sqlite3.connect(replica.directory / "nexa.db")) as db:
        return db.execute("SELECT mutation_id, entity_type, entity_id, base_revision, payload_json "
            "FROM local_mutation_queue WHERE status != 'resolved' ORDER BY entity_type, entity_id").fetchall()


def main():
    database_url = os.environ["DATABASE_URL"]
    assert database_url.startswith("postgresql+psycopg://")
    engine = create_engine(database_url)
    with engine.connect() as db:
        assert db.scalar(text("SELECT version_num FROM alembic_version")) == "0017_automation_engine"
    password, jwt = secrets.token_urlsafe(24), secrets.token_hex(32)
    credentials = [password, jwt]
    with TemporaryDirectory(prefix="nexa-personal-state-") as temporary:
        directory = Path(temporary)
        core = Server(directory, "core", core_env={"NEXA_MODE": "core", "DATABASE_URL": database_url,
            "JWT_SECRET": jwt, "CORS_ORIGINS": "http://localhost:5173"})
        a, b = Server(directory, "local-a"), Server(directory, "local-b")
        try:
            for server in (core, a, b):
                server.start()
            username = "personal_core_" + uuid4().hex[:12]
            credentials.extend((core.register(username, password), a.register("personal_a", password), b.register("personal_b", password)))
            for replica in (a, b):
                connect(replica, core, username, password)
                eventually(lambda: drained(replica), "initial background sync")
            assert a.status()["conflicts"] == b.status()["conflicts"] == 0
            a.request("PATCH", PREFERENCES, json={"theme": "dark", "language": "en-US", "appearance": {"accent": "mint"}})
            eventually(lambda: drained(a) and b.request("GET", PREFERENCES)["theme"] == "dark", "preferences A -> Core -> B")
            base_layout = a.request("GET", DASHBOARD)["layout_json"]
            changed = {"widgets": base_layout["widgets"][:3]}
            edit(b, "dashboard.layout", changed, None)
            eventually(lambda: drained(b) and read(a, "dashboard.layout", None) == changed, "dashboard B -> Core -> A")
            definition = a.request("POST", AUTOMATIONS, expected=201, json={"name": "Daily Summary", "description": "Initial",
                "trigger_type": "schedule", "trigger_config_json": {"cron": "0 9 * * *"},
                "workflow_json": [{"kind": "DO", "label": "Notify", "text": "Daily summary", "detail": "Definition only"}]})
            automation_id = definition["id"]
            eventually(lambda: drained(a) and read(b, "automation.definition", automation_id) == "Initial", "automation stable UUID create")
            b.request("PATCH", f"{AUTOMATIONS}/{automation_id}", json={"enabled": False, "description": "B edit",
                "trigger_config_json": {"cron": "0 10 * * *"}, "workflow_json": [{"kind": "DO", "text": "Updated action"}]})
            eventually(lambda: drained(b) and read(a, "automation.definition", automation_id) == "B edit", "automation edit")
            a.request("POST", f"{AUTOMATIONS}/{automation_id}/test-run", expected=201)
            assert b.request("GET", f"{AUTOMATIONS}/{automation_id}/executions") == []
            eventually(lambda: drained(a) and drained(b), "online idle")
            print("Personal State background preferences/layout/definition and local-only history: PASS", flush=True)

            # Real offline business writes, durable restart and automatic recovery.
            core.stop()
            edit(a, "user.preferences", "light", automation_id)
            offline_layout = {"widgets": base_layout["widgets"][:4]}
            edit(b, "dashboard.layout", offline_layout, automation_id)
            edit(b, "automation.definition", "Offline durable", automation_id)
            eventually(lambda: a.status()["lastError"] and b.status()["lastError"], "offline bounded retry")
            before = queue(b)
            assert {row[1] for row in before} == {"dashboard.layout", "automation.definition"}
            b.stop(); b.start()
            assert queue(b) == before
            core.start()
            eventually(lambda: drained(a) and drained(b) and read(b, "user.preferences", automation_id) == "light"
                and read(a, "dashboard.layout", automation_id) == offline_layout
                and read(a, "automation.definition", automation_id) == "Offline durable", "offline/restart auto convergence")
            print("Personal State offline/restart persistence and background recovery: PASS", flush=True)

            # All three kinds use both decisions, dependent tails and stale guards.
            for kind in ("user.preferences", "dashboard.layout", "automation.definition"):
                for strategy in ("local", "remote"):
                    eventually(lambda: drained(a) and drained(b), "pre-conflict idle")
                    disconnect(b)
                    if kind == "user.preferences":
                        local_value, remote_value, stale_value, tail_value = "system", "dark", "light", "system"
                    elif kind == "dashboard.layout":
                        local_value, remote_value, stale_value, tail_value = [{"widgets": base_layout["widgets"][:count]} for count in (2, 3, 5, 6)]
                    else:
                        local_value, remote_value, stale_value, tail_value = [f"{strategy} {value}" for value in ("Local", "Core", "Core race", "Local tail")]
                    edit(b, kind, local_value, automation_id)
                    edit(a, kind, remote_value, automation_id)
                    eventually(lambda: drained(a), "Core conflicting edit publication")
                    connect(b, core, username, password)
                    old = eventually(lambda: snapshot(b, kind), "personal conflict")
                    assert read(b, kind, automation_id) == local_value
                    edit(b, kind, tail_value, automation_id)
                    edit(a, kind, stale_value, automation_id)
                    eventually(lambda: drained(a), "second Core revision")
                    current = eventually(lambda: (value if value and value["remoteRevision"] > old["remoteRevision"] else None)
                        if (value := snapshot(b, kind)) else None, "fresh remote snapshot")
                    response = b.client.post(f"{CONFLICTS}/{old['id']}/resolve", json={"strategy": strategy, "expectedRemoteRevision": old["remoteRevision"]})
                    assert response.status_code == 409
                    assert current["hasPendingTail"]
                    b.request("POST", f"{CONFLICTS}/{current['id']}/resolve", json={"strategy": strategy, "expectedRemoteRevision": current["remoteRevision"]})
                    expected = tail_value if strategy == "local" else stale_value
                    eventually(lambda: drained(a) and drained(b) and read(a, kind, automation_id) == expected
                        and read(b, kind, automation_id) == expected, "personal conflict decision convergence")
            print("Three Personal State kinds, both decisions, tails and stale revision races: PASS", flush=True)

            b.request("DELETE", f"{AUTOMATIONS}/{automation_id}", expected=204)
            eventually(lambda: drained(b) and read(a, "automation.definition", automation_id) is None, "definition tombstone propagation")
            with engine.connect() as db:
                assert db.scalar(text("SELECT deleted_at FROM automation_workflows WHERE id=:id"), {"id": automation_id}) is not None
                assert db.scalar(text("SELECT count(*) FROM automation_executions WHERE workflow_id=:id"), {"id": automation_id}) == 0
                workspace_id = db.scalar(text("SELECT workspace_id FROM automation_workflows WHERE id=:id"), {"id": automation_id})
                payloads = db.execute(text("SELECT payload_json FROM sync_changes WHERE workspace_id=:workspace"), {"workspace": workspace_id}).scalars().all()
            all_payloads = json.dumps(payloads)
            for forbidden in ("nc_live_", "na_live_", "Authorization", "password", "credential", "installationId", "filesystem", "token", "jwt", "secret"):
                assert forbidden not in all_payloads
            for replica in (a, b):
                credentials.extend(((replica.directory / "secret.key").read_text(),))
                with closing(sqlite3.connect(replica.directory / "nexa.db")) as db:
                    local_payloads = json.dumps(db.execute("SELECT payload_json, conflict_json FROM local_mutation_queue").fetchall())
                    for credential in credentials:
                        assert credential not in local_payloads
            print("Personal State tombstones, Core payload/outbox/conflict secret exclusions: PASS", flush=True)
        finally:
            for server in (a, b, core):
                server.close()
            for path in directory.rglob("process.log"):
                log = path.read_text(encoding="utf-8", errors="replace")
                for credential in credentials:
                    assert credential not in log, "Credential appeared in process log"
            engine.dispose()
    print(("Packaged Windows" if os.environ.get("NEXA_BACKGROUND_SIDECAR") else "Source") + " PostgreSQL Personal State E2E: PASS")


if __name__ == "__main__":
    main()
