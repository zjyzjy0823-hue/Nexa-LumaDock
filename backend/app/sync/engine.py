"""One shared Local sync cycle; every network call is outside a SQLite transaction."""

import logging
from contextlib import nullcontext
from threading import Lock

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select

from ..models import (LocalMutation, LocalAutomationEvent,
                      LocalSyncState, utcnow)
from ..utils.time import iso_utc
from .adapters import get_adapter
from .local import (bind_local_sync_state, get_local_sync_state,
                    ordered_pending_mutations, seed_local_queue)
from .protocol import SYNC_PROTOCOL_VERSION
from .remote import SyncRemoteClient, SyncRemoteError


logger = logging.getLogger(__name__)

_locks_guard = Lock()
_workspace_locks: dict[tuple[str, str], Lock] = {}

# A cursor beyond the Core revision is not corruption: Core lost the history this
# replica is based on (rebuild/restore) and only a snapshot can recover it.
RESYNC_REQUIRED = "resync_required"
# Snapshot recovery is a whole-workspace operation, so it waits for a running cycle
# exactly like a conflict decision does (see conflicts.RESOLVE_LOCK_TIMEOUT_SECONDS).
RESYNC_LOCK_TIMEOUT_SECONDS = 10.0
RESYNC_PAGE_LIMIT = 200
RESYNC_SNAPSHOT_RESTARTS = 2
# A snapshot may omit the parent of a child it still returns: the parent was written
# after the pinned revision and is filtered out. Storage-level foreign keys would
# reject such a child (PostgreSQL), so the child is deferred rather than applied.
# Deferring alone is not enough — the child's own change revision is <= R, so
# `/changes?cursor=R` will never replay it — therefore a round with skips is
# followed by one more snapshot round, which pins a newer revision that does
# include the parent.
RESYNC_SKIPPED = frozenset({"missing_category", "collection_not_found"})
RESYNC_SNAPSHOT_ROUNDS = 2


class SyncCycleCancelled(Exception):
    """Cooperative lifecycle stop, never a persisted synchronization error."""


def _check_cancelled(cancel_event) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise SyncCycleCancelled()


def _lock_for(database: str, workspace_id: str) -> Lock:
    key = (database, workspace_id)
    with _locks_guard:
        return _workspace_locks.setdefault(key, Lock())


def _entries(db, workspace_id: str, entity_type: str, entity_id: str) -> list[LocalMutation]:
    return db.scalars(select(LocalMutation).where(
        LocalMutation.workspace_id == workspace_id,
        LocalMutation.entity_type == entity_type,
        LocalMutation.entity_id == entity_id,
        LocalMutation.status != "resolved")).all()


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
            item = adapter.find(db, entry.entity_id, workspace_id)
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
                                   "deleted": result["deleted"], "detectedAt": iso_utc(utcnow())}
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
    "collection_not_found", "collection_id_immutable", "delete_unsupported"})


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


def _send(factory, workspace_id: str, remote, mutation_id: str, cancel_event=None) -> str:
    _check_cancelled(cancel_event)
    request = _freeze(factory, workspace_id, mutation_id)
    # A transport failure leaves the exact frozen request in SQLite for replay.
    try:
        _check_cancelled(cancel_event)
        result = remote.push_mutation(request)
        if not isinstance(result, dict) or result.get("mutationId") != mutation_id:
            raise SyncRemoteError("invalid_response")
        return _acknowledge(factory, workspace_id, mutation_id, result)
    except SyncRemoteError as error:
        _check_cancelled(cancel_event)
        with factory() as db:
            entry = db.scalar(select(LocalMutation).where(
                LocalMutation.workspace_id == workspace_id,
                LocalMutation.mutation_id == mutation_id))
            if entry is not None and entry.status == "in_flight":
                entry.last_error = error.code
                db.commit()
        raise


