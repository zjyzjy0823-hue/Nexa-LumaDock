"""Rejected mutations get two explicit exits (resync R5/R6).

A rejected push used to be terminal: the frozen unique index blocked new writes
for the entity and dependent tails waited forever. ``dismiss`` drops the chain,
``retry`` rebuilds one pending mutation from the *current* business row.
"""

from uuid import uuid4

import pytest
from sqlalchemy import select

from app.database import get_db
from app.models import LocalMutation, User
from app.workspaces import get_personal_workspace

SYNC = "/api/v1/sync"
WEBSITE = {"name": "rejected chain", "url": "https://rejected.example.com"}


def db_session(client):
    return next(client.app.dependency_overrides[get_db]())


def seed_rejected(client, headers, payload=None, with_tail=True):
    """Insert a rejected mutation (plus one dependent tail) for the owner's workspace."""
    with db_session(client) as db:
        user = db.scalar(select(User).order_by(User.id))
        workspace = get_personal_workspace(db, user)
        website = client.post("/api/v1/websites", headers=headers, json=WEBSITE).json()
        # The ordinary write already queued a pending mutation for the entity; the
        # rejected entry replaces it (that is exactly what a rejected push leaves).
        for existing in db.scalars(select(LocalMutation).where(
                LocalMutation.workspace_id == workspace.id,
                LocalMutation.entity_id == website["id"])).all():
            db.delete(existing)
        db.flush()
        entry = LocalMutation(
            id=str(uuid4()), mutation_id=str(uuid4()), workspace_id=workspace.id,
            entity_type="website", entity_id=website["id"], operation="upsert",
            base_revision=0, payload_json=payload if payload is not None else WEBSITE,
            status="rejected", attempt_count=1, last_error="invalid_fields")
        tail = None
        if with_tail:
            tail = LocalMutation(
                id=str(uuid4()), mutation_id=str(uuid4()), workspace_id=workspace.id,
                entity_type="website", entity_id=website["id"], operation="upsert",
                base_revision=0, payload_json={**WEBSITE, "name": "tail edit"},
                status="pending", attempt_count=0, depends_on_mutation_id=entry.mutation_id)
        db.add(entry)
        if tail is not None:
            db.add(tail)
        db.commit()
        return entry.id, entry.mutation_id, (tail.id if tail else None), website["id"], workspace.id


def rows(client, workspace_id):
    with db_session(client) as db:
        return {item.id: item for item in db.scalars(
            select(LocalMutation).where(LocalMutation.workspace_id == workspace_id)).all()}


def test_dismiss_resolves_entry_and_skips_tails(client, users):
    owner, _ = users
    entry_id, mutation_id, tail_id, _, workspace_id = seed_rejected(client, owner)
    response = client.post(f"{SYNC}/rejected/{entry_id}/dismiss", headers=owner)
    assert response.status_code == 200, response.text
    receipt = response.json()
    assert receipt["decision"] == "dismiss" and receipt["status"] == "resolved"
    assert receipt["mutationId"] is None

    state = rows(client, workspace_id)
    assert state[entry_id].status == "resolved"
    assert state[entry_id].payload_json is None
    assert state[tail_id].status == "skipped"
    assert state[tail_id].depends_on_mutation_id is None


def test_dismiss_is_idempotent_and_rejects_a_second_decision(client, users):
    owner, _ = users
    entry_id, _, _, _, _ = seed_rejected(client, owner)
    first = client.post(f"{SYNC}/rejected/{entry_id}/dismiss", headers=owner).json()
    again = client.post(f"{SYNC}/rejected/{entry_id}/dismiss", headers=owner)
    assert again.status_code == 200 and again.json() == first
    other = client.post(f"{SYNC}/rejected/{entry_id}/retry", headers=owner)
    assert other.status_code == 409 and other.json()["detail"] == "rejected_already_resolved"


def test_retry_rebuilds_from_the_current_business_row(client, users):
    owner, _ = users
    entry_id, old_mutation, tail_id, website_id, workspace_id = seed_rejected(
        client, owner, payload={**WEBSITE, "name": "stale payload"})
    # The user fixes the row before retrying; the retry must carry the fixed value.
    client.patch(f"/api/v1/websites/{website_id}", headers=owner, json={"name": "fixed before retry"})
    response = client.post(f"{SYNC}/rejected/{entry_id}/retry", headers=owner)
    assert response.status_code == 200, response.text
    receipt = response.json()
    assert receipt["decision"] == "retry" and receipt["mutationId"]

    state = rows(client, workspace_id)
    assert state[entry_id].status == "resolved"
    pending = [item for item in state.values() if item.status == "pending"]
    assert len(pending) == 1
    rebuilt = pending[0]
    assert rebuilt.mutation_id == receipt["mutationId"] != old_mutation
    assert rebuilt.payload_json["name"] == "fixed before retry"
    assert rebuilt.depends_on_mutation_id is None
    # The local fix already queued one pending row for the entity; retry reuses it
    # (the queue only ever holds a single pending row per entity), so no entry may
    # keep pointing at the rejected mutation any more.
    assert not [item for item in state.values()
                if item.depends_on_mutation_id == old_mutation]


