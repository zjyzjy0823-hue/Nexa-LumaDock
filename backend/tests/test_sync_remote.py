import json
import httpx
import pytest

from app.sync.remote import SyncRemoteClient, SyncRemoteError


def test_client_credential_and_http_safety(monkeypatch):
    original_client = httpx.Client
    settings = {}
    seen = []

    def response(request):
        seen.append(request)
        assert request.headers["Authorization"] == "Bearer nc_live_test"
        if request.method == "POST":
            body = json.loads(request.read())
            assert body["protocolVersion"] == 3
            assert set(body["mutations"][0]) == {"mutationId", "entityType", "entityId",
                                                  "operation", "baseRevision", "data"}
            return httpx.Response(200, json={"protocolVersion": 3, "results": [
                {"mutationId": "test-id", "status": "applied", "revision": 1}]})
        assert request.url.params["protocolVersion"] == "3"
        return httpx.Response(200, json={"protocolVersion": 3, "changes": [],
                                         "cursor": 0, "hasMore": False, "workspaceRevision": 1})

    def client_factory(**kwargs):
        settings.update(kwargs)
        return original_client(transport=httpx.MockTransport(response), **kwargs)

    monkeypatch.setattr(httpx, "Client", client_factory)
    with SyncRemoteClient("https://core.example", "nc_live_test") as remote:
        assert remote.push_mutation({"mutationId": "test-id", "entityType": "ledger.category",
                                     "entityId": "entity-id", "operation": "upsert",
                                     "baseRevision": 0, "data": {"name": "Food"}})["revision"] == 1
        assert remote.get_changes(0)["workspaceRevision"] == 1
    assert settings["follow_redirects"] is False
    assert settings["trust_env"] is False and settings["verify"] is True
    assert settings["timeout"].connect == 5.0
    assert all(request.url.host == "core.example" for request in seen)


@pytest.mark.parametrize("status,code", [(401, "unauthorized"), (502, "unreachable"),
                                           (503, "unreachable"), (504, "unreachable"),
                                           (302, "invalid_response")])
def test_safe_remote_error_codes(monkeypatch, status, code):
    original_client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original_client(
        transport=httpx.MockTransport(lambda _request: httpx.Response(status)), **kwargs))
    with SyncRemoteClient("https://core.example", "nc_live_test") as remote:
        with pytest.raises(SyncRemoteError) as error:
            remote.get_changes(0)
    assert error.value.code == code
    assert "nc_live_" not in str(error.value)


@pytest.mark.parametrize("failure,code", [(httpx.ConnectError, "unreachable"),
                                         (httpx.ReadTimeout, "timeout"),
                                         (httpx.ConnectTimeout, "timeout")])
def test_network_failures_are_safe_retryable_codes(monkeypatch, failure, code):
    original_client = httpx.Client

    def fail(request):
        raise failure("private nc_live_secret Authorization traceback", request=request)

    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original_client(
        transport=httpx.MockTransport(fail), **kwargs))
    with SyncRemoteClient("https://core.example", "nc_live_test") as remote:
        with pytest.raises(SyncRemoteError) as error:
            remote.get_changes(0)
    assert error.value.code == code
    assert str(error.value) == code


@pytest.mark.parametrize("status,body", [(200, {"protocolVersion": 1}),
                                        (409, {"detail": "sync_protocol_mismatch"})])
def test_protocol_mismatch_is_safe(monkeypatch, status, body):
    original_client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original_client(
        transport=httpx.MockTransport(lambda request: httpx.Response(status, json=body)), **kwargs))
    with SyncRemoteClient("https://core.example", "nc_live_test") as remote:
        with pytest.raises(SyncRemoteError, match="protocol_mismatch"):
            remote.get_changes(0)
