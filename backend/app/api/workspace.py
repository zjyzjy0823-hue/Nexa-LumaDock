"""The current user's Personal Workspace."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User, Workspace
from ..security import current_user
from ..utils.time import iso_utc
from ..workspaces import get_personal_workspace


router = APIRouter(prefix="/api/v1/workspace", tags=["workspace"])


class WorkspacePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)

    @field_validator("name")
    @classmethod
    def nonempty_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Name cannot be empty")
        return value


def workspace_json(item: Workspace) -> dict:
    return dict(id=item.id, name=item.name, kind=item.kind,
                createdAt=iso_utc(item.created_at), updatedAt=iso_utc(item.updated_at))


@router.get("")
def current_workspace(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return workspace_json(get_personal_workspace(db, user))


@router.patch("")
def rename_workspace(payload: WorkspacePatch, user: User = Depends(current_user),
                     db: Session = Depends(get_db)):
    workspace = get_personal_workspace(db, user)
    workspace.name = payload.name
    db.commit()
    db.refresh(workspace)
    return workspace_json(workspace)
