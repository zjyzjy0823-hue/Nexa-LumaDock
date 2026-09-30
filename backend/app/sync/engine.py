"""One manual Local sync cycle; every network call is outside a SQLite transaction."""

from contextlib import nullcontext
from threading import Lock

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select

from ..models import (LocalMutation,
                      LocalSyncState, utcnow)
from .adapters import get_adapter
from .local import (bind_local_sync_state, get_local_sync_state,
                    ordered_pending_mutations, seed_local_queue)
from .protocol import SYNC_PROTOCOL_VERSION
from .remote import SyncRemoteClient, SyncRemoteError


_locks_guard = Lock()
_workspace_locks: dict[tuple[str, str], Lock] = {}


def _lock_for(database: str, workspace_id: str) -> Lock:
    key = (database, workspace_id)
    with _locks_guard:
        return _workspace_locks.setdefault(key, Lock())


def _entries(db, workspace_id: str, entity_type: str, entity_id: str) -> list[LocalMutation]:
    return db.scalars(select(LocalMutation).where(
        LocalMutation.workspace_id == workspace_id,
        LocalMutation.entity_type == entity_type,
        LocalMutation.entity_id == entity_id)).all()


def _outbound(entry: LocalMutation) -> dict:
    return {"mutationId": entry.mutation_id, "entityType": entry.entity_type,
            "entityId": entry.entity_id, "operation": entry.operation,
            "baseRevision": entry.base_revision, "data": entry.payload_json}


def _freeze(factory, workspace_id: str, mutation_id: str) -> dict:
    with factory() as db:
        entry = db.scalar(select(LocalMutation).where(
            LocalMutation.workspace_id == workspace_id,
            LocalMutation.mutation_id == mutation_id))
        if entry is None or entry.status not in ("pending", "in_flight"):
            raise SyncRemoteError("invalid_local_state")
        if entry.status == "pending" and entry.depends_on_mutation_id is not None:
            raise SyncRemoteError("invalid_local_state")
        entry.status = "in_flight"
        entry.attempt_count += 1
        entry.updated_at = utcnow()
        payload = _outbound(entry)
        db.commit()  # Durable freeze before the request can reach Core.
        return payload


def _acknowledge(factory, workspace_id: str, mutation_id: str, result: dict) -> str:
    status = result.get("status")
    if status not in ("applied", "conflict", "rejected"):
        raise SyncRemoteError("invalid_response")
    with factory() as db:
        entry = db.scalar(select(LocalMutation).where(
            LocalMutation.workspace_id == workspace_id,
            LocalMutation.mutation_id == mutation_id))
        if entry is None or entry.status != "in_flight":
            raise SyncRemoteError("invalid_local_state")
        if status == "applied":
            revision = result.get("revision")
            if type(revision) is not int or revision <= entry.base_revision:
                raise SyncRemoteError("invalid_response")
            adapter = get_adapter(entry.entity_type)
            model = adapter.model
            item = db.get(model, entry.entity_id)
            if item is None or adapter.workspace_id(db, item) != workspace_id:
                raise SyncRemoteError("invalid_local_state")
            item.sync_revision = revision
            tails = [value for value in _entries(db, workspace_id, entry.entity_type, entry.entity_id)
                     if value.depends_on_mutation_id == mutation_id]
            if len(tails) > 1:
                raise SyncRemoteError("invalid_local_state")
            for tail in tails:
                tail.base_revision = revision
                tail.depends_on_mutation_id = None
                tail.updated_at = utcnow()
            db.delete(entry)
        elif status == "conflict":
            revision = result.get("currentRevision")
            if type(revision) is not int or revision < 0 or type(result.get("deleted")) is not bool:
                raise SyncRemoteError("invalid_response")
            _validate_snapshot(get_adapter(entry.entity_type), result.get("current"), result["deleted"])
            entry.status = "conflict"
            entry.conflict_json = {"currentRevision": revision, "current": result.get("current"),
                                   "deleted": result["deleted"]}
            entry.result_revision = revision
            entry.last_error = None
        else:
            reason = result.get("reason")
            if not isinstance(reason, str) or reason not in REJECTION_REASONS:
                raise SyncRemoteError("invalid_response")
            entry.status = "rejected"
            entry.last_error = reason
        db.commit()
    return status


REJECTION_REASONS = frozenset({"invalid_id", "invalid_fields", "unknown_entity_type",
    "invalid_operation", "invalid_base_revision", "invalid_data", "entity_id_unavailable",
    "category_not_found", "category_type_mismatch", "category_has_transactions",
    "collection_not_found", "collection_id_immutable"})


def _validate_snapshot(adapter, payload, deleted):
    if payload is None:
        # A conflict may represent an entity that has never existed on Core.
        return
    if deleted:
        raise SyncRemoteError("invalid_response")
    try:
        adapter.schema.model_validate(payload)
    except ValidationError:
        raise SyncRemoteError("invalid_response") from None


