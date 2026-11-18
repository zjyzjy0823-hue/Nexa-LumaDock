"""OpenCode 适配器：对接 `opencode serve` REST + SSE `/event` 接口。"""

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from .base import (
    AdapterProbe,
    AgentAdapter,
    ApprovalCallback,
    EventEmitter,
    build_token_usage_event,
    extract_usage_counts,
    merge_prompt_with_attachments,
    prepare_session_dir,
)


class OpenCodeAdapter(AgentAdapter):
    provider = "opencode"

    def __init__(
        self,
        allowed_roots: tuple[Path, ...],
        *,
        serve_url: str = "http://127.0.0.1:4096",
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        self.allowed_roots = allowed_roots
        self.serve_url = serve_url.rstrip("/")
        self._auth = httpx.BasicAuth(username, password) if username and password is not None else None

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(auth=self._auth, timeout=httpx.Timeout(60.0, connect=4.0))

    async def probe(self) -> AdapterProbe:
        caps = ("chat", "history", "approval", "worktree", "models")
        try:
            async with self._client() as c:
                res = await c.get(f"{self.serve_url}/session")
                if res.status_code < 500:
                    return AdapterProbe(provider=self.provider, version="serve-http", status="ready", capabilities=caps)
        except Exception:
            pass
        return AdapterProbe(provider=self.provider, version="", status="unavailable", capabilities=caps)

    async def list_models(self) -> list[dict[str, Any]]:
        async with self._client() as client:
            response = await client.get(f"{self.serve_url}/provider")
            response.raise_for_status()
            catalog = response.json()
            return [{"id": f"{provider['id']}/{key}", "label": model.get("name") or key,
                     "efforts": list(model.get("variants") or {})}
                    for provider in catalog.get("all", []) if provider["id"] in catalog.get("connected", [])
                    for key, model in provider.get("models", {}).items()]

    async def list_sessions(self, *, page: int = 1, limit: int = 30) -> list[dict[str, Any]]:
        async with self._client() as c:
            res = await c.get(f"{self.serve_url}/session")
            res.raise_for_status()
            rows = res.json() if isinstance(res.json(), list) else []
            return [
                {"sessionId": s.get("id"), "provider": self.provider, "title": s.get("title") or s.get("id"), "cwd": s.get("directory", "")}
                for s in rows[:limit]
                if isinstance(s, dict) and s.get("id")
            ]

    async def open_session(
        self,
        *,
        cwd: str,
        session_id: str | None = None,
        use_worktree: bool = False,
    ) -> dict[str, Any]:
        sid_seed = session_id or f"oc-{uuid4().hex[:8]}"
        eff_cwd, wt_path = prepare_session_dir(cwd, self.allowed_roots, session_id=sid_seed, use_worktree=use_worktree)
        if session_id:
            return {"sessionId": session_id, "provider": self.provider, "cwd": str(eff_cwd), "worktreePath": wt_path, "title": f"OpenCode ({eff_cwd.name})"}
        async with self._client() as c:
            res = await c.post(f"{self.serve_url}/session", json={"directory": str(eff_cwd)})
            res.raise_for_status()
            data = res.json()
            sid = str(data.get("id") or sid_seed)
            return {"sessionId": sid, "provider": self.provider, "cwd": str(eff_cwd), "worktreePath": wt_path, "title": data.get("title") or sid}

    async def get_history(self, *, session_id: str, limit: int = 50) -> list[dict[str, Any]]:
        async with self._client() as c:
            res = await c.get(f"{self.serve_url}/session/{session_id}/message", params={"limit": limit})
            if res.status_code != 200:
                return []
            items = res.json() if isinstance(res.json(), list) else []
            out: list[dict[str, Any]] = []
            for msg in items[-limit:]:
                info = msg.get("info") or {}
                parts = msg.get("parts") or []
                text = "".join(p.get("text", "") for p in parts if isinstance(p, dict) and p.get("type") == "text")
                out.append({"role": info.get("role", "assistant"), "text": text})
            return out

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
        await emit({"type": "Accepted", "sessionId": session_id, "runId": run_id, "requestId": request_id, "provider": self.provider})
        async with self._client() as c:
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
                        if part.get("sessionID") == session_id and part.get("type") == "text":
                            await emit({"type": "TextDelta", "sessionId": session_id, "runId": run_id, "text": str(props.get("delta") or part.get("text") or "")})
                    elif etype == "message.updated":
                        info = props.get("info") if isinstance(props.get("info"), dict) else props
                        if (
                            isinstance(info, dict)
                            and info.get("sessionID") == session_id
                            and info.get("role", "assistant") == "assistant"
                            and isinstance(info.get("tokens"), dict)
                        ):
                            c = extract_usage_counts(info["tokens"])
                            if sum(c.values()) > 0:
                                await emit(
                                    build_token_usage_event(
                                        session_id=session_id,
                                        run_id=run_id,
                                        request_id=request_id,
                                        message_id=str(info.get("id") or "") or None,
                                        scope="turn",
                                        input_tokens=c["inputTokens"],
                                        cached_input_tokens=c["cachedInputTokens"],
                                        output_tokens=c["outputTokens"],
                                        reasoning_tokens=c["reasoningTokens"],
                                        total_tokens=c["totalTokens"],
                                        model=str(info.get("modelID") or (options or {}).get("model") or "") or None,
                                        source="exact",
                                    )
                                )
                    elif etype == "permission.asked" and props.get("sessionID") == session_id:
                        perm_id = str(props.get("id") or "")
                        dec = await request_approval(session_id, perm_id, str(props.get("title") or props.get("type") or "tool"), "medium")
                        resp = "once" if dec == "allow_once" else "always" if dec == "allow_session" else "reject"
                        await c.post(f"{self.serve_url}/session/{session_id}/permissions/{perm_id}", json={"response": resp})
                    elif etype == "session.idle" and props.get("sessionID") == session_id:
                        await emit({"type": "Completed", "sessionId": session_id, "runId": run_id, "requestId": request_id})
                        return

    async def cancel(self, *, session_id: str, run_id: str | None = None) -> None:
        async with self._client() as c:
            await c.post(f"{self.serve_url}/session/{session_id}/abort")
