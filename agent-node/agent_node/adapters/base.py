"""统一 AgentAdapter 抽象契约与共享本地探测/工作目录沙箱辅助函数。"""

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
from typing import Any

from ..config import ensure_allowed_path
from ..worktree import create_session_worktree


EventEmitter = Callable[[dict[str, Any]], Awaitable[None]]
ApprovalCallback = Callable[[str, str, str, str], Awaitable[str]]


def safe_token_int(value: Any) -> int:
    """将上游传入的 Token 计数字段安全转为非负整数。"""
    if isinstance(value, bool) or value is None:
        return 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def merge_prompt_with_attachments(text: str, attachments: list[dict[str, Any]] | None) -> str:
    """将已解密落盘的本地附件路径或票据描述附加到提示词尾部，供不支持专有多模态字段的代理读取。"""
    if not attachments:
        return text
    lines: list[str] = []
    for item in attachments:
        if not isinstance(item, dict):
            continue
        name = str(item.get("fileName") or item.get("artifactId") or "attachment")
        local_path = item.get("localPath")
        if local_path:
            mime = str(item.get("mime") or "application/octet-stream")
            lines.append(f"- [已解密附件] {name} ({mime}): {local_path}")
        elif item.get("artifactId"):
            lines.append(f"- [加密附件票据] {name} (id={item['artifactId']})")
    if not lines:
        return text
    block = "[附带文件]\n" + "\n".join(lines)
    return f"{text}\n\n{block}" if text.strip() else block


