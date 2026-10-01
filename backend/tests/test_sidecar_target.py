"""Guard native target selection, especially Windows compatibility from a Mac."""

import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("desktop_target", Path(__file__).resolve().parents[2] / "scripts/desktop_target.py")
target = importlib.util.module_from_spec(spec)
spec.loader.exec_module(target)


def test_target_precedence(monkeypatch):
    monkeypatch.setenv("TAURI_ENV_TARGET_TRIPLE", "x86_64-pc-windows-msvc")
    assert target.resolve_target("x86_64-apple-darwin") == "x86_64-apple-darwin"
    assert target.resolve_target() == "x86_64-pc-windows-msvc"
    monkeypatch.delenv("TAURI_ENV_TARGET_TRIPLE")
    monkeypatch.setattr(target.subprocess, "check_output", lambda *args, **kwargs: "aarch64-apple-darwin\n")
    assert target.resolve_target() == "aarch64-apple-darwin"


@pytest.mark.parametrize("triple,name", [
    ("x86_64-pc-windows-msvc", "nexa-backend-x86_64-pc-windows-msvc.exe"),
    ("x86_64-apple-darwin", "nexa-backend-x86_64-apple-darwin"),
    ("aarch64-apple-darwin", "nexa-backend-aarch64-apple-darwin"),
])
def test_platform_filename(triple, name):
    assert target.sidecar_path(triple).name == name


def test_rejects_unsupported_target():
    with pytest.raises(ValueError, match="Unsupported"):
        target.resolve_target("x86_64-unknown-linux-gnu")


def test_rejects_cross_architecture_python(monkeypatch):
    monkeypatch.setattr(target.platform, "machine", lambda: "arm64")
    with pytest.raises(ValueError, match="native Python"):
        target.require_native("x86_64-apple-darwin")
