"""Export static, model-visible schemas from the strict Action registry.

Run from anywhere. --check verifies committed catalog hasn't drifted.
"""

import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("JWT_SECRET", "schema-export-not-a-runtime-secret")
from app.actions.registry import REGISTRY

catalog = []
for action in REGISTRY.values():
    schema = action.schema.model_json_schema(by_alias=True)
    description = f"{action.name}. Requires {action.scope}."
    if action.effect == "delete":
        description += " Destructive deletion; requires separate delete permission."
    elif action.effect == "write":
        description += (
            " Returns entityId/entityType receipt; use a read tool to fetch content."
        )
    if action.name == "ledger.transaction.create":
        description += " Supply type (income/expense), positive amount, description and ISO occurredAt. categoryId is optional; list categories first to select a matching type."
    if action.name == "data.record.create":
        description += " Supply collectionId from nexa_data_collections_list; dataJson is a structured object."
    catalog.append(
        {
            "action": action.name,
            "toolName": "nexa_" + action.name.replace(".", "_"),
            "effect": action.effect,
            "description": description,
            "parameters": schema,
        }
    )
path = ROOT / "agent-adapters/openclaw/plugin/src/catalog.json"
content = json.dumps(catalog, ensure_ascii=False, indent=2) + "\n"
if "--check" in sys.argv:
    assert (
        path.read_text(encoding="utf-8") == content
    ), "Tool schemas drifted; run export-agent-tools.py"
else:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
print(f"{len(catalog)} static Action schemas")
