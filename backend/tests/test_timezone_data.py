"""Settings must work on hosts without a system IANA timezone database."""
import zoneinfo
from contextlib import closing

import pytest
from sqlalchemy import select

from app.database import get_db
from app.main import app
from app.models import LocalMutation
from app.sync.adapters.personal_state import PreferencesData


@pytest.fixture
def package_timezones_only():
    previous_path = zoneinfo.TZPATH
    zoneinfo.reset_tzpath(())
    zoneinfo.ZoneInfo.clear_cache()
    try:
        yield
    finally:
        zoneinfo.reset_tzpath(previous_path)
        zoneinfo.ZoneInfo.clear_cache()


def test_settings_outbox_without_system_timezone_database(client, users, package_timezones_only):
    assert zoneinfo.ZoneInfo("Asia/Shanghai").key == "Asia/Shanghai"
    PreferencesData.model_validate({"timezone": "Asia/Shanghai"})
    headers, _ = users
    saved = client.patch("/api/v1/settings", headers=headers,
                         json={"theme": "dark", "appearance": {"accent": "mint"}})
    assert saved.status_code == 200
    assert saved.json()["timezone"] == "Asia/Shanghai"
    assert saved.json()["theme"] == "dark"
    assert saved.json()["appearance"]["accent"] == "mint"

    with closing(app.dependency_overrides[get_db]()) as sessions:
        db = next(sessions)
        entries = db.scalars(select(LocalMutation).where(
            LocalMutation.entity_type == "user.preferences")).all()
        assert len(entries) == 1
        assert entries[0].status == "pending"
        expected = entries[0].payload_json.copy()
        assert expected["timezone"] == "Asia/Shanghai"
        assert expected["theme"] == "dark"
        assert expected["appearance"]["accent"] == "mint"

    invalid = client.patch("/api/v1/settings", headers=headers,
                           json={"timezone": "Invalid/Nexa-Timezone"})
    assert invalid.status_code == 422
    with closing(app.dependency_overrides[get_db]()) as sessions:
        db = next(sessions)
        entries = db.scalars(select(LocalMutation).where(
            LocalMutation.entity_type == "user.preferences")).all()
        assert len(entries) == 1
        assert entries[0].payload_json == expected
