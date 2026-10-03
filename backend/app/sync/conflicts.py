"""Explicit Local conflict decisions, with durable metadata-only replay receipts."""

from uuid import UUID, uuid4
from datetime import datetime

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


def _timestamp(value):
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError()
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError()
    return parsed


def _uuid(value):
    try:
        return isinstance(value, str) and str(UUID(value)) == value
    except (ValueError, TypeError, AttributeError):
        return False


def _receipt(entry, strategy):
    receipt = entry.conflict_json
    keys = {"id", "strategy", "status", "remoteRevision", "mutationId", "resolvedAt"}
    if (not isinstance(receipt, dict) or set(receipt) != keys or
            receipt.get("status") != "resolved" or receipt.get("id") != entry.id or
            not _uuid(receipt.get("id")) or receipt.get("strategy") not in ("local", "remote") or
            type(receipt.get("remoteRevision")) is not int or
            not 0 <= receipt["remoteRevision"] <= 2**63 - 1 or
            receipt["remoteRevision"] != entry.result_revision or
            (receipt.get("mutationId") is not None and not _uuid(receipt["mutationId"])) or
            (receipt["strategy"] == "remote" and receipt["mutationId"] is not None)):
        raise HTTPException(409, "invalid_resolution_receipt")
    try:
        _timestamp(receipt["resolvedAt"])
    except (ValueError, TypeError):
        raise HTTPException(409, "invalid_resolution_receipt") from None
    if receipt["strategy"] != strategy:
        raise HTTPException(409, "conflict_already_resolved")
    return receipt


def _adapter(entity_type):
    try:
        return get_adapter(entity_type)
    except SyncRemoteError:
        raise HTTPException(409, "unknown_entity_type") from None


def _snapshot(entry, adapter):
    snapshot = entry.conflict_json
    required = {"currentRevision", "current", "deleted"}
    if (not isinstance(snapshot, dict) or not required <= set(snapshot) or
            set(snapshot) - required - {"detectedAt"}):
        raise HTTPException(409, "invalid_conflict_snapshot")
    if "detectedAt" in snapshot:
        try:
            _timestamp(snapshot["detectedAt"])
        except (ValueError, TypeError):
            raise HTTPException(409, "invalid_conflict_snapshot") from None
    revision, payload, deleted = (snapshot["currentRevision"], snapshot["current"], snapshot["deleted"])
    if (type(revision) is not int or not 0 <= revision <= 2**63 - 1 or
            type(deleted) is not bool or
            (entry.result_revision is not None and entry.result_revision != revision) or
            (deleted and (payload is not None or revision == 0)) or
            (payload is None and not deleted and revision != 0) or
            (payload is not None and revision == 0)):
        raise HTTPException(409, "invalid_conflict_snapshot")
    if payload is not None:
        try:
            adapter.schema.model_validate(payload)
        except (ValidationError, ValueError, TypeError):
            raise HTTPException(409, "invalid_conflict_snapshot") from None
    return revision, payload, deleted


def _item(db, workspace_id, entry, adapter):
    item = db.get(adapter.model, entry.entity_id, populate_existing=True)
    if item is None or adapter.workspace_id(db, item) != workspace_id:
        raise HTTPException(409, "invalid_local_state")
    return item


def _entry(db, workspace_id, conflict_id):
    entry = db.scalar(select(LocalMutation).where(
        LocalMutation.workspace_id == workspace_id, LocalMutation.id == conflict_id)
        .execution_options(populate_existing=True))
    if entry is None or entry.status not in ("conflict", "resolved"):
        raise HTTPException(404, "conflict_not_found")
    return entry


def _presentation(db, workspace_id, entry):
    adapter = _adapter(entry.entity_type)
    revision, remote, deleted = _snapshot(entry, adapter)
    item = _item(db, workspace_id, entry, adapter)
    try:
        local = None if item.deleted_at is not None else adapter.serialize(item)
        if local is not None:
            adapter.schema.model_validate(local)
    except (ValidationError, ValueError, TypeError):
        raise HTTPException(409, "invalid_local_state") from None
    tail = db.scalar(select(LocalMutation.id).where(
        LocalMutation.workspace_id == workspace_id,
        LocalMutation.entity_type == entry.entity_type, LocalMutation.entity_id == entry.entity_id,
        LocalMutation.status == "pending"))
    return {"id": entry.id, "entityType": entry.entity_type, "entityId": entry.entity_id,
            "local": local, "localDeleted": item.deleted_at is not None,
            "remote": remote, "remoteRevision": revision, "remoteDeleted": deleted,
            "createdAt": iso_utc(entry.created_at),
            "detectedAt": entry.conflict_json.get("detectedAt") or iso_utc(entry.updated_at),
            "updatedAt": iso_utc(getattr(item, "updated_at", item.created_at)),
            "hasPendingTail": tail is not None}


