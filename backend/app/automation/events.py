from sqlalchemy import select
from ..database import runtime_config
from ..models import AutomationEvent, AutomationExecution, AutomationActionReceipt

BUSINESS_ENTITIES = {"ledger.transaction", "data.record", "website"}


def business_change(db, workspace_id, revision, entity_type, entity_id, operation, *, sync=False):
    if entity_type not in BUSINESS_ENTITIES:
        return
    context = db.info.get("automation_context", {})
    db.add(AutomationEvent(id=f"change:{workspace_id}:{revision}", workspace_id=workspace_id,
        type="data_changed", entity_type=entity_type, entity_id=entity_id, operation=operation,
        origin="automation" if context else "sync" if sync else db.info.get("business_origin", "user"),
        origin_execution_id=context.get("execution_id"), ancestry=context.get("ancestry", []), payload={}))


def task_completed(db, agent, task):
    if runtime_config.mode != "core":
        return
    # Agent tasks are runtime entities; ancestry comes from the durable dispatch receipt.
    receipt = db.scalar(select(AutomationActionReceipt).where(
        AutomationActionReceipt.result_summary["taskId"].as_string() == task.id))
    source = db.get(AutomationExecution, receipt.execution_id) if receipt else None
    db.add(AutomationEvent(id=f"task:{task.id}:completed", workspace_id=agent.workspace_id,
        type="agent_completed", entity_type="agent.task", entity_id=task.id, operation="completed",
        origin="automation" if source else "agent", origin_execution_id=source.id if source else None,
        ancestry=source.ancestry if source else [], payload={"agent_id": agent.id}))
