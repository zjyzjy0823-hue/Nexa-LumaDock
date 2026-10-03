from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User, UserPreference
from ..security import current_user, hash_password, verify_password
from ..schemas import UserPublic
from ..workspaces import get_personal_workspace
from ..sync.publisher import prepare_write, publish
from ..sync.adapters.personal_state import PreferencesData, project
from pydantic import ValidationError
from .personal_route import SafePersonalRoute

router = APIRouter(prefix="/api/v1", tags=["settings"], route_class=SafePersonalRoute)
DEFAULT_NOTIFICATIONS = {"events": {"agentComplete": True, "deviceOffline": True, "automationFailure": True,
                                     "budgetAlert": False, "securityAlert": True},
                         "channels": {"desktop": True, "email": False, "telegram": False, "webhook": False}}


class SettingsPatch(BaseModel):
    theme: Literal["light", "dark", "system"] | None = None
    language: str | None = Field(default=None, min_length=2, max_length=20)
    timezone: str | None = Field(default=None, min_length=1, max_length=80)
    notifications: dict[str, Any] | None = None
    appearance: dict[str, Any] | None = None
    sync: dict[str, Any] | None = None
    security: dict[str, Any] | None = None


class AccountPatch(BaseModel):
    username: str | None = None
    avatar: str | None = Field(default=None, max_length=500)

    @field_validator("username")
    @classmethod
    def valid_username(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not 3 <= len(value) <= 80 or not all(c.isalnum() or c in "_-" for c in value):
            raise ValueError("Username must have 3-80 letters, numbers, underscores or hyphens")
        return value


class PasswordPatch(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=256)


def preference(db: Session, user: User, *, commit=True) -> UserPreference:
    item = db.scalar(select(UserPreference).where(UserPreference.user_id == user.id))
    if item is None:
        item = UserPreference(user_id=user.id, workspace_id=get_personal_workspace(db, user).id,
                              theme="system", language="zh-CN", timezone="Asia/Shanghai", settings_json={})
        db.add(item)
        db.flush()
        if commit:
            db.commit()
            db.refresh(item)
    return item


def public_settings(item: UserPreference) -> dict:
    extra = item.settings_json or {}
    values = project(PreferencesData, {"theme": item.theme, "language": item.language,
        "timezone": item.timezone, "appearance": extra.get("appearance", {}),
        "notifications": extra.get("notifications", {})})
    values.pop("schemaVersion")
    values.update(sync={key: value for key, value in (extra.get("sync") or {}).items()
                       if key in {"mode", "serverUrl", "automatic", "cellular", "lastSynced"}},
                  security={key: value for key, value in (extra.get("security") or {}).items()
                       if key in {"twoFactor", "requireRemoteConfirmation", "trustedDevices", "activeSessions", "apiTokens"}})
    return values


@router.get("/settings")
def get_settings(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return public_settings(preference(db, user))


@router.patch("/settings")
def patch_settings(payload: SettingsPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    prepare_write(db, user)
    item = preference(db, user, commit=False)
    values = payload.model_dump(exclude_unset=True)
    sync_values = {key: value for key, value in values.items() if key in PreferencesData.model_fields}
    try:
        PreferencesData.model_validate(sync_values)
    except ValidationError:
        raise HTTPException(422, "Invalid personal preferences") from None
    for key in ("theme", "language", "timezone"):
        if key in values:
            if values[key] is None:
                raise HTTPException(422, f"{key} cannot be null")
            setattr(item, key, values.pop(key))
    item.settings_json = {**(item.settings_json or {}), **values}
    if sync_values:
        publish(db, item)
    db.commit()
    db.refresh(item)
    return public_settings(item)


@router.patch("/account", response_model=UserPublic)
def patch_account(payload: AccountPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if payload.username is not None:
        other = db.scalar(select(User).where(func.lower(User.username) == payload.username.lower(), User.id != user.id))
        if other:
            raise HTTPException(409, "Username already exists")
        user.username = payload.username
    if "avatar" in payload.model_fields_set:
        user.avatar = payload.avatar
    db.commit()
    db.refresh(user)
    return user


@router.post("/account/password")
def change_password(payload: PasswordPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(400, "Current password is incorrect")
    user.password_hash = hash_password(payload.new_password)
    db.commit()
    return {"message": "Password changed"}
