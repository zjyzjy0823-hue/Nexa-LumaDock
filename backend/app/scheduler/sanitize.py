"""统一定时任务通知与执行摘要脱敏器（零聊天正文、零凭据、零 Shared Space 明文泄漏）。"""

from __future__ import annotations

import re
from typing import Any


# 覆盖 Studiolo 各类专用 Token、常见大模型 API Key、Bearer/JWT 及密码键值对
_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(?:ss_live_|sv_live_|na_live_|nc_live_|nd_live_|sn_live_)[A-Za-z0-9_\-]{8,}"), "[REDACTED_TOKEN]"),
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{12,}"), "[REDACTED_API_KEY]"),
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]{12,}"), "Bearer [REDACTED]"),
    (re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"), "[REDACTED_JWT]"),
    (
        re.compile(r'(?i)("?(?:password|passwd|secret|token|api[_-]?key|master[_-]?key|space[_-]?key)"?\s*[:=]\s*)("[^"]*"|\'[^\']*\'|\S+)'),
        r"\1[REDACTED]",
    ),
)

HIGH_IMPACT_ACTIONS = frozenset({"ledger.create", "webhook.post", "agent.run"})
MAX_SUMMARY_CHARS = 240


def sanitize_summary(text: Any, *, max_length: int = MAX_SUMMARY_CHARS) -> str:
    """脱敏并有界截断定时任务通知/运行摘要，严禁泄露密钥、Token 或长聊天正文。"""
    if text is None:
        return ""
    raw = str(text).strip()
    if not raw:
        return ""
    # 折叠多行对话正文为单行摘要并剔除控制字符
    cleaned = " ".join(raw.split())
    for pattern, replacement in _SECRET_PATTERNS:
        cleaned = pattern.sub(replacement, cleaned)
    if len(cleaned) > max_length:
        return cleaned[: max_length - 1].rstrip() + "…"
    return cleaned


def workflow_requires_manual_space_unlock(workflow_json: list[dict[str, Any]] | None) -> bool:
    """判断 Studiolo 工作流是否声明了需要人工输入密码解锁的受保护 Shared Space 资源。"""
    if not isinstance(workflow_json, list):
        return False
    for node in workflow_json:
        if not isinstance(node, dict):
            continue
        action = node.get("action")
        if not isinstance(action, dict):
            continue
        cfg = action.get("config")
        if not isinstance(cfg, dict):
            continue
        nested = [cfg]
        for subkey in ("body", "data_json"):
            sub = cfg.get(subkey)
            if isinstance(sub, dict):
                nested.append(sub)
        for obj in nested:
            if (
                obj.get("spaceUnlockMode") == "manual"
                or obj.get("requiresManualSpaceUnlock")
                or obj.get("spaceTier") in ("protected", "e2ee")
            ):
                return True
    return False


def workflow_is_high_impact(workflow_json: list[dict[str, Any]] | None) -> bool:
    """识别含高影响副作用动作的工作流，前端/API 需显式二次确认。"""
    if not isinstance(workflow_json, list):
        return False
    for node in workflow_json:
        if not isinstance(node, dict):
            continue
        action = node.get("action")
        if isinstance(action, dict) and str(action.get("type") or "") in HIGH_IMPACT_ACTIONS:
            return True
    return False
