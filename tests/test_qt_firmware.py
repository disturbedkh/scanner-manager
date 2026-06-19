"""Smoke tests for the Phase 5 firmware dock UI."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("pytestqt")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from device_manager import Device  # noqa: E402
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
