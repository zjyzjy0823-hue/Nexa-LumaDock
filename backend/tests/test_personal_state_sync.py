"""Personal business APIs, replica convergence, isolation and secret boundaries."""
from dataclasses import replace
import json
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api import settings, dashboard
from app.api.automation import routes as automation
from app.database import get_db
from app.main import app
from app.models import (User, LocalMutation, LocalSyncState, SyncChange, SyncWorkspaceState,
                        UserPreference, Dashboard, AutomationWorkflow, AutomationExecution)
from app.schemas import Layout
from app.sync import publisher
from app.sync.adapters import get_adapter
from app.sync.adapters.personal_state import PreferencesData, CATALOG
from app.sync.conflicts import list_conflicts, resolve_conflict
from app.sync.engine import _apply_change, run_sync_cycle
from app.sync.local import seed_local_queue
from app.sync.remote import SyncRemoteError
from app.sync.service import ensure_core_sync_initialized
from app.runtime_mode import require_core_mode
from test_sync_engine import network
from test_sync import user, enroll, mutation, db_session, ROOT

KINDS = ("user.preferences", "dashboard.layout", "automation.definition")


def write(local, kind, variant=1, entity_id=None):
    with local.factory() as db:
        owner = db.get(User, local.user_id)
        if kind == "user.preferences":
            settings.patch_settings(settings.SettingsPatch(theme="dark" if variant == 1 else "light"), owner, db)
        elif kind == "dashboard.layout":
            layout = CATALOG.model_dump()
            layout["widgets"] = layout["widgets"][:variant + 1]
            dashboard.update_layout(Layout.model_validate(layout), owner, db)
        elif entity_id is None:
            result = automation.create_workflow(automation.WorkflowInput(name="Daily Summary",
                trigger_type="schedule", trigger_config_json={"cron": "0 9 * * *"},
                workflow_json=[{"kind": "DO", "text": "Notify"}]), owner, db)
            return result["id"]
        else:
            automation.patch_workflow(entity_id, automation.WorkflowPatch(description=f"Variant {variant}",
                enabled=variant == 1), owner, db)
        return entity_id or get_adapter(kind).entity_id()


def payload(local, kind, entity_id):
    with local.factory() as db:
        adapter = get_adapter(kind)
        item = adapter.find(db, entity_id, local.workspace_id)
        return None if item is None or item.deleted_at else adapter.serialize(item)


@pytest.mark.parametrize("kind", KINDS)
def test_business_api_outbox_pull_stable_identity_restart(network, kind):
    n = network
    entity_id = write(n.a, kind)
    with n.a.factory() as db:
        entry = db.scalar(select(LocalMutation).where(LocalMutation.entity_type == kind))
        assert entry.status == "pending" and entry.attempt_count == 0 and entry.entity_id == entity_id
        assert entry.payload_json == payload(n.a, kind, entity_id)
        assert db.get(LocalSyncState, n.a.workspace_id).queue_seed_version == 3
    # Close connections, then resume using fresh sessions on the durable file.
    n.a.engine.dispose()
    assert n.sync(n.a, n.ta)["pushed"] == 1
    assert n.sync(n.b, n.tb)["status"] == "ok"
    assert payload(n.a, kind, entity_id) == payload(n.b, kind, entity_id) == payload(n.core, kind, entity_id)
    write(n.b, kind, 2, entity_id)
    assert n.sync(n.b, n.tb)["status"] == "ok"
    n.sync(n.a, n.ta)
    assert payload(n.a, kind, entity_id) == payload(n.b, kind, entity_id)
    with n.core.factory() as db:
        assert {row.entity_id for row in db.scalars(select(SyncChange).where(SyncChange.entity_type == kind))} == {entity_id}


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("strategy", ["local", "remote"])
def test_conflict_latest_tail_stale_race_and_both_decisions(network, kind, strategy):
    n = network
    entity_id = write(n.a, kind)
    n.sync(n.a, n.ta); n.sync(n.b, n.tb)
    write(n.a, kind, 2, entity_id)
    write(n.b, kind, 3, entity_id)
    n.sync(n.a, n.ta)
    assert n.sync(n.b, n.tb)["conflicts"] == 1
    with n.b.factory() as db:
        snapshot = list_conflicts(db, n.b.workspace_id)["conflicts"][0]
    # A fresh ordinary edit becomes a dependent pending tail, not a second owner.
    write(n.b, kind, 4, entity_id)
    if kind == "user.preferences":
        # Distinct allowed values for the second remote revision.
        with n.a.factory() as db:
            settings.patch_settings(settings.SettingsPatch(theme="system"), db.get(User, n.a.user_id), db)
    else:
        write(n.a, kind, 5, entity_id)
    n.sync(n.a, n.ta); n.sync(n.b, n.tb)
    with n.b.factory() as db:
        with pytest.raises(HTTPException, match="409"):
            resolve_conflict(db, n.b.user_id, n.b.workspace_id, snapshot["id"], strategy, snapshot["remoteRevision"])
    expected = payload(n.b if strategy == "local" else n.core, kind, entity_id)
    with n.b.factory() as db:
        current = list_conflicts(db, n.b.workspace_id)["conflicts"][0]
        assert current["hasPendingTail"]
        receipt = resolve_conflict(db, n.b.user_id, n.b.workspace_id, current["id"], strategy, current["remoteRevision"])
        assert receipt["status"] == "resolved"
    n.sync(n.b, n.tb); n.sync(n.a, n.ta)
    for local in (n.a, n.b, n.core):
        assert payload(local, kind, entity_id) == expected


