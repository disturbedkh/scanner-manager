"""Smoke tests for the Phase 5 firmware dock UI."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.qt

pytest.importorskip("pytestqt")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402

from core.device_manager import Device  # noqa: E402
from firmware.library import FirmwareCache, FirmwareVersion, HpdbVersion  # noqa: E402
from gui.firmware.firmware_dock import FirmwareDock  # noqa: E402
from scanner_profiles import get_profile  # noqa: E402


@pytest.fixture
def sds_profile():
    return get_profile("uniden_sds100")


@pytest.fixture
def fake_card(tmp_path: Path) -> Path:
    bcd = tmp_path / "BCDx36HP"
    bcd.mkdir()
    (bcd / "scanner.inf").write_text("SDS100\nSDS100-A\n1.25.99\n1.03.10\n", encoding="utf-8")
    (bcd / "firmware").mkdir()
    (bcd / "firmware" / "sub").mkdir(parents=True)
    (bcd / "HPDB").mkdir()
    return tmp_path


@pytest.fixture
def device(fake_card: Path) -> Device:
    return Device.make(
        scanner_profile_id="uniden_sds100",
        label="Test SDS-100",
        sd_card_path=str(fake_card),
    )


def test_firmware_dock_builds_in_unloaded_state(qtbot, sds_profile):
    dock = FirmwareDock()
    qtbot.addWidget(dock)
    # In unloaded state the action buttons must be disabled.
    assert not dock._refresh_btn.isEnabled()
    assert not dock._download_btn.isEnabled()
    assert not dock._update_btn.isEnabled()
    assert "Select a device" in dock._family_label.text()
    assert dock._tabs.count() == 3


def test_firmware_dock_tab_labels(qtbot):
    dock = FirmwareDock()
    qtbot.addWidget(dock)
    labels = [dock._tabs.tabText(i) for i in range(dock._tabs.count())]
    assert labels == ["Main firmware", "Sub firmware", "HPDB"]


def test_firmware_dock_set_active_device_enables_refresh(qtbot, sds_profile, device):
    dock = FirmwareDock()
    qtbot.addWidget(dock)
    dock.set_active_device(device, sds_profile)
    assert dock._refresh_btn.isEnabled()
    assert dock._open_cache_btn.isEnabled()
    # Current versions should populate from the fake scanner.inf
    assert "SDS100" in dock._current_label.text()
    assert "1.25.99" in dock._current_label.text()


def test_firmware_dock_endpoint_routing(qtbot, sds_profile):
    dock = FirmwareDock()
    qtbot.addWidget(dock)
    # SDS family -> Sentinel server
    sentinel = dock._endpoint_for_profile(sds_profile)
    assert sentinel.host == "ftp.homepatrol.com"
    # BT885 -> BT885 server (HPDB only)
    bt885 = dock._endpoint_for_profile(get_profile("uniden_bt885"))
    assert bt885.host == "ftp.uniden.com"


def test_firmware_dock_request_close_does_not_block(qtbot, sds_profile):
    dock = FirmwareDock()
    qtbot.addWidget(dock)
    assert dock.request_close() is True


def test_firmware_dock_opens_virtual_card_on_active_device(
    qtbot, monkeypatch, sds_profile, device, tmp_path: Path
):
    """Selecting a device must spin up its virtual card and the
    pending-changes panel must reflect the (initially empty) state.
    """
    monkeypatch.setenv(
        "SCANNER_MANAGER_VIRTUAL_SD_ROOT", str(tmp_path / "vcards")
    )
    dock = FirmwareDock()
    qtbot.addWidget(dock)
    dock.set_active_device(device, sds_profile)
    assert dock._virtual_card is not None
    assert dock._virtual_card.list_pending() == []
    # Apply / discard buttons should be disabled when nothing's staged.
    assert dock._apply_btn.isEnabled() is False
    assert dock._discard_btn.isEnabled() is False
    # Stage button is enabled because a card is open (operator can pick
    # a tree row and stage the cached file).
    assert dock._stage_btn.isEnabled() is True


def test_firmware_dock_stage_then_apply_round_trip(
    qtbot, monkeypatch, sds_profile, device, tmp_path: Path
):
    """End-to-end: stage a fake cached firmware blob, see it in the
    pending tree, then click apply and verify it lands on the
    physical card.
    """
    monkeypatch.setenv(
        "SCANNER_MANAGER_VIRTUAL_SD_ROOT", str(tmp_path / "vcards")
    )
    dock = FirmwareDock()
    qtbot.addWidget(dock)
    cache_root = tmp_path / "cache"
    dock._cache = FirmwareCache(root=cache_root)
    dock.set_active_device(device, sds_profile)

    # Pre-place a "downloaded" main firmware blob in the cache so the
    # stage button has something to copy.
    main_v = FirmwareVersion.parse("SDS-100_V1_26_01.bin")
    cached_path = cache_root / sds_profile.id / main_v.filename
    cached_path.parent.mkdir(parents=True, exist_ok=True)
    cached_path.write_bytes(b"FAKE-FW-PAYLOAD" * 1024)

    # Use the public stage method directly (we don't need to drive the
    # tree-selection signals to verify the round-trip).
    from virtual_sd import StageKind
    dock._virtual_card.stage(
        cached_path,
        f"BCDx36HP/firmware/{cached_path.name}",
        StageKind.MAIN_FIRMWARE,
        source_label=cached_path.name,
    )
    dock._refresh_pending_view()
    assert dock._pending_tree.topLevelItemCount() == 1
    assert dock._apply_btn.isEnabled() is True

    # Apply.
    report = dock._virtual_card.apply_to_physical(
        Path(device.sd_card_path)
    )
    assert report.ok
    landed = Path(device.sd_card_path) / "BCDx36HP" / "firmware" / cached_path.name
    assert landed.exists()
    assert landed.read_bytes() == b"FAKE-FW-PAYLOAD" * 1024


def test_firmware_dock_fills_main_tree_after_simulated_refresh(
    qtbot, sds_profile, device, tmp_path: Path
):
    dock = FirmwareDock()
    qtbot.addWidget(dock)
    # Point the cache at a temp dir so we don't pollute the user's
    # actual Sentinel cache during tests.
    dock._cache = FirmwareCache(root=tmp_path / "cache")
    dock.set_active_device(device, sds_profile)

    mains = [
        FirmwareVersion.parse("SDS-100_V1_26_01.bin"),
        FirmwareVersion.parse("SDS-100_V1_25_99.bin"),
    ]
    subs = [FirmwareVersion.parse("SDS-100-SUB_V1_03_15.firm")]
    hpdbs = [HpdbVersion.parse("MasterHpdb_05_03_2026.gz")]
    dock._mains = mains
    dock._subs = subs
    dock._hpdbs = hpdbs
    dock._fill_main_tree()
    dock._fill_sub_tree()
    dock._fill_hpdb_tree()

    assert dock._main_tree.topLevelItemCount() == 2
    assert dock._sub_tree.topLevelItemCount() == 1
    assert dock._hpdb_tree.topLevelItemCount() == 1
    # Newest main is at the top
    top_main = dock._main_tree.topLevelItem(0)
    assert top_main.text(0) == "1.26.01"
    assert "LATEST" in top_main.text(1)


@pytest.fixture
def auto_msgbox(monkeypatch):
    """Auto-accept dialogs so button-click tests stay non-interactive."""
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)


def test_parse_version_helper():
    from gui.firmware.firmware_dock import _parse_version

    assert _parse_version("1.25.99") == (1, 25, 99)
    assert _parse_version("V1.03.10") == (1, 3, 10)
    assert _parse_version("") is None
    assert _parse_version("1.2") is None
    assert _parse_version("a.b.c") is None


def test_format_bytes_helper():
    from gui.firmware.firmware_dock import _format_bytes

    assert _format_bytes(512) == "512 B"
    assert "KiB" in _format_bytes(2048)
    assert "MiB" in _format_bytes(2 * 1024 * 1024)


def test_firmware_dock_tab_switch_updates_selection(qtbot, sds_profile, device, tmp_path):
    dock = FirmwareDock()
    qtbot.addWidget(dock)
    dock._cache = FirmwareCache(root=tmp_path / "cache")
    dock.set_active_device(device, sds_profile)

    main_v = FirmwareVersion.parse("SDS-100_V1_26_01.bin")
    hpdb_v = HpdbVersion.parse("MasterHpdb_05_03_2026.gz")
    dock._mains = [main_v]
    dock._hpdbs = [hpdb_v]
    dock._fill_main_tree()
    dock._fill_hpdb_tree()

    dock._main_tree.topLevelItem(0).setSelected(True)
    dock._on_selection_changed()
    assert "1.26.01" in dock._details_label.text()
    assert dock._download_btn.isEnabled()

    dock._tabs.setCurrentIndex(2)
    dock._hpdb_tree.topLevelItem(0).setSelected(True)
    dock._on_selection_changed()
    assert "MasterHpdb" in dock._details_label.text()
    assert not dock._download_btn.isEnabled()


def test_firmware_dock_cached_selection_enables_update(
    qtbot, sds_profile, device, tmp_path, auto_msgbox
):
    dock = FirmwareDock()
    qtbot.addWidget(dock)
    cache_root = tmp_path / "cache"
    dock._cache = FirmwareCache(root=cache_root)
    dock.set_active_device(device, sds_profile)

    main_v = FirmwareVersion.parse("SDS-100_V1_26_01.bin")
    cached_path = cache_root / sds_profile.id / main_v.filename
    cached_path.parent.mkdir(parents=True, exist_ok=True)
    cached_path.write_bytes(b"FW")
    dock._cache.store(sds_profile.id, main_v, b"FW")

    dock._mains = [main_v]
    dock._fill_main_tree()
    dock._main_tree.topLevelItem(0).setSelected(True)
    dock._on_selection_changed()
    assert "CACHED" in dock._main_tree.topLevelItem(0).text(1)
    assert not dock._download_btn.isEnabled()
    assert dock._update_btn.isEnabled()


def test_firmware_dock_refresh_done_populates_trees(
    qtbot, sds_profile, device, tmp_path, auto_msgbox
):
    dock = FirmwareDock()
    qtbot.addWidget(dock)
    dock.set_active_device(device, sds_profile)

    mains = [FirmwareVersion.parse("SDS-100_V1_26_01.bin")]
    subs = [FirmwareVersion.parse("SDS-100-SUB_V1_03_15.firm")]
    hpdbs = [HpdbVersion.parse("MasterHpdb_05_03_2026.gz")]
    dock._on_refresh_done(mains, subs, hpdbs, "")
    assert dock._main_tree.topLevelItemCount() == 1
    assert dock._sub_tree.topLevelItemCount() == 1
    assert dock._hpdb_tree.topLevelItemCount() == 1
    assert "Refresh done" in dock._log_label.text()


def test_firmware_dock_refresh_done_shows_error(qtbot, sds_profile, device, auto_msgbox):
    dock = FirmwareDock()
    qtbot.addWidget(dock)
    dock.set_active_device(device, sds_profile)
    dock._on_refresh_done([], [], [], "FTP timeout")
    assert "Refresh failed" in dock._log_label.text()


def test_firmware_dock_mock_refresh_worker(qtbot, monkeypatch, sds_profile, device, auto_msgbox):
    dock = FirmwareDock()
    qtbot.addWidget(dock)
    dock.set_active_device(device, sds_profile)

    mains = [FirmwareVersion.parse("SDS-100_V1_26_01.bin")]

    class _FakeClient:
        def listing(self):
            return [mains[0].filename]

    monkeypatch.setattr(
        "gui.firmware.firmware_dock.UnidenFtpClient", lambda _ep: _FakeClient()
    )
    qtbot.mouseClick(dock._refresh_btn, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: dock._main_tree.topLevelItemCount() >= 1, timeout=3000)
    assert dock._refresh_btn.text() == "Refresh from Uniden"


def test_refresh_worker_run_success(monkeypatch):
    from firmware.ftp_client import SENTINEL_FTP
    from gui.firmware.firmware_dock import _RefreshWorker

    class _FakeClient:
        def listing(self):
            return ["SDS-100_V1_26_01.bin"]

    monkeypatch.setattr(
        "gui.firmware.firmware_dock.UnidenFtpClient", lambda _ep: _FakeClient()
    )
    worker = _RefreshWorker("uniden_sds100", SENTINEL_FTP)
    captured = []
    worker.finished_with_data.connect(lambda *args: captured.append(args))
    worker.run()
    assert captured[0][3] == ""
    assert len(captured[0][0]) == 1


def test_refresh_worker_run_failure(monkeypatch):
    from firmware.ftp_client import SENTINEL_FTP
    from gui.firmware.firmware_dock import _RefreshWorker

    class _BrokenClient:
        def listing(self):
            raise OSError("network down")

    monkeypatch.setattr(
        "gui.firmware.firmware_dock.UnidenFtpClient", lambda _ep: _BrokenClient()
    )
    worker = _RefreshWorker("uniden_sds100", SENTINEL_FTP)
    captured = []
    worker.finished_with_data.connect(lambda *args: captured.append(args))
    worker.run()
    assert captured[0][0] == []
    assert "network down" in captured[0][3]


def test_download_worker_run_success(monkeypatch, tmp_path):
    from firmware.ftp_client import SENTINEL_FTP
    from gui.firmware.firmware_dock import _DownloadWorker

    version = FirmwareVersion.parse("SDS-100_V1_26_01.bin")
    cache = FirmwareCache(root=tmp_path / "cache")

    class _FakeClient:
        def download(self, _name, dest, progress_cb=None):
            Path(dest).write_bytes(b"DOWNLOADED-FW")
            if progress_cb:
                progress_cb(14, 14)

    monkeypatch.setattr(
        "gui.firmware.firmware_dock.UnidenFtpClient", lambda _ep: _FakeClient()
    )
    worker = _DownloadWorker(SENTINEL_FTP, "uniden_sds100", version, cache)
    results = []
    worker.done.connect(lambda ok, msg: results.append((ok, msg)))
    worker.run()
    assert results[0][0] is True
    assert cache.has("uniden_sds100", version)


def test_download_worker_run_failure(monkeypatch, tmp_path):
    from firmware.ftp_client import SENTINEL_FTP
    from gui.firmware.firmware_dock import _DownloadWorker

    version = FirmwareVersion.parse("SDS-100_V1_26_01.bin")
    cache = FirmwareCache(root=tmp_path / "cache")

    class _BrokenClient:
        def download(self, *_a, **_k):
            raise RuntimeError("xfer failed")

    monkeypatch.setattr(
        "gui.firmware.firmware_dock.UnidenFtpClient", lambda _ep: _BrokenClient()
    )
    worker = _DownloadWorker(SENTINEL_FTP, "uniden_sds100", version, cache)
    results = []
    worker.done.connect(lambda ok, msg: results.append((ok, msg)))
    worker.run()
    assert results[0][0] is False
    assert "xfer failed" in results[0][1]


def test_hpdb_download_worker_run(monkeypatch, tmp_path):
    from firmware.ftp_client import SENTINEL_FTP
    from gui.firmware.firmware_dock import _HpdbDownloadWorker

    version = HpdbVersion.parse("MasterHpdb_05_03_2026.gz")
    staging = tmp_path / "hpdb"

    class _FakeClient:
        def download(self, _name, dest, progress_cb=None):
            Path(dest).write_bytes(b"GZIP")
            if progress_cb:
                progress_cb(4, 4)

    monkeypatch.setattr(
        "gui.firmware.firmware_dock.UnidenFtpClient", lambda _ep: _FakeClient()
    )
    worker = _HpdbDownloadWorker(SENTINEL_FTP, version, staging)
    results = []
    worker.done.connect(lambda ok, msg: results.append((ok, msg)))
    worker.run()
    assert results[0][0] is True
    assert Path(results[0][1]).exists()


def test_firmware_dock_on_progress(qtbot):
    dock = FirmwareDock()
    qtbot.addWidget(dock)
    dock._on_progress(50, 100)
    assert dock._progress.value() == 50
    dock._on_progress(0, 0)
    assert dock._progress.minimum() == 0 and dock._progress.maximum() == 0


def test_firmware_dock_open_cache(qtbot, monkeypatch, sds_profile, device, tmp_path):
    dock = FirmwareDock()
    qtbot.addWidget(dock)
    dock._cache = FirmwareCache(root=tmp_path / "cache")
    dock.set_active_device(device, sds_profile)
    opened = []
    monkeypatch.setattr(os, "startfile", lambda p: opened.append(p))
    qtbot.mouseClick(dock._open_cache_btn, Qt.MouseButton.LeftButton)
    assert opened


def test_firmware_dock_device_without_sd_path(qtbot, sds_profile):
    dock = FirmwareDock()
    qtbot.addWidget(dock)
    dev = Device.make("uniden_sds100", "No card", sd_card_path="")
    dock.set_active_device(dev, sds_profile)
    assert "sd card path" in dock._current_label.text().lower()


def test_firmware_dock_stage_without_selection(qtbot, monkeypatch, sds_profile, device, tmp_path):
    from PySide6.QtWidgets import QMessageBox

    dock = FirmwareDock()
    qtbot.addWidget(dock)
    monkeypatch.setenv("SCANNER_MANAGER_VIRTUAL_SD_ROOT", str(tmp_path / "vcards"))
    dock.set_active_device(device, sds_profile)
    calls = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: calls.append(a))
    qtbot.mouseClick(dock._stage_btn, Qt.MouseButton.LeftButton)
    assert calls


def test_firmware_dock_discard_staged(qtbot, monkeypatch, sds_profile, device, tmp_path, auto_msgbox):
    from virtual_sd import StageKind

    monkeypatch.setenv("SCANNER_MANAGER_VIRTUAL_SD_ROOT", str(tmp_path / "vcards"))
    dock = FirmwareDock()
    qtbot.addWidget(dock)
    cache_root = tmp_path / "cache"
    dock._cache = FirmwareCache(root=cache_root)
    dock.set_active_device(device, sds_profile)

    main_v = FirmwareVersion.parse("SDS-100_V1_26_01.bin")
    cached_path = cache_root / sds_profile.id / main_v.filename
    cached_path.parent.mkdir(parents=True, exist_ok=True)
    cached_path.write_bytes(b"FW")
    dock._virtual_card.stage(
        cached_path,
        f"BCDx36HP/firmware/{cached_path.name}",
        StageKind.MAIN_FIRMWARE,
        source_label=cached_path.name,
    )
    dock._refresh_pending_view()
    item = dock._pending_tree.topLevelItem(0)
    dock._pending_tree.setCurrentItem(item)
    qtbot.mouseClick(dock._discard_btn, Qt.MouseButton.LeftButton)
    assert dock._pending_tree.topLevelItemCount() == 0


def test_firmware_dock_discard_all_staged(
    qtbot, monkeypatch, sds_profile, device, tmp_path, auto_msgbox
):
    from virtual_sd import StageKind

    monkeypatch.setenv("SCANNER_MANAGER_VIRTUAL_SD_ROOT", str(tmp_path / "vcards"))
    dock = FirmwareDock()
    qtbot.addWidget(dock)
    cache_root = tmp_path / "cache"
    dock._cache = FirmwareCache(root=cache_root)
    dock.set_active_device(device, sds_profile)

    main_v = FirmwareVersion.parse("SDS-100_V1_26_01.bin")
    cached_path = cache_root / sds_profile.id / main_v.filename
    cached_path.parent.mkdir(parents=True, exist_ok=True)
    cached_path.write_bytes(b"FW")
    dock._virtual_card.stage(
        cached_path,
        f"BCDx36HP/firmware/{cached_path.name}",
        StageKind.MAIN_FIRMWARE,
        source_label=cached_path.name,
    )
    dock._refresh_pending_view()
    qtbot.mouseClick(dock._discard_all_btn, Qt.MouseButton.LeftButton)
    assert dock._pending_tree.topLevelItemCount() == 0


def test_firmware_dock_bt885_endpoint_label(qtbot):
    dock = FirmwareDock()
    qtbot.addWidget(dock)
    bt = get_profile("uniden_bt885")
    label = dock._endpoint_label_for_profile(bt)
    assert "ftp.uniden.com" in label


def test_firmware_dock_log_emits_status(qtbot):
    dock = FirmwareDock()
    qtbot.addWidget(dock)
    messages = []
    dock.statusMessage.connect(messages.append)
    dock._log("hello firmware")
    assert messages == ["hello firmware"]
    assert dock._log_label.text() == "hello firmware"


def test_firmware_dock_mock_download_flow(
    qtbot, monkeypatch, sds_profile, device, tmp_path, auto_msgbox
):
    from gui.firmware.firmware_dock import _DownloadWorker

    dock = FirmwareDock()
    qtbot.addWidget(dock)
    dock._cache = FirmwareCache(root=tmp_path / "cache")
    dock.set_active_device(device, sds_profile)

    main_v = FirmwareVersion.parse("SDS-100_V1_26_01.bin")
    dock._mains = [main_v]
    dock._fill_main_tree()
    dock._main_tree.topLevelItem(0).setSelected(True)
    dock._on_selection_changed()

    class _InstantWorker(_DownloadWorker):
        def start(self):
            self.done.emit(True, str(tmp_path / "ok"))

    monkeypatch.setattr(
        "gui.firmware.firmware_dock._DownloadWorker", _InstantWorker
    )
    qtbot.mouseClick(dock._download_btn, Qt.MouseButton.LeftButton)
    assert "Download complete" in dock._log_label.text() or dock._progress.value() == 0


def test_firmware_dock_stage_sub_firmware(
    qtbot, monkeypatch, sds_profile, device, tmp_path, auto_msgbox
):
    from virtual_sd import StageKind

    monkeypatch.setenv("SCANNER_MANAGER_VIRTUAL_SD_ROOT", str(tmp_path / "vcards"))
    dock = FirmwareDock()
    qtbot.addWidget(dock)
    cache_root = tmp_path / "cache"
    dock._cache = FirmwareCache(root=cache_root)
    dock.set_active_device(device, sds_profile)

    sub_v = FirmwareVersion.parse("SDS-100-SUB_V1_03_15.firm")
    cached_path = cache_root / sds_profile.id / sub_v.filename
    cached_path.parent.mkdir(parents=True, exist_ok=True)
    cached_path.write_bytes(b"SUB-FW")
    dock._cache.store(sds_profile.id, sub_v, b"SUB-FW")
    dock._subs = [sub_v]
    dock._fill_sub_tree()
    dock._sub_tree.topLevelItem(0).setSelected(True)
    dock._tabs.setCurrentIndex(1)
    qtbot.mouseClick(dock._stage_btn, Qt.MouseButton.LeftButton)
    assert dock._pending_tree.topLevelItemCount() == 1


def test_firmware_dock_apply_staged_via_button(
    qtbot, monkeypatch, sds_profile, device, tmp_path, auto_msgbox
):
    from virtual_sd import StageKind

    monkeypatch.setenv("SCANNER_MANAGER_VIRTUAL_SD_ROOT", str(tmp_path / "vcards"))
    dock = FirmwareDock()
    qtbot.addWidget(dock)
    cache_root = tmp_path / "cache"
    dock._cache = FirmwareCache(root=cache_root)
    dock.set_active_device(device, sds_profile)

    main_v = FirmwareVersion.parse("SDS-100_V1_26_01.bin")
    cached_path = cache_root / sds_profile.id / main_v.filename
    cached_path.parent.mkdir(parents=True, exist_ok=True)
    cached_path.write_bytes(b"APPLY-ME")
    dock._virtual_card.stage(
        cached_path,
        f"BCDx36HP/firmware/{cached_path.name}",
        StageKind.MAIN_FIRMWARE,
        source_label=cached_path.name,
    )
    dock._refresh_pending_view()
    qtbot.mouseClick(dock._apply_btn, Qt.MouseButton.LeftButton)
    landed = Path(device.sd_card_path) / "BCDx36HP" / "firmware" / cached_path.name
    assert landed.exists()


def test_firmware_dock_update_wizard_main_path(
    qtbot, monkeypatch, sds_profile, device, tmp_path, auto_msgbox
):
    from firmware.updater import PreflightResult

    dock = FirmwareDock()
    qtbot.addWidget(dock)
    cache_root = tmp_path / "cache"
    dock._cache = FirmwareCache(root=cache_root)
    dock.set_active_device(device, sds_profile)

    main_v = FirmwareVersion.parse("SDS-100_V1_26_01.bin")
    cached_path = cache_root / sds_profile.id / main_v.filename
    cached_path.parent.mkdir(parents=True, exist_ok=True)
    cached_path.write_bytes(b"WIZ-FW")
    dock._cache.store(sds_profile.id, main_v, b"WIZ-FW")
    dock._mains = [main_v]
    dock._fill_main_tree()
    dock._main_tree.topLevelItem(0).setSelected(True)
    dock._on_selection_changed()

    monkeypatch.setattr(
        "gui.firmware.firmware_dock.preflight",
        lambda *a, **k: PreflightResult(ok=True, reason=""),
    )
    monkeypatch.setattr(
        "gui.firmware.firmware_dock.backup_card",
        lambda card: card / "backup",
    )
    monkeypatch.setattr(
        "gui.firmware.firmware_dock.apply_main_firmware",
        lambda card, cache, fam, ver: card / "BCDx36HP" / "firmware" / ver.filename,
    )
    monkeypatch.setattr(
        "gui.firmware.firmware_dock.postflash_verify",
        lambda *a, **k: (True, "ok"),
    )
    qtbot.mouseClick(dock._update_btn, Qt.MouseButton.LeftButton)
    assert "verify" in dock._log_label.text().lower() or "main firmware" in dock._log_label.text().lower()


def test_firmware_dock_update_wizard_sub_path(
    qtbot, monkeypatch, sds_profile, device, tmp_path, auto_msgbox
):
    from firmware.updater import PreflightResult

    dock = FirmwareDock()
    qtbot.addWidget(dock)
    cache_root = tmp_path / "cache"
    dock._cache = FirmwareCache(root=cache_root)
    dock.set_active_device(device, sds_profile)
    sub_v = FirmwareVersion.parse("SDS-100-SUB_V1_03_15.firm")
    dock._cache.store(sds_profile.id, sub_v, b"SUB")
    dock._subs = [sub_v]
    dock._fill_sub_tree()
    dock._sub_tree.topLevelItem(0).setSelected(True)
    dock._tabs.setCurrentIndex(1)
    dock._on_selection_changed()
    monkeypatch.setattr(
        "gui.firmware.firmware_dock.preflight",
        lambda *a, **k: PreflightResult(ok=True, reason=""),
    )
    monkeypatch.setattr(
        "gui.firmware.firmware_dock.backup_card",
        lambda card: card / "backup",
    )
    monkeypatch.setattr(
        "gui.firmware.firmware_dock.apply_sub_firmware",
        lambda card, cache, fam, ver: card / "BCDx36HP" / "firmware" / "sub" / ver.filename,
    )
    monkeypatch.setattr(
        "gui.firmware.firmware_dock.postflash_verify",
        lambda *a, **k: (True, "ok"),
    )
    qtbot.mouseClick(dock._update_btn, Qt.MouseButton.LeftButton)
    assert "sub firmware" in dock._log_label.text().lower() or "verify" in dock._log_label.text().lower()


def test_firmware_dock_virtual_card_required_without_device(qtbot, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    dock = FirmwareDock()
    qtbot.addWidget(dock)
    calls = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: calls.append(a))
    assert dock._virtual_card_required() is None
    assert calls


def test_firmware_dock_request_close_waits_on_workers(
    qtbot, monkeypatch, sds_profile, device
):
    from gui.firmware.firmware_dock import _RefreshWorker

    dock = FirmwareDock()
    qtbot.addWidget(dock)
    dock.set_active_device(device, sds_profile)

    class _SlowWorker(_RefreshWorker):
        def isRunning(self):
            return False

        def wait(self, _ms):
            return True

    dock._refresh_worker = _SlowWorker("uniden_sds100", dock._endpoint_for_profile(sds_profile))
    assert dock.request_close() is True


def test_firmware_dock_preflight_failure_stops_wizard(
    qtbot, monkeypatch, sds_profile, device, tmp_path, auto_msgbox
):
    from firmware.updater import PreflightResult

    dock = FirmwareDock()
    qtbot.addWidget(dock)
    cache_root = tmp_path / "cache"
    dock._cache = FirmwareCache(root=cache_root)
    dock.set_active_device(device, sds_profile)
    main_v = FirmwareVersion.parse("SDS-100_V1_26_01.bin")
    dock._cache.store(sds_profile.id, main_v, b"FW")
    dock._mains = [main_v]
    dock._fill_main_tree()
    dock._main_tree.topLevelItem(0).setSelected(True)
    dock._on_selection_changed()
    monkeypatch.setattr(
        "gui.firmware.firmware_dock.preflight",
        lambda *a, **k: PreflightResult(ok=False, reason="bad card"),
    )
    qtbot.mouseClick(dock._update_btn, Qt.MouseButton.LeftButton)


def test_firmware_dock_hpdb_apply_background(
    qtbot, monkeypatch, sds_profile, device, tmp_path, auto_msgbox
):
    from gui.firmware.firmware_dock import _HpdbDownloadWorker

    dock = FirmwareDock()
    qtbot.addWidget(dock)
    dock._cache = FirmwareCache(root=tmp_path / "cache")
    dock.set_active_device(device, sds_profile)
    hpdb_v = HpdbVersion.parse("MasterHpdb_05_03_2026.gz")
    dock._hpdbs = [hpdb_v]
    dock._fill_hpdb_tree()
    dock._hpdb_tree.topLevelItem(0).setSelected(True)
    dock._tabs.setCurrentIndex(2)

    class _InstantHpdbWorker(_HpdbDownloadWorker):
        def start(self):
            staging = self._staging
            target = staging / self._version.filename
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"GZIP")
            self.done.emit(True, str(target))

    monkeypatch.setattr(
        "gui.firmware.firmware_dock._HpdbDownloadWorker", _InstantHpdbWorker
    )
    monkeypatch.setattr(
        "gui.firmware.firmware_dock.apply_hpdb",
        lambda card, path, version=None: card / "BCDx36HP" / "HPDB" / path.name,
    )
    monkeypatch.setattr(
        "gui.firmware.firmware_dock.backup_card",
        lambda card: card / "backup",
    )
    qtbot.mouseClick(dock._update_btn, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: "HPDB" in dock._log_label.text(), timeout=3000)


def test_firmware_dock_on_download_done_failure(qtbot, sds_profile, device, auto_msgbox):
    dock = FirmwareDock()
    qtbot.addWidget(dock)
    dock.set_active_device(device, sds_profile)
    dock._on_download_done(False, "network error")
    assert "Download failed" in dock._log_label.text()


def test_firmware_dock_populate_current_bad_scanner_inf(qtbot, sds_profile, tmp_path):
    dock = FirmwareDock()
    qtbot.addWidget(dock)
    bad_card = tmp_path / "bad"
    bad_card.mkdir()
    dev = Device.make("uniden_sds100", "Bad", sd_card_path=str(bad_card))
    dock.set_active_device(dev, sds_profile)
    assert "could not be read" in dock._current_label.text().lower()


def test_firmware_dock_stage_hpdb_not_downloaded(qtbot, monkeypatch, sds_profile, device, tmp_path):
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setenv("SCANNER_MANAGER_VIRTUAL_SD_ROOT", str(tmp_path / "vcards"))
    dock = FirmwareDock()
    qtbot.addWidget(dock)
    dock.set_active_device(device, sds_profile)
    hpdb_v = HpdbVersion.parse("MasterHpdb_05_03_2026.gz")
    dock._hpdbs = [hpdb_v]
    dock._fill_hpdb_tree()
    dock._hpdb_tree.topLevelItem(0).setSelected(True)
    dock._tabs.setCurrentIndex(2)
    calls = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: calls.append(a))
    qtbot.mouseClick(dock._stage_btn, Qt.MouseButton.LeftButton)
    assert calls


def test_firmware_dock_update_wizard_no_sd_shows_message(qtbot, sds_profile, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    dock = FirmwareDock()
    qtbot.addWidget(dock)
    dev = Device.make("uniden_sds100", "No card", sd_card_path="")
    dock.set_active_device(dev, sds_profile)
    calls = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: calls.append(a))
    dock._on_run_update_wizard()
    assert calls


def test_firmware_dock_open_cache_non_windows(qtbot, monkeypatch, sds_profile, device, tmp_path):
    import subprocess

    dock = FirmwareDock()
    qtbot.addWidget(dock)
    dock._cache = FirmwareCache(root=tmp_path / "cache")
    dock.set_active_device(device, sds_profile)
    monkeypatch.setattr(sys, "platform", "linux")
    launched = []
    monkeypatch.setattr(subprocess, "Popen", lambda args: launched.append(args))
    dock._on_open_cache()
    assert launched


def test_hpdb_download_worker_run_failure(monkeypatch, tmp_path):
    from firmware.ftp_client import SENTINEL_FTP
    from gui.firmware.firmware_dock import _HpdbDownloadWorker

    version = HpdbVersion.parse("MasterHpdb_05_03_2026.gz")

    class _BrokenClient:
        def download(self, *_a, **_k):
            raise OSError("hpdb xfer failed")

    monkeypatch.setattr(
        "gui.firmware.firmware_dock.UnidenFtpClient", lambda _ep: _BrokenClient()
    )
    worker = _HpdbDownloadWorker(SENTINEL_FTP, version, tmp_path / "hpdb")
    results = []
    worker.done.connect(lambda ok, msg: results.append((ok, msg)))
    worker.run()
    assert results[0][0] is False
    assert "hpdb xfer failed" in results[0][1]


def test_firmware_dock_deferred_card_context_hidden_parent(
    qtbot, sds_profile, device, tmp_path
):
    """Hidden parent dock defers virtual-card load until shown."""
    from PySide6.QtWidgets import QWidget

    parent = QWidget()
    parent.hide()
    qtbot.addWidget(parent)
    dock = FirmwareDock(parent=parent)
    qtbot.addWidget(dock)
    dock.hide()
    dock.set_active_device(device, sds_profile)
    assert "load when the firmware window is opened" in dock._current_label.text()
    assert not dock._stage_btn.isEnabled()
    dock.on_firmware_window_shown()
    assert dock._virtual_card is not None


def test_firmware_dock_deferred_card_no_sd_path(qtbot, sds_profile):
    from PySide6.QtWidgets import QWidget

    parent = QWidget()
    parent.hide()
    qtbot.addWidget(parent)
    dock = FirmwareDock(parent=parent)
    qtbot.addWidget(dock)
    dock.hide()
    dev = Device.make("uniden_sds100", "No card", sd_card_path="")
    dock.set_active_device(dev, sds_profile)
    assert "sd card path configured" in dock._current_label.text().lower()
    assert not dock._stage_btn.isEnabled()


def test_firmware_dock_virtual_card_open_failure(
    qtbot, monkeypatch, sds_profile, device, auto_msgbox
):
    dock = FirmwareDock()
    qtbot.addWidget(dock)

    def _boom(_dev):
        raise RuntimeError("vcard broken")

    monkeypatch.setattr(
        "gui.firmware.firmware_dock.VirtualCard.from_device", _boom
    )
    dock.set_active_device(device, sds_profile)
    assert dock._virtual_card is None
    calls = []
    monkeypatch.setattr(
        __import__("PySide6.QtWidgets", fromlist=["QMessageBox"]).QMessageBox,
        "information",
        lambda *a, **k: calls.append(a),
    )
    assert dock._virtual_card_required() is None
    assert calls


def test_firmware_dock_scanner_inf_read_exception(
    qtbot, monkeypatch, sds_profile, device
):
    dock = FirmwareDock()
    qtbot.addWidget(dock)

    def _raise(_path):
        raise OSError("read fail")

    monkeypatch.setattr(
        "gui.firmware.firmware_dock.read_scanner_inf", _raise
    )
    dock.set_active_device(device, sds_profile)
    assert "could not be read" in dock._current_label.text().lower()


def test_firmware_dock_refresh_skips_when_worker_running(
    qtbot, sds_profile, device, monkeypatch
):
    from gui.firmware.firmware_dock import _RefreshWorker

    dock = FirmwareDock()
    qtbot.addWidget(dock)
    dock.set_active_device(device, sds_profile)

    class _RunningWorker(_RefreshWorker):
        def isRunning(self):
            return True

    dock._refresh_worker = _RunningWorker("uniden_sds100", dock._endpoint_for_profile(sds_profile))
    dock._on_refresh()
    assert dock._refresh_btn.text() == "Refresh from Uniden"


def test_firmware_dock_fill_trees_without_profile(qtbot):
    dock = FirmwareDock()
    qtbot.addWidget(dock)
    dock._mains = [FirmwareVersion.parse("SDS-100_V1_26_01.bin")]
    dock._subs = [FirmwareVersion.parse("SDS-100-SUB_V1_03_15.firm")]
    dock._hpdbs = [HpdbVersion.parse("MasterHpdb_05_03_2026.gz")]
    dock._fill_main_tree()
    dock._fill_sub_tree()
    assert dock._main_tree.topLevelItemCount() == 0
    assert dock._sub_tree.topLevelItemCount() == 0


def test_firmware_dock_current_version_read_errors(
    qtbot, monkeypatch, sds_profile, device
):
    dock = FirmwareDock()
    qtbot.addWidget(dock)
    dock.set_active_device(device, sds_profile)

    def _raise(_path):
        raise OSError("inf unreadable")

    monkeypatch.setattr(
        "gui.firmware.firmware_dock.read_scanner_inf", _raise
    )
    assert dock._current_main_version() is None
    assert dock._current_sub_version() is None


def test_firmware_dock_download_early_returns(qtbot, sds_profile, device, tmp_path):
    dock = FirmwareDock()
    qtbot.addWidget(dock)
    dock._cache = FirmwareCache(root=tmp_path / "cache")
    dock.set_active_device(device, sds_profile)
    dock._profile = None
    dock._on_download()
    dock._profile = sds_profile
    dock._on_download()
    hpdb_v = HpdbVersion.parse("MasterHpdb_05_03_2026.gz")
    dock._hpdbs = [hpdb_v]
    dock._fill_hpdb_tree()
    dock._hpdb_tree.topLevelItem(0).setSelected(True)
    dock._tabs.setCurrentIndex(2)
    dock._on_download()


def test_firmware_dock_stage_hpdb_downloaded(
    qtbot, monkeypatch, sds_profile, device, tmp_path, auto_msgbox
):
    from virtual_sd import StageKind

    monkeypatch.setenv("SCANNER_MANAGER_VIRTUAL_SD_ROOT", str(tmp_path / "vcards"))
    dock = FirmwareDock()
    qtbot.addWidget(dock)
    cache_root = tmp_path / "cache"
    dock._cache = FirmwareCache(root=cache_root)
    dock.set_active_device(device, sds_profile)

    hpdb_v = HpdbVersion.parse("MasterHpdb_05_03_2026.gz")
    staging = cache_root / "_hpdb_staging"
    staging.mkdir(parents=True)
    (staging / hpdb_v.filename).write_bytes(b"GZIP-DATA")
    dock._hpdbs = [hpdb_v]
    dock._fill_hpdb_tree()
    dock._hpdb_tree.topLevelItem(0).setSelected(True)
    dock._tabs.setCurrentIndex(2)
    qtbot.mouseClick(dock._stage_btn, Qt.MouseButton.LeftButton)
    assert dock._pending_tree.topLevelItemCount() == 1
    item = dock._pending_tree.topLevelItem(0)
    assert item.text(1) == StageKind.HPDB


def test_firmware_dock_stage_not_cached_main(
    qtbot, monkeypatch, sds_profile, device, tmp_path
):
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setenv("SCANNER_MANAGER_VIRTUAL_SD_ROOT", str(tmp_path / "vcards"))
    dock = FirmwareDock()
    qtbot.addWidget(dock)
    dock.set_active_device(device, sds_profile)
    main_v = FirmwareVersion.parse("SDS-100_V1_26_01.bin")
    dock._mains = [main_v]
    dock._fill_main_tree()
    dock._main_tree.topLevelItem(0).setSelected(True)
    calls = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: calls.append(a))
    qtbot.mouseClick(dock._stage_btn, Qt.MouseButton.LeftButton)
    assert calls
    assert dock._pending_tree.topLevelItemCount() == 0


def test_firmware_dock_stage_virtual_card_error(
    qtbot, monkeypatch, sds_profile, device, tmp_path, auto_msgbox
):
    from PySide6.QtWidgets import QMessageBox
    from virtual_sd import VirtualCardError

    monkeypatch.setenv("SCANNER_MANAGER_VIRTUAL_SD_ROOT", str(tmp_path / "vcards"))
    dock = FirmwareDock()
    qtbot.addWidget(dock)
    cache_root = tmp_path / "cache"
    dock._cache = FirmwareCache(root=cache_root)
    dock.set_active_device(device, sds_profile)

    main_v = FirmwareVersion.parse("SDS-100_V1_26_01.bin")
    dock._cache.store(sds_profile.id, main_v, b"FW")
    dock._mains = [main_v]
    dock._fill_main_tree()
    dock._main_tree.topLevelItem(0).setSelected(True)
    dock._on_selection_changed()

    def _fail(*_a, **_k):
        raise VirtualCardError("stage boom")

    monkeypatch.setattr(dock._virtual_card, "stage", _fail)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warnings.append(a))
    dock._on_stage()
    assert warnings


def test_firmware_dock_refresh_pending_no_virtual_card(qtbot):
    dock = FirmwareDock()
    qtbot.addWidget(dock)
    dock._virtual_card = None
    dock._refresh_pending_view()
    assert "not loaded" in dock._pending_label.text()
    assert not dock._apply_btn.isEnabled()


def test_firmware_dock_apply_staged_no_sd_path(
    qtbot, monkeypatch, sds_profile, device, tmp_path, auto_msgbox
):
    from virtual_sd import StageKind

    monkeypatch.setenv("SCANNER_MANAGER_VIRTUAL_SD_ROOT", str(tmp_path / "vcards"))
    dock = FirmwareDock()
    qtbot.addWidget(dock)
    cache_root = tmp_path / "cache"
    dock._cache = FirmwareCache(root=cache_root)
    dock.set_active_device(device, sds_profile)

    main_v = FirmwareVersion.parse("SDS-100_V1_26_01.bin")
    cached_path = cache_root / sds_profile.id / main_v.filename
    cached_path.parent.mkdir(parents=True, exist_ok=True)
    cached_path.write_bytes(b"FW")
    dock._virtual_card.stage(
        cached_path,
        f"BCDx36HP/firmware/{cached_path.name}",
        StageKind.MAIN_FIRMWARE,
        source_label=cached_path.name,
    )
    dock._refresh_pending_view()
    dock._device = Device.make("uniden_sds100", "No card", sd_card_path="")
    calls = []
    monkeypatch.setattr(
        __import__("PySide6.QtWidgets", fromlist=["QMessageBox"]).QMessageBox,
        "information",
        lambda *a, **k: calls.append(a),
    )
    qtbot.mouseClick(dock._apply_btn, Qt.MouseButton.LeftButton)
    assert calls


def test_firmware_dock_apply_staged_user_declines(
    qtbot, monkeypatch, sds_profile, device, tmp_path
):
    from PySide6.QtWidgets import QMessageBox
    from virtual_sd import StageKind

    monkeypatch.setenv("SCANNER_MANAGER_VIRTUAL_SD_ROOT", str(tmp_path / "vcards"))
    dock = FirmwareDock()
    qtbot.addWidget(dock)
    cache_root = tmp_path / "cache"
    dock._cache = FirmwareCache(root=cache_root)
    dock.set_active_device(device, sds_profile)

    main_v = FirmwareVersion.parse("SDS-100_V1_26_01.bin")
    cached_path = cache_root / sds_profile.id / main_v.filename
    cached_path.parent.mkdir(parents=True, exist_ok=True)
    cached_path.write_bytes(b"FW")
    dock._virtual_card.stage(
        cached_path,
        f"BCDx36HP/firmware/{cached_path.name}",
        StageKind.MAIN_FIRMWARE,
        source_label=cached_path.name,
    )
    dock._refresh_pending_view()
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.No)
    qtbot.mouseClick(dock._apply_btn, Qt.MouseButton.LeftButton)
    assert dock._pending_tree.topLevelItemCount() == 1


def test_firmware_dock_apply_staged_virtual_card_error(
    qtbot, monkeypatch, sds_profile, device, tmp_path, auto_msgbox
):
    from virtual_sd import StageKind, VirtualCardError

    monkeypatch.setenv("SCANNER_MANAGER_VIRTUAL_SD_ROOT", str(tmp_path / "vcards"))
    dock = FirmwareDock()
    qtbot.addWidget(dock)
    cache_root = tmp_path / "cache"
    dock._cache = FirmwareCache(root=cache_root)
    dock.set_active_device(device, sds_profile)

    main_v = FirmwareVersion.parse("SDS-100_V1_26_01.bin")
    cached_path = cache_root / sds_profile.id / main_v.filename
    cached_path.parent.mkdir(parents=True, exist_ok=True)
    cached_path.write_bytes(b"FW")
    dock._virtual_card.stage(
        cached_path,
        f"BCDx36HP/firmware/{cached_path.name}",
        StageKind.MAIN_FIRMWARE,
        source_label=cached_path.name,
    )
    dock._refresh_pending_view()

    def _fail(_path):
        raise VirtualCardError("apply boom")

    monkeypatch.setattr(dock._virtual_card, "apply_to_physical", _fail)
    qtbot.mouseClick(dock._apply_btn, Qt.MouseButton.LeftButton)


def test_firmware_dock_discard_staged_no_selection(qtbot, monkeypatch, sds_profile, device, tmp_path):
    monkeypatch.setenv("SCANNER_MANAGER_VIRTUAL_SD_ROOT", str(tmp_path / "vcards"))
    dock = FirmwareDock()
    qtbot.addWidget(dock)
    dock.set_active_device(device, sds_profile)
    dock._pending_tree.setCurrentItem(None)
    dock._on_discard_staged()
    assert dock._pending_tree.topLevelItemCount() == 0


def test_firmware_dock_discard_all_user_declines(
    qtbot, monkeypatch, sds_profile, device, tmp_path
):
    from PySide6.QtWidgets import QMessageBox
    from virtual_sd import StageKind

    monkeypatch.setenv("SCANNER_MANAGER_VIRTUAL_SD_ROOT", str(tmp_path / "vcards"))
    dock = FirmwareDock()
    qtbot.addWidget(dock)
    cache_root = tmp_path / "cache"
    dock._cache = FirmwareCache(root=cache_root)
    dock.set_active_device(device, sds_profile)

    main_v = FirmwareVersion.parse("SDS-100_V1_26_01.bin")
    cached_path = cache_root / sds_profile.id / main_v.filename
    cached_path.parent.mkdir(parents=True, exist_ok=True)
    cached_path.write_bytes(b"FW")
    dock._virtual_card.stage(
        cached_path,
        f"BCDx36HP/firmware/{cached_path.name}",
        StageKind.MAIN_FIRMWARE,
        source_label=cached_path.name,
    )
    dock._refresh_pending_view()
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.No)
    qtbot.mouseClick(dock._discard_all_btn, Qt.MouseButton.LeftButton)
    assert dock._pending_tree.topLevelItemCount() == 1


def test_firmware_dock_discard_all_empty_pending(qtbot, monkeypatch, sds_profile, device, tmp_path):
    monkeypatch.setenv("SCANNER_MANAGER_VIRTUAL_SD_ROOT", str(tmp_path / "vcards"))
    dock = FirmwareDock()
    qtbot.addWidget(dock)
    dock.set_active_device(device, sds_profile)
    qtbot.mouseClick(dock._discard_all_btn, Qt.MouseButton.LeftButton)
    assert dock._pending_tree.topLevelItemCount() == 0


def test_firmware_dock_backup_failure_stops_wizard(
    qtbot, monkeypatch, sds_profile, device, tmp_path, auto_msgbox
):
    from firmware.updater import FirmwareError, PreflightResult

    dock = FirmwareDock()
    qtbot.addWidget(dock)
    cache_root = tmp_path / "cache"
    dock._cache = FirmwareCache(root=cache_root)
    dock.set_active_device(device, sds_profile)
    main_v = FirmwareVersion.parse("SDS-100_V1_26_01.bin")
    dock._cache.store(sds_profile.id, main_v, b"FW")
    dock._mains = [main_v]
    dock._fill_main_tree()
    dock._main_tree.topLevelItem(0).setSelected(True)
    dock._on_selection_changed()
    monkeypatch.setattr(
        "gui.firmware.firmware_dock.preflight",
        lambda *a, **k: PreflightResult(ok=True, reason=""),
    )

    def _backup_fail(_card):
        raise FirmwareError("backup failed")

    monkeypatch.setattr("gui.firmware.firmware_dock.backup_card", _backup_fail)
    qtbot.mouseClick(dock._update_btn, Qt.MouseButton.LeftButton)


def test_firmware_dock_postflash_verify_failure(
    qtbot, monkeypatch, sds_profile, device, tmp_path, auto_msgbox
):
    from firmware.updater import PreflightResult

    dock = FirmwareDock()
    qtbot.addWidget(dock)
    cache_root = tmp_path / "cache"
    dock._cache = FirmwareCache(root=cache_root)
    dock.set_active_device(device, sds_profile)
    main_v = FirmwareVersion.parse("SDS-100_V1_26_01.bin")
    dock._cache.store(sds_profile.id, main_v, b"FW")
    dock._mains = [main_v]
    dock._fill_main_tree()
    dock._main_tree.topLevelItem(0).setSelected(True)
    dock._on_selection_changed()
    monkeypatch.setattr(
        "gui.firmware.firmware_dock.preflight",
        lambda *a, **k: PreflightResult(ok=True, reason=""),
    )
    monkeypatch.setattr(
        "gui.firmware.firmware_dock.backup_card",
        lambda card: card / "backup",
    )
    monkeypatch.setattr(
        "gui.firmware.firmware_dock.apply_main_firmware",
        lambda card, cache, fam, ver: card / "BCDx36HP" / "firmware" / ver.filename,
    )
    monkeypatch.setattr(
        "gui.firmware.firmware_dock.postflash_verify",
        lambda *a, **k: (False, "version mismatch"),
    )
    qtbot.mouseClick(dock._update_btn, Qt.MouseButton.LeftButton)
    assert "version mismatch" in dock._log_label.text().lower()


def test_firmware_dock_update_wizard_user_declines_confirm(
    qtbot, monkeypatch, sds_profile, device, tmp_path
):
    from PySide6.QtWidgets import QMessageBox
    from firmware.updater import PreflightResult

    dock = FirmwareDock()
    qtbot.addWidget(dock)
    cache_root = tmp_path / "cache"
    dock._cache = FirmwareCache(root=cache_root)
    dock.set_active_device(device, sds_profile)
    main_v = FirmwareVersion.parse("SDS-100_V1_26_01.bin")
    dock._cache.store(sds_profile.id, main_v, b"FW")
    dock._mains = [main_v]
    dock._fill_main_tree()
    dock._main_tree.topLevelItem(0).setSelected(True)
    dock._on_selection_changed()
    monkeypatch.setattr(
        "gui.firmware.firmware_dock.preflight",
        lambda *a, **k: PreflightResult(ok=True, reason=""),
    )
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.No)
    qtbot.mouseClick(dock._update_btn, Qt.MouseButton.LeftButton)


def test_firmware_dock_update_wizard_apply_firmware_error(
    qtbot, monkeypatch, sds_profile, device, tmp_path, auto_msgbox
):
    from firmware.updater import FirmwareError, PreflightResult

    dock = FirmwareDock()
    qtbot.addWidget(dock)
    cache_root = tmp_path / "cache"
    dock._cache = FirmwareCache(root=cache_root)
    dock.set_active_device(device, sds_profile)
    main_v = FirmwareVersion.parse("SDS-100_V1_26_01.bin")
    dock._cache.store(sds_profile.id, main_v, b"FW")
    dock._mains = [main_v]
    dock._fill_main_tree()
    dock._main_tree.topLevelItem(0).setSelected(True)
    dock._on_selection_changed()
    monkeypatch.setattr(
        "gui.firmware.firmware_dock.preflight",
        lambda *a, **k: PreflightResult(ok=True, reason=""),
    )
    monkeypatch.setattr(
        "gui.firmware.firmware_dock.backup_card",
        lambda card: card / "backup",
    )

    def _apply_fail(*_a, **_k):
        raise FirmwareError("apply failed")

    monkeypatch.setattr(
        "gui.firmware.firmware_dock.apply_main_firmware", _apply_fail
    )
    qtbot.mouseClick(dock._update_btn, Qt.MouseButton.LeftButton)


def test_firmware_dock_hpdb_download_failure_in_wizard(
    qtbot, monkeypatch, sds_profile, device, tmp_path, auto_msgbox
):
    from gui.firmware.firmware_dock import _HpdbDownloadWorker

    dock = FirmwareDock()
    qtbot.addWidget(dock)
    dock._cache = FirmwareCache(root=tmp_path / "cache")
    dock.set_active_device(device, sds_profile)
    hpdb_v = HpdbVersion.parse("MasterHpdb_05_03_2026.gz")
    dock._hpdbs = [hpdb_v]
    dock._fill_hpdb_tree()
    dock._hpdb_tree.topLevelItem(0).setSelected(True)
    dock._tabs.setCurrentIndex(2)

    class _FailHpdbWorker(_HpdbDownloadWorker):
        def start(self):
            self.done.emit(False, "hpdb network down")

    monkeypatch.setattr(
        "gui.firmware.firmware_dock._HpdbDownloadWorker", _FailHpdbWorker
    )
    qtbot.mouseClick(dock._update_btn, Qt.MouseButton.LeftButton)
    qtbot.wait(100)


def test_firmware_dock_hpdb_apply_firmware_error(
    qtbot, monkeypatch, sds_profile, device, tmp_path, auto_msgbox
):
    from firmware.updater import FirmwareError
    from gui.firmware.firmware_dock import _HpdbDownloadWorker

    dock = FirmwareDock()
    qtbot.addWidget(dock)
    dock._cache = FirmwareCache(root=tmp_path / "cache")
    dock.set_active_device(device, sds_profile)
    hpdb_v = HpdbVersion.parse("MasterHpdb_05_03_2026.gz")
    dock._hpdbs = [hpdb_v]
    dock._fill_hpdb_tree()
    dock._hpdb_tree.topLevelItem(0).setSelected(True)
    dock._tabs.setCurrentIndex(2)

    class _InstantHpdbWorker(_HpdbDownloadWorker):
        def start(self):
            staging = self._staging
            target = staging / self._version.filename
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"GZIP")
            self.done.emit(True, str(target))

    monkeypatch.setattr(
        "gui.firmware.firmware_dock._HpdbDownloadWorker", _InstantHpdbWorker
    )

    def _apply_fail(*_a, **_k):
        raise FirmwareError("hpdb apply failed")

    monkeypatch.setattr("gui.firmware.firmware_dock.apply_hpdb", _apply_fail)
    qtbot.mouseClick(dock._update_btn, Qt.MouseButton.LeftButton)
    qtbot.wait(100)


def test_firmware_dock_open_cache_darwin(qtbot, monkeypatch, sds_profile, device, tmp_path):
    import subprocess

    dock = FirmwareDock()
    qtbot.addWidget(dock)
    dock._cache = FirmwareCache(root=tmp_path / "cache")
    dock.set_active_device(device, sds_profile)
    monkeypatch.setattr(sys, "platform", "darwin")
    launched = []
    monkeypatch.setattr(subprocess, "Popen", lambda args: launched.append(args))
    dock._on_open_cache()
    assert launched == [["open", str(tmp_path / "cache")]]


def test_firmware_dock_open_cache_failure(qtbot, monkeypatch, sds_profile, device, tmp_path):
    from PySide6.QtWidgets import QMessageBox

    dock = FirmwareDock()
    qtbot.addWidget(dock)
    dock._cache = FirmwareCache(root=tmp_path / "cache")
    dock.set_active_device(device, sds_profile)

    def _boom(_path):
        raise OSError("cannot open folder")

    monkeypatch.setattr(os, "startfile", _boom)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warnings.append(a))
    dock._on_open_cache()
    assert warnings


def test_firmware_dock_request_close_waits_running_download_worker(
    qtbot, monkeypatch, sds_profile, device
):
    from gui.firmware.firmware_dock import _DownloadWorker

    dock = FirmwareDock()
    qtbot.addWidget(dock)
    dock.set_active_device(device, sds_profile)
    version = FirmwareVersion.parse("SDS-100_V1_26_01.bin")

    class _SlowDownload(_DownloadWorker):
        def isRunning(self):
            return True

        def wait(self, _ms):
            return True

    dock._download_worker = _SlowDownload(
        dock._endpoint_for_profile(sds_profile),
        sds_profile.id,
        version,
        dock._cache,
    )
    assert dock.request_close() is True


def test_firmware_dock_request_close_waits_running_refresh_worker(
    qtbot, sds_profile, device
):
    from gui.firmware.firmware_dock import _RefreshWorker

    dock = FirmwareDock()
    qtbot.addWidget(dock)
    dock.set_active_device(device, sds_profile)

    class _SlowRefresh(_RefreshWorker):
        def isRunning(self):
            return True

        def wait(self, _ms):
            return True

    dock._refresh_worker = _SlowRefresh("uniden_sds100", dock._endpoint_for_profile(sds_profile))
    assert dock.request_close() is True


def test_firmware_dock_fill_main_tree_current_badge(
    qtbot, sds_profile, device, tmp_path
):
    """Main tree marks the version matching scanner.inf as CURRENT."""
    dock = FirmwareDock()
    qtbot.addWidget(dock)
    dock._cache = FirmwareCache(root=tmp_path / "cache")
    dock.set_active_device(device, sds_profile)
    current = FirmwareVersion.parse("SDS-100_V1_25_99.bin")
    newer = FirmwareVersion.parse("SDS-100_V1_26_01.bin")
    dock._mains = [current, newer]
    dock._fill_main_tree()
    found_current = False
    for i in range(dock._main_tree.topLevelItemCount()):
        item = dock._main_tree.topLevelItem(i)
        if "CURRENT" in item.text(1):
            found_current = True
            assert item.text(0) == "1.25.99"
    assert found_current


def test_firmware_dock_update_wizard_no_selection(qtbot, sds_profile, device, tmp_path):
    dock = FirmwareDock()
    qtbot.addWidget(dock)
    dock._cache = FirmwareCache(root=tmp_path / "cache")
    dock.set_active_device(device, sds_profile)
    dock._main_tree.clearSelection()
    dock._on_run_update_wizard()
