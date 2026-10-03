"""Agent authorization, atomic receipts and business/sync integration."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import hashlib
import json
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select, func

from app.api.agent_actions import router
from app.actions.registry import REGISTRY
from app.database import get_db
from app.models import (
    Agent,
    AgentActionLog,
    AgentEvent,
    LedgerTransaction,
    LocalMutation,
    Website,
    DataRecord,
    Workspace,
    LedgerCategory,
    LocalSyncState,
)
from app import runtime_mode
from app.services import ledger
from test_sync_engine import network, replica

ROOT = "/api/agent/actions"
SCOPES = [
    f"{domain}:{effect}"
    for domain in ("ledger", "websites", "data")
    for effect in ("read", "write", "delete")
]


def credential(client, owner, scopes=()):
    agent = client.post(
        "/api/v1/agents",
        headers=owner,
        json={"name": "Action Agent", "dataScopes": list(scopes)},
    ).json()
    token = client.post(f"/api/v1/agents/{agent['id']}/token", headers=owner).json()[
        "token"
    ]
    return agent, {"Authorization": "Bearer " + token}


def invoke(client, headers, name, args=None, action_id=None):
    body = {"action": name, "arguments": args or {}}
    if action_id is not None:
        body["actionId"] = str(action_id)
    return client.post(ROOT + "/execute", headers=headers, json=body)


def session(client):
    return next(client.app.dependency_overrides[get_db]())


@pytest.mark.parametrize(
    "domain,read,create,delete,args",
    [
        (
            "ledger",
            "ledger.categories.list",
            "ledger.category.create",
            "ledger.category.delete",
            {"name": "Food", "type": "expense"},
        ),
        (
            "websites",
            "website.categories.list",
            "website.category.create",
            "website.category.delete",
            {"name": "Tools"},
        ),
        (
            "data",
            "data.collections.list",
            "data.collection.create",
            "data.collection.delete",
            {"name": "Servers"},
        ),
    ],
)
def test_explicit_permissions_and_live_scope_changes(
    client, users, domain, read, create, delete, args
):
    owner, _ = users
    agent, headers = credential(client, owner)
    assert agent["dataScopes"] == []
    for name, values in [(read, {}), (create, args), (delete, {"id": str(uuid4())})]:
        response = invoke(client, headers, name, values, uuid4())
        assert (
            response.status_code == 403
            and response.json()["detail"]["code"] == "permission_denied"
        )

    def scopes(values):
        assert (
            client.patch(
                f"/api/v1/agents/{agent['id']}",
                headers=owner,
                json={"dataScopes": values},
            ).status_code
            == 200
        )

    scopes([domain + ":read"])
    assert invoke(client, headers, read).status_code == 200
    assert invoke(client, headers, create, args, uuid4()).status_code == 403
    scopes([domain + ":write"])
    created = invoke(client, headers, create, args, uuid4())
    assert created.status_code == 200
    entity_id = created.json()["data"]["entityId"]
    assert (
        invoke(
            client,
            headers,
            create.replace("create", "update"),
            {"id": entity_id, "name": "Updated"},
            uuid4(),
        ).status_code
        == 200
    )
    assert (
        invoke(client, headers, delete, {"id": entity_id}, uuid4()).status_code == 403
    )
    scopes([domain + ":delete"])
    assert (
        invoke(client, headers, delete, {"id": entity_id}, uuid4()).status_code == 200
    )
    scopes([])
    assert invoke(client, headers, read).status_code == 403
    assert (
        client.patch(
            f"/api/v1/agents/{agent['id']}",
            headers=owner,
            json={"dataScopes": ["ledger:*"]},
        ).status_code
        == 422
    )


@pytest.mark.parametrize(
    "token", ["invalid", "sk_live_fake", "nc_live_fake", "nd_live_fake"]
)
def test_wrong_identity(client, token):
    result = invoke(
        client, {"Authorization": "Bearer " + token}, "ledger.categories.list"
    )
    assert (
        result.status_code == 401 and result.json()["detail"]["code"] == "unauthorized"
    )


def test_local_only_disabled_revocation_catalog(client, users, monkeypatch):
    owner, _ = users
    agent, headers = credential(client, owner, ["ledger:read"])
    catalog = client.get(ROOT + "/catalog", headers=headers).json()
    assert catalog["agentId"] == agent["id"] and set(catalog["actions"]) == {
        "ledger.categories.list",
        "ledger.transactions.list",
        "ledger.summary.get",
    }
    assert "na_live_" not in json.dumps(catalog)
    client.patch(
        f"/api/v1/agents/{agent['id']}", headers=owner, json={"enabled": False}
    )
    assert (
        invoke(client, headers, "ledger.categories.list").json()["detail"]["code"]
        == "agent_disabled"
    )
    client.patch(f"/api/v1/agents/{agent['id']}", headers=owner, json={"enabled": True})
    client.delete(f"/api/v1/agents/{agent['id']}/token", headers=owner)
    assert invoke(client, headers, "ledger.categories.list").status_code == 401
    monkeypatch.setattr(
        runtime_mode,
        "runtime_config",
        replace(runtime_mode.runtime_config, mode="core"),
    )
    for endpoint in ("/execute", "/catalog"):
        result = (
            client.post(ROOT + endpoint, json={})
            if endpoint == "/execute"
            else client.get(ROOT + endpoint)
        )
        assert (
            result.status_code == 404
            and result.json()["detail"]["code"] == "local_only"
        )


TX = {
    "type": "expense",
    "amount": "38.00",
    "description": "Coffee",
    "occurredAt": "2026-09-30T09:00:00+08:00",
    "note": "sensitive note",
}


def test_response_lost_canonical_replay_audit_task(client, users):
    owner, _ = users
    agent, headers = credential(client, owner, SCOPES)
    task = client.post(
        f"/api/v1/agents/{agent['id']}/tasks",
        headers=owner,
        json={"title": "Buy coffee"},
    ).json()
    assert (
        client.post(f"/api/agent/tasks/{task['id']}/claim", headers=headers).status_code
        == 200
    )
    action_id = uuid4()
    first = invoke(client, headers, "ledger.transaction.create", TX, action_id)
    assert first.status_code == 200, first.text
    replay = invoke(
        client,
        headers,
        "ledger.transaction.create",
        dict(reversed(list(TX.items()))),
        action_id,
    )
    assert replay.json()["replayed"] and replay.json()["data"] == first.json()["data"]
    conflict = invoke(
        client,
        headers,
        "ledger.transaction.create",
        {**TX, "amount": "39.00"},
        action_id,
    )
    assert (
        conflict.status_code == 409
        and conflict.json()["detail"]["code"] == "idempotency_conflict"
    )
    with session(client) as db:
        assert db.scalar(select(func.count()).select_from(LedgerTransaction)) == 1
        assert db.scalar(select(func.count()).select_from(LocalMutation)) == 1
        entity_id = first.json()["data"]["entityId"]
        item = db.get(LedgerTransaction, entity_id)
        assert (item.occurred_at.hour, item.occurred_at.minute) == (1, 0)
        assert ledger.transaction_out(item)["occurredAt"] == "2026-09-30T01:00:00+00:00"
        entry = db.scalar(select(LocalMutation).where(LocalMutation.entity_id == entity_id))
        assert entry.payload_json["occurredAt"] == "2026-09-30T01:00:00+00:00"
        logs = db.scalars(select(AgentActionLog)).all()
        success = [entry for entry in logs if entry.status == "ok"]
        assert len(success) == 1 and success[0].task_id == task["id"]
        serialized = json.dumps(
            [
                {c.name: str(getattr(log, c.name)) for c in log.__table__.columns}
                for log in logs
            ]
        )
        assert all(
            secret not in serialized
            for secret in (
                "sensitive note",
                "Coffee",
                "38.00",
                "na_live_",
                "Authorization",
            )
        )
    client.post(
        f"/api/agent/tasks/{task['id']}/complete", headers=headers, json={"result": {}}
    )
    assert (
        invoke(
            client,
            headers,
            "website.create",
            {"name": "Tool", "url": "https://example.com"},
            uuid4(),
        ).status_code
        == 200
    )
    with session(client) as db:
        assert (
            db.scalar(
                select(AgentActionLog).where(
                    AgentActionLog.action_type == "website.create"
                )
            ).task_id
            is None
        )


@pytest.mark.parametrize(
    "action,args",
    [
        ("ledger.transaction.create", {**TX, "amount": "0"}),
        ("ledger.transaction.create", {**TX, "occurredAt": "today"}),
        ("website.create", {"name": "bad", "url": "file:///secret"}),
        ("data.record.create", {"name": "Record"}),
        ("ledger.summary.get", {"month": "2026-13"}),
        ("website.list", {"sort": "sql"}),
        ("ledger.categories.list", {"workspaceId": str(uuid4())}),
    ],
)
def test_strict_schemas(client, users, action, args):
    _, headers = credential(client, users[0], SCOPES)
    result = invoke(client, headers, action, args, uuid4())
    assert (
        result.status_code == 422
        and result.json()["detail"]["code"] == "validation_error"
    )


def test_missing_id_unknown_action_extra_ownership(client, users):
    _, headers = credential(client, users[0], SCOPES)
    assert invoke(client, headers, "ledger.transaction.create", TX).status_code == 422
    assert (
        invoke(client, headers, "settings.update", {}).json()["detail"]["code"]
        == "unsupported_action"
    )
    result = client.post(
        ROOT + "/execute",
        headers=headers,
        json={
            "action": "ledger.categories.list",
            "arguments": {},
            "agentId": str(uuid4()),
        },
    )
    assert result.json()["detail"]["code"] == "validation_error"


@pytest.mark.parametrize(
    "domain,path,get_action,update_action,delete_action,payload",
    [
        (
            "websites",
            "/api/v1/websites",
            "website.get",
            "website.update",
            "website.delete",
            {"name": "Other", "url": "https://example.com"},
        ),
        (
            "data",
            "/api/v1/data/collections",
            "data.collection.get",
            "data.collection.update",
            "data.collection.delete",
            {"name": "Other"},
        ),
        (
            "ledger",
            "/api/v1/ledger/categories",
            None,
            "ledger.category.update",
            "ledger.category.delete",
            {"name": "Other", "type": "expense"},
        ),
    ],
)
def test_other_user_and_workspace_ownership(
    client, users, domain, path, get_action, update_action, delete_action, payload
):
    owner, other = users
    _, headers = credential(client, owner, SCOPES)
    item = client.post(path, headers=other, json=payload).json()
    if get_action:
        assert (
            invoke(client, headers, get_action, {"id": item["id"]}).status_code == 404
        )
    assert (
        invoke(
            client, headers, update_action, {"id": item["id"], "name": "Hack"}, uuid4()
        ).status_code
        == 404
    )
    assert (
        invoke(client, headers, delete_action, {"id": item["id"]}, uuid4()).status_code
        == 404
    )


def test_same_user_other_workspace_and_record_parent(client, users):
    owner, _ = users
    agent, headers = credential(client, owner, SCOPES)
    collection = client.post(
        "/api/v1/data/collections", headers=owner, json={"name": "Other workspace"}
    ).json()
    record = client.post(
        f"/api/v1/data/collections/{collection['id']}/records",
        headers=owner,
        json={"name": "Secret"},
    ).json()
    with session(client) as db:
        a = db.get(Agent, agent["id"])
        workspace = Workspace(
            id=str(uuid4()), owner_user_id=a.user_id, name="Second", kind="custom"
        )
        db.add(workspace)
        a.workspace_id = workspace.id
        db.commit()
    assert invoke(client, headers, "data.collections.list").json()["data"] == []
    for action, args in [
        ("data.record.get", {"id": record["id"]}),
        ("data.record.update", {"id": record["id"], "name": "Hack"}),
        ("data.record.delete", {"id": record["id"]}),
        ("data.record.create", {"collectionId": collection["id"], "name": "Hack"}),
    ]:
        assert invoke(client, headers, action, args, uuid4()).status_code == 404


def test_failure_rolls_back_business_outbox_and_success_receipt(
    client, users, monkeypatch
):
    _, headers = credential(client, users[0], SCOPES)
    original = ledger.publish_ledger

    def fail_after_publish(*args):
        original(*args)
        raise RuntimeError("secret-path-token")

    monkeypatch.setattr(ledger, "publish_ledger", fail_after_publish)
    result = invoke(client, headers, "ledger.transaction.create", TX, uuid4())
    assert result.status_code == 500 and "secret-path-token" not in result.text
    with session(client) as db:
        for model in (LedgerTransaction, LocalMutation, AgentActionLog):
            assert db.scalar(select(func.count()).select_from(model)) == 0


def local_tool_client(local):
    app = FastAPI()
    app.include_router(router)

    def get_session():
        with local.factory() as db:
            yield db

    app.dependency_overrides[get_db] = get_session
    token = "na_live_" + str(uuid4())
    with local.factory() as db:
        db.add(
            Agent(
                id=str(uuid4()),
                user_id=local.user_id,
                workspace_id=local.workspace_id,
                name="Tool Agent",
                data_scopes=SCOPES,
                token_hash=hashlib.sha256(token.encode()).hexdigest(),
            )
        )
        db.commit()
    return TestClient(app), {"Authorization": "Bearer " + token}


def test_parallel_first_ledger_reads_seed_once(tmp_path):
    from app.api import ledger as ledger_api
    from app.security import create_access_token

    local = replica(tmp_path, "dashboard_reads", 52)
    with local.factory() as db:
        db.add(
            LedgerCategory(
                id=str(uuid4()),
                user_id=local.user_id,
                workspace_id=local.workspace_id,
                name="Legacy",
                type="expense",
                icon="shopping",
            )
        )
        db.commit()
    app = FastAPI()
    app.include_router(ledger_api.router)

    def database():
        with local.factory() as db:
            yield db

    app.dependency_overrides[get_db] = database
    client = TestClient(app)
    headers = {"Authorization": "Bearer " + create_access_token(local.user_id)}

    def read(index):
        return client.get(
            "/api/v1/ledger/" + ["categories", "summary", "transactions"][index % 3],
            headers=headers,
        )

    try:
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(read, range(6)))
        assert all(result.status_code == 200 for result in results)
        with local.factory() as db:
            assert db.scalar(select(func.count()).select_from(LocalSyncState)) == 1
            assert db.scalar(select(func.count()).select_from(LocalMutation)) == 1
            assert db.get(LocalSyncState, local.workspace_id).queue_seed_version == 3
    finally:
        client.close()
        local.engine.dispose()


def test_concurrent_response_loss_one_receipt(tmp_path):
    local = replica(tmp_path, "concurrent", 51)
    client, headers = local_tool_client(local)
    action_id = uuid4()

    def run(_):
        return invoke(client, headers, "ledger.transaction.create", TX, action_id)

    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(run, range(4)))
        assert all(r.status_code == 200 for r in results), [r.text for r in results]
        assert sum(not r.json()["replayed"] for r in results) == 1
        with local.factory() as db:
            for model in (LedgerTransaction, LocalMutation, AgentActionLog):
                assert db.scalar(select(func.count()).select_from(model)) == 1
    finally:
        client.close()
        local.engine.dispose()


def test_agent_offline_outbox_manual_sync_all_domains(network):
    n = network
    client, headers = local_tool_client(n.a)
    try:
        ids = {}
        ids["ledger.transaction"] = invoke(
            client, headers, "ledger.transaction.create", TX, uuid4()
        ).json()["data"]["entityId"]
        category = invoke(
            client, headers, "website.category.create", {"name": "Development"}, uuid4()
        ).json()["data"]["entityId"]
        ids["website"] = invoke(
            client,
            headers,
            "website.create",
            {"name": "Tool", "url": "https://example.com", "categoryId": category},
            uuid4(),
        ).json()["data"]["entityId"]
        collection = invoke(
            client, headers, "data.collection.create", {"name": "Servers"}, uuid4()
        ).json()["data"]["entityId"]
        ids["data.record"] = invoke(
            client,
            headers,
            "data.record.create",
            {"collectionId": collection, "name": "Mac mini", "dataJson": {"cpu": "M4"}},
            uuid4(),
        ).json()["data"]["entityId"]
        with n.a.factory() as db:
            assert len(db.scalars(select(LocalMutation)).all()) == 5
        assert n.sync(n.a, n.ta)["pushed"] == 5
        assert n.sync(n.b, n.tb)["status"] == "ok"
        from app.sync.adapters import get_adapter

        for local in (n.a, n.core, n.b):
            with local.factory() as db:
                for entity_type, entity_id in ids.items():
                    adapter = get_adapter(entity_type)
                    item = db.get(adapter.model, entity_id)
                    assert (
                        item is not None
                        and adapter.workspace_id(db, item) == local.workspace_id
                    )
                    if entity_type == "ledger.transaction":
                        assert ledger.transaction_out(item)["occurredAt"] == "2026-09-30T01:00:00+00:00"
        for parent_action, parent_id in [
            ("website.category.delete", category),
            ("data.collection.delete", collection),
        ]:
            assert (
                invoke(
                    client, headers, parent_action, {"id": parent_id}, uuid4()
                ).status_code
                == 200
            )
        assert n.sync(n.a, n.ta)["status"] == "ok"
        assert n.sync(n.b, n.tb)["status"] == "ok"
        for local in (n.a, n.core, n.b):
            with local.factory() as db:
                assert db.get(Website, ids["website"]).category_id is None
                assert db.get(DataRecord, ids["data.record"]).deleted_at is not None
    finally:
        client.close()
