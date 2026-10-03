"""A successful receipt, business mutation and outbox commit together.

Receipts contain safe identities only. Replay returns the original safe receipt,
not a second business write or an archived copy of sensitive business content.
"""

import hashlib
import json
from uuid import uuid4
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from ..models import Agent, AgentActionLog, AgentEvent, utcnow
from ..services.ownership import BusinessOwner
from .base import Envelope
from .registry import REGISTRY


def error(status, code):
    return HTTPException(status, {"code": code})


def response(envelope, data, replayed=False):
    return {
        "actionId": str(envelope.actionId) if envelope.actionId else None,
        "action": envelope.action,
        "status": "ok",
        "replayed": replayed,
        "data": data,
    }


def execute(db, agent, raw):
    try:
        envelope = Envelope.model_validate(raw)
    except ValidationError:
        raise error(422, "validation_error") from None
    action = REGISTRY.get(envelope.action)
    if action is None:
        raise error(422, "unsupported_action")
    try:
        arguments = action.schema.model_validate(envelope.arguments)
    except (ValidationError, ValueError, TypeError):
        raise error(422, "validation_error") from None
    if action.effect != "read" and envelope.actionId is None:
        raise error(422, "validation_error")
    canonical = {
        "action": action.name,
        "arguments": arguments.model_dump(
            mode="json", by_alias=True, exclude_unset=True
        ),
    }
    try:
        digest = hashlib.sha256(
            json.dumps(
                canonical,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode()
        ).hexdigest()
    except (ValueError, TypeError):
        raise error(422, "validation_error") from None
    authenticated_hash = agent.token_hash
    agent_id, workspace_id, task_id = (
        agent.id,
        agent.workspace_id,
        agent.current_task_id,
    )
    log = AgentActionLog(
        id=str(uuid4()),
        agent_id=agent_id,
        workspace_id=workspace_id,
        task_id=task_id,
        action_type=action.name,
        required_scope=action.scope,
        request_hash=digest,
        status="pending",
        target_entity_type=action.entity_type,
    )
    try:
        # A row write serializes mutations before checking receipts; this works on
        # SQLite and protects against simultaneous retries on independent sessions.
        if action.effect != "read":
            db.execute(
                update(Agent)
                .where(Agent.id == agent_id)
                .values(data_scopes=Agent.data_scopes)
            )
        db.refresh(agent)
        if not agent.token_hash or agent.token_hash != authenticated_hash:
            raise error(401, "unauthorized")
        if not agent.enabled:
            raise error(403, "agent_disabled")
        if action.scope not in (agent.data_scopes or []):
            raise error(403, "permission_denied")
        log.task_id = agent.current_task_id
        if action.effect != "read":
            prior = db.scalar(
                select(AgentActionLog).where(
                    AgentActionLog.agent_id == agent_id,
                    AgentActionLog.action_id == str(envelope.actionId),
                )
            )
            if prior:
                if prior.request_hash != digest:
                    raise error(409, "idempotency_conflict")
                receipt = prior.result_summary
                db.rollback()
                return response(envelope, receipt, True)
            log.action_id = str(envelope.actionId)
        db.add(log)
        db.flush()
        db.info["business_origin"] = "agent"
        try:
            # Preserve automation ancestry across Agent business writes too.
            if agent.current_task_id:
                from ..models import AutomationActionReceipt, AutomationExecution
                receipt = db.scalar(select(AutomationActionReceipt).where(
                    AutomationActionReceipt.result_summary["taskId"].as_string() == agent.current_task_id))
                source = db.get(AutomationExecution, receipt.execution_id) if receipt else None
                if source:
                    db.info["automation_context"] = {"execution_id": source.id, "ancestry": source.ancestry}
            data = action.handler(db, BusinessOwner(agent.user_id, agent.workspace_id), arguments)
        finally:
            db.info.pop("business_origin", None)
            db.info.pop("automation_context", None)
        entity_id = data.get("id") if isinstance(data, dict) else None
        if action.effect != "read":
            entity_id = entity_id or str(getattr(arguments, "id", "")) or None
            log.target_entity_id = entity_id
            log.result_summary = {
                "entityId": entity_id,
                "entityType": action.entity_type,
            }
            db.add(
                AgentEvent(
                    id=str(uuid4()),
                    agent_id=agent.id,
                    task_id=agent.current_task_id,
                    event_type="data.action",
                    level="info",
                    message=f"{action.name} succeeded",
                    data_json=log.result_summary,
                )
            )
        log.status = "ok"
        log.completed_at = utcnow()
        db.commit()
        return response(
            envelope, log.result_summary if action.effect != "read" else data
        )
    except HTTPException as exc:
        db.rollback()
        code = (
            exc.detail.get("code")
            if isinstance(exc.detail, dict)
            else {404: "not_found", 409: "conflict", 422: "validation_error"}.get(
                exc.status_code, "conflict"
            )
        )
        # Failed attempts do not reserve actionId: permission changes and corrected
        # invocations can succeed later. Never persist the raw body/error message.
        log.id = str(uuid4())
        log.action_id = None
        log.status = "denied" if exc.status_code == 403 else "failed"
        log.error_code = code
        log.result_summary = None
        log.completed_at = utcnow()
        db.add(log)
        db.commit()
        raise error(exc.status_code, code) from None
    except IntegrityError:
        db.rollback()
        prior = db.scalar(
            select(AgentActionLog).where(
                AgentActionLog.agent_id == agent_id,
                AgentActionLog.action_id == str(envelope.actionId),
            )
        )
        if prior and prior.request_hash == digest and prior.status == "ok":
            return response(envelope, prior.result_summary, True)
        raise error(409, "idempotency_conflict" if prior else "conflict") from None
    except SQLAlchemyError:
        db.rollback()
        raise error(503, "conflict") from None
    except Exception:
        db.rollback()
        raise error(500, "conflict") from None
