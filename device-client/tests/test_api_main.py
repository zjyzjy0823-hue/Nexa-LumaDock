from unittest.mock import Mock

import pytest
import requests

import api
import main


@pytest.mark.parametrize("status,error", [(200, None), (401, api.DeviceTokenRejected),
                                          (422, api.HeartbeatValidationError), (500, requests.HTTPError)])
def test_heartbeat_status(monkeypatch, status, error):
    response = Mock(status_code=status, text="invalid")
    response.json.return_value = {"deviceId": "device-1"}
    if status == 500:
        response.raise_for_status.side_effect = requests.HTTPError("server error")
    post = Mock(return_value=response)
    monkeypatch.setattr(api.requests, "post", post)
    if error:
        with pytest.raises(error):
            api.send_heartbeat("https://example.com", "token", {"cpu": 10})
    else:
        assert api.send_heartbeat("https://example.com", "token", {}) == {"deviceId": "device-1"}
    assert post.call_args.kwargs["headers"] == {"Authorization": "Bearer token"}


@pytest.mark.parametrize("error", [api.DeviceTokenRejected("rejected"), api.HeartbeatValidationError("bad payload")])
def test_auth_and_validation_stop_without_sleep(monkeypatch, capsys, error):
    monkeypatch.setattr(main.platform, "system", lambda: "Windows")
    monkeypatch.setattr(main, "load_config", lambda: {"serverUrl": "https://example.com", "deviceToken": "token", "intervalSeconds": 30})
    monkeypatch.setattr(main, "collect", lambda: {})
    monkeypatch.setattr(main, "send_heartbeat", Mock(side_effect=error))
    sleeper = Mock()
    monkeypatch.setattr(main.time, "sleep", sleeper)
    assert main.run() == 1
    sleeper.assert_not_called()
    if isinstance(error, api.HeartbeatValidationError):
        assert "Client/server versions may be incompatible" in capsys.readouterr().out


def test_network_error_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr(main.platform, "system", lambda: "Windows")
    monkeypatch.setattr(main, "load_config", lambda: {"serverUrl": "https://example.com", "deviceToken": "token", "intervalSeconds": 30})
    monkeypatch.setattr(main, "collect", lambda: {})
    monkeypatch.setattr(main, "send_heartbeat", Mock(side_effect=[requests.ConnectionError("offline"),
                                                              {"deviceId": "one", "lastSeenAt": "now"}]))
    sleeper = Mock()
    monkeypatch.setattr(main.time, "sleep", sleeper)
    assert main.run(once=True) == 1
    assert main.run(once=True) == 0
    sleeper.assert_not_called()


def test_network_error_backoff(monkeypatch):
    monkeypatch.setattr(main.platform, "system", lambda: "Windows")
    monkeypatch.setattr(main, "load_config", lambda: {"serverUrl": "https://example.com", "deviceToken": "token", "intervalSeconds": 30})
    monkeypatch.setattr(main, "collect", lambda: {})
    monkeypatch.setattr(main, "send_heartbeat", Mock(side_effect=[requests.ConnectionError("offline"),
                                                              api.DeviceTokenRejected("stop")]))
    sleeper = Mock()
    monkeypatch.setattr(main.time, "sleep", sleeper)
    assert main.run() == 1
    sleeper.assert_called_once_with(5)