def test_automation_tombstone_history_local_and_edit_delete_restore(network):
    n = network
    kind = "automation.definition"
    entity_id = write(n.a, kind)
    with n.a.factory() as db:
        automation.test_run(entity_id, db.get(User, n.a.user_id), db)
    n.sync(n.a, n.ta); n.sync(n.b, n.tb)
    with n.b.factory() as db:
        assert db.scalars(select(AutomationExecution)).all() == []
        automation.delete_workflow(entity_id, db.get(User, n.b.user_id), db)
    write(n.a, kind, 2, entity_id)
    n.sync(n.b, n.tb)
    assert n.sync(n.a, n.ta)["conflicts"] == 1
    with n.a.factory() as db:
        conflict = list_conflicts(db, n.a.workspace_id)["conflicts"][0]
        assert conflict["remoteDeleted"] and not conflict["localDeleted"]
        resolve_conflict(db, n.a.user_id, n.a.workspace_id, conflict["id"], "local", conflict["remoteRevision"])
    n.sync(n.a, n.ta); n.sync(n.b, n.tb)
    assert payload(n.b, kind, entity_id) == payload(n.a, kind, entity_id)
    with n.b.factory() as db:
        automation.delete_workflow(entity_id, db.get(User, n.b.user_id), db)
    n.sync(n.b, n.tb); n.sync(n.a, n.ta)
    for local in (n.a, n.b, n.core):
        with local.factory() as db:
            assert db.get(AutomationWorkflow, entity_id).deleted_at is not None
    with n.a.factory() as db:
        assert len(db.scalars(select(AutomationExecution)).all()) == 1
        with pytest.raises(HTTPException):
            automation.workflow_or_404(db, db.get(User, n.a.user_id), entity_id)


@pytest.mark.parametrize("kind", KINDS[:2])
def test_singleton_reset_upsert_and_reject_delete_arbitrary_id(network, kind):
    n = network
    entity_id = write(n.a, kind)
    n.sync(n.a, n.ta); n.sync(n.b, n.tb)
    with n.a.factory() as db:
        if kind == "user.preferences":
            settings.patch_settings(settings.SettingsPatch(theme="system"), db.get(User, n.a.user_id), db)
        else:
            dashboard.update_layout(CATALOG, db.get(User, n.a.user_id), db)
    n.sync(n.a, n.ta); n.sync(n.b, n.tb)
    assert payload(n.a, kind, entity_id) == payload(n.b, kind, entity_id)
    for operation, identity in (("delete", entity_id), ("upsert", str(uuid4()))):
        result = n.ta.push_mutation(mutation(kind, identity, 0, operation, payload(n.a, kind, entity_id) if operation == "upsert" else None))
        assert result["status"] == "rejected"
        assert result["reason"] == ("delete_unsupported" if operation == "delete" else "invalid_id")
    with pytest.raises(SyncRemoteError):
        _apply_change(n.b.factory, n.b.user_id, n.b.workspace_id,
                      {"entityType": kind, "entityId": entity_id, "operation": "delete", "revision": 999})


@pytest.mark.parametrize("mode", ["local", "core"])
def test_ordinary_publication_and_isolation(client, users, monkeypatch, mode):
    monkeypatch.setattr(publisher, "runtime_config", replace(publisher.runtime_config, mode=mode))
    a, b = users
    assert client.patch("/api/v1/settings", headers=a, json={"theme": "dark"}).status_code == 200
    layout = CATALOG.model_dump(); layout["widgets"] = layout["widgets"][:2]
    assert client.put("/api/dashboard/layout", headers=a, json=layout).status_code == 200
    workflow = client.post("/api/v1/automations", headers=a, json={"name": "Daily Summary"}).json()
    assert client.get("/api/v1/settings", headers=b).json()["theme"] == "system"
    assert len(client.get("/api/dashboard", headers=b).json()["layout_json"]["widgets"]) == len(CATALOG.widgets)
    assert client.get("/api/v1/automations", headers=b).json() == []
    assert client.patch(f"/api/v1/automations/{workflow['id']}", headers=b, json={"enabled": False}).status_code == 404
    iterator, db = db_session()
    try:
        rows = db.scalars(select(SyncChange if mode == "core" else LocalMutation)).all()
        assert {row.entity_type for row in rows} == set(KINDS)
        assert len(rows) == 3
    finally:
        iterator.close()


