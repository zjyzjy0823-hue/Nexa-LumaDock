"""Nexa Client self-service endpoints authenticated by Core credential."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Client, utcnow
from ..security import client_from_token


router = APIRouter(prefix="/api/v1/client", tags=["client-runtime"])


class Heartbeat(BaseModel):
    model_config = ConfigDict(extra="forbid")

    appVersion: str | None = Field(default=None, min_length=1, max_length=40)


def client_self(item: Client) -> dict:
    return {"clientId": item.id, "workspaceId": item.workspace_id,
            "installationId": item.installation_id, "name": item.name,
            "platform": item.platform, "appVersion": item.app_version,
            "revoked": False}


@router.get("/me")
def me(item: Client = Depends(client_from_token)):
    return client_self(item)


@router.post("/heartbeat")
def heartbeat(payload: Heartbeat, item: Client = Depends(client_from_token),
              db: Session = Depends(get_db)):
    item.last_seen_at = utcnow()
    if payload.appVersion is not None:
        item.app_version = payload.appVersion.strip()
    db.commit()
    db.refresh(item)
    return client_self(item)
