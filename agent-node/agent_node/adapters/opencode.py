"""OpenCode 适配器：对接 `opencode serve` REST + SSE `/event` 接口。"""

import asyncio
import base64
import json
import os
from pathlib import Path
import secrets
import shutil
import time
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from ..config import PathOutsideAllowedRootsError, ensure_allowed_path
from .base import (
    AdapterProbe,
    AgentAdapter,
    ApprovalCallback,
    EventEmitter,
    build_todo_updated_event,
    build_token_usage_event,
    build_tool_call_update,
    extract_usage_counts,
    merge_prompt_with_attachments,
    prepare_session_dir,
)


def _extract_incremental_text(
    cache: dict[str, str],
    part_id: str,
    delta: Any,
    full_text: Any,
) -> str:
    """兼容增量 delta 与全量 누적 text：只提取尚未下发过的新增文本片段。"""
    if isinstance(delta, str) and delta:
        prev = cache.get(part_id, "")
        cache[part_id] = str(full_text) if isinstance(full_text, str) and full_text else (prev + delta)
        return delta
    full = str(full_text or "")
    if not full:
        return ""
    prev = cache.get(part_id, "")
    if full == prev:
        return ""
    cache[part_id] = full
    if prev and full.startswith(prev):
        return full[len(prev):]
    return full


def _extract_content_media(content: Any, tool_input: Any = None) -> list[dict[str, Any]]:
    """从 OpenCode content 数组中提取图片或文件媒体块（例如 read 工具返回的 data:image/... URI）。"""
    if not isinstance(content, list):
        return []
    fallback_path = ""
    if isinstance(tool_input, dict):
        for k in ("path", "filePath", "file", "target_file", "filename"):
            v = tool_input.get(k)
            if isinstance(v, str) and v.strip():
                fallback_path = v.strip()
                break
    media: list[dict[str, Any]] = []
    for idx, c in enumerate(content):
        if not isinstance(c, dict):
            continue
        ctype = str(c.get("type") or "").lower()
        uri = str(c.get("uri") or c.get("url") or "").strip()
        if not uri and isinstance(c.get("data"), str) and c.get("data"):
            raw_mime = str(c.get("mime") or "application/octet-stream")
            uri = f"data:{raw_mime};base64,{c['data']}"
        if not uri:
            continue
        if ctype not in ("file", "image") and not uri.startswith("data:"):
            continue
        mime = str(c.get("mime") or "").strip()
        if not mime and uri.startswith("data:") and ";" in uri:
            mime = uri[5:].split(";", 1)[0].strip()
        if not mime:
            mime = "image/png" if (ctype == "image" or uri.startswith("data:image/")) else "application/octet-stream"
        raw_name = str(c.get("filename") or c.get("name") or "").strip()
        if not raw_name and fallback_path:
            raw_name = Path(fallback_path.replace("\\", "/")).name
        if not raw_name:
            ext = mime.split("/")[-1].split("+")[0] if "/" in mime else "bin"
            if ext == "jpeg":
                ext = "jpg"
            raw_name = f"media-{idx + 1}.{ext}"
        item: dict[str, Any] = {
            "id": str(c.get("id") or f"media-{idx + 1}-{uuid4().hex[:6]}"),
            "url": uri,
            "fileName": raw_name,
            "mime": mime,
        }
        if fallback_path:
            item["filePath"] = fallback_path
        media.append(item)
    return media


def _extract_opencode_tool_payload(part: dict[str, Any]) -> dict[str, Any]:
    """解析 OpenCode tool part（兼容 v1/v2 state、内容块、入参、输出、媒体与耗时）。"""
    state = part.get("state") if isinstance(part.get("state"), dict) else {}
    raw_status = str(state.get("status") or "running").lower()
    status = "completed" if raw_status == "completed" else "error" if raw_status in ("error", "failed") else "running"
    tm = state.get("time") if isinstance(state.get("time"), dict) else (part.get("time") if isinstance(part.get("time"), dict) else {})
    duration_ms: int | None = None
    start_ms = tm.get("start") if isinstance(tm.get("start"), (int, float)) else (tm.get("ran") if isinstance(tm.get("ran"), (int, float)) else tm.get("created"))
    end_ms = tm.get("end") if isinstance(tm.get("end"), (int, float)) else tm.get("completed")
    if isinstance(start_ms, (int, float)) and isinstance(end_ms, (int, float)):
        duration_ms = max(0, int(end_ms - start_ms))
    out_val = state.get("output")
    if out_val is None and isinstance(state.get("content"), list):
        chunks = [str(c.get("text") or "") for c in state["content"] if isinstance(c, dict) and c.get("type") == "text"]
        if chunks:
            out_val = "\n".join(chunks)
    err_val = state.get("error")
    tool_input = state.get("input")
    media = _extract_content_media(state.get("content"), tool_input)
    name = str(part.get("tool") or part.get("name") or "tool")
    title = str(state.get("title") or "") or _summarize_tool_title(name, tool_input)
    res: dict[str, Any] = {
        "callId": str(part.get("callID") or part.get("id") or uuid4().hex),
        "name": name,
        "status": status,
        "title": title,
        "input": tool_input,
        "output": str(out_val) if out_val is not None else None,
        "error": str(err_val) if err_val is not None else None,
        "durationMs": duration_ms,
    }
    if media:
        res["media"] = media
    return res


def _summarize_tool_title(name: str, tool_input: Any) -> str | None:
    if isinstance(tool_input, dict):
        for key in ("command", "path", "filePath", "pattern", "query", "url", "description"):
            val = tool_input.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()[:120]
    elif isinstance(tool_input, str) and tool_input.strip():
        return tool_input.strip()[:120]
    return name or None


def _extract_v2_tool_output(content: Any) -> str | None:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks = [str(c.get("text") or "") for c in content if isinstance(c, dict) and c.get("text")]
        if chunks:
            return "\n".join(chunks)
    return None


