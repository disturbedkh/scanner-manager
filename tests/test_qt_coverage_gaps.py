"""Smoke tests for low-coverage Qt GUI modules.

Each test instantiates a widget or dialog and exercises key methods
without touching real serial hardware or the user's devices.json.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.qt

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PySide6 = pytest.importorskip("PySide6")  # noqa: N816
pytest.importorskip("pytestqt")

from PySide6.QtCore import QCoreApplication  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.device_manager import Device, DeviceManager  # noqa: E402
from gui.devices_dialog import AddDeviceDialog, ManageDevicesDialog  # noqa: E402
from gui.header import HeaderBar, ModeSwitcher  # noqa: E402
from scanner_profiles import get_profile, set_active_profile  # noqa: E402
from tests._qt_fakes import (  # noqa: E402
    FakeMainWindow,
    FakeMainWindowNoOp,
    FakeQApplication,
    FakeQApplicationExec42,
    FakeQt5,
    fake_qapplication_recording,
)

_BT885_CFG = (
    "TargetModel\tBCDx36HP\n"
    "FormatVersion\t1.00\n"
    "DateModified\t04/07/2024 17:00:01\n"
    "StateInfo\tStateId=12\tCountryId=1\tFlorida\tFL\n"
)

_BT885_HPD = (
    "TargetModel\tBCDx36HP\n"
    "FormatVersion\t1.00\n"
    "DateModified\t04/07/2024 17:00:01\n"
    "Conventional\tCountyId=86\tStateId=12\tMiami-Dade\tOff\t25.7617\t-80.1918\t10.0\tCircle\n"
    "C-Group\tCGroupId=1\tCountyId=86\tDispatch\tOff\t25.7617\t-80.1918\t5.0\tCircle\n"
    "C-Freq\tCFreqId=1\tCGroupId=1\tFire Dispatch\tOff\t154445000\tFM\t100.0\t3\n"
    "C-Freq\tCFreqId=2\tCGroupId=1\tEMS Dispatch\tOff\t155865000\tFM\t\t4\n"
)


@pytest.fixture
def tmp_devices(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point DeviceManager at a tmp file so tests stay hermetic."""
    target = tmp_path / "devices.json"
    monkeypatch.setattr(
        "core.device_manager._default_devices_path", lambda: target
    )
    return target


@pytest.fixture
def card_root(tmp_path: Path) -> Path:
    root = tmp_path / "card"
    hpdb = root / "BCDx36HP" / "HPDB"
    hpdb.mkdir(parents=True)
    (root / "BCDx36HP" / "scanner.inf").write_text(
        "TargetModel\tBCDx36HP\nFormatVersion\t1.00\nScanner\tBT885-SCN\t1\t1.00\t01\t\t1.00\t1.00\t0\n",
        encoding="utf-8",
    )
    (hpdb / "hpdb.cfg").write_text(_BT885_CFG, encoding="utf-8")
    (hpdb / "s_000012.hpd").write_text(_BT885_HPD, encoding="utf-8")
    return root


def _bt885_details_panel(qtbot, *, with_profile: bool = True):
    """Bt885DetailsPanel with profile wired (not the BaseDetailsPanel alias)."""
    from gui.editor.details_panel import Bt885DetailsPanel

    if with_profile:
        set_active_profile("uniden_bt885")
    panel = Bt885DetailsPanel()
    if with_profile:
        panel.set_profile(get_profile("uniden_bt885"))
    qtbot.addWidget(panel)
    return panel


# ------------------------------------------------------------------
# gui/editor/coverage_panel.py
# ------------------------------------------------------------------


def test_coverage_panel_refresh_disabled_without_force(qtbot) -> None:
    from gui.editor.coverage_panel import CoverageHeatmapWidget, CoveragePanel

    panel = CoveragePanel()
    qtbot.addWidget(panel)
    panel.set_data_source(lambda: [])
    panel.set_refresh_enabled(False)
    assert panel.refresh_from_hpdb() is False
    assert panel.refresh_from_hpdb(force=True) is True

    heat = CoverageHeatmapWidget()
    qtbot.addWidget(heat)
    heat.set_groups([])
    heat.set_groups([(25.0, -80.0, 5.0)])


