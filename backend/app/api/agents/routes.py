from datetime import datetime, timezone
import hashlib
import secrets
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ...utils.time import iso_utc, aware_utc
from ...database import get_db
from ...models import Agent, AgentEvent, AgentTask, User
from ...security import agent_from_token, current_user, read_user_for
from ...workspaces import get_personal_workspace
from ...actions.base import DataScope

router = APIRouter(prefix="/api/v1/agents", tags=["agents"])
legacy_router = APIRouter(prefix="/api/agents", tags=["agents"])
runtime_router = APIRouter(prefix="/api/agent", tags=["agent-runtime"])
Avatar = Literal["spark", "orbit", "wave", "chart", "sun"]
TaskStatus = Literal["queued", "running", "completed", "failed"]


class AgentInput(BaseModel):
    data_scopes: list[DataScope] = Field(default_factory=list, alias="dataScopes")
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
    data_scopes: list[DataScope] | None = Field(default=None, alias="dataScopes")
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


class RuntimeHeartbeat(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["idle", "running", "error"]
    runtimeType: str = Field(min_length=1, max_length=40)
    runtimeVersion: str | None = Field(default=None, max_length=40)
    runtimeInstance: str | None = Field(default=None, max_length=120)
    model: str | None = Field(default=None, max_length=120)
    currentTaskId: str | None = Field(default=None, max_length=36)


class RuntimeEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["agent.connected", "agent.heartbeat", "task.started", "task.log", "task.completed",
                  "task.failed", "tool.started", "tool.completed", "agent.error", "task.warning", "task.error", "log"]
    level: Literal["info", "success", "warning", "error"] = "info"
    message: str = Field(min_length=1, max_length=500)
    data: dict = Field(default_factory=dict)


class RuntimeComplete(BaseModel):
    model_config = ConfigDict(extra="forbid")
    result: dict = Field(default_factory=dict)
    summary: str = Field(default="", max_length=500)


class RuntimeFail(BaseModel):
    model_config = ConfigDict(extra="forbid")
    error: str = Field(min_length=1, max_length=500)
    details: dict = Field(default_factory=dict)


def elapsed(value: datetime | None) -> str:
    if value is None:
        return "尚未连接"
    seconds = max(0, int((datetime.now(timezone.utc) - aware_utc(value)).total_seconds()))
    if seconds < 60:
        return "刚刚"
    if seconds < 3600:
        return f"{seconds // 60} 分钟前"
    if seconds < 86400:
        return f"{seconds // 3600} 小时前"
    return f"{seconds // 86400} 天前"


def effective_status(item: Agent) -> str:
    if not item.enabled:
        return "disabled"
    if item.last_seen_at and (datetime.now(timezone.utc) - aware_utc(item.last_seen_at)).total_seconds() < 120:
        return item.runtime_status
    return "offline"


def task_json(item: AgentTask) -> dict:
    return dict(id=item.id, title=item.title, description=item.description, status=item.status,
                time=elapsed(item.created_at), createdAt=iso_utc(item.created_at),
                updatedAt=iso_utc(item.updated_at), claimedAt=iso_utc(item.claimed_at),
                completedAt=iso_utc(item.completed_at), result=item.result_json,
                errorMessage=item.error_message)


def agent_json(item: Agent, db: Session) -> dict:
    tasks = list(db.scalars(select(AgentTask).where(AgentTask.agent_id == item.id).order_by(
        AgentTask.created_at.desc(), AgentTask.id)))
    events = list(db.scalars(select(AgentEvent).where(AgentEvent.agent_id == item.id).order_by(
        AgentEvent.created_at.desc(), AgentEvent.id).limit(50)))
    completed = sum(task.status == "completed" for task in tasks)
    return dict(id=item.id, name=item.name, role=item.role, description=item.description,
                status=effective_status(item), enabled=item.enabled, avatar=item.avatar,
                model=item.model, workspace=item.workspace,
                runtimeType=item.runtime_type, runtimeVersion=item.runtime_version,
                runtimeInstance=item.runtime_instance, currentTaskId=item.current_task_id,
                lastError=item.last_error, tokenLast4=item.token_last4,
                tokenCreatedAt=iso_utc(item.token_created_at),
                successRate=f"{round(completed / len(tasks) * 100)}%" if tasks else "—",
                callsToday=0, tasksToday=sum(aware_utc(task.created_at).date() == datetime.now(timezone.utc).date() for task in tasks),
                uptime=elapsed(item.last_seen_at) if item.last_seen_at else "尚未连接",
                lastActive=elapsed(item.last_seen_at), lastSeenAt=iso_utc(item.last_seen_at),
                capabilities=[], dataScopes=item.data_scopes or [], tasks=[task_json(task) for task in tasks],
                logs=[dict(time=iso_utc(event.created_at), createdAt=iso_utc(event.created_at),
                           level=event.level, eventType=event.event_type, taskId=event.task_id,
                           message=event.message) for event in events],
                apiCalls=[], createdAt=iso_utc(item.created_at), updatedAt=iso_utc(item.updated_at))


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
    item = Agent(id=str(uuid4()), user_id=user.id,
                 workspace_id=get_personal_workspace(db, user).id, **payload.model_dump())
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


@router.post("/{id}/token", status_code=201)
def generate_token(id: str, response: Response, user: User = Depends(current_user), db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    agent = owned_agent(db, user, id)
    token = f"na_live_{secrets.token_urlsafe(32)}"
    agent.token_hash = hashlib.sha256(token.encode()).hexdigest()
    agent.token_last4 = token[-4:]
    agent.token_created_at = datetime.now(timezone.utc)
    db.commit()
    return {"agentId": agent.id, "token": token, "last4": agent.token_last4,
            "createdAt": iso_utc(agent.token_created_at)}


@router.delete("/{id}/token", status_code=204)
def revoke_token(id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    agent = owned_agent(db, user, id)
    agent.token_hash = None
    agent.token_last4 = None
    agent.token_created_at = None
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
    if payload.status is not None:
        raise HTTPException(409, "Task status is controlled by the runtime")
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


def runtime_task(db: Session, agent: Agent, task_id: str) -> AgentTask:
    task = db.scalar(select(AgentTask).where(AgentTask.id == task_id, AgentTask.agent_id == agent.id))
    if task is None:
        raise HTTPException(404, "Task not found")
    return task


def runtime_event(db: Session, agent: Agent, task: AgentTask, event_type: str,
                  message: str, level: str = "info", data: dict | None = None):
    db.add(AgentEvent(id=str(uuid4()), agent_id=agent.id, task_id=task.id,
                      event_type=event_type, level=level, message=message, data_json=data or {}))


@runtime_router.post("/heartbeat")
def agent_runtime_heartbeat(payload: RuntimeHeartbeat, agent: Agent = Depends(agent_from_token),
                            db: Session = Depends(get_db)):
    if not agent.enabled:
        raise HTTPException(409, "Agent is disabled")
    if payload.currentTaskId != agent.current_task_id:
        raise HTTPException(409, "Current task does not match claimed task")
    if payload.status == "running" and not agent.current_task_id:
        raise HTTPException(409, "No claimed task")
    if agent.current_task_id and payload.status != "running":
        raise HTTPException(409, "Claimed task requires running heartbeat")
    agent.runtime_status = payload.status
    agent.runtime_type = payload.runtimeType
    agent.runtime_version = payload.runtimeVersion
    agent.runtime_instance = payload.runtimeInstance
    if payload.model is not None:
        agent.model = payload.model
    agent.last_seen_at = datetime.now(timezone.utc)
    if payload.status == "idle":
        agent.last_error = None
    db.commit()
    return {"agentId": agent.id, "status": effective_status(agent), "lastSeenAt": iso_utc(agent.last_seen_at)}


@runtime_router.get("/tasks")
def queued_tasks(status: Literal["queued"] = "queued", agent: Agent = Depends(agent_from_token),
                 db: Session = Depends(get_db)):
    if not agent.enabled:
        raise HTTPException(409, "Agent is disabled")
    return [task_json(task) for task in db.scalars(select(AgentTask).where(
        AgentTask.agent_id == agent.id, AgentTask.status == status).order_by(AgentTask.created_at, AgentTask.id))]


@runtime_router.post("/tasks/{task_id}/claim")
def claim_task(task_id: str, agent: Agent = Depends(agent_from_token), db: Session = Depends(get_db)):
    if not agent.enabled:
        raise HTTPException(409, "Agent is disabled")
    runtime_task(db, agent, task_id)
    now = datetime.now(timezone.utc)
    changed = db.execute(update(AgentTask).where(AgentTask.id == task_id, AgentTask.agent_id == agent.id,
                          AgentTask.status == "queued").values(status="running", claimed_at=now, updated_at=now))
    if changed.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "Task is not queued")
    active = db.execute(update(Agent).where(Agent.id == agent.id, Agent.current_task_id.is_(None)).values(
        current_task_id=task_id, runtime_status="running", last_seen_at=now))
    if active.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "Agent already has an active task")
    task = runtime_task(db, agent, task_id)
    runtime_event(db, agent, task, "task.started", "任务已开始")
    db.commit()
    return task_json(task)


@runtime_router.post("/tasks/{task_id}/events", status_code=201)
def post_task_event(task_id: str, payload: RuntimeEvent, agent: Agent = Depends(agent_from_token),
                    db: Session = Depends(get_db)):
    task = runtime_task(db, agent, task_id)
    if task.status != "running" or agent.current_task_id != task_id:
        raise HTTPException(409, "Task is not running")
    runtime_event(db, agent, task, "task.log" if payload.type == "log" else payload.type,
                  payload.message, payload.level, payload.data)
    db.commit()
    return {"ok": True}


@runtime_router.post("/tasks/{task_id}/complete")
def complete_task(task_id: str, payload: RuntimeComplete, agent: Agent = Depends(agent_from_token),
                  db: Session = Depends(get_db)):
    runtime_task(db, agent, task_id)
    now = datetime.now(timezone.utc)
    changed = db.execute(update(AgentTask).where(AgentTask.id == task_id, AgentTask.agent_id == agent.id,
                          AgentTask.status == "running").values(status="completed", result_json=payload.result,
                          completed_at=now, updated_at=now))
    if changed.rowcount != 1 or agent.current_task_id != task_id:
        db.rollback()
        raise HTTPException(409, "Task is not running")
    agent.current_task_id = None
    agent.runtime_status = "idle"
    agent.last_seen_at = now
    task = runtime_task(db, agent, task_id)
    runtime_event(db, agent, task, "task.completed", payload.summary or "任务已完成", "success")
    db.commit()
    return task_json(task)


@runtime_router.post("/tasks/{task_id}/fail")
def fail_task(task_id: str, payload: RuntimeFail, agent: Agent = Depends(agent_from_token),
              db: Session = Depends(get_db)):
    runtime_task(db, agent, task_id)
    now = datetime.now(timezone.utc)
    changed = db.execute(update(AgentTask).where(AgentTask.id == task_id, AgentTask.agent_id == agent.id,
                          AgentTask.status == "running").values(status="failed", error_message=payload.error,
                          completed_at=now, updated_at=now))
    if changed.rowcount != 1 or agent.current_task_id != task_id:
        db.rollback()
        raise HTTPException(409, "Task is not running")
    agent.current_task_id = None
    agent.runtime_status = "error"
    agent.last_error = payload.error
    agent.last_seen_at = now
    task = runtime_task(db, agent, task_id)
    runtime_event(db, agent, task, "task.failed", payload.error, "error", payload.details)
    db.commit()
    return task_json(task)


@router.delete("/{id}/tasks/{task_id}", status_code=204)
def delete_task(id: str, task_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    agent = owned_agent(db, user, id)
    item = db.scalar(select(AgentTask).where(AgentTask.id == task_id, AgentTask.agent_id == agent.id))
    if item is None:
        raise HTTPException(404, "Task not found")
    if item.status == "running":
        raise HTTPException(409, "Running task cannot be deleted")
    db.delete(item)
    add_event(db, agent.id, f"任务已删除：{item.title}")
    db.commit()
