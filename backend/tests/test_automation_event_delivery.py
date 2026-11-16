"""Local completion outbox and the Client-authenticated Core ingress."""
from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, inspect, select

from app import models
from app.automation import engine as automation, events
from app.database import get_db
from app.models import Agent, AgentTask, AutomationEvent, AutomationExecution
from app.runtime_mode import require_core_mode
from app.sync.engine import run_sync_cycle
from app.sync import engine as sync_engine
from app.sync.remote import SyncRemoteClient, SyncRemoteError
from test_agent_runtime import create_agent, credential, runtime, task
from test_sync_engine import replica

ENDPOINT = "/api/v1/automation/events"


@contextmanager
def database(client):
    iterator = client.app.dependency_overrides[get_db]()
    try:
        yield next(iterator)
    finally:
        iterator.close()


def event_body():
    task_id = str(uuid4())
    return {"type": "agent_completed", "eventId": f"task:{task_id}:completed",
            "agentId": str(uuid4()), "taskId": task_id}


def enroll(client, owner):
    client.app.dependency_overrides[require_core_mode] = lambda: None
    response = client.post("/api/v1/clients/enroll", headers=owner, json={
        "installationId": str(uuid4()), "name": "Event reporter", "platform": "android", "appVersion": "1"})
    assert response.status_code == 201
    return response.json(), {"Authorization": "Bearer " + response.json()["credential"]}


def test_core_event_idempotency_and_single_workflow_execution(client, users):
    owner, other = users
    body = event_body()
    workflow = client.post("/api/v1/automations", headers=owner, json={
        "name": "Completion", "trigger_type": "agent_completed",
        "trigger_config_json": {"agent_id": body["agentId"]},
        "workflow_json": [{"kind": "DO", "action": {"type": "agent.run", "config": {
            "agent_id": body["agentId"], "title": "Follow up"}}}]}).json()
    enrollment, headers = enroll(client, owner)
    first = client.post(ENDPOINT, headers=headers, json=body)
    assert first.status_code == 200
    assert first.json() == {"ok": True, "duplicated": False}
    for _ in range(2):
        with database(client) as db:
            automation.dispatch_events(db)
            db.commit()
        replay = client.post(ENDPOINT, headers=headers, json=body)
        assert replay.json() == {"ok": True, "duplicated": True}
    with database(client) as db:
        row = db.get(AutomationEvent, body["eventId"])
        assert (row.workspace_id, row.type, row.entity_type, row.entity_id, row.operation, row.origin) == (
            enrollment["client"]["workspaceId"], "agent_completed", "agent.task", body["taskId"], "completed", "agent")
        assert row.payload == {"agent_id": body["agentId"]}
        executions = db.scalars(select(AutomationExecution).where(AutomationExecution.workflow_id == workflow["id"])).all()
        assert len(executions) == 1
        assert executions[0].trigger_instance_id == "event:" + body["eventId"]
    _, foreign_headers = enroll(client, other)
    assert client.post(ENDPOINT, headers=foreign_headers, json=body).status_code == 409


def test_core_event_auth_validation_and_mode(client, users):
    owner, _ = users
    body = event_body()
    assert client.post(ENDPOINT, json=body).status_code == 404  # Local has no ingress.
    enrollment, headers = enroll(client, owner)
    for auth in ({}, owner, {"Authorization": "Bearer nc_live_invalid"},
                 {"Authorization": "Bearer nd_live_invalid"}, {"Authorization": "Bearer na_live_invalid"}):
        assert client.post(ENDPOINT, headers=auth, json=body).status_code == 401
    for invalid in ({**body, "type": "data_changed"}, {**body, "workspaceId": str(uuid4())},
                    {**body, "agentId": "invalid"}, {**body, "taskId": "invalid"},
                    {**body, "eventId": "arbitrary"}):
        assert client.post(ENDPOINT, headers=headers, json=invalid).status_code == 422
    client.post(f"/api/v1/clients/{enrollment['client']['id']}/revoke", headers=owner)
    assert client.post(ENDPOINT, headers=headers, json=body).status_code == 401


