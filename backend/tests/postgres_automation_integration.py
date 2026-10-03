"""Real Core/PostgreSQL, background Local A/B, Adapter and process crash E2E.

Use NEXA_BACKGROUND_SIDECAR to run replicas from the packaged Windows backend.
"""
from contextlib import closing
from datetime import timedelta
import json
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
from uuid import uuid4
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker
from postgres_background_sync_integration import Server, drained, eventually
from postgres_conflict_integration import connect

BACKEND = Path(__file__).resolve().parents[1]
ROOT = "/api/v1/automations"


def succeeded(replica, workflow_id):
    response = replica.client.get(f"{ROOT}/{workflow_id}/executions?runtime=true")
    if response.status_code != 200:
        return False
    return next((row for row in response.json() if row["status"] == "succeeded"), None)


def create(replica, name, action, config, trigger="manual", trigger_config=None):
    return replica.request("POST", ROOT, expected=201, json={"name": name, "trigger_type": trigger,
        "trigger_config_json": trigger_config or {}, "workflow_json": [{"kind": "DO", "action": {"type": action, "config": config}}]})["id"]


def main():
    url = os.environ["DATABASE_URL"]
    assert url.startswith("postgresql+psycopg://")
    # PostgreSQL assertions include parallel schedule scan, SKIP LOCKED claim,
    # fencing, lease takeover, all internal response-loss receipts and loops.
    unit = subprocess.run([sys.executable, "-m", "pytest", "-q", "tests/test_automation_engine.py", "tests/test_automation_webhook_tls.py", "--tb=short"],
        cwd=BACKEND, env={**os.environ, "NEXA_MODE": "local", "NEXA_AUTOMATION_TEST_DATABASE": url}, capture_output=True, text=True)
    if unit.returncode:
        raise AssertionError("Automation PostgreSQL transactional suite failed")
    print("Automation SQLite/PostgreSQL transactional and multi-worker suite: PASS", flush=True)
    sys.path.insert(0, str(BACKEND))
    from app.models import AutomationExecution as Execution, AutomationWorkflow as Workflow, utcnow
    from app.automation.engine import enqueue, scan_schedules
    engine = create_engine(url, hide_parameters=True)
    factory = sessionmaker(engine, autoflush=False, expire_on_commit=False)
    password, jwt = secrets.token_urlsafe(24), secrets.token_hex(32)
    credentials = [password, jwt]
    with TemporaryDirectory(prefix="nexa-automation-") as temporary:
        directory = Path(temporary)
        core = Server(directory, "core", core_env={"NEXA_MODE": "core", "DATABASE_URL": url,
            "JWT_SECRET": jwt, "CORS_ORIGINS": "http://localhost:5173"})
        a, b = Server(directory, "local-a"), Server(directory, "local-b")
        try:
            for server in (core, a, b): server.start()
            username = "automation_" + uuid4().hex[:10]
            credentials.extend((core.register(username, password), a.register("local_a", password), b.register("local_b", password)))
            for replica in (a, b): connect(replica, core, username, password)
            eventually(lambda: drained(a) and drained(b), "initial background sync")
            collection = a.request("POST", "/api/v1/data/collections", expected=201, json={"name": "Automation output"})["id"]
            eventually(lambda: any(row["id"] == collection for row in core.request("GET", "/api/v1/data/collections")), "collection accepted by Core")
            ledger_config = {"type": "expense", "amount": "18.00", "description": "Data changed authoritative", "occurred_at": utcnow().isoformat()}
            listener = create(a, "Data changed", "ledger.create", ledger_config, "data_changed", {"entity_type": "data.record"})
            eventually(lambda: any(row["id"] == listener for row in core.request("GET", ROOT)), "definition sync")
            source = a.request("POST", f"/api/v1/data/collections/{collection}/records", expected=201, json={"name": "Local A write"})["id"]
            event_run = eventually(lambda: succeeded(a, listener), "Local A -> background sync -> Core event -> Ledger")
            eventually(lambda: any(row["id"] == source for row in b.request("GET", f"/api/v1/data/collections/{collection}/records")), "Local B pulls source")
            eventually(lambda: drained(a) and drained(b), "both replicas idle")
            history = a.request("GET", f"{ROOT}/{listener}/executions?runtime=true")
            assert len(history) == 1 and history[0]["id"] == event_run["id"]
            assert b.request("GET", f"{ROOT}/{listener}/executions?runtime=true")[0]["id"] == event_run["id"]
            a.request("PATCH", f"{ROOT}/{listener}", json={"enabled": False})
            eventually(lambda: not core.request("GET", f"{ROOT}/{listener}")["enabled"], "disable synced")
            print("Authoritative Data Changed, Local B pull non-trigger, shared Core history: PASS", flush=True)

            manual = create(a, "Manual create", "data.create", {"collection_id": collection, "name": "Manual output"})
            eventually(lambda: any(row["id"] == manual for row in core.request("GET", ROOT)), "manual definition synced")
            key = str(uuid4())
            one = a.request("POST", f"{ROOT}/{manual}/run", expected=201, json={"request_id": key})
            two = a.request("POST", f"{ROOT}/{manual}/run", expected=201, json={"request_id": key})
            assert one["id"] == two["id"]
            eventually(lambda: succeeded(a, manual), "proxied Run now real side effect")
            assert len([row for row in core.request("GET", f"/api/v1/data/collections/{collection}/records") if row["name"] == "Manual output"]) == 1

            agent = core.request("POST", "/api/v1/agents", expected=201, json={"name": "Automation Adapter"})["id"]
            token = core.request("POST", f"/api/v1/agents/{agent}/token", expected=201)["token"]; credentials.append(token)
            completion = create(a, "Task completed", "data.update", {"record_id": source, "status": "complete"}, "agent_completed", {"agent_id": agent})
            dispatch = create(a, "Run Agent", "agent.run", {"agent_id": agent, "title": "Deterministic automation task"})
            eventually(lambda: all(any(row["id"] == wid for row in core.request("GET", ROOT)) for wid in (completion, dispatch)), "Agent definitions synced")
            a.request("POST", f"{ROOT}/{dispatch}/run", expected=201, json={"request_id": str(uuid4())})
            eventually(lambda: succeeded(a, dispatch), "Agent task dispatch")
            sys.path.insert(0, str(BACKEND.parent / "agent-adapters" / "openclaw"))
            from main import run_once
            from nexa import NexaClient
            from openclaw import ExecutionResult
            config = {"serverUrl": core.origin, "agentToken": token, "runtimeInstance": "automation-integration",
                      "pollIntervalSeconds": 5, "executionTimeoutSeconds": 10}
            adapter = NexaClient(config)
            try: run_once(adapter, config, lambda *_args: ExecutionResult("Deterministic Adapter completed"))
            finally: adapter.close()
            completed = eventually(lambda: succeeded(a, completion), "Adapter completion event -> Data update")
            assert core.request("GET", f"/api/v1/data/records/{source}")["status"] == "complete"
            assert core.request("GET", f"/api/v1/agents/{agent}")["tasks"][0]["status"] == "completed"
            print("Manual, Data create/update, Agent -> real Adapter -> completion event: PASS", flush=True)

            # Hold an execution row lock so the Core worker cannot claim it.
            # The process is killed after a due schedule is durably queued.
            schedule = create(core, "Crash schedule", "data.create", {"collection_id": collection, "name": "Restart output"},
                "schedule", {"schedule": {"type": "once", "timezone": "UTC", "at": (utcnow() + timedelta(seconds=30)).isoformat()}})
            with factory() as db:
                db.scalar(select(Workflow).where(Workflow.id == schedule).with_for_update())
                row = db.get(Workflow, schedule)
                point = utcnow() + timedelta(seconds=31)
                scan_schedules(db, point)
                db.commit()
                queued = db.scalar(select(Execution).where(Execution.workflow_id == schedule).with_for_update())
                assert queued is not None and queued.status == "queued"
                core.process.kill(); core.process.wait(timeout=10)
                core.log.close(); core.log = None; core.process = None
                db.commit()
            assert a.client.get(f"{ROOT}/{manual}/executions?runtime=true").status_code == 503
            assert a.request("PATCH", f"{ROOT}/{manual}", json={"description": "Editable while Core offline"})["description"] == "Editable while Core offline"
            core.start()
            recovered = eventually(lambda: succeeded(core, schedule), "durable queued schedule survives Core kill")
            assert recovered["id"] == queued.id
            assert len([row for row in core.request("GET", f"/api/v1/data/collections/{collection}/records") if row["name"] == "Restart output"]) == 1
            eventually(lambda: core.request("GET", f"{ROOT}/{manual}")["description"] == "Editable while Core offline", "Core recovery + background edit")
            print("Queued schedule -> Core killed -> restart -> one action; offline editing + proxy recovery: PASS", flush=True)

            for replica in (a, b):
                with closing(sqlite3.connect(replica.directory / "nexa.db")) as db:
                    for table in ("automation_executions", "automation_events", "automation_action_receipts", "automation_schedule_state"):
                        assert db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
            for server in (core, a, b):
                log = (server.directory / "process.log").read_text(encoding="utf-8", errors="replace")
                assert all(secret not in log for secret in credentials)
            print("Local runtime tables empty and process logs credential-free: PASS", flush=True)
        finally:
            for server in (b, a, core): server.close()
            engine.dispose()
    print("AUTOMATION POSTGRES E2E COMPLETE", flush=True)


if __name__ == "__main__": main()