def _apply_entity(db, user_id: int, workspace_id: str, entity_type: str, entity_id: str,
                  operation: str, revision: int, data, *, from_snapshot: bool = False) -> str:
    """Apply one remote entity state at ``revision``; the caller owns the transaction.

    Shared by the `/changes` replay (`_apply_change`) and snapshot recovery
    (`_apply_snapshot`) so both keep the same ownership and pending-edit protection.
    Only a snapshot may replace a newer local revision after Core restores a backup.
    It never touches the cursor: each caller decides what advancing it means.

    Returns ``applied``, ``deleted``, ``conflict``, ``echo`` (Core echoed a revision
    this replica already holds, so the local pending tail wins) or ``absent`` (a
    tombstone for an entity this replica never had).
    """
    adapter = get_adapter(entity_type)
    schema = adapter.schema
    item = adapter.find(db, entity_id, workspace_id)
    if item is not None and adapter.workspace_id(db, item) != workspace_id:
        raise SyncRemoteError("ownership_conflict")
    if item is not None and revision <= item.sync_revision and not from_snapshot:
        return "echo"
    entries = _entries(db, workspace_id, entity_type, entity_id)
    if from_snapshot and item is not None and revision == item.sync_revision:
        # An acknowledged revision still protects its pending local tail. Without
        # local edits, skip only an identical snapshot, never different Core data.
        if entries or (operation == "delete" and item.deleted_at is not None) or (
                operation == "upsert" and item.deleted_at is None and adapter.serialize(item) == data):
            return "echo"
    if entries:
        conflict = {"currentRevision": revision,
                    "current": data if operation == "upsert" else None,
                    "deleted": operation == "delete"}
        for entry in entries:
            if entry.status == "pending" and entry.depends_on_mutation_id is not None:
                # The predecessor owns the unresolved conflict. Keep its
                # editable tail blocked and avoid a second frozen row.
                continue
            if not from_snapshot and entry.status == "conflict" and revision <= max(
                    entry.result_revision or 0,
                    (entry.conflict_json or {}).get("currentRevision", 0)):
                # A push response can already know a revision beyond the
                # pull cursor. Older history must not regress that snapshot.
                continue
            if entry.status == "conflict" or (
                    entry.status in ("pending", "in_flight") and (
                        entry.base_revision < revision or (from_snapshot and entry.base_revision != revision))):
                # Keep the conflict owner's remote snapshot current without
                # changing the local edit, its base, or its blocked tail.
                detected_at = (entry.conflict_json or {}).get("detectedAt") or (
                    iso_utc(entry.updated_at) if entry.status == "conflict" else iso_utc(utcnow()))
                entry.status = "conflict"
                entry.conflict_json = {**conflict, "detectedAt": detected_at}
                entry.result_revision = revision
        return "conflict"
    if operation == "upsert":
        try:
            payload = schema.model_validate(data)
        except ValidationError:
            raise SyncRemoteError("invalid_response") from None
        reason = adapter.remote_dependency_error(db, workspace_id, payload, item)
        if reason:
            raise SyncRemoteError("missing_category" if reason == "category_not_found" else reason)
        if item is None:
            item = adapter.create(db, entity_id, user_id, workspace_id, payload)
            db.add(item)
        adapter.apply_data(item, payload)
        item.deleted_at = None
        item.sync_revision = revision
        return "applied"
    if item is None:
        return "absent"
    item.deleted_at = utcnow()
    item.sync_revision = revision
    return "deleted"


def _apply_change(factory, user_id: int, workspace_id: str, change: dict) -> None:
    if not isinstance(change, dict):
        raise SyncRemoteError("invalid_response")
    entity_type, entity_id = change.get("entityType"), change.get("entityId")
    operation, revision = change.get("operation"), change.get("revision")
    adapter = get_adapter(entity_type)
    if not isinstance(entity_type, str):
        raise SyncRemoteError("unknown_entity_type")
    if adapter.identity_error(entity_id, operation):
        raise SyncRemoteError("invalid_response")
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
        if _apply_entity(db, user_id, workspace_id, entity_type, entity_id,
                         operation, revision, change.get("data")) == "absent":
            raise SyncRemoteError("invalid_local_state")
        state.cursor = revision
        db.commit()  # Entity, conflict state and cursor have one crash boundary.


