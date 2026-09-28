"""Nexa Core host for the shared FastAPI application."""

import os
from typing import Mapping

from app.config import load_runtime_config


def core_bind(environ: Mapping[str, str] | None = None) -> tuple[str, int]:
    values = os.environ if environ is None else environ
    if load_runtime_config(values).mode != "core":
        raise RuntimeError("core_entry requires NEXA_MODE=core")
    host = values.get("NEXA_HOST", "0.0.0.0").strip()
    if not host:
        raise RuntimeError("NEXA_HOST must not be empty")
    try:
        port = int(values.get("NEXA_PORT", "8000"))
    except ValueError:
        raise RuntimeError("NEXA_PORT must be an integer from 1 to 65535") from None
    if not 1 <= port <= 65535:
        raise RuntimeError("NEXA_PORT must be an integer from 1 to 65535")
    return host, port


def main() -> None:
    from dotenv import load_dotenv
    load_dotenv()
    try:
        host, port = core_bind()
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from None

    import uvicorn
    uvicorn.run("app.main:app", host=host, port=port)


if __name__ == "__main__":
    main()
