"""Local authentication, transport policy, and streaming for Core device reads."""

import asyncio
import logging
from dataclasses import replace
from datetime import datetime, timezone
from uuid import uuid4

import httpx
import pytest
from fastapi.responses import StreamingResponse
from starlette.requests import ClientDisconnect

from app import core_connection, runtime_mode
from app.api import core_space_reads


LOCAL = "/api/v1/core/space-reads"
CORE = "/api/v1/client/space-reads"
CREDENTIAL = "nc_live_proxy_test"
ORIGIN = "https://core.example"


@pytest.fixture
def pair(client, users, monkeypatch, tmp_path):
    monkeypatch.setattr(runtime_mode, "runtime_config", replace(runtime_mode.runtime_config, mode="local"))
    monkeypatch.setenv("STUDIOLO_DATA_DIR", str(tmp_path))
    owner, other = users
    user_id = client.get("/api/v1/auth/me", headers=owner).json()["id"]

    def connect(origin=ORIGIN):
        metadata = core_connection.CoreConnectionMetadata(
            schemaVersion=1, coreUrl=origin, clientId=str(uuid4()), workspaceId=str(uuid4()),
            installationId=str(uuid4()), clientName="Laptop", platform="macos", appVersion="0.8.0",
            connectedAt=datetime.now(timezone.utc).isoformat(),
        )
        core_connection._persist_connection(user_id, metadata, CREDENTIAL)

    return owner, other, connect


@pytest.fixture
def mock_core(monkeypatch):
    client_class = httpx.AsyncClient

    def install(handler):
        def create(**kwargs):
            assert kwargs["follow_redirects"] is False
            assert kwargs["trust_env"] is False
            return client_class(transport=httpx.MockTransport(handler), **kwargs)

        monkeypatch.setattr(core_space_reads.httpx, "AsyncClient", create)

    return install


def test_local_auth_connection_and_whitelist(client, pair, mock_core):
    owner, other, connect = pair
    connect()
    calls = []
    mock_core(lambda request: calls.append(request) or httpx.Response(200, json=[]))
    assert client.get(f"{LOCAL}/spaces").status_code == 401
    assert client.get(f"{LOCAL}/spaces", headers={"Authorization": f"Bearer {CREDENTIAL}"}).status_code == 401
    missing = client.get(f"{LOCAL}/spaces", headers=other)
    assert missing.status_code == 409
    assert missing.json() == {"detail": "Core not connected"}
    expected = client.get(f"{LOCAL}/spaces/not-an-id", headers=owner)
    assert expected.status_code == 422
    assert expected.headers["cache-control"] == "no-store"
    space_id = uuid4()
    for path in (
        f"{LOCAL}/%2e%2e/%2e%2e/spaces",
        f"{LOCAL}/spaces/%2e%2e",
        f"{LOCAL}/spaces/{space_id}/entries/bad-id",
        f"{LOCAL}/spaces/{space_id}/blobs/bad-id/chunks/0",
        f"{LOCAL}/spaces/{space_id}/blobs/{uuid4()}/chunks/not-an-index",
        f"{LOCAL}/spaces/{space_id}/tokens",
    ):
        assert client.get(path, headers=owner).status_code in (404, 422)
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        assert client.request(method, f"{LOCAL}/spaces", headers=owner).status_code == 405
    assert calls == []


def test_pairing_replaced_between_metadata_and_credential_read(client, pair, mock_core, monkeypatch):
    owner, _, connect = pair
    connect()
    user_id = client.get("/api/v1/auth/me", headers=owner).json()["id"]
    first = core_connection.load_connection(user_id)
    connect("https://replacement.example")
    second = core_connection.load_connection(user_id)
    pairings = iter([first, second])
    monkeypatch.setattr(core_connection, "load_connection", lambda _: next(pairings, second))
    mock_core(lambda _: pytest.fail("Core request must not use an obsolete pairing"))
    response = client.get(f"{LOCAL}/spaces", headers=owner)
    assert response.status_code == 409
    assert response.json() == {"detail": "Core not connected"}


@pytest.mark.parametrize(("origin", "status"), [
    ("http://core.example", 400), ("http://localhost.example", 400),
    ("http://127.0.0.1:8000", 200), ("http://localhost:8000", 200), (ORIGIN, 200),
])
def test_origin_transport_gate(client, pair, mock_core, origin, status):
    owner, _, connect = pair
    connect(origin)
    calls = []
    mock_core(lambda request: calls.append(request) or httpx.Response(200, json={"status": "ready"}))
    response = client.get(f"{LOCAL}/status", headers=owner)
    assert response.status_code == status
    assert response.headers["cache-control"] == "no-store"
    if status == 200:
        assert [str(call.url) for call in calls] == [origin + CORE + "/status"]
    else:
        assert calls == []


