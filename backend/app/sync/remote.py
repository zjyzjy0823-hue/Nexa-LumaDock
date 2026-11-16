"""Protocol v3 HTTP transport. Only a Client credential crosses this boundary."""

import httpx
from .protocol import SYNC_PROTOCOL_VERSION


class SyncRemoteError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _failure(response) -> SyncRemoteError:
    """Map a failed Core response to a safe code, keeping the recovery signals.

    Two bodies are machine-readable by contract (§4.3, §11.4) and must not collapse
    into `invalid_response`, which would leave the Local replica unable to tell a
    dead cursor from a broken payload:

    * `{"resyncRequired": true, ...}` on a `400` — the cursor is beyond the Core
      revision, so replaying can never catch up (both `/changes` and `/snapshot`);
    * `{"detail": "snapshot_expired"}` on a `409` — the paging state must be
      dropped and a fresh first request issued.
    """
    body = None
    try:
        body = response.json()
    except (ValueError, UnicodeError):
        body = None
    detail = body.get("detail") if isinstance(body, dict) else None
    if isinstance(body, dict) and body.get("resyncRequired") is True:
        return SyncRemoteError("resync_required")
    if response.status_code == 409:
        return SyncRemoteError("snapshot_expired" if detail == "snapshot_expired"
                               else "protocol_mismatch")
    if response.status_code == 401:
        return SyncRemoteError("unauthorized")
    if response.status_code in (502, 503, 504):
        return SyncRemoteError("unreachable")
    return SyncRemoteError("invalid_response")


def _valid_entity(row) -> bool:
    if not isinstance(row, dict):
        return False
    entity_type, entity_id = row.get("entityType"), row.get("entityId")
    revision, deleted = row.get("syncRevision"), row.get("deleted")
    if not isinstance(entity_type, str) or not isinstance(entity_id, str):
        return False
    if type(revision) is not int or not 0 <= revision <= 2**63 - 1:
        return False
    if type(deleted) is not bool:
        return False
    return (row.get("data") is None) if deleted else isinstance(row.get("data"), dict)


class SyncRemoteClient:
    def __init__(self, core_url: str, credential: str):
        if not credential.startswith("nc_live_"):
            raise SyncRemoteError("unauthorized")
        self.core_url = core_url
        self.credential = credential
        self.client = httpx.Client(timeout=httpx.Timeout(15.0, connect=5.0),
                                   follow_redirects=False, trust_env=False, verify=True)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.client.close()

    def _request(self, method: str, endpoint: str, *, protocol: bool = True, **kwargs) -> dict:
        try:
            response = self.client.request(method, self.core_url + endpoint,
                                           headers={"Authorization": "Bearer " + self.credential}, **kwargs)
        except httpx.RequestError as error:
            raise SyncRemoteError("timeout" if isinstance(error, httpx.TimeoutException)
                                  else "unreachable") from None
        if response.is_redirect or response.status_code >= 400:
            raise _failure(response)
        try:
            body = response.json()
        except (ValueError, UnicodeError):
            raise SyncRemoteError("invalid_response") from None
        if not isinstance(body, dict):
            raise SyncRemoteError("invalid_response")
        if protocol and body.get("protocolVersion") != SYNC_PROTOCOL_VERSION:
            raise SyncRemoteError("protocol_mismatch")
        return body

    def report_event(self, event: dict) -> dict:
        response = self._request("POST", "/api/v1/automation/events", protocol=False, json=event)
        if response.get("ok") is not True or type(response.get("duplicated")) is not bool:
            raise SyncRemoteError("invalid_response")
        return response

    def push_mutation(self, mutation: dict) -> dict:
        response = self._request("POST", "/api/v1/sync/mutations",
                                 json={"protocolVersion": SYNC_PROTOCOL_VERSION, "mutations": [mutation]})
        results = response.get("results")
        if (not isinstance(results, list) or len(results) != 1 or
                not isinstance(results[0], dict) or results[0].get("mutationId") != mutation["mutationId"]):
            raise SyncRemoteError("invalid_response")
        return results[0]

    def get_changes(self, cursor: int, limit: int = 100) -> dict:
        response = self._request("GET", "/api/v1/sync/changes",
                                 params={"cursor": cursor, "limit": limit, "protocolVersion": SYNC_PROTOCOL_VERSION})
        if (not isinstance(response.get("changes"), list) or
                not isinstance(response.get("cursor"), int) or
                not isinstance(response.get("workspaceRevision"), int) or
                type(response.get("hasMore")) is not bool):
            raise SyncRemoteError("invalid_response")
        return response

    def get_snapshot(self, snapshot_id: str | None = None, cursor: str | None = None,
                     limit: int = 200) -> dict:
        """One page of the recovery snapshot (§11); a pure read on Core's side.

        The first request omits both ``snapshot_id`` and ``cursor``. Later pages echo
        the returned ``snapshotId`` (it pins the workspace revision) plus the opaque
        ``cursor``. `resync_required` and `snapshot_expired` arrive as distinct codes
        so the caller can restart the recovery instead of treating it as corruption.
        """
        params: dict[str, object] = {"protocolVersion": SYNC_PROTOCOL_VERSION, "limit": limit}
        if snapshot_id is not None:
            params["snapshotId"] = snapshot_id
        if cursor is not None:
            params["cursor"] = cursor
        response = self._request("GET", "/api/v1/sync/snapshot", params=params)
        entities = response.get("entities")
        revision = response.get("workspaceRevision")
        snapshot = response.get("snapshotId")
        if (not isinstance(entities, list) or len(entities) > limit or
                not isinstance(snapshot, str) or not snapshot or
                type(revision) is not int or not 0 <= revision <= 2**63 - 1 or
                type(response.get("hasMore")) is not bool or
                not all(_valid_entity(row) for row in entities)):
            raise SyncRemoteError("invalid_response")
        if response["hasMore"]:
            # `cursor is null` iff `hasMore` is false: a page that claims more work
            # without a continuation point cannot be followed.
            if not isinstance(response.get("cursor"), str) or not response["cursor"]:
                raise SyncRemoteError("invalid_response")
        elif response.get("cursor") is not None:
            raise SyncRemoteError("invalid_response")
        return response
