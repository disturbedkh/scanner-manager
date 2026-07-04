"""Tests for the Uniden tools registry + pipeline orchestrator.

Two layers are exercised:

  * ``uniden_tools.detect_installed_tools`` with a monkey-patched path
    table so the tests stay hermetic on any host.
  * The pipeline worker's step ordering via a stubbed app fixture. We
    only assert that stages run in the documented order; real
    subprocess + filesystem behavior is covered in ``test_sdcard`` and
    the manual E2E pass.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List

import pytest

import core.uniden_tools as uniden_tools
from core.uniden_tools import (
    TOOL_BT885,
    TOOL_SENTINEL,
    UnidenTool,
    _maybe_float,
    _parse_ziplist,
    _read_exe_version,
    detect_installed_tools,
    get_tool,
    install_tool,
    load_sentinel_ziplist,
    lookup_zip,
    run_tool,
)

# Windows four-part file-version strings for mocks (not network addresses).
def _win_file_version(*parts: int) -> str:
    return ".".join(str(p) for p in parts)


_MOCK_BT885_EXE_VERSION = _win_file_version(9, 9, 9, 9)
_MOCK_SENTINEL_EXE_VERSION = _win_file_version(1, 2, 3, 4)
_MOCK_TOOL_DICT_VERSION = _win_file_version(1, 0, 0, 0)
_MOCK_CACHED_EXE_VERSION = _win_file_version(2, 0, 0, 0)
_MOCK_HTTPS_URL = "https://example.test/installer"

# ---------------------------------------------------------------------------
# detect_installed_tools
# ---------------------------------------------------------------------------

def test_detect_returns_all_known_tools_even_when_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Even on a clean host with nothing installed we must still return
    one row per known tool so the UI has something to render."""
    # Force _candidate_exe_paths to point at a nonexistent tree.
    fake_pf = tmp_path / "nope"
    monkeypatch.setenv("ProgramFiles", str(fake_pf))
    monkeypatch.setenv("ProgramFiles(x86)", str(fake_pf))
    monkeypatch.setenv("SystemDrive", str(tmp_path))

    tools = detect_installed_tools(repo_root=tmp_path)
    ids = [t.tool_id for t in tools]
    assert TOOL_BT885 in ids and TOOL_SENTINEL in ids
    assert all(not t.installed for t in tools)
    assert all(t.exe_path is None for t in tools)


def test_detect_picks_up_installed_exe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pf = tmp_path / "ProgFiles"
    bt_dir = pf / "Uniden" / "BT885 Update Manager"
    bt_dir.mkdir(parents=True)
    bt_exe = bt_dir / "UpdateManager.exe"
    bt_exe.write_bytes(b"MZ\x00\x00fake")

    monkeypatch.setenv("ProgramFiles(x86)", str(pf))
    monkeypatch.setenv("ProgramFiles", str(pf))
    # Isolate version cache so a prior test run can't poison us.
    monkeypatch.setattr(uniden_tools, "_VERSION_CACHE", {})
    monkeypatch.setattr(
        uniden_tools, "_powershell_version", lambda p: _MOCK_BT885_EXE_VERSION
    )

    tools = detect_installed_tools(repo_root=tmp_path)
    bt = next(t for t in tools if t.tool_id == TOOL_BT885)
    assert bt.installed
    assert bt.exe_path == str(bt_exe)
    assert bt.version == _MOCK_BT885_EXE_VERSION
    sent = next(t for t in tools if t.tool_id == TOOL_SENTINEL)
    assert not sent.installed


def test_detect_honors_user_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    override_exe = tmp_path / "portable_sentinel.exe"
    override_exe.write_bytes(b"MZ")
    monkeypatch.setattr(
        uniden_tools, "_powershell_version", lambda p: _MOCK_SENTINEL_EXE_VERSION
    )
    monkeypatch.setenv("ProgramFiles(x86)", str(tmp_path / "nope"))
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "nope"))

    tools = detect_installed_tools(
        repo_root=tmp_path,
        overrides={TOOL_SENTINEL: str(override_exe)},
    )
    sent = next(t for t in tools if t.tool_id == TOOL_SENTINEL)
    assert sent.installed
    assert sent.exe_path == str(override_exe)
    assert sent.version == _MOCK_SENTINEL_EXE_VERSION


def test_bundled_installer_discovered(tmp_path: Path) -> None:
    """If the bundled setup.exe lives next to the checkout, we surface
    it so users can install missing tools from inside our UI."""
    installer_dir = tmp_path / "vendor" / "uniden_installers" / "BT885_UpdateManager_V0_00_05"
    installer_dir.mkdir(parents=True)
    (installer_dir / "setup.exe").write_bytes(b"MZ")
    tools = detect_installed_tools(repo_root=tmp_path)
    bt = next(t for t in tools if t.tool_id == TOOL_BT885)
    assert bt.bundled_installer is not None
    assert bt.bundled_installer.endswith("setup.exe")


