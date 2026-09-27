import argparse
import platform
import time

import requests

from api import DeviceTokenRejected, HeartbeatValidationError, send_heartbeat
from collector import collect
from config import load_config


def run(once: bool = False) -> int:
    if platform.system() != "Windows":
        print("The Device Client supports Windows only.")
        return 1
    try:
        config = load_config()
    except (OSError, ValueError) as error:
        print(f"Configuration error: {error}")
        return 1
    failures = 0
    while True:
        try:
            payload = collect()
            result = send_heartbeat(config["serverUrl"], config["deviceToken"], payload)
            print(f"Heartbeat accepted: {result['deviceId']} at {result['lastSeenAt']}")
            failures = 0
            if once:
                return 0
            delay = config["intervalSeconds"]
        except DeviceTokenRejected as error:
            print(error)
            return 1
        except HeartbeatValidationError:
            print("Heartbeat payload rejected by server. Client/server versions may be incompatible.")
            return 1
        except (requests.RequestException, OSError) as error:
            failures += 1
            delay = min(60, 5 * 2 ** min(failures - 1, 4))
            print(f"Connection failed: {error}. Retry in {delay} seconds.")
            if once:
                return 1
        time.sleep(delay)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Nexa Windows Device Client")
    parser.add_argument("--once", action="store_true", help="Send one heartbeat and exit")
    try:
        raise SystemExit(run(parser.parse_args().once))
    except KeyboardInterrupt:
        print("Device Client stopped.")