def test_coverage_panel_helpers_and_refresh_with_data(qtbot) -> None:
    from types import SimpleNamespace

    from gui.editor.coverage_panel import (
        CoveragePanel,
        _coverage_items_from_hpd_files,
        _group_coverage_from_group,
        _map_center_from_items,
        _rectangle_items_for_group,
        _site_marker_item,
    )

    group = SimpleNamespace(
        lat=34.0,
        lon=-118.0,
        range_miles=5.0,
        name="Dispatch",
        entries=[SimpleNamespace(), SimpleNamespace()],
        rectangles=[(34.0, -118.0, 34.1, -117.9), (1, 2)],
    )
    pt, items = _group_coverage_from_group(group)
    assert pt == (34.0, -118.0, 2.0)
    assert items[0]["kind"] == "circle"
    assert _rectangle_items_for_group(group)[0]["kind"] == "rectangle"

    site = SimpleNamespace(lat=35.0, lon=-119.0, name="Tower")
    assert _site_marker_item(site)["label"] == "Site: Tower"
    assert _site_marker_item(SimpleNamespace(lat=None, lon=0, name="X")) is None

    center = _map_center_from_items(items)
    assert center is not None

    system = SimpleNamespace(groups=[group], sites=[site])
    hpd = SimpleNamespace(systems=[system])
    groups, map_items = _coverage_items_from_hpd_files([hpd])
    assert groups
    assert map_items

    panel = CoveragePanel()
    qtbot.addWidget(panel)
    panel.set_sim_center(40.0, -90.0)
    panel.set_data_source(lambda: [hpd])
    panel.set_refresh_enabled(True)
    assert panel.refresh_from_hpdb() is True
    panel.invalidate_map_shell()


