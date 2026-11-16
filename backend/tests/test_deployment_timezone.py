from dataclasses import replace

from app.api import settings
from app.database import runtime_config


def test_settings_exposes_deployment_timezone_without_changing_preferences(client, users, monkeypatch):
    monkeypatch.setattr(settings, "runtime_config", replace(runtime_config, app_timezone="Pacific/Auckland"), raising=False)
    response = client.patch("/api/v1/settings", headers=users[0], json={"timezone": "UTC"})
    assert response.status_code == 200
    assert response.json()["timezone"] == "UTC"
    assert response.json()["deploymentTimezone"] == "Pacific/Auckland"
    assert client.get("/api/v1/settings", headers=users[0]).json()["deploymentTimezone"] == "Pacific/Auckland"
    assert client.patch("/api/v1/settings", headers=users[0], json={"deploymentTimezone": "UTC"}).status_code == 422
