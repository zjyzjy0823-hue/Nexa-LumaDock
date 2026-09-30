"""Trusted ownership derived from authentication, never business arguments."""

from dataclasses import dataclass
from fastapi import HTTPException
from ..models import Workspace
from ..workspaces import get_personal_workspace


@dataclass(frozen=True)
class BusinessOwner:
    id: int
    workspace_id: str


def owner_workspace(db, owner):
    if isinstance(owner, BusinessOwner):
        workspace = db.get(Workspace, owner.workspace_id)
        if workspace is None or workspace.owner_user_id != owner.id:
            raise HTTPException(404, "Workspace not found")
        return workspace.id
    return get_personal_workspace(db, owner).id
