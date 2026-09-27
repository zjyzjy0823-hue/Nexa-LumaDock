import json
from pathlib import Path
from urllib.parse import urlparse

CONFIG_PATH = Path(__file__).with_name("config.json")


def load_config(path: Path = CONFIG_PATH) -> dict:
    with path.open(encoding="utf-8") as stream:
        config = json.load(stream)
    if not isinstance(config, dict):
        raise ValueError("config.json must contain an object")
    url = config.get("serverUrl")
    parsed = urlparse(url) if isinstance(url, str) else None
    if not parsed or parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or any(c.isspace() for c in url):
        raise ValueError("serverUrl must be a valid http(s) URL")
    try:
        parsed.port
    except ValueError as error:
        raise ValueError("serverUrl must be a valid http(s) URL") from error
    insecure = config.get("allowInsecureHttp", False)
    if not isinstance(insecure, bool):
        raise ValueError("allowInsecureHttp must be a boolean")
    if parsed.scheme == "http" and parsed.hostname.lower() not in ("localhost", "127.0.0.1") and not insecure:
        raise ValueError("Remote HTTP requires allowInsecureHttp or HTTPS")
    token = config.get("agentToken")
    if not isinstance(token, str) or not token.startswith("na_live_") or len(token) < 30:
        raise ValueError("agentToken must be a generated na_live_ token")
    interval = config.get("pollIntervalSeconds", 10)
    if isinstance(interval, bool) or not isinstance(interval, int) or not 5 <= interval <= 3600:
        raise ValueError("pollIntervalSeconds must be 5–3600")
    instance = config.get("runtimeInstance")
    if not isinstance(instance, str) or not 1 <= len(instance) <= 120:
        raise ValueError("runtimeInstance must be 1–120 characters")
    timeout = config.get("executionTimeoutSeconds", 600)
    if isinstance(timeout, bool) or not isinstance(timeout, int) or not 10 <= timeout <= 3600:
        raise ValueError("executionTimeoutSeconds must be 10–3600")
    return {"serverUrl": url.rstrip("/"), "agentToken": token, "pollIntervalSeconds": interval,
            "runtimeInstance": instance, "executionTimeoutSeconds": timeout,
            "allowInsecureHttp": insecure}
