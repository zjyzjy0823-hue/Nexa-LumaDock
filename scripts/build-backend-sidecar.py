"""Build the shared backend with the active Python environment; no cross compilation."""

import argparse
import importlib.util
import os
import shutil
import subprocess
import sys

from desktop_target import ROOT, require_native, resolve_target, sidecar_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", help="Defaults to TAURI_ENV_TARGET_TRIPLE, then the Rust host")
    parser.add_argument("--clean", action="store_true", help="Clear PyInstaller caches before building")
    args = parser.parse_args()
    target = resolve_target(args.target)
    require_native(target)
    if importlib.util.find_spec("PyInstaller") is None:
        parser.error("Install PyInstaller in this Python environment: python -m pip install 'pyinstaller>=6,<7'")
    backend = ROOT / "backend"
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", *(["--clean"] if args.clean else []),
                    "--distpath", str(backend / "dist"), "--workpath", str(backend / "build"),
                    str(backend / "nexa-backend.spec")], cwd=backend, check=True)
    source = backend / "dist" / ("nexa-backend.exe" if os.name == "nt" else "nexa-backend")
    if not source.is_file():
        raise FileNotFoundError(f"Missing PyInstaller executable: {source}")
    destination = sidecar_path(target)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    if os.name != "nt":
        destination.chmod(destination.stat().st_mode | 0o111)
        if not os.access(destination, os.X_OK):
            raise PermissionError(f"Sidecar is not executable: {destination}")
    print(f"Sidecar ready: {destination}")


if __name__ == "__main__":
    main()