def _send(factory, workspace_id: str, remote, mutation_id: str) -> str:
    request = _freeze(factory, workspace_id, mutation_id)
    # A transport failure leaves the exact frozen request in SQLite for replay.
    try:
        result = remote.push_mutation(request)
        if not isinstance(result, dict) or result.get("mutationId") != mutation_id:
            raise SyncRemoteError("invalid_response")
        return _acknowledge(factory, workspace_id, mutation_id, result)
    except SyncRemoteError as error:
        with factory() as db:
            entry = db.scalar(select(LocalMutation).where(
                LocalMutation.workspace_id == workspace_id,
                LocalMutation.mutation_id == mutation_id))
            if entry is not None and entry.status == "in_flight":
                entry.last_error = error.code
                db.commit()
        raise


def _apply_change(factory, user_id: int, workspace_id: str, change: dict) -> None:
    if not isinstance(change, dict):
        raise SyncRemoteError("invalid_response")
    entity_type, entity_id = change.get("entityType"), change.get("entityId")
    operation, revision = change.get("operation"), change.get("revision")
    adapter = get_adapter(entity_type)
    if (not isinstance(entity_id, str) or
            operation not in ("upsert", "delete") or type(revision) is not int or revision <= 0):
        raise SyncRemoteError("invalid_response")
    if operation == "upsert" and change.get("data") is None:
        raise SyncRemoteError("invalid_response")
    _validate_snapshot(adapter, change.get("data"), operation == "delete")
    with factory() as db:
        state = get_local_sync_state(db, workspace_id)
        if revision != state.cursor + 1:
            raise SyncRemoteError("invalid_response")
        adapter = get_adapter(entity_type)
        model, schema = adapter.model, adapter.schema
        item = db.get(model, entity_id)
        if item is not None and adapter.workspace_id(db, item) != workspace_id:
            raise SyncRemoteError("ownership_conflict")
        if item is not None and revision <= item.sync_revision:
            # Core echoes our own acknowledged mutation. The local pending tail wins.
            state.cursor = revision
            db.commit()
            return
        entries = _entries(db, workspace_id, entity_type, entity_id)
        if entries:
            conflict = {"currentRevision": revision,
                        "current": change.get("data") if operation == "upsert" else None,
                        "deleted": operation == "delete"}
            for entry in entries:
                if entry.status == "pending" and entry.depends_on_mutation_id is not None:
                    # The predecessor owns the unresolved conflict. Keep its
                    # editable tail blocked and avoid a second frozen row.
                    continue
                if entry.status == "conflict" and revision <= max(
                        entry.result_revision or 0,
                        (entry.conflict_json or {}).get("currentRevision", 0)):
                    # A push response can already know a revision beyond the
                    # pull cursor. Older history must not regress that snapshot.
                    continue
                if entry.status == "conflict" or (
                        entry.status in ("pending", "in_flight") and entry.base_revision < revision):
                    # Keep the conflict owner's remote snapshot current without
                    # changing the local edit, its base, or its blocked tail.
                    entry.status = "conflict"
                    entry.conflict_json = conflict
                    entry.result_revision = revision
            state.cursor = revision
            db.commit()
            return
        if operation == "upsert":
            try:
                data = schema.model_validate(change.get("data"))
            except ValidationError:
                raise SyncRemoteError("invalid_response") from None
            reason = adapter.remote_dependency_error(db, workspace_id, data, item)
            if reason:
                raise SyncRemoteError("missing_category" if reason == "category_not_found" else reason)
            if item is None:
                item = adapter.create(db, entity_id, user_id, workspace_id, data)
                db.add(item)
            adapter.apply_data(item, data)
            item.deleted_at = None
        elif item is None:
            raise SyncRemoteError("invalid_local_state")
        else:
            item.deleted_at = utcnow()
        item.sync_revision = revision
        state.cursor = revision
        db.commit()  # Entity, conflict state and cursor have one crash boundary.


def _pull(factory, remote, user_id: int, workspace_id: str) -> tuple[int, int]:
    pulled = 0
    while True:
        with factory() as db:
            cursor = get_local_sync_state(db, workspace_id).cursor
        page = remote.get_changes(cursor, 100)
        if page.get("protocolVersion") != SYNC_PROTOCOL_VERSION:
            raise SyncRemoteError("protocol_mismatch")
        changes = page.get("changes")
        if not isinstance(changes, list) or len(changes) > 100:
            raise SyncRemoteError("invalid_response")
        for change in changes:
            _apply_change(factory, user_id, workspace_id, change)
            pulled += 1
        next_cursor = changes[-1]["revision"] if changes else cursor
        if page.get("cursor") != next_cursor or page["workspaceRevision"] < next_cursor:
            raise SyncRemoteError("invalid_response")
        if not page["hasMore"]:
            return pulled, page["workspaceRevision"]
        if not changes:
            raise SyncRemoteError("invalid_response")


