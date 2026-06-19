"""Smoke tests for the Phase 6 Qt dialog ports.

Each test instantiates one dialog and confirms the constructor doesn't
raise + the basic state is sane. Full UI interaction (click handlers,
file IO) is exercised by the focused tests in
``test_dialog_workspaces.py`` etc. (left for future work).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("pytestqt")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gui.dialogs.changes import ChangesPanelDialog  # noqa: E402
from gui.dialogs.city_manager import CityManagerDialog  # noqa: E402
from gui.dialogs.profile_snapshots import ProfileSnapshotsDialog  # noqa: E402
from gui.dialogs.report_issue import ReportIssueDialog  # noqa: E402
from gui.dialogs.sync_conflict import SyncConflictDialog  # noqa: E402
from gui.dialogs.uniden_tools import UnidenToolsDialog  # noqa: E402
from gui.dialogs.update_available import UpdateAvailableDialog  # noqa: E402
from gui.dialogs.workspaces import (  # noqa: E402
    Workspace,
    WorkspaceManagerDialog,
    load_workspaces,
    save_workspaces,
)


def test_workspaces_round_trip(tmp_path: Path):
    target = tmp_path / "workspaces.json"
    items = [
        Workspace(name="Home", devices_path="/path/devices.json"),
        Workspace(name="Travel", devices_path="/another/devices.json"),
    ]
    save_workspaces(items, path=target)
    reloaded = load_workspaces(path=target)
    assert [w.name for w in reloaded] == ["Home", "Travel"]
    assert reloaded[0].devices_path == "/path/devices.json"


def test_workspaces_dialog_builds(qtbot, tmp_path: Path):
    dlg = WorkspaceManagerDialog(path=tmp_path / "ws.json")
    qtbot.addWidget(dlg)
    assert dlg.windowTitle() == "Workspaces"


def test_profile_snapshots_dialog_builds(qtbot, tmp_path: Path):
    dlg = ProfileSnapshotsDialog(scanner_profile_id="uniden_sds100", card_root=tmp_path)
    qtbot.addWidget(dlg)
    assert "snapshots" in dlg.windowTitle().lower()


def test_changes_dialog_builds_with_no_metastore(qtbot, tmp_path: Path):
    dlg = ChangesPanelDialog(hpd_path=str(tmp_path / "missing.hpd"))
    qtbot.addWidget(dlg)
    # An empty / new metastore should still leave the table in a
    # consistent state (zero rows is fine, just no crash).
    assert dlg._table.columnCount() == 5


def test_sync_conflict_dialog_builds(qtbot):
    conflicts = [
        {
            "target_id": "cfreq::1::1::462.5500",
            "summary": "Local renamed; remote re-tagged",
            "local": {"name": "FD-1", "tag": "Fire"},
            "remote": {"name": "FD-1", "tag": "EMS"},
        }
    ]
    dlg = SyncConflictDialog(conflicts=conflicts)
    qtbot.addWidget(dlg)
    assert "Conflict 1 / 1" in dlg._header.text()


def test_city_manager_dialog_builds(qtbot, tmp_path: Path):
    dlg = CityManagerDialog(path=tmp_path / "cities.json")
    qtbot.addWidget(dlg)
    assert "overrides" in dlg.windowTitle().lower()


def test_uniden_tools_dialog_builds(qtbot):
    dlg = UnidenToolsDialog()
    qtbot.addWidget(dlg)
    assert "uniden" in dlg.windowTitle().lower()


def test_update_available_dialog_renders_each_mode(qtbot):
    for mode in (
        UpdateAvailableDialog.MODE_AVAILABLE,
        UpdateAvailableDialog.MODE_CURRENT,
        UpdateAvailableDialog.MODE_OFFLINE,
    ):
        dlg = UpdateAvailableDialog(info=None, current_version="0.10.0", mode=mode)
        qtbot.addWidget(dlg)
        assert dlg.windowTitle().startswith("Scanner Manager")


def test_report_issue_dialog_builds(qtbot):
    dlg = ReportIssueDialog()
    qtbot.addWidget(dlg)
    body = dlg._build_body()
    assert "OS:" in body or "Environment" in body
