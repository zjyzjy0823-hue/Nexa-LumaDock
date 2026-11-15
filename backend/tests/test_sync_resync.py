"""Local recovery from a Core snapshot (`POST /api/v1/sync/resync`) — resync P2.

`GET /changes` answers a cursor beyond the Core revision with `resyncRequired`
instead of a dead end (P1). This module covers the Local half: recognising that
signal mid-cycle, rebuilding the replica from the snapshot, and the acceptance
cases R1/R2/R3/R4/R7/R9 of `docs/resync-2026-11-15.md` §5.
"""

import time
from threading import Thread
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app import core_connection
from app.database import get_db
from app.main import app
from app.models import (Client, LedgerCategory, LedgerTransaction, LocalMutation,
                        LocalSyncState, SyncWorkspaceState, User)
from app.sync import engine
from app.sync.engine import _lock_for, run_resync, run_sync_cycle
from app.sync.remote import SyncRemoteClient, SyncRemoteError
from app.sync.service import ensure_core_sync_initialized
from app.sync.snapshot import (SnapshotCursorInvalid, SnapshotExpired, build_snapshot,
                               encode_snapshot_id)
from app.workspaces import get_personal_workspace
from test_background_sync import (FakeClock, Runner, async_test, completed,
                                  make_coordinator, restored)
from test_sync_engine import (CoreTransport, create_category, create_transaction,
                              delete, edit, queue, replica)


class SnapshotTransport(CoreTransport):
    """`CoreTransport` plus the P1 snapshot endpoint, served from the Core database.

    It raises exactly what `SyncRemoteClient` raises for the two recovery bodies, so
    the engine sees the same error codes it would see over HTTP.
    """

    def __init__(self, core, client_id):
        super().__init__(core, client_id)
        self.pages = []
        self.pin_revision = None       # serve the snapshot as of an older revision
        self.after_first_page = None   # a concurrent Core write between pages
        self.expire_page = False       # the snapshot becomes unconstructable mid-paging

    def get_snapshot(self, snapshot_id=None, cursor=None, limit=200):
        if self.unauthorized:
            raise SyncRemoteError("unauthorized")
        if self.expire_page and cursor is not None:
            self.expire_page = False
            raise SyncRemoteError("snapshot_expired")
        with self.core.factory() as db:
            ensure_core_sync_initialized(db, self.core.workspace_id)
            db.commit()
            if snapshot_id is None and cursor is None and self.pin_revision is not None:
                snapshot_id = encode_snapshot_id(self.core.workspace_id, self.pin_revision)
            try:
                page = build_snapshot(db, self.core.workspace_id, limit=limit,
                                      snapshot_id=snapshot_id, cursor=cursor)
            except SnapshotExpired:
                raise SyncRemoteError("snapshot_expired") from None
            except SnapshotCursorInvalid:
                raise SyncRemoteError("resync_required") from None
            db.commit()  # release the read lock before the concurrent-write hook
        self.pages.append(page)
        hook, self.after_first_page = self.after_first_page, None
        if hook is not None:
            hook()
        return page

    def get_changes(self, cursor, limit):
        try:
            return super().get_changes(cursor, limit)
        except HTTPException as error:
            if error.status_code == 400 and error.detail == "Invalid sync cursor":
                raise SyncRemoteError("resync_required") from None
            raise


@pytest.fixture
def network(tmp_path):
    core = replica(tmp_path, "resync_core", 33)
    a = replica(tmp_path, "resync_a", 11)
    b = replica(tmp_path, "resync_b", 22)
    transports = []
    with core.factory() as db:
        for index in range(2):
            client_id = str(uuid4())
            db.add(Client(id=client_id, workspace_id=core.workspace_id,
                          installation_id=str(uuid4()), name=f"Client {index}",
                          platform="windows", app_version="0.6.2"))
            transports.append(SnapshotTransport(core, client_id))
        db.commit()

    def metadata(transport):
        return SimpleNamespace(coreUrl="https://core.example", workspaceId=core.workspace_id,
                               clientId=transport.client_id)

    def sync(local, transport):
        return run_sync_cycle(local.factory, local.user_id, local.workspace_id,
                              metadata(transport), "nc_live_test", transport)

    def resync(local, transport, **kwargs):
        return run_resync(local.factory, local.user_id, local.workspace_id,
                          metadata(transport), "nc_live_test", transport, **kwargs)

    yield SimpleNamespace(core=core, a=a, b=b, ta=transports[0], tb=transports[1],
                          sync=sync, resync=resync)
    for database in (a, b, core):
        database.engine.dispose()


