import base64
import binascii
import hashlib
import hmac
import json
from datetime import datetime
from typing import Any
from uuid import uuid4
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session
from ..utils.time import iso_utc
from ..database import runtime_config
from ..models import DataCollection, DataRecord, User
from ..sync.publisher import prepare_write, publish, delete_entity
from .ownership import owner_workspace


def bounded_data_json(value):
    if value is not None and len(json.dumps(value, ensure_ascii=False).encode("utf-8")) > 65536:
        raise ValueError("data_json must not exceed 65536 UTF-8 bytes (64KB)")
    return value


class CollectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

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
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    icon: str | None = Field(default=None, max_length=30)
    tone: str | None = Field(default=None, max_length=30)


class RecordInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=160)
    status: str = Field(default="active", max_length=40)
    category: str = Field(default="", max_length=80)
    data_json: dict[str, Any] = Field(default_factory=dict)
    _bounded_data = field_validator("data_json")(bounded_data_json)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Name is required")
        return value


class RecordPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=160)
    status: str | None = Field(default=None, max_length=40)
    category: str | None = Field(default=None, max_length=80)
    data_json: dict[str, Any] | None = None
    _bounded_data = field_validator("data_json")(bounded_data_json)


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
    workspace_id = owner_workspace(db, user)
    item = db.scalar(
        select(DataRecord)
        .join(DataCollection)
        .where(
            DataRecord.id == id,
            DataRecord.user_id == user.id,
            DataRecord.deleted_at.is_(None),
            DataRecord.workspace_id == workspace_id,
            DataCollection.user_id == user.id,
            DataCollection.workspace_id == workspace_id,
            DataCollection.deleted_at.is_(None),
        )
    )
    if item is None:
        raise HTTPException(404, "Record not found")
    return item


def record_out(item: DataRecord, include_data_json: bool = True) -> dict:
    result = {
        "id": item.id,
        "collectionId": item.collection_id,
        "name": item.name,
        "status": item.status,
        "category": item.category,
        "createdAt": iso_utc(item.created_at),
        "updatedAt": iso_utc(item.updated_at),
    }
    if include_data_json:
        result["dataJson"] = item.data_json
    return result


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


def collection_scope(user_id: int, workspace_id: str):
    return (
        DataCollection.user_id == user_id,
        DataCollection.workspace_id == workspace_id,
        DataCollection.deleted_at.is_(None),
    )


def record_scope(user_id: int, workspace_id: str):
    """Use with a parent join; both parent and child must belong to the owner."""
    return (
        *collection_scope(user_id, workspace_id),
        DataRecord.user_id == user_id,
        DataRecord.workspace_id == workspace_id,
        DataRecord.deleted_at.is_(None),
    )


def record_match(q: str):
    return or_(*(column.icontains(q, autoescape=True) for column in (
        DataRecord.name, DataRecord.status, DataRecord.category,
    )))


def record_counts(user_id: int, workspace_id: str):
    return (
        select(DataRecord.collection_id, func.count().label("record_count"))
        .join(DataCollection)
        .where(*record_scope(user_id, workspace_id))
        .group_by(DataRecord.collection_id)
    )


def collection_response(db, user, item, include_records, count=None):
    if count is None:
        row = db.execute(record_counts(user.id, item.workspace_id)
                         .where(DataRecord.collection_id == item.id)).first()
        count = row.record_count if row else 0
    # Select only metadata here: touching item.records would trigger an unbounded read.
    result = {
        "id": item.id,
        "name": item.name,
        "description": item.description,
        "icon": item.icon,
        "tone": item.tone,
        "recordCount": count or 0,
        "createdAt": iso_utc(item.created_at),
        "updatedAt": iso_utc(item.updated_at),
    }
    if include_records:
        records = db.scalars(select(DataRecord).join(DataCollection).where(
            *record_scope(user.id, item.workspace_id), DataRecord.collection_id == item.id,
        )).all()
        result["records"] = [record_out(record) for record in records]
    return result


def list_collections(user: User = None, db: Session = None, include_records: bool = True, q: str = ""):
    workspace_id = owner_workspace(db, user)
    counts = record_counts(user.id, workspace_id).subquery()
    query = (
        select(DataCollection, func.coalesce(counts.c.record_count, 0))
        .outerjoin(counts, counts.c.collection_id == DataCollection.id)
        .where(*collection_scope(user.id, workspace_id))
        .order_by(DataCollection.created_at.desc())
    )
    if q:
        matching_record = select(DataRecord.id).where(
            DataRecord.collection_id == DataCollection.id,
            DataRecord.user_id == user.id,
            DataRecord.workspace_id == workspace_id,
            DataRecord.deleted_at.is_(None),
            record_match(q),
        ).exists()
        query = query.where(or_(DataCollection.name.icontains(q, autoescape=True),
                                DataCollection.description.icontains(q, autoescape=True), matching_record))
    return [collection_response(db, user, item, include_records, count)
            for item, count in db.execute(query).all()]


def create_collection(payload: CollectionInput, user: User = None, db: Session = None,
                      include_records: bool = True):
    prepare_write(db, user)
    item = DataCollection(
        id=str(uuid4()),
        user_id=user.id,
        workspace_id=owner_workspace(db, user),
        **payload.model_dump(),
    )
    db.add(item)
    publish(db, item)
    return collection_response(db, user, item, include_records)


def get_collection(id: str, user: User = None, db: Session = None, include_records: bool = True):
    return collection_response(db, user, collection_or_404(db, user, id), include_records)


