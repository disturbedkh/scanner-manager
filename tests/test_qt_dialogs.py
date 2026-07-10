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

pytestmark = pytest.mark.qt

pytest.importorskip("pytestqt")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QInputDialog, QTextEdit  # noqa: E402

from gui.dialogs.changes import ChangesPanelDialog  # noqa: E402
from gui.dialogs.city_manager import CityManagerDialog, load_overrides  # noqa: E402
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


def test_uniden_tools_dialog_builds(qtbot, monkeypatch):
    import sys

    monkeypatch.setattr(sys, "platform", "win32")
    dlg = UnidenToolsDialog()
    qtbot.addWidget(dlg)
    assert "uniden" in dlg.windowTitle().lower()


def test_uniden_tools_dialog_shows_windows_only_banner(qtbot, monkeypatch):
    import sys

    monkeypatch.setattr(sys, "platform", "linux")
    dlg = UnidenToolsDialog()
    qtbot.addWidget(dlg)
    assert dlg._windows_only
    assert not dlg._run_btn.isEnabled()
    assert not dlg._install_btn.isEnabled()


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


@pytest.fixture
def auto_msgbox(monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)


def test_city_manager_add_delete_round_trip(qtbot, tmp_path: Path, auto_msgbox):
    path = tmp_path / "cities.json"
    dlg = CityManagerDialog(path=path)
    qtbot.addWidget(dlg)
    dlg._zip_field.setText("33101")
    dlg._city_field.setText("Miami")
    dlg._state_field.setText("FL")
    dlg._county_field.setText("Miami-Dade")
    dlg._lat_field.setValue(25.7617)
    dlg._lon_field.setValue(-80.1918)
    dlg._on_add()
    assert dlg._table.rowCount() == 1
    assert load_overrides(path)["33101"]["city"] == "Miami"
    dlg._table.selectRow(0)
    dlg._on_selection()
    assert dlg._zip_field.text() == "33101"
    dlg._on_delete()
    assert dlg._table.rowCount() == 0
    assert load_overrides(path) == {}


def test_city_manager_rejects_empty_zip(qtbot, tmp_path: Path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.append(a))
    dlg = CityManagerDialog(path=tmp_path / "cities.json")
    qtbot.addWidget(dlg)
    dlg._on_add()
    assert warned


def test_workspaces_dialog_new_rename_delete_load(
    qtbot, tmp_path: Path, monkeypatch, auto_msgbox
):
    ws_path = tmp_path / "ws.json"
    monkeypatch.setattr(
        QInputDialog, "getText", lambda *a, **k: ("Travel", True)
    )
    devices = tmp_path / "devices.json"
    devices.write_text("{}", encoding="utf-8")

    dlg = WorkspaceManagerDialog(path=ws_path)
    qtbot.addWidget(dlg)

    monkeypatch.setattr(
        "gui.dialogs.workspaces.QFileDialog.getOpenFileName",
        lambda *a, **k: (str(devices), ""),
    )
    dlg._on_new()
    assert dlg._list.count() == 1
    dlg._list.setCurrentRow(0)

    monkeypatch.setattr(
        QInputDialog, "getText", lambda *a, **k: ("Road trip", True)
    )
    dlg._on_rename()
    dlg._list.setCurrentRow(0)
    assert dlg._list.currentItem().text().startswith("Road trip")

    loaded = []
    dlg.workspaceLoaded.connect(loaded.append)
    dlg._on_load()
    assert loaded and loaded[0].name == "Road trip"

    dlg2 = WorkspaceManagerDialog(path=ws_path)
    qtbot.addWidget(dlg2)
    dlg2._list.setCurrentRow(0)
    dlg2._on_delete()
    assert dlg2._list.count() == 0


