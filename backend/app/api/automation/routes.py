from fastapi import APIRouter, Depends

from ...mock_data import AUTOMATION
from ...models import User
from ...security import read_user_for

router = APIRouter(prefix="/api/automation", tags=["automation"])


@router.get("")
def list_automation(_user: User = Depends(read_user_for("Automation"))):
    return AUTOMATION
