"""统一定时任务（Cron）管理 Pydantic v2 契约模型。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


OwnerType = Literal["studiolo", "openclaw", "hermes"]
HistoryMode = Literal["paginated", "recent_only", "last_only", "unavailable"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class JobRef(StrictModel):
    """跨三类所有者的稳定联合主键。"""
    workspaceId: str
    ownerType: OwnerType
    ownerInstanceId: str
    ownerProfile: str = "default"
    nativeJobId: str


class CronCapabilitiesOut(StrictModel):
    supported: bool
    canCreate: bool
    canUpdate: bool
    canDelete: bool
    canPause: bool
    canRunNow: bool
    historyMode: HistoryMode
    supportsProfiles: bool = False


class OwnerInstanceOut(StrictModel):
    ownerType: OwnerType
    ownerInstanceId: str
    label: str
    status: Literal["online", "offline", "degraded"]
    note: str = ""
    capabilities: CronCapabilitiesOut


class UnifiedJobOut(StrictModel):
    ref: JobRef
    ownerLabel: str
    ownerStatus: Literal["online", "offline", "degraded"]
    name: str
    description: str = ""
    enabled: bool
    scheduleKind: str
    scheduleExpression: str
    timezone: str
    nextRunAt: str | None = None
    lastRunAt: str | None = None
    lastStatus: str = "unknown"
    nativeRevision: str = ""
    highImpact: bool = False
    requiresManualSpaceUnlock: bool = False
    capabilities: CronCapabilitiesOut


class UnifiedJobRunOut(StrictModel):
    nativeRunId: str
    scheduledAt: str | None = None
    startedAt: str | None = None
    finishedAt: str | None = None
    status: Literal["queued", "running", "succeeded", "failed", "skipped", "cancelled", "waiting_manual_unlock", "unknown"]
    nativeStatus: str
    summary: str = ""


class UnifiedJobsOverviewOut(StrictModel):
    instances: list[OwnerInstanceOut]
    jobs: list[UnifiedJobOut]


class RemoteCronCreateInput(StrictModel):
    ownerType: Literal["openclaw", "hermes"]
    ownerInstanceId: str = Field(min_length=1, max_length=64)
    ownerProfile: str = Field(default="default", min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    enabled: bool = True
    scheduleKind: Literal["cron", "interval", "once"] = "cron"
    scheduleExpression: str = Field(min_length=1, max_length=120)
    timezone: str = Field(default="Asia/Shanghai", min_length=1, max_length=64)
    prompt: str = Field(default="", max_length=4000)


class RemoteCronUpdateInput(StrictModel):
    ownerProfile: str = Field(default="default", min_length=1, max_length=64)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    enabled: bool | None = None
    scheduleKind: Literal["cron", "interval", "once"] | None = None
    scheduleExpression: str | None = Field(default=None, min_length=1, max_length=120)
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    prompt: str | None = Field(default=None, max_length=4000)
    expectedRevision: str | None = Field(default=None, max_length=120)


class RemoteCronPauseInput(StrictModel):
    paused: bool
    ownerProfile: str = Field(default="default", min_length=1, max_length=64)


class RemoteCronRunInput(StrictModel):
    requestId: str = Field(min_length=1, max_length=64)
    ownerProfile: str = Field(default="default", min_length=1, max_length=64)
    confirmed: bool = False


class RemoteCronRunsResponseOut(StrictModel):
    ref: JobRef
    historyMode: HistoryMode
    historyUnavailable: bool = False
    note: str = ""
    runs: list[UnifiedJobRunOut]
