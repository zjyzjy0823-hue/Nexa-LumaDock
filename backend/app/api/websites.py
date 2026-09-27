from uuid import uuid4
from urllib.parse import urlsplit
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User, Website, WebsiteCategory
from ..security import current_user

router = APIRouter(prefix="/api/v1", tags=["websites"])


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
        if parsed.scheme not in ("http", "https") or not parsed.hostname or any(c.isspace() for c in value):
            raise ValueError("URL must be an absolute HTTP or HTTPS URL")
        _ = parsed.port
        return value

    @field_validator("name")
    @classmethod
    def nonempty_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Name cannot be empty")
        return value


class WebsitePatch(WebsiteInput):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    url: str | None = None


def website_json(item: Website) -> dict:
    return dict(id=item.id, name=item.name, url=item.url, icon=item.icon,
                description=item.description, categoryId=item.category_id,
                favorite=item.favorite, order=item.order,
                createdAt=item.created_at.isoformat(), updatedAt=item.updated_at.isoformat(),
                lastVisitedAt=item.last_visited_at.isoformat() if item.last_visited_at else None)


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
        if value is not None and not value.strip():
            raise ValueError("Name cannot be empty")
        return value


def category_json(item: WebsiteCategory) -> dict:
    return dict(id=item.id, name=item.name, order=item.order)


def owned_website(db: Session, user: User, id: str) -> Website:
    item = db.scalar(select(Website).where(Website.id == id, Website.user_id == user.id))
    if item is None:
        raise HTTPException(404, "Website not found")
    return item


def owned_category(db: Session, user: User, id: str) -> WebsiteCategory:
    item = db.scalar(select(WebsiteCategory).where(WebsiteCategory.id == id, WebsiteCategory.user_id == user.id))
    if item is None:
        raise HTTPException(404, "Category not found")
    return item


def validate_category(db: Session, user: User, id: str | None):
    if id is not None:
        owned_category(db, user, id)


@router.get("/websites")
def list_websites(categoryId: str | None = None, search: str | None = None,
                  favorite: bool | None = None, sort: str = Query("order", pattern="^(order|name|createdAt|updatedAt|recent)$"),
                  user: User = Depends(current_user), db: Session = Depends(get_db)):
    query = select(Website).where(Website.user_id == user.id)
    if categoryId:
        query = query.where(Website.category_id == categoryId)
    if search:
        term = f"%{search.strip()}%"
        query = query.where(or_(Website.name.ilike(term), Website.description.ilike(term), Website.url.ilike(term)))
    if favorite is not None:
        query = query.where(Website.favorite == favorite)
    order_column = {"order": Website.order, "name": Website.name, "createdAt": Website.created_at,
                    "updatedAt": Website.updated_at, "recent": Website.last_visited_at}[sort]
    direction = order_column.desc() if sort in ("createdAt", "updatedAt", "recent") else order_column.asc()
    return [website_json(item) for item in db.scalars(query.order_by(direction, Website.id))]


@router.post("/websites", status_code=201)
def create_website(payload: WebsiteInput, user: User = Depends(current_user), db: Session = Depends(get_db)):
    validate_category(db, user, payload.categoryId)
    item = Website(id=str(uuid4()), user_id=user.id, category_id=payload.categoryId,
                   name=payload.name.strip(), url=payload.url, icon=payload.icon,
                   description=payload.description, favorite=payload.favorite, order=payload.order)
    db.add(item)
    db.commit()
    db.refresh(item)
    return website_json(item)


@router.get("/websites/{id}")
def get_website(id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return website_json(owned_website(db, user, id))


@router.post("/websites/{id}/visit")
def visit_website(id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = owned_website(db, user, id)
    item.last_visited_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(item)
    return website_json(item)


@router.patch("/websites/{id}")
def update_website(id: str, payload: WebsitePatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = owned_website(db, user, id)
    changes = payload.model_dump(exclude_unset=True)
    if "categoryId" in changes:
        validate_category(db, user, changes.pop("categoryId"))
        item.category_id = payload.categoryId
    for key, value in changes.items():
        if value is None and key in ("name", "url", "favorite", "order"):
            raise HTTPException(422, f"{key} cannot be null")
        setattr(item, key, value.strip() if key == "name" else value)
    db.commit()
    db.refresh(item)
    return website_json(item)


@router.delete("/websites/{id}", status_code=204)
def delete_website(id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.delete(owned_website(db, user, id))
    db.commit()


@router.get("/website-categories")
def list_categories(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return [category_json(item) for item in db.scalars(select(WebsiteCategory).where(
        WebsiteCategory.user_id == user.id).order_by(WebsiteCategory.order, WebsiteCategory.id))]


@router.post("/website-categories", status_code=201)
def create_category(payload: CategoryInput, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = WebsiteCategory(id=str(uuid4()), user_id=user.id, name=payload.name.strip(), order=payload.order)
    db.add(item)
    db.commit()
    db.refresh(item)
    return category_json(item)


@router.patch("/website-categories/{id}")
def update_category(id: str, payload: CategoryPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = owned_category(db, user, id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        if value is None:
            raise HTTPException(422, f"{key} cannot be null")
        setattr(item, key, value.strip() if key == "name" else value)
    db.commit()
    db.refresh(item)
    return category_json(item)


@router.delete("/website-categories/{id}", status_code=204)
def delete_category(id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = owned_category(db, user, id)
    for website in db.scalars(select(Website).where(Website.category_id == id, Website.user_id == user.id)):
        website.category_id = None
    db.delete(item)
    db.commit()
