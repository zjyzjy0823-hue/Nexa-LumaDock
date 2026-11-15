"""Consistent full-state reads for client recovery (Sync Protocol v3 resync).

``GET /api/v1/sync/changes`` replays history from a cursor and rejects a cursor that
is ahead of the workspace revision. A client whose cursor is ahead — Core rebuilt,
restored from a backup, or its workspace recreated — cannot catch up by replaying, so
``docs/resync-2026-11-15.md`` §2 replaces that dead end with a state snapshot.

A snapshot is a keyset-paginated read of every entity in the workspace (tombstones
included), pinned to a single workspace revision ``R``:

* the first request fixes ``R = SyncWorkspaceState.current_revision`` under the
  workspace row lock and returns it inside an opaque ``snapshotId``;
* later pages echo ``snapshotId``, so they keep reading *as of* the same ``R``;
* every page filters ``entity.sync_revision <= R``, so a row written while the client
  is paging (revision ``R+1``) cannot tear the snapshot, and a row whose current
  content was written at revision ``<= R`` *is* its state at ``R``.

Consequence for consumers (contract §11.3.1): a row updated after ``R`` has
``sync_revision > R`` and is therefore *absent* from this snapshot — but it is not
deleted. Absence must never be read as a deletion; only explicit tombstones
(``deleted: true``) mean that, and everything else converges through
``/changes?cursor=R``.

Personal-state entity ids are UUID5-derived and their payloads are projections, so the
page is assembled from the adapters and ordered in Python on
``(entityType, entityId)`` — the only total order that spans the nine heterogeneous
tables and stays stable between ``/changes`` and a snapshot.
"""

import base64
import binascii
from uuid import uuid4

from sqlalchemy import select

from .adapters import REGISTRY, adapter_for
from .protocol import SYNC_PROTOCOL_VERSION
from .service import lock_workspace_state

SNAPSHOT_ID_PREFIX = "v1"
DEFAULT_LIMIT = 200
MAX_LIMIT = 500


class SnapshotExpired(Exception):
    """The requested snapshot can no longer be reconstructed (or never could).

    ``workspace_revision`` is the revision the client should restart from, i.e. the
    workspace's current one.
    """

    def __init__(self, workspace_revision: int):
        super().__init__("snapshot_expired")
        self.workspace_revision = workspace_revision


class SnapshotCursorInvalid(Exception):
    """``cursor`` is not a value this endpoint produced for this workspace."""

    def __init__(self, workspace_revision: int):
        super().__init__("Invalid sync cursor")
        self.workspace_revision = workspace_revision


def _encode(raw: bytes) -> str:
    # base64url without padding: the value travels in a query string, so `=` would
    # have to be percent-encoded for no benefit.
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode(value: str) -> bytes:
    padded = value + "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(padded.encode("ascii"))
    except (binascii.Error, UnicodeEncodeError, ValueError):
        raise ValueError("not base64url") from None


def encode_snapshot_id(workspace_id: str, revision: int) -> str:
    """Opaque, self-describing snapshot handle: ``v1|workspace|revision|nonce``."""
    nonce = uuid4().hex[:12]
    return _encode(f"{SNAPSHOT_ID_PREFIX}|{workspace_id}|{revision}|{nonce}".encode())


def decode_snapshot_id(value: str) -> tuple[str, int]:
    """Return ``(workspace_id, revision)``; any malformed value raises ``ValueError``."""
    try:
        text = _decode(value).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        raise ValueError("not a snapshot id") from None
    parts = text.split("|")
    if len(parts) != 4 or parts[0] != SNAPSHOT_ID_PREFIX or not parts[3]:
        raise ValueError("not a snapshot id")
    revision = parts[2]
    if not revision.isdigit():
        raise ValueError("not a snapshot id")
    return parts[1], int(revision)


def encode_cursor(entity_type: str, entity_id: str) -> str:
    """Opaque keyset cursor: the ``(entityType, entityId)`` to continue *after*."""
    return _encode(f"{entity_type}|{entity_id}".encode())


