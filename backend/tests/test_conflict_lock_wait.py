"""A user decision waits for an in-flight sync cycle instead of failing instantly.

Regression cover for the `sync_in_progress` 409 seen in the PostgreSQL Personal
State E2E: the background cycle holds the workspace lock on a 1s period, and
`resolve_conflict` used to try the lock without waiting, so "Keep Local" could
fail purely because a cycle happened to be running.
"""
import time
from threading import Thread

from app.database import get_db
from app.main import app
from app.sync import conflicts as conflicts_module
from app.sync.engine import _lock_for

from test_conflicts import api_conflict  # noqa: F401  (pytest fixture)

ROOT = "/api/v1/sync/conflicts"


def session():
    iterator = app.dependency_overrides[get_db]()
    return iterator, next(iterator)


def workspace_lock(workspace_id):
    iterator, db = session()
    try:
        return _lock_for(str(db.get_bind().url), workspace_id)
    finally:
        iterator.close()


def test_resolution_waits_for_the_running_cycle(client, api_conflict):
    auth, _, entity_id, conflict_id, workspace_id = api_conflict
    lock = workspace_lock(workspace_id)
    assert lock.acquire(blocking=False), "workspace lock must be free before the test"

    def release_after(delay):
        try:
            time.sleep(delay)
        finally:
            lock.release()

    releaser = Thread(target=release_after, args=(0.2,))
    releaser.start()
    try:
        started = time.monotonic()
        response = client.post(f"{ROOT}/{conflict_id}/resolve", headers=auth,
                               json={"strategy": "remote"})
        waited = time.monotonic() - started
    finally:
        releaser.join()
        if lock.locked():
            lock.release()

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "resolved"
    assert waited >= 0.15, f"the request did not wait for the lock ({waited:.3f}s)"


def test_resolution_still_reports_a_stuck_cycle(client, api_conflict, monkeypatch):
    auth, _, entity_id, conflict_id, workspace_id = api_conflict
    monkeypatch.setattr(conflicts_module, "RESOLVE_LOCK_TIMEOUT_SECONDS", 0.2)
    lock = workspace_lock(workspace_id)
    assert lock.acquire(blocking=False)
    try:
        response = client.post(f"{ROOT}/{conflict_id}/resolve", headers=auth,
                               json={"strategy": "remote"})
    finally:
        lock.release()

    assert response.status_code == 409
    assert response.json()["detail"] == "sync_in_progress"