def revision_of(network):
    with network.core.factory() as db:
        return db.get(SyncWorkspaceState, network.core.workspace_id).current_revision


def test_recovery_error_bodies_map_to_safe_codes(monkeypatch):
    """`resyncRequired` and `snapshot_expired` stay distinguishable from corruption."""
    original_client = httpx.Client
    responses = {}

    def handler(request):
        return responses[request.url.path]

    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original_client(
        transport=httpx.MockTransport(handler), **kwargs))
    with SyncRemoteClient("https://core.example", "nc_live_test") as remote:
        responses["/api/v1/sync/changes"] = httpx.Response(400, json={
            "detail": "Invalid sync cursor", "resyncRequired": True, "workspaceRevision": 9})
        with pytest.raises(SyncRemoteError) as error:
            remote.get_changes(99)
        assert error.value.code == "resync_required"

        responses["/api/v1/sync/snapshot"] = httpx.Response(409, json={
            "detail": "snapshot_expired"})
        with pytest.raises(SyncRemoteError) as error:
            remote.get_snapshot(cursor="c", snapshot_id="s")
        assert error.value.code == "snapshot_expired"

        responses["/api/v1/sync/snapshot"] = httpx.Response(409, json={
            "detail": "sync_protocol_mismatch"})
        with pytest.raises(SyncRemoteError) as error:
            remote.get_snapshot()
        assert error.value.code == "protocol_mismatch"

        responses["/api/v1/sync/snapshot"] = httpx.Response(400, json={
            "detail": "Invalid sync cursor", "resyncRequired": True, "workspaceRevision": 4})
        with pytest.raises(SyncRemoteError) as error:
            remote.get_snapshot()
        assert error.value.code == "resync_required"


def test_snapshot_paging_parameters_and_page_validation(monkeypatch):
    original_client = httpx.Client
    seen = []

    def handler(request):
        seen.append(request)
        more = "cursor" not in request.url.params
        return httpx.Response(200, json={
            "protocolVersion": 3, "snapshotId": "snap-1", "workspaceRevision": 4,
            "entities": [{"entityType": "ledger.category", "entityId": str(uuid4()),
                          "syncRevision": 3, "deleted": False,
                          "data": {"name": "Food", "type": "expense", "icon": "shopping"}}],
            "cursor": "next" if more else None, "hasMore": more})

    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original_client(
        transport=httpx.MockTransport(handler), **kwargs))
    with SyncRemoteClient("https://core.example", "nc_live_test") as remote:
        first = remote.get_snapshot(limit=50)
        second = remote.get_snapshot("snap-1", "next", limit=50)

    assert first["snapshotId"] == "snap-1" and first["hasMore"] is True
    assert second["hasMore"] is False and second["cursor"] is None
    assert seen[0].url.params["protocolVersion"] == "3" and seen[0].url.params["limit"] == "50"
    assert "snapshotId" not in seen[0].url.params and "cursor" not in seen[0].url.params
    assert seen[1].url.params["snapshotId"] == "snap-1"
    assert seen[1].url.params["cursor"] == "next"


@pytest.mark.parametrize("page", [
    # hasMore without a continuation point cannot be followed.
    {"protocolVersion": 3, "snapshotId": "s", "workspaceRevision": 4, "entities": [],
     "cursor": None, "hasMore": True},
    # cursor is null iff hasMore is false.
    {"protocolVersion": 3, "snapshotId": "s", "workspaceRevision": 4, "entities": [],
     "cursor": "next", "hasMore": False},
    # A tombstone carries no payload; a live entity must carry one.
    {"protocolVersion": 3, "snapshotId": "s", "workspaceRevision": 4, "hasMore": False,
     "cursor": None, "entities": [{"entityType": "ledger.category", "entityId": str(uuid4()),
                                   "syncRevision": 3, "deleted": True, "data": {"name": "x"}}]},
    {"protocolVersion": 3, "snapshotId": "s", "workspaceRevision": 4, "hasMore": False,
     "cursor": None, "entities": [{"entityType": "ledger.category", "entityId": str(uuid4()),
                                   "syncRevision": 3, "deleted": False, "data": None}]},
])
def test_malformed_snapshot_pages_are_rejected(monkeypatch, page):
    original_client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original_client(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=page)), **kwargs))
    with SyncRemoteClient("https://core.example", "nc_live_test") as remote:
        with pytest.raises(SyncRemoteError, match="invalid_response"):
            remote.get_snapshot()


