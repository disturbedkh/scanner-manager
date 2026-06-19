"""Tests for the persistent multi-device manifest layer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.device_manager import (
    DEVICES_SCHEMA_VERSION,
    Device,
    DeviceManager,
)


@pytest.fixture
def empty_manager(tmp_path: Path) -> DeviceManager:
    return DeviceManager(devices_path=tmp_path / "devices.json")


def test_empty_manager_returns_no_devices(empty_manager: DeviceManager) -> None:
    assert empty_manager.list_devices() == []
    assert empty_manager.get_default() is None


def test_add_device_persists_and_becomes_default(empty_manager: DeviceManager) -> None:
    device = Device.make(
        scanner_profile_id="uniden_sds100",
        label="SDS100 - Truck",
        sd_card_path="D:\\",
    )
    empty_manager.add_device(device)
    assert len(empty_manager.list_devices()) == 1
    assert empty_manager.get_default().id == device.id

    # Reload from disk to confirm round-trip
    reloaded = DeviceManager(devices_path=empty_manager.path)
    assert len(reloaded.list_devices()) == 1
    assert reloaded.get_default().scanner_profile_id == "uniden_sds100"


def test_unknown_keys_round_trip_via_extra(tmp_path: Path) -> None:
    devices_path = tmp_path / "devices.json"
    devices_path.write_text(
        json.dumps(
            {
                "schema_version": DEVICES_SCHEMA_VERSION,
                "devices": [
                    {
                        "id": "abc",
                        "label": "Future device",
                        "scanner_profile_id": "uniden_bt885",
                        "future_field_x": 42,
                        "nested": {"a": 1},
                    }
                ],
                "default_device_id": "abc",
            }
        ),
        encoding="utf-8",
    )

    mgr = DeviceManager(devices_path=devices_path)
    mgr.save()

    reloaded = json.loads(devices_path.read_text(encoding="utf-8"))
    saved = reloaded["devices"][0]
    assert saved["future_field_x"] == 42
    assert saved["nested"] == {"a": 1}


def test_remove_device_picks_new_default(empty_manager: DeviceManager) -> None:
    a = Device.make("uniden_bt885", "BT885")
    b = Device.make("uniden_sds100", "SDS100")
    empty_manager.add_device(a)
    empty_manager.add_device(b)
    assert empty_manager.get_default().id == a.id

    empty_manager.remove_device(a.id)
    assert empty_manager.get_default().id == b.id


def test_set_default_validates_id(empty_manager: DeviceManager) -> None:
    with pytest.raises(KeyError):
        empty_manager.set_default("nope")


def test_resolve_profile_falls_back_to_default(empty_manager: DeviceManager) -> None:
    device = Device.make(scanner_profile_id="not_a_real_profile", label="Bogus")
    empty_manager.add_device(device)
    profile = device.resolve_profile()
    # get_profile() falls back to the default ID for unknown IDs
    assert profile.id == "uniden_bt885"


def test_detect_device_for_path_normalizes_separator(empty_manager: DeviceManager) -> None:
    device = Device.make(scanner_profile_id="uniden_sds100", label="X", sd_card_path="D:\\")
    empty_manager.add_device(device)
    assert empty_manager.detect_device_for_path("D:\\") is not None
    assert empty_manager.detect_device_for_path("d:\\") is not None
    assert empty_manager.detect_device_for_path("E:\\") is None


def test_auto_create_device_for_unknown_card(tmp_path: Path) -> None:
    """When the path doesn't look like a known scanner, no Device
    is created and the manager stays empty."""
    mgr = DeviceManager(devices_path=tmp_path / "devices.json")
    bogus = tmp_path / "random_dir"
    bogus.mkdir()
    assert mgr.auto_create_device_for_path(str(bogus)) is None
    assert mgr.list_devices() == []


def test_auto_create_device_for_sds100_card(tmp_path: Path) -> None:
    """Mock an SDS100 card on disk and verify the Device is created
    bound to the SDS100 profile."""
    card = tmp_path / "card"
    bcdx = card / "BCDx36HP"
    bcdx.mkdir(parents=True)
    (bcdx / "scanner.inf").write_text(
        "TargetModel\tBCDx36HP\nFormatVersion\t1.00\n"
        "Scanner\tSDS100\t99\t1.23.07\t01\t\t1.00.00\t1.00.00\t0\t1.03.05\n",
        encoding="utf-8",
    )

    mgr = DeviceManager(devices_path=tmp_path / "devices.json")
    device = mgr.auto_create_device_for_path(str(card))
    assert device is not None
    assert device.scanner_profile_id == "uniden_sds100"
    assert device.last_seen is not None
    assert mgr.get_default().id == device.id
