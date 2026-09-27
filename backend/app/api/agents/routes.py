from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...database import get_db
from ...models import Agent, AgentEvent, AgentTask, User
from ...security import current_user, read_user_for

router = APIRouter(prefix="/api/v1/agents", tags=["agents"])
legacy_router = APIRouter(prefix="/api/agents", tags=["agents"])
Avatar = Literal["spark", "orbit", "wave", "chart", "sun"]
TaskStatus = Literal["queued", "running", "completed"]


class AgentInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    role: str = Field(default="自定义助理", max_length=120)
    description: str = Field(default="", max_length=500)
    model: str = Field(default="未配置", max_length=120)
    workspace: str = Field(default="个人工作区", max_length=120)
    avatar: Avatar = "spark"

    @field_validator("name")
    @classmethod
    def nonempty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Name cannot be empty")
        return value


class AgentPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    role: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    model: str | None = Field(default=None, max_length=120)
    workspace: str | None = Field(default=None, max_length=120)
    avatar: Avatar | None = None
    enabled: bool | None = None


class TaskInput(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=500)

    @field_validator("title")
    @classmethod
    def nonempty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Title cannot be empty")
        return value


class TaskPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=500)
    status: TaskStatus | None = None


class AgentHeartbeat(BaseModel):
    status: Literal["running", "idle"] = "idle"


def aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def elapsed(value: datetime | None) -> str:
    if value is None:
        return "尚未连接"
    seconds = max(0, int((datetime.now(timezone.utc) - aware(value)).total_seconds()))
    if seconds < 60:
        return "刚刚"
    if seconds < 3600:
        return f"{seconds // 60} 分钟前"
    if seconds < 86400:
        return f"{seconds // 3600} 小时前"
    return f"{seconds // 86400} 天前"


def effective_status(item: Agent) -> str:
    if not item.enabled:
        return "offline"
    if item.last_seen_at and (datetime.now(timezone.utc) - aware(item.last_seen_at)).total_seconds() < 120:
        return item.runtime_status
    return "idle"


def task_json(item: AgentTask) -> dict:
    return dict(id=item.id, title=item.title, description=item.description, status=item.status,
                time=elapsed(item.created_at), createdAt=item.created_at.isoformat(),
                updatedAt=item.updated_at.isoformat())


def agent_json(item: Agent, db: Session) -> dict:
    tasks = list(db.scalars(select(AgentTask).where(AgentTask.agent_id == item.id).order_by(
        AgentTask.created_at.desc(), AgentTask.id)))
    events = list(db.scalars(select(AgentEvent).where(AgentEvent.agent_id == item.id).order_by(
        AgentEvent.created_at.desc(), AgentEvent.id).limit(50)))
    completed = sum(task.status == "completed" for task in tasks)
    return dict(id=item.id, name=item.name, role=item.role, description=item.description,
                status=effective_status(item), enabled=item.enabled, avatar=item.avatar,
                model=item.model, workspace=item.workspace,
                successRate=f"{round(completed / len(tasks) * 100)}%" if tasks else "—",
                callsToday=0, tasksToday=sum(aware(task.created_at).date() == datetime.now(timezone.utc).date() for task in tasks),
                uptime=elapsed(item.last_seen_at) if item.last_seen_at else "尚未连接",
                lastActive=elapsed(item.last_seen_at), lastSeenAt=item.last_seen_at.isoformat() if item.last_seen_at else None,
                capabilities=[], tasks=[task_json(task) for task in tasks],
                logs=[dict(time=event.created_at.strftime("%H:%M"), level=event.level, message=event.message) for event in events],
                apiCalls=[], createdAt=item.created_at.isoformat(), updatedAt=item.updated_at.isoformat())


def owned_agent(db: Session, user: User, id: str) -> Agent:
    item = db.scalar(select(Agent).where(Agent.id == id, Agent.user_id == user.id))
    if item is None:
        raise HTTPException(404, "Agent not found")
    return item


def add_event(db: Session, agent_id: str, message: str):
    db.add(AgentEvent(id=str(uuid4()), agent_id=agent_id, level="info", message=message))


@router.get("")
def list_agents(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return agents_for_user(user, db)


@legacy_router.get("")
def list_agents_with_key(user: User = Depends(read_user_for("Agents")), db: Session = Depends(get_db)):
    return agents_for_user(user, db)


def agents_for_user(user: User, db: Session):
    return [agent_json(item, db) for item in db.scalars(select(Agent).where(
        Agent.user_id == user.id).order_by(Agent.created_at.desc(), Agent.id))]


@router.post("", status_code=201)
def create_agent(payload: AgentInput, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = Agent(id=str(uuid4()), user_id=user.id, **payload.model_dump())
    db.add(item)
    add_event(db, item.id, "智能体已创建")
    db.commit()
    db.refresh(item)
    return agent_json(item, db)


@router.get("/{id}")
def get_agent(id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return agent_json(owned_agent(db, user, id), db)


@router.patch("/{id}")
def update_agent(id: str, payload: AgentPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = owned_agent(db, user, id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        if value is None:
            raise HTTPException(422, f"{key} cannot be null")
        if isinstance(value, str):
            value = value.strip()
        if key == "name" and not value:
            raise HTTPException(422, "name cannot be empty")
        setattr(item, key, value)
    add_event(db, item.id, "智能体设置已更新")
    db.commit()
    db.refresh(item)
    return agent_json(item, db)


@router.delete("/{id}", status_code=204)
def delete_agent(id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.delete(owned_agent(db, user, id))
    db.commit()


@router.post("/{id}/heartbeat")
def heartbeat(id: str, payload: AgentHeartbeat, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = owned_agent(db, user, id)
    if not item.enabled:
        raise HTTPException(409, "Agent is paused")
    item.runtime_status = payload.status
    item.last_seen_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(item)
    return agent_json(item, db)


@router.post("/{id}/tasks", status_code=201)
def create_task(id: str, payload: TaskInput, user: User = Depends(current_user), db: Session = Depends(get_db)):
    agent = owned_agent(db, user, id)
    item = AgentTask(id=str(uuid4()), agent_id=agent.id, title=payload.title.strip(),
                     description=payload.description.strip())
    db.add(item)
    add_event(db, agent.id, f"任务已创建：{item.title}")
    db.commit()
    db.refresh(item)
    return task_json(item)


@router.patch("/{id}/tasks/{task_id}")
def update_task(id: str, task_id: str, payload: TaskPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    agent = owned_agent(db, user, id)
    item = db.scalar(select(AgentTask).where(AgentTask.id == task_id, AgentTask.agent_id == agent.id))
    if item is None:
        raise HTTPException(404, "Task not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        if value is None:
            raise HTTPException(422, f"{key} cannot be null")
        if isinstance(value, str):
            value = value.strip()
        if key == "title" and not value:
            raise HTTPException(422, "title cannot be empty")
        setattr(item, key, value)
    add_event(db, agent.id, f"任务已更新：{item.title}")
    db.commit()
    db.refresh(item)
    return task_json(item)


@router.delete("/{id}/tasks/{task_id}", status_code=204)
def delete_task(id: str, task_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    agent = owned_agent(db, user, id)
    item = db.scalar(select(AgentTask).where(AgentTask.id == task_id, AgentTask.agent_id == agent.id))
    if item is None:
        raise HTTPException(404, "Task not found")
    db.delete(item)
    add_event(db, agent.id, f"任务已删除：{item.title}")
    db.commit()
