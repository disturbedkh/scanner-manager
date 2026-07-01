"""Device manager: persistent multi-device manifest for the GUI shell.

A "device" pairs a :class:`scanner_profiles.ScannerProfile` with an
optional metastore profile (the user's saved virtual SD card layout)
and an optional last-known SD card mount point. The desktop app's
top header populates its device selector from
:func:`DeviceManager.list_devices`. The user adds new entries via
the "Add Device" wizard.

Storage lives at ``data/devices.json`` (per
``Metacache/Dev/MULTI_DEVICE_GUI.md`` §Storage layout). Schema is documented
inline in the file. We keep the on-disk structure forward-compatible
by ignoring unknown keys instead of erroring.

This module is intentionally GUI-agnostic so the same ``DeviceManager``
can drive the Qt shell, future headless sync, and the test harness.
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from scanner_profiles import (
    ScannerProfile,
    detect_from_card,
    get_profile,
    list_profiles,
)

DEVICES_SCHEMA_VERSION = 1


@dataclass
class Device:
    """One row in the GUI's device selector.

    Persisted as-is to ``data/devices.json``; unknown future fields
    survive a round-trip via the ``extra`` catch-all.
    """

    id: str
    label: str
    scanner_profile_id: str
    metastore_profile_id: Optional[str] = None
    sd_card_path: Optional[str] = None
    last_known_main_fw: Optional[str] = None
    last_known_sub_fw: Optional[str] = None
    last_seen: Optional[str] = None
    # User-selected connection mode. The radio is mutually exclusive
    # between Serial and Mass Storage at the hardware level, so the
    # UI gates entire dock groups by this choice. Values:
    #   "live"     - serial-mode docks visible, storage-mode hidden
    #   "storage"  - storage-mode docks (editor/firmware) visible, live hidden
    #   "auto"     - infer at startup based on which surface is reachable
    # Profiles that don't support serial mode (e.g. BT885) clamp this
    # to "storage" regardless of the persisted value.
    connection_mode: str = "auto"
    extra: Dict = field(default_factory=dict)

    @classmethod
    def make(
        cls,
        scanner_profile_id: str,
        label: str,
        metastore_profile_id: Optional[str] = None,
        sd_card_path: Optional[str] = None,
    ) -> "Device":
        return cls(
            id=str(uuid.uuid4()),
            label=label,
            scanner_profile_id=scanner_profile_id,
            metastore_profile_id=metastore_profile_id,
            sd_card_path=sd_card_path,
        )

    def to_dict(self) -> Dict:
        d = {
            "id": self.id,
            "label": self.label,
            "scanner_profile_id": self.scanner_profile_id,
            "metastore_profile_id": self.metastore_profile_id,
            "sd_card_path": self.sd_card_path,
            "last_known_main_fw": self.last_known_main_fw,
            "last_known_sub_fw": self.last_known_sub_fw,
            "last_seen": self.last_seen,
            "connection_mode": self.connection_mode,
        }
        if self.extra:
            d.update(self.extra)
        return d

    @classmethod
    def from_dict(cls, raw: Dict) -> "Device":
        # Pull known fields off; preserve everything else under .extra
        # so we can round-trip future schema additions without losing data.
        known_keys = {
            "id",
            "label",
            "scanner_profile_id",
            "metastore_profile_id",
            "sd_card_path",
            "last_known_main_fw",
            "last_known_sub_fw",
            "last_seen",
            "connection_mode",
        }
        extra = {k: v for k, v in raw.items() if k not in known_keys}
        return cls(
            id=raw.get("id") or str(uuid.uuid4()),
            label=raw.get("label", "Unnamed device"),
            scanner_profile_id=raw.get("scanner_profile_id", ""),
            metastore_profile_id=raw.get("metastore_profile_id"),
            sd_card_path=raw.get("sd_card_path"),
            last_known_main_fw=raw.get("last_known_main_fw"),
            last_known_sub_fw=raw.get("last_known_sub_fw"),
            last_seen=raw.get("last_seen"),
            connection_mode=raw.get("connection_mode", "auto") or "auto",
            extra=extra,
        )

    def resolve_profile(self) -> ScannerProfile:
        """Resolve this device's scanner profile (falls back to default)."""
        return get_profile(self.scanner_profile_id)

    def update_seen(self) -> None:
        """Stamp ``last_seen`` with the current UTC ISO timestamp."""
        self.last_seen = datetime.now(timezone.utc).isoformat(timespec="seconds")


