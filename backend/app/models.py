from datetime import datetime, timezone
from typing import Any

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, Numeric, text
from decimal import Decimal
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    avatar: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    dashboard: Mapped["Dashboard"] = relationship(back_populates="user", uselist=False, cascade="all, delete-orphan")
    websites: Mapped[list["Website"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    website_categories: Mapped[list["WebsiteCategory"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    devices: Mapped[list["Device"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    agents: Mapped[list["Agent"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    agent_nodes: Mapped[list["AgentNode"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    api_keys: Mapped[list["ApiKey"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    workspaces: Mapped[list["Workspace"]] = relationship(back_populates="owner", cascade="all, delete-orphan")


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    owner: Mapped[User] = relationship(back_populates="workspaces")
    clients: Mapped[list["Client"]] = relationship(back_populates="workspace", cascade="all, delete-orphan")


class FleetUsageSample(Base):
    __tablename__ = "fleet_usage_samples"
    __table_args__ = (
        Index("ix_fleet_usage_workspace_time", "workspace_id", "recorded_at"),
        Index("ix_fleet_usage_workspace_turn", "workspace_id", "turn_key"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    turn_key: Mapped[str] = mapped_column(String(64))
    whole_turn: Mapped[bool] = mapped_column(Boolean)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sequence: Mapped[int] = mapped_column(BigInteger)
    cached: Mapped[int] = mapped_column(BigInteger)
    other_input: Mapped[int] = mapped_column(BigInteger)
    output: Mapped[int] = mapped_column(BigInteger)
    other: Mapped[int] = mapped_column(BigInteger)
    total: Mapped[int] = mapped_column(BigInteger)


class Client(Base):
    __tablename__ = "clients"
    __table_args__ = (UniqueConstraint("workspace_id", "installation_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    installation_id: Mapped[str] = mapped_column(String(36))
    name: Mapped[str] = mapped_column(String(120))
    platform: Mapped[str] = mapped_column(String(20))
    app_version: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    token_hash: Mapped[str | None] = mapped_column(String(64), unique=True, index=True, nullable=True)
    token_last4: Mapped[str | None] = mapped_column(String(4), nullable=True)
    token_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    workspace: Mapped[Workspace] = relationship(back_populates="clients")


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(48))
    last4: Mapped[str] = mapped_column(String(4))
    scopes: Mapped[list[str]] = mapped_column(JSON)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    user: Mapped[User] = relationship(back_populates="api_keys")


class Dashboard(Base):
    __tablename__ = "dashboards"
    __table_args__ = (UniqueConstraint("user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120), default="我的控制中心")
    layout_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    sync_revision: Mapped[int] = mapped_column(BigInteger, default=0)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    user: Mapped[User] = relationship(back_populates="dashboard")


class WebsiteCategory(Base):
    __tablename__ = "website_categories"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    order: Mapped[int] = mapped_column(Integer, default=0)
    sync_revision: Mapped[int] = mapped_column(BigInteger, default=0)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    user: Mapped[User] = relationship(back_populates="website_categories")
    websites: Mapped[list["Website"]] = relationship(back_populates="category")


class Website(Base):
    __tablename__ = "websites"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    category_id: Mapped[str | None] = mapped_column(ForeignKey("website_categories.id", ondelete="SET NULL"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    url: Mapped[str] = mapped_column(String(2048))
    icon: Mapped[str | None] = mapped_column(String(500), nullable=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    favorite: Mapped[bool] = mapped_column(Boolean, default=False)
    order: Mapped[int] = mapped_column(Integer, default=0)
    last_visited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sync_revision: Mapped[int] = mapped_column(BigInteger, default=0)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    user: Mapped[User] = relationship(back_populates="websites")
    category: Mapped[WebsiteCategory | None] = relationship(back_populates="websites")


class UserPreference(Base):
    __tablename__ = "user_preferences"
    __table_args__ = (UniqueConstraint("user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    theme: Mapped[str] = mapped_column(String(30), default="system")
    language: Mapped[str] = mapped_column(String(20), default="zh-CN")
    timezone: Mapped[str] = mapped_column(String(80), default="Asia/Shanghai")
    settings_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    sync_revision: Mapped[int] = mapped_column(BigInteger, default=0)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    system: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(20))
    ip: Mapped[str] = mapped_column(String(120))
    location: Mapped[str] = mapped_column(String(120), default="")
    cpu: Mapped[int] = mapped_column(Integer, default=0)
    memory: Mapped[int] = mapped_column(Integer, default=0)
    disk: Mapped[int] = mapped_column(Integer, default=0)
    battery: Mapped[int | None] = mapped_column(Integer, nullable=True)
    activity_json: Mapped[list[int]] = mapped_column(JSON, default=list)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    token_hash: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True, index=True)
    token_last4: Mapped[str | None] = mapped_column(String(4), nullable=True)
    token_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    hostname: Mapped[str | None] = mapped_column(String(120), nullable=True)
    os: Mapped[str | None] = mapped_column(String(40), nullable=True)
    os_version: Mapped[str | None] = mapped_column(String(120), nullable=True)
    architecture: Mapped[str | None] = mapped_column(String(40), nullable=True)
    cpu_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    memory_total: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    memory_used: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    disk_total: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    disk_used: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    uptime_seconds: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    local_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    client_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    user: Mapped[User] = relationship(back_populates="devices")


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(120), default="自定义助理")
    description: Mapped[str] = mapped_column(String(500), default="")
    model: Mapped[str] = mapped_column(String(120), default="未配置")
    workspace: Mapped[str] = mapped_column(String(120), default="个人工作区")
    avatar: Mapped[str] = mapped_column(String(20), default="spark")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    data_scopes: Mapped[list[str]] = mapped_column(JSON, default=list, server_default=text("'[]'"))
    runtime_status: Mapped[str] = mapped_column(String(20), default="idle")
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    token_hash: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True, index=True)
    token_last4: Mapped[str | None] = mapped_column(String(4), nullable=True)
    token_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    runtime_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    runtime_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    runtime_instance: Mapped[str | None] = mapped_column(String(120), nullable=True)
    current_task_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    user: Mapped[User] = relationship(back_populates="agents")
    tasks: Mapped[list["AgentTask"]] = relationship(back_populates="agent", cascade="all, delete-orphan")
    events: Mapped[list["AgentEvent"]] = relationship(back_populates="agent", cascade="all, delete-orphan")


class AgentActionLog(Base):
    __tablename__ = "agent_action_logs"
    __table_args__ = (UniqueConstraint("agent_id", "action_id", name="uq_agent_action_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    task_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    action_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    action_type: Mapped[str] = mapped_column(String(80))
    required_scope: Mapped[str] = mapped_column(String(40))
    target_entity_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    target_entity_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20))
    error_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    result_summary: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentTask(Base):
    __tablename__ = "agent_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(String(500), default="")
    status: Mapped[str] = mapped_column(String(20), default="queued")
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    agent: Mapped[Agent] = relationship(back_populates="tasks")


class AgentEvent(Base):
    __tablename__ = "agent_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    level: Mapped[str] = mapped_column(String(20), default="info")
    message: Mapped[str] = mapped_column(String(500))
    task_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    event_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    data_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    agent: Mapped[Agent] = relationship(back_populates="events")


class DataCollection(Base):
    __tablename__ = "data_collections"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(500), default="")
    icon: Mapped[str] = mapped_column(String(30), default="custom")
    tone: Mapped[str] = mapped_column(String(30), default="blue")
    sync_revision: Mapped[int] = mapped_column(BigInteger, default=0)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    records: Mapped[list["DataRecord"]] = relationship(back_populates="collection", cascade="all, delete-orphan")


class DataRecord(Base):
    __tablename__ = "data_records"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    collection_id: Mapped[str] = mapped_column(ForeignKey("data_collections.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(40), default="active")
    category: Mapped[str] = mapped_column(String(80), default="")
    data_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    sync_revision: Mapped[int] = mapped_column(BigInteger, default=0)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    collection: Mapped[DataCollection] = relationship(back_populates="records")


class AutomationWorkflow(Base):
    __tablename__ = "automation_workflows"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(500), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    trigger_type: Mapped[str] = mapped_column(String(30), default="manual")
    trigger_config_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    workflow_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    sync_revision: Mapped[int] = mapped_column(BigInteger, default=0)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    executions: Mapped[list["AutomationExecution"]] = relationship(back_populates="workflow", cascade="all, delete-orphan")


class AutomationExecution(Base):
    __tablename__ = "automation_executions"
    __table_args__ = (UniqueConstraint("workspace_id", "workflow_id", "trigger_instance_id", name="uq_automation_trigger"),
                      Index("ix_automation_due", "status", "next_attempt_at", "lease_expires_at"))
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(ForeignKey("automation_workflows.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(20))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    message: Mapped[str] = mapped_column(String(500), default="")
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    workspace_id: Mapped[str | None] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True)
    trigger_type: Mapped[str] = mapped_column(String(30), default="simulation")
    trigger_instance_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    automation_revision: Mapped[int] = mapped_column(BigInteger, default=0)
    trigger_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    action_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    ancestry: Mapped[list] = mapped_column(JSON, default=list)
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    worker_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    workflow: Mapped[AutomationWorkflow] = relationship(back_populates="executions")


class AutomationScheduleState(Base):
    __tablename__ = "automation_schedule_state"
    workflow_id: Mapped[str] = mapped_column(ForeignKey("automation_workflows.id", ondelete="CASCADE"), primary_key=True)
    definition_hash: Mapped[str] = mapped_column(String(64))
    next_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AutomationActionReceipt(Base):
    __tablename__ = "automation_action_receipts"
    execution_id: Mapped[str] = mapped_column(ForeignKey("automation_executions.id", ondelete="CASCADE"), primary_key=True)
    action_key: Mapped[str] = mapped_column(String(30), default="0")
    status: Mapped[str] = mapped_column(String(20), default="succeeded")
    result_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AutomationEvent(Base):
    __tablename__ = "automation_events"
    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(40))
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[str] = mapped_column(String(36))
    operation: Mapped[str] = mapped_column(String(20))
    origin: Mapped[str] = mapped_column(String(20))
    origin_execution_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    ancestry: Mapped[list] = mapped_column(JSON, default=list)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)


class LedgerCategory(Base):
    __tablename__ = "ledger_categories"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    type: Mapped[str] = mapped_column(String(10))
    icon: Mapped[str] = mapped_column(String(30), default="shopping")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    sync_revision: Mapped[int] = mapped_column(BigInteger, default=0)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    transactions: Mapped[list["LedgerTransaction"]] = relationship(back_populates="category")


class LedgerTransaction(Base):
    __tablename__ = "ledger_transactions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    category_id: Mapped[str | None] = mapped_column(ForeignKey("ledger_categories.id", ondelete="SET NULL"), nullable=True, index=True)
    type: Mapped[str] = mapped_column(String(10))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    description: Mapped[str] = mapped_column(String(200))
    merchant: Mapped[str] = mapped_column(String(120), default="")
    note: Mapped[str] = mapped_column(String(500), default="")
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    sync_revision: Mapped[int] = mapped_column(BigInteger, default=0)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    category: Mapped[LedgerCategory | None] = relationship(back_populates="transactions")


class SyncWorkspaceState(Base):
    __tablename__ = "sync_workspace_state"
    __table_args__ = (CheckConstraint("current_revision >= 0", name="ck_sync_workspace_revision_nonnegative"),)

    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True)
    current_revision: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    bootstrap_version: Mapped[int] = mapped_column(Integer, default=0)
    initialized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SyncChange(Base):
    __tablename__ = "sync_changes"
    __table_args__ = (UniqueConstraint("workspace_id", "revision", name="uq_sync_changes_workspace_revision"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    revision: Mapped[int] = mapped_column(BigInteger)
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[str] = mapped_column(String(36))
    operation: Mapped[str] = mapped_column(String(10))
    payload_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    origin_client_id: Mapped[str | None] = mapped_column(ForeignKey("clients.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SyncMutation(Base):
    __tablename__ = "sync_mutations"
    __table_args__ = (UniqueConstraint("client_id", "mutation_id", name="uq_sync_mutations_client_mutation"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    mutation_id: Mapped[str] = mapped_column(String(36))
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[str] = mapped_column(String(36))
    operation: Mapped[str] = mapped_column(String(10))
    base_revision: Mapped[int] = mapped_column(BigInteger)
    result_revision: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String(10))
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LocalSyncState(Base):
    __tablename__ = "local_sync_state"
    __table_args__ = (CheckConstraint("cursor >= 0", name="ck_local_sync_cursor_nonnegative"),)

    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True)
    cursor: Mapped[int] = mapped_column(BigInteger, default=0)
    remote_core_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    remote_workspace_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    remote_client_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    queue_seed_version: Mapped[int] = mapped_column(Integer, default=0)
    queue_seeded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class LocalAutomationEvent(Base):
    __tablename__ = "local_automation_events"
    __table_args__ = (Index("ix_local_automation_events_pending", "workspace_id", "delivered_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    event_id: Mapped[str] = mapped_column(String(160), unique=True)
    type: Mapped[str] = mapped_column(String(40))
    agent_id: Mapped[str] = mapped_column(String(36))
    task_id: Mapped[str] = mapped_column(String(36))
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String(80), nullable=True)


class LocalMutation(Base):
    __tablename__ = "local_mutation_queue"
    __table_args__ = (
        Index("ix_local_mutation_workspace_status", "workspace_id", "status"),
        Index("uq_local_mutation_pending_entity", "workspace_id", "entity_type", "entity_id",
              unique=True, sqlite_where=text("status = 'pending'"),
              postgresql_where=text("status = 'pending'")),
        Index("uq_local_mutation_frozen_entity", "workspace_id", "entity_type", "entity_id",
              unique=True, sqlite_where=text("status IN ('in_flight', 'conflict', 'rejected')"),
              postgresql_where=text("status IN ('in_flight', 'conflict', 'rejected')")),
        CheckConstraint("base_revision >= 0", name="ck_local_mutation_base_nonnegative"),
        CheckConstraint("attempt_count >= 0", name="ck_local_mutation_attempt_nonnegative"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    mutation_id: Mapped[str] = mapped_column(String(36), unique=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[str] = mapped_column(String(36))
    operation: Mapped[str] = mapped_column(String(10))
    base_revision: Mapped[int] = mapped_column(BigInteger)
    payload_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    depends_on_mutation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    result_revision: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    conflict_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(10), default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AgentNode(Base):
    """跨设备 Agent 控制节点注册元数据（严禁持久化任何聊天正文或模型订阅密钥）。"""
    __tablename__ = "agent_nodes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    platform: Mapped[str] = mapped_column(String(20), default="windows")
    hostname: Mapped[str | None] = mapped_column(String(120), nullable=True)
    token_hash: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True, index=True)
    token_last4: Mapped[str | None] = mapped_column(String(4), nullable=True)
    token_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 节点上报的只读工作目录白名单摘要与适配器能力；真实路径边界由节点本地配置强制裁决
    allowed_roots_json: Mapped[list[str]] = mapped_column(JSON, default=list, server_default=text("'[]'"))
    adapters_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, server_default=text("'[]'"))
    transfer_endpoints_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, server_default=text("'[]'"))
    runtime_status: Mapped[str] = mapped_column(String(20), default="offline")
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    user: Mapped[User] = relationship(back_populates="agent_nodes")


class EncryptedBlob(Base):
    """客户端预加密分块文件元数据（通用底座：服务 /chat 跨端附件传输及后续 Shared Space）。"""
    __tablename__ = "encrypted_blobs"
    __table_args__ = (
        Index("ix_encrypted_blobs_workspace_purpose", "workspace_id", "purpose", "expires_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    uploader_kind: Mapped[str] = mapped_column(String(20), default="user")
    uploader_id: Mapped[str] = mapped_column(String(64))
    purpose: Mapped[str] = mapped_column(String(32), default="fleet_artifact")
    digest: Mapped[str] = mapped_column(String(64), index=True)
    ciphertext_size: Mapped[int] = mapped_column(BigInteger, default=0)
    chunk_size: Mapped[int] = mapped_column(Integer)
    chunk_count: Mapped[int] = mapped_column(Integer)
    storage_role: Mapped[str] = mapped_column(String(24), default="core")
    storage_location: Mapped[str] = mapped_column(String(500), default="")
    # 仅保留密文分块清单/非敏感校验元信息（服务端不存储也不解析明文文件或解密密钥）
    manifest_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SharedSpace(Base):
    """Shared Space（/space）三档分级共享空间元数据：standard / protected / e2ee。"""
    __tablename__ = "shared_spaces"
    __table_args__ = (
        CheckConstraint("tier IN ('standard', 'protected', 'e2ee')", name="ck_shared_spaces_tier"),
        Index("ix_shared_spaces_workspace_tier", "workspace_id", "tier"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(500), default="", server_default="")
    tier: Mapped[str] = mapped_column(String(20), default="standard", server_default="standard")
    active_epoch: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    envelope_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    # 仅 protected 档保存 Argon2id 口令校验串；standard 与 e2ee 强制为空
    password_verifier: Mapped[str | None] = mapped_column(String(255), nullable=True)
    quota_bytes: Mapped[int] = mapped_column(BigInteger, default=500 * 1024 * 1024)
    used_bytes: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class SpaceDeviceGrant(Base):
    """空间设备级授权边界（预留多设备/多成员细粒度吊销扩展）。"""
    __tablename__ = "space_device_grants"
    __table_args__ = (
        Index("ix_space_device_grants_space_client", "space_id", "client_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    space_id: Mapped[str] = mapped_column(ForeignKey("shared_spaces.id", ondelete="CASCADE"), index=True)
    client_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    device_label: Mapped[str] = mapped_column(String(120), default="")
    can_read: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    can_write: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SpaceKeyEnvelope(Base):
    """极密 e2ee 空间按 epoch 存储的客户端加密 KeyEnvelope（Core 零知识）。"""
    __tablename__ = "space_key_envelopes"
    __table_args__ = (
        UniqueConstraint("space_id", "epoch", name="uq_space_key_envelopes_space_epoch"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    space_id: Mapped[str] = mapped_column(ForeignKey("shared_spaces.id", ondelete="CASCADE"), index=True)
    epoch: Mapped[int] = mapped_column(Integer, default=1)
    envelope_version: Mapped[int] = mapped_column(Integer, default=1)
    envelope_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class SpaceEntry(Base):
    """Shared Space 共享条目主表（e2ee 档强制不落任何明文标题、文件名与标签）。"""
    __tablename__ = "space_entries"
    __table_args__ = (
        CheckConstraint("entry_type IN ('text', 'config', 'key', 'file')", name="ck_space_entries_type"),
        Index("ix_space_entries_space_deleted", "space_id", "deleted_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    space_id: Mapped[str] = mapped_column(ForeignKey("shared_spaces.id", ondelete="CASCADE"), index=True)
    entry_type: Mapped[str] = mapped_column(String(20), default="text")
    current_revision: Mapped[int] = mapped_column(Integer, default=1)
    active_epoch: Mapped[int] = mapped_column(Integer, default=1)
    # standard/protected 档可见展示元数据；e2ee 档强制置空（全量移入加密 manifest）
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mime: Mapped[str] = mapped_column(String(120), default="text/plain")
    tags_json: Mapped[list[str]] = mapped_column(JSON, default=list, server_default=text("'[]'"))
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class SpaceBlob(Base):
    """Shared Space 分块文件仓储元数据（standard 存明文块，protected/e2ee 存 AES-256-GCM 密文块）。"""
    __tablename__ = "space_blobs"
    __table_args__ = (
        Index("ix_space_blobs_space_committed", "space_id", "committed_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    space_id: Mapped[str] = mapped_column(ForeignKey("shared_spaces.id", ondelete="CASCADE"), index=True)
    chunk_size: Mapped[int] = mapped_column(Integer)
    chunk_count: Mapped[int] = mapped_column(Integer)
    total_size: Mapped[int] = mapped_column(BigInteger, default=0)
    chunks_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default=text("'{}'"))
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SpaceEntryRevision(Base):
    """Shared Space 条目修订快照（支持 CAS 冲突保留与分块关联）。"""
    __tablename__ = "space_entry_revisions"
    __table_args__ = (
        UniqueConstraint("entry_id", "revision", name="uq_space_entry_revisions_entry_rev"),
        Index("ix_space_entry_revisions_space_entry", "space_id", "entry_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    space_id: Mapped[str] = mapped_column(ForeignKey("shared_spaces.id", ondelete="CASCADE"), index=True)
    entry_id: Mapped[str] = mapped_column(ForeignKey("space_entries.id", ondelete="CASCADE"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    epoch: Mapped[int] = mapped_column(Integer, default=1)
    wrapped_dek_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    encrypted_manifest_b64: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 仅 standard 档文本/配置/Key 可存明文；protected 与 e2ee 档严禁落明文
    plaintext_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    blob_id: Mapped[str | None] = mapped_column(ForeignKey("space_blobs.id", ondelete="SET NULL"), nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    chunk_size: Mapped[int] = mapped_column(Integer, default=2 * 1024 * 1024)
    ciphertext_size: Mapped[int] = mapped_column(BigInteger, default=0)
    plaintext_size: Mapped[int] = mapped_column(BigInteger, default=0)
    content_sha256: Mapped[str] = mapped_column(String(64), default="")
    is_conflict: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    base_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by: Mapped[str] = mapped_column(String(64), default="user")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SpaceToken(Base):
    """Shared Space 专用 API Token（ss_live_ 仅普通档；sv_live_ 仅受控机密档，严格隔离）。"""
    __tablename__ = "space_tokens"
    __table_args__ = (
        CheckConstraint("token_kind IN ('standard', 'vault')", name="ck_space_tokens_kind"),
        Index("ix_space_tokens_space_revoked", "space_id", "revoked_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    space_id: Mapped[str] = mapped_column(ForeignKey("shared_spaces.id", ondelete="CASCADE"), index=True)
    token_kind: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(120))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    token_last4: Mapped[str] = mapped_column(String(4))
    scopes_json: Mapped[list[str]] = mapped_column(JSON, default=list, server_default=text("'[\"read\"]'"))
    # 可选条目 ID 白名单（null 表示整个空间；非空则仅允许访问指定条目）
    entry_ids_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SpaceAccessAuditLog(Base):
    """Shared Space 敏感操作与 Token 访问审计日志（严禁记录任何明文与密码）。"""
    __tablename__ = "space_access_audit_logs"
    __table_args__ = (
        Index("ix_space_audit_space_created", "space_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    space_id: Mapped[str] = mapped_column(ForeignKey("shared_spaces.id", ondelete="CASCADE"), index=True)
    entry_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    actor_kind: Mapped[str] = mapped_column(String(24))
    actor_id: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(48))
    outcome: Mapped[str] = mapped_column(String(20), default="allowed")
    detail: Mapped[str] = mapped_column(String(240), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SpaceChange(Base):
    """Shared Space 隔离增量游标日志（不进入 Sync v3 业务流）。"""
    __tablename__ = "space_changes"
    __table_args__ = (
        Index("ix_space_changes_space_seq", "space_id", "seq"),
    )

    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    space_id: Mapped[str] = mapped_column(ForeignKey("shared_spaces.id", ondelete="CASCADE"), index=True)
    entry_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    epoch: Mapped[int] = mapped_column(Integer, default=1)
    change_type: Mapped[str] = mapped_column(String(24))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SpaceMutationReceipt(Base):
    """Shared Space 写操作幂等回执（支持断网重试不重复建条目/修订）。"""
    __tablename__ = "space_mutation_receipts"
    __table_args__ = (
        UniqueConstraint("workspace_id", "space_id", "mutation_id", name="uq_space_mutation_receipts_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    space_id: Mapped[str] = mapped_column(ForeignKey("shared_spaces.id", ondelete="CASCADE"), index=True)
    mutation_id: Mapped[str] = mapped_column(String(64))
    entry_id: Mapped[str] = mapped_column(String(36))
    result_revision: Mapped[int] = mapped_column(Integer)
    response_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
