"""Smoke tests for the Qt shell (Phases 1+).

These tests exercise the structural wiring only (the window has a
device selector, the docks exist, switching device fires the
profile-change signal). Full per-dock behavior is covered by
phase-specific test modules.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.qt

# Headless: pytest-qt auto-discovers via setuptools entry points, so
# we just need to set the offscreen platform before any Qt classes
# import. Skip the whole module if PySide6 is missing (legacy envs).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PySide6 = pytest.importorskip("PySide6")  # noqa: N816
pytest.importorskip("pytestqt")

from PySide6.QtWidgets import QDockWidget  # noqa: E402

from core.device_manager import Device, DeviceManager  # noqa: E402
from gui.main_window import _LIVE_PAGE, _STORAGE_PAGE, MainWindow  # noqa: E402


@pytest.fixture
def tmp_devices(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point DeviceManager at a tmp file so test runs don't mutate
    the real data/devices.json."""
    target = tmp_path / "devices.json"
    monkeypatch.setattr(
        "core.device_manager._default_devices_path", lambda: target
    )
    return target


def test_main_window_boots_with_no_devices(qtbot, tmp_devices: Path) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    assert window.windowTitle() == "Scanner Manager"
    # The three persistent dock widgets exist (header excluded - it's a
    # fake dock; the log lives in a standalone window since v0.10.1).
    dock_names = {d.objectName() for d in window.findChildren(QDockWidget)}
    assert "firmware_dock" in dock_names
    assert window._mode_stack is not None
    assert window._live_host is not None
    # The log view persists as a child widget even when the standalone
    # window isn't open, so messages keep accumulating.
    assert window._log_view is not None


def test_main_window_swaps_active_profile_on_device_change(
    qtbot, tmp_devices: Path
) -> None:
    # Pre-seed two devices on disk
    mgr = DeviceManager(devices_path=tmp_devices)
    bt = Device.make("uniden_bt885", "BT885 - Truck")
    sds = Device.make("uniden_sds100", "SDS100 - Home")
    mgr.add_device(bt)
    mgr.add_device(sds)

    window = MainWindow()
    qtbot.addWidget(window)

    # Initial selection should be the default (first added = bt)
    assert window._current_device is not None
    assert window._current_device.scanner_profile_id == "uniden_bt885"

    # BT885 boots into Storage-only central page.
    assert window._mode_stack.currentIndex() == _STORAGE_PAGE

    # Switch to SDS100 — Live page becomes central when mode is Live.
    window._header.select_device(sds.id)
    assert window._current_device.scanner_profile_id == "uniden_sds100"
    assert window._mode_stack.currentIndex() == _LIVE_PAGE


def test_header_no_device_disables_combo(qtbot, tmp_devices: Path) -> None:
    from gui.header import HeaderBar
    mgr = DeviceManager(devices_path=tmp_devices)
    header = HeaderBar(mgr)
    qtbot.addWidget(header)
    assert not header._combo.isEnabled()
    assert "No devices configured" in header._combo.currentText()


def test_header_emits_signal_on_device_change(qtbot, tmp_devices: Path) -> None:
    mgr = DeviceManager(devices_path=tmp_devices)
    bt = Device.make("uniden_bt885", "BT885")
    sds = Device.make("uniden_sds100", "SDS")
    mgr.add_device(bt)
    mgr.add_device(sds)

    from gui.header import HeaderBar
    header = HeaderBar(mgr)
    qtbot.addWidget(header)

    with qtbot.waitSignal(header.deviceChanged, timeout=1000) as blocker:
        header.select_device(sds.id)
    received = blocker.args[0]
    assert received.id == sds.id