class DeviceManager:
    """Read / write ``data/devices.json``; expose the device list."""

    def __init__(self, devices_path: Optional[Path] = None) -> None:
        self.path = Path(devices_path) if devices_path else _default_devices_path()
        self._devices: List[Device] = []
        self._default_device_id: Optional[str] = None
        self.load()

    # ---- Persistence -------------------------------------------------

    def load(self) -> None:
        """Reload from disk; missing/invalid file = empty manifest."""
        self._devices = []
        self._default_device_id = None
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return
        if not isinstance(raw, dict):
            return
        for entry in raw.get("devices", []):
            if isinstance(entry, dict):
                self._devices.append(Device.from_dict(entry))
        default = raw.get("default_device_id")
        if isinstance(default, str):
            self._default_device_id = default

    def reload_from(self, path: Path) -> None:
        """Point at a different on-disk manifest and reload without writing."""
        self.path = Path(path)
        self.load()

    def save(self) -> None:
        """Persist to disk atomically (write-temp + rename)."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        out = {
            "schema_version": DEVICES_SCHEMA_VERSION,
            "devices": [d.to_dict() for d in self._devices],
            "default_device_id": self._default_device_id,
        }
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, self.path)

    # ---- Read API ----------------------------------------------------

    def list_devices(self) -> List[Device]:
        return list(self._devices)

    def get_device(self, device_id: str) -> Optional[Device]:
        for d in self._devices:
            if d.id == device_id:
                return d
        return None

    def get_default(self) -> Optional[Device]:
        if self._default_device_id:
            d = self.get_device(self._default_device_id)
            if d:
                return d
        return self._devices[0] if self._devices else None

    def list_supported_scanner_profiles(self) -> List[ScannerProfile]:
        """Profiles registered today, in display order."""
        return list_profiles()

    # ---- Mutate API --------------------------------------------------

    def add_device(self, device: Device) -> Device:
        self._devices.append(device)
        if self._default_device_id is None:
            self._default_device_id = device.id
        self.save()
        return device

    def update_device(self, device: Device) -> None:
        for i, d in enumerate(self._devices):
            if d.id == device.id:
                self._devices[i] = device
                self.save()
                return
        raise KeyError(f"Device {device.id!r} is not registered")

    def remove_device(self, device_id: str) -> None:
        self._devices = [d for d in self._devices if d.id != device_id]
        if self._default_device_id == device_id:
            self._default_device_id = self._devices[0].id if self._devices else None
        self.save()

    def set_default(self, device_id: str) -> None:
        if not any(d.id == device_id for d in self._devices):
            raise KeyError(f"Device {device_id!r} is not registered")
        self._default_device_id = device_id
        self.save()

    # ---- Convenience -------------------------------------------------

    def detect_device_for_path(self, sd_path: str) -> Optional[Device]:
        """If ``sd_path`` matches an existing device's SD card path,
        return that device. Otherwise return None."""
        if not sd_path:
            return None
        normalized = os.path.normcase(os.path.normpath(sd_path))
        for d in self._devices:
            if d.sd_card_path and os.path.normcase(os.path.normpath(d.sd_card_path)) == normalized:
                return d
        return None

    def auto_create_device_for_path(
        self, sd_path: str, label_prefix: str = ""
    ) -> Optional[Device]:
        """Detect the scanner family from ``sd_path`` and create a
        Device entry for it. Returns None if detection fails.
        """
        profile = detect_from_card(sd_path)
        if profile is None:
            return None
        label = label_prefix or f"{profile.display_name} ({_short_path_label(sd_path)})"
        device = Device.make(
            scanner_profile_id=profile.id,
            label=label,
            sd_card_path=sd_path,
        )
        device.update_seen()
        self.add_device(device)
        return device


def _default_devices_path() -> Path:
    """Return the writable devices.json path.

    We write into the user's app-config dir (so PyInstaller-packaged
    builds can mutate it). For dev runs from source we still prefer
    ``data/devices.json`` next to the repo so changes show up in
    git status; the user-config path is the fallback.
    """
    repo_data = Path(__file__).resolve().parent / "data" / "devices.json"
    if repo_data.parent.exists():
        return repo_data
    return _user_config_path()


def _user_config_path() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    return base / "scanner-manager" / "devices.json"


def _short_path_label(path: str) -> str:
    """Compact human label for an SD card path - e.g. 'D:\\' or
    '/media/sdcard/BCDx36HP'."""
    if not path:
        return ""
    # Drive root on Windows: keep just `D:\`
    if sys.platform == "win32" and len(path) <= 3 and path.endswith(":\\"):
        return path
    return os.path.basename(path.rstrip("/\\")) or path


_FRESH_TIMESTAMP_FN = lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())  # noqa: E731
