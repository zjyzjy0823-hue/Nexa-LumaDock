from datetime import datetime
from zoneinfo import ZoneInfo
from decimal import Decimal
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..utils.time import iso_utc
from ..database import get_db, runtime_config
from ..models import LedgerCategory, LedgerTransaction, User
from ..security import current_user

router = APIRouter(prefix="/api/v1/ledger", tags=["ledger"])
Kind = Literal["income", "expense"]


class CategoryInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    type: Kind
    icon: str = Field(default="shopping", max_length=30)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Name is required")
        return value


class CategoryPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    type: Kind | None = None
    icon: str | None = Field(default=None, max_length=30)


class TransactionInput(BaseModel):
    category_id: str | None = None
    type: Kind
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    description: str = Field(min_length=1, max_length=200)
    occurred_at: datetime
    merchant: str = Field(default="", max_length=120)
    note: str = Field(default="", max_length=500)


class TransactionPatch(BaseModel):
    category_id: str | None = None
    type: Kind | None = None
    amount: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=2)
    description: str | None = Field(default=None, min_length=1, max_length=200)
    occurred_at: datetime | None = None
    merchant: str | None = Field(default=None, max_length=120)
    note: str | None = Field(default=None, max_length=500)


def category_or_404(db: Session, user: User, id: str) -> LedgerCategory:
    item = db.scalar(select(LedgerCategory).where(LedgerCategory.id == id, LedgerCategory.user_id == user.id))
    if item is None:
        raise HTTPException(404, "Category not found")
    return item


def transaction_or_404(db: Session, user: User, id: str) -> LedgerTransaction:
    item = db.scalar(select(LedgerTransaction).where(LedgerTransaction.id == id, LedgerTransaction.user_id == user.id))
    if item is None:
        raise HTTPException(404, "Transaction not found")
    return item


def category_out(item: LedgerCategory) -> dict:
    return {"id": item.id, "name": item.name, "type": item.type, "icon": item.icon, "createdAt": iso_utc(item.created_at)}


def transaction_out(item: LedgerTransaction) -> dict:
    return {"id": item.id, "categoryId": item.category_id, "categoryName": item.category.name if item.category else None,
            "type": item.type, "amount": str(item.amount), "description": item.description,
            "occurredAt": iso_utc(item.occurred_at), "merchant": item.merchant, "note": item.note,
            "createdAt": iso_utc(item.created_at), "updatedAt": iso_utc(item.updated_at)}


def check_category(db: Session, user: User, category_id: str | None, kind: str):
    if category_id:
        category = category_or_404(db, user, category_id)
        if category.type != kind:
            raise HTTPException(422, "Category type must match transaction type")


@router.get("/categories")
def list_categories(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return [category_out(item) for item in db.scalars(select(LedgerCategory).where(LedgerCategory.user_id == user.id).order_by(LedgerCategory.created_at)).all()]


@router.post("/categories", status_code=201)
def create_category(payload: CategoryInput, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = LedgerCategory(id=str(uuid4()), user_id=user.id, **payload.model_dump())
    db.add(item); db.commit(); db.refresh(item)
    return category_out(item)


@router.patch("/categories/{id}")
def patch_category(id: str, payload: CategoryPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = category_or_404(db, user, id)
    values = payload.model_dump(exclude_unset=True)
    if "type" in values and values["type"] != item.type and item.transactions:
        raise HTTPException(409, "Cannot change category type while transactions exist")
    for key, value in values.items():
        if value is None:
            raise HTTPException(422, f"{key} cannot be null")
        setattr(item, key, value.strip() if key == "name" else value)
    if not item.name:
        raise HTTPException(422, "Name is required")
    db.commit(); db.refresh(item)
    return category_out(item)


@router.delete("/categories/{id}", status_code=204)
def delete_category(id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = category_or_404(db, user, id)
    for transaction in item.transactions:
        transaction.category_id = None
    db.delete(item); db.commit()


@router.get("/transactions")
def list_transactions(month: str | None = Query(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
                      user: User = Depends(current_user), db: Session = Depends(get_db)):
    items = db.scalars(select(LedgerTransaction).where(LedgerTransaction.user_id == user.id).order_by(LedgerTransaction.occurred_at.desc())).all()
    return [transaction_out(item) for item in items if month is None or item.occurred_at.strftime("%Y-%m") == month]


@router.post("/transactions", status_code=201)
def create_transaction(payload: TransactionInput, user: User = Depends(current_user), db: Session = Depends(get_db)):
    check_category(db, user, payload.category_id, payload.type)
    item = LedgerTransaction(id=str(uuid4()), user_id=user.id, **payload.model_dump())
    db.add(item); db.commit(); db.refresh(item)
    return transaction_out(item)


@router.get("/transactions/{id}")
def get_transaction(id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return transaction_out(transaction_or_404(db, user, id))


@router.get("/categories/{id}")
def get_category(id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return category_out(category_or_404(db, user, id))


@router.patch("/transactions/{id}")
def patch_transaction(id: str, payload: TransactionPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = transaction_or_404(db, user, id)
    values = payload.model_dump(exclude_unset=True)
    kind = values.get("type", item.type)
    category_id = values.get("category_id", item.category_id)
    if kind is None:
        raise HTTPException(422, "type cannot be null")
    check_category(db, user, category_id, kind)
    for key, value in values.items():
        if value is None and key != "category_id":
            raise HTTPException(422, f"{key} cannot be null")
        setattr(item, key, value)
    db.commit(); db.refresh(item)
    return transaction_out(item)


@router.delete("/transactions/{id}", status_code=204)
def delete_transaction(id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.delete(transaction_or_404(db, user, id)); db.commit()


@router.get("/summary")
def summary(month: str | None = Query(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
            user: User = Depends(current_user), db: Session = Depends(get_db)):
    month = month or datetime.now(ZoneInfo(runtime_config.app_timezone)).strftime("%Y-%m")
    items = db.scalars(select(LedgerTransaction).where(LedgerTransaction.user_id == user.id)).all()
    current = [item for item in items if item.occurred_at.strftime("%Y-%m") == month]
    income = sum((item.amount for item in current if item.type == "income"), Decimal("0"))
    expense = sum((item.amount for item in current if item.type == "expense"), Decimal("0"))
    categories: dict[str, dict] = {}
    for item in current:
        if item.type == "expense":
            key = item.category_id or "uncategorized"
            if key not in categories:
                categories[key] = {"id": key, "name": item.category.name if item.category else "未分类", "amount": Decimal("0")}
            categories[key]["amount"] += item.amount
    trends: dict[str, Decimal] = {}
    for item in items:
        if item.type == "expense":
            key = item.occurred_at.strftime("%Y-%m")
            trends[key] = trends.get(key, Decimal("0")) + item.amount
    return {"month": month, "income": str(income), "expense": str(expense), "balance": str(income - expense),
            "monthlyTrend": [{"month": key, "expense": str(value)} for key, value in sorted(trends.items())],
            "categories": [{**entry, "amount": str(entry["amount"])} for entry in categories.values()]}
