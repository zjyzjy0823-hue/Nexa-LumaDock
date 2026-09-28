"""Manage installation identity records using the existing user JWT."""

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..client_credentials import issue_credential
from ..models import Client, User
from ..runtime_mode import require_core_mode
from ..security import current_user
from ..utils.time import iso_utc
from ..workspaces import get_personal_workspace


router = APIRouter(prefix="/api/v1/clients", tags=["clients"])
Platform = Literal["windows", "macos", "linux", "android", "ios", "web"]


class ClientRegistration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    installationId: UUID
    name: str = Field(min_length=1, max_length=120)
    platform: Platform
    appVersion: str = Field(min_length=1, max_length=40)

    @field_validator("name", "appVersion")
    @classmethod
    def nonempty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Value cannot be empty")
        return value


def client_json(item: Client) -> dict:
    return dict(id=item.id, installationId=item.installation_id, name=item.name,
                platform=item.platform, appVersion=item.app_version,
                createdAt=iso_utc(item.created_at), updatedAt=iso_utc(item.updated_at),
                lastSeenAt=iso_utc(item.last_seen_at), revokedAt=iso_utc(item.revoked_at))


def owned_client(db: Session, user: User, id: str) -> Client:
    workspace_id = get_personal_workspace(db, user).id
    item = db.scalar(select(Client).where(Client.id == id, Client.workspace_id == workspace_id))
    if item is None:
        raise HTTPException(404, "Client not found")
    return item


@router.get("")
def list_clients(user: User = Depends(current_user), db: Session = Depends(get_db)):
    workspace_id = get_personal_workspace(db, user).id
    return [client_json(item) for item in db.scalars(select(Client).where(
        Client.workspace_id == workspace_id).order_by(Client.created_at.desc(), Client.id))]


@router.post("", status_code=201)
def register_client(payload: ClientRegistration, response: Response,
                    user: User = Depends(current_user), db: Session = Depends(get_db)):
    workspace_id = get_personal_workspace(db, user).id
    installation_id = str(payload.installationId)
    item = db.scalar(select(Client).where(Client.workspace_id == workspace_id,
                                         Client.installation_id == installation_id))
    if item is not None and item.revoked_at is not None:
        raise HTTPException(409, "Client is revoked")
    if item is None:
        item = Client(id=str(uuid4()), workspace_id=workspace_id, installation_id=installation_id,
                      name=payload.name, platform=payload.platform, app_version=payload.appVersion)
        db.add(item)
    else:
        response.status_code = 200
        item.name = payload.name
        item.platform = payload.platform
        item.app_version = payload.appVersion
    item.last_seen_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(item)
    return client_json(item)


def credential_response(item: Client, credential: str, response: Response) -> dict:
    response.headers["Cache-Control"] = "no-store"
    return {"client": {"id": item.id, "installationId": item.installation_id,
                       "workspaceId": item.workspace_id, "name": item.name,
                       "platform": item.platform, "appVersion": item.app_version},
            "credential": credential, "tokenLast4": item.token_last4,
            "tokenCreatedAt": iso_utc(item.token_created_at)}


@router.post("/enroll", status_code=201)
def enroll_client(payload: ClientRegistration, response: Response,
                  _core: None = Depends(require_core_mode),
                  user: User = Depends(current_user), db: Session = Depends(get_db)):
    workspace_id = get_personal_workspace(db, user).id
    installation_id = str(payload.installationId)
    item = db.scalar(select(Client).where(Client.workspace_id == workspace_id,
                                         Client.installation_id == installation_id))
    if item is not None and item.revoked_at is not None:
        raise HTTPException(409, "Client is revoked")
    if item is not None and item.token_hash is not None:
        raise HTTPException(409, "Client is already enrolled")
    if item is None:
        item = Client(id=str(uuid4()), workspace_id=workspace_id, installation_id=installation_id,
                      name=payload.name, platform=payload.platform, app_version=payload.appVersion)
        db.add(item)
    else:
        item.name = payload.name
        item.platform = payload.platform
        item.app_version = payload.appVersion
    item.last_seen_at = datetime.now(timezone.utc)
    credential = issue_credential(item)
    db.commit()
    db.refresh(item)
    return credential_response(item, credential, response)


@router.post("/{id}/credential")
def rotate_client_credential(id: str, response: Response,
                             _core: None = Depends(require_core_mode),
                             user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = owned_client(db, user, id)
    if item.revoked_at is not None:
        raise HTTPException(409, "Client is revoked")
    credential = issue_credential(item)
    db.commit()
    db.refresh(item)
    return credential_response(item, credential, response)


@router.get("/{id}")
def get_client(id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return client_json(owned_client(db, user, id))


@router.post("/{id}/revoke")
def revoke_client(id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = owned_client(db, user, id)
    changed = False
    if item.revoked_at is None:
        item.revoked_at = datetime.now(timezone.utc)
        changed = True
    if item.token_hash is not None:
        item.token_hash = None
        changed = True
    if changed:
        db.commit()
        db.refresh(item)
    return client_json(item)