def _pull(factory, remote, user_id: int, workspace_id: str, cancel_event=None) -> tuple[int, int]:
    pulled = 0
    while True:
        _check_cancelled(cancel_event)
        with factory() as db:
            cursor = get_local_sync_state(db, workspace_id).cursor
        _check_cancelled(cancel_event)
        page = remote.get_changes(cursor, 100)
        _check_cancelled(cancel_event)
        if page.get("protocolVersion") != SYNC_PROTOCOL_VERSION:
            raise SyncRemoteError("protocol_mismatch")
        changes = page.get("changes")
        if not isinstance(changes, list) or len(changes) > 100:
            raise SyncRemoteError("invalid_response")
        for change in changes:
            _check_cancelled(cancel_event)
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
                LocalMutation.mutation_id == tail.depends_on_mutation_id,
                LocalMutation.status != "resolved"))
            if predecessor is not None:
                continue
            adapter = get_adapter(tail.entity_type)
            item = adapter.find(db, tail.entity_id, workspace_id)
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


def _entity_depth(entity_type: str) -> int:
    """Parent-before-child application order, derived from the adapter graph."""
    depth, seen = 0, {entity_type}
    adapter = get_adapter(entity_type)
    while adapter.parent_type is not None and adapter.parent_type not in seen:
        seen.add(adapter.parent_type)
        adapter = get_adapter(adapter.parent_type)
        depth += 1
    return depth


def _snapshot_row(row, revision: int) -> tuple:
    """Validate one snapshot entity and normalize it to an application instruction."""
    if not isinstance(row, dict):
        raise SyncRemoteError("invalid_response")
    entity_type, entity_id = row.get("entityType"), row.get("entityId")
    deleted, entity_revision = row.get("deleted"), row.get("syncRevision")
    adapter = get_adapter(entity_type)
    operation = "delete" if deleted is True else "upsert"
    if (type(deleted) is not bool or adapter.identity_error(entity_id, operation) or
            not isinstance(entity_id, str) or type(entity_revision) is not int or
            not 0 <= entity_revision <= revision):
        raise SyncRemoteError("invalid_response")
    _validate_snapshot(adapter, row.get("data"), deleted)
    if not deleted and row.get("data") is None:
        raise SyncRemoteError("invalid_response")
    return entity_type, entity_id, operation, entity_revision, row.get("data")


def _fetch_snapshot(remote, page_limit: int) -> tuple[int, list]:
    """Every entity of one pinned snapshot, pages followed to exhaustion.

    ``snapshot_expired`` cannot be resumed: contract §11.4 says to drop the paging
    state and issue a fresh first request (which pins a new revision). Restarts are
    bounded so a Core that keeps expiring snapshots cannot spin here forever.
    """
    for _attempt in range(RESYNC_SNAPSHOT_RESTARTS + 1):
        revision, snapshot_id, cursor, rows = None, None, None, []
        try:
            while True:
                page = remote.get_snapshot(snapshot_id=snapshot_id, cursor=cursor, limit=page_limit)
                if revision is None:
                    revision = page["workspaceRevision"]
                elif page["workspaceRevision"] != revision:
                    # Pages must all describe the revision the first one pinned;
                    # a moving revision would tear the recovered state.
                    raise SyncRemoteError("invalid_response")
                snapshot_id = page["snapshotId"]
                rows.extend(_snapshot_row(row, revision) for row in page["entities"])
                if not page["hasMore"]:
                    return revision, rows
                cursor = page["cursor"]
        except SyncRemoteError as error:
            if error.code != "snapshot_expired":
                raise
    raise SyncRemoteError("snapshot_expired")