# --- R1: a cursor ahead of Core requests recovery without touching the outbox -----

def test_cycle_reports_resync_required_and_keeps_the_outbox(network):
    n = network
    item_id = create_transaction(n.a)
    assert n.sync(n.a, n.ta)["status"] == "ok"
    assert n.sync(n.b, n.tb)["status"] == "ok"
    edit(n.b, item_id, "Local before resync")
    with n.b.factory() as db:
        db.get(LocalSyncState, n.b.workspace_id).cursor = 99  # Core lost this history
        db.commit()

    result = n.sync(n.b, n.tb)

    assert result["status"] == "resync_required"
    assert result["lastError"] == "resync_required"
    assert result["cursor"] == 99 and result["pending"] == 1
    assert [entry[1] for entry in queue(n.b, item_id)] == ["pending"]
    with n.b.factory() as db:
        # The persisted status the UI reads (`/sync/status` → `lastError`).
        assert db.get(LocalSyncState, n.b.workspace_id).last_error == "resync_required"
        assert db.get(LedgerTransaction, item_id).description == "Local before resync"

    # The documented exit: the explicit recovery drops the cursor back to Core's
    # revision, and the pending edit is still pushable (nothing was lost).
    recovered = n.resync(n.b, n.tb)
    assert recovered == {"workspaceRevision": 1, "applied": 0, "deleted": 0,
                         "conflicts": 0, "pending": 1, "cursor": 1}
    assert n.sync(n.b, n.tb)["status"] == "ok"
    with n.core.factory() as db:
        assert db.get(LedgerTransaction, item_id).description == "Local before resync"
    assert queue(n.b, item_id) == []


@async_test
async def test_resync_required_keeps_the_workspace_scheduled(tmp_path):
    """Not `blocked`: the user still needs the periodic cycle and the resync button."""
    local = replica(tmp_path, "resync_scheduler", 101)
    paused = {"status": "resync_required", "lastError": "resync_required", "pending": 1,
              "inFlight": 0, "conflicts": 0, "rejected": 0, "cursor": 99, "pushed": 0,
              "pulled": 0, "workspaceRevision": None}
    clock, runner = FakeClock(), Runner([paused, {**paused, "status": "ok", "lastError": None}])
    coordinator = make_coordinator(local, clock, runner)
    await restored(coordinator)
    try:
        clock.advance(1)
        await completed(coordinator, runner, 1)
        state = coordinator.snapshot(local.workspace_id)
        assert state["blocked"] is False and state["nextRetryAt"] is None
        assert state["enabled"] is True
        clock.advance(30)  # the ordinary period, not the retry backoff
        await completed(coordinator, runner, 2)
    finally:
        await coordinator.stop()
        local.engine.dispose()


def test_resync_required_is_a_known_sync_state():
    from app.sync.background import SAFE_SYNC_ERRORS

    # `/sync/status` and diagnostics mask any unknown code as `internal_error`.
    assert {"resync_required", "snapshot_expired"} <= SAFE_SYNC_ERRORS


# --- R2: recovery never silently overwrites a pending local edit ------------------

