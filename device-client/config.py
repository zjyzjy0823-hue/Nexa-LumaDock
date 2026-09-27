import json
from pathlib import Path
from urllib.parse import urlparse

CONFIG_PATH = Path(__file__).with_name("config.json")


def load_config(path: Path = CONFIG_PATH) -> dict:
    with path.open(encoding="utf-8") as stream:
        config = json.load(stream)
    if not isinstance(config, dict):
        raise ValueError("config.json must contain a JSON object")
    url = config.get("serverUrl")
    token = config.get("deviceToken")
    interval = config.get("intervalSeconds", 30)
    parsed = urlparse(url) if isinstance(url, str) else None
    if not parsed or parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or any(char.isspace() for char in url):
        raise ValueError("serverUrl must be a valid http(s) URL")
    try:
        parsed.port
    except ValueError as error:
        raise ValueError("serverUrl must be a valid http(s) URL") from error
    insecure = config.get("allowInsecureHttp", False)
    if not isinstance(insecure, bool):
        raise ValueError("allowInsecureHttp must be a boolean")
    if parsed.scheme == "http" and parsed.hostname.lower() not in ("localhost", "127.0.0.1") and not insecure:
        raise ValueError("Insecure HTTP is only allowed for localhost. Use HTTPS or explicitly enable allowInsecureHttp.")
    if not isinstance(token, str) or not token.startswith("nd_live_") or len(token) < 30:
        raise ValueError("deviceToken must be a generated nd_live_ token")
    if isinstance(interval, bool) or not isinstance(interval, int) or not 5 <= interval <= 3600:
        raise ValueError("intervalSeconds must be an integer from 5 to 3600")
    return {"serverUrl": url.rstrip("/"), "deviceToken": token, "intervalSeconds": interval,
            "allowInsecureHttp": insecure}
