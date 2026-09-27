from typing import Any, Literal
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session
from ...utils.time import iso_utc
from ...database import get_db
from ...models import AutomationWorkflow, AutomationExecution, User, utcnow
from ...security import current_user, read_user_for

router = APIRouter(prefix="/api/automation", tags=["automation"])
v1_router = APIRouter(prefix="/api/v1/automations", tags=["automation"])
Trigger = Literal["manual", "schedule", "device_status", "agent_event", "webhook"]


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
    item = db.scalar(select(AutomationWorkflow).where(AutomationWorkflow.id == id, AutomationWorkflow.user_id == user.id))
    if item is None:
        raise HTTPException(404, "Workflow not found")
    return item


def workflow_out(item: AutomationWorkflow) -> dict:
    return {"id": item.id, "name": item.name, "description": item.description, "enabled": item.enabled,
            "triggerType": item.trigger_type, "triggerConfigJson": item.trigger_config_json,
            "workflowJson": item.workflow_json, "createdAt": iso_utc(item.created_at), "updatedAt": iso_utc(item.updated_at)}


def execution_out(item: AutomationExecution) -> dict:
    return {"id": item.id, "workflowId": item.workflow_id, "status": item.status,
            "startedAt": iso_utc(item.started_at), "finishedAt": iso_utc(item.finished_at),
            "message": item.message, "resultJson": item.result_json}


@router.get("")
def legacy_automation(user: User = Depends(read_user_for("Automation")), db: Session = Depends(get_db)):
    items = db.scalars(select(AutomationWorkflow).where(AutomationWorkflow.user_id == user.id)).all()
    return {"workflows": [workflow_out(item) for item in items], "total": len(items)}


@v1_router.get("")
def list_workflows(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return [workflow_out(item) for item in db.scalars(select(AutomationWorkflow).where(AutomationWorkflow.user_id == user.id).order_by(AutomationWorkflow.created_at.desc())).all()]


@v1_router.post("", status_code=201)
def create_workflow(payload: WorkflowInput, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = AutomationWorkflow(id=str(uuid4()), user_id=user.id, **payload.model_dump())
    db.add(item); db.commit(); db.refresh(item)
    return workflow_out(item)


@v1_router.get("/{id}")
def get_workflow(id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return workflow_out(workflow_or_404(db, user, id))


@v1_router.patch("/{id}")
def patch_workflow(id: str, payload: WorkflowPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = workflow_or_404(db, user, id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        if value is None:
            raise HTTPException(422, f"{key} cannot be null")
        setattr(item, key, value.strip() if key == "name" else value)
    if not item.name:
        raise HTTPException(422, "Name is required")
    db.commit(); db.refresh(item)
    return workflow_out(item)


@v1_router.delete("/{id}", status_code=204)
def delete_workflow(id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.delete(workflow_or_404(db, user, id)); db.commit()


@v1_router.get("/{id}/executions")
def list_executions(id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    workflow_or_404(db, user, id)
    return [execution_out(item) for item in db.scalars(select(AutomationExecution).where(AutomationExecution.workflow_id == id).order_by(AutomationExecution.started_at.desc())).all()]


@v1_router.post("/{id}/test-run", status_code=201)
def test_run(id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    workflow_or_404(db, user, id)
    item = AutomationExecution(id=str(uuid4()), workflow_id=id, status="success", started_at=utcnow(),
                               finished_at=utcnow(), message="Test execution completed; no actions were run",
                               result_json={"simulated": True})
    db.add(item); db.commit(); db.refresh(item)
    return execution_out(item)
