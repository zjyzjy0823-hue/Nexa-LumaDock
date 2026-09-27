from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class Event(BaseModel):
    type: str
    source: str
    timestamp: datetime
    payload: dict[str, Any] = Field(default_factory=dict)
