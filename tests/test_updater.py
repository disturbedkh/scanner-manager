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
    assert updater.parse_release_payload([]) is None
    assert updater.parse_release_payload({"tag_name": ""}) is None


def test_parse_release_payload_skips_bad_assets():
    info = updater.parse_release_payload(
        {
            "tag_name": "v1.0.0",
            "assets": [
                {"name": "", "browser_download_url": "https://x/a"},
                {"name": "good.zip", "browser_download_url": "https://x/good.zip", "size": 10},
                "not-a-dict",
            ],
        }
    )
    assert info is not None
    assert len(info.assets) == 1
    assert info.assets[0].name == "good.zip"


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
    updater.build_windows_swap_bat(bat)
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


# ---------------------------------------------------------------------------
# Linux swap + extract
# ---------------------------------------------------------------------------


def test_build_linux_swap_script_has_expected_shape(tmp_path: Path):
    script = tmp_path / "swap.sh"
    updater.build_linux_swap_script(script)
    content = script.read_text(encoding="utf-8")
    assert content.startswith("#!/bin/sh")
    assert "kill -0" in content
    assert 'mv -f "$new_bin" "$cur_exe"' in content
    assert "chmod +x" in content
    assert "nohup" in content
    assert 'rm -f -- "$0"' in content


def test_apply_update_linux_spawns_sh_with_expected_args(tmp_path: Path):
    spawn = MagicMock()
    script = updater.apply_update_linux(
        new_binary=tmp_path / "ScannerManager.new",
        current_exe=tmp_path / "ScannerManager",
        script_dir=tmp_path,
        spawn=spawn,
    )
    assert script.exists()
    spawn.assert_called_once()
    args = spawn.call_args[0][0]
    assert args[0] == "/bin/sh"
    assert args[1] == str(script)
    assert args[3] == str(tmp_path / "ScannerManager.new")
    assert args[4] == str(tmp_path / "ScannerManager")


def test_extract_linux_release_binary(tmp_path: Path):
    import tarfile

    archive = tmp_path / "ScannerManager-linux-x64.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        payload = b"#!/bin/sh\necho ok\n"
        info = tarfile.TarInfo(name="ScannerManager")
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))
    out = updater.extract_linux_release_binary(archive, tmp_path / "out")
    assert out.name == "ScannerManager.new"
    assert out.read_bytes() == payload


def test_extract_linux_release_binary_rejects_traversal(tmp_path: Path):
    import tarfile

    archive = tmp_path / "bad.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        payload = b"x"
        info = tarfile.TarInfo(name="../ScannerManager")
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))
    with pytest.raises(ValueError, match="traversal"):
        updater.extract_linux_release_binary(archive, tmp_path / "out")


def test_extract_linux_release_binary_missing_member(tmp_path: Path):
    import tarfile

    archive = tmp_path / "empty.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        payload = b"readme"
        info = tarfile.TarInfo(name="README")
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))
    with pytest.raises(ValueError, match="no ScannerManager"):
        updater.extract_linux_release_binary(archive, tmp_path / "out")


def test_is_running_as_appimage(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("APPIMAGE", raising=False)
    monkeypatch.setattr(updater.sys, "argv", ["/opt/ScannerManager"])
    assert not updater.is_running_as_appimage()
    monkeypatch.setenv("APPIMAGE", "/tmp/ScannerManager-x86_64.AppImage")
    assert updater.is_running_as_appimage()
    monkeypatch.delenv("APPIMAGE", raising=False)
    monkeypatch.setattr(
        updater.sys, "argv", ["/home/u/ScannerManager-x86_64.AppImage"]
    )
    assert updater.is_running_as_appimage()


def test_install_linux_update_from_release(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import tarfile

    payload = b"new-bin"
    archive_bytes = io.BytesIO()
    with tarfile.open(fileobj=archive_bytes, mode="w:gz") as tar:
        info = tarfile.TarInfo(name="ScannerManager")
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))
    archive_data = archive_bytes.getvalue()
    digest = hashlib.sha256(archive_data).hexdigest()

    info = updater.UpdateInfo(
        tag="v0.12.0",
        version="0.12.0",
        assets=[
            updater.Asset(
                name="ScannerManager-linux-x64.tar.gz",
                browser_download_url="https://x/lin.tar.gz",
                size=len(archive_data),
            ),
            updater.Asset(
                name="ScannerManager-linux-x64.tar.gz.sha256",
                browser_download_url="https://x/lin.tar.gz.sha256",
            ),
        ],
    )

    def fake_urlopen(req, timeout=60.0):  # noqa: ANN001
        url = req.full_url if hasattr(req, "full_url") else str(req)
        body = archive_data if url.endswith(".tar.gz") else (digest + "\n").encode()
        resp = MagicMock()
        resp.read = MagicMock(side_effect=[body, b""] if url.endswith(".tar.gz") else [body])
        resp.headers = {"Content-Length": str(len(body))}
        resp.__enter__ = MagicMock(return_value=resp)
        resp.__exit__ = MagicMock(return_value=False)
        # stream reads in a loop — for sha one read is enough; for tar need chunks
        if url.endswith(".tar.gz"):
            chunks = [archive_data[i : i + 100] for i in range(0, len(archive_data), 100)]
            chunks.append(b"")
            resp.read = MagicMock(side_effect=chunks)
        return resp

    spawn = MagicMock()
    current = tmp_path / "ScannerManager"
    current.write_bytes(b"old")
    script = updater.install_linux_update_from_release(
        info,
        current,
        work_dir=tmp_path / "work",
        urlopen=fake_urlopen,
        spawn=spawn,
    )
    assert script.exists()
    spawn.assert_called_once()
    new_bin = tmp_path / "work" / "ScannerManager.new"
    assert new_bin.read_bytes() == payload
