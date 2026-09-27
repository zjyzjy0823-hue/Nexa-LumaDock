from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=80, pattern=r"^[\w-]+$")
    password: str = Field(min_length=8, max_length=256)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        return value.strip()


class UserLogin(BaseModel):
    username: str
    password: str


class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    avatar: str | None
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class Position(BaseModel):
    x: int = Field(ge=0, le=5000)
    y: int = Field(ge=0, le=20000)


class Size(BaseModel):
    width: int = Field(ge=100, le=2000)
    height: int = Field(ge=100, le=2000)


class Widget(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    type: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=120)
    icon: str = Field(default="", max_length=100)
    size: Size
    position: Position
    config: dict[str, Any] = Field(default_factory=dict)
    datasource: str | None = None


class Layout(BaseModel):
    widgets: list[Widget] = Field(max_length=100)

    @model_validator(mode="after")
    def unique_ids(self) -> "Layout":
        ids = [widget.id for widget in self.widgets]
        if len(ids) != len(set(ids)):
            raise ValueError("Widget IDs must be unique")
        return self


class DashboardPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    name: str
    layout_json: Layout
    created_at: datetime
    updated_at: datetime
