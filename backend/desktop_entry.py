"""PyInstaller entry point for the local Nexa Desktop backend."""

import argparse
import logging
import os
import secrets
import sys
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy.engine import URL


DESKTOP_ORIGINS = "tauri://localhost,http://tauri.localhost,http://localhost:5173,http://127.0.0.1:5173"


def prepare_desktop(data_dir: Path) -> dict[str, str]:
    """Prepare persistent desktop settings before importing app.main/security."""
    data_dir = data_dir.expanduser().resolve()
    data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    (data_dir / "logs").mkdir(exist_ok=True, mode=0o700)
    (data_dir / "core-connections").mkdir(exist_ok=True, mode=0o700)
    if os.name != "nt":
        data_dir.chmod(0o700)
    secret_path = data_dir / "secret.key"
    if not secret_path.exists():
        try:
            with os.fdopen(os.open(secret_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="ascii") as output:
                output.write(secrets.token_hex(32))
        except FileExistsError:
            pass
    if os.name != "nt":
        secret_path.chmod(0o600)
    secret = secret_path.read_text(encoding="ascii").strip()
    if len(secret) < 64:
        raise RuntimeError("Desktop secret.key is invalid")
    installation_path = data_dir / "installation.id"
    if not installation_path.exists():
        try:
            with installation_path.open("x", encoding="ascii") as output:
                output.write(str(uuid4()))
        except FileExistsError:
            pass
    try:
        installation_id = str(UUID(installation_path.read_text(encoding="ascii").strip()))
    except (OSError, ValueError, UnicodeError):
        raise RuntimeError("Desktop installation.id is invalid") from None
    # SQLAlchemy's URL renderer handles drive letters, spaces, and backslashes.
    database_url = URL.create("sqlite", database=str(data_dir / "nexa.db")).render_as_string()
    config = {
        "NEXA_MODE": "local",
        "DATABASE_URL": database_url,
        "JWT_SECRET": secret,
        "CORS_ORIGINS": DESKTOP_ORIGINS,
        "NEXA_INSTALLATION_ID": installation_id,
        "NEXA_DATA_DIR": str(data_dir),
    }
    os.environ.update(config)
    return config


def configure_logging(data_dir: Path) -> None:
    handler = RotatingFileHandler(data_dir / "logs" / "backend.log", maxBytes=5_000_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.addHandler(handler)
        logger.propagate = False


def desktop_parent_alive(parent_pid: int | None) -> bool:
    if parent_pid is None or os.name == "nt":
        return True
    try:
        os.kill(parent_pid, 0)  # Unix existence probe; no signal is delivered.
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--port", type=int, default=17800, help="Loopback port (default 17800; use an isolated port for smoke tests)")
    parser.add_argument("--parent-pid", type=int, help="Desktop process owner on Unix")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    if args.parent_pid is not None and args.parent_pid <= 0:
        parser.error("parent-pid must be positive")
    data_dir = args.data_dir.expanduser().resolve()
    try:
        prepare_desktop(data_dir)
        configure_logging(data_dir)
        logging.info("Nexa Desktop backend starting")
        from app.main import app  # Import only after desktop environment is ready.
        import uvicorn
        shutdown_file = data_dir / "backend.shutdown"
        shutdown_file.unlink(missing_ok=True)
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=args.port, log_config=None, access_log=False))

        def watch_shutdown() -> None:
            while not server.should_exit:
                if shutdown_file.exists() or not desktop_parent_alive(args.parent_pid):
                    logging.info("Desktop shutdown requested")
                    server.should_exit = True
                    return
                time.sleep(0.2)

        threading.Thread(target=watch_shutdown, daemon=True).start()
        server.run()
        shutdown_file.unlink(missing_ok=True)
        logging.info("Nexa Desktop backend stopped")
    except Exception:
        logging.exception("Nexa Desktop backend failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
