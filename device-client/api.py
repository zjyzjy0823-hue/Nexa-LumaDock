import requests


class DeviceTokenRejected(Exception):
    pass


class HeartbeatValidationError(Exception):
    pass


def send_heartbeat(server_url: str, token: str, payload: dict) -> dict:
    response = requests.post(
        f"{server_url}/api/device/heartbeat",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
        timeout=10,
    )
    if response.status_code == 401:
        raise DeviceTokenRejected("Device token rejected. Generate a new token in Nexa-LumaDock.")
    if response.status_code == 422:
        raise HeartbeatValidationError(f"Heartbeat validation error: {response.text}")
    response.raise_for_status()
    return response.json()