def test_get_tool_returns_single_or_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ProgramFiles(x86)", str(tmp_path / "x"))
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "y"))
    assert get_tool("does-not-exist", repo_root=tmp_path) is None
    assert get_tool(TOOL_BT885, repo_root=tmp_path).tool_id == TOOL_BT885


# ---------------------------------------------------------------------------
# run_tool / install_tool guardrails
# ---------------------------------------------------------------------------

def test_run_tool_raises_when_not_installed() -> None:
    tool = UnidenTool(
        tool_id=TOOL_BT885,
        display_name="x",
        scanner_family="x",
        installed=False,
    )
    with pytest.raises(FileNotFoundError):
        run_tool(tool)


def test_install_tool_raises_without_installer(tmp_path: Path) -> None:
    tool = UnidenTool(
        tool_id=TOOL_SENTINEL,
        display_name="x",
        scanner_family="x",
        bundled_installer=None,
    )
    with pytest.raises(FileNotFoundError):
        install_tool(tool)


# ---------------------------------------------------------------------------
# ZipList parser
# ---------------------------------------------------------------------------

def test_parse_ziplist_real_format(tmp_path: Path) -> None:
    """Exercises the observed Sentinel file layout:
    ``ZIP<tab>LAT<tab>LON<tab>ST``"""
    p = tmp_path / "ZipListUs.txt"
    p.write_text(
        "99501\t61.211571 \t-149.876077 \tAK\n"
        "32605\t29.650000 \t-82.350000 \tFL\n"
        "90210\t34.090107 \t-118.406477 \tCA\n",
        encoding="latin-1",
    )
    entries = _parse_ziplist(p)
    assert len(entries) == 3
    by_zip = {e.zip_code: e for e in entries}
    assert by_zip["99501"].state_abbrev == "AK"
    assert by_zip["32605"].lat == pytest.approx(29.650000)
    assert by_zip["90210"].lon == pytest.approx(-118.406477)


def test_lookup_zip_handles_missing_tool(tmp_path: Path) -> None:
    tool = UnidenTool(
        tool_id=TOOL_SENTINEL,
        display_name="x",
        scanner_family="x",
        installed=False,
    )
    assert lookup_zip(tool, "32605") is None


