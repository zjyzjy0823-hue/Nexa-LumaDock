"""v0.7.2 统一定时任务（Cron）单所有者聚合、脱敏、丢确认防重调与 macOS 打包 Spec 回归测试。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.fleet.hub import fleet_hub
from app.scheduler.sanitize import sanitize_summary, workflow_is_high_impact, workflow_requires_manual_space_unlock


def _create_node(client, headers, name: str, providers: list[str]) -> str:
    res = client.post(
        "/api/v1/fleet/nodes",
        headers=headers,
        json={"name": name, "platform": "macos"},
    )
    assert res.status_code == 201, res.text
    payload = res.json()
    node_id = payload["node"]["id"] if "node" in payload else payload["id"]
    return node_id


def test_notification_sanitizer_redacts_secrets_and_truncates_chat_bodies():
    raw = (
        "运行失败：使用 sv_live_abcdefgh12345678 与 sk-proj-secretkey99999999 "
        "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.signature123456 "
        "password=SuperSecret#2026 " + ("聊天正文片段" * 60)
    )
    cleaned = sanitize_summary(raw)
    assert "sv_live_" not in cleaned
    assert "sk-proj-" not in cleaned
    assert "eyJhbGciOiJIUzI1NiJ9" not in cleaned
    assert "SuperSecret#2026" not in cleaned
    assert "[REDACTED_TOKEN]" in cleaned
    assert "[REDACTED_API_KEY]" in cleaned
    assert len(cleaned) <= 240

    assert workflow_requires_manual_space_unlock([{"action": {"type": "data.create", "config": {"spaceTier": "e2ee"}}}])
    assert workflow_is_high_impact([{"action": {"type": "webhook.post", "config": {}}}])


def test_offline_remote_owner_blocks_writes_and_never_creates_studiolo_workflow(client, users):
    owner_a, _ = users
    node_id = _create_node(client, owner_a, "Mac-Mini-Offline", ["openclaw", "hermes"])

    # 离线状态下写操作一律返回 503 且不向 Studiolo AutomationWorkflow 写入
    res = client.post(
        "/api/v1/scheduler/jobs",
        headers=owner_a,
        json={
            "ownerType": "openclaw",
            "ownerInstanceId": node_id,
            "name": "每日汇总",
            "scheduleKind": "cron",
            "scheduleExpression": "0 9 * * *",
            "timezone": "Asia/Shanghai",
            "prompt": "汇总昨日构建",
        },
    )
    assert res.status_code == 503

    wfs = client.get("/api/v1/automations", headers=owner_a).json()
    assert wfs == []


def test_online_three_owner_aggregation_confirmation_gate_and_unknown_on_timeout(client, users, monkeypatch):
    owner_a, owner_b = users

    # 1. 创建一个 Studiolo 原生工作流（标记涉及受保护 Shared Space，需人工接续解锁）
    wf_res = client.post(
        "/api/v1/automations",
        headers=owner_a,
        json={
            "name": "每日归档到机密空间",
            "description": "归档摘要并等待人工解锁受控空间",
            "enabled": True,
            "trigger_type": "manual",
            "trigger_config_json": {},
            "workflow_json": [
                {
                    "kind": "DO",
                    "label": "写入",
                    "text": "HTTP Webhook",
                    "detail": "",
                    "action": {
                        "type": "webhook.post",
                        "config": {
                            "url": "https://example.com/hook",
                            "headers": {},
                            "body": {"spaceUnlockMode": "manual", "spaceTier": "protected"},
                            "timeout": 10,
                        },
                    },
                }
            ],
        },
    )
    assert wf_res.status_code == 201, wf_res.text

    # 2. 注册一个远端节点并模拟在线 OpenClaw + Hermes 适配器
    node_id = _create_node(client, owner_a, "OCI-VPS-1", ["openclaw", "hermes"])
    fake_conn = SimpleNamespace(
        node_id=node_id,
        adapters=[
            {"provider": "openclaw", "status": "ready", "capabilities": ["cron"]},
            {"provider": "hermes", "status": "ready", "capabilities": ["cron"]},
        ],
    )

    async def fake_get_online(ws_id: str, nid: str):
        return fake_conn if nid == node_id else None

    rpc_calls: list[dict] = []

    async def fake_call_rpc(ws_id: str, nid: str, frame: dict, timeout: float = 10.0):
        rpc_calls.append(frame)
        cmd = frame["type"]
        provider = frame["provider"]
        caps = {
            "supported": True,
            "canCreate": True,
            "canUpdate": True,
            "canDelete": True,
            "canPause": True,
            "canRunNow": True,
            "historyMode": "paginated" if provider == "openclaw" else "recent_only",
            "supportsProfiles": provider == "hermes",
        }
        if cmd == "cron.list":
            if provider == "openclaw":
                return {
                    "ok": True,
                    "capabilities": caps,
                    "jobs": [
                        {
                            "nativeJobId": "oc-job-1",
                            "ownerProfile": "default",
                            "name": "OpenClaw 早报",
                            "description": "sk-secret-key-should-be-redacted",
                            "enabled": True,
                            "scheduleKind": "cron",
                            "scheduleExpression": "0 8 * * *",
                            "timezone": "Asia/Shanghai",
                            "lastStatus": "succeeded",
                        },
                        # 重复原生 ID 应自动去重
                        {
                            "nativeJobId": "oc-job-1",
                            "ownerProfile": "default",
                            "name": "OpenClaw 早报重复项",
                            "enabled": True,
                            "scheduleKind": "cron",
                            "scheduleExpression": "0 8 * * *",
                            "timezone": "Asia/Shanghai",
                        },
                    ],
                }
            return {
                "ok": True,
                "capabilities": caps,
                "jobs": [
                    {
                        "nativeJobId": "hm-job-1",
                        "ownerProfile": "research",
                        "name": "Hermes 论文追踪",
                        "enabled": False,
                        "scheduleKind": "cron",
                        "scheduleExpression": "30 22 * * *",
                        "timezone": "UTC",
                        "lastStatus": "failed",
                    }
                ],
            }
        if cmd == "cron.pause":
            return {
                "ok": True,
                "capabilities": caps,
                "job": {
                    "nativeJobId": frame["nativeJobId"],
                    "ownerProfile": frame.get("ownerProfile", "default"),
                    "name": "Hermes 论文追踪",
                    "enabled": not frame["paused"],
                    "scheduleKind": "cron",
                    "scheduleExpression": "30 22 * * *",
                    "timezone": "UTC",
                },
            }
        if cmd == "cron.run":
            if frame.get("requestId") == "req-timeout":
                return {"ok": False, "code": "rpc_timeout", "error": "timeout"}
            return {
                "ok": True,
                "capabilities": caps,
                "run": {
                    "nativeRunId": "run-99",
                    "status": "queued",
                    "summary": "触发成功，凭据 sv_live_secretvalue999 已处理",
                },
            }
        if cmd == "cron.runs":
            return {
                "ok": True,
                "capabilities": caps,
                "runs": [
                    {
                        "nativeRunId": "run-1",
                        "status": "ok",
                        "summary": "执行完成 Bearer secret-token-value-12345",
                    }
                ],
            }
        if cmd == "cron.delete":
            return {"ok": True, "capabilities": caps, "deleted": True}
        return {"ok": False, "code": "unsupported", "error": "unsupported"}

    monkeypatch.setattr(fleet_hub, "get_online_node", fake_get_online)
    monkeypatch.setattr(fleet_hub, "call_node_rpc", fake_call_rpc)

    # 3. 聚合查询：三类所有者各 1 条（OpenClaw 重复项已去重），脱敏与 waiting_manual_unlock 生效
    overview = client.get("/api/v1/scheduler/jobs", headers=owner_a)
    assert overview.status_code == 200, overview.text
    data = overview.json()
    assert len(data["instances"]) == 3
    by_owner = {j["ref"]["ownerType"]: j for j in data["jobs"]}
    assert set(by_owner.keys()) == {"studiolo", "openclaw", "hermes"}
    assert by_owner["studiolo"]["requiresManualSpaceUnlock"] is True
    assert by_owner["studiolo"]["lastStatus"] == "waiting_manual_unlock"
    assert "sk-secret-" not in by_owner["openclaw"]["description"]
    assert by_owner["hermes"]["ref"]["ownerProfile"] == "research"

    # 4. 恢复 Hermes Cron
    resume_res = client.post(
        f"/api/v1/scheduler/jobs/hermes/{node_id}/hm-job-1/pause",
        headers=owner_a,
        json={"paused": False, "ownerProfile": "research"},
    )
    assert resume_res.status_code == 200
    assert resume_res.json()["enabled"] is True

    # 5. 手动触发必须显式二次确认（confirmed=True）
    assert (
        client.post(
            f"/api/v1/scheduler/jobs/openclaw/{node_id}/oc-job-1/run",
            headers=owner_a,
            json={"requestId": "req-1", "confirmed": False},
        ).status_code
        == 422
    )
    run_ok = client.post(
        f"/api/v1/scheduler/jobs/openclaw/{node_id}/oc-job-1/run",
        headers=owner_a,
        json={"requestId": "req-1", "confirmed": True},
    )
    assert run_ok.status_code == 200
    assert "sv_live_" not in run_ok.json()["summary"]

    # 6. 丢确认超时返回 unknown，不自动重调
    run_unknown = client.post(
        f"/api/v1/scheduler/jobs/openclaw/{node_id}/oc-job-1/run",
        headers=owner_a,
        json={"requestId": "req-timeout", "confirmed": True},
    )
    assert run_unknown.status_code == 200
    assert run_unknown.json()["status"] == "unknown"

    # 7. 查询运行账本并验证脱敏
    runs_res = client.get(
        f"/api/v1/scheduler/jobs/openclaw/{node_id}/oc-job-1/runs?limit=10",
        headers=owner_a,
    )
    assert runs_res.status_code == 200
    assert runs_res.json()["runs"][0]["status"] == "succeeded"
    assert "secret-token-value" not in runs_res.json()["runs"][0]["summary"]

    # 8. 跨工作区隔离（owner_b 访问 owner_a 节点返 404）与删除二次确认
    assert (
        client.delete(
            f"/api/v1/scheduler/jobs/openclaw/{node_id}/oc-job-1?confirmed=false",
            headers=owner_a,
        ).status_code
        == 422
    )
    assert (
        client.delete(
            f"/api/v1/scheduler/jobs/openclaw/{node_id}/oc-job-1?confirmed=true",
            headers=owner_b,
        ).status_code
        == 404
    )
    assert (
        client.delete(
            f"/api/v1/scheduler/jobs/openclaw/{node_id}/oc-job-1?confirmed=true",
            headers=owner_a,
        ).status_code
        == 204
    )


def test_macos_and_desktop_pyinstaller_spec_includes_v071_v072_hiddenimports():
    spec_path = Path(__file__).resolve().parents[1] / "studiolo-backend.spec"
    content = spec_path.read_text(encoding="utf-8")
    for mod in (
        "cryptography.hazmat.primitives.kdf.argon2",
        "cryptography.hazmat.primitives.kdf.hkdf",
        "cryptography.hazmat.primitives.ciphers.aead",
        "app.space.routes",
        "app.scheduler.routes",
    ):
        assert mod in content
