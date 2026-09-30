"""Business operations only; queue, revisions and replay belong to the engine."""
from dataclasses import dataclass

from sqlalchemy import select

from ...models import LocalMutation
from ..remote import SyncRemoteError


@dataclass(frozen=True)
class SyncAdapter:
    entity_type: str
    model: type
    schema: type
    fields: dict[str, str]
    priority: int
    generation: int = 1
    parent_type: str | None = None
    parent_field: str | None = None
    push_requires_active_parent: bool = True

    def serialize(self, item):
        from ...utils.time import iso_utc
        from datetime import datetime
        from decimal import Decimal
        return {key: iso_utc(value) if isinstance(value, datetime) else
                str(value) if isinstance(value, Decimal) else value
                for key, attr in self.fields.items() for value in [getattr(item, attr)]}

    def apply_data(self, item, data):
        for key, attr in self.fields.items():
            setattr(item, attr, getattr(data, key))

    def workspace_id(self, db, item):
        return item.workspace_id

    def create(self, db, entity_id, user_id, workspace_id, data):
        return self.model(id=entity_id, user_id=user_id, workspace_id=workspace_id)

    def legacy_rows(self, db, workspace_id):
        return db.scalars(select(self.model).where(
            self.model.workspace_id == workspace_id, self.model.sync_revision == 0,
            self.model.deleted_at.is_(None)).order_by(self.model.created_at, self.model.id)).all()

    def dependency_error(self, db, workspace_id, data, item=None):
        if self.parent_type:
            from .registry import get_adapter
            parent_id = getattr(data, self.parent_field)
            if parent_id is not None:
                adapter = get_adapter(self.parent_type)
                parent = db.get(adapter.model, parent_id)
                if (parent is None or adapter.workspace_id(db, parent) != workspace_id
                        or parent.deleted_at is not None):
                    return "category_not_found" if self.parent_field == "categoryId" else "collection_not_found"
        return None

    def push_priority(self, operation):
        return self.priority if operation == "upsert" else 100 - self.priority

    def remote_dependency_error(self, db, workspace_id, data, item=None):
        return self.dependency_error(db, workspace_id, data, item)

    def push_ready(self, db, workspace_id, entry):
        if not self.parent_type or entry.operation != "upsert":
            return True
        from .registry import get_adapter
        parent_id = (entry.payload_json or {}).get(self.parent_field)
        if parent_id is None:
            return True
        adapter = get_adapter(self.parent_type)
        parent = db.get(adapter.model, parent_id)
        if parent is None or adapter.workspace_id(db, parent) != workspace_id:
            raise SyncRemoteError("missing_category" if self.parent_field == "categoryId" else "missing_collection")
        return parent.sync_revision > 0 and (
            not self.push_requires_active_parent or parent.deleted_at is None) and db.scalar(
            select(LocalMutation.id).where(LocalMutation.workspace_id == workspace_id,
                LocalMutation.entity_type == self.parent_type,
                LocalMutation.entity_id == parent_id).limit(1)) is None

    def prepare_local_seed(self, db, item):
        pass

    def prepare_ordinary_upsert(self, item):
        pass

    def prepare_delete(self, db, item, publish):
        pass