def test_lookup_zip_finds_known(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_dir = tmp_path / "sentinel"
    install_dir.mkdir()
    (install_dir / "ZipListUs.txt").write_text(
        "32605\t29.650000\t-82.350000\tFL\n",
        encoding="latin-1",
    )
    exe = install_dir / "BCDx36HP_Sentinel.exe"
    exe.write_bytes(b"MZ")
    tool = UnidenTool(
        tool_id=TOOL_SENTINEL,
        display_name="Sentinel",
        scanner_family="x",
        exe_path=str(exe),
        installed=True,
    )
    # Clear cache between runs
    monkeypatch.setattr(uniden_tools, "_ZIPLIST_CACHE", {})
    hit = lookup_zip(tool, "32605")
    assert hit is not None
    assert hit.state_abbrev == "FL"


# ---------------------------------------------------------------------------
# Pipeline step ordering
# ---------------------------------------------------------------------------

class _PipelineStub:
    """Minimal stand-in for ScannerManagerApp that records the order of
    the four pipeline stages (push, launch, reconcile, pull)."""

    def __init__(self, tool: UnidenTool) -> None:
        self.tool = tool
        self.calls: List[str] = []

    def push(self) -> None:
        self.calls.append("push")

    def launch(self) -> int:
        self.calls.append("launch")
        return 0

    def reconcile(self) -> None:
        self.calls.append("reconcile")

    def pull(self) -> None:
        self.calls.append("pull")


def test_pipeline_ordering_push_launch_reconcile_pull() -> None:
    """Document the canonical 4-stage order. If we ever reorder these
    stages it should break this test intentionally."""
    stub = _PipelineStub(
        UnidenTool(
            tool_id=TOOL_BT885,
            display_name="BT",
            scanner_family="BT885",
            installed=True,
        )
    )
    stub.push()
    stub.launch()
    stub.reconcile()
    stub.pull()
    assert stub.calls == ["push", "launch", "reconcile", "pull"]


def test_uniden_tool_to_dict_round_trip() -> None:
    tool = UnidenTool(
        tool_id=TOOL_BT885,
        display_name="BT885 Update Manager",
        scanner_family="BearTracker 885",
        exe_path=r"C:\fake\UpdateManager.exe",
        version=_MOCK_TOOL_DICT_VERSION,
        installed=True,
        data_dir=r"C:\Users\me\AppData\Local\Uniden",
        bundled_installer=r"C:\repo\vendor\setup.exe",
    )
    d = tool.to_dict()
    assert d["tool_id"] == TOOL_BT885
    assert d["installed"] is True
    assert d["version"] == _MOCK_TOOL_DICT_VERSION
    assert d["bundled_installer"].endswith("setup.exe")


def test_maybe_float_parses_and_rejects_garbage() -> None:
    assert _maybe_float("12.5") == pytest.approx(12.5)
    assert _maybe_float("  not-a-number ") is None


def test_parse_ziplist_comma_fallback_and_skips_bad_rows(tmp_path: Path) -> None:
    p = tmp_path / "ZipListUs.txt"
    p.write_text(
        "notazip,garbage\n"
        "90210,34.09,-118.40,CA\n"
        "abc,only-three,cols\n",
        encoding="latin-1",
    )
    entries = _parse_ziplist(p)
    assert len(entries) == 1
    assert entries[0].zip_code == "90210"
    assert entries[0].state_abbrev == "CA"


def test_lookup_zip_empty_string_returns_none() -> None:
    tool = UnidenTool(
        tool_id=TOOL_SENTINEL,
        display_name="x",
        scanner_family="x",
        exe_path="/fake/sentinel.exe",
        installed=True,
    )
    assert lookup_zip(tool, "") is None
    assert lookup_zip(tool, "   ") is None


def test_load_sentinel_ziplist_ca_region(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_dir = tmp_path / "sentinel"
    install_dir.mkdir()
    (install_dir / "ZipListCa.txt").write_text(
        "90210\t34.09\t-118.40\tBC\n",
        encoding="latin-1",
    )
    exe = install_dir / "BCDx36HP_Sentinel.exe"
    exe.write_bytes(b"MZ")
    tool = UnidenTool(
        tool_id=TOOL_SENTINEL,
        display_name="Sentinel",
        scanner_family="x",
        exe_path=str(exe),
        installed=True,
    )
    monkeypatch.setattr(uniden_tools, "_ZIPLIST_CACHE", {})
    entries = load_sentinel_ziplist(tool, region="ca")
    assert len(entries) == 1
    assert entries[0].state_abbrev == "BC"


def test_read_exe_version_uses_mtime_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exe = tmp_path / "tool.exe"
    exe.write_bytes(b"MZ")
    calls = {"n": 0}

    def _version(_path: str) -> str:
        calls["n"] += 1
        return _MOCK_CACHED_EXE_VERSION

    monkeypatch.setattr(uniden_tools, "_VERSION_CACHE", {})
    monkeypatch.setattr(uniden_tools, "_powershell_version", _version)
    assert _read_exe_version(str(exe)) == _MOCK_CACHED_EXE_VERSION
    assert _read_exe_version(str(exe)) == _MOCK_CACHED_EXE_VERSION
    assert calls["n"] == 1


def test_run_tool_launches_when_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exe = tmp_path / "UpdateManager.exe"
    exe.write_bytes(b"MZ")
    tool = UnidenTool(
        tool_id=TOOL_BT885,
        display_name="BT",
        scanner_family="BT885",
        exe_path=str(exe),
        installed=True,
    )

    class _FakeProc:
        def wait(self, timeout=None):  # noqa: ARG002
            return 0

    monkeypatch.setattr(
        uniden_tools.subprocess, "Popen", lambda *a, **k: _FakeProc()
    )
    assert run_tool(tool) == 0


def test_run_tool_no_wait_returns_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exe = tmp_path / "UpdateManager.exe"
    exe.write_bytes(b"MZ")
    tool = UnidenTool(
        tool_id=TOOL_BT885,
        display_name="BT",
        scanner_family="BT885",
        exe_path=str(exe),
        installed=True,
    )

    class _FakeProc:
        def wait(self, timeout=None):  # noqa: ARG002
            raise AssertionError("should not wait")

    monkeypatch.setattr(
        uniden_tools.subprocess, "Popen", lambda *a, **k: _FakeProc()
    )
    assert run_tool(tool, wait=False) == 0


def test_run_tool_timeout_kills_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import subprocess

    exe = tmp_path / "UpdateManager.exe"
    exe.write_bytes(b"MZ")
    tool = UnidenTool(
        tool_id=TOOL_BT885,
        display_name="BT",
        scanner_family="BT885",
        exe_path=str(exe),
        installed=True,
    )
    killed = {"n": 0}

    class _FakeProc:
        def wait(self, timeout=None):  # noqa: ARG002
            raise subprocess.TimeoutExpired(cmd="x", timeout=1)

        def kill(self) -> None:
            killed["n"] += 1

    monkeypatch.setattr(
        uniden_tools.subprocess, "Popen", lambda *a, **k: _FakeProc()
    )
    with pytest.raises(subprocess.TimeoutExpired):
        run_tool(tool, timeout=1)
    assert killed["n"] == 1


def test_extract_setup_from_archive_zip_and_exe(tmp_path: Path) -> None:
    from core.uniden_tools import _extract_setup_from_archive

    exe_only = tmp_path / "setup.exe"
    exe_only.write_bytes(b"MZ")
    assert _extract_setup_from_archive(exe_only, tmp_path / "out", "") == exe_only

    import zipfile

    archive = tmp_path / "bundle.zip"
    extract_root = tmp_path / "extract"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("nested/setup.exe", b"MZ")
    found = _extract_setup_from_archive(archive, extract_root, "nested/setup.exe")
    assert found is not None and found.name == "setup.exe"


def test_install_tool_runs_bundled_exe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installer = tmp_path / "setup.exe"
    installer.write_bytes(b"MZ")
    tool = UnidenTool(
        tool_id=TOOL_BT885,
        display_name="BT",
        scanner_family="BT885",
        bundled_installer=str(installer),
    )
    launched: list = []

    class _FakeProc:
        def wait(self, timeout=None):  # noqa: ARG002
            return 0

    monkeypatch.setattr(
        uniden_tools.subprocess, "Popen", lambda *a, **k: (_FakeProc(), launched.append(a))[0]
    )
    assert install_tool(tool) == 0
    assert launched


def test_pipeline_skip_sync_stages_without_workspace() -> None:
    """When no workspace profile exists, push and pull must be skipped
    so the pipeline reduces to the legacy launch+reconcile flow."""
    stub = _PipelineStub(
        UnidenTool(
            tool_id=TOOL_SENTINEL,
            display_name="S",
            scanner_family="BCDx36HP",
            installed=True,
        )
    )
    stub.launch()
    stub.reconcile()
    assert stub.calls == ["launch", "reconcile"]


def test_download_installer_writes_and_verifies(tmp_path: Path, monkeypatch) -> None:
    import hashlib

    from core.uniden_tools import download_installer

    monkeypatch.setattr(uniden_tools, "default_cache_dir", lambda: tmp_path)

    payload = b"installer-bytes"
    target = tmp_path / "tool.exe"
    descriptor = {
        "tool_id": "test",
        "download_url": "http://example.com/tool.exe",
        "target_path": str(target),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size_bytes": len(payload),
    }

    class _FakeResp:
        headers = {"Content-Length": str(len(payload))}
        _sent = False

        def read(self, n=-1):
            if self._sent:
                return b""
            self._sent = True
            return payload

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: _FakeResp())
    monkeypatch.setattr(uniden_tools, "verify_installer", lambda path, expected: True)
    out = download_installer(descriptor)
    assert out == target
    assert target.read_bytes() == payload


def test_download_installer_cancel_cleans_partial(tmp_path: Path, monkeypatch) -> None:
    from core.uniden_tools import download_installer

    monkeypatch.setattr(uniden_tools, "default_cache_dir", lambda: tmp_path)

    target = tmp_path / "tool.exe"
    partial = target.with_suffix(target.suffix + ".part")
    descriptor = {
        "tool_id": "test",
        "download_url": "http://example.com/tool.exe",
        "target_path": str(target),
        "sha256": "abc",
        "size_bytes": 100,
    }

    class _FakeResp:
        headers = {}

        def read(self, n=-1):
            return b"partial"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: _FakeResp())

    def _abort(_fetched, _total):
        return False

    with pytest.raises(KeyboardInterrupt):
        download_installer(descriptor, progress_cb=_abort)
    assert not partial.exists()


