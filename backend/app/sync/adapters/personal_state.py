"""Explicit personal-state projections; no persistence blob is a sync schema."""
import re
from typing import Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from sqlalchemy import select

from ...models import AutomationWorkflow, Dashboard, UserPreference
from ...schemas import Layout
from ...resources import resource_path
from pathlib import Path
from .base import SyncAdapter


class StrictData(BaseModel):
    model_config = ConfigDict(extra="forbid")


def safe_text(value: str) -> str:
    # Values as well as field names matter. Known credential encodings and local
    # paths are never user-facing cross-device configuration.
    if re.search(r"(?i)(nc_live_|na_live_|nd_live_|bearer\s|authorization|"
                 r"(?:password|credential|token|jwt|secret|api[_ -]?key)\s*[:=]|"
                 r"\beyJ[A-Za-z0-9_-]+\.|[a-z]:[\\/]|\\\\|file://|"
                 r"(?:^|\s)/(?:home|users|tmp|var|etc|mnt|volumes)/)", value):
        raise ValueError("Unsupported personal state text")
    return value


class AppearanceData(StrictData):
    theme: Literal["light", "dark", "auto"] = "auto"
    transparency: int = Field(default=62, ge=20, le=90)
    blur: int = Field(default=18, ge=0, le=32)
    accent: Literal["blue", "purple", "mint", "pink", "orange"] = "blue"
    background: Literal["sky", "aurora", "minimal", "custom"] = "sky"


class NotificationEvents(StrictData):
    agentComplete: bool = True
    deviceOffline: bool = True
    automationFailure: bool = True
    budgetAlert: bool = False
    securityAlert: bool = True


class NotificationChannels(StrictData):
    desktop: bool = True
    email: bool = False
    telegram: bool = False
    webhook: bool = False


class NotificationData(StrictData):
    events: NotificationEvents = Field(default_factory=NotificationEvents)
    channels: NotificationChannels = Field(default_factory=NotificationChannels)


class PreferencesData(StrictData):
    schemaVersion: Literal[1] = 1
    theme: Literal["light", "dark", "system"] = "system"
    language: str = Field(default="zh-CN", min_length=2, max_length=20, pattern=r"^[a-zA-Z]{2,3}(?:-[a-zA-Z0-9]{2,8})*$")
    timezone: str = Field(default="Asia/Shanghai", min_length=1, max_length=80)
    appearance: AppearanceData = Field(default_factory=AppearanceData)
    notifications: NotificationData = Field(default_factory=NotificationData)

    @field_validator("timezone")
    @classmethod
    def timezone_name(cls, value):
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        try:
            ZoneInfo(value)
        except (ValueError, ZoneInfoNotFoundError):
            raise ValueError("Unsupported timezone") from None
        return value


def project(schema, values):
    """Recursive allowlist used for legacy/local-only mixed dictionaries."""
    values = values if isinstance(values, dict) else {}
    result = {}
    for key, field in schema.model_fields.items():
        if key not in values:
            continue
        annotation = field.annotation
        value = values[key]
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            result[key] = project(annotation, value)
        else:
            result[key] = value
    # Invalid legacy allowed values fall back to defaults individually. Unknown
    # fields never survive, including nested ones. New writes validate strictly.
    for _ in range(len(result) + 1):
        try:
            return schema.model_validate(result).model_dump(mode="json")
        except ValidationError as error:
            invalid = {entry["loc"][0] for entry in error.errors()}
            if not invalid & result.keys():
                raise
            for key in invalid:
                result.pop(key, None)
    raise ValueError("Invalid personal state")


CATALOG = Layout.model_validate_json(resource_path(
    "dashboard.json", Path(__file__).parents[4] / "src" / "data" / "dashboard.json"
).read_text(encoding="utf-8"))
WIDGETS = {widget.id: widget for widget in CATALOG.widgets}


class CanvasPosition(StrictData):
    x: int = Field(ge=0, le=1284)
    y: int = Field(ge=0, le=20000)


class CanvasSize(StrictData):
    width: int = Field(ge=100, le=1284)
    height: int = Field(ge=100, le=2000)


class WidgetData(StrictData):
    id: str
    position: CanvasPosition
    size: CanvasSize

    @model_validator(mode="after")
    def known_widget(self):
        if self.id not in WIDGETS or self.position.x + self.size.width > 1284:
            raise ValueError("Unsupported widget layout")
        return self


class DashboardData(StrictData):
    schemaVersion: Literal[1] = 1
    widgets: list[WidgetData] = Field(max_length=100)

    @model_validator(mode="after")
    def unique_widgets(self):
        if len({widget.id for widget in self.widgets}) != len(self.widgets):
            raise ValueError("Duplicate widget key")
        return self


class TriggerConfig(StrictData):
    label: str = Field(default="", max_length=500)
    cron: str = Field(default="", max_length=120)

    @field_validator("label", "cron")
    @classmethod
    def safe_value(cls, value):
        return safe_text(value)