@pytest.mark.parametrize("kind", KINDS[:2])
def test_first_edit_adopts_existing_core_and_replica_defaults_without_conflict(network, kind):
    n = network
    for local in (n.a, n.b, n.core):
        with local.factory() as db:
            owner = db.get(User, local.user_id)
            if kind == "user.preferences":
                settings.preference(db, owner)
            else:
                dashboard.ensure_dashboard(db, owner)
    entity_id = write(n.a, kind)
    assert n.sync(n.a, n.ta)["conflicts"] == 0
    assert n.sync(n.b, n.tb)["conflicts"] == 0
    assert payload(n.a, kind, entity_id) == payload(n.b, kind, entity_id) == payload(n.core, kind, entity_id)


def test_sync_only_local_settings_preserved_and_sensitive_projection(network, caplog):
    n = network
    # Deliberately fake credentials; never use environment secrets as fixtures.
    poison = "nc_live_FAKE_TEST_ONLY"
    kind = "user.preferences"
    entity_id = write(n.a, kind)
    for local in (n.a, n.b):
        with local.factory() as db:
            item = settings.preference(db, db.get(User, local.user_id), commit=False)
            item.settings_json = {"sync": {"serverUrl": "https://device-local.example", "credential": poison},
                "security": {"token": poison}, "installationId": poison,
                "appearance": {"accent": "mint", "password": poison},
                "notifications": {"events": {"deviceOffline": False, "Authorization": poison}}}
            if local is n.a:
                publisher.publish(db, item)
            db.commit()
    n.sync(n.a, n.ta); n.sync(n.b, n.tb)
    with n.b.factory() as db:
        item = get_adapter(kind).find(db, entity_id, n.b.workspace_id)
        assert item.settings_json["sync"]["credential"] == poison  # local value never overwritten
        assert item.settings_json["appearance"]["accent"] == "mint"
        response = settings.public_settings(item)
        assert poison not in json.dumps(response)
    write(n.a, kind, 2, entity_id); write(n.b, kind, 3, entity_id)
    n.sync(n.a, n.ta); n.sync(n.b, n.tb)
    with n.b.factory() as db:
        snapshots = list_conflicts(db, n.b.workspace_id)
        mutations = [row.payload_json for row in db.scalars(select(LocalMutation))]
    with n.core.factory() as db:
        changes = [row.payload_json for row in db.scalars(select(SyncChange))]
    serialized = json.dumps([n.ta.sent, n.tb.sent, changes, snapshots, mutations, response])
    for excluded in (poison, "password", "credential", "installationId", "Authorization", "nc_live_", "token", "jwt", "secret"):
        assert excluded not in serialized
        assert poison not in caplog.text


@pytest.mark.parametrize("bad", ["nc_live_FAKE_ONLY", "na_live_FAKE_ONLY", "Bearer FAKE_ONLY", "C:\\fake\\only",
                                "/home/fake/private", "password=FAKE_ONLY", "eyJfake.payload.signature"])
def test_supported_text_fields_cannot_smuggle_secrets(client, users, bad, caplog):
    a, _ = users
    for content in ({"name": bad}, {"name": "Safe", "trigger_config_json": {"label": bad}},
                    {"name": "Safe", "workflow_json": [{"kind": "DO", "text": bad}]}):
        response = client.post("/api/v1/automations", headers=a, json=content)
        assert response.status_code == 422 and bad not in response.text
    assert bad not in caplog.text


def test_unknown_configuration_and_ownership_fields_rejected_without_echo(client, users):
    a, _ = users
    for config in ({"credential": "FAKE_ONLY"}, {"deviceId": "FAKE_ONLY"}, {"running": True}):
        response = client.post("/api/v1/automations", headers=a, json={"name": "Safe", "trigger_config_json": config})
        assert response.status_code == 422 and "FAKE_ONLY" not in response.text
    assert client.patch("/api/v1/settings", headers=a, json={"appearance": {"token": "FAKE_ONLY"}}).status_code == 422
    layout = CATALOG.model_dump(); layout["widgets"][0]["config"] = {"password": "FAKE_ONLY"}
    assert client.put("/api/dashboard/layout", headers=a, json=layout).status_code == 422