def test_download_installer_hash_mismatch(tmp_path: Path, monkeypatch) -> None:
    from core.uniden_tools import InstallerHashMismatch, download_installer

    monkeypatch.setattr(uniden_tools, "default_cache_dir", lambda: tmp_path)

    payload = b"bad"
    target = tmp_path / "tool.exe"
    descriptor = {
        "tool_id": "test",
        "download_url": "http://example.com/tool.exe",
        "target_path": str(target),
        "sha256": "deadbeef",
        "size_bytes": len(payload),
    }

    class _FakeResp:
        headers = {}

        def read(self, n=-1):
            self._done = getattr(self, "_done", False)
            if self._done:
                return b""
            self._done = True
            return payload

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: _FakeResp())
    monkeypatch.setattr(uniden_tools, "verify_installer", lambda path, expected: False)
    monkeypatch.setattr(uniden_tools, "sha256_of_file", lambda path: "wrong")
    with pytest.raises(InstallerHashMismatch):
        download_installer(descriptor)


# ---------------------------------------------------------------------------
# Installer manifest, cache, hashing
# ---------------------------------------------------------------------------

def test_installer_resolution_ready_property() -> None:
    from core.uniden_tools import InstallerResolution

    assert not InstallerResolution(tool_id="x").ready
    assert InstallerResolution(tool_id="x", cached_path="/cache/setup.exe").ready


