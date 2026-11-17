import secrets
from datetime import timedelta
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import core_connection
from ..database import get_db, runtime_config
from ..models import User
from ..schemas import TokenResponse, UserCreate, UserLogin, UserPublic
from ..security import create_access_token, current_user, hash_password, verify_password
from ..sync.notifications import get_coordinator
from ..workspaces import ensure_personal_workspace
from .dashboard import ensure_dashboard

router = APIRouter(prefix="/api/auth", tags=["auth"])
v1_router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
WORKSTATION_TOKEN_TTL = timedelta(days=30)


class WorkstationSetupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["offline", "core"]
    coreUrl: str | None = None
    username: str | None = None
    password: str | None = None
    clientName: str | None = Field(default=None, max_length=120)
    platform: Literal["windows", "macos", "linux", "android", "ios", "web"] | None = None
    appVersion: str | None = Field(default=None, max_length=40)


def _is_workstation() -> bool:
    return runtime_config.mode == "local" and runtime_config.local_workstation


def _workstation_username(raw: str | None) -> str:
    if not raw:
        return "local"
    cleaned = "".join(ch for ch in raw.strip() if ch.isalnum() or ch in "_-")[:80]
    return cleaned if len(cleaned) >= 3 else "local"


@router.get("/status")
@v1_router.get("/status")
def auth_status(db: Session = Depends(get_db)):
    workstation = _is_workstation()
    if not workstation:
        return {
            "mode": runtime_config.mode,
            "workstation": False,
            "setupRequired": False,
            "allowRegistration": runtime_config.allow_registration,
        }
    user_count = db.scalar(select(func.count(User.id))) or 0
    return {
        "mode": runtime_config.mode,
        "workstation": True,
        "setupRequired": user_count == 0,
        "allowRegistration": runtime_config.allow_registration,
    }


@router.post("/workstation/session", response_model=TokenResponse)
@v1_router.post("/workstation/session", response_model=TokenResponse)
def workstation_session(db: Session = Depends(get_db)):
    if not _is_workstation():
        raise HTTPException(404, "Endpoint requires local workstation mode")
    users = db.scalars(select(User).order_by(User.id).limit(2)).all()
    if not users:
        raise HTTPException(404, "Workstation setup required")
    if len(users) > 1:
        raise HTTPException(409, "Multiple local accounts exist")
    return TokenResponse(access_token=create_access_token(users[0].id, WORKSTATION_TOKEN_TTL))


@router.post("/workstation/setup", response_model=TokenResponse, status_code=201)
@v1_router.post("/workstation/setup", response_model=TokenResponse, status_code=201)
def workstation_setup(payload: WorkstationSetupRequest, db: Session = Depends(get_db)):
    if not _is_workstation():
        raise HTTPException(404, "Endpoint requires local workstation mode")
    if (db.scalar(select(func.count(User.id))) or 0) > 0:
        raise HTTPException(409, "Workstation is already initialized")
    if payload.mode == "core":
        if (not payload.coreUrl or not payload.username or not payload.password
                or not payload.clientName or not payload.platform or not payload.appVersion):
            raise HTTPException(422, "Core connection fields are required")

    username = _workstation_username(payload.username if payload.mode == "core" else "local")
    user = User(
        username=username,
        email=f"{uuid4().hex}@studiolo.local",
        password_hash=hash_password(secrets.token_urlsafe(32)),
    )
    connected = False
    workspace = None
    try:
        db.add(user)
        db.flush()
        workspace = ensure_personal_workspace(db, user)
        ensure_dashboard(db, user, commit=False)
        if payload.mode == "core":
            core_connection.disconnect(user.id)
            core_connection.connect(
                user.id,
                payload.coreUrl,
                payload.username.strip(),
                payload.password,
                payload.clientName.strip(),
                payload.platform,
                payload.appVersion.strip(),
            )
            connected = True
        db.commit()
    except Exception:
        db.rollback()
        if connected and user.id is not None:
            core_connection.disconnect(user.id)
        raise

    if connected and workspace is not None:
        coordinator = get_coordinator(db.get_bind())
        if coordinator is not None:
            coordinator.connection_changed(user.id, workspace.id, True)
    return TokenResponse(access_token=create_access_token(user.id, WORKSTATION_TOKEN_TTL))


@router.post("/register", response_model=TokenResponse, status_code=201)
@v1_router.post("/register", response_model=TokenResponse, status_code=201)
def register(payload: UserCreate, db: Session = Depends(get_db)):
    if not runtime_config.allow_registration:
        raise HTTPException(status_code=403, detail="Public registration is disabled")
    if db.scalar(select(User).where(func.lower(User.username) == payload.username.lower())):
        raise HTTPException(409, detail="Username already exists")
    user = User(username=payload.username, email=f"{uuid4().hex}@studiolo.local", password_hash=hash_password(payload.password))
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
        raise HTTPException(401, detail="Invalid username or password")
    return TokenResponse(access_token=create_access_token(user.id))


@router.get("/me", response_model=UserPublic)
@v1_router.get("/me", response_model=UserPublic)
def me(user: User = Depends(current_user)):
    return user
