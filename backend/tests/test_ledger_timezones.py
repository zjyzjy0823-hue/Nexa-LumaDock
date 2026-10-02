"""Ledger input offsets must survive REST, Agent and durable Sync persistence."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.database import get_db
from app.models import LedgerTransaction, LocalMutation, User
from app.services import ledger
from app.sync.schemas import TransactionData
from test_agent_actions import credential, invoke
from test_sync_engine import network


UTC_TEXT = "2026-10-02T09:48:00+00:00"
UTC_TIME = datetime(2026, 10, 2, 9, 48, tzinfo=timezone.utc)
OFFSET_INPUTS = [
    "2026-10-02T17:48:00+08:00",
    "2026-10-02T05:48:00-04:00",
    "2026-10-02T09:48:00Z",
    "2026-10-02T09:48:00",
]
TRANSACTION = {"type": "expense", "amount": "38.00", "description": "Timezone proof"}
ROOT = "/api/v1/ledger/transactions"


def assert_utc_row(db, entity_id):
    item = db.get(LedgerTransaction, entity_id)
    # SQLite can return naive datetimes; its stored wall-clock must already be UTC.
    assert item.occurred_at.replace(tzinfo=None) == UTC_TIME.replace(tzinfo=None)
    assert ledger.transaction_out(item)["occurredAt"] == UTC_TEXT


@pytest.mark.parametrize("occurred_at", OFFSET_INPUTS)
def test_input_schemas_canonicalize_ledger_time(occurred_at):
    models = [
        ledger.TransactionInput(**TRANSACTION, occurred_at=occurred_at),
        ledger.TransactionPatch(occurred_at=occurred_at),
        TransactionData(**TRANSACTION, occurredAt=occurred_at),
    ]
    for model in models:
        value = getattr(model, "occurred_at", getattr(model, "occurredAt", None))
        assert value == UTC_TIME and value.tzinfo == timezone.utc
    assert ledger.TransactionPatch(occurred_at=None).occurred_at is None


@pytest.mark.parametrize("occurred_at", OFFSET_INPUTS)
def test_rest_create_persists_utc(client, users, occurred_at):
    owner, _ = users
    response = client.post(ROOT, headers=owner, json={**TRANSACTION, "occurred_at": occurred_at})
    assert response.status_code == 201
    entity_id = response.json()["id"]
    assert response.json()["occurredAt"] == UTC_TEXT
    assert client.get(f"{ROOT}/{entity_id}", headers=owner).json()["occurredAt"] == UTC_TEXT
    with next(client.app.dependency_overrides[get_db]()) as db:
        assert_utc_row(db, entity_id)
        entry = db.scalar(select(LocalMutation).where(LocalMutation.entity_id == entity_id))
        assert entry.payload_json["occurredAt"] == UTC_TEXT


def test_rest_patch_persists_utc_and_preserves_null_rejection(client, users):
    owner, _ = users
    created = client.post(ROOT, headers=owner, json={
        **TRANSACTION, "occurred_at": "2026-10-01T00:00:00Z"}).json()
    entity_id = created["id"]
    patched = client.patch(f"{ROOT}/{entity_id}", headers=owner,
                          json={"occurred_at": OFFSET_INPUTS[1]})
    assert patched.status_code == 200 and patched.json()["occurredAt"] == UTC_TEXT
    assert client.patch(f"{ROOT}/{entity_id}", headers=owner,
                        json={"occurred_at": None}).status_code == 422
    assert client.get(f"{ROOT}/{entity_id}", headers=owner).json()["occurredAt"] == UTC_TEXT
    with next(client.app.dependency_overrides[get_db]()) as db:
        assert_utc_row(db, entity_id)


def test_agent_create_and_patch_persist_utc(client, users):
    owner, _ = users
    _, agent_headers = credential(client, owner, ["ledger:write", "ledger:read"])
    created = invoke(client, agent_headers, "ledger.transaction.create",
                     {**TRANSACTION, "occurredAt": OFFSET_INPUTS[0]}, uuid4())
    assert created.status_code == 200
    entity_id = created.json()["data"]["entityId"]
    assert client.get(f"{ROOT}/{entity_id}", headers=owner).json()["occurredAt"] == UTC_TEXT
    patched = invoke(client, agent_headers, "ledger.transaction.update",
                     {"id": entity_id, "occurredAt": OFFSET_INPUTS[1]}, uuid4())
    assert patched.status_code == 200
    assert client.get(f"{ROOT}/{entity_id}", headers=owner).json()["occurredAt"] == UTC_TEXT
    with next(client.app.dependency_overrides[get_db]()) as db:
        assert_utc_row(db, entity_id)
        entry = db.scalar(select(LocalMutation).where(LocalMutation.entity_id == entity_id))
        assert entry.payload_json["occurredAt"] == UTC_TEXT


def test_nonzero_offset_sync_push_and_remote_apply_persist_same_instant(network, monkeypatch):
    n = network
    with n.a.factory() as db:
        created = ledger.create_transaction(
            ledger.TransactionInput(**TRANSACTION, occurred_at=OFFSET_INPUTS[0]),
            user=db.get(User, n.a.user_id), db=db)
        db.commit()
        entity_id = created["id"]
        assert_utc_row(db, entity_id)
        entry = db.scalar(select(LocalMutation).where(LocalMutation.entity_id == entity_id))
        assert entry.payload_json["occurredAt"] == UTC_TEXT
        # An older peer may still send a valid non-UTC offset on the wire.
        entry.payload_json = {**entry.payload_json, "occurredAt": OFFSET_INPUTS[0]}
        db.commit()
    assert n.sync(n.a, n.ta)["pushed"] == 1
    assert n.ta.sent[0]["data"]["occurredAt"] == OFFSET_INPUTS[0]

    original_changes = n.tb.get_changes

    def offset_changes(cursor, limit):
        page = original_changes(cursor, limit)
        for change in page["changes"]:
            if change["entityId"] == entity_id:
                change["data"] = {**change["data"], "occurredAt": OFFSET_INPUTS[1]}
        return page

    monkeypatch.setattr(n.tb, "get_changes", offset_changes)
    received = n.sync(n.b, n.tb)
    assert received["status"] == "ok" and received["pulled"] == 1
    for replica in (n.a, n.core, n.b):
        with replica.factory() as db:
            assert_utc_row(db, entity_id)
