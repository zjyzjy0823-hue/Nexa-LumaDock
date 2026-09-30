from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ...database import get_db
from ...models import User
from ...security import current_user, read_user_for
from ...services.data import CollectionInput, CollectionPatch, RecordInput, RecordPatch
from ...services import data as service

router = APIRouter(prefix="/api/data", tags=["data"])
v1_router = APIRouter(prefix="/api/v1/data", tags=["data"])


@router.get("")
def legacy_data(
    user: User = Depends(read_user_for("Data")), db: Session = Depends(get_db)
):
    result = service.legacy_data(user=user, db=db)
    return result


@v1_router.get("/collections")
def list_collections(user: User = Depends(current_user), db: Session = Depends(get_db)):
    result = service.list_collections(user=user, db=db)
    return result


@v1_router.post("/collections", status_code=201)
def create_collection(
    payload: CollectionInput,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    try:
        result = service.create_collection(payload=payload, user=user, db=db)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return result


@v1_router.get("/collections/{id}")
def get_collection(
    id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    result = service.get_collection(id=id, user=user, db=db)
    return result


@v1_router.patch("/collections/{id}")
def patch_collection(
    id: str,
    payload: CollectionPatch,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    try:
        result = service.patch_collection(id=id, payload=payload, user=user, db=db)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return result


@v1_router.delete("/collections/{id}", status_code=204)
def delete_collection(
    id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    try:
        result = service.delete_collection(id=id, user=user, db=db)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return result


@v1_router.get("/collections/{id}/records")
def list_records(
    id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    result = service.list_records(id=id, user=user, db=db)
    return result


@v1_router.post("/collections/{id}/records", status_code=201)
def create_record(
    id: str,
    payload: RecordInput,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    try:
        result = service.create_record(id=id, payload=payload, user=user, db=db)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return result


@v1_router.patch("/records/{id}")
def patch_record(
    id: str,
    payload: RecordPatch,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    try:
        result = service.patch_record(id=id, payload=payload, user=user, db=db)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return result


@v1_router.get("/records/{id}")
def get_record(
    id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    result = service.get_record(id=id, user=user, db=db)
    return result


@v1_router.delete("/records/{id}", status_code=204)
def delete_record(
    id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    try:
        result = service.delete_record(id=id, user=user, db=db)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return result
