"""Local replica state and durable multi-entity outbox; this module performs no network I/O."""

from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..models import LocalMutation, LocalSyncState, utcnow
from .adapters import REGISTRY, adapter_for, get_adapter, seed_version


def get_local_sync_state(db: Session, workspace_id: str) -> LocalSyncState:
    state = db.get(LocalSyncState, workspace_id)
    if state is None:
        # First Dashboard reads may arrive concurrently. Adopt the winner's row
        # inside this transaction instead of racing an ORM INSERT/rollback.
        if db.get_bind().dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import insert
        else:
            from sqlalchemy.dialects.sqlite import insert
        db.execute(
            insert(LocalSyncState)
            .values(workspace_id=workspace_id)
            .on_conflict_do_nothing(index_elements=["workspace_id"])
        )
        state = db.get(LocalSyncState, workspace_id)
    return state


def bind_local_sync_state(db: Session, workspace_id: str, metadata) -> LocalSyncState:
    """Bind to CoreConnectionMetadata without resetting an existing cursor."""
    state = get_local_sync_state(db, workspace_id)
    proposed = (metadata.coreUrl, metadata.workspaceId, metadata.clientId)
    existing = (
        state.remote_core_url,
        state.remote_workspace_id,
        state.remote_client_id,
    )
    if any(value is not None for value in existing) and existing != proposed:
        raise HTTPException(
            409, "Local sync state is bound to a different Core identity"
        )
    state.remote_core_url, state.remote_workspace_id, state.remote_client_id = proposed
    return state


def entity_type(item) -> str:
    return adapter_for(item).entity_type


def queued_entries(db: Session, item) -> list[LocalMutation]:
    return db.scalars(
        select(LocalMutation).where(
            LocalMutation.workspace_id == adapter_for(item).workspace_id(db, item),
            LocalMutation.entity_type == entity_type(item),
            LocalMutation.entity_id == item.id,
        )
    ).all()


def queued(db: Session, item) -> LocalMutation | None:
    """Return the editable tail if present, otherwise its frozen predecessor."""
    entries = queued_entries(db, item)
    return next(
        (entry for entry in entries if entry.status == "pending"),
        entries[0] if entries else None,
    )


def _new_mutation(db, item, operation: str, payload: dict | None) -> LocalMutation:
    return LocalMutation(
        id=str(uuid4()),
        mutation_id=str(uuid4()),
        workspace_id=adapter_for(item).workspace_id(db, item),
        entity_type=entity_type(item),
        entity_id=item.id,
        operation=operation,
        base_revision=item.sync_revision,
        payload_json=payload,
        status="pending",
        attempt_count=0,
    )


def record_local_upsert(db: Session, item) -> LocalMutation:
    if item.sync_revision is None:
        # SQLAlchemy column defaults are assigned at flush; production sessions
        # disable autoflush, so a newly created Local row needs its initial zero now.
        item.sync_revision = 0
    payload = adapter_for(item).serialize(item)
    # The outbox sends the exact same complete business shape as Protocol v2.
    adapter_for(item).schema.model_validate(payload)
    entries = queued_entries(db, item)
    entry = next((value for value in entries if value.status == "pending"), None)
    if entry is None:
        entry = _new_mutation(db, item, "upsert", payload)
        predecessor = next(
            (value for value in entries if value.status != "pending"), None
        )
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


def record_local_delete(db: Session, item) -> None:
    def publish(db, child, operation):
        db.flush()
        (
            record_local_upsert(db, child)
            if operation == "upsert"
            else record_local_delete(db, child)
        )

    adapter_for(item).prepare_delete(db, item, publish)

    entries = queued_entries(db, item)
    pending = next((value for value in entries if value.status == "pending"), None)
    predecessor = next((value for value in entries if value.status != "pending"), None)
    if (
        item.sync_revision == 0
        and predecessor is None
        and pending is not None
        and pending.attempt_count == 0
        and pending.operation == "upsert"
    ):
        db.delete(pending)
        return
    if item.sync_revision == 0 and not entries:
        # A legacy local tombstone has no known Core identity.
        return
    if pending is None:
        pending = _new_mutation(db, item, "delete", None)
        if predecessor is not None:
            pending.depends_on_mutation_id = predecessor.mutation_id
        db.add(pending)
    else:
        if pending.attempt_count != 0:
            raise RuntimeError("An attempted mutation cannot be edited")
        pending.operation = "delete"
        pending.payload_json = None
        pending.updated_at = utcnow()


def seed_local_queue(db: Session, workspace_id: str) -> LocalSyncState:
    """One-time, idempotent adoption of active revision-zero Local rows in unseeded generations."""
    state = get_local_sync_state(db, workspace_id)
    # The caller may have read an unseeded state before another request committed.
    # Serialize the one-time seed and refresh after acquiring the database lock.
    db.execute(
        update(LocalSyncState)
        .where(LocalSyncState.workspace_id == workspace_id)
        .values(
            queue_seed_version=LocalSyncState.queue_seed_version,
            updated_at=LocalSyncState.updated_at,
        )
    )
    db.refresh(state)
    if state.queue_seed_version >= seed_version():
        return state
    for adapter in REGISTRY.values():
        if adapter.generation <= state.queue_seed_version:
            continue
        for item in adapter.legacy_rows(db, workspace_id):
            repaired = adapter.prepare_local_seed(db, item)
            if repaired or queued(db, item) is None:
                record_local_upsert(db, item)
    state.queue_seed_version = seed_version()
    state.queue_seeded_at = utcnow()
    db.flush()
    return state


def ordered_pending_mutations(db: Session, workspace_id: str) -> list[LocalMutation]:
    """Dependency order for Phase 3 push; created_at only breaks ties."""
    entries = db.scalars(
        select(LocalMutation).where(
            LocalMutation.workspace_id == workspace_id,
            LocalMutation.status == "pending",
            LocalMutation.depends_on_mutation_id.is_(None),
        )
    ).all()
    return sorted(
        entries,
        key=lambda entry: (
            get_adapter(entry.entity_type).push_priority(entry.operation),
            entry.created_at,
            entry.id,
        ),
    )


# Compatibility for existing Ledger callers.
seed_local_ledger_queue = seed_local_queue