def test_profile_snapshots_take_restore_delete(
    qtbot, tmp_path: Path, monkeypatch, auto_msgbox
):
    from gui.dialogs import profile_snapshots as ps

    card = tmp_path / "card"
    bcd = card / "BCDx36HP"
    bcd.mkdir(parents=True)
    (bcd / "scanner.inf").write_text("SDS100\n", encoding="utf-8")
    snap_root = tmp_path / "snaps"
    monkeypatch.setattr(ps, "_snapshots_root", lambda: snap_root)
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("before-edit", True))

    dlg = ProfileSnapshotsDialog(scanner_profile_id="uniden_sds100", card_root=card)
    qtbot.addWidget(dlg)
    dlg._on_take()
    assert dlg._list.count() == 1

    (bcd / "scanner.inf").write_text("CHANGED\n", encoding="utf-8")
    dlg._list.setCurrentRow(0)
    restored = []
    dlg.snapshotRestored.connect(restored.append)
    dlg._on_restore()
    assert (bcd / "scanner.inf").read_text(encoding="utf-8") == "SDS100\n"
    assert restored

    dlg._on_delete()
    assert dlg._list.count() == 0


def test_changes_dialog_lists_filters_and_reverts(
    qtbot, tmp_path: Path, monkeypatch, auto_msgbox
):
    from PySide6.QtWidgets import QMessageBox

    from core.metastore import OP_EDIT_ENTRY, MetaStore

    hpd_path = tmp_path / "s_000012.hpd"
    hpd_path.write_text("TargetModel\tBCDx36HP\n", encoding="utf-8")
    store = MetaStore(str(hpd_path))
    event = store.record(
        op=OP_EDIT_ENTRY,
        target_id="cfreq::1::1::462.5500",
        payload={},
        summary="renamed entry",
        target_name="FD-1",
    )
    store.save()

    def _loaded_store(hpd: str) -> MetaStore:
        loaded = MetaStore(hpd)
        loaded.load()
        return loaded

    monkeypatch.setattr(
        "gui.dialogs.changes.metastore.MetaStore",
        _loaded_store,
    )

    dlg = ChangesPanelDialog(hpd_path=str(hpd_path))
    qtbot.addWidget(dlg)
    assert dlg._table.rowCount() == 1
    assert dlg._table.item(0, 1).text() == OP_EDIT_ENTRY

    idx = dlg._filter.findText("delete_entry")
    dlg._filter.setCurrentIndex(idx)
    assert dlg._table.rowCount() == 0

    dlg._filter.setCurrentIndex(0)
    dlg._table.selectRow(0)
    reverted: list = []
    dlg.eventReverted.connect(reverted.append)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    dlg._on_revert()
    assert reverted == [event.event_id]
    assert dlg._table.item(0, 4).text() == "yes"


def test_changes_dialog_revert_no_selection_is_noop(qtbot, tmp_path: Path):
    hpd_path = tmp_path / "s_000012.hpd"
    hpd_path.write_text("x", encoding="utf-8")
    dlg = ChangesPanelDialog(hpd_path=str(hpd_path))
    qtbot.addWidget(dlg)
    dlg._on_revert()


def test_changes_dialog_revert_failure_shows_critical(
    qtbot, tmp_path: Path, monkeypatch, auto_msgbox
):
    from PySide6.QtWidgets import QMessageBox

    from core.metastore import OP_EDIT_ENTRY, MetaStore

    hpd_path = tmp_path / "s_000012.hpd"
    hpd_path.write_text("TargetModel\tBCDx36HP\n", encoding="utf-8")
    store = MetaStore(str(hpd_path))
    store.record(op=OP_EDIT_ENTRY, target_id="t1", payload={})
    store.save()

    def _loaded_store(hpd: str) -> MetaStore:
        loaded = MetaStore(hpd)
        loaded.load()
        return loaded

    monkeypatch.setattr("gui.dialogs.changes.metastore.MetaStore", _loaded_store)

    dlg = ChangesPanelDialog(hpd_path=str(hpd_path))
    qtbot.addWidget(dlg)
    dlg._table.selectRow(0)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)

    def _boom(_event_id: str) -> None:
        raise RuntimeError("revert failed")

    monkeypatch.setattr(MetaStore, "mark_reverted", _boom)
    crit: list = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: crit.append(a))
    dlg._on_revert()
    assert crit


