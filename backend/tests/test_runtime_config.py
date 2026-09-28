import pytest

from app.config import load_runtime_config
from core_entry import core_bind


SECRET = "test-secret-for-nexa-core"
POSTGRES_URL = "postgresql+psycopg://nexa:password@postgres:5432/nexa"


def test_local_defaults_to_sqlite():
    config = load_runtime_config({"JWT_SECRET": SECRET})
    assert config.mode == "local"
    assert config.database_url == "sqlite:///./nexa.db"
    assert config.allow_registration
    assert config.cors_origins == ("http://localhost:5173", "http://127.0.0.1:5173")


def test_core_uses_postgres_and_explicit_origins():
    config = load_runtime_config({"NEXA_MODE": "core", "DATABASE_URL": POSTGRES_URL,
                                  "JWT_SECRET": SECRET, "CORS_ORIGINS": "https://nexa.example"})
    assert config.mode == "core"
    assert config.database_url == POSTGRES_URL
    assert config.cors_origins == ("https://nexa.example",)


@pytest.mark.parametrize("database_url", [None, "sqlite:///./nexa.db", "postgresql://nexa@postgres/nexa",
                                           "postgresql+psycopg://nexa:private@postgres:not-a-port/nexa"])
def test_core_requires_psycopg_postgres(database_url):
    values = {"NEXA_MODE": "core", "JWT_SECRET": SECRET}
    if database_url is not None:
        values["DATABASE_URL"] = database_url
    with pytest.raises(RuntimeError, match="Core mode requires PostgreSQL DATABASE_URL"):
        load_runtime_config(values)


def test_invalid_mode_fails():
    with pytest.raises(RuntimeError, match="Unsupported NEXA_MODE: abc"):
        load_runtime_config({"NEXA_MODE": "abc", "JWT_SECRET": SECRET})


def test_core_requires_secret_and_disallows_wildcard_cors():
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        load_runtime_config({"NEXA_MODE": "core", "DATABASE_URL": POSTGRES_URL})
    with pytest.raises(RuntimeError, match="wildcard CORS_ORIGINS"):
        load_runtime_config({"NEXA_MODE": "core", "DATABASE_URL": POSTGRES_URL,
                             "JWT_SECRET": SECRET, "CORS_ORIGINS": "*"})


def test_core_bind_defaults_and_overrides():
    values = {"NEXA_MODE": "core", "DATABASE_URL": POSTGRES_URL, "JWT_SECRET": SECRET}
    assert core_bind(values) == ("0.0.0.0", 8000)
    assert core_bind({**values, "NEXA_HOST": "127.0.0.1", "NEXA_PORT": "9000"}) == ("127.0.0.1", 9000)
    with pytest.raises(RuntimeError, match="NEXA_PORT"):
        core_bind({**values, "NEXA_PORT": "70000"})
