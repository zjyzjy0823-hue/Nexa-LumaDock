import json

import pytest

from config import load_config


TOKEN = "nd_live_" + "x" * 32


def config_file(tmp_path, **changes):
    data = {"serverUrl": "http://localhost:8000", "deviceToken": TOKEN, "intervalSeconds": 30}
    data.update(changes)
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


@pytest.mark.parametrize("url", ["http://localhost:8000", "http://127.0.0.1:8000", "https://example.com"])
def test_allowed_urls(tmp_path, url):
    assert load_config(config_file(tmp_path, serverUrl=url))["serverUrl"] == url


@pytest.mark.parametrize("url", ["http://192.168.1.10:8000", "http://example.com", "http://8.8.8.8"])
def test_remote_http_rejected(tmp_path, url):
    with pytest.raises(ValueError, match="Insecure HTTP is only allowed for localhost"):
        load_config(config_file(tmp_path, serverUrl=url))


def test_remote_http_explicit_override(tmp_path):
    assert load_config(config_file(tmp_path, serverUrl="http://192.168.1.10:8000", allowInsecureHttp=True))["allowInsecureHttp"] is True


@pytest.mark.parametrize("changes", [{"deviceToken": "bad"}, {"intervalSeconds": 4}, {"intervalSeconds": 3601},
                                     {"allowInsecureHttp": "true"}])
def test_invalid_configuration(tmp_path, changes):
    with pytest.raises(ValueError):
        load_config(config_file(tmp_path, **changes))
