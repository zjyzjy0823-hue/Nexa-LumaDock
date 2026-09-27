import hashlib
from pathlib import Path
import sys
from datetime import datetime, timedelta, timezone

import httpx

from app.database import get_db
from app.main import app
from app.models import Agent, AgentEvent, AgentTask


def create_agent(client, user, name="Nova"):
    response = client.post("/api/v1/agents", headers=user, json={"name": name})
    assert response.status_code == 201
    return response.json()["id"]


def credential(client, user, agent_id):
    response = client.post(f"/api/v1/agents/{agent_id}/token", headers=user)
    assert response.status_code == 201
    assert response.headers["Cache-Control"] == "no-store"
    return response.json()["token"]


def runtime(token):
    return {"Authorization": f"Bearer {token}"}


def task(client, user, agent_id, title="Inspect"):
    response = client.post(f"/api/v1/agents/{agent_id}/tasks", headers=user,
                           json={"title": title, "description": "Return a summary"})
    assert response.status_code == 201
    return response.json()["id"]


def session():
    return app.dependency_overrides[get_db]()


def test_agent_token_lifecycle_and_permissions(client, users):
    owner, other = users
    agent_id = create_agent(client, owner)
    assert client.post(f"/api/v1/agents/{agent_id}/token", headers=other).status_code == 404
    assert client.delete(f"/api/v1/agents/{agent_id}/token", headers=other).status_code == 404
    first = credential(client, owner, agent_id)
    db_iter = session()
    db = next(db_iter)
    try:
        record = db.get(Agent, agent_id)
        assert record.token_hash == hashlib.sha256(first.encode()).hexdigest()
        assert first not in repr(record.__dict__)
        assert record.token_last4 == first[-4:]
    finally:
        db_iter.close()
    headers = runtime(first)
    for path in ("/api/v1/devices", "/api/v1/settings", "/api/v1/ledger/summary",
                 "/api/v1/data/collections", "/api/api-keys", "/api/v1/agents", "/api/agents"):
        assert client.get(path, headers=headers).status_code == 401
    assert client.post("/api/agent/heartbeat", headers=owner, json={
        "status": "idle", "runtimeType": "openclaw"}).status_code == 401
    second = credential(client, owner, agent_id)
    assert second != first
    assert client.get("/api/agent/tasks", headers=headers).status_code == 401
    assert client.get("/api/agent/tasks", headers=runtime(second)).status_code == 200
    assert client.delete(f"/api/v1/agents/{agent_id}/token", headers=owner).status_code == 204
    assert client.get("/api/agent/tasks", headers=runtime(second)).status_code == 401
    third = credential(client, owner, agent_id)
    assert client.delete(f"/api/v1/agents/{agent_id}", headers=owner).status_code == 204
    assert client.get("/api/agent/tasks", headers=runtime(third)).status_code == 401


def test_heartbeat_validation_and_offline(client, users):
    owner, _ = users
    agent_id = create_agent(client, owner)
    headers = runtime(credential(client, owner, agent_id))
    body = {"status": "idle", "runtimeType": "openclaw", "runtimeVersion": "1.0.0",
            "runtimeInstance": "desktop-zjy", "model": "qwen3.5", "currentTaskId": None}
    for invalid in ({**body, "status": "offline"}, {**body, "runtimeInstance": "x" * 121},
                    {**body, "agentId": agent_id}):
        assert client.post("/api/agent/heartbeat", headers=headers, json=invalid).status_code == 422
    assert client.post("/api/agent/heartbeat", headers=runtime("na_live_invalid"), json=body).status_code == 401
    response = client.post("/api/agent/heartbeat", headers=headers, json=body)
    assert response.status_code == 200
    assert response.json()["lastSeenAt"].endswith("+00:00")
    state = client.get(f"/api/v1/agents/{agent_id}", headers=owner).json()
    assert (state["status"], state["runtimeType"], state["runtimeInstance"], state["model"]) == (
        "idle", "openclaw", "desktop-zjy", "qwen3.5")
    assert state["lastSeenAt"].endswith("+00:00")
    db_iter = session()
    db = next(db_iter)
    try:
        db.get(Agent, agent_id).last_seen_at = datetime.now(timezone.utc) - timedelta(seconds=121)
        db.commit()
    finally:
        db_iter.close()
    assert client.get(f"/api/v1/agents/{agent_id}", headers=owner).json()["status"] == "offline"
    assert client.patch(f"/api/v1/agents/{agent_id}", headers=owner,
                        json={"enabled": False}).json()["status"] == "disabled"
    assert client.post("/api/agent/heartbeat", headers=headers, json=body).status_code == 409


