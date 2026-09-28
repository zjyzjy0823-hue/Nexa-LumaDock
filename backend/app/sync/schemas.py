from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CategoryData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    type: Literal["income", "expense"]
    icon: str = Field(default="shopping", max_length=30)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Name is required")
        return value


class TransactionData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    categoryId: str | None = None
    type: Literal["income", "expense"]
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    description: str = Field(min_length=1, max_length=200)
    merchant: str = Field(default="", max_length=120)
    note: str = Field(default="", max_length=500)
    occurredAt: datetime

    @field_validator("amount", mode="before")
    @classmethod
    def decimal_string(cls, value):
        if not isinstance(value, str):
            raise ValueError("Amount must be a decimal string")
        return value