def test_mode_switcher_gates_live_and_storage_docks(
    qtbot, tmp_devices: Path
) -> None:
    """Verify mode stack: Live shows full-width live surface; Storage shows editor."""
    mgr = DeviceManager(devices_path=tmp_devices)
    sds = Device.make("uniden_sds100", "SDS100 - Test")
    mgr.add_device(sds)

    window = MainWindow()
    qtbot.addWidget(window)
    window._header.select_device(sds.id)

    # Default for an SDS100 device with connection_mode="auto" should
    # be Live (serial-capable scanners boot into the first supported
    # mode, which is "live").
    assert window._current_connection_mode == "live"
    assert window._mode_stack.currentIndex() == _LIVE_PAGE
    assert window._mode_stack.currentWidget() is window._live_host
    assert window._mode_stack.currentWidget() is not window._editor_dock
    assert window._save_action.isEnabled() is False
    assert window._firmware_window_action.isEnabled() is False
    _assert_no_right_side_live_docks(window)

    window._on_connection_mode_changed("storage")
    assert window._current_connection_mode == "storage"
    assert window._mode_stack.currentIndex() == _STORAGE_PAGE
    assert window._mode_stack.currentWidget() is window._editor_dock
    assert window._mode_stack.currentWidget() is not window._live_host
    assert window._save_action.isEnabled() is True
    assert window._firmware_window_action.isEnabled() is True
    _assert_no_right_side_live_docks(window)

    # Persistence: the device's connection_mode field reflects the
    # change so the next launch boots into the same mode. Reload from
    # disk via a fresh manager so we read what was actually written.
    fresh_mgr = DeviceManager(devices_path=tmp_devices)
    sds_after = fresh_mgr.get_device(sds.id)
    assert sds_after.connection_mode == "storage"


def _assert_no_right_side_live_docks(window: MainWindow) -> None:
    """Live/Streaming must be central tabs, not resurrected right docks."""
    dock_names = {d.objectName() for d in window.findChildren(QDockWidget)}
    assert "live_dock" not in dock_names
    assert "streaming_dock" not in dock_names


def test_bt885_clamped_to_storage_only(qtbot, tmp_devices: Path) -> None:
    """BearTracker 885 doesn't expose serial mode at all, so the
    mode switcher must clamp to Storage even if the persisted value
    were Live (corrupted state on disk, etc.).
    """
    mgr = DeviceManager(devices_path=tmp_devices)
    bt = Device.make("uniden_bt885", "BT885 - Truck")
    bt.connection_mode = "live"  # impossible but persisted somehow
    mgr.add_device(bt)

    window = MainWindow()
    qtbot.addWidget(window)
    window._header.select_device(bt.id)

    # Live is not in supported_connection_modes() for BT885, so the
    # switcher falls back to the first supported mode = "storage".
    assert window._current_connection_mode == "storage"
    assert window._mode_stack.currentIndex() == _STORAGE_PAGE


def test_firmware_window_opens_and_returns_widget(
    qtbot, tmp_devices: Path
) -> None:
    """Firmware updater opens as a standalone window from Storage
    mode and returns its child widget back to the hidden bottom
    dock on close so state persists across reopens.
    """
    mgr = DeviceManager(devices_path=tmp_devices)
    sds = Device.make("uniden_sds100", "SDS100 - Home")
    mgr.add_device(sds)

    window = MainWindow()
    qtbot.addWidget(window)
    window._header.select_device(sds.id)
    window._on_connection_mode_changed("storage")

    assert window._firmware_window is None
    window._on_show_firmware_window()
    assert window._firmware_window is not None
    fw_window = window._firmware_window
    qtbot.addWidget(fw_window)
    # The dock widget should now be parented to the standalone window.
    assert window._firmware_dock.parent() is fw_window
    fw_window.close()
    # Widget returns to the original bottom-dock home so the next
    # open keeps its state.
    assert window._firmware_dock.parent() is window._firmware_dock_container


def test_status_light_state_transitions(qtbot) -> None:
    from gui.header import StatusLight
    light = StatusLight()
    qtbot.addWidget(light)
    assert light.state() == "unknown"
    for state in ("red", "yellow", "green"):
        light.set_state(state)
        assert light.state() == state
    light.set_state("nonsense")
    assert light.state() == "unknown"