def test_uniden_tools_dialog_launch_and_install(
    qtbot, monkeypatch, auto_msgbox
):
    import sys

    from PySide6.QtWidgets import QMessageBox

    from core.uniden_tools import UnidenTool

    monkeypatch.setattr(sys, "platform", "win32")

    installed = UnidenTool(
        tool_id="bt885_update_manager",
        display_name="BT885 Update Manager",
        scanner_family="BearTracker 885",
        exe_path=r"C:\fake\UpdateManager.exe",
        version="1.0",
        installed=True,
        bundled_installer=r"C:\fake\setup.exe",
    )
    missing = UnidenTool(
        tool_id="bcdx36hp_sentinel",
        display_name="Sentinel",
        scanner_family="SDS",
        installed=False,
    )

    monkeypatch.setattr(
        "gui.dialogs.uniden_tools.uniden_tools.detect_installed_tools",
        lambda: [installed, missing],
    )
    launched: list = []
    monkeypatch.setattr(
        "gui.dialogs.uniden_tools.uniden_tools.run_tool",
        lambda tool: launched.append(tool.tool_id),
    )
    installed_runs: list = []
    monkeypatch.setattr(
        "gui.dialogs.uniden_tools.uniden_tools.install_tool",
        lambda tool, wait=False: installed_runs.append((tool.tool_id, wait)),
    )

    dlg = UnidenToolsDialog()
    qtbot.addWidget(dlg)
    assert dlg._table.rowCount() == 2

    dlg._table.selectRow(0)
    dlg._on_launch()
    assert launched == ["bt885_update_manager"]

    dlg._table.selectRow(1)
    informed: list = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: informed.append(a))
    dlg._on_launch()
    assert informed

    dlg._table.selectRow(0)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    dlg._on_install()
    assert installed_runs == [("bt885_update_manager", False)]


def test_uniden_tools_dialog_install_without_bundled_installer(
    qtbot, monkeypatch, auto_msgbox
):
    import sys

    from PySide6.QtWidgets import QMessageBox

    from core.uniden_tools import UnidenTool

    monkeypatch.setattr(sys, "platform", "win32")

    tool = UnidenTool(
        tool_id="bt885_update_manager",
        display_name="BT885 Update Manager",
        scanner_family="BearTracker 885",
        installed=True,
    )
    monkeypatch.setattr(
        "gui.dialogs.uniden_tools.uniden_tools.detect_installed_tools",
        lambda: [tool],
    )
    dlg = UnidenToolsDialog()
    qtbot.addWidget(dlg)
    dlg._table.selectRow(0)
    informed: list = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: informed.append(a))
    dlg._on_install()
    assert informed


def test_uniden_tools_dialog_launch_failure(
    qtbot, monkeypatch, auto_msgbox
):
    import sys

    from PySide6.QtWidgets import QMessageBox

    from core.uniden_tools import UnidenTool

    monkeypatch.setattr(sys, "platform", "win32")

    tool = UnidenTool(
        tool_id="bt885_update_manager",
        display_name="BT885 Update Manager",
        scanner_family="BearTracker 885",
        exe_path=r"C:\fake\UpdateManager.exe",
        installed=True,
    )
    monkeypatch.setattr(
        "gui.dialogs.uniden_tools.uniden_tools.detect_installed_tools",
        lambda: [tool],
    )

    def _boom(_tool) -> None:
        raise RuntimeError("launch failed")

    monkeypatch.setattr(
        "gui.dialogs.uniden_tools.uniden_tools.run_tool",
        _boom,
    )
    crit: list = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: crit.append(a))
    dlg = UnidenToolsDialog()
    qtbot.addWidget(dlg)
    dlg._table.selectRow(0)
    dlg._on_launch()
    assert crit


