"""Local runtime reads/runs use the enrolled Client; runtime never enters sync."""
import httpx
from fastapi import HTTPException
from .. import core_connection


def request(user_id, workflow_id, suffix, method="GET", payload=None, *, expect_list=False):
    try:
        metadata = core_connection.load_connection(user_id)
        credential = core_connection.credential_store.load(user_id) if metadata else None
    except (OSError, HTTPException):
        raise HTTPException(503, "Core currently unavailable; Definition remains available locally") from None
    if metadata is None or not credential:
        raise HTTPException(503, "Core currently unavailable; Definition remains available locally")
    try:
        with core_connection._http_client() as client:
            response = client.request(method, metadata.coreUrl + f"/api/v1/client/automations/{workflow_id}/{suffix}",
                headers={"Authorization": "Bearer " + credential}, json=payload)
        if response.status_code == 404:
            raise HTTPException(409, "Definition has not reached Core; wait for sync")
        if response.status_code == 422:
            raise HTTPException(422, "Definition is not executable")
        if response.is_redirect or response.status_code >= 400:
            raise ValueError("Unavailable")
        body = response.json()
        if not isinstance(body, list if expect_list else dict):
            raise ValueError("Invalid response")
        return body
    except (httpx.RequestError, ValueError):
        raise HTTPException(503, "Core currently unavailable; Execution history cannot be refreshed; Definition remains available locally") from None
