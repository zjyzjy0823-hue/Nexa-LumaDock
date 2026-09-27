from fastapi import APIRouter, Depends

from ...mock_data import DATA
from ...models import User
from ...security import read_user_for

router = APIRouter(prefix="/api/data", tags=["data"])


@router.get("")
def get_data(_user: User = Depends(read_user_for("Data"))):
    return DATA
