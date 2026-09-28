from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (Client, LedgerCategory, LedgerTransaction, SyncChange,
                      SyncMutation, SyncWorkspaceState, Workspace, utcnow)
from .ledger import REGISTRY, apply_data, category_error, serialize


def lock_workspace_state(db: Session, workspace_id: str) -> SyncWorkspaceState:
    # The parent row serializes first-use state creation too. PostgreSQL holds this
    # lock through commit; SQLite ignores FOR UPDATE but serializes database writes.
    with db.no_autoflush:
        db.execute(select(Workspace).where(Workspace.id == workspace_id).with_for_update()).scalar_one()
        state = db.scalar(select(SyncWorkspaceState).where(
            SyncWorkspaceState.workspace_id == workspace_id).with_for_update())
    if state is None:
        state = SyncWorkspaceState(workspace_id=workspace_id, current_revision=0)
        db.add(state)
        db.flush()
    return state


def append_change(db: Session, state: SyncWorkspaceState,
                  item: LedgerCategory | LedgerTransaction, operation: str,
                  client_id: str | None = None) -> int:
    state.current_revision += 1
    state.updated_at = utcnow()
    item.sync_revision = state.current_revision
    entity_type = "ledger.category" if isinstance(item, LedgerCategory) else "ledger.transaction"
    db.add(SyncChange(id=str(uuid4()), workspace_id=state.workspace_id,
                      revision=state.current_revision, entity_type=entity_type,
                      entity_id=item.id, operation=operation,
                      payload_json=serialize(item) if operation == "upsert" else None,
                      origin_client_id=client_id))
    db.flush()
    return state.current_revision


def record_ordinary_change(db: Session, item: LedgerCategory | LedgerTransaction,
                           operation: str) -> None:
    state = lock_workspace_state(db, item.workspace_id)
    append_change(db, state, item, operation)


def ensure_core_sync_initialized(db: Session, workspace_id: str) -> SyncWorkspaceState:
    """Adopt active revision-zero Ledger rows into Core history exactly once."""
    state = lock_workspace_state(db, workspace_id)
    if state.initialized_at is not None:
        return state
    for model in (LedgerCategory, LedgerTransaction):
        rows = db.scalars(select(model).where(
            model.workspace_id == workspace_id, model.sync_revision == 0,
            model.deleted_at.is_(None)).order_by(model.created_at, model.id)).all()
        for item in rows:
            append_change(db, state, item, "upsert")
    state.initialized_at = utcnow()
    db.flush()
    return state


def _uuid(value: str) -> bool:
    try:
        return str(UUID(value)) == value
    except (ValueError, TypeError, AttributeError):
        return False


def apply_mutation(db: Session, client: Client, mutation: dict) -> dict:
    """Process one mutation, including its replay result, in one transaction."""
    mid = mutation.get("mutationId")
    if not isinstance(mid, str) or not _uuid(mid):
        return {"mutationId": mid, "status": "rejected", "reason": "invalid_id"}
    try:
        state = ensure_core_sync_initialized(db, client.workspace_id)
        prior = db.scalar(select(SyncMutation).where(
            SyncMutation.client_id == client.id, SyncMutation.mutation_id == mid))
        if prior is not None:
            result = prior.result_json
            db.commit()
            return result

        etype, eid = mutation.get("entityType"), mutation.get("entityId")
        operation, base = mutation.get("operation"), mutation.get("baseRevision")
        result = {"mutationId": mid, "entityType": etype, "entityId": eid,
                  "baseRevision": base}

        def reject(reason: str) -> None:
            result.update(status="rejected", reason=reason)

        if set(mutation) - {"mutationId", "entityType", "entityId", "operation", "baseRevision", "data"}:
            reject("invalid_fields")
        elif not isinstance(eid, str) or not _uuid(eid):
            reject("invalid_id")
        elif not isinstance(etype, str) or etype not in REGISTRY:
            reject("unknown_entity_type")
        elif operation not in ("upsert", "delete"):
            reject("invalid_operation")
        elif not isinstance(base, int) or isinstance(base, bool) or not 0 <= base <= 2**63 - 1:
            reject("invalid_base_revision")
        elif operation == "delete" and mutation.get("data") is not None:
            reject("invalid_data")
        else:
            model, schema = REGISTRY[etype]
            # Global IDs are unique. Never return another workspace's record data.
            item = db.get(model, eid)
            if item is not None and item.workspace_id != client.workspace_id:
                reject("entity_id_unavailable")
            else:
                current_revision = item.sync_revision if item is not None else 0
                if (item is None and (base != 0 or operation == "delete")) or (item is not None and base != current_revision):
                    result.update(status="conflict", currentRevision=current_revision,
                                  current=serialize(item) if item is not None and item.deleted_at is None else None,
                                  deleted=bool(item is not None and item.deleted_at is not None))
                elif item is not None and base == 0 and operation == "upsert":
                    result.update(status="conflict", currentRevision=current_revision,
                                  current=serialize(item) if item.deleted_at is None else None,
                                  deleted=item.deleted_at is not None)
                elif operation == "upsert":
                    try:
                        data = schema.model_validate(mutation.get("data"))
                    except ValidationError:
                        reject("invalid_data")
                    else:
                        if etype == "ledger.transaction":
                            reason = category_error(db, client.workspace_id, data.categoryId, data.type)
                        elif item is not None and item.type != data.type and db.scalar(
                                select(LedgerTransaction.id).where(LedgerTransaction.category_id == eid).limit(1)):
                            reason = "category_has_transactions"
                        else:
                            reason = None
                        if reason:
                            reject(reason)
                        else:
                            if item is None:
                                item = model(id=eid, workspace_id=client.workspace_id,
                                             user_id=db.get(Workspace, client.workspace_id).owner_user_id)
                                db.add(item)
                            apply_data(item, data)
                            item.deleted_at = None
                            revision = append_change(db, state, item, "upsert", client.id)
                            result.update(status="applied", revision=revision)
                else:
                    item.deleted_at = utcnow()
                    revision = append_change(db, state, item, "delete", client.id)
                    result.update(status="applied", revision=revision)

        db.add(SyncMutation(id=str(uuid4()), workspace_id=client.workspace_id, client_id=client.id,
                            mutation_id=mid, entity_type=str(etype)[:40], entity_id=str(eid)[:36], operation=str(operation)[:10],
                            base_revision=base if isinstance(base, int) and not isinstance(base, bool) and 0 <= base <= 2**63 - 1 else -1,
                            result_revision=result.get("revision"),
                            status=result["status"], result_json=result))
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise


def get_changes(db: Session, workspace_id: str, cursor: int, limit: int) -> dict:
    state = db.get(SyncWorkspaceState, workspace_id)
    workspace_revision = state.current_revision if state is not None else 0
    if cursor > workspace_revision:
        from fastapi import HTTPException
        raise HTTPException(400, "Invalid sync cursor")
    rows = db.scalars(select(SyncChange).where(
        SyncChange.workspace_id == workspace_id, SyncChange.revision > cursor)
        .order_by(SyncChange.revision).limit(limit + 1)).all()
    changes = [{"revision": row.revision, "entityType": row.entity_type,
                "entityId": row.entity_id, "operation": row.operation, "data": row.payload_json}
               for row in rows[:limit]]
    return {"protocolVersion": 1, "changes": changes,
            "cursor": changes[-1]["revision"] if changes else cursor,
            "hasMore": len(rows) > limit, "workspaceRevision": workspace_revision}
