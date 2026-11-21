"""Short-lived, authenticated LAN previews of an AgentNode's loopback HTTP service."""

import asyncio
from contextlib import nullcontext
from dataclasses import dataclass
from inspect import signature
import logging
import secrets
import socket
import time
from urllib.parse import urlsplit

import httpx
import uvicorn
import websockets
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse, RedirectResponse, StreamingResponse
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket


_TTL = 900
_MAX_REQUEST = 8 * 1024 * 1024
_HOP_HEADERS = {
    "authorization", "connection", "cookie", "expect", "forwarded", "host", "keep-alive",
    "proxy-authenticate", "proxy-authorization", "proxy-connection", "referer", "set-cookie", "te", "trailer",
    "transfer-encoding", "upgrade", "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto",
}
_LOG = logging.getLogger(__name__)
_NO_PROXY = {"proxy": None} if "proxy" in signature(websockets.connect).parameters else {}


def _make_app(host: str, public_port: int, target_port: int, tls: bool, ticket: str, expires: float) -> Starlette:
    authority = f"{host}:{public_port}"
    origin = f"http://{authority}"
    cookie = f"studiolo_preview_{public_port}"
    upstream = httpx.URL(f"{'https' if tls else 'http'}://127.0.0.1:{target_port}")
    issued_cookie = secrets.token_urlsafe(32)
    ticket_used = False

    def matching_host(headers) -> bool:
        return headers.get("host") == authority and time.monotonic() < expires

    async def proxy(request: Request):
        nonlocal ticket_used
        if not matching_host(request.headers):
            return PlainTextResponse("Preview expired or unavailable", status_code=404)
        authorized = secrets.compare_digest(request.cookies.get(cookie, "").encode(), issued_cookie.encode())
        if request.url.path.startswith("/__studiolo_preview/"):
            correct_ticket = secrets.compare_digest(request.url.path.encode(), f"/__studiolo_preview/{ticket}".encode())
            if request.method != "GET" or not correct_ticket or (ticket_used and not authorized):
                return PlainTextResponse("Preview access required", status_code=403)
            response = RedirectResponse("/", status_code=303, headers={"Referrer-Policy": "no-referrer", "Cache-Control": "no-store"})
            if not ticket_used:
                ticket_used = True
                response.set_cookie(cookie, issued_cookie, max_age=_TTL, httponly=True, samesite="lax")
            return response
        if not authorized:
            return PlainTextResponse("Preview access required", status_code=403)
        requesting_origin = request.headers.get("origin")
        if requesting_origin and requesting_origin != origin:
            return PlainTextResponse("Invalid preview origin", status_code=403)
        payload = bytearray()
        async for chunk in request.stream():
            payload.extend(chunk)
            if len(payload) > _MAX_REQUEST:
                return PlainTextResponse("Preview request is too large", status_code=413)
        raw = request.scope.get("raw_path") or b"/"
        if request.scope["query_string"]:
            raw += b"?" + request.scope["query_string"]
        headers = {key: value for key, value in request.headers.items() if key.lower() not in _HOP_HEADERS}
        if requesting_origin:
            headers["origin"] = str(upstream).rstrip("/")
        client = httpx.AsyncClient(trust_env=False, timeout=12)
        try:
            outgoing = client.build_request(request.method, upstream.copy_with(raw_path=raw), headers=headers, content=bytes(payload))
            received = await client.send(outgoing, stream=True)
        except httpx.HTTPError:
            await client.aclose()
            return PlainTextResponse("Node preview service is unavailable", status_code=502)

        async def response_body():
            try:
                async for chunk in received.aiter_raw():
                    yield chunk
            finally:
                await received.aclose()
                await client.aclose()

        result_headers = {key: value for key, value in received.headers.items() if key.lower() not in _HOP_HEADERS}
        result_headers.update({"referrer-policy": "no-referrer", "cache-control": "no-store"})
        location = result_headers.get("location")
        if location:
            try:
                parsed = urlsplit(location)
                if parsed.hostname in {"127.0.0.1", "localhost", "0.0.0.0", "::1"} and parsed.port == target_port:
                    result_headers["location"] = (parsed.path or "/") + ("?" + parsed.query if parsed.query else "")
            except ValueError:
                result_headers.pop("location", None)
        return StreamingResponse(response_body(), status_code=received.status_code, headers=result_headers)

    async def socket_proxy(browser: WebSocket):
        if not matching_host(browser.headers) or browser.headers.get("origin") != origin or not secrets.compare_digest(
            browser.cookies.get(cookie, "").encode(), issued_cookie.encode()
        ):
            await browser.close(code=1008)
            return
        raw = browser.scope.get("raw_path") or b"/"
        if browser.scope["query_string"]:
            raw += b"?" + browser.scope["query_string"]
        target = upstream.copy_with(scheme="wss" if tls else "ws", raw_path=raw)
        try:
            async with websockets.connect(str(target), origin=str(upstream).rstrip("/"),
                                          subprotocols=browser.scope["subprotocols"], max_size=_MAX_REQUEST,
                                          open_timeout=5, **_NO_PROXY) as service:
                await browser.accept(subprotocol=service.subprotocol)

                async def from_browser():
                    while True:
                        event = await browser.receive()
                        if event["type"] == "websocket.disconnect":
                            return
                        await service.send(event["bytes"] if event.get("bytes") is not None else event["text"])

                async def from_service():
                    async for message in service:
                        if isinstance(message, bytes):
                            await browser.send_bytes(message)
                        else:
                            await browser.send_text(message)

                tasks = [asyncio.create_task(from_browser()), asyncio.create_task(from_service())]
                try:
                    await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                finally:
                    for task in tasks:
                        task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
        except (OSError, TimeoutError, websockets.WebSocketException):
            pass
        finally:
            try:
                await browser.close()
            except RuntimeError:
                pass

    routes = [Route("/{path:path}", proxy, methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]),
              WebSocketRoute("/{path:path}", socket_proxy)]
    return Starlette(routes=routes)


