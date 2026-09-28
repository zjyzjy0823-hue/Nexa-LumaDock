"""Local user's bridge to Core enrollment; the WebView never contacts Core."""

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from .. import core_connection
from ..models import User
from ..runtime_mode import require_local_mode
from ..security import current_user


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
def connect(payload: ConnectRequest, user: User = Depends(current_user)):
    return core_connection.connect(user.id, payload.coreUrl, payload.username, payload.password,
                                   payload.clientName, payload.platform, payload.appVersion)


@router.get("/connection")
def connection(user: User = Depends(current_user)):
    return core_connection.public_connection(core_connection.load_connection(user.id))


@router.post("/connection/test")
def connection_test(user: User = Depends(current_user)):
    return core_connection.test_connection(user.id)


@router.delete("/connection")
def disconnect(user: User = Depends(current_user)):
    return core_connection.disconnect(user.id)
