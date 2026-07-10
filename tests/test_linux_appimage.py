"""Tests for Linux AppImage staging helpers."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# scripts/ is not a package; import by path like build_release does
_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import linux_appimage as la  # noqa: E402


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_desktop_file_has_required_keys(repo_root: Path) -> None:
    desktop = la.desktop_file_path(repo_root)
    assert desktop.is_file()
    keys = la.parse_desktop_keys(desktop.read_text(encoding="utf-8"))
    for req in la.required_desktop_keys():
        assert req in keys, f"missing {req}"
    assert keys["Type"] == "Application"
    assert keys["Exec"] == "ScannerManager"
    assert keys["Icon"] == "scanner-manager"
    assert "HamRadio" in keys["Categories"]


def test_icon_and_udev_assets_exist(repo_root: Path) -> None:
    assert la.icon_file_path(repo_root).is_file()
    assert la.udev_file_path(repo_root).is_file()


def test_stage_appdir_layout(repo_root: Path, tmp_path: Path) -> None:
    binary = tmp_path / "ScannerManager"
    binary.write_bytes(b"#!/bin/sh\necho smoke\n")
    binary.chmod(0o755)
    appdir = tmp_path / "AppDir"
    la.stage_appdir(repo_root=repo_root, binary=binary, appdir=appdir)

    assert (appdir / "usr" / "bin" / "ScannerManager").is_file()
    assert (appdir / "usr" / "share" / "applications" / "scanner-manager.desktop").is_file()
    assert (
        appdir / "usr" / "share" / "icons" / "hicolor" / "256x256" / "apps" / "scanner-manager.png"
    ).is_file()
    assert (appdir / "scanner-manager.desktop").is_file()
    assert (appdir / "scanner-manager.png").is_file()
    assert (appdir / "AppRun").exists()
    assert (
        appdir / "usr" / "share" / "doc" / "scanner-manager" / "99-uniden-scanner.rules"
    ).is_file()
    assert (
        appdir / "usr" / "share" / "doc" / "scanner-manager" / "README-udev.txt"
    ).is_file()


def test_build_appimage_skips_without_tool(
    repo_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("APPIMAGE_TOOL", raising=False)
    monkeypatch.setattr(la, "find_appimagetool", lambda: None)
    binary = tmp_path / "ScannerManager"
    binary.write_bytes(b"bin")
    result = la.build_appimage(
        repo_root=repo_root,
        binary=binary,
        out_dir=tmp_path,
    )
    assert result is None


def test_build_appimage_invokes_tool(
    repo_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary = tmp_path / "ScannerManager"
    binary.write_bytes(b"bin")
    tool = tmp_path / "fake-appimagetool"
    tool.write_text("#!/bin/sh\n", encoding="utf-8")

    calls: list[list[str]] = []

    def _fake_run(cmd, **kwargs):  # noqa: ANN001
        calls.append(list(cmd))
        # Simulate appimagetool writing the output path (cmd[2])
        Path(cmd[2]).write_bytes(b"AI")
        return None

    monkeypatch.setattr(la.subprocess, "run", _fake_run)
    out = la.build_appimage(
        repo_root=repo_root,
        binary=binary,
        out_dir=tmp_path,
        appimagetool=tool,
    )
    assert out is not None
    assert out.name == "ScannerManager-x86_64.AppImage"
    assert out.is_file()
    assert calls and str(tool) in calls[0][0]