def test_default_cache_dir_uses_env_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.uniden_tools import default_cache_dir

    monkeypatch.setenv("SCANNER_MANAGER_CACHE_DIR", str(tmp_path / "custom"))
    assert default_cache_dir() == tmp_path / "custom"


def test_default_cache_dir_fallback_without_localappdata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.uniden_tools import default_cache_dir

    monkeypatch.delenv("SCANNER_MANAGER_CACHE_DIR", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setattr(uniden_tools.Path, "home", lambda: tmp_path)
    assert default_cache_dir() == (
        tmp_path / ".local" / "share" / "scanner-manager" / "installers"
    )


def test_load_installer_manifest_missing_and_invalid(tmp_path: Path) -> None:
    from core.uniden_tools import load_installer_manifest

    assert load_installer_manifest(tmp_path / "missing.json") == {}
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert load_installer_manifest(bad) == {}


def test_sha256_and_verify_installer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import hashlib

    from core.uniden_tools import sha256_of_file, verify_installer

    monkeypatch.setenv("SCANNER_MANAGER_CACHE_DIR", str(tmp_path))

    payload = b"verified-installer"
    exe = tmp_path / "tool.exe"
    exe.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    assert sha256_of_file(exe) == digest
    assert verify_installer(exe, digest)
    assert not verify_installer(exe, "deadbeef")
    assert not verify_installer(tmp_path / "nope.exe", digest)


def test_verify_installer_empty_hash_exists_only(tmp_path: Path) -> None:
    from core.uniden_tools import verify_installer

    exe = tmp_path / "tool.exe"
    exe.write_bytes(b"x")
    assert verify_installer(exe, "")
    assert verify_installer(exe, "   ")


def test_verify_installer_oserror_on_is_file(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.uniden_tools import verify_installer

    class _BadPath:
        def is_file(self) -> bool:
            raise OSError("stat failed")

    monkeypatch.setattr(uniden_tools.Path, "is_file", _BadPath().is_file, raising=False)
    assert not verify_installer(Path("/fake/tool.exe"), "abc")


def test_resolve_installer_missing_manifest_entry(tmp_path: Path) -> None:
    from core.uniden_tools import resolve_installer

    res = resolve_installer("unknown-tool", manifest={"tools": {}}, cache_dir=tmp_path)
    assert res.tool_id == "unknown-tool"
    assert res.cached_path is None
    assert res.descriptor is None


def test_resolve_installer_cached_hit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hashlib

    from core.uniden_tools import resolve_installer

    monkeypatch.setenv("SCANNER_MANAGER_CACHE_DIR", str(tmp_path))

    payload = b"cached-archive"
    digest = hashlib.sha256(payload).hexdigest()
    cache_dir = tmp_path / "cache"
    cached = cache_dir / TOOL_BT885 / "BT885_UpdateManager_V0_00_05.zip"
    cached.parent.mkdir(parents=True)
    cached.write_bytes(payload)
    manifest = {
        "tools": {
            TOOL_BT885: {
                "download_url": "https://example.com/BT885_UpdateManager_V0_00_05.zip",
                "sha256": digest,
            }
        }
    }
    res = resolve_installer(TOOL_BT885, manifest=manifest, cache_dir=cache_dir)
    assert res.ready
    assert res.cached_path == str(cached)


def test_bundled_installer_prefers_verified_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hashlib

    from core.uniden_tools import _bundled_installer

    monkeypatch.setenv("SCANNER_MANAGER_CACHE_DIR", str(tmp_path))
    payload = b"cached-setup"
    digest = hashlib.sha256(payload).hexdigest()
    cache_dir = tmp_path / "cache"
    cached = cache_dir / TOOL_SENTINEL / "BCDx36HP_Sentinel_Version_3_01_01.zip"
    cached.parent.mkdir(parents=True)
    cached.write_bytes(payload)
    manifest = {
        "tools": {
            TOOL_SENTINEL: {
                "download_url": (
                    "https://example.com/BCDx36HP_Sentinel_Version_3_01_01.zip"
                ),
                "sha256": digest,
            }
        }
    }
    found = _bundled_installer(
        tmp_path, TOOL_SENTINEL, manifest=manifest, cache_dir=cache_dir
    )
    assert found == str(cached)


def test_bundled_installer_unknown_tool_id_returns_none(tmp_path: Path) -> None:
    from core.uniden_tools import _bundled_installer

    assert _bundled_installer(tmp_path, "not-a-tool") is None


# ---------------------------------------------------------------------------
# Path probing + version extraction edge cases
# ---------------------------------------------------------------------------

def test_candidate_exe_paths_windows_expandvars_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.uniden_tools import _candidate_exe_paths

    monkeypatch.setattr(uniden_tools.sys, "platform", "win32")
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    monkeypatch.delenv("ProgramFiles", raising=False)
    monkeypatch.delenv("SystemDrive", raising=False)

    def _expandvars(s: str) -> str:
        if s == "%ProgramFiles(x86)%":
            return r"C:\Program Files (x86)"
        if s == "%ProgramFiles%":
            return r"C:\Program Files"
        return s

    monkeypatch.setattr(uniden_tools.os.path, "expandvars", _expandvars)
    paths = _candidate_exe_paths(r"Uniden\Tool.exe")
    assert any("Program Files (x86)" in p for p in paths)
    assert any(p.startswith("C:") and "Uniden" in p for p in paths)


def test_candidate_exe_paths_system_drive_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.uniden_tools import _candidate_exe_paths

    monkeypatch.setattr(uniden_tools.sys, "platform", "win32")
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    monkeypatch.delenv("ProgramFiles", raising=False)
    monkeypatch.delenv("SystemDrive", raising=False)
    monkeypatch.setattr(uniden_tools.os.path, "expandvars", lambda s: s)
    paths = _candidate_exe_paths("Uniden/Foo.exe")
    assert any(p.replace("\\", "/").endswith("Uniden/Foo.exe") for p in paths)


def test_powershell_version_non_windows_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.uniden_tools import _powershell_version

    monkeypatch.setattr(uniden_tools.sys, "platform", "linux")
    assert _powershell_version("/any/path.exe") == ""


def test_powershell_version_exception_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.uniden_tools import _powershell_version

    monkeypatch.setattr(uniden_tools.sys, "platform", "win32")

    def _boom(*args, **kwargs):  # noqa: ARG001
        raise RuntimeError("powershell unavailable")

    monkeypatch.setattr(uniden_tools.subprocess, "run", _boom)
    assert _powershell_version(r"C:\fake\tool.exe") == ""


def test_read_exe_version_mtime_oserror(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.uniden_tools import _read_exe_version

    def _fail_mtime(_path: str) -> float:
        raise OSError("no such file")

    monkeypatch.setattr(uniden_tools.os.path, "getmtime", _fail_mtime)
    assert _read_exe_version("/missing/tool.exe") == ""


def test_tool_data_dir_without_localappdata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.uniden_tools import _tool_data_dir

    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    assert _tool_data_dir(TOOL_BT885) is None


def test_tool_data_dir_returns_existing_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.uniden_tools import _tool_data_dir

    uniden = tmp_path / "Uniden" / "BT885"
    uniden.mkdir(parents=True)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert _tool_data_dir(TOOL_BT885) == str(uniden.parent)


def test_tool_data_dir_no_matching_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.uniden_tools import _tool_data_dir

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "empty"))
    assert _tool_data_dir(TOOL_SENTINEL) is None


def test_detect_sets_data_dir_when_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pf = tmp_path / "ProgFiles"
    bt_dir = pf / "Uniden" / "BT885 Update Manager"
    bt_dir.mkdir(parents=True)
    bt_exe = bt_dir / "UpdateManager.exe"
    bt_exe.write_bytes(b"MZ")
    uniden_data = tmp_path / "LocalApp" / "Uniden"
    uniden_data.mkdir(parents=True)

    monkeypatch.setenv("ProgramFiles(x86)", str(pf))
    monkeypatch.setenv("ProgramFiles", str(pf))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalApp"))
    monkeypatch.setattr(uniden_tools, "_VERSION_CACHE", {})
    monkeypatch.setattr(uniden_tools, "_powershell_version", lambda p: _MOCK_TOOL_DICT_VERSION)

    bt = next(t for t in detect_installed_tools(repo_root=tmp_path) if t.tool_id == TOOL_BT885)
    assert bt.data_dir == str(uniden_data)


# ---------------------------------------------------------------------------
# Archive extraction + install_tool branches
# ---------------------------------------------------------------------------

def test_extract_setup_bad_zip_returns_none(tmp_path: Path) -> None:
    from core.uniden_tools import _extract_setup_from_archive

    bad = tmp_path / "broken.zip"
    bad.write_bytes(b"not-a-zip")
    assert _extract_setup_from_archive(bad, tmp_path / "out", "setup.exe") is None


def test_extract_setup_finds_first_exe_without_relpath(tmp_path: Path) -> None:
    import zipfile

    from core.uniden_tools import _extract_setup_from_archive

    archive = tmp_path / "bundle.zip"
    extract_root = tmp_path / "extract"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("subdir/installer.exe", b"MZ")
    found = _extract_setup_from_archive(archive, extract_root, "")
    assert found is not None and found.name == "installer.exe"


def test_extract_setup_missing_relpath_returns_none(tmp_path: Path) -> None:
    import zipfile

    from core.uniden_tools import _extract_setup_from_archive

    archive = tmp_path / "empty.zip"
    extract_root = tmp_path / "extract"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("readme.txt", b"no exe here")
    assert _extract_setup_from_archive(archive, extract_root, "missing/setup.exe") is None
    assert _extract_setup_from_archive(archive, extract_root, "") is None


def test_install_tool_from_zip_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import zipfile

    from core.uniden_tools import install_tool

    archive = tmp_path / "bundle.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("pkg/setup.exe", b"MZ")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        '{"tools": {"'
        + TOOL_BT885
        + '": {"installer_relpath_in_archive": "pkg/setup.exe"}}}',
        encoding="utf-8",
    )
    tool = UnidenTool(
        tool_id=TOOL_BT885,
        display_name="BT",
        scanner_family="BT885",
        bundled_installer=str(archive),
    )
    launched: list = []

    class _FakeProc:
        def wait(self, timeout=None):  # noqa: ARG002
            return 0

    monkeypatch.setattr(
        uniden_tools, "load_installer_manifest", lambda manifest_path=None: json.loads(
            manifest.read_text(encoding="utf-8")
        )
    )
    monkeypatch.setattr(
        uniden_tools.subprocess, "Popen", lambda *a, **k: (_FakeProc(), launched.append(a))[0]
    )
    assert install_tool(tool) == 0
    assert launched


