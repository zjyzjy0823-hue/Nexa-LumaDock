"""Explicit exits for rejected Local mutations.

A rejected push used to be terminal: the row kept status ``rejected``, the frozen
unique index blocked any new mutation for the same entity and dependent tails
waited forever. These two decisions give the user a way out:

* ``dismiss`` — give up on the write; dependent tails are marked ``skipped`` so
  they stop waiting.
* ``retry`` — rebuild one pending mutation from the *current* business row (so
  the user's fix is included) with a fresh ``mutation_id``; dependent tails are
  repointed to the new mutation.

Both are Local-only user actions, executed under the workspace lock with the same
bounded wait as conflict resolution.
"""

from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.exc import OperationalError

from ..models import LocalMutation, utcnow
from ..utils.time import iso_utc
from .adapters import get_adapter
from .engine import _lock_for
from .notifications import request_after_commit
from .remote import SyncRemoteError

LIVE_STATUSES = ("pending", "in_flight", "conflict", "rejected")
LOCK_TIMEOUT_SECONDS = 10.0
DECISIONS = ("dismiss", "retry")


def _entry(db, workspace_id, entry_id):
    entry = db.scalar(select(LocalMutation).where(
        LocalMutation.workspace_id == workspace_id, LocalMutation.id == entry_id))
    if entry is None:
        raise HTTPException(404, "rejected_not_found")
    return entry


def _replay(entry, decision):
    receipt = entry.conflict_json
    if (isinstance(receipt, dict) and receipt.get("status") == "resolved"
            and receipt.get("decision") == decision and receipt.get("id") == entry.id):
        return receipt
    raise HTTPException(409, "rejected_already_resolved")


def _locked(db, workspace_id):
    lock = _lock_for(str(db.get_bind().url), workspace_id)
    if not lock.acquire(timeout=LOCK_TIMEOUT_SECONDS):
        raise HTTPException(409, "sync_in_progress")
    return lock


def _tails(db, workspace_id, entry):
    return db.scalars(select(LocalMutation).where(
        LocalMutation.workspace_id == workspace_id,
        LocalMutation.entity_type == entry.entity_type,
        LocalMutation.entity_id == entry.entity_id,
        LocalMutation.id != entry.id,
        LocalMutation.status.in_(LIVE_STATUSES))).all()


def _receipt(entry, decision, mutation_id):
    return {"id": entry.id, "decision": decision, "status": "resolved",
            "mutationId": mutation_id, "resolvedAt": iso_utc(utcnow())}


def dismiss_rejected(db, workspace_id, entry_id):
    lock = _locked(db, workspace_id)
    try:
        # Serialize SQLite writers and lock the receipt row on PostgreSQL.
        db.execute(update(LocalMutation).where(
            LocalMutation.workspace_id == workspace_id, LocalMutation.id == entry_id)
            .values(updated_at=LocalMutation.updated_at)
            .execution_options(synchronize_session=False))
        db.expire_all()
        entry = _entry(db, workspace_id, entry_id)
        if entry.status == "resolved":
            receipt = _replay(entry, "dismiss")
            db.commit()
            return receipt
        if entry.status != "rejected":
            raise HTTPException(404, "rejected_not_found")
        for tail in _tails(db, workspace_id, entry):
            tail.status = "skipped"
            tail.depends_on_mutation_id = None
            tail.payload_json = None
            tail.updated_at = utcnow()
        receipt = _receipt(entry, "dismiss", None)
        entry.status = "resolved"
        entry.payload_json = None
        entry.depends_on_mutation_id = None
        entry.conflict_json = receipt
        entry.updated_at = utcnow()
        db.commit()
        return receipt
    except OperationalError:
        db.rollback()
        raise HTTPException(409, "rejected_busy") from None
    except Exception:
        db.rollback()
        raise
    finally:
        lock.release()


def retry_rejected(db, workspace_id, entry_id):
    lock = _locked(db, workspace_id)
    try:
        db.execute(update(LocalMutation).where(
            LocalMutation.workspace_id == workspace_id, LocalMutation.id == entry_id)
            .values(updated_at=LocalMutation.updated_at)
            .execution_options(synchronize_session=False))
        db.expire_all()
        entry = _entry(db, workspace_id, entry_id)
        if entry.status == "resolved":
            receipt = _replay(entry, "retry")
            db.commit()
            return receipt
        if entry.status != "rejected":
            raise HTTPException(404, "rejected_not_found")
        try:
            adapter = get_adapter(entry.entity_type)
        except SyncRemoteError:
            raise HTTPException(409, "unknown_entity_type") from None
        item = adapter.find(db, entry.entity_id, workspace_id)
        if item is None or adapter.workspace_id(db, item) != workspace_id:
            raise HTTPException(409, "invalid_local_state")
        deleted = item.deleted_at is not None
        payload = None if deleted else adapter.serialize(item)
        if payload is not None:
            try:
                data = adapter.schema.model_validate(payload)
            except (ValidationError, ValueError, TypeError):
                raise HTTPException(409, "invalid_local_state") from None
            reason = adapter.dependency_error(db, workspace_id, data, item)
            if reason:
                raise HTTPException(409, reason)
        tails = _tails(db, workspace_id, entry)
        # A local edit made while the entry was rejected already queued one pending
        # row for this entity. Reuse it (it carries the user's fix) instead of
        # inserting a second pending row, which the unique index forbids.
        pending = next((tail for tail in tails if tail.status == "pending"), None)
        for tail in tails:
            if tail is not pending:
                tail.depends_on_mutation_id = None
                tail.updated_at = utcnow()
        if pending is None:
            pending = LocalMutation(
                id=str(uuid4()), mutation_id=str(uuid4()), workspace_id=workspace_id,
                entity_type=entry.entity_type, entity_id=entry.entity_id,
                operation="delete" if deleted else "upsert",
                base_revision=item.sync_revision or 0, payload_json=payload,
                status="pending", attempt_count=0, depends_on_mutation_id=None)
        else:
            pending.operation = "delete" if deleted else "upsert"
            pending.base_revision = item.sync_revision or 0
            pending.payload_json = payload
            pending.depends_on_mutation_id = None
            pending.attempt_count = 0
            pending.last_error = None
            pending.updated_at = utcnow()
        receipt = _receipt(entry, "retry", pending.mutation_id)
        entry.status = "resolved"
        entry.payload_json = None
        entry.conflict_json = receipt
        entry.updated_at = utcnow()
        db.flush()  # Release the partial unique indexes before inserting the new row.
        db.add(pending)
        request_after_commit(db, workspace_id)
        db.commit()
        return receipt
    except OperationalError:
        db.rollback()
        raise HTTPException(409, "rejected_busy") from None
    except Exception:
        db.rollback()
        raise
    finally:
        lock.release()

def list_rejected(db, workspace_id, limit=50):
    entries = db.scalars(select(LocalMutation).where(
        LocalMutation.workspace_id == workspace_id,
        LocalMutation.status == "rejected").order_by(LocalMutation.updated_at.desc()).limit(limit)).all()
    return [{"id": entry.id, "mutationId": entry.mutation_id,
             "entityType": entry.entity_type, "entityId": entry.entity_id,
             "operation": entry.operation, "baseRevision": entry.base_revision,
             "reason": entry.last_error, "attempts": entry.attempt_count,
             "payload": entry.payload_json,
             "updatedAt": iso_utc(entry.updated_at)} for entry in entries]
