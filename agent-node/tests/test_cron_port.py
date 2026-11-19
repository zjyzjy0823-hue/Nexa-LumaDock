"""AgentNode OpenClaw & Hermes CronPort 单元测试。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import httpx
import pytest

from agent_node.adapters.hermes import HermesAdapter
from agent_node.adapters.openclaw import OpenClawAdapter


def test_openclaw_cron_port_rpc_mapping(tmp_path: Path, monkeypatch):
    adapter = OpenClawAdapter((tmp_path,), gateway_url="ws://127.0.0.1:18789", token="oc-tok")
    calls: list[tuple[str, dict[str, Any]]] = []

    async def fake_rpc(method: str, params: dict[str, Any]):
        calls.append((method, params))
        if method == "cron.list":
            return {"jobs": [{"id": "j1", "name": "Daily", "schedule": {"kind": "cron", "expr": "0 9 * * *", "tz": "Asia/Shanghai"}, "enabled": True}]}
        if method == "cron.add":
            return {"job": {"id": "j2", "name": params["name"], "schedule": params["schedule"], "enabled": True}}
        if method == "cron.update":
            return {"job": {"id": params["id"], "name": "Daily", "enabled": params.get("enabled", True), "schedule": {"kind": "cron", "expr": "0 9 * * *", "tz": "Asia/Shanghai"}}}
        if method == "cron.run":
            return {"runId": "r-101", "status": "queued"}
        if method == "cron.runs":
            return {"runs": [{"id": "r-101", "status": "ok", "summary": "done"}]}
        if method == "cron.remove":
            return {"deleted": True}
        raise AssertionError(f"Unexpected RPC {method}")

    monkeypatch.setattr(adapter, "_rpc", fake_rpc)

    async def run():
        assert adapter.cron_capabilities()["supported"] is True
        jobs = await adapter.cron_list()
        assert len(jobs) == 1 and jobs[0]["nativeJobId"] == "j1"

        created = await adapter.cron_create({"name": "NewJob", "scheduleExpression": "*/5 * * * *", "timezone": "UTC"})
        assert created["nativeJobId"] == "j2"

        paused = await adapter.cron_pause(native_job_id="j1", paused=True)
        assert paused["enabled"] is False

        triggered = await adapter.cron_run_now(native_job_id="j1", request_id="req-abc")
        assert triggered["nativeRunId"] == "r-101"

        runs = await adapter.cron_list_runs(native_job_id="j1", limit=5)
        assert runs[0]["status"] == "succeeded"

        await adapter.cron_delete(native_job_id="j2")

    asyncio.run(run())
    assert [m for m, _ in calls] == ["cron.list", "cron.add", "cron.update", "cron.run", "cron.runs", "cron.remove"]


def test_hermes_cron_port_gateway_and_acp_capability_boundary(tmp_path: Path, monkeypatch):
    # 纯 ACP 模式无 serve_url：必须准确汇报不支持 CronPort
    acp_only = HermesAdapter((tmp_path,), mode="acp", serve_url=None)
    assert acp_only.cron_capabilities()["supported"] is False
    assert acp_only.cron_capabilities()["historyMode"] == "unavailable"

    # Gateway 模式：对接 /api/cron/jobs、/pause、/trigger、/{id}/runs
    gw = HermesAdapter((tmp_path,), mode="gateway", serve_url="http://hermes.local:8088", api_key="hm-key")
    assert gw.cron_capabilities()["supported"] is True
    assert gw.cron_capabilities()["supportsProfiles"] is True

    requests_seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests_seen.append((request.method, str(request.url)))
        if request.method == "GET" and request.url.path == "/api/cron/jobs":
            return httpx.Response(200, json={"jobs": [{"id": "hm-1", "name": "Digest", "schedule": "0 7 * * *", "timezone": "Asia/Shanghai", "profile": "work", "paused": False}]})
        if request.method == "POST" and request.url.path == "/api/cron/jobs/hm-1/pause":
            return httpx.Response(200, json={"job": {"id": "hm-1", "name": "Digest", "paused": True, "profile": "work"}})
        if request.method == "POST" and request.url.path == "/api/cron/jobs/hm-1/trigger":
            return httpx.Response(200, json={"run_id": "hm-run-1", "status": "running"})
        if request.method == "GET" and request.url.path == "/api/cron/jobs/hm-1/runs":
            return httpx.Response(200, json={"runs": [{"run_id": "hm-run-1", "status": "completed", "summary": "ok"}]})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    real_client_cls = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: real_client_cls(transport=transport, **{k: v for k, v in kw.items() if k != "transport"}))

    async def run():
        jobs = await gw.cron_list(profile="work")
        assert jobs[0]["nativeJobId"] == "hm-1"
        assert jobs[0]["ownerProfile"] == "work"

        paused = await gw.cron_pause(native_job_id="hm-1", paused=True, profile="work")
        assert paused["enabled"] is False

        run_info = await gw.cron_run_now(native_job_id="hm-1", request_id="r-1", profile="work")
        assert run_info["nativeRunId"] == "hm-run-1"

        runs = await gw.cron_list_runs(native_job_id="hm-1", limit=10, profile="work")
        assert runs[0]["status"] == "succeeded"

    asyncio.run(run())
    assert any("/api/cron/jobs/hm-1/pause" in url for _, url in requests_seen)
    assert any("profile=work" in url for _, url in requests_seen)
