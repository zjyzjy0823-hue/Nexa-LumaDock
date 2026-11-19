"""统一定时任务（/api/v1/scheduler）REST 路由。"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..security import current_user
from . import service
from .schemas import (
    RemoteCronCreateInput,
    RemoteCronPauseInput,
    RemoteCronRunInput,
    RemoteCronRunsResponseOut,
    RemoteCronUpdateInput,
    UnifiedJobOut,
    UnifiedJobRunOut,
    UnifiedJobsOverviewOut,
)


router = APIRouter(prefix="/api/v1/scheduler", tags=["scheduler"])


@router.get("/jobs", response_model=UnifiedJobsOverviewOut)
async def list_jobs(
    owner: Literal["all", "studiolo", "openclaw", "hermes"] = Query(default="all"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    return await service.list_unified_jobs(db, user, owner_filter=owner)


@router.post("/jobs", response_model=UnifiedJobOut, status_code=201)
async def create_remote_job(
    payload: RemoteCronCreateInput,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    return await service.create_remote_job(db, user, payload)


@router.put("/jobs/{owner_type}/{instance_id}/{native_job_id}", response_model=UnifiedJobOut)
async def update_remote_job(
    owner_type: Literal["openclaw", "hermes"],
    instance_id: str,
    native_job_id: str,
    payload: RemoteCronUpdateInput,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    return await service.update_remote_job(db, user, owner_type, instance_id, native_job_id, payload)


@router.post("/jobs/{owner_type}/{instance_id}/{native_job_id}/pause", response_model=UnifiedJobOut)
async def pause_remote_job(
    owner_type: Literal["openclaw", "hermes"],
    instance_id: str,
    native_job_id: str,
    payload: RemoteCronPauseInput,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    return await service.pause_remote_job(db, user, owner_type, instance_id, native_job_id, payload)


@router.post("/jobs/{owner_type}/{instance_id}/{native_job_id}/run", response_model=UnifiedJobRunOut)
async def run_remote_job(
    owner_type: Literal["openclaw", "hermes"],
    instance_id: str,
    native_job_id: str,
    payload: RemoteCronRunInput,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    return await service.run_remote_job_now(db, user, owner_type, instance_id, native_job_id, payload)


@router.delete("/jobs/{owner_type}/{instance_id}/{native_job_id}", status_code=204)
async def delete_remote_job(
    owner_type: Literal["openclaw", "hermes"],
    instance_id: str,
    native_job_id: str,
    profile: str = Query(default="default"),
    confirmed: bool = Query(default=False),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    await service.delete_remote_job(
        db,
        user,
        owner_type,
        instance_id,
        native_job_id,
        profile=profile,
        confirmed=confirmed,
    )
    return Response(status_code=204)


@router.get("/jobs/{owner_type}/{instance_id}/{native_job_id}/runs", response_model=RemoteCronRunsResponseOut)
async def list_job_runs(
    owner_type: Literal["studiolo", "openclaw", "hermes"],
    instance_id: str,
    native_job_id: str,
    profile: str = Query(default="default"),
    limit: int = Query(default=20, ge=1, le=100),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    return await service.list_job_runs(
        db,
        user,
        owner_type,
        instance_id,
        native_job_id,
        profile=profile,
        limit=limit,
    )