def list_conflicts(db, workspace_id):
    entries = db.scalars(select(LocalMutation).where(
        LocalMutation.workspace_id == workspace_id, LocalMutation.status == "conflict")
        .order_by(LocalMutation.updated_at.desc(), LocalMutation.id)).all()
    return {"conflicts": [_presentation(db, workspace_id, entry) for entry in entries]}


def get_conflict(db, workspace_id, conflict_id):
    entry = _entry(db, workspace_id, conflict_id)
    if entry.status != "conflict":
        raise HTTPException(404, "conflict_not_found")
    return _presentation(db, workspace_id, entry)


def resolve_conflict(db, user_id, workspace_id, conflict_id, strategy, expected_revision=None):
    if strategy not in ("local", "remote"):
        raise HTTPException(422, "invalid_resolution_strategy")
    lock = _lock_for(str(db.get_bind().url), workspace_id)
    if not lock.acquire(blocking=False):
        raise HTTPException(409, "sync_in_progress")
    try:
        # The first DML serializes SQLite business writers before we inspect the
        # latest row. It also locks the receipt for simultaneous retries on PG.
        db.execute(update(LocalMutation).where(LocalMutation.workspace_id == workspace_id,
            LocalMutation.id == conflict_id).values(updated_at=LocalMutation.updated_at)
            .execution_options(synchronize_session=False))
        db.expire_all()  # Refresh cached parent rows after acquiring the writer lock.
        entry = _entry(db, workspace_id, conflict_id)
        if entry.status == "resolved":
            receipt = _receipt(entry, strategy)
            db.commit()
            return receipt
        adapter = _adapter(entry.entity_type)
        revision, remote, deleted = _snapshot(entry, adapter)
        if expected_revision is not None and expected_revision != revision:
            raise HTTPException(409, "conflict_snapshot_changed")
        item = _item(db, workspace_id, entry, adapter)
        pending = None
        if strategy == "remote":
            if remote is not None:
                data = adapter.schema.model_validate(remote)
                reason = adapter.remote_dependency_error(db, workspace_id, data, item)
                if reason:
                    raise HTTPException(409, reason)
                adapter.apply_data(item, data)
                item.deleted_at = None
            else:
                # revision zero/absent and authoritative tombstones both mean
                # this entity must disappear from ordinary Local business APIs.
                item.deleted_at = utcnow()
            item.sync_revision = revision
        else:
            local_deleted = item.deleted_at is not None
            payload = None if local_deleted else adapter.serialize(item)
            if payload is not None:
                try:
                    data = adapter.schema.model_validate(payload)
                except (ValidationError, ValueError, TypeError):
                    raise HTTPException(409, "invalid_local_state") from None
                reason = adapter.dependency_error(db, workspace_id, data, item)
                if reason:
                    raise HTTPException(409, reason)
            # Keeping a deletion when Core has never seen the row needs no push.
            if not (local_deleted and revision == 0):
                pending = LocalMutation(id=str(uuid4()), mutation_id=str(uuid4()),
                    workspace_id=workspace_id, entity_type=entry.entity_type,
                    entity_id=entry.entity_id, operation="delete" if local_deleted else "upsert",
                    base_revision=revision, payload_json=payload, status="pending", attempt_count=0)
        # Remove the whole live tail atomically. The receipt no longer belongs to
        # the outbox, and cannot become a predecessor for subsequent local edits.
        tails = db.scalars(select(LocalMutation).where(
            LocalMutation.workspace_id == workspace_id, LocalMutation.entity_type == entry.entity_type,
            LocalMutation.entity_id == entry.entity_id, LocalMutation.id != entry.id,
            LocalMutation.status.in_(LIVE_STATUSES))).all()
        for tail in tails:
            db.delete(tail)
        receipt = {"id": entry.id, "strategy": strategy, "status": "resolved",
                   "remoteRevision": revision, "mutationId": pending.mutation_id if pending else None,
                   "resolvedAt": iso_utc(utcnow())}
        entry.status = "resolved"
        entry.result_revision = revision
        entry.payload_json = None
        entry.conflict_json = receipt
        entry.depends_on_mutation_id = None
        entry.last_error = None
        entry.updated_at = utcnow()
        db.flush()  # Release partial unique indexes before inserting the new row.
        if pending is not None:
            db.add(pending)
            request_after_commit(db, workspace_id)
        db.commit()
        return receipt
    except OperationalError:
        db.rollback()
        raise HTTPException(409, "conflict_busy") from None
    except Exception:
        db.rollback()
        raise
    finally:
        lock.release()
