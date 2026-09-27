from typing import Any
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session
from ...database import get_db
from ...models import DataCollection, DataRecord, User
from ...security import current_user, read_user_for

router = APIRouter(prefix="/api/data", tags=["data"])
v1_router = APIRouter(prefix="/api/v1/data", tags=["data"])


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
    item = db.scalar(select(DataCollection).where(DataCollection.id == id, DataCollection.user_id == user.id))
    if item is None:
        raise HTTPException(404, "Collection not found")
    return item


def record_or_404(db: Session, user: User, id: str) -> DataRecord:
    item = db.scalar(select(DataRecord).join(DataCollection).where(DataRecord.id == id, DataCollection.user_id == user.id))
    if item is None:
        raise HTTPException(404, "Record not found")
    return item


def record_out(item: DataRecord) -> dict:
    return {"id": item.id, "collectionId": item.collection_id, "name": item.name, "status": item.status,
            "category": item.category, "dataJson": item.data_json, "createdAt": item.created_at, "updatedAt": item.updated_at}


def collection_out(item: DataCollection) -> dict:
    return {"id": item.id, "name": item.name, "description": item.description, "icon": item.icon,
            "tone": item.tone, "recordCount": len(item.records), "records": [record_out(record) for record in item.records],
            "createdAt": item.created_at, "updatedAt": item.updated_at}


@router.get("")
def legacy_data(user: User = Depends(read_user_for("Data")), db: Session = Depends(get_db)):
    items = db.scalars(select(DataCollection).where(DataCollection.user_id == user.id)).all()
    return {"collections": [collection_out(item) for item in items], "totalCollections": len(items),
            "totalRecords": sum(len(item.records) for item in items)}


@v1_router.get("/collections")
def list_collections(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return [collection_out(item) for item in db.scalars(select(DataCollection).where(DataCollection.user_id == user.id).order_by(DataCollection.created_at.desc())).all()]


@v1_router.post("/collections", status_code=201)
def create_collection(payload: CollectionInput, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = DataCollection(id=str(uuid4()), user_id=user.id, **payload.model_dump())
    db.add(item); db.commit(); db.refresh(item)
    return collection_out(item)


@v1_router.get("/collections/{id}")
def get_collection(id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return collection_out(collection_or_404(db, user, id))


@v1_router.patch("/collections/{id}")
def patch_collection(id: str, payload: CollectionPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = collection_or_404(db, user, id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        if value is None:
            raise HTTPException(422, f"{key} cannot be null")
        setattr(item, key, value.strip() if key == "name" else value)
    if not item.name:
        raise HTTPException(422, "Name is required")
    db.commit(); db.refresh(item)
    return collection_out(item)


@v1_router.delete("/collections/{id}", status_code=204)
def delete_collection(id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.delete(collection_or_404(db, user, id)); db.commit()


@v1_router.get("/collections/{id}/records")
def list_records(id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return [record_out(item) for item in collection_or_404(db, user, id).records]


@v1_router.post("/collections/{id}/records", status_code=201)
def create_record(id: str, payload: RecordInput, user: User = Depends(current_user), db: Session = Depends(get_db)):
    collection_or_404(db, user, id)
    item = DataRecord(id=str(uuid4()), collection_id=id, **payload.model_dump())
    db.add(item); db.commit(); db.refresh(item)
    return record_out(item)


@v1_router.patch("/records/{id}")
def patch_record(id: str, payload: RecordPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = record_or_404(db, user, id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        if value is None:
            raise HTTPException(422, f"{key} cannot be null")
        setattr(item, key, value.strip() if key == "name" else value)
    if not item.name:
        raise HTTPException(422, "Name is required")
    db.commit(); db.refresh(item)
    return record_out(item)


@v1_router.get("/records/{id}")
def get_record(id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return record_out(record_or_404(db, user, id))


@v1_router.delete("/records/{id}", status_code=204)
def delete_record(id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.delete(record_or_404(db, user, id)); db.commit()
