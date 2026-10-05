from typing import Any, Literal
from uuid import UUID, uuid4, uuid5, NAMESPACE_URL
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session
from ...utils.time import iso_utc
from ...database import get_db
from ...models import AutomationWorkflow, AutomationExecution, AutomationScheduleState, Client, User, utcnow
from ...database import runtime_config
from ...security import current_user, read_user_for, client_from_token
from ...automation import connection
from ...automation.engine import enqueue, ActionError, cancel_pending
from ...workspaces import get_personal_workspace
from ...sync.publisher import prepare_write, publish, delete_entity
from ...sync.adapters import get_adapter
from ...sync.adapters.personal_state import AutomationData
from pydantic import ValidationError
from ..personal_route import SafePersonalRoute

router = APIRouter(prefix="/api/automation", tags=["automation"], route_class=SafePersonalRoute)
v1_router = APIRouter(prefix="/api/v1/automations", tags=["automation"], route_class=SafePersonalRoute)
client_router = APIRouter(prefix="/api/v1/client/automations", tags=["automation-runtime"], route_class=SafePersonalRoute)
Trigger = Literal["manual", "schedule", "data_changed", "agent_completed", "device_status", "agent_event", "webhook"]


class WorkflowInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    enabled: bool = True
    trigger_type: Trigger = "manual"
    trigger_config_json: dict[str, Any] = Field(default_factory=dict)
    workflow_json: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Name is required")
        return value


class WorkflowPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    enabled: bool | None = None
    trigger_type: Trigger | None = None
    trigger_config_json: dict[str, Any] | None = None
    workflow_json: list[dict[str, Any]] | None = None


def workflow_or_404(db: Session, user: User, id: str) -> AutomationWorkflow:
    item = db.scalar(select(AutomationWorkflow).where(AutomationWorkflow.id == id, AutomationWorkflow.user_id == user.id,
                                                     AutomationWorkflow.deleted_at.is_(None)))
    if item is None:
        raise HTTPException(404, "Workflow not found")
    return item


def workflow_out(item: AutomationWorkflow) -> dict:
    definition = get_adapter("automation.definition").serialize(item)
    return {"id": item.id, "name": definition["name"], "description": definition["description"], "enabled": item.enabled,
            "triggerType": definition["triggerType"], "triggerConfigJson": definition["triggerConfigJson"],
            "workflowJson": definition["workflowJson"], "createdAt": iso_utc(item.created_at), "updatedAt": iso_utc(item.updated_at)}


def validate_definition(item):
    adapter = get_adapter("automation.definition")
    try:
        # Strict input validation, unlike the legacy allowlist projection.
        data = AutomationData.model_validate({key: getattr(item, attr) for key, attr in adapter.fields.items()})
    except ValidationError:
        raise HTTPException(422, "Unsupported automation definition") from None
    adapter.apply_data(item, data)


def execution_out(item: AutomationExecution) -> dict:
    return {"id": item.id, "workflowId": item.workflow_id, "status": item.status,
            "startedAt": iso_utc(item.started_at), "finishedAt": iso_utc(item.finished_at),
            "message": item.message, "resultJson": item.result_json,
            "triggerType": item.trigger_type, "triggerInstanceId": item.trigger_instance_id,
            "attempt": item.attempt, "createdAt": iso_utc(item.created_at),
            "errorCode": item.error_code, "resultSummary": item.result_json,
            "nextAttemptAt": iso_utc(item.next_attempt_at), "automationRevision": item.automation_revision,
            "action": item.action_snapshot, "trigger": item.trigger_snapshot}


@router.get("")
def legacy_automation(user: User = Depends(read_user_for("Automation")), db: Session = Depends(get_db)):
    items = db.scalars(select(AutomationWorkflow).where(AutomationWorkflow.user_id == user.id, AutomationWorkflow.deleted_at.is_(None))).all()
    return {"workflows": [workflow_out(item) for item in items], "total": len(items)}