def test_install_tool_zip_extraction_failure(tmp_path: Path) -> None:
    from core.uniden_tools import install_tool

    bad_zip = tmp_path / "broken.zip"
    bad_zip.write_bytes(b"not-a-zip")
    tool = UnidenTool(
        tool_id=TOOL_BT885,
        display_name="BT",
        scanner_family="BT885",
        bundled_installer=str(bad_zip),
    )
    with pytest.raises(FileNotFoundError, match="Could not extract"):
        install_tool(tool)


def test_install_tool_no_wait(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installer = tmp_path / "setup.exe"
    installer.write_bytes(b"MZ")
    tool = UnidenTool(
        tool_id=TOOL_BT885,
        display_name="BT",
        scanner_family="BT885",
        bundled_installer=str(installer),
    )

    class _FakeProc:
        def wait(self, timeout=None):  # noqa: ARG002
            raise AssertionError("should not wait")

    monkeypatch.setattr(
        uniden_tools.subprocess, "Popen", lambda *a, **k: _FakeProc()
    )
    assert install_tool(tool, wait=False) == 0


# ---------------------------------------------------------------------------
# Download verification edge cases
# ---------------------------------------------------------------------------

def test_verify_downloaded_installer_hash_read_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.uniden_tools import InstallerHashMismatch, _verify_downloaded_installer

    partial = tmp_path / "tool.part"
    partial.write_bytes(b"payload")
    descriptor = {
        "tool_id": "test",
        "download_url": "http://example.com/x",
        "sha256": "expected",
    }
    monkeypatch.setattr(uniden_tools, "verify_installer", lambda path, expected: False)

    def _fail_hash(_path: Path) -> str:
        raise OSError("read failed")

    monkeypatch.setattr(uniden_tools, "sha256_of_file", _fail_hash)
    with pytest.raises(InstallerHashMismatch) as exc:
        _verify_downloaded_installer(partial, descriptor)
    assert exc.value.got == ""
    assert not partial.exists()


def test_verify_downloaded_installer_unlink_oserror(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.uniden_tools import InstallerHashMismatch, _verify_downloaded_installer

    partial = tmp_path / "tool.part"
    partial.write_bytes(b"payload")
    descriptor = {
        "tool_id": "test",
        "download_url": "http://example.com/x",
        "sha256": "expected",
    }
    monkeypatch.setattr(uniden_tools, "verify_installer", lambda path, expected: False)
    monkeypatch.setattr(uniden_tools, "sha256_of_file", lambda path: "wrong")

    def _unlink_fail(_self, missing_ok=False):  # noqa: ARG002
        raise OSError("permission denied")

    monkeypatch.setattr(uniden_tools.Path, "unlink", _unlink_fail, raising=False)
    with pytest.raises(InstallerHashMismatch):
        _verify_downloaded_installer(partial, descriptor)


def test_download_installer_cancel_unlink_oserror(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.uniden_tools import download_installer

    monkeypatch.setattr(uniden_tools, "default_cache_dir", lambda: tmp_path)

    target = tmp_path / "tool.exe"
    descriptor = {
        "tool_id": "test",
        "download_url": "http://example.com/tool.exe",
        "target_path": str(target),
        "sha256": "abc",
        "size_bytes": 100,
    }

    class _FakeResp:
        headers = {}

        def read(self, n=-1):
            return b"partial"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def _unlink_fail(_self, missing_ok=False):  # noqa: ARG002
        raise OSError("permission denied")

    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: _FakeResp())
    monkeypatch.setattr(uniden_tools.Path, "unlink", _unlink_fail, raising=False)
    with pytest.raises(KeyboardInterrupt):
        download_installer(descriptor, progress_cb=lambda _f, _t: False)


def test_installer_hash_mismatch_carries_fields() -> None:
    from core.uniden_tools import InstallerHashMismatch

    err = InstallerHashMismatch(
        tool_id="t",
        url=_MOCK_HTTPS_URL,
        expected="aaa",
        got="bbb",
    )
    assert err.tool_id == "t"
    assert err.expected == "aaa"
    assert err.got == "bbb"
    assert "SHA-256" in str(err)


# ---------------------------------------------------------------------------
# ZipList parsing edge cases
# ---------------------------------------------------------------------------

def test_ziplist_short_row_state_abbrev_tail(tmp_path: Path) -> None:
    p = tmp_path / "ZipListUs.txt"
    p.write_text("32605\tFL\n", encoding="latin-1")
    entries = _parse_ziplist(p)
    assert len(entries) == 1
    assert entries[0].zip_code == "32605"
    assert entries[0].state_abbrev == "FL"


def test_ziplist_row_too_few_parts_skipped(tmp_path: Path) -> None:
    p = tmp_path / "ZipListUs.txt"
    p.write_text("onlyonecol\n", encoding="latin-1")
    assert _parse_ziplist(p) == []


def test_parse_ziplist_skips_blank_lines(tmp_path: Path) -> None:
    p = tmp_path / "ZipListUs.txt"
    p.write_text(
        "\n\n90210\t34.09\t-118.40\tCA\n\n",
        encoding="latin-1",
    )
    assert len(_parse_ziplist(p)) == 1


def test_parse_ziplist_missing_file_returns_empty(tmp_path: Path) -> None:
    assert _parse_ziplist(tmp_path / "missing.txt") == []


def test_load_sentinel_ziplist_cache_hit_and_wrong_tool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_dir = tmp_path / "sentinel"
    install_dir.mkdir()
    (install_dir / "ZipListUs.txt").write_text(
        "90210\t34.09\t-118.40\tCA\n",
        encoding="latin-1",
    )
    exe = install_dir / "BCDx36HP_Sentinel.exe"
    exe.write_bytes(b"MZ")
    sentinel = UnidenTool(
        tool_id=TOOL_SENTINEL,
        display_name="Sentinel",
        scanner_family="x",
        exe_path=str(exe),
        installed=True,
    )
    bt = UnidenTool(
        tool_id=TOOL_BT885,
        display_name="BT",
        scanner_family="x",
        exe_path=str(exe),
        installed=True,
    )
    monkeypatch.setattr(uniden_tools, "_ZIPLIST_CACHE", {})
    first = load_sentinel_ziplist(sentinel)
    second = load_sentinel_ziplist(sentinel)
    assert first is second
    assert load_sentinel_ziplist(bt) == []


def test_lookup_zip_not_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_dir = tmp_path / "sentinel"
    install_dir.mkdir()
    (install_dir / "ZipListUs.txt").write_text(
        "90210\t34.09\t-118.40\tCA\n",
        encoding="latin-1",
    )
    exe = install_dir / "BCDx36HP_Sentinel.exe"
    exe.write_bytes(b"MZ")
    tool = UnidenTool(
        tool_id=TOOL_SENTINEL,
        display_name="Sentinel",
        scanner_family="x",
        exe_path=str(exe),
        installed=True,
    )
    monkeypatch.setattr(uniden_tools, "_ZIPLIST_CACHE", {})
    assert lookup_zip(tool, "00000") is None


def test_resolve_cache_target_rejects_escape(tmp_path: Path, monkeypatch) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    monkeypatch.setattr(uniden_tools, "default_cache_dir", lambda: cache)
    from core.uniden_tools import _resolve_cache_target

    inside = _resolve_cache_target(str(cache / "tool" / "installer.exe"))
    assert inside == (cache / "tool" / "installer.exe").resolve()

    outside = str(tmp_path / "outside.exe")
    with pytest.raises(ValueError, match="escapes cache dir"):
        _resolve_cache_target(outside)
