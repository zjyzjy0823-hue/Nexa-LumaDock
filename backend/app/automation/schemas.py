from datetime import datetime
import json
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Schedule(Strict):
    type: Literal["once", "daily", "weekly", "interval"]
    timezone: str
    at: datetime | None = None
    time: str = Field(default="22:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    weekdays: list[int] = Field(default_factory=lambda: [0], min_length=1, max_length=7)
    seconds: int = Field(default=3600, ge=10, le=31536000)
    catch_up: Literal["skip", "catch_up_once"] = "catch_up_once"

    @model_validator(mode="after")
    def valid(self):
        try:
            ZoneInfo(self.timezone)
        except (ValueError, ZoneInfoNotFoundError):
            raise ValueError("Invalid IANA timezone") from None
        if any(day < 0 or day > 6 for day in self.weekdays):
            raise ValueError("Invalid weekday")
        if self.type in ("once", "interval") and (self.at is None or self.at.tzinfo is None):
            raise ValueError("An explicit offset-aware anchor is required")
        return self


class Action(Strict):
    type: Literal["ledger.create", "data.create", "data.update", "agent.run", "webhook.post"]
    config: dict

    @model_validator(mode="after")
    def valid(self):
        from ..services.ledger import TransactionInput
        from ..services.data import RecordInput, RecordPatch
        schemas = {"ledger.create": TransactionInput, "data.create": RecordInput,
                   "data.update": RecordPatch, "agent.run": AgentRun, "webhook.post": Webhook}
        schema = schemas[self.type]
        values = dict(self.config)
        reference = {}
        ref_key = {"data.create": "collection_id", "data.update": "record_id"}.get(self.type)
        if ref_key:
            ref = values.pop(ref_key, None)
            if not isinstance(ref, str) or not 1 <= len(ref) <= 36:
                raise ValueError("Entity reference required")
            reference[ref_key] = ref
        if set(values) - set(schema.model_fields):
            raise ValueError("Unsupported action fields")
        # Store the normalized, explicitly allowed definition only.
        self.config = {**schema.model_validate(values).model_dump(mode="json"), **reference}
        from ..sync.adapters.personal_state import safe_text
        def check(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    normalized = key.lower().replace("-", "").replace("_", "")
                    if (any(word in normalized for word in ("authorization", "password", "secret", "credential"))
                            or normalized.endswith(("token", "apikey")) or normalized in {"jwt", "cookie"}):
                        raise ValueError("Secrets cannot enter automation definitions")
                    safe_text(key)
                    check(child)
            elif isinstance(value, list):
                for child in value:
                    check(child)
            elif isinstance(value, str):
                safe_text(value)
        check(self.config)
        if len(json.dumps(self.config)) > 32768:
            raise ValueError("Action configuration too large")
        return self


class AgentRun(Strict):
    agent_id: str = Field(min_length=1, max_length=36)
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=500)


class Webhook(Strict):
    url: str = Field(max_length=2048)
    headers: dict[str, str] = Field(default_factory=dict)
    body: dict = Field(default_factory=dict)
    timeout: int = Field(default=10, ge=1, le=30)

    @model_validator(mode="after")
    def valid(self):
        from .webhook import validate_url
        validate_url(self.url)
        for key, value in self.headers.items():
            if key.lower() not in {"accept", "content-type", "user-agent"} or "\r" in value or "\n" in value or len(value) > 256:
                raise ValueError("Only non-secret headers are supported")
        return self
