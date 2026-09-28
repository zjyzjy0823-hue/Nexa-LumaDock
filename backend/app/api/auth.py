from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db, runtime_config
from ..models import User
from ..schemas import TokenResponse, UserCreate, UserLogin, UserPublic
from ..security import create_access_token, current_user, hash_password, verify_password
from ..workspaces import ensure_personal_workspace
from .dashboard import ensure_dashboard

router = APIRouter(prefix="/api/auth", tags=["auth"])
v1_router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=201)
@v1_router.post("/register", response_model=TokenResponse, status_code=201)
def register(payload: UserCreate, db: Session = Depends(get_db)):
    if not runtime_config.allow_registration:
        raise HTTPException(status_code=403, detail="Public registration is disabled")
    if db.scalar(select(User).where(func.lower(User.username) == payload.username.lower())):
        raise HTTPException(status_code=409, detail="Username already exists")
    user = User(username=payload.username, email=f"{uuid4().hex}@nexa.local", password_hash=hash_password(payload.password))
    try:
        db.add(user)
        db.flush()
        ensure_personal_workspace(db, user)
        ensure_dashboard(db, user, commit=False)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return TokenResponse(access_token=create_access_token(user.id))


@router.post("/login", response_model=TokenResponse)
@v1_router.post("/login", response_model=TokenResponse)
def login(payload: UserLogin, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(func.lower(User.username) == payload.username.strip().lower()))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    return TokenResponse(access_token=create_access_token(user.id))


@router.get("/me", response_model=UserPublic)
@v1_router.get("/me", response_model=UserPublic)
def me(user: User = Depends(current_user)):
    return user