def test_profile_snapshots_list_and_selection(qtbot, tmp_path: Path, monkeypatch):
    from gui.dialogs import profile_snapshots as ps
    from gui.dialogs.profile_snapshots import list_snapshots, take_snapshot

    card = tmp_path / "card"
    bcd = card / "BCDx36HP"
    bcd.mkdir(parents=True)
    (bcd / "scanner.inf").write_text("x", encoding="utf-8")
    monkeypatch.setattr(ps, "_snapshots_root", lambda: tmp_path / "snaps")

    snap = take_snapshot(card, "uniden_sds100", "test", notes="note")
    assert list_snapshots("uniden_sds100")[0].id == snap.id

    dlg = ProfileSnapshotsDialog(scanner_profile_id="uniden_sds100", card_root=card)
    qtbot.addWidget(dlg)
    dlg._list.setCurrentRow(0)
    dlg._on_selection()
    assert dlg._notes.toPlainText() == "note"


def test_profile_snapshots_root_non_windows(monkeypatch, tmp_path: Path):
    from gui.dialogs import profile_snapshots as ps

    monkeypatch.setattr(ps.sys, "platform", "darwin")
    assert "Application Support" in str(ps._snapshots_root())

    monkeypatch.setattr(ps.sys, "platform", "linux")
    xdg_home = tmp_path / "xdg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_home))
    assert ps._snapshots_root().as_posix().endswith("scanner-manager/snapshots")


def test_profile_snapshots_list_skips_bad_entries(tmp_path: Path, monkeypatch):
    from gui.dialogs import profile_snapshots as ps

    base = tmp_path / "snaps" / "uniden_sds100"
    bad_dir = base / "bad"
    bad_dir.mkdir(parents=True)
    (bad_dir / "snapshot.json").write_text("{not json", encoding="utf-8")
    (base / "readme.txt").write_text("skip me", encoding="utf-8")
    monkeypatch.setattr(ps, "_snapshots_root", lambda: tmp_path / "snaps")
    assert ps.list_snapshots("uniden_sds100") == []


def test_profile_snapshots_take_without_card(qtbot, auto_msgbox):
    dlg = ProfileSnapshotsDialog(scanner_profile_id="uniden_sds100", card_root=None)
    qtbot.addWidget(dlg)
    dlg._on_take()
    assert dlg._list.count() == 0


def test_profile_snapshots_restore_and_delete_cancel(
    qtbot, tmp_path: Path, monkeypatch, auto_msgbox
):
    from PySide6.QtWidgets import QMessageBox

    from gui.dialogs import profile_snapshots as ps

    card = tmp_path / "card"
    bcd = card / "BCDx36HP"
    bcd.mkdir(parents=True)
    (bcd / "scanner.inf").write_text("orig", encoding="utf-8")
    monkeypatch.setattr(ps, "_snapshots_root", lambda: tmp_path / "snaps")
    ps.take_snapshot(card, "uniden_sds100", "keep")

    dlg = ProfileSnapshotsDialog(scanner_profile_id="uniden_sds100", card_root=card)
    qtbot.addWidget(dlg)
    dlg._list.setCurrentRow(0)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.No)
    dlg._on_restore()
    dlg._on_delete()
    assert dlg._list.count() == 1


def test_report_issue_crash_log_helpers(tmp_path: Path, monkeypatch):
    from gui.dialogs import report_issue as ri

    monkeypatch.setattr(ri.sys, "platform", "darwin")
    assert "Logs" in str(ri._crash_log_dir())

    monkeypatch.setattr(ri.sys, "platform", "linux")
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    assert ri._crash_log_dir().name == "crash"

    missing = tmp_path / "missing"
    monkeypatch.setattr(ri, "_crash_log_dir", lambda: missing)
    assert ri.find_latest_crash_log() is None


