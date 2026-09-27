from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...database import get_db
from ...models import Device, User
from ...security import current_user, read_user_for

router = APIRouter(prefix="/api/v1/devices", tags=["devices"])
legacy_router = APIRouter(prefix="/api/devices", tags=["devices"])

DeviceKind = Literal["desktop", "mac", "phone", "tablet", "server", "nas"]


class DeviceInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    system: str = Field(min_length=1, max_length=120)
    ip: str = Field(min_length=1, max_length=120)
    kind: DeviceKind = "desktop"
    location: str = Field(default="", max_length=120)

    @field_validator("name", "system", "ip")
    @classmethod
    def nonempty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Value cannot be empty")
        return value


class DevicePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    system: str | None = Field(default=None, min_length=1, max_length=120)
    ip: str | None = Field(default=None, min_length=1, max_length=120)
    kind: DeviceKind | None = None
    location: str | None = Field(default=None, max_length=120)


class DeviceHeartbeat(BaseModel):
    cpu: int = Field(ge=0, le=100)
    memory: int = Field(ge=0, le=100)
    disk: int = Field(ge=0, le=100)
    battery: int | None = Field(default=None, ge=0, le=100)


def aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def online(item: Device) -> bool:
    return bool(item.last_seen_at and (datetime.now(timezone.utc) - aware(item.last_seen_at)).total_seconds() < 120)


def last_seen(item: Device) -> str:
    if not item.last_seen_at:
        return "从未连接"
    seconds = max(0, int((datetime.now(timezone.utc) - aware(item.last_seen_at)).total_seconds()))
    if seconds < 60:
        return "刚刚"
    if seconds < 3600:
        return f"{seconds // 60} 分钟前"
    if seconds < 86400:
        return f"{seconds // 3600} 小时前"
    return f"{seconds // 86400} 天前"


def device_json(item: Device) -> dict:
    return dict(id=item.id, name=item.name, system=item.system, ip=item.ip, kind=item.kind,
                location=item.location, online=online(item), cpu=item.cpu, memory=item.memory,
                disk=item.disk, battery=item.battery, activity=item.activity_json or [],
                lastSeen=last_seen(item), lastSeenAt=item.last_seen_at.isoformat() if item.last_seen_at else None,
                createdAt=item.created_at.isoformat(), updatedAt=item.updated_at.isoformat())


def owned_device(db: Session, user: User, id: str) -> Device:
    item = db.scalar(select(Device).where(Device.id == id, Device.user_id == user.id))
    if item is None:
        raise HTTPException(404, "Device not found")
    return item


def list_for_user(user: User, db: Session):
    return [device_json(item) for item in db.scalars(select(Device).where(
        Device.user_id == user.id).order_by(Device.created_at.desc(), Device.id))]


@router.get("")
def list_devices(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return list_for_user(user, db)


@legacy_router.get("")
def list_devices_with_key(user: User = Depends(read_user_for("Devices")), db: Session = Depends(get_db)):
    return list_for_user(user, db)


@router.post("", status_code=201)
def create_device(payload: DeviceInput, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = Device(id=str(uuid4()), user_id=user.id, **payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return device_json(item)


@router.get("/{id}")
def get_device(id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return device_json(owned_device(db, user, id))


@router.patch("/{id}")
def update_device(id: str, payload: DevicePatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = owned_device(db, user, id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        if value is None:
            raise HTTPException(422, f"{key} cannot be null")
        if isinstance(value, str):
            value = value.strip()
        if key in ("name", "system", "ip") and not value:
            raise HTTPException(422, f"{key} cannot be empty")
        setattr(item, key, value)
    db.commit()
    db.refresh(item)
    return device_json(item)


@router.delete("/{id}", status_code=204)
def delete_device(id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.delete(owned_device(db, user, id))
    db.commit()


@router.post("/{id}/heartbeat")
def heartbeat(id: str, payload: DeviceHeartbeat, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = owned_device(db, user, id)
    item.cpu = payload.cpu
    item.memory = payload.memory
    item.disk = payload.disk
    item.battery = payload.battery
    item.activity_json = [*(item.activity_json or []), payload.cpu][-14:]
    item.last_seen_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(item)
    return device_json(item)
