import hashlib
import secrets
from datetime import timedelta
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import ApiKey, User, utcnow
from ..schemas import ApiKeyCreate, ApiKeyCreated, ApiKeyPublic, ApiKeyStatusUpdate
from ..security import current_user
from ..utils.time import aware_utc

router = APIRouter(prefix="/api/api-keys", tags=["api-keys"])


def public_key(item: ApiKey) -> ApiKeyPublic:
    expires_at = aware_utc(item.expires_at)
    status = "expired" if expires_at and expires_at <= utcnow() else "active" if item.is_active else "inactive"
    return ApiKeyPublic(
        id=item.id, name=item.name, status=status, masked_key=f"sk_live_••••{item.last4}",
        scopes=item.scopes, created_at=aware_utc(item.created_at), last_used_at=aware_utc(item.last_used_at),
        expires_at=expires_at,
    )


@router.get("", response_model=list[ApiKeyPublic])
def list_api_keys(user: User = Depends(current_user), db: Session = Depends(get_db)):
    items = db.scalars(select(ApiKey).where(ApiKey.user_id == user.id).order_by(ApiKey.created_at.desc(), ApiKey.id))
    return [public_key(item) for item in items]


@router.post("", response_model=ApiKeyCreated, status_code=201)
def create_api_key(payload: ApiKeyCreate, response: Response, user: User = Depends(current_user), db: Session = Depends(get_db)):
    secret = f"sk_live_{secrets.token_urlsafe(32)}"
    item = ApiKey(
        id=str(uuid4()), user_id=user.id, token_hash=hashlib.sha256(secret.encode()).hexdigest(),
        name=payload.name, last4=secret[-4:], scopes=payload.scopes, is_active=True,
        expires_at=utcnow() + timedelta(days=payload.expires_in_days) if payload.expires_in_days else None,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    response.headers["Cache-Control"] = "no-store"
    return ApiKeyCreated(**public_key(item).model_dump(), secret=secret)


@router.put("/{id}/status", response_model=ApiKeyPublic)
def set_api_key_status(id: str, payload: ApiKeyStatusUpdate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = db.scalar(select(ApiKey).where(ApiKey.id == id, ApiKey.user_id == user.id))
    if item is None:
        raise HTTPException(404, "API Key not found")
    if payload.status == "active" and item.expires_at and aware_utc(item.expires_at) <= utcnow():
        raise HTTPException(409, "Expired API Key cannot be activated")
    item.is_active = payload.status == "active"
    db.commit()
    db.refresh(item)
    return public_key(item)