def _failure_from_error(error: Any) -> tuple[str, str]:
    """把 opencode 的 error 结构压成 (message, code)，供 Failed 事件使用。"""
    if isinstance(error, dict):
        raw = error.get("data")
        data: dict[str, Any] = raw if isinstance(raw, dict) else {}
        message = str(data.get("message") or error.get("message") or error.get("name") or "").strip()
        code = str(data.get("statusCode") or error.get("name") or "")
        return message or "opencode 运行失败", code
    return (str(error).strip() or "opencode 运行失败"), ""


class OpenCodeAdapter(AgentAdapter):
    provider = "opencode"

    def __init__(
        self,
        allowed_roots: tuple[Path, ...],
        *,
        serve_url: str = "http://127.0.0.1:4096",
        username: str | None = None,
        password: str | None = None,
        command: str = "opencode",
        auto_start: bool = False,
    ) -> None:
        self.allowed_roots = allowed_roots
        self.serve_url = serve_url.rstrip("/")
        self.command = command
        self.auto_start = auto_start
        eff_pw = password if password is not None else os.environ.get("OPENCODE_SERVER_PASSWORD")
        eff_user = username or os.environ.get("OPENCODE_SERVER_USERNAME") or "opencode"
        self._username = eff_user
        self._password = eff_pw
        self._auth = httpx.BasicAuth(eff_user, eff_pw) if eff_pw is not None else None
        self._api_prefix: str | None = None
        self._model_context_windows: dict[str, int] = {}
        self._managed_proc: asyncio.subprocess.Process | None = None
        self._managed_lock = asyncio.Lock()

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(auth=self._auth, timeout=httpx.Timeout(180.0, connect=4.0))

    async def _ensure_managed_serve(self) -> None:
        """若开启 auto_start 且本机 loopback serve 未监听，自动拉起托管 `opencode serve` 并注入随机/配置密钥。"""
        if not self.auto_start:
            return
        parsed = urlsplit(self.serve_url)
        if parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
            return
        async with self._managed_lock:
            if self._managed_proc is not None and self._managed_proc.returncode is None:
                return
            try:
                async with self._client() as c:
                    probe = await c.get(f"{self.serve_url}/api/session")
                    if self._is_json_response(probe):
                        return
            except Exception:
                pass
            cmd_path = shutil.which(f"{self.command}.cmd") if os.name == "nt" else None
            resolved = cmd_path or shutil.which(self.command)
            if resolved and resolved.lower().endswith(".ps1"):
                alt_cmd = Path(resolved).with_suffix(".cmd")
                if alt_cmd.is_file():
                    resolved = str(alt_cmd)
            if not resolved:
                return
            if not self._password:
                self._password = secrets.token_urlsafe(18)
                self._auth = httpx.BasicAuth(self._username, self._password)
            port = str(parsed.port or 4096)
            env = os.environ.copy()
            env["OPENCODE_SERVER_PASSWORD"] = self._password
            env["OPENCODE_SERVER_USERNAME"] = self._username
            argv = [resolved, "serve", "--hostname", parsed.hostname or "127.0.0.1", "--port", port]
            self._managed_proc = await asyncio.create_subprocess_exec(
                *argv,
                cwd=str(self.allowed_roots[0]),
                env=env,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            for _ in range(25):
                await asyncio.sleep(0.2)
                if self._managed_proc.returncode is not None:
                    break
                try:
                    async with self._client() as c:
                        res = await c.get(f"{self.serve_url}/api/session")
                        if self._is_json_response(res):
                            self._api_prefix = "/api"
                            return
                except Exception:
                    continue

    async def close(self) -> None:
        proc = self._managed_proc
        self._managed_proc = None
        if proc is not None and proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=3.0)
            except Exception:
                proc.kill()

    @staticmethod
    def _is_json_response(res: httpx.Response) -> bool:
        if res.status_code != 200:
            return False
        ctype = str(res.headers.get("content-type") or "").lower()
        if "json" in ctype:
            return True
        txt = res.text.lstrip()
        return txt.startswith("{") or txt.startswith("[")

    async def _detect_api_prefix(self, client: httpx.AsyncClient) -> str:
        if self._api_prefix is not None:
            return self._api_prefix
        try:
            r_v2 = await client.get(f"{self.serve_url}/api/session")
            if self._is_json_response(r_v2):
                self._api_prefix = "/api"
                return "/api"
        except Exception:
            pass
        self._api_prefix = ""
        return ""

    async def probe(self) -> AdapterProbe:
        caps = (
            "chat",
            "history",
            "approval",
            "worktree",
            "models",
            "files",
            "diff",
            "checkpoints",
            "todos",
            "agents",
            "mcp",
            "forms",
            "subagents",
        )
        await self._ensure_managed_serve()
        try:
            async with self._client() as c:
                r_v2 = await c.get(f"{self.serve_url}/api/session")
                if self._is_json_response(r_v2):
                    self._api_prefix = "/api"
                    return AdapterProbe(provider=self.provider, version="serve-v2", status="ready", capabilities=caps)
                r_v1 = await c.get(f"{self.serve_url}/session")
                if self._is_json_response(r_v1):
                    self._api_prefix = ""
                    return AdapterProbe(provider=self.provider, version="serve-http", status="ready", capabilities=caps)
        except Exception:
            pass
        return AdapterProbe(provider=self.provider, version="", status="unavailable", capabilities=caps)

    async def list_models(self) -> list[dict[str, Any]]:
        async with self._client() as client:
            prefix = await self._detect_api_prefix(client)
            if prefix == "/api":
                response = await client.get(f"{self.serve_url}/api/model")
                response.raise_for_status()
                raw = response.json()
                rows = raw.get("data", []) if isinstance(raw, dict) else (raw if isinstance(raw, list) else [])
                enabled_rows = [
                    m for m in rows
                    if isinstance(m, dict) and m.get("enabled", True) and str(m.get("type") or "chat") == "chat"
                ]
                key_counts: dict[str, int] = {}
                for m in enabled_rows:
                    mid = str(m.get("modelID") or m.get("id") or "")
                    if mid:
                        key_counts[mid] = key_counts.get(mid, 0) + 1
                models: list[dict[str, Any]] = []
                for m in enabled_rows:
                    provider_id = str(m.get("providerID") or "")
                    model_id = str(m.get("modelID") or m.get("id") or "")
                    if not model_id:
                        continue
                    full_id = f"{provider_id}/{model_id}" if provider_id else model_id
                    name = str(m.get("name") or model_id)
                    variants_raw = m.get("variants") or []
                    efforts = [
                        str(v.get("id")) if isinstance(v, dict) else str(v)
                        for v in (variants_raw if isinstance(variants_raw, list) else list(variants_raw))
                        if (isinstance(v, dict) and v.get("id")) or isinstance(v, str)
                    ]
                    ctx = (m.get("limit") or {}).get("context")
                    if isinstance(ctx, int) and ctx > 0:
                        self._model_context_windows[full_id] = ctx
                        self._model_context_windows[model_id] = ctx
                    models.append(
                        {
                            "id": full_id,
                            "label": f"{provider_id} · {name}" if key_counts.get(model_id, 0) > 1 and provider_id else name,
                            "provider": provider_id,
                            "efforts": efforts,
                        }
                    )
                return models

            response = await client.get(f"{self.serve_url}/provider")
            response.raise_for_status()
            catalog = response.json()
            connected = [p for p in catalog.get("all", []) if p["id"] in catalog.get("connected", [])]
            key_counts = {}
            for provider in connected:
                for key in provider.get("models", {}):
                    key_counts[key] = key_counts.get(key, 0) + 1
            models = []
            for provider in connected:
                provider_id = str(provider["id"])
                for key, model in provider.get("models", {}).items():
                    name = model.get("name") or key
                    models.append(
                        {
                            "id": f"{provider_id}/{key}",
                            "label": f"{provider_id} · {name}" if key_counts.get(key, 0) > 1 else name,
                            "provider": provider_id,
                            "efforts": list(model.get("variants") or {}),
                        }
                    )
            return models

    def _allowed_session_directory(self, session: dict[str, Any]) -> Path:
        location = session.get("location")
        directory = session.get("directory") or (location.get("directory") if isinstance(location, dict) else None)
        if not isinstance(directory, str) or not Path(directory).is_absolute():
            raise PathOutsideAllowedRootsError("OpenCode session has no verifiable workspace")
        try:
            return ensure_allowed_path(directory, self.allowed_roots)
        except (PathOutsideAllowedRootsError, OSError, ValueError):
            raise PathOutsideAllowedRootsError("OpenCode session is outside the allowed workspace") from None

    async def _session_directory(self, client: httpx.AsyncClient, prefix: str, session_id: str) -> Path:
        if not session_id or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for char in session_id):
            raise PathOutsideAllowedRootsError("Invalid OpenCode session")
        response = await client.get(f"{self.serve_url}{prefix}/session/{session_id}")
        if response.status_code != 200:
            raise PathOutsideAllowedRootsError("Cannot verify the OpenCode session workspace")
        payload = response.json()
        details = payload.get("data", payload) if isinstance(payload, dict) else None
        if not isinstance(details, dict) or details.get("id") != session_id:
            raise PathOutsideAllowedRootsError("Cannot verify the OpenCode session workspace")
        return self._allowed_session_directory(details)

    async def list_sessions(self, *, page: int = 1, limit: int = 30) -> list[dict[str, Any]]:
        async with self._client() as c:
            prefix = await self._detect_api_prefix(c)
            res = await c.get(f"{self.serve_url}{prefix}/session")
            res.raise_for_status()
            payload = res.json()
            rows = payload.get("data", []) if isinstance(payload, dict) else (payload if isinstance(payload, list) else [])
            out: list[dict[str, Any]] = []
            for s in rows:
                if not isinstance(s, dict) or not s.get("id"):
                    continue
                try:
                    cwd = self._allowed_session_directory(s)
                except PathOutsideAllowedRootsError:
                    continue
                sid = str(s.get("id"))
                raw_title = str(s.get("title") or "").strip()
                tokens = s.get("tokens")
                if isinstance(tokens, dict):
                    in_tok = int(tokens.get("input") or 0)
                    out_tok = int(tokens.get("output") or 0)
                    # 过滤从未发送过任何消息的空白未命名会话残骸，避免列表出现大量重复的空白「新对话」
                    if in_tok == 0 and out_tok == 0 and (not raw_title or raw_title == sid or raw_title.startswith("ses_")):
                        continue
                if not raw_title or raw_title == sid or raw_title.startswith("ses_"):
                    try:
                        m_res = await c.get(f"{self.serve_url}{prefix}/session/{sid}/message", params={"limit": 10})
                        if m_res.status_code == 200:
                            m_payload = m_res.json()
                            m_rows = m_payload.get("data", []) if isinstance(m_payload, dict) else (
                                m_payload if isinstance(m_payload, list) else []
                            )
                            user_texts = [
                                str(m.get("text") or "").strip()
                                for m in m_rows
                                if isinstance(m, dict) and m.get("type") == "user" and str(m.get("text") or "").strip()
                            ]
                            if user_texts:
                                first_txt = " ".join(user_texts[-1].split())
                                raw_title = f"{first_txt[:22]}…" if len(first_txt) > 22 else first_txt
                                await c.patch(f"{self.serve_url}{prefix}/session/{sid}", json={"title": raw_title})
                    except Exception:
                        pass
                out.append(
                    {
                        "sessionId": sid,
                        "provider": self.provider,
                        "title": raw_title or sid,
                        "cwd": str(cwd),
                    }
                )
                if len(out) >= limit:
                    break
            return out

    async def open_session(
        self,
        *,
        cwd: str,
        session_id: str | None = None,
        use_worktree: bool = False,
    ) -> dict[str, Any]:
        if session_id:
            async with self._client() as c:
                prefix = await self._detect_api_prefix(c)
                directory = await self._session_directory(c, prefix, session_id)
            return {"sessionId": session_id, "provider": self.provider, "cwd": str(directory), "title": f"OpenCode ({directory.name})"}
        sid_seed = f"oc-{uuid4().hex[:8]}"
        eff_cwd, wt_path = prepare_session_dir(cwd, self.allowed_roots, session_id=sid_seed, use_worktree=use_worktree)
        async with self._client() as c:
            prefix = await self._detect_api_prefix(c)
            if prefix == "/api":
                res = await c.post(f"{self.serve_url}/api/session", json={"location": {"directory": str(eff_cwd)}})
                res.raise_for_status()
                raw = res.json()
                data = raw.get("data", raw) if isinstance(raw, dict) else {}
            else:
                res = await c.post(f"{self.serve_url}/session", params={"directory": str(eff_cwd)})
                res.raise_for_status()
                data = res.json()
            sid = str(data.get("id") or sid_seed)
            return {"sessionId": sid, "provider": self.provider, "cwd": str(eff_cwd), "worktreePath": wt_path, "title": data.get("title") or sid}

    async def get_history(self, *, session_id: str, limit: int = 50) -> list[dict[str, Any]]:
        async with self._client() as c:
            prefix = await self._detect_api_prefix(c)
            await self._session_directory(c, prefix, session_id)
            fetch_limit = max(limit * 3, 120) if prefix == "/api" else limit
            res = await c.get(f"{self.serve_url}{prefix}/session/{session_id}/message", params={"limit": fetch_limit})
            if res.status_code != 200:
                return []
            payload = res.json()
            raw_items = payload.get("data", []) if isinstance(payload, dict) else (payload if isinstance(payload, list) else [])
            items = [m for m in raw_items if isinstance(m, dict)]

            # OpenCode v2 `/api/session/{id}/message` 默认按时间倒序（最新在前）返回，需按时间正序还原对话流
            ts_list: list[float] = []
            for m in items:
                tm = m.get("time") if isinstance(m.get("time"), dict) else (
                    (m.get("info") or {}).get("time") if isinstance(m.get("info"), dict) else None
                )
                if isinstance(tm, dict) and isinstance(tm.get("created"), (int, float)):
                    ts_list.append(float(tm["created"]))
            if len(ts_list) >= 2 and ts_list[0] > ts_list[-1]:
                items = list(reversed(items))

            out: list[dict[str, Any]] = []
            for msg in items:
                # OpenCode v2 消息结构：{type: "user"|"assistant"|"idle", text?, content?: [...]}
                if "type" in msg and "info" not in msg:
                    mtype = msg.get("type")
                    if mtype == "user":
                        user_entry: dict[str, Any] = {"role": "user", "text": str(msg.get("text") or "")}
                        user_media = _extract_content_media(msg.get("content") or msg.get("files"))
                        if user_media:
                            user_entry["media"] = user_media
                        out.append(user_entry)
                    elif mtype == "assistant":
                        t_chunks: list[str] = []
                        r_chunks: list[str] = []
                        t_calls: list[dict[str, Any]] = []
                        ordered_parts: list[dict[str, Any]] = []
                        step_media: list[dict[str, Any]] = []
                        raw_content = msg.get("content") or []
                        step_media.extend(_extract_content_media(raw_content))
                        for p in raw_content:
                            if not isinstance(p, dict):
                                continue
                            ptype = p.get("type")
                            if ptype == "text":
                                txt_val = str(p.get("text") or "")
                                t_chunks.append(txt_val)
                                if txt_val:
                                    ordered_parts.append({"type": "text", "text": txt_val})
                            elif ptype == "reasoning":
                                r_val = str(p.get("text") or "")
                                r_chunks.append(r_val)
                                if r_val:
                                    ordered_parts.append({"type": "thought", "text": r_val})
                            elif ptype == "tool":
                                tp = _extract_opencode_tool_payload(p)
                                tc = {"id": tp["callId"], **tp}
                                t_calls.append(tc)
                                ordered_parts.append({"type": "tool", **tc})
                                if isinstance(tp.get("media"), list):
                                    step_media.extend(tp["media"])
                        # OpenCode v2 同一轮助手回复的多步工具调用会拆为多条连续 assistant 记录，自动归并为单条气泡
                        if out and out[-1].get("role") == "assistant":
                            prev = out[-1]
                            add_txt = "".join(t_chunks)
                            if add_txt:
                                prev["text"] = f"{prev['text']}\n\n{add_txt}" if prev.get("text") else add_txt
                            if r_chunks:
                                add_r = "\n".join(r_chunks)
                                prev["thought"] = f"{prev['thought']}\n{add_r}" if prev.get("thought") else add_r
                            if t_calls:
                                prev["toolCalls"] = [*(prev.get("toolCalls") or []), *t_calls]
                            if ordered_parts:
                                prev["parts"] = [*(prev.get("parts") or []), *ordered_parts]
                            if step_media:
                                prev["media"] = [*(prev.get("media") or []), *step_media]
                        else:
                            entry: dict[str, Any] = {"role": "assistant", "text": "".join(t_chunks)}
                            if r_chunks:
                                entry["thought"] = "\n".join(r_chunks)
                            if t_calls:
                                entry["toolCalls"] = t_calls
                            if ordered_parts:
                                entry["parts"] = ordered_parts
                            if step_media:
                                entry["media"] = step_media
                            out.append(entry)
                    continue

                info = msg.get("info") or {}
                parts = msg.get("parts") or []
                text_chunks: list[str] = []
                thought_chunks: list[str] = []
                tool_calls: list[dict[str, Any]] = []
                ordered_v1: list[dict[str, Any]] = []
                v1_media: list[dict[str, Any]] = _extract_content_media(parts)
                for p in parts:
                    if not isinstance(p, dict) or p.get("synthetic"):
                        continue
                    ptype = p.get("type")
                    if ptype == "text":
                        txt_val = str(p.get("text") or "")
                        text_chunks.append(txt_val)
                        if txt_val:
                            ordered_v1.append({"type": "text", "text": txt_val})
                    elif ptype == "reasoning":
                        r_val = str(p.get("text") or "")
                        thought_chunks.append(r_val)
                        if r_val:
                            ordered_v1.append({"type": "thought", "text": r_val})
                    elif ptype == "tool":
                        tp = _extract_opencode_tool_payload(p)
                        tc = {"id": tp["callId"], **tp}
                        tool_calls.append(tc)
                        ordered_v1.append({"type": "tool", **tc})
                        if isinstance(tp.get("media"), list):
                            v1_media.extend(tp["media"])
                entry_v1: dict[str, Any] = {
                    "role": info.get("role", "assistant"),
                    "text": "".join(text_chunks),
                }
                if thought_chunks:
                    entry_v1["thought"] = "".join(thought_chunks)
                if tool_calls:
                    entry_v1["toolCalls"] = tool_calls
                if ordered_v1 and entry_v1["role"] == "assistant":
                    entry_v1["parts"] = ordered_v1
                if v1_media:
                    entry_v1["media"] = v1_media
                out.append(entry_v1)
            return out[-limit:]

    async def send_prompt(
        self,
        *,
        session_id: str,
        text: str,
        request_id: str,
        emit: EventEmitter,
        request_approval: ApprovalCallback,
        attachments: list[dict[str, Any]] | None = None,
        options: dict[str, str] | None = None,
    ) -> None:
        run_id = request_id
        async with self._client() as c:
            prefix = await self._detect_api_prefix(c)
            await self._session_directory(c, prefix, session_id)
            await emit({"type": "Accepted", "sessionId": session_id, "runId": run_id, "requestId": request_id, "provider": self.provider})
            if prefix == "/api":
                await self._send_prompt_v2(
                    c,
                    session_id=session_id,
                    text=text,
                    request_id=request_id,
                    run_id=run_id,
                    emit=emit,
                    request_approval=request_approval,
                    attachments=attachments,
                    options=options,
                )
                return

            extra_attachments: list[dict[str, Any]] = []
            file_parts: list[dict[str, Any]] = []
            for att in attachments or []:
                lp = att.get("localPath") if isinstance(att, dict) else None
                if lp:
                    file_parts.append({
                        "type": "file",
                        "mime": str(att.get("mime") or "application/octet-stream"),
                        "filename": str(att.get("fileName") or Path(str(lp)).name),
                        "url": Path(str(lp)).as_uri(),
                    })
                else:
                    extra_attachments.append(att)
            prompt_text = merge_prompt_with_attachments(text, extra_attachments)
            payload: dict[str, Any] = {"parts": [{"type": "text", "text": prompt_text}, *file_parts]}
            if options and options.get("model"):
                provider, model = options["model"].split("/", 1)
                payload["model"] = {"providerID": provider, "modelID": model}
                if options.get("effort"):
                    payload["variant"] = options["effort"]
            res = await c.post(f"{self.serve_url}/session/{session_id}/prompt_async", json=payload)
            res.raise_for_status()
            role_by_msg_id: dict[str, str] = {}
            seen_part_text: dict[str, str] = {}
            seen_part_reasoning: dict[str, str] = {}
            seen_tool_sig: dict[str, str] = {}
            async with c.stream("GET", f"{self.serve_url}/event") as stream:
                async for line in stream.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    try:
                        evt = json.loads(line[5:].strip())
                    except json.JSONDecodeError:
                        continue
                    etype = evt.get("type")
                    props = evt.get("properties") or {}
                    if etype == "message.part.updated":
                        part = props.get("part") or {}
                        if part.get("sessionID") != session_id or part.get("synthetic"):
                            continue
                        msg_id = str(part.get("messageID") or "")
                        msg_role = role_by_msg_id.get(msg_id)
                        if msg_role == "user":
                            continue
                        ptype = str(part.get("type") or "text")
                        part_id = str(part.get("id") or f"{msg_id}:{ptype}")
                        # 若用户消息回显早于 message.updated 到达且原文完全一致，提前识别为 user 跳过
                        if msg_role is None and ptype == "text" and not props.get("delta"):
                            raw_txt = str(part.get("text") or "").strip()
                            if raw_txt and raw_txt in (prompt_text.strip(), text.strip()):
                                if msg_id:
                                    role_by_msg_id[msg_id] = "user"
                                continue
                        if ptype == "text":
                            chunk = _extract_incremental_text(seen_part_text, part_id, props.get("delta"), part.get("text"))
                            if chunk:
                                await emit({"type": "TextDelta", "sessionId": session_id, "runId": run_id, "text": chunk})
                        elif ptype == "reasoning":
                            if msg_id:
                                role_by_msg_id[msg_id] = "assistant"
                            chunk = _extract_incremental_text(seen_part_reasoning, part_id, props.get("delta"), part.get("text"))
                            if chunk:
                                await emit({"type": "ThoughtDelta", "sessionId": session_id, "runId": run_id, "text": chunk})
                        elif ptype == "tool":
                            if msg_id:
                                role_by_msg_id[msg_id] = "assistant"
                            tp = _extract_opencode_tool_payload(part)
                            sig = f"{tp['status']}:{len(tp.get('output') or '')}:{bool(tp.get('error'))}:{len(tp.get('media') or [])}"
                            if seen_tool_sig.get(part_id) != sig:
                                seen_tool_sig[part_id] = sig
                                await emit(
                                    build_tool_call_update(
                                        session_id=session_id,
                                        run_id=run_id,
                                        request_id=request_id,
                                        call_id=tp["callId"],
                                        name=tp["name"],
                                        status=tp["status"],
                                        title=tp["title"],
                                        tool_input=tp["input"],
                                        output=tp["output"],
                                        error=tp["error"],
                                        duration_ms=tp["durationMs"],
                                        media=tp.get("media"),
                                    )
                                )
                            t_input = tp.get("input")
                            if tp["name"].lower() in ("todowrite", "todo_write", "todo") and isinstance(t_input, dict) and isinstance(t_input.get("todos"), list):
                                await emit(build_todo_updated_event(session_id=session_id, run_id=run_id, request_id=request_id, items=t_input["todos"]))
                    elif etype == "message.updated":
                        info = props.get("info") if isinstance(props.get("info"), dict) else props
                        if isinstance(info, dict) and info.get("sessionID") == session_id:
                            if info.get("id") and info.get("role"):
                                role_by_msg_id[str(info["id"])] = str(info["role"])
                            if info.get("error"):
                                message, code = _failure_from_error(info.get("error"))
                                await emit({"type": "Failed", "provider": self.provider, "sessionId": session_id,
                                            "runId": run_id, "requestId": request_id, "code": code, "message": message})
                                return
                            if info.get("role", "assistant") == "assistant" and isinstance(info.get("tokens"), dict):
                                counts = extract_usage_counts(info["tokens"])
                                if sum(counts.values()) > 0:
                                    await emit(
                                        build_token_usage_event(
                                            session_id=session_id,
                                            run_id=run_id,
                                            request_id=request_id,
                                            message_id=str(info.get("id") or "") or None,
                                            scope="turn",
                                            input_tokens=counts["inputTokens"],
                                            cached_input_tokens=counts["cachedInputTokens"],
                                            output_tokens=counts["outputTokens"],
                                            reasoning_tokens=counts["reasoningTokens"],
                                            total_tokens=counts["totalTokens"],
                                            model=str(info.get("modelID") or (options or {}).get("model") or "") or None,
                                            source="exact",
                                        )
                                    )
                    elif etype == "permission.asked" and props.get("sessionID") == session_id:
                        perm_id = str(props.get("id") or "")
                        dec = await request_approval(session_id, perm_id, str(props.get("title") or props.get("type") or "tool"), "medium")
                        resp = "once" if dec == "allow_once" else "always" if dec == "allow_session" else "reject"
                        await c.post(f"{self.serve_url}/session/{session_id}/permissions/{perm_id}", json={"response": resp})
                    elif etype == "session.error" and props.get("sessionID") == session_id:
                        # opencode 把模型/额度/上游错误只发在这里（例如 402 Insufficient balance）。
                        # 不转成 Failed 的话，节点会一直等 session.idle，前端就是永远空白的气泡。
                        message, code = _failure_from_error(props.get("error"))
                        await emit({"type": "Failed", "provider": self.provider, "sessionId": session_id,
                                    "runId": run_id, "requestId": request_id, "code": code, "message": message})
                        return
                    elif etype == "session.idle" and props.get("sessionID") == session_id:
                        await emit({"type": "Completed", "sessionId": session_id, "runId": run_id, "requestId": request_id})
                        return
            await emit({"type": "Failed", "provider": self.provider, "sessionId": session_id, "runId": run_id,
                        "requestId": request_id, "code": "stream_closed",
                        "message": "opencode 事件流已关闭但未收到完成信号"})

    async def _send_prompt_v2(
        self,
        c: httpx.AsyncClient,
        *,
        session_id: str,
        text: str,
        request_id: str,
        run_id: str,
        emit: EventEmitter,
        request_approval: ApprovalCallback,
        attachments: list[dict[str, Any]] | None = None,
        options: dict[str, str] | None = None,
    ) -> None:
        if options and options.get("agent"):
            try:
                a_res = await c.post(
                    f"{self.serve_url}/api/session/{session_id}/agent",
                    json={"agent": options["agent"]},
                )
                a_res.raise_for_status()
            except Exception:
                pass
        if options and options.get("model"):
            raw_m = options["model"]
            if "/" in raw_m:
                prov_id, mod_id = raw_m.split("/", 1)
                model_obj: dict[str, Any] = {"providerID": prov_id, "id": mod_id}
            else:
                model_obj = {"providerID": "opencode-go", "id": raw_m}
            if options.get("effort"):
                model_obj["variant"] = options["effort"]
            m_res = await c.post(f"{self.serve_url}/api/session/{session_id}/model", json={"model": model_obj})
            m_res.raise_for_status()

        v2_files: list[dict[str, Any]] = []
        extra_attachments: list[dict[str, Any]] = []
        for att in attachments or []:
            lp = att.get("localPath") if isinstance(att, dict) else None
            if lp and Path(str(lp)).is_file() and Path(str(lp)).stat().st_size <= 6 * 1024 * 1024:
                raw_bytes = Path(str(lp)).read_bytes()
                v2_files.append(
                    {
                        "data": base64.b64encode(raw_bytes).decode("ascii"),
                        "mime": str(att.get("mime") or "application/octet-stream"),
                        "source": {"type": "uri", "uri": Path(str(lp)).as_uri()},
                        "name": str(att.get("fileName") or Path(str(lp)).name),
                    }
                )
            else:
                extra_attachments.append(att)

        prompt_text = merge_prompt_with_attachments(text, extra_attachments)
        body: dict[str, Any] = {"text": prompt_text}
        if v2_files:
            body["files"] = v2_files
        tool_meta: dict[str, dict[str, Any]] = {}
        has_text_emitted = False

        async with c.stream("GET", f"{self.serve_url}/api/event") as stream:
            p_res = await c.post(f"{self.serve_url}/api/session/{session_id}/prompt", json=body)
            p_res.raise_for_status()
            async for line in stream.aiter_lines():
                if not line.startswith("data:"):
                    continue
                try:
                    evt = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue
                etype = str(evt.get("type") or "")
                data = evt.get("data") if isinstance(evt.get("data"), dict) else {}
                form_obj = data.get("form") if isinstance(data.get("form"), dict) else {}
                evt_sid = data.get("sessionID") or form_obj.get("sessionID")
                if evt_sid and evt_sid != session_id:
                    continue

                if etype == "session.text.started":
                    if has_text_emitted:
                        await emit({"type": "TextDelta", "sessionId": session_id, "runId": run_id, "text": "\n\n"})
                elif etype == "session.text.delta":
                    delta = data.get("delta")
                    if isinstance(delta, str) and delta:
                        has_text_emitted = True
                        await emit({"type": "TextDelta", "sessionId": session_id, "runId": run_id, "text": delta})
                elif etype == "session.reasoning.delta":
                    delta = data.get("delta")
                    if isinstance(delta, str) and delta:
                        await emit({"type": "ThoughtDelta", "sessionId": session_id, "runId": run_id, "text": delta})
                elif etype == "session.tool.input.started":
                    call_id = str(data.get("id") or "")
                    name = str(data.get("name") or "tool")
                    if call_id:
                        tool_meta[call_id] = {"name": name, "started": time.monotonic()}
                        await emit(
                            build_tool_call_update(
                                session_id=session_id,
                                run_id=run_id,
                                request_id=request_id,
                                call_id=call_id,
                                name=name,
                                status="running",
                                title=name,
                            )
                        )
                elif etype == "session.tool.called":
                    call_id = str(data.get("id") or "")
                    tmeta = tool_meta.setdefault(call_id, {"name": str(data.get("name") or "tool"), "started": time.monotonic()})
                    name = str(data.get("name") or tmeta.get("name") or "tool")
                    tool_in = data.get("input")
                    title = _summarize_tool_title(name, tool_in)
                    tmeta["title"] = title
                    tmeta["input"] = tool_in
                    sub_sid = None
                    if isinstance(tool_in, dict):
                        sub_sid = str(tool_in.get("session_id") or tool_in.get("sessionID") or "") or None
                    await emit(
                        build_tool_call_update(
                            session_id=session_id,
                            run_id=run_id,
                            request_id=request_id,
                            call_id=call_id,
                            name=name,
                            status="running",
                            title=title,
                            tool_input=tool_in,
                            subagent_session_id=sub_sid,
                        )
                    )
                    if name.lower() in ("todowrite", "todo_write", "todo") and isinstance(tool_in, dict) and isinstance(tool_in.get("todos"), list):
                        await emit(build_todo_updated_event(session_id=session_id, run_id=run_id, request_id=request_id, items=tool_in["todos"]))
                elif etype == "session.tool.progress":
                    call_id = str(data.get("id") or "")
                    meta = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
                    partial = meta.get("output") or meta.get("stdout")
                    sub_sid = str(meta.get("sessionID") or meta.get("childSessionID") or "") or None
                    if call_id and (sub_sid or (isinstance(partial, str) and partial)):
                        tmeta = tool_meta.get(call_id, {})
                        if sub_sid:
                            tmeta["subagentSessionId"] = sub_sid
                        await emit(
                            build_tool_call_update(
                                session_id=session_id,
                                run_id=run_id,
                                request_id=request_id,
                                call_id=call_id,
                                name=str(tmeta.get("name") or "tool"),
                                status="running",
                                title=tmeta.get("title"),
                                delta_output=partial if isinstance(partial, str) else None,
                                subagent_session_id=sub_sid,
                            )
                        )
                elif etype == "session.tool.success":
                    call_id = str(data.get("id") or "")
                    tmeta = tool_meta.pop(call_id, {})
                    started = tmeta.get("started")
                    dur = int((time.monotonic() - started) * 1000) if isinstance(started, (int, float)) else None
                    out_text = _extract_v2_tool_output(data.get("content"))
                    media = _extract_content_media(data.get("content"), tmeta.get("input"))
                    meta = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
                    sub_sid = str(meta.get("sessionID") or meta.get("childSessionID") or tmeta.get("subagentSessionId") or "") or None
                    await emit(
                        build_tool_call_update(
                            session_id=session_id,
                            run_id=run_id,
                            request_id=request_id,
                            call_id=call_id or uuid4().hex,
                            name=str(tmeta.get("name") or "tool"),
                            status="completed",
                            title=tmeta.get("title"),
                            tool_input=tmeta.get("input"),
                            output=out_text,
                            duration_ms=dur,
                            subagent_session_id=sub_sid,
                            media=media or None,
                        )
                    )
                elif etype == "session.tool.failed":
                    call_id = str(data.get("id") or "")
                    tmeta = tool_meta.pop(call_id, {})
                    started = tmeta.get("started")
                    dur = int((time.monotonic() - started) * 1000) if isinstance(started, (int, float)) else None
                    out_text = _extract_v2_tool_output(data.get("content"))
                    err_msg = str(data.get("error") or "Tool execution failed")
                    await emit(
                        build_tool_call_update(
                            session_id=session_id,
                            run_id=run_id,
                            request_id=request_id,
                            call_id=call_id or uuid4().hex,
                            name=str(tmeta.get("name") or "tool"),
                            status="error",
                            title=tmeta.get("title"),
                            tool_input=tmeta.get("input"),
                            output=out_text,
                            error=err_msg,
                            duration_ms=dur,
                        )
                    )
                elif etype == "form.created" and form_obj:
                    await emit(
                        {
                            "type": "FormRequest",
                            "sessionId": session_id,
                            "runId": run_id,
                            "requestId": request_id,
                            "formId": str(form_obj.get("id") or ""),
                            "title": str(form_obj.get("title") or "需要补充确认信息"),
                            "fields": form_obj.get("fields") or [],
                        }
                    )
                elif etype in ("form.replied", "form.cancelled") and data.get("id"):
                    await emit(
                        {
                            "type": "FormResolved",
                            "sessionId": session_id,
                            "formId": str(data["id"]),
                            "cancelled": etype == "form.cancelled",
                        }
                    )
                elif etype == "session.step.ended":
                    tokens = data.get("tokens")
                    if isinstance(tokens, dict):
                        counts = extract_usage_counts(tokens)
                        if sum(counts.values()) > 0:
                            sel_model = (options or {}).get("model") or ""
                            ctx_win = self._model_context_windows.get(sel_model)
                            await emit(
                                build_token_usage_event(
                                    session_id=session_id,
                                    run_id=run_id,
                                    request_id=request_id,
                                    message_id=str(data.get("assistantMessageID") or "") or None,
                                    scope="turn",
                                    input_tokens=counts["inputTokens"],
                                    cached_input_tokens=counts["cachedInputTokens"],
                                    output_tokens=counts["outputTokens"],
                                    reasoning_tokens=counts["reasoningTokens"],
                                    total_tokens=counts["totalTokens"],
                                    context_window=ctx_win,
                                    model=sel_model or None,
                                    source="exact",
                                )
                            )
                elif etype == "permission.asked":
                    perm_id = str(data.get("id") or "")
                    cmd_desc = str(data.get("title") or data.get("permission") or data.get("resource") or data.get("type") or "tool")
                    dec = await request_approval(session_id, perm_id, cmd_desc, "medium")
                    decision = "once" if dec == "allow_once" else "always" if dec == "allow_session" else "reject"
                    await c.post(f"{self.serve_url}/api/session/{session_id}/permission/{perm_id}/reply", json={"decision": decision})
                elif etype == "session.renamed" and data.get("title"):
                    await emit({"type": "SessionRenamed", "sessionId": session_id, "title": str(data["title"])})
                elif etype == "session.execution.failed":
                    message, code = _failure_from_error(data.get("error"))
                    await emit({"type": "Failed", "provider": self.provider, "sessionId": session_id, "runId": run_id, "requestId": request_id, "code": code, "message": message})
                    return
                elif etype == "session.execution.interrupted":
                    await emit({"type": "Failed", "provider": self.provider, "sessionId": session_id, "runId": run_id, "requestId": request_id, "code": "cancelled", "message": "已中断当前 OpenCode 任务"})
                    return
                elif etype == "session.execution.succeeded":
                    await emit({"type": "Completed", "sessionId": session_id, "runId": run_id, "requestId": request_id})
                    return

        await emit({"type": "Failed", "provider": self.provider, "sessionId": session_id, "runId": run_id,
                    "requestId": request_id, "code": "stream_closed",
                    "message": "opencode v2 事件流已关闭但未收到完成信号"})

    async def list_agents(self) -> list[dict[str, Any]]:
        async with self._client() as c:
            prefix = await self._detect_api_prefix(c)
            if prefix != "/api":
                # 兜底直接探测 /api/agent，兼容未预先挂载 /api/session 的服务端或测试桩
                res = await c.get(f"{self.serve_url}/api/agent")
                if not self._is_json_response(res):
                    return []
                self._api_prefix = "/api"
            else:
                res = await c.get(f"{self.serve_url}/api/agent")
            if res.status_code != 200:
                return []
            raw = res.json() or {}
            rows = raw.get("data", []) if isinstance(raw, dict) else (raw if isinstance(raw, list) else [])
            out: list[dict[str, Any]] = []
            for r in rows:
                if not isinstance(r, dict) or r.get("hidden"):
                    continue
                aid = str(r.get("id") or r.get("name") or "").strip()
                if not aid:
                    continue
                out.append(
                    {
                        "id": aid,
                        "name": str(r.get("name") or aid),
                        "description": str(r.get("description") or ""),
                        "mode": str(r.get("mode") or "primary"),
                    }
                )
            return out

    async def list_mcp_servers(self) -> list[dict[str, Any]]:
        async with self._client() as c:
            prefix = await self._detect_api_prefix(c)
            if prefix != "/api":
                return []
            res = await c.get(f"{self.serve_url}/api/mcp")
            if res.status_code != 200:
                return []
            data = (res.json() or {}).get("data") or []
            if isinstance(data, dict):
                return [{"name": k, **(v if isinstance(v, dict) else {"status": str(v)})} for k, v in data.items()]
            return [item for item in data if isinstance(item, dict)]

    async def reply_form(
        self,
        *,
        session_id: str,
        form_id: str,
        answer: dict[str, Any] | None = None,
        cancel: bool = False,
    ) -> dict[str, Any]:
        async with self._client() as c:
            prefix = await self._detect_api_prefix(c)
            await self._session_directory(c, prefix, session_id)
            if prefix != "/api":
                return {"sessionId": session_id, "formId": form_id, "cancelled": cancel}
            if cancel:
                res = await c.delete(f"{self.serve_url}/api/session/{session_id}/form/{form_id}")
            else:
                res = await c.post(
                    f"{self.serve_url}/api/session/{session_id}/form/{form_id}/reply",
                    json={"answer": answer or {}},
                )
            res.raise_for_status()
            return {"sessionId": session_id, "formId": form_id, "cancelled": cancel}

    async def cancel(self, *, session_id: str, run_id: str | None = None) -> None:
        async with self._client() as c:
            prefix = await self._detect_api_prefix(c)
            await self._session_directory(c, prefix, session_id)
            if prefix == "/api":
                await c.post(f"{self.serve_url}/api/session/{session_id}/interrupt")
            else:
                await c.post(f"{self.serve_url}/session/{session_id}/abort")

    async def rename_session(self, *, session_id: str, title: str) -> dict[str, Any]:
        async with self._client() as c:
            prefix = await self._detect_api_prefix(c)
            await self._session_directory(c, prefix, session_id)
            res = await c.patch(f"{self.serve_url}{prefix}/session/{session_id}", json={"title": title})
            if res.status_code < 400:
                return {"sessionId": session_id, "title": title}
        return {"sessionId": session_id, "title": title}

    async def delete_session(self, *, session_id: str) -> None:
        async with self._client() as c:
            prefix = await self._detect_api_prefix(c)
            await self._session_directory(c, prefix, session_id)
            await c.delete(f"{self.serve_url}{prefix}/session/{session_id}")

    async def compact_session(self, *, session_id: str) -> dict[str, Any]:
        async with self._client() as c:
            prefix = await self._detect_api_prefix(c)
            await self._session_directory(c, prefix, session_id)
            if prefix == "/api":
                res = await c.post(f"{self.serve_url}/api/session/{session_id}/compact", json={})
            else:
                res = await c.post(f"{self.serve_url}/session/{session_id}/summarize", json={})
            if res.status_code < 400:
                return {"supported": True, "message": "已通知 OpenCode 压缩会话上下文"}
        return {"supported": False}
