"""Shared target resolution for native PyInstaller builds and packaged smoke tests."""

import os
import platform
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def resolve_target(explicit: str | None = None) -> str:
    target = explicit or os.environ.get("TAURI_ENV_TARGET_TRIPLE")
    if not target:
        target = subprocess.check_output(["rustc", "--print", "host-tuple"], text=True).strip()
    if target not in {"x86_64-pc-windows-msvc", "x86_64-apple-darwin", "aarch64-apple-darwin"}:
        raise ValueError(f"Unsupported desktop target: {target}")
    return target


def require_native(target: str) -> None:
    system = "windows" if os.name == "nt" else "darwin" if platform.system() == "Darwin" else "unsupported"
    machine = {"amd64": "x86_64", "arm64": "aarch64"}.get(platform.machine().lower(), platform.machine().lower())
    if not target.startswith(machine + "-") or system not in target.split("-"):
        raise ValueError(f"PyInstaller requires native Python: {system}/{machine} cannot build or run {target}")


def sidecar_path(target: str) -> Path:
    suffix = ".exe" if "windows" in target.split("-") else ""
    return ROOT / "src-tauri" / "binaries" / f"nexa-backend-{target}{suffix}"