def decode_cursor(value: str) -> tuple[str, str]:
    """Return ``(entity_type, entity_id)``; unknown types or malformed values raise."""
    try:
        text = _decode(value).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        raise ValueError("not a snapshot cursor") from None
    entity_type, separator, entity_id = text.partition("|")
    if not separator or not entity_id or entity_type not in REGISTRY:
        raise ValueError("not a snapshot cursor")
    return entity_type, entity_id


def _snapshot_revision(snapshot_id: str | None, workspace_id: str,
                       current_revision: int) -> int:
    if snapshot_id is None:
        return current_revision
    try:
        snapshot_workspace, revision = decode_snapshot_id(snapshot_id)
    except ValueError:
        raise SnapshotExpired(current_revision) from None
    # A snapshot id is only meaningful for the workspace that produced it, and only
    # while the revision it pins is still inside the workspace's history.
    if snapshot_workspace != workspace_id or revision > current_revision:
        raise SnapshotExpired(current_revision)
    return revision


def _read_page(db, workspace_id: str, revision: int,
               after: tuple[str, str] | None, limit: int) -> list[tuple]:
    """Every entity of the workspace as of ``revision``, ordered after ``after``.

    The ``sync_revision <= revision`` filter and the workspace scope are pushed into
    SQL; the keyset comparison is not, because two of the nine adapters derive
    ``entityId`` by UUID5 from the entity type (their primary key is not the wire id),
    so the anchor only exists after serialization. One page therefore costs O(rows in
    the workspace) — a recovery path, not a hot loop, and the alternative (a UNION over
    nine tables with per-type id expressions) would be far harder to keep correct.
    """
    rows: list[tuple[str, str, object]] = []
    for entity_type in sorted(REGISTRY):
        if after is not None and entity_type < after[0]:
            continue
        adapter = REGISTRY[entity_type]
        items = db.scalars(select(adapter.model).where(
            adapter.model.workspace_id == workspace_id,
            adapter.model.sync_revision <= revision)).all()
        for item in items:
            entity_id = adapter.entity_id(item)
            if after is not None and entity_type == after[0] and entity_id <= after[1]:
                continue
            rows.append((entity_type, entity_id, item))
    # Deterministic across every page: entity ids are canonical lowercase UUIDs, so
    # plain string comparison is the same order on every platform.
    rows.sort(key=lambda row: (row[0], row[1]))
    return rows[:limit + 1]


def _entity(adapter, item) -> dict:
    deleted = item.deleted_at is not None
    return {"entityType": adapter.entity_type,
            "entityId": adapter.entity_id(item),
            "syncRevision": item.sync_revision,
            "deleted": deleted,
            # Tombstones carry no payload: the client only needs to know it is gone.
            "data": None if deleted else adapter_for(item).serialize(item)}


def build_snapshot(db, workspace_id: str, *, limit: int = DEFAULT_LIMIT,
                   snapshot_id: str | None = None,
                   cursor: str | None = None) -> dict:
    """One snapshot page. Pure read: callers own the transaction and its locking.

    Raises ``SnapshotExpired`` when ``snapshot_id`` cannot be honoured and
    ``SnapshotCursorInvalid`` when ``cursor`` is malformed, unknown, or sent without the
    ``snapshot_id`` that pins its revision.
    """
    if not 1 <= limit <= MAX_LIMIT:
        raise ValueError("limit must be 1..500")
    state = lock_workspace_state(db, workspace_id)
    current_revision = state.current_revision
    revision = _snapshot_revision(snapshot_id, workspace_id, current_revision)

    after = None
    if cursor is not None:
        # Without the pinned revision the next page could skip a row inserted before
        # the cursor position, so a bare cursor is refused instead of served torn.
        if snapshot_id is None:
            raise SnapshotCursorInvalid(current_revision)
        try:
            after = decode_cursor(cursor)
        except ValueError:
            raise SnapshotCursorInvalid(current_revision) from None

    rows = _read_page(db, workspace_id, revision, after, limit)
    has_more = len(rows) > limit
    page = rows[:limit]
    return {"protocolVersion": SYNC_PROTOCOL_VERSION,
            "snapshotId": snapshot_id or encode_snapshot_id(workspace_id, revision),
            "workspaceRevision": revision,
            "entities": [_entity(adapter_for(item), item) for _type, _id, item in page],
            "cursor": encode_cursor(page[-1][0], page[-1][1]) if has_more else None,
            "hasMore": has_more}
