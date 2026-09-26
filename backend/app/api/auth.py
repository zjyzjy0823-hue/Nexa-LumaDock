from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..schemas import TokenResponse, UserCreate, UserLogin, UserPublic
from ..security import create_access_token, current_user, hash_password, verify_password
from .dashboard import ensure_dashboard

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=201)
def register(payload: UserCreate, db: Session = Depends(get_db)):
    if db.scalar(select(User).where(or_(User.username == payload.username, User.email == payload.email))):
        raise HTTPException(status_code=409, detail="Username or email already exists")
    user = User(username=payload.username, email=payload.email, password_hash=hash_password(payload.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    ensure_dashboard(db, user)
    return TokenResponse(access_token=create_access_token(user.id))


@router.post("/login", response_model=TokenResponse)
def login(payload: UserLogin, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == payload.email.strip().lower()))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return TokenResponse(access_token=create_access_token(user.id))


@router.get("/me", response_model=UserPublic)
def me(user: User = Depends(current_user)):
    return user