@pytest.mark.parametrize(("upstream", "local", "detail"), [
    (401, 401, "Core authorization required"), (403, 401, "Core authorization required"),
    (404, 404, "Not found"), (409, 409, "Core conflict"),
    (302, 502, "Core unavailable"), (304, 502, "Core unavailable"),
    (500, 502, "Core unavailable"), ("timeout", 502, "Core unavailable"),
])
def test_safe_error_mapping(client, pair, mock_core, caplog, upstream, local, detail):
    owner, _, connect = pair
    connect()
    auth = f"Bearer {CREDENTIAL}"
    private_body = "Private document text"
    private_name = "private-file.pdf"
    calls = []

    def handle(request):
        calls.append(request)
        assert request.headers["authorization"] == auth
        assert request.extensions["timeout"]["read"] == 30
        if upstream == "timeout":
            raise httpx.ReadTimeout(f"{auth} {private_name}", request=request)
        return httpx.Response(upstream, json={"detail": private_body}, headers={
            "Location": f"https://redirect.example/{private_name}",
            "Content-Disposition": f'attachment; filename="{private_name}"',
        }, extensions={"reason_phrase": private_name.encode()})

    mock_core(handle)
    with caplog.at_level(logging.DEBUG):
        response = client.get(f"{LOCAL}/spaces", headers=owner)
    assert response.status_code == local
    assert response.json() == {"detail": detail}
    assert response.headers["cache-control"] == "no-store"
    assert len(calls) == 1
    for private in ("Authorization", CREDENTIAL, private_body, private_name):
        assert private not in caplog.text


def test_fixed_paths_entries_query_and_binary_headers(client, pair, mock_core):
    owner, _, connect = pair
    connect()
    space = f"/spaces/{uuid4()}"
    entry = f"{space}/entries/{uuid4()}"
    download = f"{entry}/download"
    chunk = f"{space}/blobs/{uuid4()}/chunks/2"
    paths = ["/status", "/spaces", space, f"{space}/entries", entry, download, chunk]
    calls = []

    def handle(request):
        calls.append(request.url.path)
        assert request.method == "GET"
        assert request.headers["authorization"] == f"Bearer {CREDENTIAL}"
        assert request.headers["cache-control"] == "no-store"
        assert request.extensions["timeout"]["connect"] == 5
        assert request.extensions["timeout"]["read"] == (300 if request.url.path in (CORE + download, CORE + chunk) else 30)
        if request.url.path == CORE + download:
            return httpx.Response(200, content=b"file", headers={
                "Content-Type": "text/plain", "Content-Disposition": "attachment; filename*=UTF-8''test.txt",
            })
        if request.url.path == CORE + chunk:
            return httpx.Response(200, content=b"chunk", headers={"X-Chunk-Sha256": "chunk-digest"})
        if request.url.path == CORE + f"{space}/entries":
            assert request.url.params.multi_items() == [
                ("search", "a & b"), ("entryType", "text"), ("limit", "1"), ("offset", "2"),
            ]
        return httpx.Response(200, json={"path": request.url.path})

    mock_core(handle)
    for path in paths:
        params = {"search": "a & b", "entryType": "text", "limit": 1, "offset": 2} if path == f"{space}/entries" else None
        response = client.get(LOCAL + path, headers=owner, params=params)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        if path == download:
            assert response.headers["content-disposition"] == "attachment; filename*=UTF-8''test.txt"
            assert response.content == b"file"
        elif path == chunk:
            assert response.headers["x-chunk-sha256"] == "chunk-digest"
            assert response.content == b"chunk"
        else:
            assert response.json() == {"path": CORE + path}
    assert calls == [CORE + path for path in paths]


@pytest.mark.parametrize("disconnect", [False, True])
def test_download_streams_64k_and_closes_upstream(mock_core, disconnect):
    size = 64 * 1024
    consumed = []
    closed = []

    class Upstream(httpx.AsyncByteStream):
        async def __aiter__(self):
            for i in range(4):
                consumed.append(i)
                yield bytes([i]) * size

        async def aclose(self):
            closed.append(True)

    mock_core(lambda _: httpx.Response(200, stream=Upstream(), headers={"Content-Length": str(4 * size)}))

    async def run():
        response = await core_space_reads.download_entry(str(uuid4()), str(uuid4()), (httpx.URL(ORIGIN), CREDENTIAL))
        assert isinstance(response, StreamingResponse)
        assert consumed == [0]
        assert not closed
        sent = []

        async def send(message):
            if message["type"] == "http.response.body" and message["body"]:
                if disconnect:
                    raise OSError("Connection closed")
                assert len(message["body"]) == size
                sent.append(message["body"][0])
                assert sent == consumed

        scope = {"type": "http", "asgi": {"spec_version": "2.4"}}
        if disconnect:
            with pytest.raises(ClientDisconnect):
                await response(scope, None, send)
            assert consumed == [0]
        else:
            await response(scope, None, send)
            assert sent == [0, 1, 2, 3]
        assert closed == [True]

    asyncio.run(run())
