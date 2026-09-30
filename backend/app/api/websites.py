from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import User
from ..security import current_user
from ..services.websites import WebsiteInput, WebsitePatch, CategoryInput, CategoryPatch
from ..services import websites as service

router = APIRouter(prefix="/api/v1", tags=["websites"])


@router.get("/websites")
def list_websites(
    categoryId: str | None = None,
    search: str | None = None,
    favorite: bool | None = None,
    sort: str = Query("order", pattern="^(order|name|createdAt|updatedAt|recent)$"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    result = service.list_websites(
        categoryId=categoryId,
        search=search,
        favorite=favorite,
        sort=sort,
        user=user,
        db=db,
    )
    return result


@router.post("/websites", status_code=201)
def create_website(
    payload: WebsiteInput,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    try:
        result = service.create_website(payload=payload, user=user, db=db)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return result


@router.get("/websites/{id}")
def get_website(
    id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    result = service.get_website(id=id, user=user, db=db)
    return result


@router.post("/websites/{id}/visit")
def visit_website(
    id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    try:
        result = service.visit_website(id=id, user=user, db=db)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return result


@router.patch("/websites/{id}")
def update_website(
    id: str,
    payload: WebsitePatch,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    try:
        result = service.update_website(id=id, payload=payload, user=user, db=db)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return result


@router.delete("/websites/{id}", status_code=204)
def delete_website(
    id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    try:
        result = service.delete_website(id=id, user=user, db=db)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return result


@router.get("/website-categories")
def list_categories(user: User = Depends(current_user), db: Session = Depends(get_db)):
    result = service.list_categories(user=user, db=db)
    return result


@router.post("/website-categories", status_code=201)
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


@router.patch("/website-categories/{id}")
def update_category(
    id: str,
    payload: CategoryPatch,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    try:
        result = service.update_category(id=id, payload=payload, user=user, db=db)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return result


@router.delete("/website-categories/{id}", status_code=204)
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