def test_coverage_heatmap_no_pyqtgraph_placeholder(
    qtbot, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("gui.editor.coverage_panel.HAS_PYQTGRAPH", False)
    from gui.editor.coverage_panel import CoverageHeatmapWidget

    heat = CoverageHeatmapWidget()
    qtbot.addWidget(heat)
    assert heat._plot is None
    heat.set_groups([(25.0, -80.0, 1.0)])


def test_coverage_heatmap_collapsed_lat_lon_range(qtbot) -> None:
    from gui.editor.coverage_panel import HAS_PYQTGRAPH, CoverageHeatmapWidget

    if not HAS_PYQTGRAPH:
        pytest.skip("pyqtgraph required")
    heat = CoverageHeatmapWidget()
    qtbot.addWidget(heat)
    heat.set_groups([(25.0, -80.0, 1.0), (25.0, -80.0, 2.0)])


def test_coverage_map_view_no_webengine_placeholder(
    qtbot, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("gui.editor.coverage_panel.HAS_WEBENGINE", False)
    from gui.editor.coverage_panel import CoverageMapView

    map_view = CoverageMapView()
    qtbot.addWidget(map_view)
    assert map_view._view is None
    map_view.set_view(1.0, 2.0, zoom=5, items=[])


def test_coverage_map_view_webengine_shell_and_javascript(
    qtbot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    from gui.editor.coverage_panel import HAS_WEBENGINE, CoverageMapView

    if not HAS_WEBENGINE:
        pytest.skip("QtWebEngine required")

    map_view = CoverageMapView()
    qtbot.addWidget(map_view)

    js_calls: list[str] = []
    html_calls: list[str] = []

    monkeypatch.setattr(
        map_view._view,
        "page",
        lambda: SimpleNamespace(runJavaScript=js_calls.append),
    )
    monkeypatch.setattr(map_view._view, "setHtml", html_calls.append)

    map_view.invalidate_shell()
    items = [{"kind": "marker", "lat": 34.0, "lon": -118.0, "label": "A"}]
    map_view.set_view(34.0, -118.0, zoom=6, items=items)
    assert map_view._loading_shell
    assert html_calls

    map_view._on_shell_loaded(True)
    assert map_view._shell_loaded
    assert js_calls
    assert "updateCoverageData" in js_calls[0]

    map_view.set_view(35.0, -119.0, zoom=7, items=[])
    assert len(js_calls) >= 2

    map_view._on_shell_loaded(False)
    map_view._on_shell_loaded(True)


def test_coverage_map_view_shell_load_without_pending(qtbot) -> None:
    from gui.editor.coverage_panel import HAS_WEBENGINE, CoverageMapView

    if not HAS_WEBENGINE:
        pytest.skip("QtWebEngine required")

    map_view = CoverageMapView()
    qtbot.addWidget(map_view)
    map_view._pending_view = None
    map_view._shell_loaded = False
    map_view._loading_shell = True
    map_view._on_shell_loaded(True)
    assert map_view._shell_loaded
    assert not map_view._loading_shell


def test_group_coverage_from_group_skips_missing_coords() -> None:
    from types import SimpleNamespace

    from gui.editor.coverage_panel import _group_coverage_from_group

    group = SimpleNamespace(
        lat=None,
        lon=-118.0,
        range_miles=5.0,
        name="NoCoords",
        entries=[],
        rectangles=[],
    )
    assert _group_coverage_from_group(group) == (None, [])


def test_coverage_panel_refresh_without_data_source(qtbot) -> None:
    from gui.editor.coverage_panel import CoveragePanel

    panel = CoveragePanel()
    qtbot.addWidget(panel)
    assert panel.refresh_from_hpdb(force=True) is False


def test_coverage_panel_refresh_swallows_provider_error(qtbot) -> None:
    from gui.editor.coverage_panel import CoveragePanel

    panel = CoveragePanel()
    qtbot.addWidget(panel)

    def _boom() -> None:
        raise RuntimeError("provider failed")

    panel.set_data_source(_boom)
    panel.set_refresh_enabled(True)
    assert panel.refresh_from_hpdb() is True


@pytest.fixture
def loaded_hpd(card_root: Path):
    from legacy_tk.scanner_manager import HpdFile

    hpd_path = card_root / "BCDx36HP" / "HPDB" / "s_000012.hpd"
    hpd = HpdFile()
    hpd.load(str(hpd_path))
    system = hpd.systems[0]
    group = system.groups[0]
    entry = group.entries[0]
    return {
        "hpd": hpd,
        "path": str(hpd_path),
        "system": system,
        "group": group,
        "entry": entry,
    }


# ------------------------------------------------------------------
# gui/devices_dialog.py
# ------------------------------------------------------------------


def test_add_device_dialog_builds(qtbot, tmp_devices: Path) -> None:
    mgr = DeviceManager(devices_path=tmp_devices)
    dlg = AddDeviceDialog(mgr)
    qtbot.addWidget(dlg)
    assert dlg.windowTitle() == "Add Scanner Device"
    assert dlg._profile_combo.count() >= 1


def test_add_device_dialog_autodetect_empty_path(qtbot, tmp_devices: Path) -> None:
    mgr = DeviceManager(devices_path=tmp_devices)
    dlg = AddDeviceDialog(mgr)
    qtbot.addWidget(dlg)
    dlg._maybe_autodetect("")
    assert dlg._detect_label.text() == ""


def test_add_device_dialog_autodetect_unknown_path(
    qtbot, tmp_devices: Path, tmp_path: Path
) -> None:
    mgr = DeviceManager(devices_path=tmp_devices)
    dlg = AddDeviceDialog(mgr)
    qtbot.addWidget(dlg)
    dlg._maybe_autodetect(str(tmp_path / "not-a-card"))
    assert "not recognized" in dlg._detect_label.text().lower()


def test_manage_devices_dialog_empty_list(qtbot, tmp_devices: Path) -> None:
    mgr = DeviceManager(devices_path=tmp_devices)
    dlg = ManageDevicesDialog(mgr)
    qtbot.addWidget(dlg)
    assert dlg.windowTitle() == "Manage Devices"
    assert dlg._table.rowCount() == 0


def test_manage_devices_dialog_lists_devices(qtbot, tmp_devices: Path) -> None:
    mgr = DeviceManager(devices_path=tmp_devices)
    bt = Device.make("uniden_bt885", "Truck")
    mgr.add_device(bt)
    dlg = ManageDevicesDialog(mgr)
    qtbot.addWidget(dlg)
    assert dlg._table.rowCount() == 1
    assert dlg._table.item(0, 0).text() == "Truck"


# ------------------------------------------------------------------
# gui/header.py
# ------------------------------------------------------------------


def test_mode_switcher_supported_modes_and_selection(qtbot) -> None:
    switcher = ModeSwitcher()
    qtbot.addWidget(switcher)
    switcher.set_supported_modes(("storage",))
    switcher.set_current_mode("live")
    assert switcher.current_mode() == "storage"
    switcher.set_supported_modes(("live", "storage"))
    switcher.set_current_mode("live")
    assert switcher.current_mode() == "live"


def test_header_bar_firmware_and_connection_api(qtbot, tmp_devices: Path) -> None:
    mgr = DeviceManager(devices_path=tmp_devices)
    sds = Device.make("uniden_sds100", "Home")
    mgr.add_device(sds)

    header = HeaderBar(mgr)
    qtbot.addWidget(header)

    header.set_firmware_version("1.26.01", "1.03.15")
    assert "Main 1.26.01" in header._fw_label.text()
    assert "Sub 1.03.15" in header._fw_label.text()

    header.set_firmware_version(main_version="1.25.99")
    assert header._fw_label.text() == "FW: 1.25.99"

    header.set_firmware_version()
    assert header._fw_label.text() == "FW: —"

    header.set_connection_state("green", "Serial link up")
    assert header._status_light.state() == "green"
    assert "Serial link up" in header._status_label.text()

    header.set_supported_connection_modes(("storage",))
    header.set_connection_mode("live")
    assert header.current_connection_mode() == "storage"


def test_header_bar_refresh_devices_emits_signal(qtbot, tmp_devices: Path) -> None:
    mgr = DeviceManager(devices_path=tmp_devices)
    bt = Device.make("uniden_bt885", "BT885")
    mgr.add_device(bt)

    header = HeaderBar(mgr)
    qtbot.addWidget(header)

    with qtbot.waitSignal(header.deviceChanged, timeout=1000) as blocker:
        header.refresh_devices()
    assert blocker.args[0].label == "BT885"


# ------------------------------------------------------------------
# gui/editor/entry_dialog.py
# ------------------------------------------------------------------


def test_entry_edit_dialog_cfreq_builds(qtbot, loaded_hpd) -> None:
    from gui.editor.entry_dialog import EntryEditDialog

    set_active_profile("uniden_bt885")
    entry = loaded_hpd["entry"]
    dlg = EntryEditDialog(
        entry,
        loaded_hpd["hpd"],
        get_profile("uniden_bt885"),
    )
    qtbot.addWidget(dlg)
    assert "Fire Dispatch" in dlg.windowTitle()
    assert dlg._freq_spin.value() > 0


def test_group_edit_dialog_builds(qtbot, loaded_hpd) -> None:
    from gui.editor.entry_dialog import GroupEditDialog

    group = loaded_hpd["group"]
    dlg = GroupEditDialog(group, loaded_hpd["hpd"])
    qtbot.addWidget(dlg)
    assert "Dispatch" in dlg.windowTitle()
    assert dlg._name_edit.text() == "Dispatch"


def test_bulk_service_type_dialog_builds(qtbot) -> None:
    from gui.editor.entry_dialog import BulkServiceTypeDialog

    dlg = BulkServiceTypeDialog(
        "all 2 entries in 'Dispatch'",
        get_profile("uniden_bt885"),
    )
    qtbot.addWidget(dlg)
    assert dlg.selected_service_type() is not None


# ------------------------------------------------------------------
# gui/editor/details_panel.py
# ------------------------------------------------------------------


def test_details_panel_default_state(qtbot) -> None:
    from gui.editor.details_panel import BaseDetailsPanel

    panel = BaseDetailsPanel()
    qtbot.addWidget(panel)
    assert panel._title.text() == "Select a node in the tree"
    assert not panel._edit_button.isEnabled()


def test_details_panel_show_entry_payload(qtbot, loaded_hpd) -> None:
    panel = _bt885_details_panel(qtbot)

    payload = {
        "kind": "entry",
        "system": loaded_hpd["system"],
        "group": loaded_hpd["group"],
        "entry": loaded_hpd["entry"],
        "hpd_file": loaded_hpd["hpd"],
    }
    panel.show_entry(payload)
    assert "Fire Dispatch" in panel._title.text()
    assert panel._edit_button.isEnabled()
    assert panel._info_form.rowCount() >= 4


def test_details_panel_show_group_and_system(qtbot, loaded_hpd) -> None:
    panel = _bt885_details_panel(qtbot)

    group_payload = {
        "kind": "group",
        "system": loaded_hpd["system"],
        "group": loaded_hpd["group"],
        "hpd_file": loaded_hpd["hpd"],
    }
    panel.show_entry(group_payload)
    assert "Dispatch" in panel._title.text()
    assert panel._bulk_button.isEnabled()

    system_payload = {
        "kind": "system",
        "system": loaded_hpd["system"],
        "hpd_file": loaded_hpd["hpd"],
    }
    panel.show_entry(system_payload)
    assert "Miami-Dade" in panel._title.text()
    assert not panel._edit_button.isEnabled()


def test_details_panel_show_file_payload(qtbot, loaded_hpd) -> None:
    from gui.editor.details_panel import BaseDetailsPanel

    panel = BaseDetailsPanel()
    qtbot.addWidget(panel)

    file_payload = {
        "kind": "file",
        "state_id": 12,
        "path": loaded_hpd["path"],
        "hpd_file": loaded_hpd["hpd"],
    }
    panel.show_entry(file_payload)
    assert panel._title.text() == "HPDB state file"
    assert panel._info_form.rowCount() >= 2


def test_details_panel_show_none_resets(qtbot, loaded_hpd) -> None:
    panel = _bt885_details_panel(qtbot)
    panel.show_entry(
        {
            "kind": "entry",
            "system": loaded_hpd["system"],
            "group": loaded_hpd["group"],
            "entry": loaded_hpd["entry"],
            "hpd_file": loaded_hpd["hpd"],
        }
    )
    panel.show_entry(None)
    assert panel._title.text() == "Select a node in the tree"


# ------------------------------------------------------------------
# gui/app.py
# ------------------------------------------------------------------


def test_app_module_imports() -> None:
    import gui.app as app_mod

    assert callable(app_mod.main)
    assert callable(app_mod._crash_log_dir)
    assert callable(app_mod._set_app_metadata)


def test_crash_log_dir_is_writable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from gui.app import _crash_log_dir

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    log_dir = _crash_log_dir()
    assert log_dir.is_dir()
    assert log_dir.name == "crash"


def test_app_metadata_and_style(qtbot) -> None:
    from gui.app import _apply_app_style, _set_app_metadata

    app = QApplication.instance()
    assert app is not None
    _set_app_metadata()
    _apply_app_style(app)
    assert QCoreApplication.applicationName() == "Scanner Manager"
    assert QCoreApplication.applicationVersion()


def test_install_global_excepthook_replaces_hook(
    qtbot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gui.app import _install_global_excepthook

    delegated: list[tuple] = []
    monkeypatch.setattr(
        sys,
        "__excepthook__",
        lambda exc_type, exc_value, exc_tb: delegated.append(
            (exc_type, exc_value, exc_tb)
        ),
    )

    original = sys.excepthook
    _install_global_excepthook(None)
    assert sys.excepthook is not original

    sys.excepthook(KeyboardInterrupt, KeyboardInterrupt(), None)
    assert len(delegated) == 1
    assert delegated[0][0] is KeyboardInterrupt


def test_install_global_excepthook_writes_crash_log(
    qtbot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from gui.app import _install_global_excepthook

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    _install_global_excepthook(None)
    sys.excepthook(ValueError, ValueError("test"), None)
    crash_dir = tmp_path / "scanner-manager" / "crash"
    assert any(crash_dir.glob("crash-*.log"))


def test_add_device_dialog_autodetect_success(
    qtbot, tmp_devices: Path, card_root: Path, monkeypatch
) -> None:
    from scanner_profiles import get_profile

    mgr = DeviceManager(devices_path=tmp_devices)
    dlg = AddDeviceDialog(mgr)
    qtbot.addWidget(dlg)
    monkeypatch.setattr(
        "gui.devices_dialog.detect_from_card",
        lambda _p: get_profile("uniden_bt885"),
    )
    dlg._maybe_autodetect(str(card_root))
    assert "Detected:" in dlg._detect_label.text()


def test_add_device_dialog_accept_creates_device(
    qtbot, tmp_devices: Path, monkeypatch
) -> None:

    mgr = DeviceManager(devices_path=tmp_devices)
    dlg = AddDeviceDialog(mgr)
    qtbot.addWidget(dlg)
    dlg._label_edit.setText("Garage")
    dlg._path_edit.setText("C:/fake/card")
    dlg._on_accept()
    assert dlg.created_device is not None
    assert mgr.get_device(dlg.created_device.id) is not None


def test_add_device_dialog_accept_validates(qtbot, tmp_devices: Path, monkeypatch) -> None:
    from PySide6.QtWidgets import QMessageBox

    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.append(a))
    mgr = DeviceManager(devices_path=tmp_devices)
    dlg = AddDeviceDialog(mgr)
    qtbot.addWidget(dlg)
    dlg._label_edit.clear()
    dlg._on_accept()
    assert warned


def test_manage_devices_rename_and_remove(qtbot, tmp_devices: Path, monkeypatch) -> None:
    from PySide6.QtWidgets import QInputDialog, QMessageBox

    mgr = DeviceManager(devices_path=tmp_devices)
    bt = Device.make("uniden_bt885", "Truck", sd_card_path="C:/card")
    mgr.add_device(bt)

    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Garage", True))
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)

    dlg = ManageDevicesDialog(mgr)
    qtbot.addWidget(dlg)
    dlg._table.selectRow(0)
    dlg._on_rename()
    assert mgr.list_devices()[0].label == "Garage"
    dlg._table.selectRow(0)
    dlg._on_remove()
    assert mgr.list_devices() == []


def test_manage_devices_rebind_path(qtbot, tmp_devices: Path, monkeypatch, tmp_path: Path) -> None:
    from PySide6.QtWidgets import QFileDialog

    mgr = DeviceManager(devices_path=tmp_devices)
    bt = Device.make("uniden_bt885", "Truck")
    mgr.add_device(bt)
    new_path = tmp_path / "newcard"
    new_path.mkdir()
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", lambda *a, **k: str(new_path)
    )
    dlg = ManageDevicesDialog(mgr)
    qtbot.addWidget(dlg)
    dlg._table.selectRow(0)
    dlg._on_rebind()
    assert mgr.list_devices()[0].sd_card_path == str(new_path)


def test_add_device_dialog_browse_sets_path(qtbot, tmp_devices: Path, monkeypatch, tmp_path: Path) -> None:
    from PySide6.QtWidgets import QFileDialog

    mgr = DeviceManager(devices_path=tmp_devices)
    dlg = AddDeviceDialog(mgr)
    qtbot.addWidget(dlg)
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", lambda *a, **k: str(tmp_path)
    )
    dlg._on_browse()
    assert dlg._path_edit.text() == str(tmp_path)


def test_dev_mcp_attach_is_optional(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mirrors gui/app.py: dev_mcp is gated and ImportError is swallowed."""
    sentinel = object()
    monkeypatch.setitem(sys.modules, "dev_mcp", sentinel)
    monkeypatch.setenv("SCANNER_MANAGER_DEV_MCP", "1")
    err = None
    try:
        try:
            from dev_mcp import attach as _dev_attach  # type: ignore

            _dev_attach.maybe_start(None)
        except ImportError:
            pass
    except Exception as exc:  # pragma: no cover
        err = exc
    assert err is None


def test_crash_log_dir_darwin_and_linux(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from gui.app import _crash_log_dir

    monkeypatch.setattr(sys, "platform", "darwin")
    log_dir = _crash_log_dir()
    assert log_dir.is_dir()
    assert "Logs" in str(log_dir)

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    log_dir = _crash_log_dir()
    assert log_dir.is_dir()


def test_install_global_excepthook_shows_dialog_with_window(
    qtbot, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from PySide6.QtWidgets import QMessageBox, QWidget

    from gui.app import _install_global_excepthook

    shown: list = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: shown.append(a))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    window = QWidget()
    qtbot.addWidget(window)
    _install_global_excepthook(window)  # type: ignore[arg-type]
    sys.excepthook(RuntimeError, RuntimeError("boom"), None)
    assert shown


def test_set_app_metadata_package_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    from importlib.metadata import PackageNotFoundError

    from gui.app import _set_app_metadata

    def _raise(_name: str) -> str:
        raise PackageNotFoundError("nope")

    monkeypatch.setattr("importlib.metadata.version", _raise)
    _set_app_metadata()
    assert QCoreApplication.applicationVersion() == "0.9.0b3-dev"


def test_main_returns_qapplication_exec_code(qtbot, monkeypatch: pytest.MonkeyPatch) -> None:
    from gui import app as app_mod

    shown: list = []

    monkeypatch.setattr(app_mod, "QApplication", FakeQApplicationExec42)
    monkeypatch.setattr(app_mod, "MainWindow", lambda: FakeMainWindow(shown))
    monkeypatch.delenv("SCANNER_MANAGER_DEV_MCP", raising=False)
    assert app_mod.main(["scanner-manager-test"]) == 42
    assert shown


def test_main_dev_mcp_import_error_is_swallowed(qtbot, monkeypatch: pytest.MonkeyPatch) -> None:
    from gui import app as app_mod

    monkeypatch.setattr(app_mod, "QApplication", FakeQApplication)
    monkeypatch.setattr(app_mod, "MainWindow", FakeMainWindowNoOp)
    monkeypatch.setenv("SCANNER_MANAGER_DEV_MCP", "1")
    monkeypatch.delitem(sys.modules, "dev_mcp", raising=False)
    assert app_mod.main([]) == 0


def test_main_dev_mcp_attach_exception_is_logged(qtbot, monkeypatch: pytest.MonkeyPatch) -> None:
    import types

    from gui import app as app_mod

    def _boom(_window) -> None:
        raise RuntimeError("attach failed")

    mod = types.ModuleType("dev_mcp")
    mod.attach = types.SimpleNamespace(maybe_start=_boom)
    monkeypatch.setitem(sys.modules, "dev_mcp", mod)
    monkeypatch.setattr(app_mod, "QApplication", FakeQApplication)
    monkeypatch.setattr(app_mod, "MainWindow", FakeMainWindowNoOp)
    monkeypatch.setenv("SCANNER_MANAGER_DEV_MCP", "1")
    assert app_mod.main([]) == 0


def test_bt885_read_tables_return_none_when_sdcard_import_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import builtins

    profile = get_profile("uniden_bt885")
    real_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name == "core.sdcard":
            raise ImportError("blocked")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    assert profile.read_zip_table("/card") is None
    assert profile.read_city_table("/card") is None


def test_main_qt5_high_dpi_attributes(qtbot, monkeypatch: pytest.MonkeyPatch) -> None:
    from gui import app as app_mod

    set_attrs: list = []

    monkeypatch.setattr(app_mod, "Qt", FakeQt5)
    monkeypatch.setattr(
        app_mod.QCoreApplication,
        "setAttribute",
        lambda attr, value: set_attrs.append((attr, value)),
    )
    monkeypatch.setattr(app_mod, "QApplication", FakeQApplication)
    monkeypatch.setattr(app_mod, "MainWindow", FakeMainWindowNoOp)
    monkeypatch.delenv("SCANNER_MANAGER_DEV_MCP", raising=False)
    app_mod.main([])
    assert len(set_attrs) == 2


def test_details_panel_edit_entry_emits_signal(
    qtbot, loaded_hpd, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gui.editor.entry_dialog import Bt885EntryEditDialog

    panel = _bt885_details_panel(qtbot)
    payload = {
        "kind": "entry",
        "system": loaded_hpd["system"],
        "group": loaded_hpd["group"],
        "entry": loaded_hpd["entry"],
        "hpd_file": loaded_hpd["hpd"],
    }
    panel.show_entry(payload)
    monkeypatch.setattr(Bt885EntryEditDialog, "exec", lambda self: Bt885EntryEditDialog.Accepted)
    with qtbot.waitSignal(panel.entryEdited, timeout=1000):
        panel._on_edit_clicked()


def test_details_panel_edit_group_emits_signal(
    qtbot, loaded_hpd, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gui.editor.entry_dialog import GroupEditDialog

    panel = _bt885_details_panel(qtbot)
    payload = {
        "kind": "group",
        "system": loaded_hpd["system"],
        "group": loaded_hpd["group"],
        "hpd_file": loaded_hpd["hpd"],
    }
    panel.show_entry(payload)
    monkeypatch.setattr(GroupEditDialog, "exec", lambda self: GroupEditDialog.Accepted)
    with qtbot.waitSignal(panel.entryEdited, timeout=1000):
        panel._on_edit_clicked()


def test_details_panel_bulk_service_on_group(
    qtbot, loaded_hpd, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QDialog

    from gui.editor.entry_dialog import Bt885BulkServiceTypeDialog

    panel = _bt885_details_panel(qtbot)
    payload = {
        "kind": "group",
        "system": loaded_hpd["system"],
        "group": loaded_hpd["group"],
        "hpd_file": loaded_hpd["hpd"],
    }
    panel.show_entry(payload)
    monkeypatch.setattr(
        Bt885BulkServiceTypeDialog,
        "exec",
        lambda self: QDialog.DialogCode.Accepted,
    )
    monkeypatch.setattr(
        Bt885BulkServiceTypeDialog,
        "selected_service_type",
        lambda self: 14,
    )
    with qtbot.waitSignal(panel.entryEdited, timeout=1000):
        panel._on_bulk_service_clicked()
    assert loaded_hpd["entry"].service_type == 14


def test_details_panel_bulk_service_on_system(
    qtbot, loaded_hpd, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QDialog

    from gui.editor.entry_dialog import Bt885BulkServiceTypeDialog

    panel = _bt885_details_panel(qtbot)
    payload = {
        "kind": "system",
        "system": loaded_hpd["system"],
        "hpd_file": loaded_hpd["hpd"],
    }
    panel.show_entry(payload)
    monkeypatch.setattr(
        Bt885BulkServiceTypeDialog,
        "exec",
        lambda self: QDialog.DialogCode.Accepted,
    )
    monkeypatch.setattr(
        Bt885BulkServiceTypeDialog,
        "selected_service_type",
        lambda self: 1,
    )
    with qtbot.waitSignal(panel.entryEdited, timeout=1000):
        panel._on_bulk_service_clicked()


def test_details_panel_delete_entry(
    qtbot, loaded_hpd, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QMessageBox

    panel = _bt885_details_panel(qtbot)
    entry = loaded_hpd["entry"]
    payload = {
        "kind": "entry",
        "system": loaded_hpd["system"],
        "group": loaded_hpd["group"],
        "entry": entry,
        "hpd_file": loaded_hpd["hpd"],
    }
    panel.show_entry(payload)
    before = len(loaded_hpd["group"].entries)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    with qtbot.waitSignal(panel.entryEdited, timeout=1000):
        panel._on_delete_clicked()
    assert len(loaded_hpd["group"].entries) == before - 1
    assert panel._title.text() == "Select a node in the tree"


def test_details_panel_show_site_and_tgid_entry(qtbot, tmp_path: Path) -> None:
    from legacy_tk.scanner_manager import HpdFile

    hpd_path = tmp_path / "trunk.hpd"
    hpd_path.write_text(
        "TargetModel\tBCDx36HP\n"
        "Trunk\tTrunkId=900\tStateId=12\tAlachua Trunk\n"
        "AreaState\tStateId=12\tFL\n"
        "Site\tSiteId=1\tTrunkId=900\tSite1\tOff\t29.65\t-82.33\t25.0\n"
        "T-Freq\t460500000\n"
        "T-Group\tTGroupId=1\tTrunkId=900\tTrunk Group A\tOff\t29.65\t-82.33\t25.0\n"
        "TGID\tTid=1\tTGroupId=1\tTGA1\tOff\t1234\tDIGITAL\t2\n",
        encoding="utf-8",
    )
    hpd = HpdFile()
    hpd.load(str(hpd_path))
    trunk = hpd.systems[0]
    site = trunk.sites[0]
    tgid_entry = trunk.groups[0].entries[0]

    panel = _bt885_details_panel(qtbot)

    panel.show_entry(
        {
            "kind": "site",
            "system": trunk,
            "site": site,
            "hpd_file": hpd,
        }
    )
    assert "Site:" in panel._title.text()
    assert panel._info_form.rowCount() >= 4

    panel.show_entry(
        {
            "kind": "entry",
            "system": trunk,
            "group": trunk.groups[0],
            "entry": tgid_entry,
            "hpd_file": hpd,
        }
    )
    assert "TGA1" in panel._title.text()
    assert panel._info_form.rowCount() >= 4


def test_entry_edit_dialog_save_and_validation(
    qtbot, loaded_hpd, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QMessageBox

    from gui.editor.entry_dialog import EntryEditDialog

    set_active_profile("uniden_bt885")
    entry = loaded_hpd["entry"]
    dlg = EntryEditDialog(
        entry,
        loaded_hpd["hpd"],
        get_profile("uniden_bt885"),
    )
    qtbot.addWidget(dlg)

    warned: list = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.append(a))
    dlg._name_edit.clear()
    dlg._on_save()
    assert warned

    dlg._name_edit.setText("Renamed Dispatch")
    dlg._freq_spin.setValue(462.55)
    dlg._on_save()
    assert entry.name == "Renamed Dispatch"


def test_group_edit_dialog_save(qtbot, loaded_hpd) -> None:
    from gui.editor.entry_dialog import GroupEditDialog

    group = loaded_hpd["group"]
    dlg = GroupEditDialog(group, loaded_hpd["hpd"])
    qtbot.addWidget(dlg)
    dlg._name_edit.setText("Renamed Group")
    dlg._on_save()
    assert group.name == "Renamed Group"


def test_tgid_entry_edit_dialog_save(qtbot, tmp_path: Path) -> None:
    from gui.editor.entry_dialog import EntryEditDialog
    from legacy_tk.scanner_manager import HpdFile

    hpd_path = tmp_path / "trunk.hpd"
    hpd_path.write_text(
        "TargetModel\tBCDx36HP\n"
        "Trunk\tTrunkId=900\tStateId=12\tAlachua Trunk\n"
        "AreaState\tStateId=12\tFL\n"
        "T-Group\tTGroupId=1\tTrunkId=900\tTrunk Group A\tOff\t29.65\t-82.33\t25.0\n"
        "TGID\tTid=1\tTGroupId=1\tTGA1\tOff\t1234\tDIGITAL\t2\n",
        encoding="utf-8",
    )
    hpd = HpdFile()
    hpd.load(str(hpd_path))
    entry = hpd.systems[0].groups[0].entries[0]
    set_active_profile("uniden_bt885")
    dlg = EntryEditDialog(entry, hpd, get_profile("uniden_bt885"))
    qtbot.addWidget(dlg)
    dlg._name_edit.setText("Renamed TG")
    dlg._tgid_spin.setValue(5678)
    dlg._on_save()
    assert entry.name == "Renamed TG"
    assert entry.record.get_field(5, "") == "5678"


def test_apply_app_style_dark_palette(qtbot, monkeypatch: pytest.MonkeyPatch) -> None:
    from PySide6.QtGui import QColor, QPalette

    from gui.app import _apply_app_style

    app = QApplication.instance()
    assert app is not None
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(20, 20, 20))
    monkeypatch.setattr(app, "palette", lambda: palette)
    _apply_app_style(app)


def test_set_app_metadata_importlib_import_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import builtins

    from gui.app import _set_app_metadata

    real_import = builtins.__import__

    def _block(name, *args, **kwargs):
        if name == "importlib.metadata":
            raise ImportError("blocked")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _block)
    _set_app_metadata()
    assert QCoreApplication.applicationVersion() == "0.9.0b3-dev"


def test_main_uses_sys_argv_when_none(qtbot, monkeypatch: pytest.MonkeyPatch) -> None:
    from gui import app as app_mod

    captured: list = []

    monkeypatch.setattr(
        app_mod, "QApplication", fake_qapplication_recording(captured)
    )
    monkeypatch.setattr(app_mod, "MainWindow", FakeMainWindowNoOp)
    monkeypatch.delenv("SCANNER_MANAGER_DEV_MCP", raising=False)
    app_mod.main(None)
    assert captured and captured[0] is sys.argv


def test_main_dev_mcp_missing_package_logs_debug(qtbot, monkeypatch: pytest.MonkeyPatch) -> None:
    from gui import app as app_mod

    real_import = __import__

    def _block_dev_mcp(name, *args, **kwargs):
        if name == "dev_mcp" or name.startswith("dev_mcp."):
            raise ImportError("dev_mcp not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(app_mod, "QApplication", FakeQApplication)
    monkeypatch.setattr(app_mod, "MainWindow", FakeMainWindowNoOp)
    monkeypatch.setenv("SCANNER_MANAGER_DEV_MCP", "1")
    monkeypatch.delitem(sys.modules, "dev_mcp", raising=False)
    monkeypatch.setitem(sys.modules, "dev_mcp", None)  # force re-import attempt
    monkeypatch.setattr("builtins.__import__", _block_dev_mcp)
    assert app_mod.main([]) == 0
