from fastapi import HTTPException
from pydantic import ValidationError
from ..models import AutomationActionReceipt, User
from ..services import ledger, data, agent_tasks
from ..services.ownership import BusinessOwner
from .schemas import Action
from .webhook import ActionError, post


def execute(db, execution):
    receipt = db.get(AutomationActionReceipt, execution.id)
    if receipt:
        return receipt.result_summary
    try:
        action = Action.model_validate(execution.action_snapshot)
        config = dict(action.config)
        user = db.get(User, execution.workflow.user_id)
        if user is None:
            raise ActionError("permission_denied")
        user = BusinessOwner(user.id, execution.workspace_id)
        db.info["automation_context"] = {"execution_id": execution.id, "ancestry": execution.ancestry}
        if action.type == "ledger.create":
            result = ledger.create_transaction(ledger.TransactionInput.model_validate(config), user, db)
            summary = {"entityId": result["id"], "entityType": "ledger.transaction"}
        elif action.type == "data.create":
            collection = config.pop("collection_id")
            result = data.create_record(collection, data.RecordInput.model_validate(config), user, db)
            summary = {"entityId": result["id"], "entityType": "data.record"}
        elif action.type == "data.update":
            record = config.pop("record_id")
            # Optional omitted fields must stay omitted rather than patching null.
            config = {key: value for key, value in config.items() if value is not None}
            result = data.patch_record(record, data.RecordPatch.model_validate(config), user, db)
            summary = {"entityId": result["id"], "entityType": "data.record"}
        elif action.type == "agent.run":
            task = agent_tasks.create_task(db, user, config["agent_id"], config["title"], config["description"],
                                           workspace_id=execution.workspace_id)
            summary = {"taskId": task.id}
        else:
            summary = post(config, execution.id)
        db.add(AutomationActionReceipt(execution_id=execution.id, result_summary=summary))
        db.flush()
        return summary
    except ValidationError:
        raise ActionError("invalid_config") from None
    except HTTPException as error:
        raise ActionError("missing_entity" if error.status_code == 404 else "validation_error" if error.status_code == 422
                          else "agent_unavailable" if error.status_code == 409 else "permission_denied",
                          error.status_code == 409 and execution.action_snapshot.get("type") == "agent.run") from None
    finally:
        db.info.pop("automation_context", None)
