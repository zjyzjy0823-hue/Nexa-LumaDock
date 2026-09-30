from datetime import datetime
from urllib.parse import urlsplit
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from ...models import WebsiteCategory, Website, utcnow
from .base import SyncAdapter


class WebsiteCategoryData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    order: int = 0

    @field_validator("name")
    @classmethod
    def clean_name(cls, value):
        if not value.strip():
            raise ValueError("Name is required")
        return value.strip()


class WebsiteData(WebsiteCategoryData):
    name: str = Field(min_length=1, max_length=120)
    url: str = Field(max_length=2048)
    icon: str | None = Field(default=None, max_length=500)
    description: str | None = Field(default=None, max_length=500)
    categoryId: str | None = None
    favorite: bool = False
    lastVisitedAt: datetime | None = None
    createdAt: datetime
    updatedAt: datetime

    @field_validator("url")
    @classmethod
    def valid_url(cls, value):
        parsed = urlsplit(value)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or any(c.isspace() for c in value):
            raise ValueError("URL must be an absolute HTTP or HTTPS URL")
        _ = parsed.port
        return value


class WebsiteCategoryAdapter(SyncAdapter):
    def prepare_delete(self, db, item, publish):
        for child in db.scalars(select(Website).where(Website.category_id == item.id,
                Website.workspace_id == item.workspace_id, Website.deleted_at.is_(None))).all():
            child.category_id = None
            child.updated_at = utcnow()
            publish(db, child, "upsert")


class WebsiteAdapter(SyncAdapter):
    def prepare_ordinary_upsert(self, item):
        item.updated_at = utcnow()

    def prepare_local_seed(self, db, item):
        parent = db.get(WebsiteCategory, item.category_id) if item.category_id else None
        if parent is not None and parent.deleted_at is not None:
            item.category_id = None
            return True


ADAPTERS = [
    WebsiteCategoryAdapter("website.category", WebsiteCategory, WebsiteCategoryData,
                          {"name": "name", "order": "order"}, 10, 2),
    WebsiteAdapter("website", Website, WebsiteData,
        {"name": "name", "url": "url", "icon": "icon", "description": "description",
         "categoryId": "category_id", "favorite": "favorite", "order": "order",
         "lastVisitedAt": "last_visited_at", "createdAt": "created_at", "updatedAt": "updated_at"},
        11, 2, "website.category", "categoryId"),
]
