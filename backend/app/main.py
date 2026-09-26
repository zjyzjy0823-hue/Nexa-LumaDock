import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import auth, dashboard
from .api.agents.routes import router as agents_router
from .api.automation.routes import router as automation_router
from .api.data.routes import router as data_router
from .api.devices.routes import router as devices_router
from .database import Base, engine


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="Nexa API", version="0.2.0", lifespan=lifespan)
origins = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in origins],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["Authorization", "Content-Type"],
)
for router in (
    auth.router, dashboard.router, devices_router, agents_router, data_router, automation_router,
):
    app.include_router(router)
