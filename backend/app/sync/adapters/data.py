from typing import Any
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from ...models import DataCollection, DataRecord, utcnow
from .base import SyncAdapter


class CollectionData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    icon: str = Field(default="custom", max_length=30)
    tone: str = Field(default="blue", max_length=30)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value):
        if not value.strip():
            raise ValueError("Name is required")
        return value.strip()


class RecordData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    collectionId: str
    name: str = Field(min_length=1, max_length=160)
    status: str = Field(default="active", max_length=40)
    category: str = Field(default="", max_length=80)
    dataJson: dict[str, Any] = Field(default_factory=dict)
    @field_validator("name")
    @classmethod
    def clean_name(cls, value):
        if not value.strip():
            raise ValueError("Name is required")
        return value.strip()


class DataCollectionAdapter(SyncAdapter):
    def prepare_delete(self, db, item, publish):
        for child in db.scalars(select(DataRecord).where(DataRecord.collection_id == item.id,
                                                         DataRecord.deleted_at.is_(None))).all():
            child.deleted_at = utcnow()
            publish(db, child, "delete")


class DataRecordAdapter(SyncAdapter):
    def workspace_id(self, db, item):
        parent = db.get(DataCollection, item.collection_id)
        return parent.workspace_id if parent else None

    def create(self, db, entity_id, user_id, workspace_id, data):
        return DataRecord(id=entity_id, collection_id=data.collectionId)

    def legacy_rows(self, db, workspace_id):
        return db.scalars(select(DataRecord).join(DataCollection).where(
            DataCollection.workspace_id == workspace_id, DataCollection.deleted_at.is_(None),
            DataRecord.sync_revision == 0, DataRecord.deleted_at.is_(None))
            .order_by(DataRecord.created_at, DataRecord.id)).all()

    def dependency_error(self, db, workspace_id, data, item=None):
        reason = super().dependency_error(db, workspace_id, data, item)
        if reason:
            return reason
        if item is not None and item.collection_id != data.collectionId:
            return "collection_id_immutable"


ADAPTERS = [
    DataCollectionAdapter("data.collection", DataCollection, CollectionData,
        {"name": "name", "description": "description", "icon": "icon", "tone": "tone"}, 20, 2),
    DataRecordAdapter("data.record", DataRecord, RecordData,
        {"collectionId": "collection_id", "name": "name", "status": "status",
         "category": "category", "dataJson": "data_json"}, 21, 2, "data.collection", "collectionId"),
]
