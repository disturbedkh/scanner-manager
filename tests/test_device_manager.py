"""Tests for the persistent multi-device manifest layer."""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

from core.device_manager import (
    DEVICES_SCHEMA_VERSION,
    Device,
    DeviceManager,
    _default_devices_path,
    _short_path_label,
    _user_config_path,
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


@pytest.mark.skipif(sys.platform != "win32", reason="Windows drive letters are not valid on this platform")
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


def test_load_invalid_json_leaves_empty_manager(tmp_path: Path) -> None:
    devices_path = tmp_path / "devices.json"
    devices_path.write_text("{not valid json", encoding="utf-8")
    mgr = DeviceManager(devices_path=devices_path)
    assert mgr.list_devices() == []
    assert mgr.get_default() is None


def test_load_non_dict_root_leaves_empty_manager(tmp_path: Path) -> None:
    devices_path = tmp_path / "devices.json"
    devices_path.write_text(json.dumps([]), encoding="utf-8")
    mgr = DeviceManager(devices_path=devices_path)
    assert mgr.list_devices() == []


def test_load_skips_non_dict_device_entries(tmp_path: Path) -> None:
    devices_path = tmp_path / "devices.json"
    devices_path.write_text(
        json.dumps(
            {
                "schema_version": DEVICES_SCHEMA_VERSION,
                "devices": ["bad", {"id": "ok", "label": "Good", "scanner_profile_id": "uniden_bt885"}],
            }
        ),
        encoding="utf-8",
    )
    mgr = DeviceManager(devices_path=devices_path)
    assert len(mgr.list_devices()) == 1
    assert mgr.list_devices()[0].id == "ok"


def test_device_manager_reload_from(tmp_path: Path) -> None:
    default = tmp_path / "default.json"
    alt = tmp_path / "travel.json"
    home = Device.make("uniden_bt885", "Home")
    travel = Device.make("uniden_sds100", "Travel")
    default.write_text(
        json.dumps(
            {
                "schema_version": DEVICES_SCHEMA_VERSION,
                "devices": [home.to_dict()],
                "default_device_id": home.id,
            }
        ),
        encoding="utf-8",
    )
    alt.write_text(
        json.dumps(
            {
                "schema_version": DEVICES_SCHEMA_VERSION,
                "devices": [travel.to_dict()],
                "default_device_id": travel.id,
            }
        ),
        encoding="utf-8",
    )

    mgr = DeviceManager(devices_path=default)
    assert mgr.get_default().label == "Home"

    mgr.reload_from(alt)
    assert mgr.path == alt
    assert mgr.get_default().label == "Travel"


def test_get_device_returns_none_for_unknown_id(empty_manager: DeviceManager) -> None:
    assert empty_manager.get_device("missing") is None


def test_get_device_returns_matching_device(empty_manager: DeviceManager) -> None:
    device = Device.make("uniden_bt885", "BT885")
    empty_manager.add_device(device)
    assert empty_manager.get_device(device.id) is device


def test_list_supported_scanner_profiles(empty_manager: DeviceManager) -> None:
    profiles = empty_manager.list_supported_scanner_profiles()
    assert profiles
    assert all(p.id for p in profiles)


def test_update_device_persists_changes(empty_manager: DeviceManager) -> None:
    device = Device.make("uniden_bt885", "Before")
    empty_manager.add_device(device)
    device.label = "After"
    device.connection_mode = "storage"
    empty_manager.update_device(device)

    reloaded = DeviceManager(devices_path=empty_manager.path)
    saved = reloaded.get_device(device.id)
    assert saved is not None
    assert saved.label == "After"
    assert saved.connection_mode == "storage"


def test_update_device_raises_for_unknown_id(empty_manager: DeviceManager) -> None:
    device = Device.make("uniden_bt885", "Ghost")
    with pytest.raises(KeyError, match="not registered"):
        empty_manager.update_device(device)


def test_set_default_persists_second_device(empty_manager: DeviceManager) -> None:
    first = Device.make("uniden_bt885", "First")
    second = Device.make("uniden_sds100", "Second")
    empty_manager.add_device(first)
    empty_manager.add_device(second)
    empty_manager.set_default(second.id)

    reloaded = DeviceManager(devices_path=empty_manager.path)
    assert reloaded.get_default().id == second.id


def test_remove_last_device_clears_default(empty_manager: DeviceManager) -> None:
    device = Device.make("uniden_bt885", "Only")
    empty_manager.add_device(device)
    empty_manager.remove_device(device.id)
    assert empty_manager.list_devices() == []
    assert empty_manager.get_default() is None


def test_get_default_when_stored_default_missing(tmp_path: Path) -> None:
    devices_path = tmp_path / "devices.json"
    device = Device.make("uniden_bt885", "Fallback")
    devices_path.write_text(
        json.dumps(
            {
                "schema_version": DEVICES_SCHEMA_VERSION,
                "devices": [device.to_dict()],
                "default_device_id": "gone",
            }
        ),
        encoding="utf-8",
    )
    mgr = DeviceManager(devices_path=devices_path)
    assert mgr.get_default().id == device.id


def test_detect_device_for_path_empty_returns_none(empty_manager: DeviceManager) -> None:
    assert empty_manager.detect_device_for_path("") is None


def test_device_from_dict_defaults() -> None:
    generated_id = str(uuid.uuid4())
    with patch("core.device_manager.uuid.uuid4", return_value=uuid.UUID(generated_id)):
        device = Device.from_dict({"scanner_profile_id": "uniden_bt885"})
    assert device.id == generated_id
    assert device.label == "Unnamed device"
    assert device.connection_mode == "auto"

    empty_mode = Device.from_dict({"connection_mode": ""})
    assert empty_mode.connection_mode == "auto"


def test_device_to_dict_includes_extra() -> None:
    device = Device.make("uniden_bt885", "Extra")
    device.extra = {"future_field_x": 42}
    saved = device.to_dict()
    assert saved["future_field_x"] == 42


def test_device_update_seen() -> None:
    device = Device.make("uniden_bt885", "Seen")
    assert device.last_seen is None
    device.update_seen()
    assert device.last_seen is not None
    assert device.last_seen.endswith("+00:00")


def test_auto_create_device_uses_label_prefix(tmp_path: Path) -> None:
    card = tmp_path / "card"
    bcdx = card / "BCDx36HP"
    bcdx.mkdir(parents=True)
    (bcdx / "scanner.inf").write_text(
        "TargetModel\tBCDx36HP\nFormatVersion\t1.00\n"
        "Scanner\tSDS100\t99\t1.23.07\t01\t\t1.00.00\t1.00.00\t0\t1.03.05\n",
        encoding="utf-8",
    )
    mgr = DeviceManager(devices_path=tmp_path / "devices.json")
    device = mgr.auto_create_device_for_path(str(card), label_prefix="My Scanner")
    assert device is not None
    assert device.label == "My Scanner"


def test_short_path_label_empty_and_windows_root() -> None:
    assert _short_path_label("") == ""
    if sys.platform == "win32":
        assert _short_path_label("D:\\") == "D:\\"
    assert _short_path_label("/media/sdcard/BCDx36HP") == "BCDx36HP"


def test_user_config_path_win32(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.delenv("SCANNER_MANAGER_CONFIG_DIR", raising=False)
    assert _user_config_path() == tmp_path / "Roaming" / "scanner-manager" / "devices.json"


def test_user_config_path_darwin(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.delenv("SCANNER_MANAGER_CONFIG_DIR", raising=False)
    assert _user_config_path() == (
        tmp_path / "Library" / "Application Support" / "scanner-manager" / "devices.json"
    )


def test_user_config_path_linux(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.delenv("SCANNER_MANAGER_CONFIG_DIR", raising=False)
    assert _user_config_path() == tmp_path / "xdg" / "scanner-manager" / "devices.json"


def test_default_devices_path_falls_back_to_user_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # parents[1] of this stub is tmp_path; no data/ dir → user config
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    fake_module = pkg / "device_manager.py"
    fake_module.write_text("# stub", encoding="utf-8")
    monkeypatch.setattr("core.device_manager.__file__", str(fake_module))
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.delenv("SCANNER_MANAGER_CONFIG_DIR", raising=False)
    assert _default_devices_path() == _user_config_path()


def test_default_devices_path_uses_repo_data_when_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Mimic repo layout: <root>/core/device_manager.py and <root>/data/
    core_dir = tmp_path / "core"
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    core_dir.mkdir(parents=True)
    fake_module = core_dir / "device_manager.py"
    fake_module.write_text("# stub", encoding="utf-8")
    monkeypatch.setattr("core.device_manager.__file__", str(fake_module))
    assert _default_devices_path() == data_dir / "devices.json"


def test_save_creates_parent_directory(tmp_path: Path) -> None:
    nested = tmp_path / "nested" / "devices.json"
    mgr = DeviceManager(devices_path=nested)
    device = Device.make("uniden_bt885", "Nested")
    mgr.add_device(device)
    assert nested.exists()
    assert nested.parent.is_dir()
