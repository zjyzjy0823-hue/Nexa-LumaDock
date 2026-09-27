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
    if not isinstance(url, str) or not url or urlparse(url).scheme not in ("http", "https") or not urlparse(url).netloc:
        raise ValueError("serverUrl must be a valid http(s) URL")
    if not isinstance(token, str) or not token.startswith("nd_live_") or len(token) < 30:
        raise ValueError("deviceToken must be a generated nd_live_ token")
    if isinstance(interval, bool) or not isinstance(interval, int) or not 5 <= interval <= 3600:
        raise ValueError("intervalSeconds must be an integer from 5 to 3600")
    return {"serverUrl": url.rstrip("/"), "deviceToken": token, "intervalSeconds": interval}
