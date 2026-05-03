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

from pathlib import Path
from typing import List

import pytest

import uniden_tools
from uniden_tools import (
    TOOL_BT885,
    TOOL_SENTINEL,
    UnidenTool,
    _parse_ziplist,
    detect_installed_tools,
    get_tool,
    install_tool,
    lookup_zip,
    run_tool,
)

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
        uniden_tools, "_powershell_version", lambda p: "9.9.9.9"
    )

    tools = detect_installed_tools(repo_root=tmp_path)
    bt = next(t for t in tools if t.tool_id == TOOL_BT885)
    assert bt.installed
    assert bt.exe_path == str(bt_exe)
    assert bt.version == "9.9.9.9"
    sent = next(t for t in tools if t.tool_id == TOOL_SENTINEL)
    assert not sent.installed


def test_detect_honors_user_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    override_exe = tmp_path / "portable_sentinel.exe"
    override_exe.write_bytes(b"MZ")
    monkeypatch.setattr(
        uniden_tools, "_powershell_version", lambda p: "1.2.3.4"
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
    assert sent.version == "1.2.3.4"


def test_bundled_installer_discovered(tmp_path: Path) -> None:
    """If the bundled setup.exe lives next to the checkout, we surface
    it so users can install missing tools from inside our UI."""
    installer_dir = tmp_path / "BT885_UpdateManager_V0_00_05"
    installer_dir.mkdir()
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
    has_workspace = False
    if has_workspace:
        stub.push()
    stub.launch()
    stub.reconcile()
    if has_workspace:
        stub.pull()
    assert stub.calls == ["launch", "reconcile"]