def test_mixed_protocol_2_requests_fail_before_history(client):
    app.dependency_overrides[require_core_mode] = lambda: None
    auth = user(client, "old_replica")
    credential = enroll(client, auth)
    for version in (1, 2, 4):
        assert client.get(ROOT + f"/changes?protocolVersion={version}", headers=credential).status_code == 409
        assert client.post(ROOT + "/mutations", headers=credential,
            json={"protocolVersion": version, "mutations": [mutation()]}).status_code == 409
    iterator, db = db_session()
    try:
        assert db.scalars(select(SyncChange)).all() == []
        assert db.scalars(select(SyncWorkspaceState)).all() == []
    finally:
        iterator.close()


def test_local_protocol_probe_preserves_cursor_queue_and_never_sends(network):
    n = network
    write(n.a, "user.preferences")
    class OldCore:
        def get_changes(self, cursor, limit):
            return {"protocolVersion": 2}
        def push_mutation(self, value):
            pytest.fail("No mutation may be sent after failed probe")
    with n.a.factory() as db:
        before = [(row.mutation_id, row.payload_json, row.status) for row in db.scalars(select(LocalMutation))]
    metadata = type("Metadata", (), dict(coreUrl="https://fake.example", workspaceId=n.core.workspace_id, clientId=n.ta.client_id))()
    result = run_sync_cycle(n.a.factory, n.a.user_id, n.a.workspace_id, metadata, "FAKE_ONLY", OldCore())
    assert result["lastError"] == "protocol_mismatch" and result["cursor"] == 0
    with n.a.factory() as db:
        assert before == [(row.mutation_id, row.payload_json, row.status) for row in db.scalars(select(LocalMutation))]


@pytest.mark.parametrize("kind", KINDS)
def test_authenticated_core_client_owns_personal_state_and_rejects_injected_owner(client, kind):
    app.dependency_overrides[require_core_mode] = lambda: None
    a, b = user(client, "personal_core_a"), user(client, "personal_core_b")
    ca, cb = enroll(client, a), enroll(client, b)
    adapter = get_adapter(kind)
    entity_id = adapter.entity_id() if kind != "automation.definition" else str(uuid4())
    data = (PreferencesData(theme="dark").model_dump(mode="json") if kind == "user.preferences" else
            {"schemaVersion": 1, "widgets": []} if kind == "dashboard.layout" else
            {"schemaVersion": 1, "name": "User A definition", "description": "", "enabled": True,
             "triggerType": "manual", "triggerConfigJson": {}, "workflowJson": []})
    def send(headers, value):
        return client.post(ROOT + "/mutations", headers=headers,
            json={"protocolVersion": 3, "mutations": [value]}).json()["results"][0]
    result = send(ca, mutation(kind, entity_id, data=data))
    assert result["status"] == "applied"
    assert client.get(ROOT + "/changes?protocolVersion=3", headers=cb).json()["changes"] == []
    for key in ("userId", "workspaceId", "ownerId"):
        rejected = send(cb, mutation(kind, entity_id, data={**data, key: "FAKE_OWNER_ONLY"}))
        assert rejected["status"] == "rejected"
        assert "User A definition" not in json.dumps(rejected)
    if kind == "automation.definition":
        rejected = send(cb, mutation(kind, entity_id, data=data))
        assert rejected["reason"] == "entity_id_unavailable"
    else:
        other = {**data, "theme": "light"} if kind == "user.preferences" else {"schemaVersion": 1, "widgets": [{
            "id": "clock", "position": {"x": 0, "y": 0}, "size": {"width": 284, "height": 299}}]}
        # Same canonical singleton UUID is independently owned in each workspace.
        assert send(cb, mutation(kind, entity_id, data=other))["status"] == "applied"
        feed_a = client.get(ROOT + "/changes?protocolVersion=3", headers=ca).json()["changes"]
        feed_b = client.get(ROOT + "/changes?protocolVersion=3", headers=cb).json()["changes"]
        assert len(feed_a) == len(feed_b) == 1
        assert feed_a[0]["data"] != feed_b[0]["data"]


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("mode", ["local", "core"])
def test_publication_failure_rolls_back_business_and_queue(network, monkeypatch, kind, mode):
    n = network
    monkeypatch.setattr(publisher, "runtime_config", replace(publisher.runtime_config, mode=mode))
    def fail(*args):
        raise RuntimeError("Simulated transaction failure")
    monkeypatch.setattr(publisher, "record_ordinary_change" if mode == "core" else "record_local_upsert", fail)
    with pytest.raises(RuntimeError):
        write(n.a, kind)
    with n.a.factory() as db:
        assert db.scalars(select(get_adapter(kind).model)).all() == []
        assert db.scalars(select(LocalMutation)).all() == []
        assert db.scalars(select(SyncChange)).all() == []
