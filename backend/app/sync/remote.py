"""Protocol v1 HTTP transport. Only a Client credential crosses this boundary."""

import httpx


class SyncRemoteError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


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

    def _request(self, method: str, endpoint: str, **kwargs) -> dict:
        try:
            response = self.client.request(method, self.core_url + endpoint,
                                           headers={"Authorization": "Bearer " + self.credential}, **kwargs)
        except httpx.RequestError as error:
            raise SyncRemoteError("timeout" if isinstance(error, httpx.TimeoutException)
                                  else "unreachable") from None
        if response.status_code == 401:
            raise SyncRemoteError("unauthorized")
        if response.status_code in (502, 503, 504):
            raise SyncRemoteError("unreachable")
        if response.is_redirect or response.status_code >= 400:
            raise SyncRemoteError("invalid_response")
        try:
            body = response.json()
        except (ValueError, UnicodeError):
            raise SyncRemoteError("invalid_response") from None
        if not isinstance(body, dict) or body.get("protocolVersion") != 1:
            raise SyncRemoteError("invalid_response")
        return body

    def push_mutation(self, mutation: dict) -> dict:
        response = self._request("POST", "/api/v1/sync/mutations",
                                 json={"protocolVersion": 1, "mutations": [mutation]})
        results = response.get("results")
        if (not isinstance(results, list) or len(results) != 1 or
                not isinstance(results[0], dict) or results[0].get("mutationId") != mutation["mutationId"]):
            raise SyncRemoteError("invalid_response")
        return results[0]

    def get_changes(self, cursor: int, limit: int = 100) -> dict:
        response = self._request("GET", "/api/v1/sync/changes",
                                 params={"cursor": cursor, "limit": limit})
        if (not isinstance(response.get("changes"), list) or
                not isinstance(response.get("cursor"), int) or
                not isinstance(response.get("workspaceRevision"), int) or
                type(response.get("hasMore")) is not bool):
            raise SyncRemoteError("invalid_response")
        return response