def estimate_tokens(text: str) -> int:
    """近似估算文本 Token 数量（CJK/多字节字符按 ~1 token，ASCII 按 4 字符 ~1 token）。"""
    clean = text.strip()
    if not clean:
        return 0
    non_ascii = sum(1 for ch in clean if ord(ch) > 127)
    ascii_chars = len(clean) - non_ascii
    return max(1, non_ascii + (ascii_chars + 3) // 4)


def extract_usage_counts(raw: dict[str, Any]) -> dict[str, int]:
    """兼容 camelCase / snake_case 上游用法字典，提取标准化输入输出与缓存计数。"""
    cache = raw.get("cache") if isinstance(raw.get("cache"), dict) else {}
    inp = safe_token_int(raw.get("inputTokens") or raw.get("input_tokens") or raw.get("promptTokens") or raw.get("prompt_tokens") or raw.get("input"))
    cached = safe_token_int(
        raw.get("cachedInputTokens")
        or raw.get("cached_input_tokens")
        or raw.get("cacheReadInputTokens")
        or raw.get("cache_read_input_tokens")
        or cache.get("read")
    )
    out = safe_token_int(raw.get("outputTokens") or raw.get("output_tokens") or raw.get("completionTokens") or raw.get("completion_tokens") or raw.get("output"))
    reasoning = safe_token_int(
        raw.get("reasoningOutputTokens")
        or raw.get("reasoning_output_tokens")
        or raw.get("reasoningTokens")
        or raw.get("reasoning_tokens")
        or raw.get("reasoning")
    )
    total = safe_token_int(raw.get("totalTokens") or raw.get("total_tokens") or raw.get("total"))
    if total == 0 and (inp or out or reasoning):
        total = inp + out + (reasoning if raw.get("reasoning") is not None else 0)
    return {
        "inputTokens": inp,
        "cachedInputTokens": cached,
        "outputTokens": out,
        "reasoningTokens": reasoning,
        "totalTokens": total,
    }


def build_token_usage_event(
    *,
    session_id: str,
    run_id: str | None = None,
    request_id: str | None = None,
    message_id: str | None = None,
    scope: str = "turn",
    input_tokens: int = 0,
    cached_input_tokens: int = 0,
    output_tokens: int = 0,
    reasoning_tokens: int = 0,
    total_tokens: int | None = None,
    last_input_tokens: int | None = None,
    last_cached_input_tokens: int | None = None,
    last_output_tokens: int | None = None,
    last_reasoning_tokens: int | None = None,
    last_total_tokens: int | None = None,
    context_window: int | None = None,
    model: str | None = None,
    source: str = "exact",
) -> dict[str, Any]:
    """构造标准化的 `TokenUsage` WebSocket 控制事件帧。"""
    inp = max(0, int(input_tokens))
    cached = max(0, int(cached_input_tokens))
    out = max(0, int(output_tokens))
    reasoning = max(0, int(reasoning_tokens))
    total = max(0, int(total_tokens)) if total_tokens is not None else inp + out
    frame: dict[str, Any] = {
        "type": "TokenUsage",
        "sessionId": session_id,
        "scope": scope,
        "inputTokens": inp,
        "cachedInputTokens": cached,
        "outputTokens": out,
        "reasoningTokens": reasoning,
        "totalTokens": total,
        "source": source,
    }
    if run_id:
        frame["runId"] = run_id
    if request_id:
        frame["requestId"] = request_id
    if message_id:
        frame["messageId"] = message_id
    if last_input_tokens is not None:
        frame["lastInputTokens"] = max(0, int(last_input_tokens))
    if last_cached_input_tokens is not None:
        frame["lastCachedInputTokens"] = max(0, int(last_cached_input_tokens))
    if last_output_tokens is not None:
        frame["lastOutputTokens"] = max(0, int(last_output_tokens))
    if last_reasoning_tokens is not None:
        frame["lastReasoningTokens"] = max(0, int(last_reasoning_tokens))
    if last_total_tokens is not None:
        frame["lastTotalTokens"] = max(0, int(last_total_tokens))
    if context_window and context_window > 0:
        frame["contextWindow"] = int(context_window)
    if model:
        frame["model"] = model
    return frame


def build_tool_call_update(
    *,
    session_id: str,
    call_id: str,
    name: str,
    status: str = "running",
    run_id: str | None = None,
    request_id: str | None = None,
    title: str | None = None,
    tool_input: Any = None,
    output: str | None = None,
    delta_output: str | None = None,
    error: str | None = None,
    duration_ms: int | None = None,
    subagent_session_id: str | None = None,
    media: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """构造标准化的 `ToolCallUpdate` 结构化工具执行事件帧。"""
    frame: dict[str, Any] = {
        "type": "ToolCallUpdate",
        "sessionId": session_id,
        "callId": call_id,
        "name": name,
        "status": status,
    }
    if run_id:
        frame["runId"] = run_id
    if request_id:
        frame["requestId"] = request_id
    if title:
        frame["title"] = title
    if tool_input is not None:
        frame["input"] = tool_input
    if output is not None:
        frame["output"] = output
    if delta_output:
        frame["deltaOutput"] = delta_output
    if error:
        frame["error"] = error
    if duration_ms is not None and duration_ms >= 0:
        frame["durationMs"] = int(duration_ms)
    if subagent_session_id:
        frame["subagentSessionId"] = subagent_session_id
    if media:
        frame["media"] = media
    return frame


def build_todo_updated_event(
    *,
    session_id: str,
    items: list[dict[str, Any]],
    run_id: str | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """构造标准化的 `TodoUpdated` 任务清单事件帧。"""
    normalized: list[dict[str, Any]] = []
    for idx, row in enumerate(items):
        if not isinstance(row, dict):
            continue
        content = str(row.get("content") or row.get("text") or row.get("title") or "").strip()
        if not content:
            continue
        raw_status = str(row.get("status") or "pending").lower()
        status = (
            raw_status
            if raw_status in ("pending", "in_progress", "completed", "cancelled")
            else "completed"
            if raw_status in ("done", "finished")
            else "in_progress"
            if raw_status in ("running", "active")
            else "pending"
        )
        normalized.append({
            "id": str(row.get("id") or f"todo-{idx + 1}"),
            "content": content,
            "status": status,
            **({"priority": str(row["priority"])} if row.get("priority") else {}),
        })
    frame: dict[str, Any] = {"type": "TodoUpdated", "sessionId": session_id, "items": normalized}
    if run_id:
        frame["runId"] = run_id
    if request_id:
        frame["requestId"] = request_id
    return frame


@dataclass(frozen=True)
class AdapterProbe:
    provider: str
    version: str
    status: str  # "ready" | "unavailable" | "error"
    capabilities: tuple[str, ...] = ("chat", "history", "approval", "worktree")


def probe_cli_binary(provider: str, command: str, capabilities: tuple[str, ...]) -> AdapterProbe:
    """探测本机命令行 Harness 是否在 PATH / 配置路径可用并读取版本号。"""
    resolved = shutil.which(command)
    if resolved is None and Path(command).is_file():
        resolved = command
    if resolved is None:
        return AdapterProbe(provider=provider, version="", status="unavailable", capabilities=capabilities)
    version = "detected"
    try:
        res = subprocess.run([resolved, "--version"], capture_output=True, text=True, timeout=4.0)
        line = (res.stdout or res.stderr or "").strip().splitlines()
        if line:
            version = line[0][:64]
    except Exception:
        pass
    return AdapterProbe(provider=provider, version=version, status="ready", capabilities=capabilities)


def prepare_session_dir(
    cwd: str,
    allowed_roots: tuple[Path, ...],
    *,
    session_id: str,
    use_worktree: bool,
) -> tuple[Path, str | None]:
    """校验 cwd 处于 allowedRoots，并按需创建独立 Git Worktree。"""
    safe_cwd = ensure_allowed_path(cwd, allowed_roots)
    if not use_worktree:
        return safe_cwd, None
    wt = create_session_worktree(safe_cwd, session_id, allowed_roots)
    return wt, str(wt)


class AgentAdapter(ABC):
    """所有 Coding Agent / Gateway CLI 适配器均实现的统一控制边界。"""

    provider: str

    async def list_models(self) -> list[dict[str, Any]]:
        return []

    @abstractmethod
    async def probe(self) -> AdapterProbe:
        """检查本地 CLI / Gateway 是否安装就绪及支持的能力清单。"""

    @abstractmethod
    async def list_sessions(self, *, page: int = 1, limit: int = 30) -> list[dict[str, Any]]:
        """向上游拉取可用会话摘要（Studiolo 服务端不缓存正文）。"""

    @abstractmethod
    async def open_session(
        self,
        *,
        cwd: str,
        session_id: str | None = None,
        use_worktree: bool = False,
    ) -> dict[str, Any]:
        """在允许的工作目录中打开或恢复会话，返回会话元数据。"""

    @abstractmethod
    async def get_history(self, *, session_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """从上游拉取指定会话最近有界历史。"""

    @abstractmethod
    async def send_prompt(
        self,
        *,
        session_id: str,
        text: str,
        request_id: str,
        emit: EventEmitter,
        request_approval: ApprovalCallback,
        attachments: list[dict[str, Any]] | None = None,
    ) -> None:
        """发送用户指令，实时通过 emit 推流事件并在高危调用时挂起等待审批。"""

    @abstractmethod
    async def cancel(self, *, session_id: str, run_id: str | None = None) -> None:
        """取消当前运行中的任务或 Turn。"""

    async def rename_session(self, *, session_id: str, title: str) -> dict[str, Any]:
        """更新会话显示名称（不支持持久化重命名的代理仍返回前端可应用的元数据）。"""
        return {"sessionId": session_id, "title": title}

    async def delete_session(self, *, session_id: str) -> None:
        """删除或清理上游会话资源。"""
        return None

    async def compact_session(self, *, session_id: str) -> dict[str, Any]:
        """压缩上游长对话上下文（由支持的代理执行摘要压缩）。"""
        return {"supported": False}

    async def list_agents(self) -> list[dict[str, Any]]:
        """列出当前适配器可用的原生模式 / 子代理（如 build / plan）。"""
        return []

    async def list_mcp_servers(self) -> list[dict[str, Any]]:
        """列出当前适配器挂载的 MCP 工具服务及连接状态。"""
        return []

    async def reply_form(
        self,
        *,
        session_id: str,
        form_id: str,
        answer: dict[str, Any] | None = None,
        cancel: bool = False,
    ) -> dict[str, Any]:
        """提交或取消上游交互式提问表单（如 AskUserQuestion / OpenCode form）。"""
        return {"sessionId": session_id, "formId": form_id, "cancelled": cancel}

    async def close(self) -> None:
        """关闭适配器托管子进程等资源。"""
        return None

    # ---------------- 统一 CronPort 可选契约（单所有者语义） ----------------

    def cron_capabilities(self) -> dict[str, Any]:
        """返回该适配器对原生定时任务的真实能力边界。"""
        return {
            "supported": False,
            "canCreate": False,
            "canUpdate": False,
            "canDelete": False,
            "canPause": False,
            "canRunNow": False,
            "historyMode": "unavailable",
            "supportsProfiles": False,
        }

    async def cron_list(self, *, profile: str | None = None) -> list[dict[str, Any]]:
        raise NotImplementedError(f"{self.provider} does not support CronPort")

    async def cron_create(self, payload: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError(f"{self.provider} does not support CronPort")

    async def cron_update(self, *, native_job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError(f"{self.provider} does not support CronPort")

    async def cron_delete(self, *, native_job_id: str, profile: str | None = None) -> None:
        raise NotImplementedError(f"{self.provider} does not support CronPort")

    async def cron_pause(self, *, native_job_id: str, paused: bool, profile: str | None = None) -> dict[str, Any]:
        raise NotImplementedError(f"{self.provider} does not support CronPort")

    async def cron_run_now(
        self,
        *,
        native_job_id: str,
        request_id: str,
        profile: str | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError(f"{self.provider} does not support CronPort")

    async def cron_list_runs(
        self,
        *,
        native_job_id: str,
        limit: int = 20,
        profile: str | None = None,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError(f"{self.provider} does not support CronPort")
