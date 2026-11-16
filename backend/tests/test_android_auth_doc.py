"""Pin the Android decision to existing API routes, without adding a new protocol."""
from pathlib import Path
from app.main import app


def test_android_auth_document_records_credentials_and_existing_routes():
    content = (Path(__file__).parents[2] / "docs/android-auth.md").read_text()
    for decision in ("nc_live_", "nd_live_", "Android Keystore", "POST /api/v1/core/connect",
                     "POST /api/v1/clients/{id}/revoke", "401", "409", "工作区", "不接受扫码",
                     "POST /api/v1/devices/{id}/token", "DELETE /api/v1/devices/{id}/token"):
        assert decision in content
    paths = app.openapi()["paths"]
    for method, path in (("post", "/api/v1/core/connect"), ("post", "/api/v1/clients/{id}/revoke"),
                         ("post", "/api/v1/devices/{id}/token"), ("delete", "/api/v1/devices/{id}/token"),
                         ("post", "/api/v1/clients/{id}/credential"), ("get", "/api/v1/workspace")):
        assert method in paths[path]
