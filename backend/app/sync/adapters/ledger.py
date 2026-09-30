from sqlalchemy import select
from ...models import LedgerCategory, LedgerTransaction
from ..schemas import CategoryData, TransactionData

from .base import SyncAdapter


class LedgerCategoryAdapter(SyncAdapter):
    def remote_dependency_error(self, db, workspace_id, data, item=None):
        return None

    def dependency_error(self, db, workspace_id, data, item=None):
        if item is not None and item.type != data.type and db.scalar(select(
                LedgerTransaction.id).where(LedgerTransaction.category_id == item.id).limit(1)):
            return "category_has_transactions"

    def prepare_delete(self, db, item, publish):
        # Preserve Ledger semantics: established transactions keep the category UUID.
        from fastapi import HTTPException
        if item.sync_revision == 0:
            active = db.scalars(select(LedgerTransaction).where(
                LedgerTransaction.workspace_id == item.workspace_id,
                LedgerTransaction.category_id == item.id,
                LedgerTransaction.deleted_at.is_(None))).all()
            if any(row.sync_revision > 0 for row in active):
                raise HTTPException(409, "Unsynced category has a synced transaction")
            for row in active:
                row.category_id = None
                publish(db, row, "upsert")


class LedgerTransactionAdapter(SyncAdapter):
    def remote_dependency_error(self, db, workspace_id, data, item=None):
        # Authoritative history may update a transaction's retained tombstone
        # category reference, as supported by the ordinary Ledger API in v0.5.3.
        if data.categoryId is not None:
            parent = db.get(LedgerCategory, data.categoryId)
            if parent is None or parent.workspace_id != workspace_id:
                return "category_not_found"

    def dependency_error(self, db, workspace_id, data, item=None):
        if data.categoryId is None:
            return None
        parent = db.get(LedgerCategory, data.categoryId)
        if parent is None or parent.workspace_id != workspace_id or parent.deleted_at is not None:
            return "category_not_found"
        if parent.type != data.type:
            return "category_type_mismatch"

    def prepare_local_seed(self, db, item):
        parent = db.get(LedgerCategory, item.category_id) if item.category_id else None
        if parent is not None and parent.sync_revision == 0 and parent.deleted_at is not None:
            item.category_id = None
            return True


ADAPTERS = [
    LedgerCategoryAdapter("ledger.category", LedgerCategory, CategoryData,
                          {"name": "name", "type": "type", "icon": "icon"}, 0),
    LedgerTransactionAdapter("ledger.transaction", LedgerTransaction, TransactionData,
        {"categoryId": "category_id", "type": "type", "amount": "amount",
         "description": "description", "merchant": "merchant", "note": "note",
         "occurredAt": "occurred_at"}, 1, parent_type="ledger.category", parent_field="categoryId",
        push_requires_active_parent=False),
]
