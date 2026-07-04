"""Regression tests for device-switch performance (Wave 3).

Covers HPDB session cache hits, Live-mode HPDB deferral via EditorDock,
and coverage refresh gating when the popout window is closed.

MainWindow deferred switch (Wave 2 Shell) may not be wired yet; tests
exercise EditorDock / CoveragePanel APIs directly where needed.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.qt

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PySide6 = pytest.importorskip("PySide6")  # noqa: N816
pytest.importorskip("pytestqt")

from scanner_profiles import get_profile  # noqa: E402

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
)


@pytest.fixture
def tmp_devices(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
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


def test_device_switch_uses_hpdb_cache_on_second_select(
    qtbot, card_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Re-selecting the same device must not re-parse HPD files from disk."""
    from core.device_manager import Device
    from gui.editor.editor_dock import EditorDock
    from gui.editor.hpdb_cache import get_hpdb_session_cache
    from legacy_tk.scanner_manager import HpdFile

    get_hpdb_session_cache().invalidate()

    load_calls = 0
    original_load = HpdFile.load

    def _counting_load(self, path: str) -> None:
        nonlocal load_calls
        load_calls += 1
        return original_load(self, path)

    monkeypatch.setattr(HpdFile, "load", _counting_load)

    dock = EditorDock()
    qtbot.addWidget(dock)
    profile = get_profile("uniden_bt885")
    device_a = Device.make("uniden_bt885", "Truck A", sd_card_path=str(card_root))
    device_b = Device.make("uniden_bt885", "Truck B", sd_card_path=str(card_root))

    dock.set_active_device(device_a, profile)
    assert load_calls == 1
    assert dock._tree.loaded_files()

    dock.set_active_device(device_b, profile)
    assert load_calls == 2

    dock.set_active_device(device_a, profile)
    assert load_calls == 2, "second select of device A should hit HPDB session cache"


def test_sds_live_switch_skips_hpdb_load(
    qtbot, card_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Live-mode deferral: load_hpdb=False must not touch the HPDB tree."""
    from core.device_manager import Device
    from gui.editor.editor_dock import EditorDock
    from gui.editor.hpdb_tree import HpdbTreeWidget

    try_load_calls: list[tuple[str, str]] = []
    original_try_load = HpdbTreeWidget.try_load_from_card

    def _spy_try_load(self, sd_path: str, device_id: str = "") -> bool:
        try_load_calls.append((sd_path, device_id))
        return original_try_load(self, sd_path, device_id=device_id)

    monkeypatch.setattr(HpdbTreeWidget, "try_load_from_card", _spy_try_load)

    dock = EditorDock()
    qtbot.addWidget(dock)
    profile = get_profile("uniden_sds100")
    device = Device.make("uniden_sds100", "SDS Home", sd_card_path=str(card_root))

    dock.set_active_device(device, profile, load_hpdb=False)

    assert try_load_calls == []
    assert dock._tree.loaded_files() == []
    assert dock._current_device is not None
    assert dock._current_device.id == device.id


def test_coverage_refresh_skipped_when_window_closed(
    qtbot, tmp_devices: Path, card_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Coverage heatmap/map must not refresh when the popout is closed."""
    from core.device_manager import Device, DeviceManager
    from gui.main_window import MainWindow

    mgr = DeviceManager(devices_path=tmp_devices)
    bt = Device.make("uniden_bt885", "BT885", sd_card_path=str(card_root))
    mgr.add_device(bt)

    window = MainWindow()
    qtbot.addWidget(window)
    window._header.select_device(bt.id)
    qtbot.wait(10)
    assert window._coverage_window is None

    panel = window._coverage_panel
    assert panel._refresh_enabled is False
    heatmap_calls: list = []
    monkeypatch.setattr(
        panel._heatmap,
        "set_groups",
        lambda groups: heatmap_calls.append(groups),
    )
    map_calls: list = []
    monkeypatch.setattr(
        panel._map,
        "set_view",
        lambda *a, **k: map_calls.append((a, k)),
    )

    assert panel.refresh_from_hpdb() is False
    assert heatmap_calls == []
    assert map_calls == []

    heatmap_calls.clear()
    map_calls.clear()
    window._editor_dock.refresh_coverage()
    assert heatmap_calls == []
    assert map_calls == []

    panel.set_refresh_enabled(True)
    panel.set_data_source(lambda: [])
    assert panel.refresh_from_hpdb() is True
    assert len(heatmap_calls) == 1
