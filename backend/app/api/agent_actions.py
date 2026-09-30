from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Agent
from ..runtime_mode import require_local_mode
from ..security import agent_from_token, bearer
from ..actions.registry import REGISTRY
from ..actions.service import execute, error


def local_only():
    try:
        require_local_mode()
    except HTTPException:
        raise error(404, "local_only") from None


def authenticated(credentials=Depends(bearer), db: Session = Depends(get_db)):
    try:
        agent = agent_from_token(credentials, db)
    except HTTPException:
        raise error(401, "unauthorized") from None
    if not agent.enabled:
        raise error(403, "agent_disabled")
    return agent


router = APIRouter(
    prefix="/api/agent/actions",
    tags=["agent-actions"],
    dependencies=[Depends(local_only)],
)


@router.post("/execute")
async def execute_action(
    request: Request,
    agent: Agent = Depends(authenticated),
    db: Session = Depends(get_db),
):
    try:
        raw = await request.json()
    except ValueError:
        raise error(422, "validation_error") from None
    return execute(db, agent, raw)


@router.get("/catalog")
def catalog(agent: Agent = Depends(authenticated)):
    from ..main import APP_VERSION

    return {
        "connected": True,
        "agentId": agent.id,
        "agentName": agent.name,
        "dataScopes": agent.data_scopes or [],
        "version": APP_VERSION,
        "actions": [
            a.name for a in REGISTRY.values() if a.scope in (agent.data_scopes or [])
        ],
    }
