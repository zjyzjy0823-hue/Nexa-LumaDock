from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import LedgerCategory, LedgerTransaction
from ..utils.time import iso_utc
from .schemas import CategoryData, TransactionData


REGISTRY = {
    "ledger.category": (LedgerCategory, CategoryData),
    "ledger.transaction": (LedgerTransaction, TransactionData),
}


def serialize(item: LedgerCategory | LedgerTransaction) -> dict:
    if isinstance(item, LedgerCategory):
        return {"name": item.name, "type": item.type, "icon": item.icon}
    return {"categoryId": item.category_id, "type": item.type, "amount": str(item.amount),
            "description": item.description, "merchant": item.merchant, "note": item.note,
            "occurredAt": iso_utc(item.occurred_at)}


def category_error(db: Session, workspace_id: str, category_id: str | None, kind: str) -> str | None:
    if category_id is None:
        return None
    category = db.scalar(select(LedgerCategory).where(
        LedgerCategory.id == category_id, LedgerCategory.workspace_id == workspace_id,
        LedgerCategory.deleted_at.is_(None)))
    if category is None:
        return "category_not_found"
    if category.type != kind:
        return "category_type_mismatch"
    return None


def apply_data(item: LedgerCategory | LedgerTransaction, data: CategoryData | TransactionData) -> None:
    if isinstance(item, LedgerCategory):
        item.name, item.type, item.icon = data.name, data.type, data.icon
    else:
        item.category_id, item.type, item.amount = data.categoryId, data.type, data.amount
        item.description, item.merchant, item.note = data.description, data.merchant, data.note
        item.occurred_at = data.occurredAt
