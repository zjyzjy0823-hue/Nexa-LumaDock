"""Publish ordinary business writes inside the caller's database transaction."""
from sqlalchemy import update

from ..database import runtime_config
from ..models import LocalSyncState
from ..services.ownership import owner_workspace
from .adapters import REGISTRY, adapter_for, seed_version
from .local import get_local_sync_state, record_local_delete, record_local_upsert, seed_local_queue
from .service import ensure_core_sync_initialized, record_ordinary_change


def prepare_write(db, user):
    workspace_id = owner_workspace(db, user)
    if runtime_config.mode == "core":
        # Adopt legacy parents before an ordinary child write can enter history.
        ensure_core_sync_initialized(db, workspace_id)
    else:
        get_local_sync_state(db, workspace_id)
        # Serialize with explicit conflict decisions before reading business
        # rows. Otherwise a patch could publish unedited attributes cached
        # before a concurrent Core-version decision replaced the row.
        db.execute(update(LocalSyncState).where(LocalSyncState.workspace_id == workspace_id)
                   .values(updated_at=LocalSyncState.updated_at)
                   .execution_options(synchronize_session=False))
        # An agent action may have already inserted its audit receipt in this
        # transaction. Preserve auth/audit objects for their rollback handling;
        # only synchronized business rows can contain pre-resolution data.
        refresh_models = tuple(adapter.model for adapter in REGISTRY.values()) + (LocalSyncState,)
        for cached in list(db.identity_map.values()):
            if isinstance(cached, refresh_models):
                db.expire(cached)
        state = db.get(LocalSyncState, workspace_id)
        if state is None or state.queue_seed_version < seed_version():
            seed_local_queue(db, workspace_id)


def publish(db, item, operation="upsert"):
    if operation == "upsert":
        adapter_for(item).prepare_ordinary_upsert(item)
    # Flush assigns defaults and updated_at before freezing the business snapshot.
    db.flush()
    if runtime_config.mode == "core":
        record_ordinary_change(db, item, operation)
    elif operation == "delete":
        record_local_delete(db, item)
    else:
        record_local_upsert(db, item)


def delete_entity(db, item):
    from ..models import utcnow
    if runtime_config.mode == "core":
        adapter_for(item).prepare_delete(db, item, publish)
    item.deleted_at = utcnow()
    publish(db, item, "delete")
