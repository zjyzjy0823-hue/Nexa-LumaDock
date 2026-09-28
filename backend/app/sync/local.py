"""Local replica state and durable Ledger outbox; this module performs no network I/O."""

from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import LedgerCategory, LedgerTransaction, LocalMutation, LocalSyncState, utcnow
from .ledger import REGISTRY, serialize


PUSH_PRIORITY = {
    ("ledger.category", "upsert"): 0,
    ("ledger.transaction", "upsert"): 1,
    ("ledger.transaction", "delete"): 2,
    ("ledger.category", "delete"): 3,
}


def get_local_sync_state(db: Session, workspace_id: str) -> LocalSyncState:
    state = db.get(LocalSyncState, workspace_id)
    if state is None:
        state = LocalSyncState(workspace_id=workspace_id, cursor=0)
        db.add(state)
        db.flush()
    return state


def bind_local_sync_state(db: Session, workspace_id: str, metadata) -> LocalSyncState:
    """Bind to CoreConnectionMetadata without resetting an existing cursor."""
    state = get_local_sync_state(db, workspace_id)
    proposed = (metadata.coreUrl, metadata.workspaceId, metadata.clientId)
    existing = (state.remote_core_url, state.remote_workspace_id, state.remote_client_id)
    if any(value is not None for value in existing) and existing != proposed:
        raise HTTPException(409, "Local sync state is bound to a different Core identity")
    state.remote_core_url, state.remote_workspace_id, state.remote_client_id = proposed
    return state


def entity_type(item: LedgerCategory | LedgerTransaction) -> str:
    return "ledger.category" if isinstance(item, LedgerCategory) else "ledger.transaction"


def queued_entries(db: Session, item: LedgerCategory | LedgerTransaction) -> list[LocalMutation]:
    return db.scalars(select(LocalMutation).where(
        LocalMutation.workspace_id == item.workspace_id,
        LocalMutation.entity_type == entity_type(item), LocalMutation.entity_id == item.id)).all()


def queued(db: Session, item: LedgerCategory | LedgerTransaction) -> LocalMutation | None:
    """Return the editable tail if present, otherwise its frozen predecessor."""
    entries = queued_entries(db, item)
    return next((entry for entry in entries if entry.status == "pending"), entries[0] if entries else None)


def _new_mutation(item: LedgerCategory | LedgerTransaction, operation: str,
                  payload: dict | None) -> LocalMutation:
    return LocalMutation(id=str(uuid4()), mutation_id=str(uuid4()),
                         workspace_id=item.workspace_id, entity_type=entity_type(item),
                         entity_id=item.id, operation=operation, base_revision=item.sync_revision,
                         payload_json=payload, status="pending", attempt_count=0)


def record_local_upsert(db: Session, item: LedgerCategory | LedgerTransaction) -> LocalMutation:
    if item.sync_revision is None:
        # SQLAlchemy column defaults are assigned at flush; production sessions
        # disable autoflush, so a newly created Local row needs its initial zero now.
        item.sync_revision = 0
    payload = serialize(item)
    # The outbox sends the exact same complete business shape as Protocol v1.
    REGISTRY[entity_type(item)][1].model_validate(payload)
    entries = queued_entries(db, item)
    entry = next((value for value in entries if value.status == "pending"), None)
    if entry is None:
        entry = _new_mutation(item, "upsert", payload)
        predecessor = next((value for value in entries if value.status != "pending"), None)
        if predecessor is not None:
            entry.depends_on_mutation_id = predecessor.mutation_id
        db.add(entry)
    else:
        if entry.attempt_count != 0:
            raise RuntimeError("An attempted mutation cannot be edited")
        entry.operation = "upsert"
        entry.payload_json = payload
        entry.updated_at = utcnow()
    return entry


def record_local_delete(db: Session, item: LedgerCategory | LedgerTransaction) -> None:
    if isinstance(item, LedgerCategory) and item.sync_revision == 0:
        active = db.scalars(select(LedgerTransaction).where(
            LedgerTransaction.workspace_id == item.workspace_id,
            LedgerTransaction.category_id == item.id,
            LedgerTransaction.deleted_at.is_(None)).order_by(LedgerTransaction.id)).all()
        if any(transaction.sync_revision > 0 for transaction in active):
            raise HTTPException(409, "Unsynced category has a synced transaction")
        for transaction in active:
            transaction.category_id = None
            record_local_upsert(db, transaction)

    entries = queued_entries(db, item)
    pending = next((value for value in entries if value.status == "pending"), None)
    predecessor = next((value for value in entries if value.status != "pending"), None)
    if (item.sync_revision == 0 and predecessor is None and pending is not None and
            pending.attempt_count == 0 and pending.operation == "upsert"):
        db.delete(pending)
        return
    if item.sync_revision == 0 and not entries:
        # A legacy local tombstone has no known Core identity.
        return
    if pending is None:
        pending = _new_mutation(item, "delete", None)
        if predecessor is not None:
            pending.depends_on_mutation_id = predecessor.mutation_id
        db.add(pending)
    else:
        if pending.attempt_count != 0:
            raise RuntimeError("An attempted mutation cannot be edited")
        pending.operation = "delete"
        pending.payload_json = None
        pending.updated_at = utcnow()


def seed_local_ledger_queue(db: Session, workspace_id: str) -> LocalSyncState:
    """One-time, idempotent adoption of active revision-zero Local Ledger rows."""
    state = get_local_sync_state(db, workspace_id)
    if state.queue_seeded_at is not None:
        return state
    for model in (LedgerCategory, LedgerTransaction):
        rows = db.scalars(select(model).where(
            model.workspace_id == workspace_id, model.sync_revision == 0,
            model.deleted_at.is_(None)).order_by(model.created_at, model.id)).all()
        for item in rows:
            repaired_reference = False
            if isinstance(item, LedgerTransaction) and item.category_id is not None:
                category = db.get(LedgerCategory, item.category_id)
                if category is not None and category.sync_revision == 0 and category.deleted_at is not None:
                    item.category_id = None
                    repaired_reference = True
            if repaired_reference or queued(db, item) is None:
                record_local_upsert(db, item)
    state.queue_seeded_at = utcnow()
    db.flush()
    return state


def ordered_pending_mutations(db: Session, workspace_id: str) -> list[LocalMutation]:
    """Dependency order for Phase 3 push; created_at only breaks ties."""
    entries = db.scalars(select(LocalMutation).where(
        LocalMutation.workspace_id == workspace_id, LocalMutation.status == "pending",
        LocalMutation.depends_on_mutation_id.is_(None))).all()
    return sorted(entries, key=lambda entry: (
        PUSH_PRIORITY[(entry.entity_type, entry.operation)], entry.created_at, entry.id))