def test_task_lifecycle_isolation_events_and_claim_race(client, users):
    owner, other = users
    first_agent = create_agent(client, owner)
    second_agent = create_agent(client, other)
    first_token = runtime(credential(client, owner, first_agent))
    second_token = runtime(credential(client, other, second_agent))
    first_task = task(client, owner, first_agent)
    second_task = task(client, other, second_agent)
    assert [item["id"] for item in client.get("/api/agent/tasks", headers=first_token).json()] == [first_task]
    assert client.post(f"/api/agent/tasks/{second_task}/claim", headers=first_token).status_code == 404
    assert client.post(f"/api/agent/tasks/{second_task}/events", headers=first_token,
                       json={"type": "log", "message": "bad"}).status_code == 404
    assert client.post(f"/api/agent/tasks/{first_task}/complete", headers=first_token,
                       json={"result": {}}).status_code == 409
    claimed = client.post(f"/api/agent/tasks/{first_task}/claim", headers=first_token)
    assert claimed.status_code == 200
    assert claimed.json()["claimedAt"].endswith("+00:00")
    assert client.post(f"/api/agent/tasks/{first_task}/claim", headers=first_token).status_code == 409
    assert client.post(f"/api/agent/tasks/{first_task}/claim", headers=second_token).status_code == 404
    assert client.get("/api/agent/tasks", headers=first_token).json() == []
    event = client.post(f"/api/agent/tasks/{first_task}/events", headers=first_token,
                        json={"type": "log", "level": "info", "message": "Checking repository", "data": {}})
    assert event.status_code == 201
    finished = client.post(f"/api/agent/tasks/{first_task}/complete", headers=first_token,
                           json={"result": {"text": "Healthy"}, "summary": "Checked"})
    assert finished.status_code == 200
    assert finished.json()["completedAt"].endswith("+00:00")
    assert finished.json()["result"] == {"text": "Healthy"}
    assert client.post(f"/api/agent/tasks/{first_task}/fail", headers=first_token,
                       json={"error": "too late"}).status_code == 409
    state = client.get(f"/api/v1/agents/{first_agent}", headers=owner).json()
    assert state["status"] == "idle" and state["currentTaskId"] is None
    assert any(log["eventType"] == "task.log" and log["taskId"] == first_task and
               log["createdAt"].endswith("+00:00") for log in state["logs"])
    db_iter = session()
    db = next(db_iter)
    try:
        entry = db.query(AgentEvent).filter_by(agent_id=first_agent, task_id=first_task,
                                                event_type="task.log").one()
        assert entry.message == "Checking repository"
    finally:
        db_iter.close()
    assert client.post(f"/api/agent/tasks/{second_task}/claim", headers=second_token).status_code == 200
    failed = client.post(f"/api/agent/tasks/{second_task}/fail", headers=second_token,
                         json={"error": "OpenClaw unavailable", "details": {}})
    assert failed.status_code == 200
    assert failed.json()["status"] == "failed"
    assert client.get(f"/api/v1/agents/{second_agent}", headers=other).json()["status"] == "error"
    assert client.post(f"/api/agent/tasks/{second_task}/complete", headers=second_token,
                       json={"result": {}}).status_code == 409


def test_disabling_agent_stops_new_claims_but_allows_active_result(client, users):
    owner, _ = users
    agent_id = create_agent(client, owner)
    headers = runtime(credential(client, owner, agent_id))
    first = task(client, owner, agent_id)
    second = task(client, owner, agent_id, "Next")
    assert client.post(f"/api/agent/tasks/{first}/claim", headers=headers).status_code == 200
    assert client.patch(f"/api/v1/agents/{agent_id}", headers=owner,
                        json={"enabled": False}).status_code == 200
    assert client.post(f"/api/agent/tasks/{second}/claim", headers=headers).status_code == 409
    assert client.post(f"/api/agent/tasks/{first}/complete", headers=headers,
                       json={"result": {"text": "done"}}).status_code == 200
    assert client.get(f"/api/v1/agents/{agent_id}", headers=owner).json()["status"] == "disabled"


def test_adapter_protocol_roundtrip_with_fake_openclaw(client, users):
    """Run the real HTTP protocol through the adapter; only OpenClaw execution is stubbed."""
    adapter_path = Path(__file__).parents[2] / "agent-adapters" / "openclaw"
    sys.path.insert(0, str(adapter_path))
    try:
        from main import run_once
        from nexa import NexaClient
        from openclaw import ExecutionResult
    finally:
        sys.path.remove(str(adapter_path))

    owner, _ = users
    agent_id = create_agent(client, owner)
    token = credential(client, owner, agent_id)
    config = {"serverUrl": "http://localhost", "agentToken": token,
              "runtimeInstance": "integration-test", "pollIntervalSeconds": 10,
              "executionTimeoutSeconds": 60}

    def forward(request):
        response = client.request(request.method, request.url.raw_path.decode(),
                                  headers=dict(request.headers), content=request.content)
        return httpx.Response(response.status_code, content=response.content,
                              headers=dict(response.headers))

    api = NexaClient(config, httpx.MockTransport(forward))
    try:
        run_once(api, config)
        online = client.get(f"/api/v1/agents/{agent_id}", headers=owner).json()
        assert online["status"] == "idle" and online["runtimeInstance"] == "integration-test"
        success_id = task(client, owner, agent_id, "Project status")
        run_once(api, config, lambda *_: ExecutionResult("Project healthy"))
        state = client.get(f"/api/v1/agents/{agent_id}", headers=owner).json()
        assert state["tasks"][0]["id"] == success_id
        assert state["tasks"][0]["status"] == "completed"
        assert state["tasks"][0]["result"] == {"text": "Project healthy"}
        assert state["status"] == "idle"
        assert any(log["eventType"] == "task.completed" for log in state["logs"])

        failure_id = task(client, owner, agent_id, "Fail intentionally")

        def fail(*_):
            raise RuntimeError("OpenClaw execution failed")

        run_once(api, config, fail)
        state = client.get(f"/api/v1/agents/{agent_id}", headers=owner).json()
        assert state["tasks"][0]["id"] == failure_id
        assert state["tasks"][0]["status"] == "failed"
        assert state["status"] == "error"
        assert any(log["eventType"] == "task.failed" for log in state["logs"])
        db_iter = session()
        db = next(db_iter)
        try:
            db.get(Agent, agent_id).last_seen_at = datetime.now(timezone.utc) - timedelta(seconds=121)
            db.commit()
        finally:
            db_iter.close()
        assert client.get(f"/api/v1/agents/{agent_id}", headers=owner).json()["status"] == "offline"
    finally:
        api.close()
