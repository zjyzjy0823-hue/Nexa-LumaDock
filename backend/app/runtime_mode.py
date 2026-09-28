"""Endpoint boundaries between the shared Local and Core application."""

from fastapi import HTTPException

from .database import runtime_config


def require_core_mode() -> None:
    if runtime_config.mode != "core":
        raise HTTPException(404, "Endpoint requires Nexa Core")


def require_local_mode() -> None:
    if runtime_config.mode != "local":
        raise HTTPException(404, "Endpoint requires Nexa Local")
