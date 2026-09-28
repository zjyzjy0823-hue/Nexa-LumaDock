"""Shared startup configuration for the local and Core hosts."""

import os
from dataclasses import dataclass, field
from typing import Literal, Mapping

from dotenv import load_dotenv
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


LOCAL_DATABASE_URL = "sqlite:///./nexa.db"
LOCAL_CORS_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"


@dataclass(frozen=True)
class RuntimeConfig:
    mode: Literal["local", "core"]
    database_url: str = field(repr=False)
    jwt_secret: str = field(repr=False)
    cors_origins: tuple[str, ...]
    app_timezone: str
    allow_registration: bool


def load_runtime_config(environ: Mapping[str, str] | None = None) -> RuntimeConfig:
    if environ is None:
        load_dotenv()
        environ = os.environ

    mode = environ.get("NEXA_MODE", "local").strip().lower()
    if mode not in ("local", "core"):
        raise RuntimeError(f"Unsupported NEXA_MODE: {mode}")

    database_url = environ.get("DATABASE_URL", "")
    if mode == "core":
        if not database_url:
            raise RuntimeError("Core mode requires PostgreSQL DATABASE_URL")
        try:
            url = make_url(database_url)
            driver = url.drivername
            _ = url.port
        except (ArgumentError, ValueError):
            raise RuntimeError("Core mode requires PostgreSQL DATABASE_URL") from None
        if driver != "postgresql+psycopg":
            raise RuntimeError("Core mode requires PostgreSQL DATABASE_URL (postgresql+psycopg)")
    else:
        database_url = database_url or LOCAL_DATABASE_URL
        try:
            driver = make_url(database_url).drivername
        except (ArgumentError, ValueError):
            raise RuntimeError("Local mode requires SQLite DATABASE_URL") from None
        if driver != "sqlite":
            raise RuntimeError("Local mode requires SQLite DATABASE_URL")

    jwt_secret = environ.get("JWT_SECRET", "")
    if len(jwt_secret) < 16:
        raise RuntimeError("JWT_SECRET must be set to a secret of at least 16 characters")

    origins = tuple(origin.strip() for origin in environ.get(
        "CORS_ORIGINS", LOCAL_CORS_ORIGINS if mode == "local" else ""
    ).split(",") if origin.strip())
    if mode == "core" and "*" in origins:
        raise RuntimeError("Core mode does not allow wildcard CORS_ORIGINS")

    return RuntimeConfig(
        mode=mode,
        database_url=database_url,
        jwt_secret=jwt_secret,
        cors_origins=origins,
        app_timezone=environ.get("APP_TIMEZONE", "Asia/Shanghai"),
        allow_registration=environ.get("ALLOW_REGISTRATION", "true").lower() == "true",
    )
