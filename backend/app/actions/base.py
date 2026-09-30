from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

DataScope = Literal[
    "ledger:read",
    "ledger:write",
    "ledger:delete",
    "websites:read",
    "websites:write",
    "websites:delete",
    "data:read",
    "data:write",
    "data:delete",
]


class Arguments(BaseModel):
    model_config = ConfigDict(
        extra="forbid", alias_generator=to_camel, populate_by_name=True
    )


class Envelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    actionId: UUID | None = None
    action: str = Field(min_length=1, max_length=80)
    arguments: dict


class IdArguments(Arguments):
    id: UUID


class MonthArguments(Arguments):
    month: str | None = Field(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
