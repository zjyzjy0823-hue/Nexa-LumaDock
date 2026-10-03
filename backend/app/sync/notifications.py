"""Wake the app-owned scheduler only after the Local outbox commits.

No database, credential or network access occurs in these transaction hooks.
Registrations use Engine identity so independent replicas and test databases
cannot accidentally wake another application's coordinator.
"""

import logging
from threading import Lock
from weakref import WeakKeyDictionary

from sqlalchemy import event
from sqlalchemy.orm import Session


_guard = Lock()
_coordinators = WeakKeyDictionary()
_REQUESTS = "nexa_sync_requests"
logger = logging.getLogger(__name__)


def register_coordinator(engine, coordinator):
    with _guard:
        if engine in _coordinators:
            raise RuntimeError("A sync coordinator already owns this Local database")
        _coordinators[engine] = coordinator


def unregister_coordinator(engine, coordinator):
    with _guard:
        if _coordinators.get(engine) is coordinator:
            del _coordinators[engine]


def get_coordinator(bind):
    engine = getattr(bind, "engine", bind)
    with _guard:
        return _coordinators.get(engine)


def request_after_commit(db, workspace_id):
    db.info.setdefault(_REQUESTS, set()).add(workspace_id)


@event.listens_for(Session, "after_commit")
def _committed(db):
    if db.in_nested_transaction():
        return
    requested = db.info.pop(_REQUESTS, ())
    coordinator = get_coordinator(db.get_bind())
    if coordinator is not None:
        for workspace_id in requested:
            try:
                coordinator.request_sync(workspace_id)
            except Exception:
                # The business transaction already succeeded. Periodic sync or
                # restart recovers the durable outbox even if a wake-up fails.
                logger.warning("Background sync wake-up unavailable")


@event.listens_for(Session, "after_soft_rollback")
def _rolled_back(db, previous_transaction):
    if previous_transaction.parent is None:
        db.info.pop(_REQUESTS, None)