def test_local_completion_durably_enqueues_once(client, users, monkeypatch):
    def no_network(*_args, **_kwargs):
        pytest.fail("Completion must not send HTTP")
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", no_network)
    owner, _ = users
    agent_id = create_agent(client, owner)
    headers = runtime(credential(client, owner, agent_id))
    task_id = task(client, owner, agent_id)
    assert client.post(f"/api/agent/tasks/{task_id}/claim", headers=headers).status_code == 200
    assert client.post(f"/api/agent/tasks/{task_id}/complete", headers=headers, json={"result": {}}).status_code == 200
    with database(client) as db:
        assert "local_automation_events" in inspect(db.get_bind()).get_table_names()
        model = models.LocalAutomationEvent
        events.task_completed(db, db.get(Agent, agent_id), db.get(AgentTask, task_id))
        events.task_completed(db, db.get(Agent, agent_id), db.get(AgentTask, task_id))
        db.commit()
        row = db.scalar(select(model))
        assert db.scalar(select(func.count()).select_from(model)) == 1
        assert row.event_id == f"task:{task_id}:completed"
        assert (row.agent_id, row.task_id, row.type) == (agent_id, task_id, "agent_completed")
        assert row.workspace_id == db.get(Agent, agent_id).workspace_id
        assert row.delivered_at is None and row.attempts == 0 and row.last_error is None
        assert db.scalar(select(func.count()).select_from(AutomationEvent)) == 0


class Transport:
    def __init__(self, factory, fail=False):
        self.factory, self.fail, self.sent = factory, fail, []
        self.sync_failure = False

    def get_changes(self, cursor, limit):
        if self.sync_failure:
            raise SyncRemoteError("unreachable")
        return {"protocolVersion": 3, "changes": [], "cursor": 0, "hasMore": False, "workspaceRevision": 0}

    def report_event(self, event):
        # Reads and network operations must never hold an outbox transaction open.
        with self.factory() as db:
            db.execute(models.LocalAutomationEvent.__table__.update().values(last_error=None))
            db.commit()
        self.sent.append(event)
        if self.fail:
            raise SyncRemoteError("timeout")
        return {"ok": True, "duplicated": False}


@pytest.fixture
def local_outbox(tmp_path):
    local = replica(tmp_path, "event_local", 11)
    body = event_body()
    with local.factory() as db:
        events.task_completed(db, SimpleNamespace(id=body["agentId"], workspace_id=local.workspace_id),
                              SimpleNamespace(id=body["taskId"]))
        db.commit()
    metadata = SimpleNamespace(coreUrl="https://core.example", workspaceId=str(uuid4()), clientId=str(uuid4()))
    yield local, body, metadata
    local.engine.dispose()


def sync(local, metadata, transport):
    return run_sync_cycle(local.factory, local.user_id, local.workspace_id, metadata, "nc_live_test", transport)


def test_sync_flush_success_and_no_redelivery(local_outbox):
    local, body, metadata = local_outbox
    transport = Transport(local.factory)
    assert sync(local, metadata, transport)["status"] == "ok"
    assert transport.sent == [body]
    assert sync(local, metadata, transport)["status"] == "ok"
    assert transport.sent == [body]
    with local.factory() as db:
        row = db.scalar(select(models.LocalAutomationEvent))
        assert row.delivered_at is not None and row.last_error is None


def test_local_enqueue_rolls_back_with_completion(local_outbox):
    local, _, _ = local_outbox
    body = event_body()
    with local.factory() as db:
        events.task_completed(db, SimpleNamespace(id=body["agentId"], workspace_id=local.workspace_id),
                              SimpleNamespace(id=body["taskId"]))
        db.rollback()
    with local.factory() as db:
        assert db.scalar(select(models.LocalAutomationEvent).where(
            models.LocalAutomationEvent.event_id == body["eventId"])) is None