def _apply_snapshot(factory, user_id: int, workspace_id: str, revision: int, rows) -> tuple:
    """Apply a whole snapshot and advance the cursor to its revision, atomically.

    One transaction for the batch: a crash can only redo the recovery, never leave
    the cursor ahead of applied state. Nothing is deleted for being *absent* from
    the snapshot (contract §11.3.1) — only explicit tombstones are applied.
    """
    applied = deleted = conflicts = skipped = 0
    # `(entityType, entityId)` puts `website` before `website.category` and
    # `data.record` before `data.collection`, so parents are applied first.
    order = sorted(rows, key=lambda row: (row[2] == "delete", _entity_depth(row[0]), row[0], row[1]))
    with factory() as db:
        state = get_local_sync_state(db, workspace_id)
        for entity_type, entity_id, operation, entity_revision, data in order:
            try:
                outcome = _apply_entity(db, user_id, workspace_id, entity_type, entity_id,
                                        operation, entity_revision, data, from_snapshot=True)
            except SyncRemoteError as error:
                if error.code not in RESYNC_SKIPPED:
                    raise
                logger.info("Resync deferred %s %s: %s", entity_type, entity_id, error.code)
                skipped += 1
                continue
            # Sessions run with autoflush disabled, so a parent applied earlier in
            # this same transaction is only visible to the children's `db.get`
            # after a flush — which keeps the whole batch in one transaction.
            db.flush()
            applied += outcome == "applied"
            deleted += outcome == "deleted"
            conflicts += outcome == "conflict"
        state.cursor = revision
        state.last_error = None
        db.commit()
    return applied, deleted, conflicts, skipped


def run_resync(factory, user_id: int, workspace_id: str, metadata=None, credential=None,
               remote=None, *, page_limit: int | None = None) -> dict:
    """Rebuild this Local replica from a Core snapshot (protocol v3 §11).

    Holds the workspace lock for the whole recovery, so a background cycle can never
    interleave with it. Local edits keep their payload and `base_revision`; divergent
    snapshot revisions turn them into conflicts instead of overwriting them.
    """
    page_limit = page_limit or RESYNC_PAGE_LIMIT
    with factory() as db:
        database_key = str(db.get_bind().url)
    lock = _lock_for(database_key, workspace_id)
    if not lock.acquire(timeout=RESYNC_LOCK_TIMEOUT_SECONDS):
        raise HTTPException(409, "sync_in_progress")
    try:
        with factory() as db:
            if metadata is not None:
                bind_local_sync_state(db, workspace_id, metadata)
            # Seed before applying: a revision-zero local row must become a pending
            # edit (and therefore a conflict) instead of being silently overwritten.
            seed_local_queue(db, workspace_id)
            db.commit()
        if remote is not None:
            context = nullcontext(remote)
        elif metadata is not None:
            context = SyncRemoteClient(metadata.coreUrl, credential or "")
        else:
            raise SyncRemoteError("invalid_local_state")
        applied = deleted = conflicts = 0
        revision, skipped = 0, 0
        with context as transport:
            for _round in range(RESYNC_SNAPSHOT_ROUNDS):
                revision, rows = _fetch_snapshot(transport, page_limit)
                round_applied, round_deleted, round_conflicts, skipped = _apply_snapshot(
                    factory, user_id, workspace_id, revision, rows)
                applied += round_applied
                deleted += round_deleted
                conflicts += round_conflicts
                if not skipped:
                    break
        if skipped:
            # Two rounds and still short: Core is being written continuously, so the
            # deferred rows stay missing until the next recovery. Never silent.
            logger.warning("Resync finished with %s deferred entities at revision %s",
                           skipped, revision)
        counts = _counts(factory, workspace_id)
        return {"workspaceRevision": revision, "applied": applied, "deleted": deleted,
                "conflicts": conflicts, "pending": counts["pending"], "cursor": counts["cursor"]}
    finally:
        lock.release()


EVENT_BATCH_LIMIT = 100
EVENT_MAX_ATTEMPTS = 10


def flush_events(factory, workspace_id, transport, cancel_event=None):
    """Bounded, best-effort delivery after sync; retained failures never log raw errors."""
    with factory() as db:
        rows = db.scalars(select(LocalAutomationEvent).where(
            LocalAutomationEvent.workspace_id == workspace_id,
            LocalAutomationEvent.delivered_at.is_(None),
            LocalAutomationEvent.attempts < EVENT_MAX_ATTEMPTS)
            .order_by(LocalAutomationEvent.created_at, LocalAutomationEvent.id).limit(EVENT_BATCH_LIMIT)).all()
        pending = [(row.id, {"type": row.type, "eventId": row.event_id,
                            "agentId": row.agent_id, "taskId": row.task_id}) for row in rows]
    for row_id, payload in pending:
        _check_cancelled(cancel_event)
        error_code = None
        try:
            transport.report_event(payload)  # No SQLite transaction is held during HTTP.
        except SyncRemoteError as error:
            error_code = error.code if error.code in {
                "unauthorized", "timeout", "unreachable", "invalid_response", "protocol_mismatch"
            } else "invalid_response"
        _check_cancelled(cancel_event)
        with factory() as db:
            row = db.get(LocalAutomationEvent, row_id)
            if error_code:
                row.attempts += 1
                row.last_error = error_code
            else:
                row.delivered_at = utcnow()
                row.last_error = None
            db.commit()


