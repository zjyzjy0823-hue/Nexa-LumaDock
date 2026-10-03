"""Database-owned scheduling and leased single-action execution.

Delivery is at least once. Trigger constraints and transactional receipts provide
one logical execution and replay-safe internal actions, not external exactly-once.
"""
import asyncio
from copy import deepcopy
from datetime import timedelta
import hashlib
import json
import logging
from uuid import uuid4
from pydantic import ValidationError
from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import IntegrityError
from ..database import runtime_config
from ..models import (AutomationWorkflow as Workflow, AutomationExecution as Execution,
                      AutomationScheduleState as ScheduleState, AutomationEvent as Event,
                      Workspace, utcnow)
from ..utils.time import aware_utc
from .schemas import Action
from .schedule import next_due, latest_due
from .actions import execute
from .webhook import ActionError

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 5
MAX_AUTOMATION_DEPTH = 8
BACKOFF_SECONDS = (5, 15, 30, 60, 300)
LEASE_SECONDS = 90
SCAN_SECONDS = 1


def action_for(workflow):
    nodes = workflow.workflow_json or []
    if len(nodes) != 1 or nodes[0].get("kind") != "DO" or not nodes[0].get("action"):
        raise ActionError("definition_not_executable")
    try:
        return Action.model_validate(nodes[0]["action"]).model_dump(mode="json")
    except (ValidationError, ValueError):
        raise ActionError("invalid_config") from None


def enqueue(db, workflow, trigger_type, identity, *, ancestry=None, now=None):
    now = now or utcnow()
    source = list(ancestry or [])
    guard = workflow.id in source or len(source) >= MAX_AUTOMATION_DEPTH
    execution = Execution(id=str(uuid4()), workflow_id=workflow.id, workspace_id=workflow.workspace_id,
        trigger_type=trigger_type, trigger_instance_id=identity,
        automation_revision=workflow.sync_revision, trigger_snapshot=deepcopy(workflow.trigger_config_json),
        action_snapshot=action_for(workflow), ancestry=source + [workflow.id],
        status="skipped" if guard else "queued", error_code="loop_guard" if guard else None,
        started_at=now, created_at=now, finished_at=now if guard else None, next_attempt_at=None if guard else now)
    try:
        with db.begin_nested():
            db.add(execution)
            db.flush()
    except IntegrityError:
        previous = db.scalar(select(Execution).where(Execution.workspace_id == workflow.workspace_id,
            Execution.workflow_id == workflow.id, Execution.trigger_instance_id == identity))
        if previous is None:
            raise
        return previous
    logger.info("automation %s execution=%s automation=%s trigger=%s", "loop_guard" if guard else "created",
                execution.id, workflow.id, trigger_type)
    return execution


def cancel_pending(db):
    deleted = select(Workflow.id).where(Workflow.deleted_at.is_not(None))
    disabled = select(Workflow.id).where(Workflow.enabled.is_(False))
    db.execute(update(Execution).where(Execution.status == "queued", or_(Execution.workflow_id.in_(deleted),
        and_(Execution.workflow_id.in_(disabled), Execution.trigger_type != "manual"))).values(
        status="cancelled", finished_at=utcnow(), next_attempt_at=None, error_code="definition_inactive"))


def scan_schedules(db, now=None):
    now = aware_utc(now or utcnow())
    cancel_pending(db)
    workflows = db.scalars(select(Workflow).where(Workflow.trigger_type == "schedule", Workflow.enabled.is_(True),
        Workflow.deleted_at.is_(None)).order_by(Workflow.id).with_for_update(skip_locked=True)).all()
    for workflow in workflows:
        try:
            action_for(workflow)
            config = workflow.trigger_config_json["schedule"]
            digest = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
            state = db.get(ScheduleState, workflow.id)
            if state is None:
                state = ScheduleState(workflow_id=workflow.id, definition_hash=digest,
                    next_due_at=next_due(config, workflow.created_at, inclusive=True))
                db.add(state)
            elif state.definition_hash != digest:
                state.definition_hash = digest
                state.next_due_at = next_due(config, workflow.updated_at, inclusive=True)
            due = aware_utc(state.next_due_at) if state.next_due_at else None
            if due is None or due > now:
                continue
            latest = latest_due(config, due, now)
            # A scan grace window lets 'skip' execute on-time points; missed points
            # older than one scan window are skipped without replaying downtime.
            if config.get("catch_up", "catch_up_once") == "catch_up_once" or (now - latest).total_seconds() <= SCAN_SECONDS * 2:
                enqueue(db, workflow, "schedule", "schedule:" + latest.isoformat(), now=now)
                state.last_run_at = now
            state.next_due_at = next_due(config, now)
        except (KeyError, ValueError, ActionError):
            # Legacy display-only definitions remain editable and never run.
            continue
    db.flush()


def dispatch_events(db, now=None):
    now = now or utcnow()
    events = db.scalars(select(Event).where(Event.dispatched_at.is_(None)).order_by(Event.created_at, Event.id)
        .limit(100).with_for_update(skip_locked=True)).all()
    for event in events:
        workflows = db.scalars(select(Workflow).where(Workflow.workspace_id == event.workspace_id,
            Workflow.trigger_type == event.type, Workflow.enabled.is_(True), Workflow.deleted_at.is_(None),
            Workflow.created_at <= event.created_at).with_for_update()).all()
        for workflow in workflows:
            config = workflow.trigger_config_json
            if event.type == "data_changed" and (config.get("entity_type") != event.entity_type
                    or (config.get("operation") and config["operation"] != event.operation)):
                continue
            if event.type == "agent_completed" and config.get("agent_id") and config["agent_id"] != event.payload.get("agent_id"):
                continue
            try:
                enqueue(db, workflow, event.type, "event:" + event.id, ancestry=event.ancestry, now=now)
            except ActionError:
                continue
        event.dispatched_at = now
    db.flush()


