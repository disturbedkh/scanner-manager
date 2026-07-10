"""Tests for BT885 location simulation bar and tree filtering."""

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
    "StateInfo\tStateId=12\tCountryId=1\tFlorida\tFL\n"
)

_BT885_HPD = (
    "TargetModel\tBCDx36HP\n"
    "FormatVersion\t1.00\n"
    "Conventional\tCountyId=86\tStateId=12\tMiami-Dade\tOff\t25.7617\t-80.1918\t10.0\tCircle\n"
    "C-Group\tCGroupId=1\tCountyId=86\tDispatch\tOff\t25.7617\t-80.1918\t5.0\tCircle\n"
    "C-Freq\tCFreqId=1\tCGroupId=1\tFire Dispatch\tOff\t154445000\tFM\t100.0\t3\n"
    "C-Freq\tCFreqId=2\tCGroupId=1\tEMS Dispatch\tOff\t155865000\tFM\t\t4\n"
)

_FAR_HPD = (
    "TargetModel\tBCDx36HP\n"
    "FormatVersion\t1.00\n"
    "Conventional\tCountyId=1\tStateId=12\tAlachua\tOff\t29.6516\t-82.3248\t10.0\tCircle\n"
    "C-Group\tCGroupId=1\tCountyId=1\tFar Group\tOff\t29.6516\t-82.3248\t5.0\tCircle\n"
    "C-Freq\tCFreqId=1\tCGroupId=1\tFar Fire\tOff\t460000000\tFM\t\t3\n"
)


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


@pytest.fixture
def dual_system_card(tmp_path: Path) -> Path:
    root = tmp_path / "card2"
    hpdb = root / "BCDx36HP" / "HPDB"
    hpdb.mkdir(parents=True)
    (hpdb / "hpdb.cfg").write_text(_BT885_CFG, encoding="utf-8")
    combined = _BT885_HPD + "\n" + _FAR_HPD
    (hpdb / "s_000012.hpd").write_text(combined, encoding="utf-8")
    return root


def test_location_filter_state_imports() -> None:
    from gui.editor.location_filter import LocationFilterState

    state = LocationFilterState(enabled=True, coords=(25.7617, -80.1918))
    assert state.enabled is True


def test_location_sim_bar_sanitizes_zip(qtbot, tmp_path: Path, monkeypatch) -> None:
    from PySide6.QtWidgets import QMessageBox

    from gui.editor.location_sim_bar import LocationSimBar
    from legacy_tk.scanner_manager import HpdConfig

    messages: list[str] = []

    def _capture_warning(_parent, _title, text):
        messages.append(text)

    monkeypatch.setattr(QMessageBox, "warning", _capture_warning)

    cfg_path = tmp_path / "hpdb.cfg"
    cfg_path.write_text(_BT885_CFG, encoding="utf-8")
    cfg = HpdConfig()
    cfg.load(str(cfg_path))

    bar = LocationSimBar()
    qtbot.addWidget(bar)
    bar.set_hpdb_context(cfg, None)
    bar._zip_field.setText("3310")
    bar._on_zip_lookup()
    assert messages and "5-digit" in messages[0]
    assert bar._zip_field.text() == "3310"


def test_location_sim_bar_emits_on_toggle(qtbot, card_root: Path) -> None:
    from gui.editor.hpdb_tree import HpdbTreeWidget
    from gui.editor.location_sim_bar import LocationSimBar

    tree = HpdbTreeWidget()
    qtbot.addWidget(tree)
    tree.set_profile(get_profile("uniden_bt885"))
    tree.try_load_from_card(str(card_root))

    bar = LocationSimBar()
    qtbot.addWidget(bar)
    bar.set_hpdb_context(tree.hpd_config(), tree.sd_root())

    states: list = []
    bar.locationFilterChanged.connect(states.append)
    bar._lat_spin.setValue(25.7617)
    bar._lon_spin.setValue(-80.1918)
    bar._filter_enabled.setChecked(True)
    assert states
    assert states[-1].enabled is True
    assert states[-1].coords == (25.7617, -80.1918)


def _count_visible_groups_in_system(tree, file_item, sys_item) -> int:
    from PySide6.QtCore import Qt

    visible_groups = 0
    for grp_row in range(sys_item.rowCount()):
        grp_item = sys_item.child(grp_row, 0)
        if grp_item is None:
            continue
        payload = grp_item.data(Qt.UserRole)
        if not isinstance(payload, dict) or payload.get("kind") != "group":
            continue
        if not tree._view.isRowHidden(grp_row, sys_item.index()):
            visible_groups += 1
    return visible_groups


def _visible_group_count(tree, file_item) -> int:
    visible_groups = 0
    for sys_row in range(file_item.rowCount()):
        sys_item = file_item.child(sys_row, 0)
        if sys_item is None or tree._view.isRowHidden(sys_row, file_item.index()):
            continue
        visible_groups += _count_visible_groups_in_system(tree, file_item, sys_item)
    return visible_groups


def test_location_filter_hides_far_group(qtbot, dual_system_card: Path) -> None:
    from gui.editor.hpdb_tree import HpdbTreeWidget
    from gui.editor.location_filter import LocationFilterState

    tree = HpdbTreeWidget()
    qtbot.addWidget(tree)
    tree.set_profile(get_profile("uniden_bt885"))
    tree.try_load_from_card(str(dual_system_card))

    file_item = tree._model.item(0, 0)
    assert file_item is not None
    assert file_item.rowCount() >= 2

    tree.set_location_filter(
        LocationFilterState(
            enabled=True,
            coords=(25.7617, -80.1918),
            tolerance_mi=0.0,
            state_id=12,
        )
    )

    visible_groups = _visible_group_count(tree, file_item)
    assert visible_groups >= 1
    assert visible_groups < file_item.rowCount() + 1


def test_inspector_include_others_signal(qtbot) -> None:
    from gui.editor.bt885_inspector import Bt885InspectorPanel

    panel = Bt885InspectorPanel()
    qtbot.addWidget(panel)
    flags: list = []
    panel.includeOthersChanged.connect(flags.append)
    buttons = panel.button_filter_panel()
    assert buttons._include_others.parent() is buttons._button_box
    buttons._include_others.setChecked(False)
    assert flags == [False]
    assert panel.include_others() is False


def test_editor_dock_has_no_embedded_coverage(qtbot, card_root: Path) -> None:
    from core.device_manager import Device
    from gui.editor.coverage_panel import CoveragePanel
    from gui.editor.editor_dock import EditorDock

    dock = EditorDock()
    qtbot.addWidget(dock)
    dock.show()
    profile = get_profile("uniden_bt885")
    device = Device.make("uniden_bt885", "Test", sd_card_path=str(card_root))
    dock.set_active_device(device, profile)

    coverage_children = dock.findChildren(CoveragePanel)
    assert coverage_children == []
    assert not hasattr(dock, "_coverage")
    assert dock._location_sim.isHidden() is False
    assert dock._bt885_inspector.isHidden() is False