def test_resync_keeps_the_pending_edit_and_reports_a_conflict(network):
    n = network
    item_id = create_transaction(n.a)
    assert n.sync(n.a, n.ta)["status"] == "ok"
    assert n.sync(n.b, n.tb)["status"] == "ok"
    edit(n.b, item_id, "Local 42")
    edit(n.a, item_id, "Remote 41")
    assert n.sync(n.a, n.ta)["status"] == "ok"
    assert revision_of(n) == 2

    result = n.resync(n.b, n.tb)

    assert result == {"workspaceRevision": 2, "applied": 0, "deleted": 0,
                      "conflicts": 1, "pending": 0, "cursor": 2}
    with n.b.factory() as db:
        item = db.get(LedgerTransaction, item_id)
        assert item.description == "Local 42" and item.sync_revision == 1
        assert item.deleted_at is None
        entry = db.scalar(select(LocalMutation).where(LocalMutation.entity_id == item_id))
        assert entry.status == "conflict" and entry.result_revision == 2
        assert entry.conflict_json["current"]["description"] == "Remote 41"
        assert entry.conflict_json["currentRevision"] == 2
    # The following cycle must not overwrite the local value either.
    assert n.sync(n.b, n.tb)["status"] == "ok"
    with n.b.factory() as db:
        assert db.get(LedgerTransaction, item_id).description == "Local 42"


def test_resync_restarts_a_snapshot_that_expires_mid_paging(network):
    n = network
    ids = [create_transaction(n.a, description=f"T{index}") for index in range(3)]
    assert n.sync(n.a, n.ta)["status"] == "ok"
    n.tb.expire_page = True

    result = n.resync(n.b, n.tb, page_limit=1)

    assert result == {"workspaceRevision": 3, "applied": 3, "deleted": 0,
                      "conflicts": 0, "pending": 0, "cursor": 3}
    # One page of the aborted snapshot, then the three pages of the restarted one.
    assert len(n.tb.pages) == 4
    with n.b.factory() as db:
        for item_id in ids:
            item = db.get(LedgerTransaction, item_id)
            assert item.deleted_at is None and item.description.startswith("T")


# --- R3: an explicit Core tombstone deletes the local row -------------------------

def test_snapshot_tombstone_marks_the_local_row_deleted(network):
    n = network
    item_id = create_transaction(n.a)
    assert n.sync(n.a, n.ta)["status"] == "ok"
    assert n.sync(n.b, n.tb)["status"] == "ok"
    delete(n.a, item_id)
    assert n.sync(n.a, n.ta)["status"] == "ok"
    assert revision_of(n) == 2

    result = n.resync(n.b, n.tb)

    assert result == {"workspaceRevision": 2, "applied": 0, "deleted": 1,
                      "conflicts": 0, "pending": 0, "cursor": 2}
    with n.b.factory() as db:
        item = db.get(LedgerTransaction, item_id)
        assert item.deleted_at is not None and item.sync_revision == 2
    assert queue(n.b, item_id) == []  # recovery never enqueues a push of its own


# --- R4: one page per call still applies the whole workspace ----------------------

def test_paged_snapshot_applies_every_entity_and_lands_on_the_pinned_revision(network):
    n = network
    category_id = create_category(n.a)
    ids = [create_transaction(n.a, category_id) for _ in range(4)]
    assert n.sync(n.a, n.ta)["status"] == "ok"
    revision = revision_of(n)
    assert revision == 5

    result = n.resync(n.b, n.tb, page_limit=1)

    assert result == {"workspaceRevision": revision, "applied": 5, "deleted": 0,
                      "conflicts": 0, "pending": 0, "cursor": revision}
    assert len(n.tb.pages) == 5
    assert {page["workspaceRevision"] for page in n.tb.pages} == {revision}
    assert n.tb.pages[-1]["hasMore"] is False and n.tb.pages[-1]["cursor"] is None
    with n.b.factory() as db:
        assert db.get(LedgerCategory, category_id).name == "Food"
        for item_id in ids:
            item = db.get(LedgerTransaction, item_id)
            assert item.workspace_id == n.b.workspace_id and item.category_id == category_id
            assert item.deleted_at is None
    with n.b.factory() as db:
        assert db.get(LocalSyncState, n.b.workspace_id).last_error is None


# --- R9: absent from the snapshot is not deleted ---------------------------------

