"""Local user's bridge to Core enrollment; the WebView never contacts Core."""

from typing import Literal

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel, ConfigDict, Field

from .. import core_connection
from ..models import User
from ..runtime_mode import require_local_mode
from ..security import current_user
from ..database import get_db
from ..workspaces import get_personal_workspace
from ..sync.notifications import get_coordinator


router = APIRouter(prefix="/api/v1/core", tags=["core-connection"],
                   dependencies=[Depends(require_local_mode)])


class ConnectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    coreUrl: str
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)
    clientName: str = Field(min_length=1, max_length=120)
    platform: Literal["windows", "macos", "linux", "android", "ios", "web"]
    appVersion: str = Field(min_length=1, max_length=40)


@router.post("/connect")
def connect(payload: ConnectRequest, user: User = Depends(current_user), db: Session = Depends(get_db)):
    user_id = user.id
    workspace_id = get_personal_workspace(db, user).id
    db.rollback()
    result = core_connection.connect(user_id, payload.coreUrl, payload.username, payload.password,
                                     payload.clientName, payload.platform, payload.appVersion)
    coordinator = get_coordinator(db.get_bind())
    if coordinator is not None:
        coordinator.connection_changed(user_id, workspace_id, True)
    return result


@router.get("/connection")
def connection(user: User = Depends(current_user)):
    return core_connection.public_connection(core_connection.load_connection(user.id))


@router.post("/connection/test")
def connection_test(user: User = Depends(current_user)):
    return core_connection.test_connection(user.id)


@router.delete("/connection")
def disconnect(user: User = Depends(current_user), db: Session = Depends(get_db)):
    user_id = user.id
    workspace_id = get_personal_workspace(db, user).id
    db.rollback()
    result = core_connection.disconnect(user_id)
    coordinator = get_coordinator(db.get_bind())
    if coordinator is not None:
        coordinator.connection_changed(user_id, workspace_id, False)
    return result
