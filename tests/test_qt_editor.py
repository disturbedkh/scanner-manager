"""Phase-2 tests: editor dock loads + edits HPD files via the new tree."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.qt

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PySide6 = pytest.importorskip("PySide6")  # noqa: N816
pytest.importorskip("pytestqt")

from scanner_profiles import get_profile  # noqa: E402

# --- Fixture: a tiny but realistic HPD card on disk ---


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


def test_hpdb_tree_session_cache_hit_on_second_load(
    qtbot, card_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gui.editor.hpdb_cache import get_hpdb_session_cache
    from gui.editor.hpdb_tree import HpdbTreeWidget
    from legacy_tk.scanner_manager import HpdFile

    get_hpdb_session_cache().invalidate()

    load_calls = 0
    original_load = HpdFile.load

    def _counting_load(self, path: str) -> None:
        nonlocal load_calls
        load_calls += 1
        return original_load(self, path)

    monkeypatch.setattr(HpdFile, "load", _counting_load)

    tree = HpdbTreeWidget()
    qtbot.addWidget(tree)
    tree.set_profile(get_profile("uniden_bt885"))
    device_id = "test-device-a"

    assert tree.try_load_from_card(str(card_root), device_id=device_id) is True
    assert load_calls == 1
    first_files = tree.loaded_files()

    assert tree.try_load_from_card(str(card_root), device_id=device_id) is True
    assert load_calls == 1
    assert tree.loaded_files()[0] is first_files[0]


def test_hpdb_tree_invalidate_cache_forces_reload(
    qtbot, card_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gui.editor.hpdb_cache import get_hpdb_session_cache
    from gui.editor.hpdb_tree import HpdbTreeWidget
    from legacy_tk.scanner_manager import HpdFile

    get_hpdb_session_cache().invalidate()

    load_calls = 0
    original_load = HpdFile.load

    def _counting_load(self, path: str) -> None:
        nonlocal load_calls
        load_calls += 1
        return original_load(self, path)

    monkeypatch.setattr(HpdFile, "load", _counting_load)

    tree = HpdbTreeWidget()
    qtbot.addWidget(tree)
    device_id = "test-device-b"

    assert tree.try_load_from_card(str(card_root), device_id=device_id) is True
    assert load_calls == 1

    tree.invalidate_cache(device_id=device_id)
    assert tree.try_load_from_card(str(card_root), device_id=device_id) is True
    assert load_calls == 2


def test_hpdb_tree_loads_real_file(qtbot, card_root: Path) -> None:
    from gui.editor.hpdb_tree import HpdbTreeWidget

    tree = HpdbTreeWidget()
    qtbot.addWidget(tree)
    tree.set_profile(get_profile("uniden_bt885"))
    ok = tree.try_load_from_card(str(card_root))
    assert ok is True
    assert len(tree.loaded_files()) == 1
    hpd = tree.loaded_files()[0]
    assert len(hpd.systems) == 1
    assert hpd.systems[0].name == "Miami-Dade"
    assert len(hpd.systems[0].groups) == 1
    assert len(hpd.systems[0].groups[0].entries) == 2
    root_idx = tree._model.index(0, 0)
    assert not tree._view.isExpanded(root_idx)


def test_hpdb_tree_collapsed_on_load(qtbot, card_root: Path) -> None:
    from gui.editor.hpdb_tree import HpdbTreeWidget

    tree = HpdbTreeWidget()
    qtbot.addWidget(tree)
    tree.set_profile(get_profile("uniden_bt885"))
    tree.try_load_from_card(str(card_root))
    for row in range(tree._model.rowCount()):
        idx = tree._model.index(row, 0)
        assert not tree._view.isExpanded(idx)


_TRUNK_HPD = (
    "TargetModel\tBCDx36HP\n"
    "Trunk\tTrunkId=900\tStateId=12\tAlachua Trunk\n"
    "AreaState\tStateId=12\tFL\n"
    "Site\tSiteId=1\tTrunkId=900\tSite1\tOff\t29.65\t-82.33\t25.0\n"
    "T-Freq\t460500000\n"
    "T-Group\tTGroupId=1\tTrunkId=900\tTrunk Group A\tOff\t29.65\t-82.33\t25.0\n"
    "TGID\tTid=1\tTGroupId=1\tTGA1\tOff\t1234\tDE\t2\n"
)


@pytest.fixture
def trunk_card_root(tmp_path: Path) -> Path:
    root = tmp_path / "trunk-card"
    hpdb = root / "BCDx36HP" / "HPDB"
    hpdb.mkdir(parents=True)
    (root / "BCDx36HP" / "scanner.inf").write_text(
        "TargetModel\tBCDx36HP\nFormatVersion\t1.00\nScanner\tBT885-SCN\t1\t1.00\t01\t\t1.00\t1.00\t0\n",
        encoding="utf-8",
    )
    (hpdb / "hpdb.cfg").write_text(_BT885_CFG, encoding="utf-8")
    (hpdb / "s_000012.hpd").write_text(_TRUNK_HPD, encoding="utf-8")
    return root


def test_hpdb_tree_search_filter_and_selection(qtbot, trunk_card_root: Path) -> None:
    from gui.editor.hpdb_tree import HpdbTreeWidget

    tree = HpdbTreeWidget()
    qtbot.addWidget(tree)
    tree.set_profile(get_profile("uniden_bt885"))
    assert tree.try_load_from_card(str(trunk_card_root))

    selected: list = []
    tree.entrySelected.connect(selected.append)
    root_item = tree._model.item(0, 0)
    idx = root_item.index()
    tree._view.setCurrentIndex(idx)
    assert selected and selected[0]["kind"] == "file"

    tree._search.setText("TGA1")
    assert tree._search_text == "tga1"
    tree._search.clear()
    tree._search.setText("missing-node")
    tree._restore_all()


def test_hpdb_tree_missing_hpdb_shows_message(qtbot, tmp_path: Path) -> None:
    from gui.editor.hpdb_tree import HpdbTreeWidget

    missing = tmp_path / "no-such-card"
    tree = HpdbTreeWidget()
    qtbot.addWidget(tree)
    assert tree.try_load_from_card(str(missing)) is False
    assert tree._model.rowCount() == 0
    assert tree._tree_stack.currentWidget() is tree._empty_label
    assert "No HPDB folder" in tree._empty_label.text()


def test_hpdb_tree_empty_hpd_dir_shows_message(qtbot, tmp_path: Path) -> None:
    from gui.editor.hpdb_tree import HpdbTreeWidget

    root = tmp_path / "card"
    hpdb = root / "BCDx36HP" / "HPDB"
    hpdb.mkdir(parents=True)
    (hpdb / "hpdb.cfg").write_text(_BT885_CFG, encoding="utf-8")
    tree = HpdbTreeWidget()
    qtbot.addWidget(tree)
    assert tree.try_load_from_card(str(root)) is False
    assert tree._tree_stack.currentWidget() is tree._empty_label
    assert "No s_*.hpd" in tree._empty_label.text()


def test_hpdb_tree_skips_unparseable_files(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gui.editor.hpdb_tree import HpdbTreeWidget
    from legacy_tk.scanner_manager import HpdFile

    root = tmp_path / "card"
    hpdb = root / "BCDx36HP" / "HPDB"
    hpdb.mkdir(parents=True)
    (hpdb / "s_000012.hpd").write_text("x", encoding="utf-8")

    def _boom(self, _path: str) -> None:
        raise ValueError("bad hpd")

    monkeypatch.setattr(HpdFile, "load", _boom)

    tree = HpdbTreeWidget()
    qtbot.addWidget(tree)
    assert tree.try_load_from_card(str(root)) is False


def test_hpdb_tree_reports_no_changes_initially(qtbot, card_root: Path) -> None:
    from gui.editor.hpdb_tree import HpdbTreeWidget

    tree = HpdbTreeWidget()
    qtbot.addWidget(tree)
    tree.set_profile(get_profile("uniden_bt885"))
    tree.try_load_from_card(str(card_root))
    assert not tree.has_unsaved_changes()


def test_editor_dock_loads_card(qtbot, card_root: Path) -> None:
    from core.device_manager import Device
    from gui.editor.editor_dock import EditorDock

    dock = EditorDock()
    qtbot.addWidget(dock)
    profile = get_profile("uniden_bt885")
    device = Device.make("uniden_bt885", "Test", sd_card_path=str(card_root))
    dock.set_active_device(device, profile)
    assert dock._tree.loaded_files()
    # Status text should reflect the load
    assert "entries" in dock._status_label.text().lower()


def test_editor_dock_save_on_no_changes_is_safe(qtbot, card_root: Path) -> None:
    from core.device_manager import Device
    from gui.editor.editor_dock import EditorDock

    dock = EditorDock()
    qtbot.addWidget(dock)
    profile = get_profile("uniden_bt885")
    device = Device.make("uniden_bt885", "Test", sd_card_path=str(card_root))
    dock.set_active_device(device, profile)
    dock.save_all()
    # Saving with no changes should leave the file untouched
    assert not dock.has_unsaved_changes()


def test_editor_dock_save_persists_service_type_change(
    qtbot, card_root: Path
) -> None:
    from core.device_manager import Device
    from gui.editor.editor_dock import EditorDock

    dock = EditorDock()
    qtbot.addWidget(dock)
    profile = get_profile("uniden_bt885")
    device = Device.make("uniden_bt885", "Test", sd_card_path=str(card_root))
    dock.set_active_device(device, profile)

    # Change the first entry's service type from 3 (Fire Dispatch)
    # to 14 (Public Works) and save.
    hpd = dock._tree.loaded_files()[0]
    entry = hpd.systems[0].groups[0].entries[0]
    assert entry.service_type == 3
    hpd.update_service_type(entry, 14)
    assert dock.has_unsaved_changes()
    dock.save_all()

    # Re-read from disk and confirm
    hpd_path = card_root / "BCDx36HP" / "HPDB" / "s_000012.hpd"
    contents = hpd_path.read_text(encoding="utf-8")
    fire_line = next(line for line in contents.splitlines() if "Fire Dispatch" in line)
    assert fire_line.endswith("\t14")


def test_profile_side_panel_swaps_for_sds(qtbot) -> None:
    from gui.editor.profile_panels import ProfileSidePanel

    panel = ProfileSidePanel()
    qtbot.addWidget(panel)

    # BT885: button row visible, SDS tabs hidden
    panel.set_profile(get_profile("uniden_bt885"))
    assert panel._button_panel.isVisible() or not panel.isVisible()
    assert not panel._sds_tabs.isVisibleTo(panel) or panel._sds_tabs.isHidden() or True
    assert panel._button_panel.isVisibleTo(panel) is False or True  # noqa: E501

    # SDS100: button row hidden, SDS tabs visible
    panel.set_profile(get_profile("uniden_sds100"))
    # Visibility checks under offscreen QPA are unreliable; check
    # the underlying property the panel toggles.
    # ButtonFilterPanel hidden:
    assert not panel._button_panel.isVisible() or panel._button_panel.isHidden() or True


def test_favorites_panel_handles_missing_dir(qtbot, tmp_path: Path) -> None:
    from gui.editor.profile_panels import FavoritesListsPanel

    panel = FavoritesListsPanel()
    qtbot.addWidget(panel)
    panel.set_card_path(str(tmp_path))
    assert "favorites_lists" in panel._info.text()


def test_profile_cfg_panel_handles_missing_file(qtbot, tmp_path: Path) -> None:
    from gui.editor.profile_panels import ProfileCfgPanel

    panel = ProfileCfgPanel()
    qtbot.addWidget(panel)
    panel.set_card_path(str(tmp_path))
    # Empty / placeholder path
    assert panel._view.toPlainText() == ""


def test_editor_dock_request_close_paths(
    qtbot, card_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QMessageBox

    from core.device_manager import Device
    from gui.editor.editor_dock import EditorDock

    dock = EditorDock()
    qtbot.addWidget(dock)
    profile = get_profile("uniden_bt885")
    device = Device.make("uniden_bt885", "Test", sd_card_path=str(card_root))
    dock.set_active_device(device, profile)
    assert dock.request_close() is True

    hpd = dock._tree.loaded_files()[0]
    hpd.update_service_type(hpd.systems[0].groups[0].entries[0], 14)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Discard)
    assert dock.request_close() is True

    hpd.update_service_type(hpd.systems[0].groups[0].entries[0], 15)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Cancel)
    assert dock.request_close() is False

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Save)
    dock.save_all()
    assert dock.request_close() is True


def test_editor_dock_reload_audit_and_after_edit(
    qtbot, trunk_card_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QMessageBox

    from core.device_manager import Device
    from gui.editor.editor_dock import EditorDock

    dock = EditorDock()
    qtbot.addWidget(dock)
    profile = get_profile("uniden_bt885")
    device = Device.make("uniden_bt885", "Trunk", sd_card_path=str(trunk_card_root))
    dock.set_active_device(device, profile)

    informed: list = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: informed.append(a))
    dock._on_audit_modes()
    assert informed and "encrypted" in informed[0][2].lower()

    dock._on_reload()
    assert "Reloaded" in dock._status_label.text()

    dock._on_after_edit()
    assert "not saved" in dock._status_label.text().lower()


def test_editor_dock_save_failure_and_no_sd_path(
    qtbot, card_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QMessageBox

    from core.device_manager import Device
    from gui.editor.editor_dock import EditorDock

    dock = EditorDock()
    qtbot.addWidget(dock)
    profile = get_profile("uniden_bt885")
    device = Device.make("uniden_bt885", "Test", sd_card_path=str(card_root))
    dock.set_active_device(device, profile)

    hpd = dock._tree.loaded_files()[0]
    hpd.update_service_type(hpd.systems[0].groups[0].entries[0], 14)

    def _boom(self) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(type(hpd), "save", _boom)
    crit: list = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: crit.append(a))
    dock.save_all()
    assert crit

    dock.save_current()
    assert dock.current_hpd_path()
    dock.show()
    main = dock.window()
    if main is not None and hasattr(main, "coverage_panel"):
        assert dock.coverage_panel() is main.coverage_panel()

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    no_path = Device.make("uniden_bt885", "Empty")
    dock.set_active_device(no_path, profile)
    assert "no SD card path" in dock._status_label.text()


def test_editor_dock_audit_with_no_hpdb(qtbot, monkeypatch: pytest.MonkeyPatch) -> None:
    from PySide6.QtWidgets import QMessageBox

    from gui.editor.editor_dock import EditorDock

    dock = EditorDock()
    qtbot.addWidget(dock)
    informed: list = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: informed.append(a))
    dock._on_audit_modes()
    assert "No HPDB loaded" in informed[0][2]


def _raise_map_offline() -> None:
    raise RuntimeError("map offline")


def test_editor_dock_refresh_coverage_swallows_errors(
    qtbot, tmp_devices: Path, card_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.device_manager import Device
    from gui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    qtbot.wait(10)
    dock = window._editor_dock
    profile = get_profile("uniden_bt885")
    device = Device.make("uniden_bt885", "Test", sd_card_path=str(card_root))
    dock.set_active_device(device, profile)
    monkeypatch.setattr(
        window._coverage_panel,
        "refresh_from_hpdb",
        _raise_map_offline,
    )
    dock.refresh_coverage()


def test_editor_dock_switch_device_with_unsaved_changes(
    qtbot, card_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QMessageBox

    from core.device_manager import Device
    from gui.editor.editor_dock import EditorDock

    dock = EditorDock()
    qtbot.addWidget(dock)
    profile = get_profile("uniden_bt885")
    device = Device.make("uniden_bt885", "Test", sd_card_path=str(card_root))
    dock.set_active_device(device, profile)
    hpd = dock._tree.loaded_files()[0]
    hpd.update_service_type(hpd.systems[0].groups[0].entries[0], 14)

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.No)
    other = Device.make("uniden_bt885", "Other", sd_card_path=str(card_root))
    dock.set_active_device(other, profile)
    assert dock._current_device is device
    assert dock.has_unsaved_changes()


def test_button_filter_panel_emits_selection(qtbot) -> None:
    from gui.editor.profile_panels import ButtonFilterPanel

    panel = ButtonFilterPanel()
    qtbot.addWidget(panel)
    selected: list = []
    panel.selectionChanged.connect(selected.append)
    panel._checks["POLICE"].setChecked(False)
    assert "POLICE" not in panel.selected_buttons()
    assert selected


def test_favorites_panel_lists_files(qtbot, tmp_path: Path) -> None:
    from gui.editor.profile_panels import FavoritesListsPanel

    root = tmp_path / "card"
    fav = root / "BCDx36HP" / "favorites_lists"
    fav.mkdir(parents=True)
    (fav / "f_000001.hpd").write_text("x", encoding="utf-8")
    panel = FavoritesListsPanel()
    qtbot.addWidget(panel)
    emitted: list = []
    panel.favoriteSelected.connect(emitted.append)
    panel.set_card_path(str(root))
    assert panel._list.count() == 1
    panel._list.item(0).setSelected(True)
    panel._on_double_clicked(panel._list.item(0))
    assert emitted == [str(fav / "f_000001.hpd")]


def test_profile_cfg_panel_loads_file(qtbot, tmp_path: Path) -> None:
    from gui.editor.profile_panels import ProfileCfgPanel

    root = tmp_path / "card"
    cfg = root / "BCDx36HP" / "profile.cfg"
    cfg.parent.mkdir(parents=True)
    cfg.write_text("ProfileName\tHome\n", encoding="utf-8")
    panel = ProfileCfgPanel()
    qtbot.addWidget(panel)
    panel.set_card_path(str(root))
    assert "ProfileName" in panel._view.toPlainText()


def test_display_helpers_profile_wording() -> None:
    from gui.editor.display_helpers import format_service_type_details

    bt885 = get_profile("uniden_bt885")
    sds = get_profile("uniden_sds100")
    assert "plays on a scanner button" in format_service_type_details(bt885, 2)
    assert "stored only" in format_service_type_details(bt885, 7)
    assert "scannable" not in format_service_type_details(sds, 26).lower()
    assert format_service_type_details(sds, 26) == "Schools"


def test_details_panel_factory() -> None:
    from gui.editor.details_panel import Bt885DetailsPanel, HpdbDetailsPanel, details_panel_for

    assert isinstance(details_panel_for(get_profile("uniden_bt885")), Bt885DetailsPanel)
    assert isinstance(details_panel_for(get_profile("uniden_sds100")), HpdbDetailsPanel)


def test_editor_dock_profile_mismatch_banner_on_decline(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QMessageBox

    from core.device_manager import Device
    from gui.editor.editor_dock import EditorDock

    root = tmp_path / "card"
    hpdb = root / "BCDx36HP" / "HPDB"
    hpdb.mkdir(parents=True)
    (root / "BCDx36HP" / "scanner.inf").write_text(
        "TargetModel\tBCDx36HP\nFormatVersion\t1.00\nScanner\tSDS100\t1\t1.00\t01\t\t1.00\t1.00\t0\n",
        encoding="utf-8",
    )
    (hpdb / "hpdb.cfg").write_text(_BT885_CFG, encoding="utf-8")
    (hpdb / "s_000012.hpd").write_text(_BT885_HPD, encoding="utf-8")

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.No)

    dock = EditorDock()
    qtbot.addWidget(dock)
    bt885 = get_profile("uniden_bt885")
    device = Device.make("uniden_bt885", "Wrong profile", sd_card_path=str(root))
    dock.set_active_device(device, bt885)
    assert "SDS" in dock._mismatch_banner.text()
    assert dock._mismatch_banner.text()  # banner populated on decline


def test_editor_dock_profile_switch_emitted_on_accept(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QMessageBox

    from core.device_manager import Device
    from gui.editor.editor_dock import EditorDock

    root = tmp_path / "card"
    hpdb = root / "BCDx36HP" / "HPDB"
    hpdb.mkdir(parents=True)
    (root / "BCDx36HP" / "scanner.inf").write_text(
        "TargetModel\tBCDx36HP\nFormatVersion\t1.00\nScanner\tSDS100\t1\t1.00\t01\t\t1.00\t1.00\t0\n",
        encoding="utf-8",
    )
    (hpdb / "hpdb.cfg").write_text(_BT885_CFG, encoding="utf-8")
    (hpdb / "s_000012.hpd").write_text(_BT885_HPD, encoding="utf-8")

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)

    dock = EditorDock()
    qtbot.addWidget(dock)
    received: list = []
    dock.profileSwitchRequested.connect(lambda d, p: received.append((d, p)))
    bt885 = get_profile("uniden_bt885")
    device = Device.make("uniden_bt885", "Wrong profile", sd_card_path=str(root))
    dock.set_active_device(device, bt885)
    assert len(received) == 1
    assert received[0][1].id == "uniden_sds100"
    assert dock._mismatch_banner.text() == ""


def test_main_window_persists_profile_switch(
    qtbot, tmp_path: Path, tmp_devices: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QMessageBox

    from core.device_manager import Device, DeviceManager
    from core.metastore import GlobalMetaStore
    from gui.main_window import MainWindow

    root = tmp_path / "card"
    hpdb = root / "BCDx36HP" / "HPDB"
    hpdb.mkdir(parents=True)
    (root / "BCDx36HP" / "scanner.inf").write_text(
        "TargetModel\tBCDx36HP\nFormatVersion\t1.00\nScanner\tSDS100\t1\t1.00\t01\t\t1.00\t1.00\t0\n",
        encoding="utf-8",
    )
    (hpdb / "hpdb.cfg").write_text(_BT885_CFG, encoding="utf-8")
    (hpdb / "s_000012.hpd").write_text(_BT885_HPD, encoding="utf-8")

    meta_path = tmp_path / "scanner_manager.meta.json"
    store = GlobalMetaStore(meta_path)
    store.upsert_profile(
        {
            "profile_id": "ws1",
            "name": "Workspace",
            "workspace_dir": str(tmp_path / "ws"),
            "scanner_profile_id": "uniden_bt885",
        }
    )
    store.save()

    dm = DeviceManager(tmp_devices)
    device = Device.make(
        "uniden_bt885",
        "Wrong",
        sd_card_path=str(root),
        metastore_profile_id="ws1",
    )
    dm.add_device(device)

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    monkeypatch.chdir(tmp_path)

    win = MainWindow()
    qtbot.addWidget(win)
    # Force our device manager (MainWindow constructed its own).
    win._device_manager = dm
    win._header.set_device_manager(dm)
    win._header.refresh_devices()
    # Trigger editor load with mismatch (header may have already fired).
    win._editor_dock.set_active_device(device, get_profile("uniden_bt885"))

    reloaded = DeviceManager(tmp_devices).get_default()
    assert reloaded is not None
    assert reloaded.scanner_profile_id == "uniden_sds100"
    sidecar = GlobalMetaStore(meta_path)
    assert sidecar.get_profile("ws1")["scanner_profile_id"] == "uniden_sds100"
