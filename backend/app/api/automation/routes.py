from fastapi import APIRouter, Depends

from ...mock_data import AUTOMATION
from ...models import User
from ...security import current_user

router = APIRouter(prefix="/api/automation", tags=["automation"])


@router.get("")
def list_automation(_user: User = Depends(current_user)):
    return AUTOMATION
