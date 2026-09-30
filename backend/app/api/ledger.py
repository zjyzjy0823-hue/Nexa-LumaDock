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
from ..models import LedgerCategory, LedgerTransaction, LocalSyncState, User, utcnow
from ..security import current_user
from ..sync.adapters import seed_version
from ..sync.local import record_local_delete, record_local_upsert, seed_local_ledger_queue
from ..sync.service import ensure_core_sync_initialized, record_ordinary_change
from ..workspaces import get_personal_workspace


def ensure_local_ledger_ready(user: User = Depends(current_user), db: Session = Depends(get_db)) -> None:
    if runtime_config.mode == "local":
        workspace_id = get_personal_workspace(db, user).id
        try:
            state = db.get(LocalSyncState, workspace_id)
            if state is None or state.queue_seed_version < seed_version():
                seed_local_ledger_queue(db, workspace_id)
                db.commit()
        except Exception:
            db.rollback()
            raise


router = APIRouter(prefix="/api/v1/ledger", tags=["ledger"], dependencies=[Depends(ensure_local_ledger_ready)])
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
    workspace_id = get_personal_workspace(db, user).id
    item = db.scalar(select(LedgerCategory).where(LedgerCategory.id == id, LedgerCategory.user_id == user.id,
                                                  LedgerCategory.workspace_id == workspace_id,
                                                  LedgerCategory.deleted_at.is_(None)))
    if item is None:
        raise HTTPException(404, "Category not found")
    return item


def transaction_or_404(db: Session, user: User, id: str) -> LedgerTransaction:
    workspace_id = get_personal_workspace(db, user).id
    item = db.scalar(select(LedgerTransaction).where(LedgerTransaction.id == id, LedgerTransaction.user_id == user.id,
                                                     LedgerTransaction.workspace_id == workspace_id,
                                                     LedgerTransaction.deleted_at.is_(None)))
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


def commit_ledger(db: Session, item: LedgerCategory | LedgerTransaction, operation: str = "upsert") -> None:
    try:
        if runtime_config.mode == "core":
            record_ordinary_change(db, item, operation)
        elif operation == "delete":
            record_local_delete(db, item)
        else:
            record_local_upsert(db, item)
        db.commit()
        db.refresh(item)
    except Exception:
        db.rollback()
        raise


def lock_core_write(db: Session, user: User) -> None:
    if runtime_config.mode == "core":
        ensure_core_sync_initialized(db, get_personal_workspace(db, user).id)


@router.get("/categories")
def list_categories(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return [category_out(item) for item in db.scalars(select(LedgerCategory).where(
        LedgerCategory.user_id == user.id, LedgerCategory.deleted_at.is_(None)).order_by(LedgerCategory.created_at)).all()]


@router.post("/categories", status_code=201)
def create_category(payload: CategoryInput, user: User = Depends(current_user), db: Session = Depends(get_db)):
    lock_core_write(db, user)
    item = LedgerCategory(id=str(uuid4()), user_id=user.id,
                          workspace_id=get_personal_workspace(db, user).id, **payload.model_dump())
    db.add(item); commit_ledger(db, item)
    return category_out(item)


@router.patch("/categories/{id}")
def patch_category(id: str, payload: CategoryPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    lock_core_write(db, user)
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
    commit_ledger(db, item)
    return category_out(item)


@router.delete("/categories/{id}", status_code=204)
def delete_category(id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    lock_core_write(db, user)
    item = category_or_404(db, user, id)
    item.deleted_at = utcnow()
    commit_ledger(db, item, "delete")


@router.get("/transactions")
def list_transactions(month: str | None = Query(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
                      user: User = Depends(current_user), db: Session = Depends(get_db)):
    items = db.scalars(select(LedgerTransaction).where(
        LedgerTransaction.user_id == user.id, LedgerTransaction.deleted_at.is_(None))
        .order_by(LedgerTransaction.occurred_at.desc())).all()
    return [transaction_out(item) for item in items if month is None or item.occurred_at.strftime("%Y-%m") == month]


@router.post("/transactions", status_code=201)
def create_transaction(payload: TransactionInput, user: User = Depends(current_user), db: Session = Depends(get_db)):
    lock_core_write(db, user)
    check_category(db, user, payload.category_id, payload.type)
    item = LedgerTransaction(id=str(uuid4()), user_id=user.id,
                             workspace_id=get_personal_workspace(db, user).id, **payload.model_dump())
    db.add(item); commit_ledger(db, item)
    return transaction_out(item)


@router.get("/transactions/{id}")
def get_transaction(id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return transaction_out(transaction_or_404(db, user, id))


@router.get("/categories/{id}")
def get_category(id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return category_out(category_or_404(db, user, id))


@router.patch("/transactions/{id}")
def patch_transaction(id: str, payload: TransactionPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    lock_core_write(db, user)
    item = transaction_or_404(db, user, id)
    values = payload.model_dump(exclude_unset=True)
    kind = values.get("type", item.type)
    category_id = values.get("category_id", item.category_id)
    if kind is None:
        raise HTTPException(422, "type cannot be null")
    if "category_id" in values or kind != item.type:
        check_category(db, user, category_id, kind)
    for key, value in values.items():
        if value is None and key != "category_id":
            raise HTTPException(422, f"{key} cannot be null")
        setattr(item, key, value)
    commit_ledger(db, item)
    return transaction_out(item)


@router.delete("/transactions/{id}", status_code=204)
def delete_transaction(id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    lock_core_write(db, user)
    item = transaction_or_404(db, user, id)
    item.deleted_at = utcnow()
    commit_ledger(db, item, "delete")


@router.get("/summary")
def summary(month: str | None = Query(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
            user: User = Depends(current_user), db: Session = Depends(get_db)):
    month = month or datetime.now(ZoneInfo(runtime_config.app_timezone)).strftime("%Y-%m")
    items = db.scalars(select(LedgerTransaction).where(
        LedgerTransaction.user_id == user.id, LedgerTransaction.deleted_at.is_(None))).all()
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