def claim(db, worker_id, now=None):
    now = aware_utc(now or utcnow())
    cancel_pending(db)
    execution = db.scalar(select(Execution).where(or_(
        and_(Execution.status == "queued", Execution.next_attempt_at <= now),
        and_(Execution.status.in_(("claimed", "running")), Execution.lease_expires_at <= now)))
        .order_by(Execution.created_at, Execution.id).limit(1).with_for_update(skip_locked=True))
    if execution is None:
        return None
    recovered = execution.status != "queued"
    if execution.attempt >= MAX_ATTEMPTS:
        # A committed receipt must still finalize after the last-attempt crash.
        from ..models import AutomationActionReceipt
        receipt = db.get(AutomationActionReceipt, execution.id)
        execution.status = "succeeded" if receipt else "failed"
        execution.result_json = receipt.result_summary if receipt else {}
        execution.error_code = None if receipt else "max_attempts"
        execution.finished_at = now
        execution.next_attempt_at = None
        execution.worker_id = execution.lease_expires_at = None
        db.flush()
        return None
    execution.worker_id = worker_id
    execution.lease_expires_at = now + timedelta(seconds=LEASE_SECONDS)
    execution.status = "claimed"
    execution.attempt += 1
    db.flush()
    logger.info("automation %s execution=%s attempt=%s", "lease_recovered" if recovered else "claimed", execution.id, execution.attempt)
    return execution.id


def run_claimed(factory, execution_id, worker_id, *, after_action=None):
    # Workspace first: business services use the same lock order. Holding the
    # execution row through side effect + receipt fences expired workers.
    with factory() as db:
        item = db.get(Execution, execution_id)
        workspace_id = item.workspace_id if item else None
        db.rollback()
        if workspace_id is None:
            return
        db.scalar(select(Workspace).where(Workspace.id == workspace_id).with_for_update())
        item = db.scalar(select(Execution).where(Execution.id == execution_id).with_for_update())
        if item.worker_id != worker_id or item.status != "claimed" or aware_utc(item.lease_expires_at) <= utcnow():
            db.rollback()
            return
        from ..models import AutomationActionReceipt
        committed = db.get(AutomationActionReceipt, item.id)
        if not committed and (item.workflow.deleted_at or (not item.workflow.enabled and item.trigger_type != "manual")):
            item.status, item.finished_at, item.error_code = "cancelled", utcnow(), "definition_inactive"
            item.worker_id = item.lease_expires_at = None
            item.next_attempt_at = None
            db.commit()
            return
        attempt = item.attempt
        item.status = "running"
        item.started_at = utcnow()
        item.lease_expires_at = utcnow() + timedelta(seconds=LEASE_SECONDS)
        logger.info("automation action_started execution=%s action=%s", item.id, item.action_snapshot.get("type"))
        try:
            summary = execute(db, item)
            db.commit()  # receipt and internal business side effect are inseparable
        except ActionError as error:
            db.rollback()
            finish(factory, execution_id, worker_id, attempt, error=error)
            return
        except Exception:
            db.rollback()
            finish(factory, execution_id, worker_id, attempt, error=ActionError("internal_error", True))
            logger.warning("automation action_failed execution=%s code=internal_error", execution_id)
            return
    if after_action:
        after_action()  # deterministic crash/response-loss injection, never configured by users
    finish(factory, execution_id, worker_id, attempt, summary=summary)


def finish(factory, execution_id, worker_id, attempt, *, summary=None, error=None):
    with factory() as db:
        item = db.scalar(select(Execution).where(Execution.id == execution_id).with_for_update())
        if item is None or item.worker_id != worker_id or item.attempt != attempt or item.status not in ("claimed", "running"):
            return
        item.worker_id = item.lease_expires_at = None
        if error and error.retryable and attempt < MAX_ATTEMPTS:
            item.status = "queued"
            item.next_attempt_at = utcnow() + timedelta(seconds=BACKOFF_SECONDS[attempt - 1])
            item.error_code = error.code
            logger.info("automation retry_scheduled execution=%s attempt=%s code=%s", item.id, attempt, error.code)
        else:
            item.status = "failed" if error else "succeeded"
            item.finished_at = utcnow()
            item.next_attempt_at = None
            item.error_code = error.code if error else None
            item.result_json = summary or {}
            logger.info("automation action_%s execution=%s", "failed" if error else "succeeded", item.id)
        db.commit()


class AutomationEngine:
    def __init__(self, factory):
        self.factory, self.worker_id = factory, str(uuid4())
        self.stopping = asyncio.Event()
        self.task = None

    def start(self):
        if runtime_config.mode != "core":
            raise RuntimeError("Automation engine is Core-only")
        self.task = asyncio.create_task(self.loop())

    def tick(self):
        with self.factory() as db:
            scan_schedules(db)
            db.commit()
            dispatch_events(db)
            db.commit()
            execution_id = claim(db, self.worker_id)
            db.commit()
        if execution_id:
            run_claimed(self.factory, execution_id, self.worker_id)

    async def loop(self):
        while not self.stopping.is_set():
            try:
                await asyncio.to_thread(self.tick)
            except Exception:
                logger.warning("automation tick_failed")
            try:
                await asyncio.wait_for(self.stopping.wait(), SCAN_SECONDS)
            except TimeoutError:
                pass

    async def stop(self):
        self.stopping.set()
        if self.task:
            await self.task