def _ready_pending(db, workspace_id: str) -> list[LocalMutation]:
    entries = ordered_pending_mutations(db, workspace_id)
    ready = []
    for entry in entries:
        if get_adapter(entry.entity_type).push_ready(db, workspace_id, entry):
            ready.append(entry)
    return ready


def _repair_acknowledged_tails(factory, workspace_id: str) -> None:
    """Rebase a tail inserted during the small race after predecessor ack."""
    with factory() as db:
        tails = db.scalars(select(LocalMutation).where(
            LocalMutation.workspace_id == workspace_id,
            LocalMutation.status == "pending",
            LocalMutation.depends_on_mutation_id.is_not(None))).all()
        for tail in tails:
            predecessor = db.scalar(select(LocalMutation.id).where(
                LocalMutation.mutation_id == tail.depends_on_mutation_id))
            if predecessor is not None:
                continue
            adapter = get_adapter(tail.entity_type)
            item = db.get(adapter.model, tail.entity_id)
            if item is None or adapter.workspace_id(db, item) != workspace_id or item.sync_revision <= tail.base_revision:
                raise SyncRemoteError("invalid_local_state")
            tail.base_revision = item.sync_revision
            tail.depends_on_mutation_id = None
            tail.updated_at = utcnow()
        db.commit()


def _counts(factory, workspace_id: str) -> dict:
    with factory() as db:
        state = get_local_sync_state(db, workspace_id)
        counts = dict(db.execute(select(LocalMutation.status, func.count()).where(
            LocalMutation.workspace_id == workspace_id).group_by(LocalMutation.status)).all())
        return {"pending": counts.get("pending", 0), "inFlight": counts.get("in_flight", 0),
                "conflicts": counts.get("conflict", 0), "rejected": counts.get("rejected", 0),
                "cursor": state.cursor, "lastError": state.last_error}


def run_sync_cycle(factory, user_id: int, workspace_id: str, metadata, credential: str,
                   remote=None) -> dict:
    """Synchronize one Local Personal Workspace. A caller may inject a test transport."""
    with factory() as db:
        database_key = str(db.get_bind().url)
    lock = _lock_for(database_key, workspace_id)
    if not lock.acquire(blocking=False):
        raise HTTPException(409, "Sync is already running for this workspace")
    pushed = pulled = 0
    workspace_revision = None
    try:
        with factory() as db:
            bind_local_sync_state(db, workspace_id, metadata)
            seed_local_queue(db, workspace_id)
            db.commit()
        context = nullcontext(remote) if remote is not None else SyncRemoteClient(metadata.coreUrl, credential)
        with context as transport:
            with factory() as db:
                cursor = get_local_sync_state(db, workspace_id).cursor
            if transport.get_changes(cursor, 1).get("protocolVersion") != SYNC_PROTOCOL_VERSION:
                raise SyncRemoteError("protocol_mismatch")
            with factory() as db:
                inflight = db.scalars(select(LocalMutation).where(
                    LocalMutation.workspace_id == workspace_id,
                    LocalMutation.status == "in_flight")).all()
                inflight_ids = [entry.mutation_id for entry in sorted(inflight, key=lambda entry: (
                    get_adapter(entry.entity_type).push_priority(entry.operation), entry.created_at, entry.id))]
            for mutation_id in inflight_ids:
                outcome = _send(factory, workspace_id, transport, mutation_id)
                pushed += outcome == "applied"
            count, workspace_revision = _pull(factory, transport, user_id, workspace_id)
            pulled += count
            # Re-evaluate after each acknowledgement so category dependencies and
            # pending tails can become eligible within this same cycle.
            while True:
                _repair_acknowledged_tails(factory, workspace_id)
                with factory() as db:
                    ready = _ready_pending(db, workspace_id)
                    mutation_id = ready[0].mutation_id if ready else None
                if mutation_id is None:
                    break
                outcome = _send(factory, workspace_id, transport, mutation_id)
                pushed += outcome == "applied"
            count, workspace_revision = _pull(factory, transport, user_id, workspace_id)
            pulled += count
        with factory() as db:
            state = get_local_sync_state(db, workspace_id)
            state.last_success_at = utcnow()
            state.last_error = None
            db.commit()
        return {"status": "ok", "pushed": pushed, "pulled": pulled,
                **_counts(factory, workspace_id), "workspaceRevision": workspace_revision}
    except SyncRemoteError as error:
        with factory() as db:
            state = get_local_sync_state(db, workspace_id)
            state.last_error = error.code
            db.commit()
        return {"status": "error", "pushed": pushed, "pulled": pulled,
                **_counts(factory, workspace_id), "workspaceRevision": workspace_revision}
    finally:
        lock.release()