def test_sync_flush_is_workspace_scoped_and_batch_bounded(local_outbox, monkeypatch):
    local, first, metadata = local_outbox
    second, foreign = event_body(), event_body()
    foreign_workspace = str(uuid4())
    with local.factory() as db:
        db.add(models.Workspace(id=foreign_workspace, owner_user_id=local.user_id, name="Other", kind="team"))
        db.flush()
        for body, workspace in ((second, local.workspace_id), (foreign, foreign_workspace)):
            events.task_completed(db, SimpleNamespace(id=body["agentId"], workspace_id=workspace),
                                  SimpleNamespace(id=body["taskId"]))
        db.commit()
    monkeypatch.setattr(sync_engine, "EVENT_BATCH_LIMIT", 1)
    transport = Transport(local.factory)
    sync(local, metadata, transport)
    assert transport.sent == [first]
    sync(local, metadata, transport)
    assert transport.sent == [first, second]
    with local.factory() as db:
        row = db.scalar(select(models.LocalAutomationEvent).where(models.LocalAutomationEvent.event_id == foreign["eventId"]))
        assert row.delivered_at is None and row.attempts == 0


def test_sync_flush_failure_is_retained_and_retry_is_bounded(local_outbox, caplog):
    local, body, metadata = local_outbox
    transport = Transport(local.factory, fail=True)
    assert sync(local, metadata, transport)["status"] == "ok"
    assert transport.sent == [body]
    with local.factory() as db:
        row = db.scalar(select(models.LocalAutomationEvent))
        assert row.delivered_at is None and row.attempts == 1 and row.last_error == "timeout"
    for _ in range(24):
        sync(local, metadata, transport)
    assert 1 < len(transport.sent) <= 10
    with local.factory() as db:
        row = db.scalar(select(models.LocalAutomationEvent))
        assert row.delivered_at is None and row.attempts == len(transport.sent)
    assert len(caplog.records) <= 1


def test_sync_failed_cycle_does_not_flush(local_outbox):
    local, _, metadata = local_outbox
    transport = Transport(local.factory)
    transport.sync_failure = True
    assert sync(local, metadata, transport)["status"] == "error"
    assert transport.sent == []


def test_sync_flush_retries_response_loss_idempotently(local_outbox, client, users):
    local, body, metadata = local_outbox
    _, headers = enroll(client, users[0])
    transport = Transport(local.factory)
    def report(event):
        response = client.post(ENDPOINT, headers=headers, json=event)
        assert response.status_code == 200
        transport.sent.append(response.json())
        if len(transport.sent) == 1:
            raise SyncRemoteError("timeout")
        return response.json()
    transport.report_event = report
    sync(local, metadata, transport)
    sync(local, metadata, transport)
    assert transport.sent == [{"ok": True, "duplicated": False}, {"ok": True, "duplicated": True}]
    with database(client) as db:
        assert db.scalar(select(func.count()).select_from(AutomationEvent)) == 1
    with local.factory() as db:
        assert db.scalar(select(models.LocalAutomationEvent)).delivered_at is not None


@pytest.mark.parametrize("response", [{"ok": True, "duplicated": False}, {"ok": True, "duplicated": True},
    {"ok": False}, {"ok": "true", "duplicated": False}, {"ok": True, "duplicated": "false"}])
def test_remote_reports_event_with_client_credential(monkeypatch, response):
    body = event_body()
    original = httpx.Client
    def handler(request):
        import json
        assert request.url.path == ENDPOINT and request.method == "POST"
        assert request.headers["Authorization"] == "Bearer nc_live_test"
        assert json.loads(request.read()) == body
        return httpx.Response(200, json=response)
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    with SyncRemoteClient("https://core.example", "nc_live_test") as remote:
        if response.get("ok") is True and type(response.get("duplicated")) is bool:
            assert remote.report_event(body) == response
        else:
            with pytest.raises(SyncRemoteError, match="invalid_response"):
                remote.report_event(body)