def test_entity_written_after_the_snapshot_is_not_deleted(network):
    n = network
    category_id = create_category(n.a)
    item_id = create_transaction(n.a, category_id)
    assert n.sync(n.a, n.ta)["status"] == "ok"
    assert n.sync(n.b, n.tb)["status"] == "ok"
    edit(n.b, item_id, "Local 42")

    def concurrent_write():
        # Lands after the snapshot pinned revision 2, while this client is paging.
        edit(n.a, item_id, "Remote 41")
        assert n.sync(n.a, n.ta)["status"] == "ok"
        assert revision_of(n) == 3

    n.tb.pin_revision = 2
    n.tb.after_first_page = concurrent_write
    result = n.resync(n.b, n.tb, page_limit=1)

    # The transaction is filtered out of the snapshot (its revision is 3 > R=2).
    assert result == {"workspaceRevision": 2, "applied": 0, "deleted": 0,
                      "conflicts": 0, "pending": 1, "cursor": 2}
    with n.b.factory() as db:
        item = db.get(LedgerTransaction, item_id)
        assert item.deleted_at is None and item.description == "Local 42"
        assert item.sync_revision == 2
    assert [entry[1] for entry in queue(n.b, item_id)] == ["pending"]

    # `/changes?cursor=R` then converges: the local edit conflicts instead of losing.
    result = n.sync(n.b, n.tb)
    assert result["status"] == "ok" and result["conflicts"] == 1 and result["cursor"] == 3
    with n.b.factory() as db:
        item = db.get(LedgerTransaction, item_id)
        assert item.description == "Local 42" and item.deleted_at is None
        entry = db.scalar(select(LocalMutation).where(LocalMutation.entity_id == item_id))
        assert entry.conflict_json["current"]["description"] == "Remote 41"


# --- R7: recovery and a sync cycle never overlap ----------------------------------

def test_resync_times_out_with_sync_in_progress(network, monkeypatch):
    n = network
    monkeypatch.setattr(engine, "RESYNC_LOCK_TIMEOUT_SECONDS", 0.2)
    with n.b.factory() as db:
        lock = _lock_for(str(db.get_bind().url), n.b.workspace_id)
    assert lock.acquire(blocking=False)
    try:
        with pytest.raises(HTTPException) as error:
            n.resync(n.b, n.tb)
    finally:
        lock.release()

    assert error.value.status_code == 409 and error.value.detail == "sync_in_progress"
    assert n.tb.pages == []  # nothing was fetched while another cycle held the lock


def test_resync_waits_for_a_running_cycle(network):
    n = network
    with n.b.factory() as db:
        lock = _lock_for(str(db.get_bind().url), n.b.workspace_id)
    assert lock.acquire(blocking=False)

    def release_after(delay):
        try:
            time.sleep(delay)
        finally:
            lock.release()

    releaser = Thread(target=release_after, args=(0.2,))
    releaser.start()
    try:
        started = time.monotonic()
        result = n.resync(n.b, n.tb)
        waited = time.monotonic() - started
    finally:
        releaser.join()
        if lock.locked():
            lock.release()

    assert result["cursor"] == 0 and waited >= 0.15, f"did not wait for the lock ({waited:.3f}s)"


# --- API: `POST /api/v1/sync/resync` ----------------------------------------------

def session():
    iterator = app.dependency_overrides[get_db]()
    return iterator, next(iterator)


def local_identity():
    """The registered user's workspace and the URL its session binds to."""
    iterator, db = session()
    try:
        user = db.scalar(select(User).where(User.username == "owner_a"))
        return get_personal_workspace(db, user).id, str(db.get_bind().url)
    finally:
        iterator.close()


class FakeSnapshot:
    """Stands in for `SyncRemoteClient`: one already-complete snapshot page."""

    def __init__(self, page):
        self.page = page
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass

    def get_snapshot(self, snapshot_id=None, cursor=None, limit=200):
        self.calls.append((snapshot_id, cursor, limit))
        return self.page