class WorkflowNode(StrictData):
    kind: Literal["WHEN", "IF", "DO"]
    label: str = Field(default="", max_length=120)
    text: str = Field(default="", max_length=500)
    detail: str = Field(default="", max_length=500)

    @field_validator("label", "text", "detail")
    @classmethod
    def safe_value(cls, value):
        return safe_text(value)


class AutomationData(StrictData):
    schemaVersion: Literal[1] = 1
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    enabled: bool = True
    triggerType: Literal["manual", "schedule", "device_status", "agent_event", "webhook"] = "manual"
    triggerConfigJson: TriggerConfig = Field(default_factory=TriggerConfig)
    workflowJson: list[WorkflowNode] = Field(default_factory=list, max_length=100)

    @field_validator("name", "description")
    @classmethod
    def safe_value(cls, value):
        value = safe_text(value).strip()
        return value


class SingletonAdapter(SyncAdapter):
    def accepts_initial_upsert(self, item):
        # A built-in default row has never entered authority. The first real
        # edit adopts it in place, rather than conflicting with its defaults.
        return item.sync_revision == 0

    def entity_id(self, item=None):
        return str(uuid5(NAMESPACE_URL, "nexa:personal-state:" + self.entity_type))

    def identity_error(self, entity_id, operation):
        if entity_id != self.entity_id():
            return "invalid_id"
        if operation == "delete":
            return "delete_unsupported"

    def find(self, db, entity_id, workspace_id):
        if entity_id != self.entity_id():
            return None
        return db.scalar(select(self.model).where(self.model.workspace_id == workspace_id)
                         .execution_options(populate_existing=True))

    def create(self, db, entity_id, user_id, workspace_id, data):
        return self.model(user_id=user_id, workspace_id=workspace_id)


class PreferencesAdapter(SingletonAdapter):
    def legacy_rows(self, db, workspace_id):
        return [item for item in super().legacy_rows(db, workspace_id)
                if self.serialize(item) != PreferencesData().model_dump(mode="json")]

    def serialize(self, item):
        values = {key: getattr(item, key) for key in ("theme", "language", "timezone")}
        extra = item.settings_json or {}
        values.update({key: extra.get(key, {}) for key in ("appearance", "notifications")})
        return project(PreferencesData, values)

    def apply_data(self, item, data):
        for key in ("theme", "language", "timezone"):
            setattr(item, key, getattr(data, key))
        item.settings_json = {**(item.settings_json or {}),
                              "appearance": data.appearance.model_dump(mode="json"),
                              "notifications": data.notifications.model_dump(mode="json")}


class DashboardAdapter(SingletonAdapter):
    def legacy_rows(self, db, workspace_id):
        default = DashboardData(widgets=[{key: widget.model_dump()[key] for key in ("id", "position", "size")}
                                        for widget in CATALOG.widgets]).model_dump(mode="json")
        return [item for item in super().legacy_rows(db, workspace_id) if self.serialize(item) != default]

    def serialize(self, item):
        # No arbitrary titles, icons, URLs or configuration blobs. Current
        # widgets have no user-configurable per-widget fields in the product.
        widgets = [{key: widget[key] for key in ("id", "position", "size")}
                   for widget in (item.layout_json or {}).get("widgets", [])
                   if widget.get("id") in WIDGETS]
        return DashboardData(widgets=widgets).model_dump(mode="json")

    def apply_data(self, item, data):
        item.layout_json = {"widgets": [dict(WIDGETS[widget.id].model_dump(mode="json"),
            position=widget.position.model_dump(), size=widget.size.model_dump()) for widget in data.widgets]}


class AutomationAdapter(SyncAdapter):
    def serialize(self, item):
        # Project mixed legacy blobs before validation; unsupported data remains
        # local and is never included in history, outbox or conflict snapshots.
        data = {key: getattr(item, attr) for key, attr in self.fields.items()}
        data["triggerConfigJson"] = project(TriggerConfig, data["triggerConfigJson"])
        nodes = []
        for node in data["workflowJson"]:
            try:
                nodes.append(project(WorkflowNode, node))
            except ValueError:
                continue
        data["workflowJson"] = nodes
        for key in ("name", "description"):
            try:
                safe_text(data[key])
            except ValueError:
                data[key] = "Automation" if key == "name" else ""
        return AutomationData.model_validate(data).model_dump(mode="json")

    def apply_data(self, item, data):
        for key, attr in self.fields.items():
            value = getattr(data, key)
            if isinstance(value, BaseModel):
                value = value.model_dump(mode="json")
            elif isinstance(value, list):
                value = [node.model_dump(mode="json") for node in value]
            setattr(item, attr, value)


ADAPTERS = [
    PreferencesAdapter("user.preferences", UserPreference, PreferencesData, {}, 30, 3),
    DashboardAdapter("dashboard.layout", Dashboard, DashboardData, {}, 31, 3),
    AutomationAdapter("automation.definition", AutomationWorkflow, AutomationData,
        {"name": "name", "description": "description", "enabled": "enabled", "triggerType": "trigger_type",
         "triggerConfigJson": "trigger_config_json", "workflowJson": "workflow_json"}, 32, 3),
]
