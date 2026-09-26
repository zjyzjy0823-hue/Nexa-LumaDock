from fastapi import APIRouter, Depends

from ...mock_data import AGENTS
from ...models import User
from ...security import current_user

router = APIRouter(prefix="/api/agents", tags=["agents"])


@router.get("")
def list_agents(_user: User = Depends(current_user)):
    return AGENTS
