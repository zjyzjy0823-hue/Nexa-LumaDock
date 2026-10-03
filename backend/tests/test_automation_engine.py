"""Same transactional cases run on SQLite and optional isolated PostgreSQL."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import os
from uuid import uuid4
import pytest
from sqlalchemy import create_engine, select, func, text
from sqlalchemy.orm import sessionmaker
from app.database import Base
from app.models import (User, Workspace, AutomationWorkflow as Workflow, AutomationExecution as Execution,
    AutomationEvent as Event, AutomationActionReceipt as Receipt, AutomationScheduleState as State,
    DataCollection, DataRecord, LedgerTransaction, Agent, AgentTask, utcnow)
from app.automation import engine as runtime, webhook, events, actions
from app.automation.schemas import Action, Schedule
from app.automation.schedule import next_due
from app.sync import publisher
from app.sync.adapters import REGISTRY
from app.utils.time import aware_utc

UTC = timezone.utc


@pytest.fixture(params=["sqlite"] + (["postgres"] if os.getenv("NEXA_AUTOMATION_TEST_DATABASE") else []))
def network(request, tmp_path, monkeypatch):
    schema = "automation_" + uuid4().hex
    if request.param == "postgres":
        admin = create_engine(os.environ["NEXA_AUTOMATION_TEST_DATABASE"])
        with admin.begin() as db:
            db.execute(text(f'CREATE SCHEMA "{schema}"'))
        db_engine = create_engine(os.environ["NEXA_AUTOMATION_TEST_DATABASE"], connect_args={"options": "-csearch_path=" + schema})
    else:
        db_engine = create_engine("sqlite:///" + (tmp_path / "runtime.db").as_posix())
    Base.metadata.create_all(db_engine)
    factory = sessionmaker(db_engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(publisher, "runtime_config", replace(publisher.runtime_config, mode="core"))
    monkeypatch.setattr(events, "runtime_config", replace(events.runtime_config, mode="core"))
    with factory() as db:
        user = User(username="runtime_owner", email="runtime@example.test", password_hash="FAKE_HASH_ONLY")
        db.add(user); db.flush()
        workspace = Workspace(id=str(uuid4()), owner_user_id=user.id, name="Runtime", kind="personal")
        db.add(workspace); db.flush()
        collection = DataCollection(id=str(uuid4()), user_id=user.id, workspace_id=workspace.id, name="Output")
        agent = Agent(id=str(uuid4()), user_id=user.id, workspace_id=workspace.id, name="Runtime Agent")
        db.add_all([collection, agent]); db.commit()
        ids = dict(user=user.id, workspace=workspace.id, collection=collection.id, agent=agent.id)
    yield factory, ids
    db_engine.dispose()
    if request.param == "postgres":
        with admin.begin() as db:
            db.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def workflow(factory, ids, action_type="data.create", *, trigger="manual", trigger_config=None, config=None):
    config = config or ({"collection_id": ids["collection"], "name": "Automatic record"} if action_type == "data.create" else
        {"type": "expense", "amount": "12.00", "description": "Automatic transaction", "occurred_at": utcnow().isoformat()} if action_type == "ledger.create" else
        {"agent_id": ids["agent"], "title": "Automatic task"})
    with factory() as db:
        row = Workflow(id=str(uuid4()), user_id=ids["user"], workspace_id=ids["workspace"], name="Automation",
            trigger_type=trigger, trigger_config_json=trigger_config or {},
            workflow_json=[{"kind": "DO", "action": Action(type=action_type, config=config).model_dump(mode="json")}])
        db.add(row); db.commit()
        return row.id


def queue(factory, workflow_id, identity=None, trigger="manual", ancestry=None):
    with factory() as db:
        row = runtime.enqueue(db, db.get(Workflow, workflow_id), trigger, identity or str(uuid4()), ancestry=ancestry)
        db.commit()
        return row.id


def step(factory):
    worker = str(uuid4())
    with factory() as db:
        runtime.dispatch_events(db); db.commit()
        execution_id = runtime.claim(db, worker); db.commit()
    if execution_id:
        runtime.run_claimed(factory, execution_id, worker)
    return execution_id


@pytest.mark.parametrize("kind,model", [("ledger.create", LedgerTransaction), ("data.create", DataRecord), ("agent.run", AgentTask)])
def test_receipt_recovers_committed_action_response_loss(network, kind, model):
    factory, ids = network
    wid = workflow(factory, ids, kind)
    execution_id = queue(factory, wid, "stable-instance")
    assert queue(factory, wid, "stable-instance") == execution_id
    with factory() as db:
        assert runtime.claim(db, "worker-a") == execution_id; db.commit()
    def crash():
        raise RuntimeError("Simulated process crash after committed receipt")
    with pytest.raises(RuntimeError):
        runtime.run_claimed(factory, execution_id, "worker-a", after_action=crash)
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(model)) == 1
        assert db.get(Receipt, execution_id) is not None
        row = db.get(Execution, execution_id); row.lease_expires_at = utcnow() - timedelta(seconds=1); db.commit()
    with factory() as db:
        assert runtime.claim(db, "worker-b") == execution_id; db.commit()
    runtime.run_claimed(factory, execution_id, "worker-a")  # fenced old worker
    runtime.run_claimed(factory, execution_id, "worker-b")
    with factory() as db:
        row = db.get(Execution, execution_id)
        assert row.status == "succeeded" and row.attempt == 2
        assert db.scalar(select(func.count()).select_from(model)) == 1


def test_snapshot_and_data_update(network):
    factory, ids = network
    wid = workflow(factory, ids)
    eid = queue(factory, wid)
    with factory() as db:
        row = db.get(Workflow, wid); row.workflow_json = [{"kind": "DO", "action": {"type": "data.create", "config": {"collection_id": ids["collection"], "name": "New definition"}}}]; db.commit()
    step(factory)
    with factory() as db:
        record = db.scalar(select(DataRecord)); assert record.name == "Automatic record"; record_id = record.id
    update = workflow(factory, ids, "data.update", config={"record_id": record_id, "status": "complete"})
    queue(factory, update); step(factory)
    with factory() as db:
        assert db.get(DataRecord, record_id).status == "complete"
        assert db.scalar(select(func.count()).select_from(DataRecord)) == 1
        assert db.get(Execution, eid).action_snapshot["config"]["name"] == "Automatic record"


def test_retry_backoff_max_attempts_and_nonretryable(network, monkeypatch):
    factory, ids = network
    wid = workflow(factory, ids)
    eid = queue(factory, wid)
    def fail(db, execution):
        raise webhook.ActionError("webhook_network", True)
    monkeypatch.setattr(runtime, "execute", fail)
    for attempt in range(1, runtime.MAX_ATTEMPTS + 1):
        before = utcnow(); step(factory)
        with factory() as db:
            row = db.get(Execution, eid); assert row.attempt == attempt
            if attempt < runtime.MAX_ATTEMPTS:
                assert row.status == "queued"
                assert aware_utc(row.next_attempt_at) >= before + timedelta(seconds=runtime.BACKOFF_SECONDS[attempt - 1])
                assert runtime.claim(db, "early") is None
                row.next_attempt_at = utcnow() - timedelta(seconds=1)
            else:
                assert row.status == "failed" and row.finished_at and row.error_code == "webhook_network"
            db.commit()
    monkeypatch.setattr(runtime, "execute", actions.execute)
    missing = workflow(factory, ids, config={"collection_id": str(uuid4()), "name": "Missing"})
    eid = queue(factory, missing); step(factory)
    with factory() as db:
        assert db.get(Execution, eid).status == "failed" and db.get(Execution, eid).attempt == 1


def test_disable_delete_and_manual_policy(network):
    factory, ids = network
    wid = workflow(factory, ids)
    scheduled, manual = queue(factory, wid, trigger="schedule"), queue(factory, wid)
    with factory() as db:
        db.get(Workflow, wid).enabled = False; db.flush(); runtime.cancel_pending(db); db.commit()
        assert db.get(Execution, scheduled).status == "cancelled" and db.get(Execution, manual).status == "queued"
    step(factory)
    orphan = queue(factory, wid)
    with factory() as db:
        db.get(Workflow, wid).deleted_at = utcnow(); db.flush(); runtime.cancel_pending(db); db.commit()
        assert db.get(Execution, orphan).status == "cancelled"
        assert db.get(Execution, manual).status == "succeeded"


def test_self_cross_loop_and_safe_chain(network):
    factory, ids = network
    a = workflow(factory, ids, trigger="data_changed", trigger_config={"entity_type": "data.record"})
    b = workflow(factory, ids, trigger="data_changed", trigger_config={"entity_type": "data.record"})
    c = workflow(factory, ids, trigger="data_changed", trigger_config={"entity_type": "data.record"})
    queue(factory, a)
    for _ in range(35):
        step(factory)
    with factory() as db:
        rows = db.scalars(select(Execution)).all()
        assert any(row.status == "skipped" and row.error_code == "loop_guard" for row in rows)
        assert any(row.status == "succeeded" and row.ancestry == [a, b, c] for row in rows)
        assert all(len(row.ancestry) <= 4 for row in rows)
        assert not any(row.status in ("queued", "claimed", "running") for row in rows)
        assert db.scalar(select(func.count()).select_from(DataRecord)) == 5
    deep = queue(factory, c, ancestry=[str(uuid4()) for _ in range(runtime.MAX_AUTOMATION_DEPTH)])
    with factory() as db:
        assert db.get(Execution, deep).status == "skipped"


def test_durable_completion_event_and_ancestry(network):
    factory, ids = network
    origin = workflow(factory, ids, "agent.run")
    follower = workflow(factory, ids, trigger="agent_completed", trigger_config={"agent_id": ids["agent"]})
    queue(factory, origin); step(factory)
    with factory() as db:
        task = db.scalar(select(AgentTask)); task.status = "completed"
        events.task_completed(db, db.get(Agent, ids["agent"]), task); db.commit()
    step(factory)
    with factory() as db:
        row = db.scalar(select(Execution).where(Execution.workflow_id == follower))
        assert row.status == "succeeded" and row.ancestry == [origin, follower]
        assert db.scalar(select(Event).where(Event.type == "agent_completed")).dispatched_at


@pytest.mark.parametrize("kind", ["once", "daily", "weekly", "interval"])
def test_schedule_persistence_duplicate_scan_and_catch_up(network, kind):
    factory, ids = network
    now = datetime(2030, 1, 7, 15, tzinfo=UTC)
    config = {"type": kind, "timezone": "Asia/Shanghai", "time": "22:00", "weekdays": [0],
              "at": "2030-01-07T14:00:00Z", "seconds": 3600}
    wid = workflow(factory, ids, trigger="schedule", trigger_config={"schedule": config})
    with factory() as db:
        row = db.get(Workflow, wid); row.created_at = now - timedelta(days=10); db.commit()
        runtime.scan_schedules(db, now); db.commit()
        runtime.scan_schedules(db, now); db.commit()
        assert db.scalar(select(func.count()).select_from(Execution)) == 1
        assert db.get(State, wid).next_due_at is not None or kind == "once"
    with factory() as db:
        runtime.scan_schedules(db, now + timedelta(days=14)); db.commit()
        assert db.scalar(select(func.count()).select_from(Execution)) == (1 if kind == "once" else 2)


def test_skip_catchup_and_timezone_semantics(network):
    factory, ids = network
    config = {"type": "daily", "timezone": "Asia/Shanghai", "time": "22:00", "catch_up": "skip"}
    wid = workflow(factory, ids, trigger="schedule", trigger_config={"schedule": config})
    with factory() as db:
        db.get(Workflow, wid).created_at = datetime(2030, 1, 1, tzinfo=UTC); db.commit()
        runtime.scan_schedules(db, datetime(2030, 1, 3, 15, tzinfo=UTC)); db.commit()
        assert db.scalar(select(func.count()).select_from(Execution)) == 0
        assert aware_utc(db.get(State, wid).next_due_at) == datetime(2030, 1, 4, 14, tzinfo=UTC)
        runtime.scan_schedules(db, datetime(2030, 1, 4, 14, tzinfo=UTC)); db.commit()
        assert db.scalar(select(func.count()).select_from(Execution)) == 1


def test_dst_gap_fold_and_explicit_timezone():
    c = {"type": "daily", "timezone": "America/New_York", "time": "02:30"}
    assert next_due(c, datetime(2026, 3, 8, 6, tzinfo=UTC)) == datetime(2026, 3, 9, 6, 30, tzinfo=UTC)
    c["time"] = "01:30"
    assert next_due(c, datetime(2026, 11, 1, 4, tzinfo=UTC)) == datetime(2026, 11, 1, 5, 30, tzinfo=UTC)
    assert next_due(c, datetime(2026, 11, 1, 5, 30, tzinfo=UTC)) == datetime(2026, 11, 2, 6, 30, tzinfo=UTC)
    with pytest.raises(ValueError):
        Schedule(type="once", timezone="UTC", at="2030-01-01T00:00:00")
    assert set(REGISTRY).isdisjoint({"automation.execution", "automation.event", "automation.receipt", "automation.runtime"})


def test_postgres_parallel_scheduler_claim_and_expired_lock_fence(network):
    factory, ids = network
    if factory.kw["bind"].dialect.name != "postgresql":
        pytest.skip("PostgreSQL row locks require real PostgreSQL")
    now = utcnow()
    wid = workflow(factory, ids, trigger="schedule", trigger_config={"schedule": {"type": "once", "timezone": "UTC", "at": (now - timedelta(seconds=1)).isoformat()}})
    with factory() as db:
        db.get(Workflow, wid).created_at = now - timedelta(seconds=5); db.commit()
    def scan(_):
        with factory() as db:
            runtime.scan_schedules(db, now); db.commit()
    with ThreadPoolExecutor(2) as pool:
        list(pool.map(scan, range(2)))
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Execution)) == 1
    def take(worker):
        with factory() as db:
            result = runtime.claim(db, worker); db.commit(); return result
    with ThreadPoolExecutor(2) as pool:
        claims = list(pool.map(take, ["worker-a", "worker-b"]))
    assert sum(value is not None for value in claims) == 1
    eid = next(value for value in claims if value)
    with factory() as db:
        db.get(Execution, eid).lease_expires_at = now - timedelta(seconds=1); db.commit()
    with factory() as locked:
        locked.scalar(select(Execution).where(Execution.id == eid).with_for_update())
        assert take("worker-c") is None  # expiry cannot bypass a live side-effect transaction
    assert take("worker-c") == eid
