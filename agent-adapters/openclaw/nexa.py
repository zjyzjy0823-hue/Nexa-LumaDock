import logging
import time

import httpx

log = logging.getLogger(__name__)


class FatalApiError(RuntimeError):
    pass


class NexaClient:
    def __init__(self, config: dict, transport=None):
        self.client = httpx.Client(base_url=config["serverUrl"],
                                   headers={"Authorization": f"Bearer {config['agentToken']}"},
                                   timeout=10, transport=transport)

    def close(self):
        self.client.close()

    def request(self, method: str, path: str, payload=None, conflict_ok=False):
        for attempt in range(3):
            try:
                response = self.client.request(method, path, json=payload)
            except (httpx.NetworkError, httpx.TimeoutException) as error:
                if attempt == 2:
                    raise ConnectionError("Nexa API unavailable") from error
                time.sleep(0.2 * 2**attempt)
                continue
            if response.status_code in (401, 422):
                raise FatalApiError(f"Nexa API rejected request ({response.status_code})")
            if response.status_code >= 500 and attempt < 2:
                time.sleep(0.2 * 2**attempt)
                continue
            if response.status_code == 409 and conflict_ok:
                return None
            if 400 <= response.status_code < 500:
                raise FatalApiError(f"Nexa API rejected request ({response.status_code})")
            response.raise_for_status()
            return response.json()
        raise ConnectionError("Nexa API unavailable")

    def heartbeat(self, status: str, instance: str, task_id=None):
        return self.request("POST", "/api/agent/heartbeat", {
            "status": status, "runtimeType": "openclaw", "runtimeVersion": "0.1.0",
            "runtimeInstance": instance, "currentTaskId": task_id})

    def tasks(self):
        return self.request("GET", "/api/agent/tasks")

    def claim(self, task_id: str):
        return self.request("POST", f"/api/agent/tasks/{task_id}/claim", conflict_ok=True)

    def event(self, task_id: str, event_type: str, message: str, level="info"):
        return self.request("POST", f"/api/agent/tasks/{task_id}/events", {
            "type": event_type, "level": level, "message": message[:500], "data": {}})

    def complete(self, task_id: str, text: str):
        return self.request("POST", f"/api/agent/tasks/{task_id}/complete", {
            "result": {"text": text}, "summary": text[:500]})

    def fail(self, task_id: str, error: str):
        return self.request("POST", f"/api/agent/tasks/{task_id}/fail", {
            "error": error[:500], "details": {}})
