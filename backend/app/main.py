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

from .api import api_keys, auth, client_runtime, clients, core, dashboard, ledger, settings, sync, workspace
from .api.agents.routes import router as agents_router, legacy_router as legacy_agents_router, runtime_router as agent_runtime_router
from .api.automation.routes import router as automation_router, v1_router as v1_automation_router
from .api.data.routes import router as data_router, v1_router as v1_data_router
from .api.devices.routes import router as devices_router, legacy_router as legacy_devices_router, runtime_router as device_runtime_router
from .api.websites import router as websites_router
from .api.agent_actions import router as agent_actions_router
from .realtime.events import Event
from .resources import resource_path
from .config import load_runtime_config
from .database import SessionLocal, engine
from .sync.background import BackgroundSyncCoordinator, BackgroundSyncConfig
from .sync.notifications import register_coordinator, unregister_coordinator

logger = logging.getLogger(__name__)
runtime_config = load_runtime_config()
APP_VERSION = "0.5.9"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    config = Config(str(resource_path("alembic.ini", Path(__file__).parents[1] / "alembic.ini")))
    config.set_main_option("script_location", str(resource_path("migrations", Path(__file__).parents[1] / "migrations")))
    logger.info("Running database migrations")
    command.upgrade(config, "head")
    logger.info("Database migrations completed")
    coordinator = None
    if runtime_config.mode == "local":
        # The Desktop sidecar runs a single Uvicorn worker. Scheduling belongs
        # to this lifespan, never to imports or a separate daemon process.
        coordinator = BackgroundSyncCoordinator(SessionLocal, config=BackgroundSyncConfig.from_env())
        register_coordinator(engine, coordinator)
        _app.state.background_sync = coordinator
        coordinator.start()
    try:
        yield
    finally:
        if coordinator is not None:
            unregister_coordinator(engine, coordinator)
            await coordinator.stop()
            _app.state.background_sync = None


app = FastAPI(title="Nexa API", version=APP_VERSION, lifespan=lifespan)
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
    workspace.router, clients.router, client_runtime.router, core.router, sync.router, agent_actions_router,
):
    app.include_router(router)


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "nexa", "version": APP_VERSION}


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