@dataclass
class Preview:
    server: uvicorn.Server
    task: asyncio.Task
    socket: socket.socket


class PreviewServer(uvicorn.Server):
    def capture_signals(self):
        return nullcontext()


class PortPreviewManager:
    def __init__(self) -> None:
        self._leases: dict[tuple[str, str, int], Preview] = {}

    async def open(self, provider: str, sid: str, host: str, target_port: int, tls: bool = False) -> str:
        key = (provider, sid, target_port)
        if key not in self._leases and len(self._leases) >= 4:
            raise ValueError("节点已有 4 个端口预览，请等待其到期")
        async with asyncio.timeout(2):
            _, writer = await asyncio.open_connection("127.0.0.1", target_port)
            writer.close()
            await writer.wait_closed()
        if key not in self._leases and len(self._leases) >= 4:
            raise ValueError("节点已有 4 个端口预览，请等待其到期")
        previous = self._leases.pop(key, None)
        if previous:
            previous.server.should_exit = True
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            listener.bind((host, 0))
            port = listener.getsockname()[1]
            token = secrets.token_urlsafe(32)
            app = _make_app(host, port, target_port, tls, token, time.monotonic() + _TTL)
            server = PreviewServer(uvicorn.Config(app, log_level="warning", access_log=False,
                                                   proxy_headers=False, timeout_graceful_shutdown=2))
            task = asyncio.create_task(server.serve(sockets=[listener]))
            lease = Preview(server, task, listener)
            self._leases[key] = lease

            def stop():
                server.should_exit = True

            expiry = asyncio.get_running_loop().call_later(_TTL, stop)

            def cleanup(done: asyncio.Task):
                expiry.cancel()
                listener.close()
                if self._leases.get(key) is lease:
                    self._leases.pop(key)
                if not done.cancelled() and done.exception() is not None:
                    _LOG.error("LAN preview listener stopped unexpectedly")

            task.add_done_callback(cleanup)
            async with asyncio.timeout(2):
                while not server.started:
                    if task.done():
                        await task
                        raise OSError("Preview listener failed to start")
                    await asyncio.sleep(0.02)
            return f"http://{host}:{port}/__studiolo_preview/{token}"
        except BaseException:
            if key in self._leases and self._leases[key].socket is listener:
                self._leases[key].server.should_exit = True
            else:
                listener.close()
            raise

    async def close(self, session: tuple[str, str] | None = None) -> None:
        previews = [preview for key, preview in self._leases.items() if session is None or key[:2] == session]
        for preview in previews:
            preview.server.should_exit = True
        await asyncio.gather(*(preview.task for preview in previews), return_exceptions=True)