def patch_collection(
    id: str, payload: CollectionPatch, user: User = None, db: Session = None,
    include_records: bool = True,
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
    return collection_response(db, user, item, include_records)


def delete_collection(id: str, user: User = None, db: Session = None):
    prepare_write(db, user)
    delete_entity(db, collection_or_404(db, user, id))


def list_records(id: str, user: User = None, db: Session = None):
    collection = collection_or_404(db, user, id)
    return [
        record_out(item)
        for item in db.scalars(select(DataRecord).join(DataCollection).where(
            *record_scope(user.id, collection.workspace_id), DataRecord.collection_id == id,
        )).all()
    ]


RECORD_ORDER = (DataRecord.updated_at.desc(), DataRecord.id.desc())
RECORD_SUMMARY_COLUMNS = (
    DataRecord.id, DataRecord.collection_id, DataRecord.name, DataRecord.status,
    DataRecord.category, DataRecord.created_at, DataRecord.updated_at,
)


def cursor_context(user_id, workspace_id, collection_id, q):
    return {"v": 1, "user": user_id, "workspace": workspace_id, "collection": collection_id,
            "q": q, "order": "updated_at:desc,id:desc"}


def encode_record_cursor(context, item):
    payload = {**context, "updatedAt": iso_utc(item.updated_at), "id": item.id}
    body = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()
    signature = hmac.new(runtime_config.jwt_secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{signature}"


def decode_record_cursor(cursor, context):
    try:
        body, signature = cursor.split(".")
        expected = hmac.new(runtime_config.jwt_secret.encode(), body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError
        payload = json.loads(base64.b64decode(body, altchars=b"-_", validate=True))
        if not isinstance(payload, dict) or set(payload) != set(context) | {"updatedAt", "id"}:
            raise ValueError
        if any(payload[key] != value for key, value in context.items()):
            raise ValueError
        if not isinstance(payload["id"], str) or not 1 <= len(payload["id"]) <= 36:
            raise ValueError
        timestamp = datetime.fromisoformat(payload["updatedAt"])
        if timestamp.tzinfo is None:
            raise ValueError
        return timestamp, payload["id"]
    except (ValueError, TypeError, KeyError, binascii.Error, OverflowError):
        raise HTTPException(422, "Invalid record cursor") from None


def page_records(id: str, user: User, db: Session, limit: int = 50,
                 cursor: str | None = None, q: str = "", include_data_json: bool = False):
    collection = collection_or_404(db, user, id)
    context = cursor_context(user.id, collection.workspace_id, id, q)
    position = decode_record_cursor(cursor, context) if cursor is not None else None
    scope = (*record_scope(user.id, collection.workspace_id), DataRecord.collection_id == id)
    match = record_match(q) if q else None
    # Counts describe the full result set, before the keyset cursor is applied.
    counts = select(func.count())
    if match is not None:
        counts = counts.add_columns(func.coalesce(func.sum(case((match, 1), else_=0)), 0))
    counts = counts.select_from(DataRecord).join(DataCollection).where(*scope)
    totals = db.execute(counts).one()
    total, matched = totals[0], totals[1] if match is not None else totals[0]
    columns = (*RECORD_SUMMARY_COLUMNS, DataRecord.data_json) if include_data_json else RECORD_SUMMARY_COLUMNS
    query = select(*columns).join(DataCollection).where(*scope)
    if match is not None:
        query = query.where(match)
    if position:
        timestamp, record_id = position
        query = query.where(or_(DataRecord.updated_at < timestamp,
                                and_(DataRecord.updated_at == timestamp, DataRecord.id < record_id)))
    rows = db.execute(query.order_by(*RECORD_ORDER).limit(limit + 1)).all()
    has_more = len(rows) > limit
    items = rows[:limit]  # At most limit + 1 rows were read from SQL.
    return {
        "items": [record_out(item, include_data_json) for item in items],
        "total": total,
        "matchedCount": matched,
        "nextCursor": encode_record_cursor(context, items[-1]) if has_more else None,
        "hasMore": has_more,
    }


def overview(user: User, db: Session, recent_limit: int = 4):
    workspace_id = owner_workspace(db, user)
    total_collections = db.scalar(select(func.count()).select_from(DataCollection)
                                  .where(*collection_scope(user.id, workspace_id)))
    total, completed = db.execute(
        select(func.count(), func.coalesce(func.sum(case(
            (DataRecord.status.in_(("done", "completed", "完成")), 1), else_=0,
        )), 0))
        .select_from(DataRecord).join(DataCollection).where(*record_scope(user.id, workspace_id))
    ).one()
    recent = db.execute(
        select(*RECORD_SUMMARY_COLUMNS, DataCollection.name.label("collection_name"))
        .join(DataCollection).where(*record_scope(user.id, workspace_id))
        .order_by(*RECORD_ORDER).limit(recent_limit)
    ).all()
    return {
        "totalCollections": total_collections,
        "totalRecords": total,
        "active": total - completed,
        "completed": completed,
        "recentRecords": [{**record_out(item, False), "collectionName": item.collection_name} for item in recent],
    }


def create_record(id: str, payload: RecordInput, user: User = None, db: Session = None):
    prepare_write(db, user)
    collection = collection_or_404(db, user, id)
    item = DataRecord(
        id=str(uuid4()),
        collection_id=collection.id,
        user_id=collection.user_id,
        workspace_id=collection.workspace_id,
        **payload.model_dump(),
    )
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