def test_main_window_coverage_not_in_editor_dock(
    qtbot, tmp_devices: Path, tmp_path: Path
) -> None:
    """Coverage lives on MainWindow hidden host, not inside EditorDock."""
    from core.device_manager import Device, DeviceManager
    from gui.editor.coverage_panel import CoveragePanel
    from gui.main_window import MainWindow

    mgr = DeviceManager(devices_path=tmp_devices)
    bt = Device.make("uniden_bt885", "BT885", sd_card_path=str(tmp_path))
    mgr.add_device(bt)

    window = MainWindow()
    qtbot.addWidget(window)
    window._header.select_device(bt.id)

    assert window.coverage_panel() is window._coverage_panel
    assert window._coverage_panel.parent() is window._hidden_coverage_host
    assert window._editor_dock.findChildren(CoveragePanel) == []


def _menu_action_texts(window: MainWindow, title: str) -> list[str]:
    """Collect submenu action labels without retaining a QMenu reference."""
    for action in window.menuBar().actions():
        label = action.text().replace("&", "")
        if label == title:
            menu = action.menu()
            assert menu is not None, f"Top-level action {title!r} has no submenu"
            return [a.text().replace("&", "") for a in menu.actions()]
    raise AssertionError(f"Menu {title!r} not found")


def test_coverage_action_under_view_menu(qtbot, tmp_devices: Path) -> None:
    """Coverage / heatmap opens from View menu, not Tools."""
    mgr = DeviceManager(devices_path=tmp_devices)
    bt = Device.make("uniden_bt885", "BT885")
    mgr.add_device(bt)

    window = MainWindow()
    qtbot.addWidget(window)
    # Native menu bar on Windows drops QMenu wrappers in offscreen tests.
    window.menuBar().setNativeMenuBar(False)
    window._header.select_device(bt.id)

    view_texts = _menu_action_texts(window, "View")
    assert "Coverage / heatmap…" in view_texts
    assert "Log window…" in view_texts

    tools_texts = _menu_action_texts(window, "Tools")
    assert not any("Coverage" in t or "heatmap" in t for t in tools_texts)


def test_main_window_log_and_coverage_windows(qtbot, tmp_devices: Path, monkeypatch) -> None:
    from PySide6.QtWidgets import QMessageBox

    mgr = DeviceManager(devices_path=tmp_devices)
    bt = Device.make("uniden_bt885", "BT885")
    mgr.add_device(bt)

    window = MainWindow()
    qtbot.addWidget(window)
    window._header.select_device(bt.id)

    window._on_show_log_window()
    assert window._log_window is not None
    window._log_window.close()
    window._on_log_window_closed()
    assert window._log_window is None

    window._on_show_log_window()
    window._on_show_log_window()
    assert window._log_window is not None

    window._on_show_coverage_window()
    assert window._coverage_window is not None
    window._coverage_window.close()
    window._on_coverage_window_closed()
    assert window._coverage_window is None

    monkeypatch.setattr(QMessageBox, "about", lambda *a, **k: None)
    window._on_about()


def test_main_window_live_telemetry_bridge(qtbot, tmp_devices: Path) -> None:
    from scanner_drivers.serial_main import GlgEvent, GsiSnapshot
    from scanner_drivers.serial_sub import WaterfallFrame

    mgr = DeviceManager(devices_path=tmp_devices)
    sds = Device.make("uniden_sds100", "SDS")
    mgr.add_device(sds)

    window = MainWindow()
    qtbot.addWidget(window)
    window._header.select_device(sds.id)
    window._on_connection_mode_changed("live")

    window._live_dock.gsiUpdated.emit(GsiSnapshot(mode="Scan", system_name="BridgeTest"))
    window._live_dock.glgUpdated.emit(GlgEvent(is_receiving=True, frq="154445000"))
    window._live_dock.waterfallUpdated.emit(WaterfallFrame(samples=[1, 2, 3, 4]))