def test_report_issue_read_app_version_fallback(monkeypatch):
    import builtins

    from gui.dialogs.report_issue import _read_app_version

    real_import = builtins.__import__

    def _block_metadata(name, *args, **kwargs):
        if name == "importlib.metadata":
            raise ImportError("blocked")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _block_metadata)
    assert _read_app_version() == "dev"


def test_report_issue_dialog_copy_open_and_crash_log(
    qtbot, tmp_path: Path, monkeypatch, auto_msgbox
):
    from PySide6.QtWidgets import QApplication

    from gui.dialogs import report_issue as ri

    crash_dir = tmp_path / "crash"
    crash_dir.mkdir()
    log_path = crash_dir / "crash-20260101.log"
    log_path.write_text("traceback line", encoding="utf-8")
    monkeypatch.setattr(ri, "_crash_log_dir", lambda: crash_dir)

    opened: list = []
    monkeypatch.setattr(ri.webbrowser, "open", lambda url: opened.append(url))

    dlg = ReportIssueDialog()
    qtbot.addWidget(dlg)
    assert dlg._include_crash.isEnabled()
    dlg._description.setPlainText("Something broke badly")
    dlg._on_copy()
    clipboard = QApplication.clipboard().text()
    assert "Something broke badly" in clipboard
    assert "traceback line" in clipboard
    dlg._on_open()
    assert opened and "github.com" in opened[0]


def test_report_issue_dialog_no_crash_log(qtbot, monkeypatch):
    from gui.dialogs import report_issue as ri

    monkeypatch.setattr(ri, "find_latest_crash_log", lambda: None)
    dlg = ReportIssueDialog()
    qtbot.addWidget(dlg)
    assert not dlg._include_crash.isEnabled()
    assert "no crash log" in dlg._include_crash.text().lower()


def test_report_issue_crash_log_read_failure(qtbot, tmp_path: Path, monkeypatch):
    from gui.dialogs import report_issue as ri

    crash_dir = tmp_path / "crash"
    crash_dir.mkdir()
    log_path = crash_dir / "crash-bad.log"
    log_path.write_text("x", encoding="utf-8")
    monkeypatch.setattr(ri, "_crash_log_dir", lambda: crash_dir)

    dlg = ReportIssueDialog()
    qtbot.addWidget(dlg)

    class _UnreadableLog:
        name = "crash-bad.log"

        def read_text(self, *args, **kwargs):
            raise OSError("denied")

    dlg._latest_crash = _UnreadableLog()
    dlg._include_crash.setChecked(True)
    body = dlg._build_body()
    assert "could not read crash log" in body


def test_update_available_dialog_with_release_notes(qtbot):
    from core.app_updater import UpdateInfo

    info = UpdateInfo(
        tag="v0.11.0",
        version="0.11.0",
        body="  Release notes here  ",
        html_url="https://example.com/release",
    )
    dlg = UpdateAvailableDialog(
        info=info, current_version="0.10.0", mode=UpdateAvailableDialog.MODE_AVAILABLE
    )
    qtbot.addWidget(dlg)
    notes = dlg.findChild(QTextEdit)
    assert notes is not None
    assert "Release notes here" in notes.toPlainText()


def test_update_available_dialog_update_now_and_release_page(
    qtbot, monkeypatch, auto_msgbox
):
    from core.app_updater import UpdateInfo

    opened: list = []
    monkeypatch.setattr(
        "gui.dialogs.update_available.webbrowser.open", lambda url: opened.append(url)
    )
    info = UpdateInfo(
        tag="v0.11.0",
        version="0.11.0",
        body="notes",
        html_url="https://example.com/release",
    )
    dlg = UpdateAvailableDialog(
        info=info, current_version="0.10.0", mode=UpdateAvailableDialog.MODE_AVAILABLE
    )
    qtbot.addWidget(dlg)
    dlg._on_update_now()
    assert opened

    opened.clear()
    dlg._on_open_release()
    assert opened == ["https://example.com/release"]


