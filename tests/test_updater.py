"""Tests for :mod:`updater`.

Covers the pure bits of the updater: version comparison, platform asset
picking, GitHub-release payload parsing, hash verification, and the
shape of the Windows self-swap bat. No real network is contacted and
no subprocess is spawned.
"""
from __future__ import annotations

import hashlib
import io
import json
import socket
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

import core.app_updater as updater

# ---------------------------------------------------------------------------
# Version compare
# ---------------------------------------------------------------------------


def test_version_compare_orders_prerelease_before_final():
    assert updater.Version("0.9.0a2") < updater.Version("0.9.0a3")
    assert updater.Version("0.9.0a3") < updater.Version("0.9.0")
    assert updater.Version("0.9.0") < updater.Version("0.9.1a1")
    assert updater.Version("0.9.1a1") < updater.Version("1.0.0")


def test_is_newer_handles_v_prefix_and_invalid():
    info = updater.parse_release_payload(
        {"tag_name": "v0.9.0a3", "name": "v0.9.0a3"}
    )
    assert info is not None
    assert info.version == "0.9.0a3"
    assert updater.parse_release_payload({"tag_name": "banana"}) is None


# ---------------------------------------------------------------------------
# Asset picker
# ---------------------------------------------------------------------------


def _fake_info() -> updater.UpdateInfo:
    return updater.UpdateInfo(
        tag="v0.9.0a3",
        version="0.9.0a3",
        assets=[
            updater.Asset(name="ScannerManager-windows-x64.zip", browser_download_url="https://x/win.zip"),
            updater.Asset(name="ScannerManager-windows-x64.zip.sha256", browser_download_url="https://x/win.zip.sha256"),
            updater.Asset(name="ScannerManager-macos.tar.gz", browser_download_url="https://x/mac.tar.gz"),
            updater.Asset(name="ScannerManager-linux-x64.tar.gz", browser_download_url="https://x/lin.tar.gz"),
        ],
    )


@pytest.mark.parametrize(
    "platform,expected",
    [
        ("win32", "ScannerManager-windows-x64.zip"),
        ("darwin", "ScannerManager-macos.tar.gz"),
        ("linux", "ScannerManager-linux-x64.tar.gz"),
        ("linux2", "ScannerManager-linux-x64.tar.gz"),
    ],
)
def test_pick_platform_asset(platform, expected):
    asset = updater.pick_platform_asset(_fake_info(), platform=platform)
    assert asset is not None
    assert asset.name == expected


def test_pick_sha_asset_returns_sibling():
    info = _fake_info()
    target = info.assets[0]  # windows zip
    sha = updater.pick_sha_asset(info, target)
    assert sha is not None
    assert sha.name == f"{target.name}.sha256"


# ---------------------------------------------------------------------------
# check_for_update
# ---------------------------------------------------------------------------


def _mock_urlopen(body: bytes, *, status: int = 200):
    class _Resp(io.BytesIO):
        def __init__(self, data: bytes) -> None:
            super().__init__(data)
            self.headers: dict[str, str] = {"Content-Length": str(len(data))}

        def __enter__(self) -> "_Resp":
            return self

        def __exit__(self, *exc: Any) -> None:  # noqa: D401
            self.close()

    def _opener(req, *, timeout=0):  # pragma: no cover - trivial
        return _Resp(body)

    return _opener


def test_check_for_update_returns_info_when_newer():
    payload = json.dumps({
        "tag_name": "v0.9.0a3",
        "name": "v0.9.0a3",
        "body": "# Notes\nsome notes",
        "prerelease": True,
        "assets": [],
        "html_url": "https://example.test/release",
    }).encode("utf-8")
    info = updater.check_for_update(
        "0.9.0a2", urlopen=_mock_urlopen(payload), timeout=1.0,
    )
    assert info is not None
    assert info.version == "0.9.0a3"


def test_check_for_update_returns_none_when_current():
    payload = json.dumps({
        "tag_name": "v0.9.0a2",
        "name": "v0.9.0a2",
        "prerelease": True,
        "assets": [],
    }).encode("utf-8")
    info = updater.check_for_update(
        "0.9.0a2", urlopen=_mock_urlopen(payload), timeout=1.0,
    )
    assert info is None


