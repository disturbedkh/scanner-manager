"""Tests for workspace loading and data-source indicators."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from core.device_manager import Device, DeviceManager
from gui.dialogs.workspaces import Workspace, WorkspaceManagerDialog
from gui.main_window import MainWindow

pytestmark = pytest.mark.qt


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _write_devices(path: Path, label: str = "Test Scanner") -> None:
    device = Device.make("uniden_bt885", label)
    payload = {
        "schema_version": 1,
        "devices": [device.to_dict()],
        "default_device_id": device.id,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def test_device_manager_reload_from(tmp_path: Path) -> None:
    default = tmp_path / "default.json"
    alt = tmp_path / "travel.json"
    _write_devices(default, "Home")
    _write_devices(alt, "Travel")

    mgr = DeviceManager(devices_path=default)
    assert mgr.get_default().label == "Home"

    mgr.reload_from(alt)
    assert mgr.path == alt
    assert mgr.get_default().label == "Travel"


def test_main_window_applies_workspace(qtbot, tmp_path: Path, monkeypatch) -> None:
    default_devices = tmp_path / "default.json"
    travel_devices = tmp_path / "travel.json"
    _write_devices(default_devices, "Default device")
    _write_devices(travel_devices, "Travel device")

    monkeypatch.setattr(
        "gui.main_window._default_devices_path",
        lambda: default_devices,
    )
    monkeypatch.setattr(
        "core.device_manager._default_devices_path",
        lambda: default_devices,
    )

    window = MainWindow()
    qtbot.addWidget(window)

    ws = Workspace(name="Travel", devices_path=str(travel_devices))
    window._apply_workspace(ws)

    assert window._active_workspace is not None
    assert window._active_workspace.name == "Travel"
    assert window._device_manager.path == travel_devices
    assert window._device_manager.get_default().label == "Travel device"
    assert "Workspace: Travel" in window._header._source_label.text()
    assert window._editor_dock._workspace_name == "Travel"


def test_main_window_clears_workspace(qtbot, tmp_path: Path, monkeypatch) -> None:
    default_devices = tmp_path / "default.json"
    travel_devices = tmp_path / "travel.json"
    _write_devices(default_devices, "Default device")
    _write_devices(travel_devices, "Travel device")

    monkeypatch.setattr(
        "gui.main_window._default_devices_path",
        lambda: default_devices,
    )
    monkeypatch.setattr(
        "core.device_manager._default_devices_path",
        lambda: default_devices,
    )

    window = MainWindow()
    qtbot.addWidget(window)
    window._apply_workspace(
        Workspace(name="Travel", devices_path=str(travel_devices))
    )
    window._clear_workspace()

    assert window._active_workspace is None
    assert window._device_manager.path == default_devices
    assert window._header._source_label.text() == "Device list: default"
    assert window._editor_dock._workspace_name is None


def test_workspace_dialog_load_emits_signal(
    qtbot, tmp_path: Path,
) -> None:
    devices = tmp_path / "devices.json"
    _write_devices(devices)
    ws_path = tmp_path / "ws.json"

    dlg = WorkspaceManagerDialog(path=ws_path)
    qtbot.addWidget(dlg)
    dlg._workspaces.append(
        Workspace(name="Home", devices_path=str(devices))
    )
    dlg._refresh_list()
    dlg._list.setCurrentRow(0)

    loaded = []
    dlg.workspaceLoaded.connect(loaded.append)
    dlg._on_load()
    assert loaded and loaded[0].name == "Home"
