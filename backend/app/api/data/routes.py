from fastapi import APIRouter, Depends

from ...mock_data import DATA
from ...models import User
from ...security import current_user

router = APIRouter(prefix="/api/data", tags=["data"])


@router.get("")
def get_data(_user: User = Depends(current_user)):
    return DATA
