import logging
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from alembic import command
from alembic.config import Config

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from .api import api_keys, auth, clients, dashboard, ledger, settings, workspace
from .api.agents.routes import router as agents_router, legacy_router as legacy_agents_router, runtime_router as agent_runtime_router
from .api.automation.routes import router as automation_router, v1_router as v1_automation_router
from .api.data.routes import router as data_router, v1_router as v1_data_router
from .api.devices.routes import router as devices_router, legacy_router as legacy_devices_router, runtime_router as device_runtime_router
from .api.websites import router as websites_router
from .realtime.events import Event
from .resources import resource_path
from .config import load_runtime_config

logger = logging.getLogger(__name__)
runtime_config = load_runtime_config()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    config = Config(str(resource_path("alembic.ini", Path(__file__).parents[1] / "alembic.ini")))
    config.set_main_option("script_location", str(resource_path("migrations", Path(__file__).parents[1] / "migrations")))
    logger.info("Running database migrations")
    command.upgrade(config, "head")
    logger.info("Database migrations completed")
    yield


app = FastAPI(title="Nexa API", version="0.5.1", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(runtime_config.cors_origins),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)
for router in (
    auth.router, auth.v1_router, dashboard.router, api_keys.router, websites_router,
    devices_router, legacy_devices_router, device_runtime_router, agents_router, legacy_agents_router, agent_runtime_router, data_router, automation_router,
    v1_data_router, v1_automation_router, settings.router, ledger.router,
    workspace.router, clients.router,
):
    app.include_router(router)


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "nexa", "version": "0.5.1"}


@app.exception_handler(RequestValidationError)
async def validation_error(_request: Request, exc: RequestValidationError):
    details = [{"field": ".".join(map(str, error["loc"])), "message": error["msg"]} for error in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": details, "error": {"code": "validation_error", "message": "Invalid request", "details": details}})


@app.exception_handler(HTTPException)
async def http_error(_request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail, "error": {"code": "request_error", "message": str(exc.detail)}})


@app.exception_handler(Exception)
async def api_error(request: Request, exc: Exception):
    logger.error("Unhandled API error on %s %s", request.method, request.url.path,
                 exc_info=(type(exc), exc, exc.__traceback__))
    return JSONResponse(status_code=500, content={"error": {"code": "internal_error", "message": "Internal server error"}})


@app.websocket("/ws")
async def websocket_entry(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            message = await websocket.receive_json()
            if isinstance(message, dict) and message.get("type") == "ping":
                payload = message.get("payload")
                event = Event(type="pong", source="nexa", timestamp=datetime.now(ZoneInfo(runtime_config.app_timezone)), payload=payload if isinstance(payload, dict) else {})
                await websocket.send_json(event.model_dump(mode="json"))
    except WebSocketDisconnect:
        pass