def test_main_window_menu_dialogs_smoke(qtbot, tmp_devices: Path, monkeypatch) -> None:
    from PySide6.QtWidgets import QDialog, QInputDialog, QMessageBox

    mgr = DeviceManager(devices_path=tmp_devices)
    bt = Device.make("uniden_bt885", "BT885")
    mgr.add_device(bt)

    window = MainWindow()
    qtbot.addWidget(window)
    window._header.select_device(bt.id)

    monkeypatch.setattr(QMessageBox, "about", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("", False))

    class _InstantDialog(QDialog):
        def exec(self):
            return 0

    monkeypatch.setattr(
        "gui.main_window.WorkspaceManagerDialog",
        lambda *a, **k: _InstantDialog(),
    )
    monkeypatch.setattr(
        "gui.main_window.ProfileSnapshotsDialog",
        lambda *a, **k: _InstantDialog(),
    )
    monkeypatch.setattr(
        "gui.main_window.ChangesPanelDialog",
        lambda *a, **k: _InstantDialog(),
    )
    monkeypatch.setattr(
        "gui.main_window.CityManagerDialog",
        lambda *a, **k: _InstantDialog(),
    )
    monkeypatch.setattr(
        "gui.main_window.UnidenToolsDialog",
        lambda *a, **k: _InstantDialog(),
    )
    monkeypatch.setattr(
        "gui.main_window.ReportIssueDialog",
        lambda *a, **k: _InstantDialog(),
    )

    from gui.dialogs.update_available import UpdateAvailableDialog as _RealUpdateDlg

    class _FakeUpdateDlg:
        MODE_OFFLINE = _RealUpdateDlg.MODE_OFFLINE
        MODE_AVAILABLE = _RealUpdateDlg.MODE_AVAILABLE
        MODE_CURRENT = _RealUpdateDlg.MODE_CURRENT

        def __init__(self, info=None, current_version="", mode=None, parent=None):
            self.info = info
            self.mode = mode

        def exec(self):
            return 0

    monkeypatch.setattr(
        "gui.main_window.UpdateAvailableDialog",
        _FakeUpdateDlg,
    )
    monkeypatch.setattr(
        "core.app_updater.check_for_update",
        lambda: None,
    )

    window._on_workspaces()
    window._on_snapshots()
    window._on_changes()
    window._on_city_manager()
    window._on_uniden_tools()
    window._on_report_issue()
    window._on_check_updates()


def test_main_window_add_manage_and_firmware_menu(
    qtbot, tmp_devices: Path, monkeypatch, tmp_path: Path
) -> None:
    from PySide6.QtWidgets import QDialog

    class _FakeAddDlg:
        accepted = QDialog.DialogCode.Accepted
        Accepted = accepted  # Qt DialogCode alias for main_window comparison

        def __init__(self, dm, parent=None):
            self._dm = dm
            self.created_device = Device.make(
                "uniden_bt885", "NewOne", sd_card_path=str(tmp_path)
            )

        def exec(self):
            self._dm.add_device(self.created_device)
            return self.accepted

    class _FakeManageDlg:
        class _Sig:
            def connect(self, _cb):
                return None  # stub signal connector

        devices_changed = _Sig()
        devicesChanged = devices_changed  # Qt signal alias for main_window wiring

        def __init__(self, _dm, parent=None):
            """Test double; arguments unused."""

        def exec(self):
            return 0

    monkeypatch.setattr("gui.main_window.AddDeviceDialog", _FakeAddDlg)
    monkeypatch.setattr("gui.main_window.ManageDevicesDialog", _FakeManageDlg)

    mgr = DeviceManager(devices_path=tmp_devices)
    sds = Device.make("uniden_sds100", "SDS")
    mgr.add_device(sds)

    window = MainWindow()
    qtbot.addWidget(window)
    window._header.select_device(sds.id)
    window._on_add_device()
    window._on_manage_devices()
    window._on_update_firmware()
    assert window._firmware_window is not None
    window._firmware_window.close()


def test_main_window_close_event_accepts(qtbot, tmp_devices: Path) -> None:
    from PySide6.QtGui import QCloseEvent

    window = MainWindow()
    qtbot.addWidget(window)
    event = QCloseEvent()
    window.closeEvent(event)
    assert event.isAccepted()


def test_main_window_close_event_can_abort(qtbot, tmp_devices: Path, monkeypatch) -> None:
    from PySide6.QtGui import QCloseEvent

    window = MainWindow()
    qtbot.addWidget(window)
    monkeypatch.setattr(window._editor_dock, "request_close", lambda: False)
    event = QCloseEvent()
    window.closeEvent(event)
    assert not event.isAccepted()
