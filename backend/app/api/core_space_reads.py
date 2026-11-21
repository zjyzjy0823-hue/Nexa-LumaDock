"""Local JWT-authenticated proxy for the device's Core Shared Space reads."""

import logging
import re
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, contextmanager
from contextvars import ContextVar
from typing import Annotated

import httpx
from anyio import CancelScope
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.routing import APIRoute
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import Receive, Scope, Send

from .. import core_connection
from ..models import User
from ..runtime_mode import require_local_mode
from ..security import current_user


CORE_PREFIX = "/api/v1/client/space-reads"
UUID_PATTERN = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", re.IGNORECASE | re.ASCII)
NO_STORE = {"Cache-Control": "no-store"}
FORWARDED_HEADERS = ("Content-Type", "Content-Disposition", "X-Chunk-Sha256")
_device_read_request = ContextVar("device_read_request", default=False)


def _allow_http_log(_record: logging.LogRecord) -> bool:
    return not _device_read_request.get()


# HTTPX logs request queries and HTTP Core debug traces include response headers.
for _logger_name in ("httpx", "httpcore.connection", "httpcore.http11", "httpcore.http2"):
    logging.getLogger(_logger_name).addFilter(_allow_http_log)


@contextmanager
def _quiet_core_http():
    token = _device_read_request.set(True)
    try:
        yield
    finally:
        _device_read_request.reset(token)


class _NoStoreRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def no_store(request: Request):
            try:
                with _quiet_core_http():
                    response = await handler(request)
            except StarletteHTTPException as exc:
                response = JSONResponse(
                    {"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers,
                )
            except RequestValidationError:
                response = JSONResponse({"detail": "Invalid request"}, status_code=422)
            response.headers.update(NO_STORE)
            return response

        return no_store


router = APIRouter(
    prefix="/api/v1/core/space-reads",
    tags=["core-space-reads"],
    dependencies=[Depends(require_local_mode)],
    route_class=_NoStoreRoute,
)


def _connection(user: User = Depends(current_user)) -> tuple[httpx.URL, str]:
    try:
        metadata = core_connection.load_connection(user.id)
    except HTTPException as exc:
        if exc.status_code == 409:
            raise HTTPException(409, "Core not connected") from None
        raise
    if metadata is None:
        raise HTTPException(409, "Core not connected")
    try:
        origin = httpx.URL(metadata.coreUrl)
    except httpx.InvalidURL:
        raise HTTPException(400, "Invalid Core origin") from None
    if origin.scheme != "https" and not (origin.scheme == "http" and origin.host in {"127.0.0.1", "localhost"}):
        raise HTTPException(400, "Core requires HTTPS or loopback HTTP")
    try:
        credential = core_connection.credential_store.load(user.id)
    except OSError:
        raise HTTPException(502, "Core unavailable") from None
    # A disconnect or rebind can replace the pairing during the credential read.
    if (not credential or not credential.startswith("nc_live_")
            or core_connection.load_connection(user.id) != metadata):
        raise HTTPException(409, "Core not connected")
    return origin, credential


Connection = Annotated[tuple[httpx.URL, str], Depends(_connection)]


def _uuid(value: str) -> str:
    if not UUID_PATTERN.fullmatch(value):
        raise HTTPException(422, "Invalid resource ID")
    return value.lower()


def _check_status(status: int) -> None:
    if 200 <= status < 300:
        return
    if status in (401, 403):
        raise HTTPException(401, "Core authorization required")
    if status == 404:
        raise HTTPException(404, "Not found")
    if status == 409:
        raise HTTPException(409, "Core conflict")
    if status in (400, 422):
        raise HTTPException(status, "Invalid Core request")
    raise HTTPException(502, "Core unavailable")


class _CoreStream(StreamingResponse):
    def __init__(self, body: AsyncIterator[bytes], headers: dict[str, str], resources: AsyncExitStack):
        super().__init__(body, headers=headers)
        self.resources = resources

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        with _quiet_core_http():
            try:
                await super().__call__(scope, receive, send)
            finally:
                with CancelScope(shield=True):
                    await self.resources.aclose()


async def _proxy(connection: tuple[httpx.URL, str], path: str, *, params=None, stream: bool = False):
    origin, credential = connection
    timeout = httpx.Timeout(300.0 if stream else 30.0, connect=5.0)
    async with AsyncExitStack() as resources:
        client = await resources.enter_async_context(
            httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False)
        )
        try:
            request = client.build_request(
                "GET", origin.copy_with(path=CORE_PREFIX + path), params=params,
                headers={
                    "Authorization": f"Bearer {credential}",
                    "Cache-Control": "no-store",
                    "Accept-Encoding": "identity",
                },
            )
            upstream = await client.send(request, stream=True)
            resources.push_async_callback(upstream.aclose)
            _check_status(upstream.status_code)
            if not stream:
                await upstream.aread()
                return JSONResponse(upstream.json())

            headers = {name: upstream.headers[name] for name in FORWARDED_HEADERS if name in upstream.headers}
            if "Content-Encoding" not in upstream.headers and "Content-Length" in upstream.headers:
                headers["Content-Length"] = upstream.headers["Content-Length"]
            chunks = upstream.aiter_bytes(64 * 1024)
            first = await anext(chunks, None)
        except (httpx.RequestError, httpx.InvalidURL, ValueError):
            raise HTTPException(502, "Core unavailable") from None

        async def body():
            if first is not None:
                yield first
            try:
                async for chunk in chunks:
                    yield chunk
            except httpx.RequestError:
                # The status and headers have already been sent. Terminate the download.
                raise RuntimeError("Core download interrupted") from None

        return _CoreStream(body(), headers, resources.pop_all())


@router.get("/status")
async def status(connection: Connection):
    return await _proxy(connection, "/status")


@router.get("/spaces")
async def list_spaces(connection: Connection):
    return await _proxy(connection, "/spaces")


@router.get("/spaces/{space_id}")
async def get_space(space_id: str, connection: Connection):
    return await _proxy(connection, f"/spaces/{_uuid(space_id)}")


@router.get("/spaces/{space_id}/entries")
async def list_entries(space_id: str, request: Request, connection: Connection):
    return await _proxy(connection, f"/spaces/{_uuid(space_id)}/entries", params=request.query_params.multi_items())


@router.get("/spaces/{space_id}/entries/{entry_id}")
async def get_entry(space_id: str, entry_id: str, connection: Connection):
    return await _proxy(connection, f"/spaces/{_uuid(space_id)}/entries/{_uuid(entry_id)}")


@router.get("/spaces/{space_id}/entries/{entry_id}/download", response_class=StreamingResponse)
async def download_entry(space_id: str, entry_id: str, connection: Connection):
    return await _proxy(connection, f"/spaces/{_uuid(space_id)}/entries/{_uuid(entry_id)}/download", stream=True)


@router.get("/spaces/{space_id}/blobs/{blob_id}/chunks/{chunk_index}", response_class=StreamingResponse)
async def get_chunk(space_id: str, blob_id: str, chunk_index: int, connection: Connection):
    return await _proxy(connection, f"/spaces/{_uuid(space_id)}/blobs/{_uuid(blob_id)}/chunks/{chunk_index}", stream=True)