def test_resync_endpoint_returns_the_documented_shape(client, users, monkeypatch):
    auth, _ = users
    workspace_id, _bind = local_identity()
    metadata = SimpleNamespace(coreUrl="https://core.example", workspaceId=str(uuid4()),
                               clientId=str(uuid4()))
    monkeypatch.setattr(core_connection, "load_connection", lambda _user_id: metadata)
    monkeypatch.setattr(core_connection.credential_store, "load", lambda _user_id: "nc_live_secret")
    live_id, dead_id = str(uuid4()), str(uuid4())
    transport = FakeSnapshot({
        "protocolVersion": 3, "snapshotId": "snap-1", "workspaceRevision": 4, "cursor": None,
        "hasMore": False, "entities": [
            {"entityType": "ledger.category", "entityId": live_id, "syncRevision": 3,
             "deleted": False, "data": {"name": "Remote", "type": "expense", "icon": "shopping"}},
            # A tombstone for a row this replica never held: nothing to delete, no error.
            {"entityType": "ledger.category", "entityId": dead_id, "syncRevision": 4,
             "deleted": True, "data": None}]})
    monkeypatch.setattr(engine, "SyncRemoteClient", lambda _url, _credential: transport)

    response = client.post("/api/v1/sync/resync", headers=auth)

    assert response.status_code == 200, response.text
    assert response.json() == {"workspaceRevision": 4, "applied": 1, "deleted": 0,
                               "conflicts": 0, "pending": 0, "cursor": 4}
    assert transport.calls == [(None, None, 200)]
    names = {row["name"] for row in client.get("/api/v1/ledger/categories", headers=auth).json()}
    assert "Remote" in names
    iterator, db = session()
    try:
        assert db.get(LedgerCategory, live_id).workspace_id == workspace_id
        assert db.get(LocalSyncState, workspace_id).cursor == 4
        assert db.get(LocalSyncState, workspace_id).last_error is None
    finally:
        iterator.close()


def test_resync_endpoint_reports_sync_in_progress(client, users, monkeypatch):
    auth, _ = users
    workspace_id, bind = local_identity()
    metadata = SimpleNamespace(coreUrl="https://core.example", workspaceId=str(uuid4()),
                               clientId=str(uuid4()))
    monkeypatch.setattr(core_connection, "load_connection", lambda _user_id: metadata)
    monkeypatch.setattr(core_connection.credential_store, "load", lambda _user_id: "nc_live_secret")
    monkeypatch.setattr(engine, "RESYNC_LOCK_TIMEOUT_SECONDS", 0.1)
    lock = _lock_for(bind, workspace_id)
    assert lock.acquire(blocking=False)
    try:
        response = client.post("/api/v1/sync/resync", headers=auth)
    finally:
        lock.release()

    assert response.status_code == 409
    assert response.json()["detail"] == "sync_in_progress"


# ---------------------------------------------------------------------------
# Deferred children: a snapshot may return a child whose parent was written
# after the pinned revision, so the parent is filtered out. Applying such a
# child would violate the storage FK, and skipping it outright would lose it
# forever (its own change revision is <= R, so /changes?cursor=R never replays
# it). Recovery must therefore run one more snapshot round before giving up.
# ---------------------------------------------------------------------------


def test_snapshot_round_defers_a_child_whose_parent_is_missing(network):
    n = network
    child_row = ("ledger.transaction", str(uuid4()), "upsert", 0, {
        "categoryId": str(uuid4()), "type": "expense", "amount": "9.00",
        "description": "child of a parent filtered at the pinned revision",
        "merchant": "", "note": "", "occurredAt": "2026-11-15T00:00:00Z"})
    applied, deleted, conflicts, skipped = engine._apply_snapshot(
        n.b.factory, n.b.user_id, n.b.workspace_id, 10, [child_row])
    assert skipped == 1, "a child without its parent must be deferred, not applied"
    assert (applied, deleted, conflicts) == (0, 0, 0)


def test_resync_runs_a_second_round_when_a_round_defers_anything(network, monkeypatch):
    calls = {"fetch": 0, "apply": []}

    def fake_fetch(transport, page_limit):
        calls["fetch"] += 1
        if calls["fetch"] == 1:
            return 10, [("ledger.category", str(uuid4()), "upsert", 9, None)]
        return 11, []

    def fake_apply(factory, user_id, workspace_id, revision, rows):
        calls["apply"].append(revision)
        if len(calls["apply"]) == 1:
            return 0, 0, 0, 1          # one deferred child
        return 2, 0, 0, 0              # second round applies both

    monkeypatch.setattr(engine, "_fetch_snapshot", fake_fetch)
    monkeypatch.setattr(engine, "_apply_snapshot", fake_apply)
    receipt = network.resync(network.b, network.tb, page_limit=1)
    assert calls["fetch"] == 2 and calls["apply"] == [10, 11]
    assert receipt["workspaceRevision"] == 11
    assert receipt["applied"] == 2
    # `_apply_snapshot` is faked here, so it never writes the cursor itself; the
    # real cursor write is covered by the non-faked pagination test above.