@v1_router.get("")
def list_workflows(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return [workflow_out(item) for item in db.scalars(select(AutomationWorkflow).where(AutomationWorkflow.user_id == user.id, AutomationWorkflow.deleted_at.is_(None)).order_by(AutomationWorkflow.created_at.desc())).all()]


@v1_router.post("", status_code=201)
def create_workflow(payload: WorkflowInput, user: User = Depends(current_user), db: Session = Depends(get_db)):
    prepare_write(db, user)
    item = AutomationWorkflow(id=str(uuid4()), user_id=user.id,
                              workspace_id=get_personal_workspace(db, user).id, **payload.model_dump())
    validate_definition(item)
    db.add(item)
    publish(db, item)
    db.commit(); db.refresh(item)
    return workflow_out(item)


@v1_router.get("/{id}")
def get_workflow(id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return workflow_out(workflow_or_404(db, user, id))


@v1_router.patch("/{id}")
def patch_workflow(id: str, payload: WorkflowPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    prepare_write(db, user)
    item = workflow_or_404(db, user, id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        if value is None:
            raise HTTPException(422, f"{key} cannot be null")
        setattr(item, key, value.strip() if key == "name" else value)
    if not item.name:
        raise HTTPException(422, "Name is required")
    validate_definition(item)
    publish(db, item)
    if runtime_config.mode == "core":
        cancel_pending(db)
    db.commit(); db.refresh(item)
    return workflow_out(item)


@v1_router.delete("/{id}", status_code=204)
def delete_workflow(id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    prepare_write(db, user)
    delete_entity(db, workflow_or_404(db, user, id))
    if runtime_config.mode == "core":
        cancel_pending(db)
    db.commit()


@v1_router.get("/{id}/executions")
def list_executions(id: str, runtime: bool = False, user: User = Depends(current_user), db: Session = Depends(get_db)):
    workflow_or_404(db, user, id)
    if runtime and runtime_config.mode == "local":
        return connection.request(user.id, id, "executions", expect_list=True)
    return [execution_out(item) for item in db.scalars(select(AutomationExecution).where(AutomationExecution.workflow_id == id).order_by(AutomationExecution.started_at.desc())).all()]


class RunInput(BaseModel):
    model_config = {"extra": "forbid"}
    request_id: UUID = Field(default_factory=uuid4)


def queue_manual(db, workflow, payload):
    if workflow.deleted_at is not None:
        raise HTTPException(404, "Workflow not found")
    try:
        identity = str(uuid5(NAMESPACE_URL, f"nexa:manual:{workflow.id}:{payload.request_id}"))
        item = enqueue(db, workflow, "manual", identity)
        db.commit()
        return execution_out(item)
    except ActionError:
        raise HTTPException(422, "Definition is not executable") from None


@v1_router.post("/{id}/run", status_code=201)
def run_now(id: str, payload: RunInput | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    payload = payload or RunInput()
    workflow = workflow_or_404(db, user, id)
    if runtime_config.mode == "local":
        return connection.request(user.id, id, "run", "POST", payload.model_dump(mode="json"))
    # Serialize manual dispatch against tombstone/definition updates.
    db.refresh(workflow, with_for_update=True)
    return queue_manual(db, workflow, payload)


def detail(db, workflow, execution_id):
    item = db.scalar(select(AutomationExecution).where(AutomationExecution.id == execution_id,
        AutomationExecution.workflow_id == workflow.id, AutomationExecution.workspace_id == workflow.workspace_id))
    if item is None:
        raise HTTPException(404, "Execution not found")
    return execution_out(item)


@v1_router.get("/{id}/executions/{execution_id}")
def execution_detail(id: str, execution_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    workflow = workflow_or_404(db, user, id)
    if runtime_config.mode == "local":
        return connection.request(user.id, id, "executions/" + str(execution_id))
    return detail(db, workflow, str(execution_id))


def runtime_out(db, workflow):
    state = db.get(AutomationScheduleState, workflow.id)
    latest = db.scalar(select(AutomationExecution).where(AutomationExecution.workflow_id == workflow.id,
        AutomationExecution.trigger_type != "simulation").order_by(AutomationExecution.created_at.desc()).limit(1))
    return {"authority": "core", "available": True,
            "nextRunAt": iso_utc(state.next_due_at) if state and workflow.enabled else None,
            "lastRunAt": iso_utc(latest.started_at) if latest else None, "lastResult": latest.status if latest else None}


@v1_router.get("/{id}/runtime")
def runtime_status(id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    workflow = workflow_or_404(db, user, id)
    if runtime_config.mode == "local":
        return connection.request(user.id, id, "runtime")
    return runtime_out(db, workflow)


def client_workflow(db, client, id):
    item = db.scalar(select(AutomationWorkflow).where(AutomationWorkflow.id == id,
        AutomationWorkflow.workspace_id == client.workspace_id,
        AutomationWorkflow.deleted_at.is_(None)))
    if item is None:
        raise HTTPException(404, "Workflow not found")
    return item


@client_router.post("/{id}/run", status_code=201)
def client_run(id: str, payload: RunInput | None = None, client: Client = Depends(client_from_token), db: Session = Depends(get_db)):
    payload = payload or RunInput()
    workflow = client_workflow(db, client, id)
    db.refresh(workflow, with_for_update=True)
    return queue_manual(db, workflow, payload)


@client_router.get("/{id}/executions")
def client_history(id: str, client: Client = Depends(client_from_token), db: Session = Depends(get_db)):
    workflow = client_workflow(db, client, id)
    return [execution_out(item) for item in db.scalars(select(AutomationExecution).where(
        AutomationExecution.workflow_id == workflow.id, AutomationExecution.workspace_id == client.workspace_id,
        AutomationExecution.trigger_type != "simulation").order_by(AutomationExecution.created_at.desc()).limit(100))]


@client_router.get("/{id}/executions/{execution_id}")
def client_detail(id: str, execution_id: UUID, client: Client = Depends(client_from_token), db: Session = Depends(get_db)):
    return detail(db, client_workflow(db, client, id), str(execution_id))


@client_router.get("/{id}/runtime")
def client_runtime(id: str, client: Client = Depends(client_from_token), db: Session = Depends(get_db)):
    return runtime_out(db, client_workflow(db, client, id))


@v1_router.post("/{id}/test-run", status_code=201)
def test_run(id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    workflow_or_404(db, user, id)
    item = AutomationExecution(id=str(uuid4()), workflow_id=id, status="success", started_at=utcnow(),
                               finished_at=utcnow(), message="Test execution completed; no actions were run",
                               result_json={"simulated": True})
    db.add(item); db.commit(); db.refresh(item)
    return execution_out(item)