def run_sync_cycle(factory, user_id: int, workspace_id: str, metadata, credential: str,
                   remote=None, *, cancel_event=None) -> dict:
    """Synchronize one Local Personal Workspace. A caller may inject a test transport."""
    with factory() as db:
        database_key = str(db.get_bind().url)
    lock = _lock_for(database_key, workspace_id)
    if not lock.acquire(blocking=False):
        raise HTTPException(409, "Sync is already running for this workspace")
    pushed = pulled = 0
    workspace_revision = None
    try:
        _check_cancelled(cancel_event)
        with factory() as db:
            bind_local_sync_state(db, workspace_id, metadata)
            seed_local_queue(db, workspace_id)
            db.commit()
        context = nullcontext(remote) if remote is not None else SyncRemoteClient(metadata.coreUrl, credential)
        with context as transport:
            with factory() as db:
                cursor = get_local_sync_state(db, workspace_id).cursor
            _check_cancelled(cancel_event)
            if transport.get_changes(cursor, 1).get("protocolVersion") != SYNC_PROTOCOL_VERSION:
                raise SyncRemoteError("protocol_mismatch")
            _check_cancelled(cancel_event)
            with factory() as db:
                inflight = db.scalars(select(LocalMutation).where(
                    LocalMutation.workspace_id == workspace_id,
                    LocalMutation.status == "in_flight")).all()
                inflight_ids = [entry.mutation_id for entry in sorted(inflight, key=lambda entry: (
                    get_adapter(entry.entity_type).push_priority(entry.operation), entry.created_at, entry.id))]
            for mutation_id in inflight_ids:
                outcome = _send(factory, workspace_id, transport, mutation_id, cancel_event)
                pushed += outcome == "applied"
            count, workspace_revision = _pull(factory, transport, user_id, workspace_id, cancel_event)
            pulled += count
            # Re-evaluate after each acknowledgement so category dependencies and
            # pending tails can become eligible within this same cycle.
            while True:
                _check_cancelled(cancel_event)
                _repair_acknowledged_tails(factory, workspace_id)
                with factory() as db:
                    ready = _ready_pending(db, workspace_id)
                    mutation_id = ready[0].mutation_id if ready else None
                if mutation_id is None:
                    break
                outcome = _send(factory, workspace_id, transport, mutation_id, cancel_event)
                pushed += outcome == "applied"
            count, workspace_revision = _pull(factory, transport, user_id, workspace_id, cancel_event)
            pulled += count
            flush_events(factory, workspace_id, transport, cancel_event)
        _check_cancelled(cancel_event)
        with factory() as db:
            state = get_local_sync_state(db, workspace_id)
            state.last_success_at = utcnow()
            state.last_error = None
            db.commit()
        return {"status": "ok", "pushed": pushed, "pulled": pulled,
                **_counts(factory, workspace_id), "workspaceRevision": workspace_revision}
    except SyncRemoteError as error:
        _check_cancelled(cancel_event)
        with factory() as db:
            state = get_local_sync_state(db, workspace_id)
            state.last_error = error.code
            db.commit()
        # `resync_required` is a clean stop, not a cycle failure: the outbox and the
        # cursor are untouched, the scheduler keeps running, and only the explicit
        # `POST /sync/resync` (user or UI) rebuilds the replica.
        return {"status": RESYNC_REQUIRED if error.code == RESYNC_REQUIRED else "error",
                "pushed": pushed, "pulled": pulled,
                **_counts(factory, workspace_id), "workspaceRevision": workspace_revision}
    finally:
        lock.release()
