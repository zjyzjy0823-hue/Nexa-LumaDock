"""Resolve the single Personal Workspace used by the current API."""

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import User, Workspace


def get_personal_workspace(db: Session, user: User) -> Workspace:
    workspace = db.scalar(select(Workspace).where(
        Workspace.owner_user_id == user.id, Workspace.kind == "personal"
    ).order_by(Workspace.created_at, Workspace.id))
    if workspace is None:
        raise RuntimeError("Personal Workspace is missing for user")
    return workspace


def ensure_personal_workspace(db: Session, user: User) -> Workspace:
    workspace = db.scalar(select(Workspace).where(
        Workspace.owner_user_id == user.id, Workspace.kind == "personal"
    ).order_by(Workspace.created_at, Workspace.id))
    if workspace is None:
        workspace = Workspace(id=str(uuid4()), owner_user_id=user.id, name="个人工作区", kind="personal")
        db.add(workspace)
        db.flush()
    return workspace
