from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from ..database import get_db, runtime_config
from ..models import LocalSyncState, User
from ..security import current_user
from ..sync.adapters import seed_version
from ..sync.local import seed_local_ledger_queue
from ..workspaces import get_personal_workspace
from ..services.ledger import (
    CategoryInput,
    CategoryPatch,
    TransactionInput,
    TransactionPatch,
)
from ..services import ledger as service


def ensure_local_ledger_ready(
    user: User = Depends(current_user), db: Session = Depends(get_db)
) -> None:
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


router = APIRouter(
    prefix="/api/v1/ledger",
    tags=["ledger"],
    dependencies=[Depends(ensure_local_ledger_ready)],
)


@router.get("/categories")
def list_categories(user: User = Depends(current_user), db: Session = Depends(get_db)):
    result = service.list_categories(user=user, db=db)
    return result


@router.post("/categories", status_code=201)
def create_category(
    payload: CategoryInput,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    try:
        result = service.create_category(payload=payload, user=user, db=db)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return result


@router.patch("/categories/{id}")
def patch_category(
    id: str,
    payload: CategoryPatch,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    try:
        result = service.patch_category(id=id, payload=payload, user=user, db=db)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return result


@router.delete("/categories/{id}", status_code=204)
def delete_category(
    id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    try:
        result = service.delete_category(id=id, user=user, db=db)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return result


@router.get("/transactions")
def list_transactions(
    month: str | None = Query(default=None, pattern="^\\d{4}-(0[1-9]|1[0-2])$"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    result = service.list_transactions(month=month, user=user, db=db)
    return result


@router.post("/transactions", status_code=201)
def create_transaction(
    payload: TransactionInput,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    try:
        result = service.create_transaction(payload=payload, user=user, db=db)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return result


@router.get("/transactions/{id}")
def get_transaction(
    id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    result = service.get_transaction(id=id, user=user, db=db)
    return result


@router.get("/categories/{id}")
def get_category(
    id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    result = service.get_category(id=id, user=user, db=db)
    return result


@router.patch("/transactions/{id}")
def patch_transaction(
    id: str,
    payload: TransactionPatch,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    try:
        result = service.patch_transaction(id=id, payload=payload, user=user, db=db)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return result


@router.delete("/transactions/{id}", status_code=204)
def delete_transaction(
    id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    try:
        result = service.delete_transaction(id=id, user=user, db=db)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return result


@router.get("/summary")
def summary(
    month: str | None = Query(default=None, pattern="^\\d{4}-(0[1-9]|1[0-2])$"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    result = service.summary(month=month, user=user, db=db)
    return result