def test_check_for_update_respects_timeout():
    def boom(req, *, timeout=0):
        raise socket.timeout("nope")

    info = updater.check_for_update(
        "0.9.0a2", urlopen=boom, timeout=0.1,
    )
    assert info is None


def test_check_for_update_skips_prereleases_when_opted_out():
    payload = json.dumps({
        "tag_name": "v0.9.0a3",
        "prerelease": True,
        "assets": [],
    }).encode("utf-8")
    info = updater.check_for_update(
        "0.9.0a2",
        urlopen=_mock_urlopen(payload),
        include_prereleases=False,
    )
    assert info is None


# ---------------------------------------------------------------------------
# download_and_verify
# ---------------------------------------------------------------------------


def _opener_sequence(*bodies: bytes):
    """Return a urlopen-compatible callable that yields the next body
    from ``bodies`` on each call — used when download_and_verify needs
    to fetch both the asset and the sha256 sibling.
    """
    queue = list(bodies)

    class _Resp(io.BytesIO):
        def __init__(self, data: bytes) -> None:
            super().__init__(data)
            self.headers = {"Content-Length": str(len(data))}

        def __enter__(self) -> "_Resp":
            return self

        def __exit__(self, *exc: Any) -> None:
            self.close()

    def _opener(req, *, timeout=0):
        return _Resp(queue.pop(0))

    return _opener


def test_download_and_verify_matches_expected(tmp_path: Path):
    payload = b"hello-update"
    digest = hashlib.sha256(payload).hexdigest()
    asset = updater.Asset(name="payload.zip", browser_download_url="https://x/payload.zip")
    sha_asset = updater.Asset(
        name="payload.zip.sha256",
        browser_download_url="https://x/payload.zip.sha256",
    )
    opener = _opener_sequence(
        (digest + "  payload.zip\n").encode("utf-8"),
        payload,
    )
    dest = tmp_path / "payload.zip"
    result = updater.download_and_verify(
        asset, dest, sha_asset=sha_asset, urlopen=opener,
    )
    assert result == dest
    assert dest.read_bytes() == payload


def test_download_and_verify_rejects_mismatch(tmp_path: Path):
    payload = b"hello-update"
    wrong = "0" * 64
    asset = updater.Asset(name="payload.zip", browser_download_url="https://x/payload.zip")
    opener = _opener_sequence(payload)
    dest = tmp_path / "payload.zip"
    with pytest.raises(ValueError):
        updater.download_and_verify(
            asset, dest, expected_sha256=wrong, urlopen=opener,
        )
    # Partial file should be cleaned up.
    assert not dest.exists()


# ---------------------------------------------------------------------------
# Windows swap bat
# ---------------------------------------------------------------------------


def test_build_windows_swap_bat_has_expected_shape(tmp_path: Path):
    bat = tmp_path / "swap.bat"
    updater.build_windows_swap_bat(
        bat,
        new_exe=tmp_path / "new.exe",
        current_exe=tmp_path / "current.exe",
    )
    content = bat.read_text(encoding="ascii")
    assert content.startswith("@echo off")
    assert "tasklist" in content
    assert "move /y" in content
    assert 'start ""' in content
    assert content.rstrip().endswith('del "%~f0"')


def test_apply_update_windows_spawns_bat_with_expected_args(tmp_path: Path):
    spawn = MagicMock()
    bat = updater.apply_update_windows(
        new_exe=tmp_path / "new.exe",
        current_exe=tmp_path / "current.exe",
        script_dir=tmp_path,
        spawn=spawn,
    )
    assert bat.exists()
    spawn.assert_called_once()
    args = spawn.call_args[0][0]
    assert args[0].lower().endswith("cmd.exe")
    assert args[1] == "/c"
    assert args[2] == str(bat)
    assert args[4] == "current.exe"
    assert args[5] == str(tmp_path / "new.exe")
    assert args[6] == str(tmp_path / "current.exe")
