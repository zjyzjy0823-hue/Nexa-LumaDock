from fastapi import APIRouter, Depends

from ...mock_data import DEVICES
from ...models import User
from ...security import current_user

router = APIRouter(prefix="/api/devices", tags=["devices"])


@router.get("")
def list_devices(_user: User = Depends(current_user)):
    return DEVICES
