"""Shared task creation, leaving transaction ownership to the caller."""
from uuid import uuid4
from fastapi import HTTPException
from sqlalchemy import select
from ..models import Agent, AgentTask, AgentEvent


def create_task(db, user, agent_id, title, description="", *, workspace_id=None):
    agent = db.scalar(select(Agent).where(Agent.id == agent_id, Agent.user_id == user.id))
    if agent is None or (workspace_id is not None and agent.workspace_id != workspace_id):
        raise HTTPException(404, "Agent not found")
    if not agent.enabled:
        raise HTTPException(409, "Agent is paused")
    title, description = title.strip(), description.strip()
    if not title or len(title) > 160 or len(description) > 500:
        raise HTTPException(422, "Invalid task")
    item = AgentTask(id=str(uuid4()), agent_id=agent.id, title=title, description=description)
    db.add(item)
    db.add(AgentEvent(id=str(uuid4()), agent_id=agent.id, level="info", message="任务已创建"))
    db.flush()
    return item