def test_retry_is_idempotent(client, users):
    owner, _ = users
    entry_id, _, _, _, _ = seed_rejected(client, owner)
    first = client.post(f"{SYNC}/rejected/{entry_id}/retry", headers=owner).json()
    again = client.post(f"{SYNC}/rejected/{entry_id}/retry", headers=owner)
    assert again.status_code == 200 and again.json() == first


def test_decision_on_a_pending_mutation_is_not_found(client, users):
    owner, _ = users
    with db_session(client) as db:
        user = db.scalar(select(User).order_by(User.id))
        workspace = get_personal_workspace(db, user)
        website = client.post("/api/v1/websites", headers=owner, json=WEBSITE).json()
        for existing in db.scalars(select(LocalMutation).where(
                LocalMutation.workspace_id == workspace.id,
                LocalMutation.entity_id == website["id"])).all():
            db.delete(existing)
        db.flush()
        entry = LocalMutation(
            id=str(uuid4()), mutation_id=str(uuid4()), workspace_id=workspace.id,
            entity_type="website", entity_id=website["id"], operation="upsert",
            base_revision=0, payload_json=WEBSITE, status="pending", attempt_count=0)
        db.add(entry)
        db.commit()
        entry_id = entry.id
    for decision in ("dismiss", "retry"):
        response = client.post(f"{SYNC}/rejected/{entry_id}/{decision}", headers=owner)
        assert response.status_code == 404 and response.json()["detail"] == "rejected_not_found"


def test_status_counts_drop_after_dismiss(client, users):
    owner, _ = users
    entry_id, _, _, _, _ = seed_rejected(client, owner)
    assert client.get(f"{SYNC}/status", headers=owner).json()["rejected"] == 1
    assert client.post(f"{SYNC}/rejected/{entry_id}/dismiss", headers=owner).status_code == 200
    assert client.get(f"{SYNC}/status", headers=owner).json()["rejected"] == 0


def test_decision_requires_another_users_entry_to_stay_hidden(client, users):
    owner, stranger = users
    entry_id, _, _, _, _ = seed_rejected(client, owner)
    response = client.post(f"{SYNC}/rejected/{entry_id}/dismiss", headers=stranger)
    assert response.status_code == 404

def test_retry_without_a_pending_tail_creates_one(client, users):
    owner, _ = users
    entry_id, old_mutation, _, website_id, workspace_id = seed_rejected(client, owner, with_tail=False)
    client.patch(f"/api/v1/websites/{website_id}", headers=owner, json={"name": "fresh retry"})
    # Drop the row the ordinary patch queued, so retry is the only writer.
    with db_session(client) as db:
        for item in db.scalars(select(LocalMutation).where(
                LocalMutation.workspace_id == workspace_id,
                LocalMutation.entity_id == website_id,
                LocalMutation.status == "pending")).all():
            db.delete(item)
        db.commit()
    response = client.post(f"{SYNC}/rejected/{entry_id}/retry", headers=owner)
    assert response.status_code == 200, response.text
    receipt = response.json()
    state = rows(client, workspace_id)
    rebuilt = [item for item in state.values() if item.status == "pending"]
    assert len(rebuilt) == 1
    assert rebuilt[0].mutation_id == receipt["mutationId"] != old_mutation
    assert rebuilt[0].payload_json["name"] == "fresh retry"


def test_list_shows_only_rejected_entries(client, users):
    owner, _ = users
    entry_id, mutation_id, _, website_id, _ = seed_rejected(client, owner)
    listed = client.get(f"{SYNC}/rejected", headers=owner)
    assert listed.status_code == 200
    rows_ = listed.json()
    assert [item["id"] for item in rows_] == [entry_id]
    item = rows_[0]
    assert item["mutationId"] == mutation_id
    assert item["entityType"] == "website" and item["entityId"] == website_id
    assert item["reason"] == "invalid_fields"
    assert item["payload"]["url"] == WEBSITE["url"]


def test_list_is_empty_after_a_decision(client, users):
    owner, _ = users
    entry_id, _, _, _, _ = seed_rejected(client, owner)
    client.post(f"{SYNC}/rejected/{entry_id}/dismiss", headers=owner)
    assert client.get(f"{SYNC}/rejected", headers=owner).json() == []
