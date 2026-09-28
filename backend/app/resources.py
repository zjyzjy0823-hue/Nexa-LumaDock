import sys
from pathlib import Path


def resource_path(name: str, source_path: Path) -> Path:
    """Resolve an installed PyInstaller resource or its source-tree original."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / name
    return source_path
