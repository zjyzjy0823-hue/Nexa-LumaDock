from uuid import uuid4
from urllib.parse import urlsplit
from datetime import datetime, timezone
from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import or_, select
from sqlalchemy.orm import Session
from ..utils.time import iso_utc
from ..models import User, Website, WebsiteCategory
from ..sync.publisher import prepare_write, publish, delete_entity
from .ownership import owner_workspace


class WebsiteInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    url: str = Field(max_length=2048)
    icon: str | None = Field(default=None, max_length=500)
    description: str | None = Field(default=None, max_length=500)
    categoryId: str | None = None
    favorite: bool = False
    order: int = 0

    @field_validator("url")
    @classmethod
    def valid_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in ("http", "https")
            or not parsed.hostname
            or any((c.isspace() for c in value))
        ):
            raise ValueError("URL must be an absolute HTTP or HTTPS URL")
        _ = parsed.port
        return value

    @field_validator("name")
    @classmethod
    def nonempty_name(cls, value: str) -> str:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("Name cannot be empty")
        return value


class WebsitePatch(WebsiteInput):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    url: str | None = Field(default=None, max_length=2048)


def website_json(item: Website) -> dict:
    return dict(
        id=item.id,
        name=item.name,
        url=item.url,
        icon=item.icon,
        description=item.description,
        categoryId=item.category_id,
        favorite=item.favorite,
        order=item.order,
        createdAt=iso_utc(item.created_at),
        updatedAt=iso_utc(item.updated_at),
        lastVisitedAt=iso_utc(item.last_visited_at),
    )


class CategoryInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    order: int = 0

    @field_validator("name")
    @classmethod
    def nonempty_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Name cannot be empty")
        return value


class CategoryPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    order: int | None = None

    @field_validator("name")
    @classmethod
    def nonempty_name(cls, value: str | None) -> str | None:
        if value is not None and (not value.strip()):
            raise ValueError("Name cannot be empty")
        return value


def category_json(item: WebsiteCategory) -> dict:
    return dict(id=item.id, name=item.name, order=item.order)


def owned_website(db: Session, user: User, id: str) -> Website:
    item = db.scalar(
        select(Website).where(
            Website.id == id,
            Website.user_id == user.id,
            Website.workspace_id == owner_workspace(db, user),
            Website.deleted_at.is_(None),
        )
    )
    if item is None:
        raise HTTPException(404, "Website not found")
    return item


def owned_category(db: Session, user: User, id: str) -> WebsiteCategory:
    item = db.scalar(
        select(WebsiteCategory).where(
            WebsiteCategory.id == id,
            WebsiteCategory.user_id == user.id,
            WebsiteCategory.workspace_id == owner_workspace(db, user),
            WebsiteCategory.deleted_at.is_(None),
        )
    )
    if item is None:
        raise HTTPException(404, "Category not found")
    return item


def validate_category(db: Session, user: User, id: str | None):
    if id is not None:
        owned_category(db, user, id)


def list_websites(
    categoryId: str | None = None,
    search: str | None = None,
    favorite: bool | None = None,
    sort: str = "order",
    user: User = None,
    db: Session = None,
):
    query = select(Website).where(
        Website.user_id == user.id,
        Website.workspace_id == owner_workspace(db, user),
        Website.deleted_at.is_(None),
    )
    if categoryId:
        query = query.where(Website.category_id == categoryId)
    if search:
        term = f"%{search.strip()}%"
        query = query.where(
            or_(
                Website.name.ilike(term),
                Website.description.ilike(term),
                Website.url.ilike(term),
            )
        )
    if favorite is not None:
        query = query.where(Website.favorite == favorite)
    order_column = {
        "order": Website.order,
        "name": Website.name,
        "createdAt": Website.created_at,
        "updatedAt": Website.updated_at,
        "recent": Website.last_visited_at,
    }[sort]
    direction = (
        order_column.desc()
        if sort in ("createdAt", "updatedAt", "recent")
        else order_column.asc()
    )
    return [
        website_json(item) for item in db.scalars(query.order_by(direction, Website.id))
    ]


def create_website(payload: WebsiteInput, user: User = None, db: Session = None):
    prepare_write(db, user)
    validate_category(db, user, payload.categoryId)
    item = Website(
        id=str(uuid4()),
        user_id=user.id,
        workspace_id=owner_workspace(db, user),
        category_id=payload.categoryId,
        name=payload.name.strip(),
        url=payload.url,
        icon=payload.icon,
        description=payload.description,
        favorite=payload.favorite,
        order=payload.order,
    )
    db.add(item)
    publish(db, item)
    return website_json(item)


def get_website(id: str, user: User = None, db: Session = None):
    return website_json(owned_website(db, user, id))


def visit_website(id: str, user: User = None, db: Session = None):
    prepare_write(db, user)
    item = owned_website(db, user, id)
    item.last_visited_at = datetime.now(timezone.utc)
    publish(db, item)
    return website_json(item)


def update_website(
    id: str, payload: WebsitePatch, user: User = None, db: Session = None
):
    prepare_write(db, user)
    item = owned_website(db, user, id)
    changes = payload.model_dump(exclude_unset=True)
    if "categoryId" in changes:
        validate_category(db, user, changes.pop("categoryId"))
        item.category_id = payload.categoryId
    for key, value in changes.items():
        if value is None and key in ("name", "url", "favorite", "order"):
            raise HTTPException(422, f"{key} cannot be null")
        setattr(item, key, value.strip() if key == "name" else value)
    publish(db, item)
    return website_json(item)


def delete_website(id: str, user: User = None, db: Session = None):
    prepare_write(db, user)
    delete_entity(db, owned_website(db, user, id))


def list_categories(user: User = None, db: Session = None):
    return [
        category_json(item)
        for item in db.scalars(
            select(WebsiteCategory)
            .where(
                WebsiteCategory.user_id == user.id,
                WebsiteCategory.workspace_id == owner_workspace(db, user),
                WebsiteCategory.deleted_at.is_(None),
            )
            .order_by(WebsiteCategory.order, WebsiteCategory.id)
        )
    ]


def create_category(payload: CategoryInput, user: User = None, db: Session = None):
    prepare_write(db, user)
    item = WebsiteCategory(
        id=str(uuid4()),
        user_id=user.id,
        workspace_id=owner_workspace(db, user),
        name=payload.name.strip(),
        order=payload.order,
    )
    db.add(item)
    publish(db, item)
    return category_json(item)


def update_category(
    id: str, payload: CategoryPatch, user: User = None, db: Session = None
):
    prepare_write(db, user)
    item = owned_category(db, user, id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        if value is None:
            raise HTTPException(422, f"{key} cannot be null")
        setattr(item, key, value.strip() if key == "name" else value)
    publish(db, item)
    return category_json(item)


def delete_category(id: str, user: User = None, db: Session = None):
    prepare_write(db, user)
    item = owned_category(db, user, id)
    delete_entity(db, item)