def test_update_available_dialog_update_now_windows_frozen(
    qtbot, monkeypatch, auto_msgbox
):
    import gui.dialogs.update_available as ua
    from core.app_updater import UpdateInfo

    opened: list = []
    monkeypatch.setattr(ua.webbrowser, "open", lambda url: opened.append(url))
    monkeypatch.setattr(ua.sys, "platform", "win32")
    monkeypatch.setattr(ua.sys, "frozen", True, raising=False)

    info = UpdateInfo(
        tag="v0.11.0",
        version="0.11.0",
        html_url="https://example.com/frozen",
    )
    dlg = UpdateAvailableDialog(
        info=info, current_version="0.10.0", mode=UpdateAvailableDialog.MODE_AVAILABLE
    )
    qtbot.addWidget(dlg)
    dlg._on_update_now()
    assert opened == ["https://example.com/frozen"]


def test_update_available_dialog_update_now_linux_frozen(
    qtbot, monkeypatch, auto_msgbox
):
    import gui.dialogs.update_available as ua
    from core.app_updater import UpdateInfo

    opened: list = []
    applied: list = []
    exits: list = []
    monkeypatch.setattr(ua.webbrowser, "open", lambda url: opened.append(url))
    monkeypatch.setattr(ua.sys, "platform", "linux")
    monkeypatch.setattr(ua.sys, "frozen", True, raising=False)
    monkeypatch.setattr(ua.updater, "is_running_as_appimage", lambda: False)
    monkeypatch.setattr(
        ua.updater,
        "frozen_executable_path",
        lambda: Path("/opt/ScannerManager"),
    )
    monkeypatch.setattr(
        ua.updater,
        "install_linux_update_from_release",
        lambda info, current, **kw: applied.append((info.version, str(current))) or Path("/tmp/swap.sh"),
    )
    monkeypatch.setattr(ua.os, "_exit", lambda code: exits.append(code))

    info = UpdateInfo(
        tag="v0.12.0",
        version="0.12.0",
        html_url="https://example.com/linux",
    )
    dlg = UpdateAvailableDialog(
        info=info, current_version="0.11.0", mode=UpdateAvailableDialog.MODE_AVAILABLE
    )
    qtbot.addWidget(dlg)
    dlg._on_update_now()
    assert applied == [("0.12.0", str(Path("/opt/ScannerManager")))]
    assert not opened
    assert exits == [0]


def test_update_available_dialog_update_now_linux_appimage(
    qtbot, monkeypatch, auto_msgbox
):
    import gui.dialogs.update_available as ua
    from core.app_updater import UpdateInfo

    opened: list = []
    monkeypatch.setattr(ua.webbrowser, "open", lambda url: opened.append(url))
    monkeypatch.setattr(ua.sys, "platform", "linux")
    monkeypatch.setattr(ua.sys, "frozen", True, raising=False)
    monkeypatch.setattr(ua.updater, "is_running_as_appimage", lambda: True)
    monkeypatch.setattr(
        ua.updater,
        "install_linux_update_from_release",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not install")),
    )

    info = UpdateInfo(
        tag="v0.12.0",
        version="0.12.0",
        html_url="https://example.com/appimage",
    )
    dlg = UpdateAvailableDialog(
        info=info, current_version="0.11.0", mode=UpdateAvailableDialog.MODE_AVAILABLE
    )
    qtbot.addWidget(dlg)
    dlg._on_update_now()
    assert opened == ["https://example.com/appimage"]


def test_update_available_dialog_update_now_without_info(qtbot, monkeypatch):
    from core.app_updater import UpdateInfo

    dlg = UpdateAvailableDialog(
        info=UpdateInfo(tag="v0.11.0", version="0.11.0"),
        current_version="0.10.0",
        mode=UpdateAvailableDialog.MODE_AVAILABLE,
    )
    qtbot.addWidget(dlg)
    dlg._info = None
    accepted: list = []
    monkeypatch.setattr(dlg, "accept", lambda: accepted.append(True))
    dlg._on_update_now()
    assert accepted
