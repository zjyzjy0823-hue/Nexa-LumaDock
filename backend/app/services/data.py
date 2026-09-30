from typing import Any
from uuid import uuid4
from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..utils.time import iso_utc
from ..models import DataCollection, DataRecord, User
from ..sync.publisher import prepare_write, publish, delete_entity
from .ownership import owner_workspace


class CollectionInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    icon: str = Field(default="custom", max_length=30)
    tone: str = Field(default="blue", max_length=30)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Name is required")
        return value


class CollectionPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    icon: str | None = Field(default=None, max_length=30)
    tone: str | None = Field(default=None, max_length=30)


class RecordInput(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    status: str = Field(default="active", max_length=40)
    category: str = Field(default="", max_length=80)
    data_json: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Name is required")
        return value


class RecordPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    status: str | None = Field(default=None, max_length=40)
    category: str | None = Field(default=None, max_length=80)
    data_json: dict[str, Any] | None = None


def collection_or_404(db: Session, user: User, id: str) -> DataCollection:
    item = db.scalar(
        select(DataCollection).where(
            DataCollection.id == id,
            DataCollection.user_id == user.id,
            DataCollection.workspace_id == owner_workspace(db, user),
            DataCollection.deleted_at.is_(None),
        )
    )
    if item is None:
        raise HTTPException(404, "Collection not found")
    return item


def record_or_404(db: Session, user: User, id: str) -> DataRecord:
    item = db.scalar(
        select(DataRecord)
        .join(DataCollection)
        .where(
            DataRecord.id == id,
            DataRecord.deleted_at.is_(None),
            DataCollection.user_id == user.id,
            DataCollection.workspace_id == owner_workspace(db, user),
            DataCollection.deleted_at.is_(None),
        )
    )
    if item is None:
        raise HTTPException(404, "Record not found")
    return item


def record_out(item: DataRecord) -> dict:
    return {
        "id": item.id,
        "collectionId": item.collection_id,
        "name": item.name,
        "status": item.status,
        "category": item.category,
        "dataJson": item.data_json,
        "createdAt": iso_utc(item.created_at),
        "updatedAt": iso_utc(item.updated_at),
    }


def collection_out(item: DataCollection) -> dict:
    return {
        "id": item.id,
        "name": item.name,
        "description": item.description,
        "icon": item.icon,
        "tone": item.tone,
        "recordCount": sum((record.deleted_at is None for record in item.records)),
        "records": [
            record_out(record) for record in item.records if record.deleted_at is None
        ],
        "createdAt": iso_utc(item.created_at),
        "updatedAt": iso_utc(item.updated_at),
    }


def legacy_data(user: User = None, db: Session = None):
    items = db.scalars(
        select(DataCollection).where(
            DataCollection.user_id == user.id,
            DataCollection.workspace_id == owner_workspace(db, user),
            DataCollection.deleted_at.is_(None),
        )
    ).all()
    return {
        "collections": [collection_out(item) for item in items],
        "totalCollections": len(items),
        "totalRecords": sum(
            (
                sum((record.deleted_at is None for record in item.records))
                for item in items
            )
        ),
    }


def list_collections(user: User = None, db: Session = None):
    return [
        collection_out(item)
        for item in db.scalars(
            select(DataCollection)
            .where(
                DataCollection.user_id == user.id,
                DataCollection.workspace_id == owner_workspace(db, user),
                DataCollection.deleted_at.is_(None),
            )
            .order_by(DataCollection.created_at.desc())
        ).all()
    ]


def create_collection(payload: CollectionInput, user: User = None, db: Session = None):
    prepare_write(db, user)
    item = DataCollection(
        id=str(uuid4()),
        user_id=user.id,
        workspace_id=owner_workspace(db, user),
        **payload.model_dump(),
    )
    db.add(item)
    publish(db, item)
    return collection_out(item)


def get_collection(id: str, user: User = None, db: Session = None):
    return collection_out(collection_or_404(db, user, id))


def patch_collection(
    id: str, payload: CollectionPatch, user: User = None, db: Session = None
):
    prepare_write(db, user)
    item = collection_or_404(db, user, id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        if value is None:
            raise HTTPException(422, f"{key} cannot be null")
        setattr(item, key, value.strip() if key == "name" else value)
    if not item.name:
        raise HTTPException(422, "Name is required")
    publish(db, item)
    return collection_out(item)


def delete_collection(id: str, user: User = None, db: Session = None):
    prepare_write(db, user)
    delete_entity(db, collection_or_404(db, user, id))


def list_records(id: str, user: User = None, db: Session = None):
    return [
        record_out(item)
        for item in collection_or_404(db, user, id).records
        if item.deleted_at is None
    ]


def create_record(id: str, payload: RecordInput, user: User = None, db: Session = None):
    prepare_write(db, user)
    collection_or_404(db, user, id)
    item = DataRecord(id=str(uuid4()), collection_id=id, **payload.model_dump())
    db.add(item)
    publish(db, item)
    return record_out(item)


def patch_record(id: str, payload: RecordPatch, user: User = None, db: Session = None):
    prepare_write(db, user)
    item = record_or_404(db, user, id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        if value is None:
            raise HTTPException(422, f"{key} cannot be null")
        setattr(item, key, value.strip() if key == "name" else value)
    if not item.name:
        raise HTTPException(422, "Name is required")
    publish(db, item)
    return record_out(item)


def get_record(id: str, user: User = None, db: Session = None):
    return record_out(record_or_404(db, user, id))


def delete_record(id: str, user: User = None, db: Session = None):
    prepare_write(db, user)
    delete_entity(db, record_or_404(db, user, id))
