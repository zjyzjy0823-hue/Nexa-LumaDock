"""统一定时任务（Cron）单所有者聚合、远端 CronPort 路由与脱敏服务。"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..fleet.hub import fleet_hub
from ..models import (
    AgentNode,
    AutomationExecution,
    AutomationScheduleState,
    AutomationWorkflow,
    User,
)
from ..utils.time import iso_utc
from ..workspaces import get_personal_workspace
from .sanitize import (
    sanitize_summary,
    workflow_is_high_impact,
    workflow_requires_manual_space_unlock,
)
from .schemas import (
    CronCapabilitiesOut,
    JobRef,
    OwnerInstanceOut,
    RemoteCronCreateInput,
    RemoteCronPauseInput,
    RemoteCronRunInput,
    RemoteCronRunsResponseOut,
    RemoteCronUpdateInput,
    UnifiedJobOut,
    UnifiedJobRunOut,
    UnifiedJobsOverviewOut,
)


_READONLY_OFFLINE_CAPS = CronCapabilitiesOut(
    supported=False,
    canCreate=False,
    canUpdate=False,
    canDelete=False,
    canPause=False,
    canRunNow=False,
    historyMode="unavailable",
    supportsProfiles=False,
)

_STUDIOLO_CAPS = CronCapabilitiesOut(
    supported=True,
    canCreate=True,
    canUpdate=True,
    canDelete=True,
    canPause=True,
    canRunNow=True,
    historyMode="paginated",
    supportsProfiles=False,
)


def _normalize_run_status(raw: str) -> Literal[
    "queued", "running", "succeeded", "failed", "skipped", "cancelled", "waiting_manual_unlock", "unknown"
]:
    low = (raw or "").strip().lower()
    if low in ("queued", "pending", "claimed"):
        return "queued"
    if low in ("running", "in_progress"):
        return "running"
    if low in ("succeeded", "success", "ok", "completed"):
        return "succeeded"
    if low in ("failed", "error"):
        return "failed"
    if low == "skipped":
        return "skipped"
    if low in ("cancelled", "canceled"):
        return "cancelled"
    if low == "waiting_manual_unlock":
        return "waiting_manual_unlock"
    return "unknown"


def _studiolo_schedule_expr(workflow: AutomationWorkflow) -> tuple[str, str, str]:
    cfg = workflow.trigger_config_json if isinstance(workflow.trigger_config_json, dict) else {}
    sched = cfg.get("schedule") if isinstance(cfg.get("schedule"), dict) else {}
    tz = str(sched.get("timezone") or "Asia/Shanghai")
    if workflow.trigger_type != "schedule":
        return workflow.trigger_type, workflow.trigger_type, tz
    stype = str(sched.get("type") or "daily")
    if stype == "daily":
        return "daily", f"daily @ {sched.get('time', '00:00')}", tz
    if stype == "weekly":
        days = ",".join(str(d) for d in (sched.get("weekdays") or []))
        return "weekly", f"weekly[{days}] @ {sched.get('time', '00:00')}", tz
    if stype == "interval":
        return "interval", f"every {sched.get('seconds', 3600)}s", tz
    if stype == "once":
        return "once", str(sched.get("at") or "once"), tz
    return stype, str(sched.get("cron") or stype), tz


def _collect_studiolo_jobs(db: Session, workspace_id: str) -> list[UnifiedJobOut]:
    workflows = list(
        db.scalars(
            select(AutomationWorkflow)
            .where(
                AutomationWorkflow.workspace_id == workspace_id,
                AutomationWorkflow.deleted_at.is_(None),
            )
            .order_by(AutomationWorkflow.updated_at.desc())
        )
    )
    out: list[UnifiedJobOut] = []
    for wf in workflows:
        sched_state = db.scalar(
            select(AutomationScheduleState).where(AutomationScheduleState.workflow_id == wf.id)
        )
        last_exec = db.scalar(
            select(AutomationExecution)
            .where(AutomationExecution.workflow_id == wf.id)
            .order_by(AutomationExecution.started_at.desc())
            .limit(1)
        )
        kind, expr, tz = _studiolo_schedule_expr(wf)
        needs_unlock = workflow_requires_manual_space_unlock(wf.workflow_json)
        high_impact = workflow_is_high_impact(wf.workflow_json)
        last_status = (
            "waiting_manual_unlock"
            if needs_unlock
            else (_normalize_run_status(last_exec.status) if last_exec else "unknown")
        )
        out.append(
            UnifiedJobOut(
                ref=JobRef(
                    workspaceId=workspace_id,
                    ownerType="studiolo",
                    ownerInstanceId="core",
                    ownerProfile="default",
                    nativeJobId=wf.id,
                ),
                ownerLabel="Studiolo Core",
                ownerStatus="online",
                name=wf.name,
                description=sanitize_summary(wf.description),
                enabled=bool(wf.enabled),
                scheduleKind=kind,
                scheduleExpression=expr,
                timezone=tz,
                nextRunAt=iso_utc(sched_state.next_run_at) if (sched_state and sched_state.next_run_at) else None,
                lastRunAt=iso_utc(last_exec.started_at) if last_exec else None,
                lastStatus=last_status,
                nativeRevision=str(wf.sync_revision),
                highImpact=high_impact,
                requiresManualSpaceUnlock=needs_unlock,
                capabilities=_STUDIOLO_CAPS,
            )
        )
    return out


def _node_providers(node: AgentNode, live_adapters: list[dict[str, Any]] | None = None) -> list[Literal["openclaw", "hermes"]]:
    raw = live_adapters if live_adapters is not None else (node.adapters_json or [])
    providers: list[Literal["openclaw", "hermes"]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        p = str(item.get("provider") or "").lower()
        if p in ("openclaw", "hermes") and p not in providers:
            providers.append(p)  # type: ignore[arg-type]
    return providers


def _parse_caps(raw: dict[str, Any] | None) -> CronCapabilitiesOut:
    if not isinstance(raw, dict):
        return _READONLY_OFFLINE_CAPS
    hm = str(raw.get("historyMode") or "unavailable")
    if hm not in ("paginated", "recent_only", "last_only", "unavailable"):
        hm = "unavailable"
    return CronCapabilitiesOut(
        supported=bool(raw.get("supported", False)),
        canCreate=bool(raw.get("canCreate", False)),
        canUpdate=bool(raw.get("canUpdate", False)),
        canDelete=bool(raw.get("canDelete", False)),
        canPause=bool(raw.get("canPause", False)),
        canRunNow=bool(raw.get("canRunNow", False)),
        historyMode=hm,  # type: ignore[arg-type]
        supportsProfiles=bool(raw.get("supportsProfiles", False)),
    )


def _remote_job_to_unified(
    *,
    workspace_id: str,
    owner_type: Literal["openclaw", "hermes"],
    node: AgentNode,
    raw: dict[str, Any],
    fallback_caps: CronCapabilitiesOut,
) -> UnifiedJobOut:
    caps = _parse_caps(raw.get("capabilities")) if isinstance(raw.get("capabilities"), dict) else fallback_caps
    native_id = str(raw.get("nativeJobId") or raw.get("id") or "")
    profile = str(raw.get("ownerProfile") or "default")
    return UnifiedJobOut(
        ref=JobRef(
            workspaceId=workspace_id,
            ownerType=owner_type,
            ownerInstanceId=node.id,
            ownerProfile=profile,
            nativeJobId=native_id,
        ),
        ownerLabel=f"{node.name} ({'OpenClaw' if owner_type == 'openclaw' else 'Hermes'})",
        ownerStatus="online",
        name=sanitize_summary(raw.get("name") or native_id, max_length=120),
        description=sanitize_summary(raw.get("description") or ""),
        enabled=bool(raw.get("enabled", True)),
        scheduleKind=str(raw.get("scheduleKind") or "cron"),
        scheduleExpression=str(raw.get("scheduleExpression") or ""),
        timezone=str(raw.get("timezone") or "UTC"),
        nextRunAt=raw.get("nextRunAt"),
        lastRunAt=raw.get("lastRunAt"),
        lastStatus=_normalize_run_status(str(raw.get("lastStatus") or "unknown")),
        nativeRevision=str(raw.get("nativeRevision") or ""),
        highImpact=True,
        requiresManualSpaceUnlock=False,
        capabilities=caps,
    )


async def list_unified_jobs(
    db: Session,
    user: User,
    *,
    owner_filter: str | None = None,
) -> UnifiedJobsOverviewOut:
    """按单所有者语义聚合 Studiolo Core、OpenClaw 与 Hermes 任务（离线节点不伪造、不接管）。"""
    ws = get_personal_workspace(db, user)
    instances: list[OwnerInstanceOut] = [
        OwnerInstanceOut(
            ownerType="studiolo",
            ownerInstanceId="core",
            label="Studiolo Core",
            status="online",
            note="原生自动化调度引擎，支持定时、数据变更、Agent 完成与手动触发",
            capabilities=_STUDIOLO_CAPS,
        )
    ]
    jobs: list[UnifiedJobOut] = []
    if owner_filter in (None, "", "all", "studiolo"):
        jobs.extend(_collect_studiolo_jobs(db, ws.id))

    nodes = list(
        db.scalars(
            select(AgentNode)
            .where(AgentNode.workspace_id == ws.id, AgentNode.revoked_at.is_(None))
            .order_by(AgentNode.created_at.asc())
        )
    )
    seen_refs: set[tuple[str, str, str, str]] = set()

    for node in nodes:
        online_conn = await fleet_hub.get_online_node(ws.id, node.id)
        providers = _node_providers(node, online_conn.adapters if online_conn else None)
        for provider in providers:
            if owner_filter not in (None, "", "all", provider):
                continue
            label = f"{node.name} ({'OpenClaw' if provider == 'openclaw' else 'Hermes'})"
            if online_conn is None:
                instances.append(
                    OwnerInstanceOut(
                        ownerType=provider,
                        ownerInstanceId=node.id,
                        label=label,
                        status="offline",
                        note="节点已离线：远端原生 Cron 仍由所有者按自身规则运行，离线时禁用写入且 Studiolo 不误接管",
                        capabilities=_READONLY_OFFLINE_CAPS,
                    )
                )
                continue

            rpc_res = await fleet_hub.call_node_rpc(
                ws.id,
                node.id,
                {"type": "cron.list", "provider": provider},
                timeout=8.0,
            )
            caps = _parse_caps(rpc_res.get("capabilities"))
            if not rpc_res.get("ok"):
                instances.append(
                    OwnerInstanceOut(
                        ownerType=provider,
                        ownerInstanceId=node.id,
                        label=label,
                        status="degraded",
                        note=sanitize_summary(rpc_res.get("error") or "远端 Cron 接口暂不可用"),
                        capabilities=caps,
                    )
                )
                continue

            instances.append(
                OwnerInstanceOut(
                    ownerType=provider,
                    ownerInstanceId=node.id,
                    label=label,
                    status="online",
                    note="在线，直接读写所有者原生 Cron",
                    capabilities=caps,
                )
            )
            for raw_job in rpc_res.get("jobs") or []:
                if not isinstance(raw_job, dict):
                    continue
                unified = _remote_job_to_unified(
                    workspace_id=ws.id,
                    owner_type=provider,
                    node=node,
                    raw=raw_job,
                    fallback_caps=caps,
                )
                dedup_key = (
                    unified.ref.ownerType,
                    unified.ref.ownerInstanceId,
                    unified.ref.ownerProfile,
                    unified.ref.nativeJobId,
                )
                if unified.ref.nativeJobId and dedup_key not in seen_refs:
                    seen_refs.add(dedup_key)
                    jobs.append(unified)

    return UnifiedJobsOverviewOut(instances=instances, jobs=jobs)


def _owned_remote_node(db: Session, workspace_id: str, node_id: str) -> AgentNode:
    node = db.scalar(
        select(AgentNode).where(
            AgentNode.id == node_id,
            AgentNode.workspace_id == workspace_id,
            AgentNode.revoked_at.is_(None),
        )
    )
    if node is None:
        raise HTTPException(404, "Remote scheduler node not found")
    return node


async def _require_online_rpc(
    ws_id: str,
    node: AgentNode,
    frame: dict[str, Any],
    *,
    timeout: float = 10.0,
) -> dict[str, Any]:
    res = await fleet_hub.call_node_rpc(ws_id, node.id, frame, timeout=timeout)
    if res.get("code") in ("node_offline", "node_disconnected"):
        raise HTTPException(503, "Remote owner node is offline; write disabled")
    if res.get("code") == "cron_unsupported":
        raise HTTPException(400, sanitize_summary(res.get("error") or "Remote owner does not support CronPort"))
    return res


async def create_remote_job(db: Session, user: User, payload: RemoteCronCreateInput) -> UnifiedJobOut:
    ws = get_personal_workspace(db, user)
    node = _owned_remote_node(db, ws.id, payload.ownerInstanceId)
    res = await _require_online_rpc(
        ws.id,
        node,
        {
            "type": "cron.create",
            "provider": payload.ownerType,
            "ownerProfile": payload.ownerProfile,
            "payload": payload.model_dump(mode="json"),
        },
    )
    if not res.get("ok"):
        raise HTTPException(502, sanitize_summary(res.get("error") or "Failed to create remote cron job"))
    return _remote_job_to_unified(
        workspace_id=ws.id,
        owner_type=payload.ownerType,
        node=node,
        raw=dict(res.get("job") or {}),
        fallback_caps=_parse_caps(res.get("capabilities")),
    )


async def update_remote_job(
    db: Session,
    user: User,
    owner_type: Literal["openclaw", "hermes"],
    instance_id: str,
    native_job_id: str,
    payload: RemoteCronUpdateInput,
) -> UnifiedJobOut:
    ws = get_personal_workspace(db, user)
    node = _owned_remote_node(db, ws.id, instance_id)
    res = await _require_online_rpc(
        ws.id,
        node,
        {
            "type": "cron.update",
            "provider": owner_type,
            "ownerProfile": payload.ownerProfile,
            "nativeJobId": native_job_id,
            "payload": payload.model_dump(mode="json", exclude_none=True),
        },
    )
    if not res.get("ok"):
        raise HTTPException(502, sanitize_summary(res.get("error") or "Failed to update remote cron job"))
    return _remote_job_to_unified(
        workspace_id=ws.id,
        owner_type=owner_type,
        node=node,
        raw=dict(res.get("job") or {"id": native_job_id}),
        fallback_caps=_parse_caps(res.get("capabilities")),
    )


async def pause_remote_job(
    db: Session,
    user: User,
    owner_type: Literal["openclaw", "hermes"],
    instance_id: str,
    native_job_id: str,
    payload: RemoteCronPauseInput,
) -> UnifiedJobOut:
    ws = get_personal_workspace(db, user)
    node = _owned_remote_node(db, ws.id, instance_id)
    res = await _require_online_rpc(
        ws.id,
        node,
        {
            "type": "cron.pause",
            "provider": owner_type,
            "ownerProfile": payload.ownerProfile,
            "nativeJobId": native_job_id,
            "paused": payload.paused,
        },
    )
    if not res.get("ok"):
        raise HTTPException(502, sanitize_summary(res.get("error") or "Failed to pause/resume remote cron job"))
    return _remote_job_to_unified(
        workspace_id=ws.id,
        owner_type=owner_type,
        node=node,
        raw=dict(res.get("job") or {"id": native_job_id, "enabled": not payload.paused}),
        fallback_caps=_parse_caps(res.get("capabilities")),
    )


async def run_remote_job_now(
    db: Session,
    user: User,
    owner_type: Literal["openclaw", "hermes"],
    instance_id: str,
    native_job_id: str,
    payload: RemoteCronRunInput,
) -> UnifiedJobRunOut:
    """手动触发远端原生 Cron：要求显式二次确认，超时或丢确认返回 unknown 而绝不自动重调。"""
    if not payload.confirmed:
        raise HTTPException(422, "Explicit confirmation (confirmed=true) is required to trigger remote cron job")
    ws = get_personal_workspace(db, user)
    node = _owned_remote_node(db, ws.id, instance_id)
    res = await fleet_hub.call_node_rpc(
        ws.id,
        node.id,
        {
            "type": "cron.run",
            "provider": owner_type,
            "ownerProfile": payload.ownerProfile,
            "nativeJobId": native_job_id,
            "requestId": payload.requestId,
        },
        timeout=10.0,
    )
    if res.get("code") == "node_offline":
        raise HTTPException(503, "Remote owner node is offline; trigger disabled")
    if res.get("code") in ("rpc_timeout", "node_disconnected"):
        # 丢确认防重调：返回 unknown 状态要求人工核对运行账本，绝不自动重试
        return UnifiedJobRunOut(
            nativeRunId=payload.requestId,
            status="unknown",
            nativeStatus=str(res.get("code")),
            summary="远端触发确认丢失，请先查询所有者运行账本确认是否已执行，切勿盲目重复触发。",
        )
    if not res.get("ok"):
        raise HTTPException(502, sanitize_summary(res.get("error") or "Failed to trigger remote cron job"))

    run = dict(res.get("run") or {})
    raw_st = str(run.get("status") or "queued")
    return UnifiedJobRunOut(
        nativeRunId=str(run.get("nativeRunId") or payload.requestId),
        scheduledAt=run.get("scheduledAt"),
        startedAt=run.get("startedAt"),
        finishedAt=run.get("finishedAt"),
        status=_normalize_run_status(raw_st),
        nativeStatus=str(run.get("nativeStatus") or raw_st),
        summary=sanitize_summary(run.get("summary") or ""),
    )


async def delete_remote_job(
    db: Session,
    user: User,
    owner_type: Literal["openclaw", "hermes"],
    instance_id: str,
    native_job_id: str,
    *,
    profile: str = "default",
    confirmed: bool = False,
) -> None:
    if not confirmed:
        raise HTTPException(422, "Explicit confirmation (confirmed=true) is required to delete remote cron job")
    ws = get_personal_workspace(db, user)
    node = _owned_remote_node(db, ws.id, instance_id)
    res = await _require_online_rpc(
        ws.id,
        node,
        {
            "type": "cron.delete",
            "provider": owner_type,
            "ownerProfile": profile,
            "nativeJobId": native_job_id,
        },
    )
    if not res.get("ok"):
        raise HTTPException(502, sanitize_summary(res.get("error") or "Failed to delete remote cron job"))


async def list_job_runs(
    db: Session,
    user: User,
    owner_type: Literal["studiolo", "openclaw", "hermes"],
    instance_id: str,
    native_job_id: str,
    *,
    profile: str = "default",
    limit: int = 20,
) -> RemoteCronRunsResponseOut:
    ws = get_personal_workspace(db, user)
    capped = max(1, min(limit, 100))
    ref = JobRef(
        workspaceId=ws.id,
        ownerType=owner_type,
        ownerInstanceId=instance_id,
        ownerProfile=profile,
        nativeJobId=native_job_id,
    )

    if owner_type == "studiolo":
        wf = db.scalar(
            select(AutomationWorkflow).where(
                AutomationWorkflow.id == native_job_id,
                AutomationWorkflow.workspace_id == ws.id,
                AutomationWorkflow.deleted_at.is_(None),
            )
        )
        if wf is None:
            raise HTTPException(404, "Studiolo workflow not found")
        needs_unlock = workflow_requires_manual_space_unlock(wf.workflow_json)
        rows = list(
            db.scalars(
                select(AutomationExecution)
                .where(AutomationExecution.workflow_id == wf.id)
                .order_by(AutomationExecution.started_at.desc())
                .limit(capped)
            )
        )
        runs = [
            UnifiedJobRunOut(
                nativeRunId=r.id,
                scheduledAt=iso_utc(r.scheduled_for) if r.scheduled_for else None,
                startedAt=iso_utc(r.started_at),
                finishedAt=iso_utc(r.finished_at) if r.finished_at else None,
                status="waiting_manual_unlock" if needs_unlock else _normalize_run_status(r.status),
                nativeStatus=r.status,
                summary=sanitize_summary(r.error_message or r.message or ""),
            )
            for r in rows
        ]
        return RemoteCronRunsResponseOut(ref=ref, historyMode="paginated", runs=runs)

    node = _owned_remote_node(db, ws.id, instance_id)
    res = await fleet_hub.call_node_rpc(
        ws.id,
        node.id,
        {
            "type": "cron.runs",
            "provider": owner_type,
            "ownerProfile": profile,
            "nativeJobId": native_job_id,
            "limit": capped,
        },
        timeout=8.0,
    )
    caps = _parse_caps(res.get("capabilities"))
    if not res.get("ok"):
        return RemoteCronRunsResponseOut(
            ref=ref,
            historyMode="unavailable",
            historyUnavailable=True,
            note=sanitize_summary(res.get("error") or "无法获取远端运行历史"),
            runs=[],
        )

    runs = [
        UnifiedJobRunOut(
            nativeRunId=str(item.get("nativeRunId") or ""),
            scheduledAt=item.get("scheduledAt"),
            startedAt=item.get("startedAt"),
            finishedAt=item.get("finishedAt"),
            status=_normalize_run_status(str(item.get("status") or "unknown")),
            nativeStatus=str(item.get("nativeStatus") or item.get("status") or "unknown"),
            summary=sanitize_summary(item.get("summary") or ""),
        )
        for item in (res.get("runs") or [])[:capped]
        if isinstance(item, dict)
    ]
    return RemoteCronRunsResponseOut(
        ref=ref,
        historyMode=caps.historyMode,
        historyUnavailable=caps.historyMode == "unavailable",
        runs=runs,
    )
