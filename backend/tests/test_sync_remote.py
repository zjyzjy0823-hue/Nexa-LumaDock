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
            assert set(body["mutations"][0]) == {"mutationId", "entityType", "entityId",
                                                  "operation", "baseRevision", "data"}
            return httpx.Response(200, json={"protocolVersion": 1, "results": [
                {"mutationId": "test-id", "status": "applied", "revision": 1}]})
        return httpx.Response(200, json={"protocolVersion": 1, "changes": [],
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


@pytest.mark.parametrize("status,code", [(401, "unauthorized"), (503, "unreachable"),
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
