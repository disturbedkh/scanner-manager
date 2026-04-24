#!/usr/bin/env python3
"""
Beartracker 885 Scanner Manager

Manage HPD frequency/talkgroup files for the Uniden Beartracker 885 scanner.
Load files from the SD card, browse the tree of counties/groups/frequencies,
edit service types, add new entries from RadioReference, and save back.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.parse
import urllib.request
import uuid
import webbrowser
from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Dict, List, Optional, Set, Tuple

import sdcard
import uniden_tools
from metastore import (
    OP_ADD_ENTRY,
    OP_ADD_GROUP,
    OP_BULK_REVERT,
    OP_DELETE_ENTRY,
    OP_DELETE_GROUP,
    OP_DELETE_SYSTEM,
    OP_EDIT_ENTRY,
    OP_EDIT_GROUP,
    OP_EDIT_SYSTEM,
    OP_EXTERNAL_CHANGE,
    OP_IMPORT_APPLY,
    OP_LINK_RR,
    OP_REVERT,
    OP_SET_AVOID,
    OP_SET_SERVICE,
    OP_UNLINK_RR,
    Event,
    GlobalMetaStore,
    MetaStore,
    entry_id_for,
    group_id_for,
    session_snapshot_path,
    system_id_for,
    write_session_snapshot,
)

# ---------------------------------------------------------------------------
# Project-level constants (single source of truth for version + URLs)
# ---------------------------------------------------------------------------

APP_NAME = "Scanner Manager"
APP_TAGLINE = "Uniden BearTracker 885 SD card companion"
APP_GITHUB_URL = "https://github.com/disturbedkh/scanner-manager"
APP_WIKI_URL = f"{APP_GITHUB_URL}/wiki"
APP_ISSUES_URL = f"{APP_GITHUB_URL}/issues"

DONATE_PAYPAL_URL = "https://paypal.me/gvillescanner"
DONATE_BTC_ADDR = "3FEgJ7y5qpagB2NqZaNhCurx8tA3cC8Gv3"
DONATE_ETH_ADDR = "0xC407c8f7b1f35182341AC914B5A51D867Ae986FA"
DONATE_USDT_ERC20_ADDR = "0xA34409BD5612FF23727fB6aEA0d584Bf0e841365"


def get_app_version() -> str:
    """Return the installed package version, or a dev fallback.

    Uses ``importlib.metadata`` so the EXE built by PyInstaller picks up
    the version from the pyproject-generated metadata just like a
    ``pip install -e .`` run does.
    """
    try:
        from importlib.metadata import PackageNotFoundError, version
        try:
            return version("beartracker-885-scanner-manager")
        except PackageNotFoundError:
            return "0.9.0a2-dev"
    except Exception:
        return "0.9.0a2-dev"


APP_VERSION = get_app_version()

IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")


def bundled_resources_dir() -> Path:
    """Return the dir that holds read-only assets (``data/...``) at runtime.

    When running from a PyInstaller one-file EXE, this is ``_MEIPASS``
    (the temp extraction dir). When running from source, it's the dir
    containing ``scanner_manager.py``.
    """
    mei = getattr(sys, "_MEIPASS", None)
    if mei:
        return Path(mei)
    return Path(__file__).resolve().parent


def open_in_file_manager(path: str) -> None:
    """Open ``path`` in the host OS's file manager.

    Wraps the three platform idioms (``os.startfile`` on Windows,
    ``open`` on macOS, ``xdg-open`` on Linux/BSD) so the caller can
    just pass a path without a platform check. Raises the underlying
    exception on failure so callers can surface a meaningful error.
    """
    if IS_WINDOWS:
        os.startfile(path)  # type: ignore[attr-defined]
    elif IS_MACOS:
        import subprocess as _sp
        _sp.run(["open", path], check=False)
    else:
        import subprocess as _sp
        _sp.run(["xdg-open", path], check=False)


try:
    import rr_api
except Exception:  # pragma: no cover - module always imports
    rr_api = None  # type: ignore

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SERVICE_TYPES = {
    1: "Multi Dispatch",
    2: "Police Dispatch",
    3: "Fire Dispatch",
    4: "EMS Dispatch",
    6: "Multi-Tac",
    7: "Law Tac",
    8: "Fire-Tac",
    9: "EMS-Tac",
    14: "Public Works",
    22: "Multi-Talk",
    23: "Law Talk",
    24: "Fire-Talk",
    25: "EMS-Talk",
    209: "Auto/BTW",
}

SCANNABLE_TYPES = {1, 2, 3, 4, 14}

SERVICE_CHOICES = [
    (1, "1 - Multi Dispatch"),
    (2, "2 - Police Dispatch"),
    (3, "3 - Fire Dispatch"),
    (4, "4 - EMS Dispatch"),
    (6, "6 - Multi-Tac"),
    (7, "7 - Law Tac"),
    (8, "8 - Fire-Tac"),
    (9, "9 - EMS-Tac"),
    (14, "14 - Public Works"),
    (22, "22 - Multi-Talk"),
    (23, "23 - Law Talk"),
    (24, "24 - Fire-Talk"),
    (25, "25 - EMS-Talk"),
]

MODE_CHOICES_CONV = ["FM", "NFM", "AM", "AUTO"]
# BearTracker 885 HPD format (verified against real SD card):
#   TGID Mode column only ever contains ALL / ANALOG / DIGITAL.
#   There is NO separate TDMA token — TDMA (P25 Phase II) is decoded
#   automatically based on the Trunk record's system type (P25Standard).
#   So DIGITAL covers both P25 Phase I (FDMA) and Phase II (TDMA).
MODE_CHOICES_TGID = ["ALL", "ANALOG", "DIGITAL"]

# Friendly labels for UI. Canonical value (what we store in the HPD file)
# -> human label shown in the GUI. The label explains that DIGITAL covers
# (D) P25 Phase I FDMA *and* (T) P25 Phase II TDMA on this scanner.
TGID_MODE_UI_LABELS: Dict[str, str] = {
    "ALL": "ALL (auto D/T/A)",
    "ANALOG": "ANALOG (A)",
    "DIGITAL": "DIGITAL (D / T TDMA)",
}
TGID_MODE_LABEL_TO_CANONICAL: Dict[str, str] = {
    label: canonical for canonical, label in TGID_MODE_UI_LABELS.items()
}
MODE_CHOICES_TGID_LABELS: List[str] = [
    TGID_MODE_UI_LABELS[c] for c in MODE_CHOICES_TGID
]


def tgid_mode_label(canonical: str) -> str:
    """Render an HPD TGID mode value (ALL/ANALOG/DIGITAL/legacy) as a UI label."""
    if not canonical:
        return ""
    key = canonical.strip().upper()
    return TGID_MODE_UI_LABELS.get(key, canonical)


def tgid_mode_canonical(label: str) -> str:
    """Convert a UI label (or canonical/legacy value) back to an HPD-safe token."""
    if not label:
        return ""
    stripped = label.strip()
    if stripped in TGID_MODE_LABEL_TO_CANONICAL:
        return TGID_MODE_LABEL_TO_CANONICAL[stripped]
    upper = stripped.upper()
    if upper in ("D", "DMR"):
        return "DIGITAL"
    if upper in ("T", "TD", "TDMA"):
        return "DIGITAL"
    if upper == "DE":
        return "DIGITAL"  # scanner can't decode; flagged elsewhere
    if upper in ("A", "ANALOG"):
        return "ANALOG"
    if upper == "AE":
        return "ANALOG"
    if upper == "ALL":
        return "ALL"
    if upper in {"ALL", "ANALOG", "DIGITAL"}:
        return upper
    return upper or ""

SERVICE_TYPE_HELP_TEXT = (
    "BearTracker 885 Scan Buttons (only these exist):\n"
    "  Police -> Type 2 (Police Dispatch)\n"
    "  Fire -> Type 3 (Fire Dispatch)\n"
    "  EMS -> Type 4 (EMS Dispatch)\n"
    "  DOT -> Type 14 (Public Works) - shown green like 2/3/4\n\n"
    "Type 1 (Multi Dispatch) is generic dispatch only.\n"
    "It is not a dedicated scanner button and is not 'all buttons'.\n"
    "No other service-type buttons are available on this scanner.\n"
    "Any channel using a different service type will not be scanned.\n"
    "Remap channels to 2/3/4/14 for predictable behavior.\n"
    "Example: Security channels -> Type 14 to hear them under DOT.\n\n"
    "Tip: Select a group or system to apply service type or avoid to all entries at once."
)

# ---------------------------------------------------------------------------
# Data Model
# ---------------------------------------------------------------------------

@dataclass
class HpdRecord:
    """A single tab-delimited line in an HPD file."""
    line_index: int
    raw_line: str
    record_type: str
    fields: List[str]
    modified: bool = False

    def get_field(self, index: int, default: str = "") -> str:
        if index < len(self.fields):
            return self.fields[index]
        return default

    def set_field(self, index: int, value: str):
        while len(self.fields) <= index:
            self.fields.append("")
        self.fields[index] = value
        self.modified = True

    def to_line(self) -> str:
        if not self.modified:
            return self.raw_line
        return "\t".join(self.fields)


@dataclass
class FreqEntry:
    """A C-Freq or TGID entry."""
    record: HpdRecord
    name: str
    service_type: int
    entry_type: str
    group_id: str = ""
    group_type: str = ""
    group_name: str = ""
    system_id: str = ""
    system_type: str = ""
    system_name: str = ""


@dataclass
class GroupNode:
    """A C-Group or T-Group."""
    record: HpdRecord
    name: str
    group_type: str
    group_id: str
    parent_id: str
    system_id: str = ""
    system_type: str = ""
    system_name: str = ""
    lat: Optional[float] = None
    lon: Optional[float] = None
    range_miles: Optional[float] = None
    rectangles: List[Tuple[float, float, float, float]] = field(default_factory=list)
    entries: List[FreqEntry] = field(default_factory=list)


@dataclass
class SiteNode:
    """A Site within a Trunk system."""
    record: HpdRecord
    name: str
    site_id: str
    lat: Optional[float] = None
    lon: Optional[float] = None
    range_miles: Optional[float] = None
    freqs: List[HpdRecord] = field(default_factory=list)


@dataclass
class SystemNode:
    """A Conventional or Trunk system."""
    record: HpdRecord
    name: str
    system_type: str
    system_id: str
    area_records: List[HpdRecord] = field(default_factory=list)
    state_ids: Set[int] = field(default_factory=set)
    county_ids: Set[int] = field(default_factory=set)
    groups: List[GroupNode] = field(default_factory=list)
    sites: List[SiteNode] = field(default_factory=list)


@dataclass
class EntryCustomization:
    """User-relevant entry fields that should survive a database refresh."""
    entry_type: str
    system_id: str
    system_type: str
    system_name: str
    group_id: str
    group_type: str
    group_name: str
    name: str
    service_type: int
    avoid: str
    identity_value: str
    mode: str = ""
    tone: str = ""
    is_user_added: bool = False

# ---------------------------------------------------------------------------
# HPD File Parser / Writer
# ---------------------------------------------------------------------------

class HpdFile:
    """Parses and manages an HPD file."""

    def __init__(self):
        self.records: List[HpdRecord] = []
        self.systems: List[SystemNode] = []
        self.header_records: List[HpdRecord] = []
        self.filepath: Optional[str] = None
        self.has_changes = False

    def load(self, filepath: str):
        self.filepath = filepath
        self.records.clear()
        self.systems.clear()
        self.header_records.clear()
        self.has_changes = False

        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            for i, raw in enumerate(f):
                raw = raw.rstrip("\r\n")
                fields = raw.split("\t")
                rec_type = fields[0] if fields else ""
                rec = HpdRecord(
                    line_index=i,
                    raw_line=raw,
                    record_type=rec_type,
                    fields=fields,
                )
                self.records.append(rec)

        self._build_tree()

    def _build_tree(self):
        self.systems.clear()
        self.header_records.clear()

        current_system: Optional[SystemNode] = None
        current_group: Optional[GroupNode] = None
        current_site: Optional[SiteNode] = None

        for rec in self.records:
            rt = rec.record_type

            if rt in ("TargetModel", "FormatVersion", "DateModified"):
                self.header_records.append(rec)

            elif rt == "Conventional":
                sys_id = self._extract_id(rec.fields[1])
                name = rec.get_field(3, "Unknown")
                current_system = SystemNode(
                    record=rec, name=name, system_type="Conventional",
                    system_id=sys_id,
                )
                self.systems.append(current_system)
                current_group = None
                current_site = None

            elif rt == "Trunk":
                sys_id = self._extract_id(rec.fields[1])
                name = rec.get_field(3, "Unknown")
                current_system = SystemNode(
                    record=rec, name=name, system_type="Trunk",
                    system_id=sys_id,
                )
                self.systems.append(current_system)
                current_group = None
                current_site = None

            elif rt in ("AreaState", "AreaCounty"):
                if current_system:
                    current_system.area_records.append(rec)
                    state_id, county_id = self._extract_area_ids(rec.fields)
                    if state_id is not None:
                        current_system.state_ids.add(state_id)
                    if county_id is not None:
                        current_system.county_ids.add(county_id)

            elif rt == "C-Group":
                gid = self._extract_id(rec.fields[1])
                pid = self._extract_id(rec.fields[2])
                name = rec.get_field(3, "Unknown")
                lat, lon, rng = self._extract_geo(rec.fields, 5)
                current_group = GroupNode(
                    record=rec, name=name, group_type="C-Group",
                    group_id=gid, parent_id=pid,
                    system_id=current_system.system_id if current_system else "",
                    system_type=current_system.system_type if current_system else "",
                    system_name=current_system.name if current_system else "",
                    lat=lat, lon=lon, range_miles=rng,
                )
                if current_system:
                    current_system.groups.append(current_group)
                current_site = None

            elif rt == "C-Freq":
                stype = self._parse_int(rec.get_field(8, "0"))
                name = rec.get_field(3, "")
                entry = FreqEntry(
                    record=rec, name=name, service_type=stype,
                    entry_type="C-Freq",
                    group_id=current_group.group_id if current_group else "",
                    group_type=current_group.group_type if current_group else "",
                    group_name=current_group.name if current_group else "",
                    system_id=current_system.system_id if current_system else "",
                    system_type=current_system.system_type if current_system else "",
                    system_name=current_system.name if current_system else "",
                )
                if current_group:
                    current_group.entries.append(entry)

            elif rt == "Site":
                sid = self._extract_id(rec.fields[1])
                name = rec.get_field(3, "Unknown")
                lat, lon, rng = self._extract_geo(rec.fields, 5)
                current_site = SiteNode(
                    record=rec, name=name, site_id=sid,
                    lat=lat, lon=lon, range_miles=rng,
                )
                if current_system:
                    current_system.sites.append(current_site)
                current_group = None

            elif rt == "T-Freq":
                if current_site:
                    current_site.freqs.append(rec)

            elif rt == "T-Group":
                gid = self._extract_id(rec.fields[1])
                pid = self._extract_id(rec.fields[2])
                name = rec.get_field(3, "Unknown")
                lat, lon, rng = self._extract_geo(rec.fields, 5)
                current_group = GroupNode(
                    record=rec, name=name, group_type="T-Group",
                    group_id=gid, parent_id=pid,
                    system_id=current_system.system_id if current_system else "",
                    system_type=current_system.system_type if current_system else "",
                    system_name=current_system.name if current_system else "",
                    lat=lat, lon=lon, range_miles=rng,
                )
                if current_system:
                    current_system.groups.append(current_group)
                current_site = None

            elif rt == "TGID":
                stype = self._parse_int(rec.get_field(7, "0"))
                name = rec.get_field(3, "")
                entry = FreqEntry(
                    record=rec, name=name, service_type=stype,
                    entry_type="TGID",
                    group_id=current_group.group_id if current_group else "",
                    group_type=current_group.group_type if current_group else "",
                    group_name=current_group.name if current_group else "",
                    system_id=current_system.system_id if current_system else "",
                    system_type=current_system.system_type if current_system else "",
                    system_name=current_system.name if current_system else "",
                )
                if current_group:
                    current_group.entries.append(entry)

            elif rt == "Rectangle":
                target_group = self._find_group_for_rectangle(rec)
                coords = self._extract_rectangle_coords(rec.fields)
                if target_group is not None and coords is not None:
                    target_group.rectangles.append(coords)

    def _find_group_for_rectangle(self, rec: HpdRecord) -> Optional[GroupNode]:
        target_key: Optional[Tuple[str, str]] = None
        for field_str in rec.fields[1:]:
            if "=" not in field_str:
                continue
            key, value = field_str.split("=", 1)
            if key == "CGroupId":
                target_key = ("C-Group", value)
                break
            if key == "TGroupId":
                target_key = ("T-Group", value)
                break
        if target_key is None:
            return None
        group_type, group_id = target_key
        for system in self.systems:
            for group in system.groups:
                if group.group_type == group_type and group.group_id == group_id:
                    return group
        return None

    @staticmethod
    def _extract_rectangle_coords(
        fields: List[str],
    ) -> Optional[Tuple[float, float, float, float]]:
        numbers: List[float] = []
        for field_str in fields[1:]:
            if "=" in field_str:
                continue
            try:
                numbers.append(float(field_str))
            except ValueError:
                continue
        if len(numbers) < 4:
            return None
        return numbers[0], numbers[1], numbers[2], numbers[3]

    def save(self, filepath: Optional[str] = None) -> Optional[str]:
        """Persist the HPD file to disk.

        The old per-save timestamped .backup_<ts> scheme was retired in
        favour of the MetaStore event log + single .session.bak safety
        net (see scanner_manager.MetaStore); ``save`` no longer manages
        backups.
        """
        target = filepath or self.filepath
        if not target:
            raise ValueError("No filepath specified")

        with open(target, "w", encoding="utf-8", newline="\r\n") as f:
            for rec in self.records:
                f.write(rec.to_line() + "\n")

        self.has_changes = False
        return None

    def add_tgroup(
        self,
        system: SystemNode,
        name: str,
        lat: Optional[float] = None,
        lon: Optional[float] = None,
        range_miles: Optional[float] = None,
    ) -> GroupNode:
        """Add a new T-Group under a Trunk system."""
        if system.system_type != "Trunk":
            raise ValueError("T-Groups can only be added to trunked systems.")
        trunk_id = system.system_id
        lat_str = f"{lat:.6f}" if lat is not None else ""
        lon_str = f"{lon:.6f}" if lon is not None else ""
        range_str = f"{range_miles:.1f}" if range_miles is not None else ""
        fields = [
            "T-Group",
            "TGroupId=0",
            f"TrunkId={trunk_id}",
            name,
            "Off",
            lat_str,
            lon_str,
            range_str,
        ]
        raw = "\t".join(fields)
        insert_idx = self._find_system_end(system)
        rec = HpdRecord(
            line_index=insert_idx, raw_line=raw,
            record_type="T-Group", fields=fields, modified=True,
        )
        self.records.insert(insert_idx, rec)
        group = GroupNode(
            record=rec, name=name, group_type="T-Group",
            group_id="0", parent_id=str(trunk_id),
            system_id=system.system_id,
            system_type=system.system_type,
            system_name=system.name,
            lat=lat, lon=lon, range_miles=range_miles,
        )
        system.groups.append(group)
        self.has_changes = True
        return group

    def add_cgroup(
        self,
        system: SystemNode,
        name: str,
        lat: Optional[float] = None,
        lon: Optional[float] = None,
        range_miles: Optional[float] = None,
    ) -> GroupNode:
        """Add a new C-Group under a conventional (county) system."""
        if system.system_type != "Conventional":
            raise ValueError("Groups can only be added to conventional systems.")
        county_id = system.system_id
        lat_str = f"{lat:.6f}" if lat is not None else ""
        lon_str = f"{lon:.6f}" if lon is not None else ""
        range_str = f"{range_miles:.1f}" if range_miles is not None else ""
        fields = [
            "C-Group",
            "CGroupId=0",
            f"CountyId={county_id}",
            name,
            "Off",
            lat_str,
            lon_str,
            range_str,
            "Circle",
        ]
        raw = "\t".join(fields)
        insert_idx = self._find_system_end(system)
        rec = HpdRecord(
            line_index=insert_idx, raw_line=raw,
            record_type="C-Group", fields=fields, modified=True,
        )
        self.records.insert(insert_idx, rec)
        group = GroupNode(
            record=rec, name=name, group_type="C-Group",
            group_id="0", parent_id=str(county_id),
            system_id=system.system_id,
            system_type=system.system_type,
            system_name=system.name,
            lat=lat, lon=lon, range_miles=range_miles,
        )
        system.groups.append(group)
        self.has_changes = True
        return group

    def add_cfreq(self, group: GroupNode, name: str, freq_hz: int,
                  mode: str, tone: str, service_type: int) -> FreqEntry:
        """Add a new conventional frequency to a group."""
        group_id = group.group_id
        fields = [
            "C-Freq",
            "CFreqId=0",
            f"CGroupId={group_id}",
            name,
            "Off",
            str(freq_hz),
            mode,
            tone,
            str(service_type),
        ]
        raw = "\t".join(fields)
        insert_idx = self._find_group_end(group)
        rec = HpdRecord(
            line_index=insert_idx, raw_line=raw,
            record_type="C-Freq", fields=fields, modified=True,
        )
        self.records.insert(insert_idx, rec)
        entry = FreqEntry(
            record=rec, name=name, service_type=service_type,
            entry_type="C-Freq",
            group_id=group.group_id,
            group_type=group.group_type,
            group_name=group.name,
            system_id=group.system_id,
            system_type=group.system_type,
            system_name=group.system_name,
        )
        group.entries.append(entry)
        self.has_changes = True
        return entry

    def add_tgid(self, group: GroupNode, name: str, tgid: int,
                 mode: str, service_type: int) -> FreqEntry:
        """Add a new trunked talkgroup to a group."""
        group_id = group.group_id
        fields = [
            "TGID",
            "Tid=0",
            f"TGroupId={group_id}",
            name,
            "Off",
            str(tgid),
            mode,
            str(service_type),
        ] + [""] * 8 + ["Any"]
        raw = "\t".join(fields)
        insert_idx = self._find_group_end(group)
        rec = HpdRecord(
            line_index=insert_idx, raw_line=raw,
            record_type="TGID", fields=fields, modified=True,
        )
        self.records.insert(insert_idx, rec)
        entry = FreqEntry(
            record=rec, name=name, service_type=service_type,
            entry_type="TGID",
            group_id=group.group_id,
            group_type=group.group_type,
            group_name=group.name,
            system_id=group.system_id,
            system_type=group.system_type,
            system_name=group.system_name,
        )
        group.entries.append(entry)
        self.has_changes = True
        return entry

    def update_service_type(self, entry: FreqEntry, new_type: int):
        """Change the service type of a frequency or talkgroup."""
        rec = entry.record
        if entry.entry_type == "C-Freq":
            rec.set_field(8, str(new_type))
        elif entry.entry_type == "TGID":
            rec.set_field(7, str(new_type))
        entry.service_type = new_type
        self.has_changes = True

    def toggle_avoid(self, entry: FreqEntry):
        """Toggle the avoid (Off/On) state."""
        rec = entry.record
        if entry.entry_type == "C-Freq":
            idx = 4
        elif entry.entry_type == "TGID":
            idx = 4
        else:
            return
        current = rec.get_field(idx, "Off")
        new_val = "On" if current == "Off" else "Off"
        rec.set_field(idx, new_val)
        self.has_changes = True

    def edit_entry(
        self,
        entry: FreqEntry,
        name: Optional[str] = None,
        identity_value: Optional[str] = None,
        mode: Optional[str] = None,
        tone: Optional[str] = None,
    ):
        """Edit name/frequency/tgid/mode/tone on an entry in-place."""
        rec = entry.record
        if name is not None:
            rec.set_field(3, name)
            entry.name = name
        if identity_value is not None:
            rec.set_field(5, identity_value)
        if mode is not None:
            rec.set_field(6, mode)
        if entry.entry_type == "C-Freq" and tone is not None:
            rec.set_field(7, tone)
        self.has_changes = True

    def delete_entry(self, entry: FreqEntry):
        """Remove an entry and its record from the HPD."""
        rec = entry.record
        try:
            self.records.remove(rec)
        except ValueError:
            pass
        for system in self.systems:
            for group in system.groups:
                if entry in group.entries:
                    group.entries.remove(entry)
        self.has_changes = True

    def edit_group(
        self,
        group: GroupNode,
        name: Optional[str] = None,
        lat: Optional[float] = None,
        lon: Optional[float] = None,
        range_miles: Optional[float] = None,
    ):
        """Edit group name, lat, lon, or range. Pass None to keep a field unchanged."""
        rec = group.record
        if name is not None:
            rec.set_field(3, name)
            group.name = name
            for entry in group.entries:
                entry.group_name = name
        if lat is not None:
            rec.set_field(5, f"{lat:.6f}")
            group.lat = lat
        if lon is not None:
            rec.set_field(6, f"{lon:.6f}")
            group.lon = lon
        if range_miles is not None:
            rec.set_field(7, f"{range_miles:.1f}")
            group.range_miles = range_miles
        self.has_changes = True

    def delete_group(self, group: GroupNode):
        """Remove a group, its record, and all entries under it."""
        targets = [id(group.record)] + [id(e.record) for e in group.entries]
        target_set = set(targets)
        self.records = [r for r in self.records if id(r) not in target_set]
        for system in self.systems:
            if group in system.groups:
                system.groups.remove(group)
        group.entries.clear()
        self.has_changes = True

    # ---- System-level (macro) operations ------------------------------

    def edit_system(
        self,
        system: SystemNode,
        name: Optional[str] = None,
    ) -> None:
        """Edit a system's top-level fields. Pass None to keep unchanged.

        A name change propagates into child groups/entries so the in-memory
        tree stays consistent with what's displayed.
        """
        if name is None:
            return
        rec = system.record
        rec.set_field(3, name)
        system.name = name
        for group in system.groups:
            group.system_name = name
            for entry in group.entries:
                entry.system_name = name
        self.has_changes = True

    def _records_owned_by_system(
        self, system: SystemNode
    ) -> List["HpdRecord"]:
        """Every HpdRecord that belongs to the given system, in the order
        they appear in ``self.records``. Used by delete_system + revert."""
        owned_ids: Set[int] = {id(system.record)}
        for rec in system.area_records:
            owned_ids.add(id(rec))
        for site in system.sites:
            owned_ids.add(id(site.record))
            for freq_rec in site.freqs:
                owned_ids.add(id(freq_rec))
        group_keys: Set[Tuple[str, str]] = set()
        for group in system.groups:
            owned_ids.add(id(group.record))
            group_keys.add((group.group_type, group.group_id))
            for entry in group.entries:
                owned_ids.add(id(entry.record))
        for rec in self.records:
            if rec.record_type != "Rectangle":
                continue
            ref: Optional[Tuple[str, str]] = None
            for field_str in rec.fields[1:]:
                if "=" not in field_str:
                    continue
                key, value = field_str.split("=", 1)
                if key == "CGroupId":
                    ref = ("C-Group", value)
                    break
                if key == "TGroupId":
                    ref = ("T-Group", value)
                    break
            if ref is not None and ref in group_keys:
                owned_ids.add(id(rec))
        return [r for r in self.records if id(r) in owned_ids]

    def delete_system(self, system: SystemNode) -> Dict[str, Any]:
        """Cascading delete of a system.

        Removes the system record, all AreaState/AreaCounty rows, all Sites
        (+ their T-Freq rows), all groups (+ their entries), and any
        Rectangle rows referring to those groups. Rebuilds the tree from
        the remaining records.

        Returns a snapshot payload with the original insertion index and
        raw field arrays so the deletion can be reverted.
        """
        owned = self._records_owned_by_system(system)
        if not owned:
            return {"insertion_index": 0, "records": []}
        owned_ids = {id(r) for r in owned}
        try:
            insertion_index = next(
                i for i, r in enumerate(self.records) if id(r) in owned_ids
            )
        except StopIteration:
            insertion_index = len(self.records)
        payload: Dict[str, Any] = {
            "insertion_index": insertion_index,
            "records": [
                {"record_type": r.record_type, "fields": list(r.fields)}
                for r in owned
            ],
            "system_id": system.system_id,
            "system_type": system.system_type,
            "system_name": system.name,
            "group_count": len(system.groups),
            "entry_count": sum(len(g.entries) for g in system.groups),
        }
        self.records = [r for r in self.records if id(r) not in owned_ids]
        self._build_tree()
        self.has_changes = True
        return payload

    def reinsert_system_from_payload(
        self, payload: Dict[str, Any]
    ) -> Optional[SystemNode]:
        """Inverse of delete_system. Inserts the saved raw records at the
        original position, rebuilds the tree, and returns the new
        SystemNode (or None on failure)."""
        raw = payload.get("records") or []
        if not raw:
            return None
        idx = int(payload.get("insertion_index") or 0)
        idx = max(0, min(idx, len(self.records)))
        new_records: List[HpdRecord] = []
        for blob in raw:
            fields = list(blob.get("fields") or [])
            rec_type = str(blob.get("record_type") or (fields[0] if fields else ""))
            raw_line = "\t".join(fields)
            new_records.append(
                HpdRecord(
                    line_index=idx,
                    raw_line=raw_line,
                    record_type=rec_type,
                    fields=fields,
                    modified=True,
                )
            )
        self.records[idx:idx] = new_records
        self._build_tree()
        self.has_changes = True
        target_system_id = str(payload.get("system_id") or "")
        target_system_type = str(payload.get("system_type") or "")
        for sys_node in self.systems:
            if (
                sys_node.system_id == target_system_id
                and sys_node.system_type == target_system_type
            ):
                return sys_node
        return None

    def snapshot_customizations(self) -> List[EntryCustomization]:
        snapshot: List[EntryCustomization] = []
        for sys_node in self.systems:
            for group in sys_node.groups:
                for entry in group.entries:
                    rec = entry.record
                    if entry.entry_type == "C-Freq":
                        identity = rec.get_field(5, "")
                        mode = rec.get_field(6, "")
                        tone = rec.get_field(7, "")
                        id_field = rec.get_field(1, "")
                    else:
                        identity = rec.get_field(5, "")
                        mode = rec.get_field(6, "")
                        tone = ""
                        id_field = rec.get_field(1, "")
                    snapshot.append(
                        EntryCustomization(
                            entry_type=entry.entry_type,
                            system_id=entry.system_id,
                            system_type=entry.system_type,
                            system_name=entry.system_name,
                            group_id=entry.group_id,
                            group_type=entry.group_type,
                            group_name=entry.group_name,
                            name=entry.name,
                            service_type=entry.service_type,
                            avoid=rec.get_field(4, "Off"),
                            identity_value=identity,
                            mode=mode,
                            tone=tone,
                            is_user_added=self._is_user_added_id(id_field),
                        )
                    )
        return snapshot

    def apply_customizations(self, snapshot: List[EntryCustomization]) -> Dict[str, int]:
        entry_map: Dict[Tuple[str, str, str, str], FreqEntry] = {}
        fallback_map: Dict[Tuple[str, str, str, str], FreqEntry] = {}
        for sys_node in self.systems:
            for group in sys_node.groups:
                for entry in group.entries:
                    entry_map[self._entry_key(entry)] = entry
                    fallback_map[self._entry_fallback_key(entry)] = entry

        reapplied = 0
        unresolved = 0
        inserted = 0

        for custom in snapshot:
            key = self._custom_key(custom)
            entry = entry_map.get(key)
            if entry is None:
                fallback_key = self._custom_fallback_key(custom)
                entry = fallback_map.get(fallback_key)

            if entry is not None:
                changed = False
                if entry.service_type != custom.service_type:
                    self.update_service_type(entry, custom.service_type)
                    changed = True
                current_avoid = entry.record.get_field(4, "Off")
                if current_avoid != custom.avoid:
                    entry.record.set_field(4, custom.avoid)
                    self.has_changes = True
                    changed = True
                if changed:
                    reapplied += 1
                continue

            if custom.is_user_added:
                if self._reinsert_custom_entry(custom):
                    inserted += 1
                    continue
            unresolved += 1

        return {
            "reapplied": reapplied,
            "inserted": inserted,
            "unresolved": unresolved,
        }

    def _reinsert_custom_entry(self, custom: EntryCustomization) -> bool:
        group = self._find_group(custom)
        if not group:
            return False
        try:
            if custom.entry_type == "C-Freq":
                freq_hz = self._parse_int(custom.identity_value)
                entry = self.add_cfreq(
                    group=group,
                    name=custom.name,
                    freq_hz=freq_hz,
                    mode=custom.mode or "NFM",
                    tone=custom.tone,
                    service_type=custom.service_type,
                )
            else:
                tgid = self._parse_int(custom.identity_value)
                entry = self.add_tgid(
                    group=group,
                    name=custom.name,
                    tgid=tgid,
                    mode=custom.mode or "ALL",
                    service_type=custom.service_type,
                )
            entry.record.set_field(4, custom.avoid)
            self.has_changes = True
            return True
        except Exception:
            return False

    def _find_group(self, custom: EntryCustomization) -> Optional[GroupNode]:
        for sys_node in self.systems:
            if custom.system_id and sys_node.system_id == custom.system_id:
                for group in sys_node.groups:
                    if custom.group_id and group.group_id == custom.group_id:
                        return group
        for sys_node in self.systems:
            if self._norm(sys_node.name) != self._norm(custom.system_name):
                continue
            for group in sys_node.groups:
                if self._norm(group.name) == self._norm(custom.group_name):
                    return group
        return None

    def _entry_key(self, entry: FreqEntry) -> Tuple[str, str, str, str]:
        return (
            entry.entry_type,
            entry.system_id,
            entry.group_id,
            entry.record.get_field(5, ""),
        )

    def _entry_fallback_key(self, entry: FreqEntry) -> Tuple[str, str, str, str]:
        return (
            entry.entry_type,
            self._norm(entry.system_name),
            self._norm(entry.group_name),
            entry.record.get_field(5, ""),
        )

    def _custom_key(self, custom: EntryCustomization) -> Tuple[str, str, str, str]:
        return (
            custom.entry_type,
            custom.system_id,
            custom.group_id,
            custom.identity_value,
        )

    def _custom_fallback_key(self, custom: EntryCustomization) -> Tuple[str, str, str, str]:
        return (
            custom.entry_type,
            self._norm(custom.system_name),
            self._norm(custom.group_name),
            custom.identity_value,
        )

    @staticmethod
    def _norm(text: str) -> str:
        return " ".join((text or "").strip().lower().split())

    @staticmethod
    def _is_user_added_id(id_field: str) -> bool:
        if "=" not in id_field:
            return False
        return id_field.split("=", 1)[1] == "0"

    def _find_group_end(self, group: GroupNode) -> int:
        """Find the record index after the last entry in a group."""
        if group.entries:
            last_rec = group.entries[-1].record
            return self.records.index(last_rec) + 1
        return self.records.index(group.record) + 1

    def _find_system_end(self, system: SystemNode) -> int:
        """Find the record index after the last record belonging to a system."""
        if system.groups:
            last_group = system.groups[-1]
            if last_group.entries:
                return self.records.index(last_group.entries[-1].record) + 1
            return self.records.index(last_group.record) + 1
        if system.area_records:
            return self.records.index(system.area_records[-1]) + 1
        return self.records.index(system.record) + 1

    @staticmethod
    def _extract_id(field_str: str) -> str:
        if "=" in field_str:
            return field_str.split("=", 1)[1]
        return field_str

    @staticmethod
    def _extract_area_ids(fields: List[str]) -> Tuple[Optional[int], Optional[int]]:
        state_id = None
        county_id = None
        for field_value in fields:
            for name, raw_value in re.findall(r"([A-Za-z]+Id)=(-?\d+)", field_value):
                if name == "StateId":
                    state_id = HpdFile._parse_int(raw_value)
                elif name == "CountyId":
                    county_id = HpdFile._parse_int(raw_value)
        return state_id, county_id

    @staticmethod
    def _parse_int(s: str) -> int:
        try:
            return int(s)
        except (ValueError, TypeError):
            return 0

    @staticmethod
    def _extract_geo(fields: List[str], start_index: int) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        def parse_float(value: str) -> Optional[float]:
            try:
                return float(value)
            except (ValueError, TypeError):
                return None

        lat = parse_float(fields[start_index]) if len(fields) > start_index else None
        lon = parse_float(fields[start_index + 1]) if len(fields) > start_index + 1 else None
        rng = parse_float(fields[start_index + 2]) if len(fields) > start_index + 2 else None
        if lat is None or lon is None:
            return None, None, None
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            return None, None, None
        return lat, lon, rng

# ---------------------------------------------------------------------------
# Geo helpers
# ---------------------------------------------------------------------------

EARTH_RADIUS_MILES = 3958.7613


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    import math
    rad_lat1 = math.radians(lat1)
    rad_lat2 = math.radians(lat2)
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = math.sin(d_lat / 2) ** 2 + math.cos(rad_lat1) * math.cos(rad_lat2) * math.sin(d_lon / 2) ** 2
    c = 2 * math.asin(min(1.0, math.sqrt(a)))
    return EARTH_RADIUS_MILES * c


def rectangle_contains_point(
    rect: Tuple[float, float, float, float], lat: float, lon: float
) -> bool:
    lat_a, lon_a, lat_b, lon_b = rect
    lat_min, lat_max = min(lat_a, lat_b), max(lat_a, lat_b)
    lon_min, lon_max = min(lon_a, lon_b), max(lon_a, lon_b)
    return lat_min <= lat <= lat_max and lon_min <= lon <= lon_max


def system_covers_point(sys_node: "SystemNode", lat: float, lon: float) -> Tuple[bool, float]:
    """Return (covered, best_delta_miles). best_delta is min(distance - range)."""
    best_delta = float("inf")
    covered = False
    for group in sys_node.groups:
        for rect in group.rectangles:
            if rectangle_contains_point(rect, lat, lon):
                covered = True
                best_delta = min(best_delta, 0.0)
        if group.lat is None or group.lon is None:
            continue
        d = haversine_miles(lat, lon, group.lat, group.lon)
        rng = group.range_miles or 0.0
        delta = d - rng
        if delta < best_delta:
            best_delta = delta
        if rng > 0 and d <= rng:
            covered = True
    for site in sys_node.sites:
        if site.lat is None or site.lon is None:
            continue
        d = haversine_miles(lat, lon, site.lat, site.lon)
        rng = site.range_miles or 0.0
        delta = d - rng
        if delta < best_delta:
            best_delta = delta
        if rng > 0 and d <= rng:
            covered = True
    return covered, best_delta


def nearest_distance_miles(sys_node: "SystemNode", lat: float, lon: float) -> Optional[float]:
    best = None
    for group in sys_node.groups:
        if group.lat is None or group.lon is None:
            continue
        d = haversine_miles(lat, lon, group.lat, group.lon)
        if best is None or d < best:
            best = d
    for site in sys_node.sites:
        if site.lat is None or site.lon is None:
            continue
        d = haversine_miles(lat, lon, site.lat, site.lon)
        if best is None or d < best:
            best = d
    return best


def system_has_geo(sys_node: "SystemNode") -> bool:
    for group in sys_node.groups:
        if group.lat is not None and group.lon is not None:
            return True
    for site in sys_node.sites:
        if site.lat is not None and site.lon is not None:
            return True
    return False

# ---------------------------------------------------------------------------
# Config Parser (hpdb.cfg)
# ---------------------------------------------------------------------------

class HpdConfig:
    """Parses hpdb.cfg for state/county info."""

    def __init__(self):
        self.states: Dict[int, Tuple[str, str]] = {}
        self.counties: Dict[int, Tuple[str, int]] = {}
        self.state_files: Dict[int, str] = {}

    def load(self, cfg_path: str):
        self.states.clear()
        self.counties.clear()

        hpdb_dir = os.path.dirname(cfg_path)

        with open(cfg_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.rstrip("\r\n")
                fields = line.split("\t")
                if not fields:
                    continue

                if fields[0] == "StateInfo":
                    sid = self._extract_int(fields[1])
                    name = fields[3] if len(fields) > 3 else ""
                    abbrev = fields[4] if len(fields) > 4 else ""
                    self.states[sid] = (name, abbrev)
                    hpd_file = os.path.join(
                        hpdb_dir, f"s_{sid:06d}.hpd"
                    )
                    if os.path.exists(hpd_file):
                        self.state_files[sid] = hpd_file

                elif fields[0] == "CountyInfo":
                    cid = self._extract_int(fields[1])
                    sid = self._extract_int(fields[2])
                    name = fields[3] if len(fields) > 3 else ""
                    self.counties[cid] = (name, sid)

    def get_state_name(self, sid: int) -> str:
        name, abbrev = self.states.get(sid, ("Unknown", ""))
        if abbrev:
            return f"{name} ({abbrev})"
        return name

    def get_counties_for_state(self, sid: int) -> List[Tuple[int, str]]:
        result = []
        for cid, (name, csid) in self.counties.items():
            if csid == sid:
                result.append((cid, name))
        result.sort(key=lambda x: x[1])
        return result

    @staticmethod
    def _extract_int(field_str: str) -> int:
        if "=" in field_str:
            field_str = field_str.split("=", 1)[1]
        try:
            return int(field_str)
        except (ValueError, TypeError):
            return 0


class ZipCountyLookup:
    """
    Zip-to-county mapping loader.

    Supports a user-supplied `zip_county_map.json` next to the app with schema:
    {
      "by_zip": {
        "33101": [
          {"state_id": 12, "county_id": 86, "county_name": "Miami-Dade"}
        ]
      }
    }
    """

    def __init__(
        self,
        script_dir: Path,
        *,
        bundled_dir: Optional[Path] = None,
    ):
        self.by_zip: Dict[str, List[Dict[str, Any]]] = {}
        self.script_dir = script_dir
        self.bundled_dir = bundled_dir or script_dir
        self._load(script_dir, self.bundled_dir)

    def _load(self, script_dir: Path, bundled_dir: Path):
        # Preference order: a user-provided override in the app dir,
        # then the bundled sample. The bundled dir may differ from the
        # app dir when running as a PyInstaller frozen EXE.
        candidates = [
            script_dir / "zip_county_map.json",
            script_dir / "data" / "zip_county_map_sample.json",
            bundled_dir / "data" / "zip_county_map_sample.json",
        ]
        for candidate in candidates:
            if not candidate.exists():
                continue
            try:
                with candidate.open("r", encoding="utf-8") as f:
                    payload = json.load(f)
            except Exception:
                continue
            by_zip = payload.get("by_zip", {})
            if isinstance(by_zip, dict):
                self.by_zip = {
                    self.normalize_zip(zip_code): entries
                    for zip_code, entries in by_zip.items()
                    if isinstance(entries, list)
                }
                return

    @staticmethod
    def normalize_zip(zip_code: str) -> str:
        digits = "".join(ch for ch in zip_code if ch.isdigit())
        if len(digits) >= 5:
            return digits[:5]
        return digits

    def lookup(self, zip_code: str, state_id: Optional[int] = None) -> List[Dict[str, Any]]:
        z = self.normalize_zip(zip_code)
        rows = self.by_zip.get(z, [])
        if state_id is None:
            return rows
        return [row for row in rows if row.get("state_id") == state_id]

    def resolve(
        self, zip_code: str, config: HpdConfig, preferred_state_id: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        z = self.normalize_zip(zip_code)
        if len(z) != 5:
            return None

        local_matches = self.by_zip.get(z, [])
        if preferred_state_id is not None:
            local_matches = [
                row for row in local_matches if row.get("state_id") in (None, preferred_state_id)
            ]
        if local_matches:
            resolved = self._resolve_match(local_matches[0], config, preferred_state_id)
            if resolved:
                resolved["source"] = "local"
                return resolved

        resolved = self._resolve_via_nominatim(z, config, preferred_state_id)
        if resolved:
            resolved["source"] = "online"
            self._persist_mapping(z, resolved)
            return resolved
        return None

    def _resolve_match(
        self,
        match: Dict[str, Any],
        config: HpdConfig,
        preferred_state_id: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        state_id = match.get("state_id")
        if not isinstance(state_id, int):
            state_id = self._state_id_from_name_or_abbrev(
                config, match.get("state_name"), match.get("state_abbrev")
            )
        if not isinstance(state_id, int):
            state_id = preferred_state_id
        if not isinstance(state_id, int):
            return None

        county_id = match.get("county_id")
        county_name = match.get("county_name")

        if not isinstance(county_id, int) and isinstance(county_name, str):
            county_id = self._county_id_from_name(config, state_id, county_name)

        if not isinstance(county_name, str) and isinstance(county_id, int):
            county_name = next(
                (name for cid, name in config.get_counties_for_state(state_id) if cid == county_id),
                "",
            )

        if not isinstance(county_id, int):
            return None

        return {
            "state_id": state_id,
            "county_id": county_id,
            "county_name": county_name or "",
        }

    def _resolve_via_nominatim(
        self,
        zip_code: str,
        config: HpdConfig,
        preferred_state_id: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        params = urllib.parse.urlencode(
            {
                "postalcode": zip_code,
                "country": "us",
                "format": "jsonv2",
                "addressdetails": 1,
                "limit": 1,
            }
        )
        url = f"https://nominatim.openstreetmap.org/search?{params}"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "scanner-manager/0.1 (zip-lookup)",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except Exception:
            return None

        if not isinstance(payload, list) or not payload:
            return None

        address = payload[0].get("address", {})
        if not isinstance(address, dict):
            return None

        state_name = address.get("state")
        state_abbrev = address.get("ISO3166-2-lvl4", "")
        if isinstance(state_abbrev, str) and "-" in state_abbrev:
            state_abbrev = state_abbrev.split("-", 1)[1]
        county_name = address.get("county", "")

        state_id = self._state_id_from_name_or_abbrev(config, state_name, state_abbrev)
        if state_id is None:
            state_id = preferred_state_id
        if state_id is None:
            return None

        county_id = self._county_id_from_name(config, state_id, county_name or "")
        if county_id is None:
            return None

        return {
            "state_id": state_id,
            "county_id": county_id,
            "county_name": county_name or "",
            "state_name": state_name or "",
            "state_abbrev": state_abbrev or "",
        }

    def _persist_mapping(self, zip_code: str, resolved: Dict[str, Any]):
        self.by_zip[zip_code] = [
            {
                "state_id": resolved["state_id"],
                "county_id": resolved["county_id"],
                "county_name": resolved.get("county_name", ""),
            }
        ]
        target = self.script_dir / "zip_county_map.json"
        data = {"by_zip": self.by_zip}
        try:
            with target.open("w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    @staticmethod
    def _normalize_name(name: str) -> str:
        clean = " ".join((name or "").strip().lower().split())
        clean = clean.replace(" county", "")
        return clean

    def _county_id_from_name(self, config: HpdConfig, state_id: int, county_name: str) -> Optional[int]:
        target = self._normalize_name(county_name)
        if not target:
            return None
        for county_id, name in config.get_counties_for_state(state_id):
            if self._normalize_name(name) == target:
                return county_id
        return None

    def _state_id_from_name_or_abbrev(
        self, config: HpdConfig, state_name: Any, state_abbrev: Any
    ) -> Optional[int]:
        target_name = self._normalize_name(state_name) if isinstance(state_name, str) else ""
        target_abbrev = state_abbrev.strip().upper() if isinstance(state_abbrev, str) else ""
        for sid, (name, abbrev) in config.states.items():
            if target_abbrev and abbrev.upper() == target_abbrev:
                return sid
            if target_name and self._normalize_name(name) == target_name:
                return sid
        return None


class FirmwareZipTable:
    """Parses scanner firmware ZipTable and maps ZIP -> (state abbrev, lat, lon).

    In addition to the state/coord maps, ``zip_flag_bytes`` captures the
    byte between the ASCII key and the coordinate block (usually the
    ASCII NUL string terminator, but some firmware revisions stash a
    region/sub-division flag there) and ``zip_extras`` captures any
    bytes trailing the lat/lon pair for record sizes larger than 16.
    These are surfaced so downstream tools (CityManager, diagnostics,
    future re-writers) can preserve unknown bytes verbatim instead of
    silently dropping them.
    """

    START_MARKER = b"START_ZIP_TABLE\x00"
    END_MARKER = b"END_ZIP_TABLE\x00"
    COORD_SCALE = 600000.0
    LAT_OFFSET = 90.0
    LON_OFFSET = 360.0

    def __init__(self):
        self.zip_to_state_abbrev: Dict[str, str] = {}
        self.zip_to_coords: Dict[str, Tuple[float, float]] = {}
        self.zip_flag_bytes: Dict[str, int] = {}
        self.zip_extras: Dict[str, bytes] = {}
        self.record_size: Optional[int] = None
        self.source_path: Optional[Path] = None

    def load_from_sd(self, sd_root: str) -> bool:
        firmware_dir = Path(sd_root) / "firmware"
        if not firmware_dir.exists():
            return False
        candidates = sorted(firmware_dir.glob("ZipTable*.dat"))
        if not candidates:
            return False
        table_path = candidates[0]
        parsed = self._parse_zip_file_full(table_path)
        if not parsed["state_map"]:
            return False
        self.zip_to_state_abbrev = parsed["state_map"]
        self.zip_to_coords = parsed["coord_map"]
        self.zip_flag_bytes = parsed["flag_bytes"]
        self.zip_extras = parsed["extras"]
        self.record_size = parsed["record_size"]
        self.source_path = table_path
        return True

    def state_abbrev_for_zip(self, zip_code: str) -> Optional[str]:
        z = "".join(ch for ch in zip_code if ch.isdigit())[:5]
        if len(z) != 5:
            return None
        return self.zip_to_state_abbrev.get(z)

    def coords_for_zip(self, zip_code: str) -> Optional[Tuple[float, float]]:
        z = "".join(ch for ch in zip_code if ch.isdigit())[:5]
        if len(z) != 5:
            return None
        return self.zip_to_coords.get(z)

    @classmethod
    def _parse_zip_file(cls, path: Path) -> Tuple[Dict[str, str], Dict[str, Tuple[float, float]]]:
        parsed = cls._parse_zip_file_full(path)
        return parsed["state_map"], parsed["coord_map"]

    @classmethod
    def _parse_zip_file_full(cls, path: Path) -> Dict[str, object]:
        empty = {
            "state_map": {},
            "coord_map": {},
            "flag_bytes": {},
            "extras": {},
            "record_size": None,
        }
        try:
            data = path.read_bytes()
        except Exception:
            return dict(empty)
        start = data.find(cls.START_MARKER)
        end = data.find(cls.END_MARKER)
        if start < 0 or end < 0 or end <= start:
            return dict(empty)
        payload = data[start + len(cls.START_MARKER): end]
        record_size = cls._detect_record_size(payload)
        if record_size is None:
            return dict(empty)
        import struct
        state_map: Dict[str, str] = {}
        coord_map: Dict[str, Tuple[float, float]] = {}
        flag_bytes: Dict[str, int] = {}
        extras: Dict[str, bytes] = {}
        for i in range(0, len(payload) - record_size + 1, record_size):
            rec = payload[i: i + record_size]
            key = rec[:7].decode("ascii", errors="ignore")
            if not re.fullmatch(r"[A-Z]{2}\d{5}", key):
                continue
            zip_code = key[2:]
            state_map[zip_code] = key[:2]
            if len(rec) >= 8:
                flag_bytes[zip_code] = rec[7]
            if len(rec) >= 16:
                try:
                    lat_raw = struct.unpack(">I", rec[8:12])[0]
                    lon_raw = struct.unpack(">I", rec[12:16])[0]
                    lat = lat_raw / cls.COORD_SCALE - cls.LAT_OFFSET
                    lon = lon_raw / cls.COORD_SCALE - cls.LON_OFFSET
                    if -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0:
                        coord_map[zip_code] = (lat, lon)
                except Exception:
                    pass
            if record_size > 16:
                tail = bytes(rec[16:])
                if any(b != 0 for b in tail):
                    extras[zip_code] = tail
        return {
            "state_map": state_map,
            "coord_map": coord_map,
            "flag_bytes": flag_bytes,
            "extras": extras,
            "record_size": record_size,
        }

    @staticmethod
    def _detect_record_size(payload: bytes) -> Optional[int]:
        best_size = None
        best_hits = -1
        best_checked = 0
        for size in (16, 12, 20, 24):
            hits = 0
            checked = 0
            for i in range(0, min(len(payload), size * 200), size):
                rec = payload[i: i + size]
                if len(rec) < 8:
                    continue
                checked += 1
                key = rec[:7].decode("ascii", errors="ignore")
                if re.fullmatch(r"[A-Z]{2}\d{5}", key):
                    hits += 1
            if checked and hits > best_hits:
                best_hits = hits
                best_size = size
                best_checked = checked
        if best_size is None:
            return None
        min_hits = 1 if best_checked <= 10 else 10
        if best_hits < min_hits:
            return None
        return best_size


@dataclass
class CityRecord:
    state_abbrev: str
    city_id: int
    lat: float
    lon: float
    extras: bytes = b""


class FirmwareCityTable:
    """Parses scanner firmware CityTable (coordinates + state + internal city id).

    The minimum known record is 12 bytes (2B state / 2B city_id / 4B lat
    / 4B lon). If the detected record size is bigger we surface the
    trailing bytes on :class:`CityRecord` as ``extras`` so they're not
    silently dropped by the re-writer.
    """

    START_MARKER = b"START_CITY_TABLE\x00"
    END_MARKER = b"END_CITY_TABLE\x00"
    RECORD_SIZE = 12
    COORD_SCALE = 600000.0
    LAT_OFFSET = 90.0
    LON_OFFSET = 360.0

    def __init__(self):
        self.records: List[CityRecord] = []
        self.by_state: Dict[str, List[CityRecord]] = {}
        self.record_size: int = self.RECORD_SIZE
        self.source_path: Optional[Path] = None

    def load_from_sd(self, sd_root: str) -> bool:
        firmware_dir = Path(sd_root) / "firmware"
        if not firmware_dir.exists():
            return False
        candidates = sorted(firmware_dir.glob("CityTable*.dat"))
        if not candidates:
            return False
        table_path = candidates[0]
        records, rec_size = self._parse_file_with_size(table_path)
        if not records:
            return False
        self.records = records
        self.record_size = rec_size
        self.by_state = {}
        for rec in records:
            self.by_state.setdefault(rec.state_abbrev, []).append(rec)
        self.source_path = table_path
        return True

    def is_loaded(self) -> bool:
        return bool(self.records)

    @classmethod
    def _parse_file(cls, path: Path) -> List[CityRecord]:
        records, _ = cls._parse_file_with_size(path)
        return records

    @classmethod
    def _detect_city_record_size(cls, payload: bytes) -> int:
        """Return 12 unless a larger fixed size scores strictly better.

        Newer firmware may pad records with additional bytes; we never
        guess below 12 (the known minimum) and we only switch to a
        larger size if it produces more valid records without dropping
        any that 12-byte parsing would find.
        """
        best_size = cls.RECORD_SIZE
        best_hits = cls._count_valid_city_records(payload, best_size)
        for size in (16, 20, 24):
            if len(payload) < size * 10:
                continue
            hits = cls._count_valid_city_records(payload, size)
            # Require a clear improvement so we don't drop records by
            # over-fitting to an arbitrary alignment.
            if hits > best_hits * 1.1 and hits > 0:
                best_size = size
                best_hits = hits
        return best_size

    @classmethod
    def _count_valid_city_records(cls, payload: bytes, size: int) -> int:
        import struct
        hits = 0
        for i in range(0, len(payload) - size + 1, size):
            rec = payload[i: i + size]
            if len(rec) < 12:
                continue
            state_bytes = rec[:2]
            state_abbrev = state_bytes.decode("ascii", errors="ignore")
            if not re.fullmatch(r"[A-Z]{2}", state_abbrev):
                continue
            try:
                lat_raw = struct.unpack(">I", rec[4:8])[0]
                lon_raw = struct.unpack(">I", rec[8:12])[0]
            except Exception:
                continue
            lat = lat_raw / cls.COORD_SCALE - cls.LAT_OFFSET
            lon = lon_raw / cls.COORD_SCALE - cls.LON_OFFSET
            if -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0:
                hits += 1
        return hits

    @classmethod
    def _parse_file_with_size(cls, path: Path) -> Tuple[List[CityRecord], int]:
        try:
            data = path.read_bytes()
        except Exception:
            return [], cls.RECORD_SIZE
        start = data.find(cls.START_MARKER)
        end = data.find(cls.END_MARKER)
        if start < 0 or end < 0 or end <= start:
            return [], cls.RECORD_SIZE
        payload = data[start + len(cls.START_MARKER): end]
        record_size = cls._detect_city_record_size(payload)
        import struct
        records: List[CityRecord] = []
        for i in range(0, len(payload) - record_size + 1, record_size):
            rec = payload[i: i + record_size]
            state_bytes = rec[:2]
            try:
                state_abbrev = state_bytes.decode("ascii", errors="ignore")
            except Exception:
                continue
            if not re.fullmatch(r"[A-Z]{2}", state_abbrev):
                continue
            try:
                city_id = struct.unpack(">H", rec[2:4])[0]
                lat_raw = struct.unpack(">I", rec[4:8])[0]
                lon_raw = struct.unpack(">I", rec[8:12])[0]
            except Exception:
                continue
            lat = lat_raw / cls.COORD_SCALE - cls.LAT_OFFSET
            lon = lon_raw / cls.COORD_SCALE - cls.LON_OFFSET
            if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
                continue
            extras = bytes(rec[12:]) if record_size > 12 else b""
            records.append(
                CityRecord(
                    state_abbrev=state_abbrev,
                    city_id=city_id,
                    lat=lat,
                    lon=lon,
                    extras=extras,
                )
            )
        return records, record_size

    def export_patched(
        self,
        target_path: Path,
        extra_records: List[CityRecord],
        make_backup: bool = True,
    ) -> Path:
        """Write CityTable with original + extra records. Returns written path."""
        if not self.source_path:
            raise RuntimeError("Original CityTable not loaded; cannot export.")
        source = self.source_path.read_bytes()
        start = source.find(self.START_MARKER)
        end = source.find(self.END_MARKER)
        if start < 0 or end < 0 or end <= start:
            raise RuntimeError("Source CityTable markers missing; refusing to write.")
        header = source[: start + len(self.START_MARKER)]
        footer = source[end:]
        import struct
        body = bytearray(source[start + len(self.START_MARKER): end])
        rec_size = getattr(self, "record_size", None) or self.RECORD_SIZE
        tail_pad = max(0, rec_size - 12)
        for rec in extra_records:
            if len(rec.state_abbrev) != 2:
                continue
            lat_raw = int(round((rec.lat + self.LAT_OFFSET) * self.COORD_SCALE))
            lon_raw = int(round((rec.lon + self.LON_OFFSET) * self.COORD_SCALE))
            lat_raw = max(0, min(lat_raw, 0xFFFFFFFF))
            lon_raw = max(0, min(lon_raw, 0xFFFFFFFF))
            body.extend(rec.state_abbrev.encode("ascii"))
            body.extend(struct.pack(">H", rec.city_id & 0xFFFF))
            body.extend(struct.pack(">I", lat_raw))
            body.extend(struct.pack(">I", lon_raw))
            if tail_pad:
                tail = rec.extras or b""
                if len(tail) < tail_pad:
                    tail = tail + b"\x00" * (tail_pad - len(tail))
                else:
                    tail = tail[:tail_pad]
                body.extend(tail)
        if target_path == self.source_path and make_backup:
            # Single-snapshot pattern (same as HPD's .session.bak). One
            # overwrite per session keeps recovery possible without
            # accumulating timestamped copies on every save.
            write_session_snapshot(str(self.source_path))
        with target_path.open("wb") as f:
            f.write(header)
            f.write(body)
            f.write(footer)
        return target_path


class ScannerCityIndex:
    """Name-to-coordinate index derived from HPD C-Group names per state."""

    CITY_TOKEN_RE = re.compile(r"^([A-Za-z][A-Za-z .'-]{0,60})$")

    def __init__(self):
        self.by_state_name: Dict[Tuple[int, str], Tuple[float, float]] = {}

    def build(self, hpd: "HpdFile", state_id: Optional[int]):
        if state_id is None:
            return
        for system in hpd.systems:
            for group in system.groups:
                if group.lat is None or group.lon is None:
                    continue
                name = group.name or ""
                for token in self._extract_city_tokens(name):
                    key = (state_id, self._norm(token))
                    if key not in self.by_state_name:
                        self.by_state_name[key] = (group.lat, group.lon)

    def lookup(self, state_id: int, city_name: str) -> Optional[Tuple[float, float]]:
        return self.by_state_name.get((state_id, self._norm(city_name)))

    @classmethod
    def _extract_city_tokens(cls, group_name: str) -> List[str]:
        if not group_name:
            return []
        parts = [p.strip() for p in re.split(r"\s*[-:]\s*", group_name) if p.strip()]
        candidates: List[str] = []
        for part in parts:
            cleaned = re.sub(r"\([^)]*\)", "", part).strip()
            cleaned = re.sub(r"\b(County|Parish|Borough)\b", "", cleaned, flags=re.IGNORECASE).strip()
            if cleaned and cls.CITY_TOKEN_RE.match(cleaned):
                candidates.append(cleaned)
        return candidates

    @staticmethod
    def _norm(text: str) -> str:
        return " ".join((text or "").strip().lower().split())


class CustomLocationsStore:
    """Local JSON of user-added custom locations (name + state + coordinates)."""

    FILENAME = "custom_locations.json"

    def __init__(self, script_dir: Path):
        self.script_dir = script_dir
        self.locations: List[Dict[str, Any]] = []
        self.load()

    @property
    def path(self) -> Path:
        return self.script_dir / self.FILENAME

    def load(self):
        self.locations = []
        if not self.path.exists():
            return
        try:
            with self.path.open("r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception:
            return
        if isinstance(payload, dict):
            items = payload.get("locations", [])
        elif isinstance(payload, list):
            items = payload
        else:
            items = []
        if isinstance(items, list):
            cleaned: List[Dict[str, Any]] = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                try:
                    name = str(item.get("name", "")).strip()
                    state_id = int(item.get("state_id"))
                    lat = float(item.get("lat"))
                    lon = float(item.get("lon"))
                except Exception:
                    continue
                if not name:
                    continue
                cleaned.append({"name": name, "state_id": state_id, "lat": lat, "lon": lon})
            self.locations = cleaned

    def save(self):
        data = {"locations": self.locations}
        with self.path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def add(self, name: str, state_id: int, lat: float, lon: float):
        self.locations.append(
            {"name": name.strip(), "state_id": state_id, "lat": lat, "lon": lon}
        )
        self.save()

    def remove(self, name: str, state_id: int):
        key = name.strip().lower()
        self.locations = [
            loc for loc in self.locations
            if not (loc["state_id"] == state_id and loc["name"].lower() == key)
        ]
        self.save()

    def lookup(self, state_id: int, name: str) -> Optional[Tuple[float, float]]:
        key = name.strip().lower()
        for loc in self.locations:
            if loc["state_id"] == state_id and loc["name"].lower() == key:
                return (loc["lat"], loc["lon"])
        return None


_SCANNER_HEADER_TYPES = {"TargetModel", "FormatVersion", "DateModified"}


def parse_discovery_file(path: Path) -> Dict[str, Any]:
    """Parse a discovery log file as tab-delimited records.
    Falls back to reporting raw bytes when unreadable as text."""
    info: Dict[str, Any] = {
        "path": str(path),
        "name": path.name,
        "size_bytes": 0,
        "modified": "",
        "header": {},
        "records": [],
        "counts": {},
        "raw_preview": "",
    }
    try:
        stat = path.stat()
        info["size_bytes"] = stat.st_size
        info["modified"] = datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds")
    except Exception:
        pass
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return info
    info["raw_preview"] = text[:2000]
    for line in text.splitlines():
        fields = line.split("\t")
        if not fields or not fields[0]:
            continue
        rec_type = fields[0]
        if rec_type in _SCANNER_HEADER_TYPES and len(fields) > 1:
            info["header"][rec_type] = fields[1]
            continue
        info["records"].append((rec_type, fields))
        info["counts"][rec_type] = info["counts"].get(rec_type, 0) + 1
    return info


def discover_log_files(discovery_root: Path) -> Dict[str, List[Path]]:
    """Walk discovery/Conventional and discovery/Trunk subfolders for log files."""
    groups: Dict[str, List[Path]] = {"Conventional": [], "Trunk": []}
    if not discovery_root.exists():
        return groups
    for kind in ("Conventional", "Trunk"):
        sub = discovery_root / kind
        if not sub.exists():
            continue
        for p in sorted(sub.rglob("*")):
            if p.is_file() and not p.name.startswith("."):
                groups[kind].append(p)
    return groups


def discover_alert_files(alert_root: Path) -> List[Path]:
    """Return every file under the ``alert/`` folder, recursively, skipping
    hidden entries. Flat list; folder grouping happens at render time.
    """
    files: List[Path] = []
    if not alert_root.exists():
        return files
    for p in sorted(alert_root.rglob("*")):
        if p.is_file() and not p.name.startswith("."):
            files.append(p)
    return files


def resolve_city_offline(
    name: str,
    config: HpdConfig,
    custom: CustomLocationsStore,
    firmware_city: FirmwareCityTable,
    city_index: ScannerCityIndex,
    state_id: Optional[int] = None,
    state_abbrev: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    cleaned = name.strip()
    if not cleaned:
        return None
    abbrev_upper = (state_abbrev or "").strip().upper() or None
    resolved_state_id = state_id
    if resolved_state_id is None and abbrev_upper:
        for sid, (_, abbrev) in config.states.items():
            if abbrev.upper() == abbrev_upper:
                resolved_state_id = sid
                break
    if resolved_state_id is not None:
        result = custom.lookup(resolved_state_id, cleaned)
        if result is not None:
            return {
                "state_id": resolved_state_id,
                "lat": result[0],
                "lon": result[1],
                "source": "custom",
            }
        result = city_index.lookup(resolved_state_id, cleaned)
        if result is not None:
            return {
                "state_id": resolved_state_id,
                "lat": result[0],
                "lon": result[1],
                "source": "hpd",
            }
    return None


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def format_freq(freq_hz: int) -> str:
    """Convert Hz integer to readable MHz string."""
    if freq_hz == 0:
        return ""
    mhz = freq_hz / 1_000_000
    return f"{mhz:.4f} MHz"


def parse_freq_mhz(text: str) -> int:
    """Convert user-entered MHz string to Hz integer."""
    cleaned = text.strip().upper().replace("MHZ", "").replace(" ", "").replace(",", "")
    mhz = float(cleaned)
    return int(round(mhz * 1_000_000))


def service_label(stype: int) -> str:
    name = SERVICE_TYPES.get(stype, f"Type {stype}")
    return f"{stype} - {name}"


def is_scannable(stype: int) -> bool:
    return stype in SCANNABLE_TYPES


BACKUP_SUFFIX_PATTERN = re.compile(
    r"^(?P<base>.+)\.backup_(?P<ts>\d{8}_\d{6})(?:_\w+)?$"
)


def list_backups_for(source_path: str) -> List[Path]:
    """Return backup files for source_path sorted oldest-first."""
    directory = Path(source_path).parent
    base_name = Path(source_path).name
    prefix = f"{base_name}.backup_"
    items: List[Path] = []
    if not directory.exists():
        return items
    for p in directory.iterdir():
        if p.is_file() and p.name.startswith(prefix):
            items.append(p)
    items.sort(key=lambda p: p.stat().st_mtime)
    return items


def discover_backups(search_roots: List[Path]) -> Dict[str, List[Path]]:
    """Walk given directories and group backup files by their source path.

    Also de-duplicates overlapping search roots (e.g., SD root + HPD folder).
    """
    groups: Dict[str, List[Path]] = {}
    seen_files: Set[str] = set()
    for root in search_roots:
        if not root or not root.exists():
            continue
        for p in root.rglob("*.backup_*"):
            if not p.is_file():
                continue
            m = BACKUP_SUFFIX_PATTERN.match(p.name)
            if not m:
                continue
            try:
                key = str(p.resolve())
            except Exception:
                key = str(p)
            if key in seen_files:
                continue
            seen_files.add(key)
            source_name = m.group("base")
            source_path = str(p.parent / source_name)
            groups.setdefault(source_path, []).append(p)
    for source in groups:
        groups[source].sort(key=lambda p: p.stat().st_mtime)
    return groups


def prune_backups(source_path: str, max_backups: int) -> List[Path]:
    """Delete oldest backups for source_path so only the newest max_backups remain.

    Returns the list of successfully removed paths. Unlink failures are silenced.
    For a richer result (including failures), use :func:`prune_backups_detailed`.
    """
    result = prune_backups_detailed(source_path, max_backups)
    return result["removed"]


def prune_backups_detailed(source_path: str, max_backups: int) -> Dict[str, Any]:
    """Like :func:`prune_backups` but returns detailed results:
    {
        "candidates": [Path, ...] (files that should have been deleted),
        "removed": [Path, ...],
        "failed": [(Path, error_message), ...],
    }
    """
    info: Dict[str, Any] = {"candidates": [], "removed": [], "failed": []}
    if max_backups is None or max_backups < 0:
        return info
    backups = list_backups_for(source_path)
    if len(backups) <= max_backups:
        return info
    to_delete = backups[: len(backups) - max_backups]
    info["candidates"] = list(to_delete)
    for p in to_delete:
        try:
            p.unlink()
            info["removed"].append(p)
        except Exception as exc:
            info["failed"].append((p, str(exc)))
    return info


BAND_MODE_RULES: List[Tuple[float, float, str, Set[str]]] = [
    (25_000_000, 54_000_000, "FM", {"FM", "NFM"}),
    (108_000_000, 137_000_000, "AM", {"AM"}),
    (137_000_000, 174_000_000, "NFM", {"FM", "NFM"}),
    (216_000_000, 225_000_000, "NFM", {"FM", "NFM"}),
    (406_000_000, 420_000_000, "NFM", {"FM", "NFM"}),
    (450_000_000, 470_000_000, "NFM", {"FM", "NFM"}),
    (470_000_000, 512_000_000, "NFM", {"FM", "NFM"}),
    (758_000_000, 824_000_000, "NFM", {"FM", "NFM"}),
    (849_000_000, 869_000_000, "NFM", {"FM", "NFM"}),
    (894_000_000, 960_000_000, "NFM", {"FM", "NFM"}),
]


def suggest_mode_for_freq(freq_hz: int) -> Optional[str]:
    for lo, hi, suggested, _ in BAND_MODE_RULES:
        if lo <= freq_hz <= hi:
            return suggested
    return None


def audit_mode_issues(
    entry: "FreqEntry",
) -> Optional[Tuple[str, str]]:
    """Return (issue, suggested_mode) tuple when the entry has a mode/band problem."""
    if entry.entry_type != "C-Freq":
        return None
    rec = entry.record
    try:
        freq_hz = int(rec.get_field(5, "0"))
    except ValueError:
        return None
    if freq_hz <= 0:
        return None
    mode = rec.get_field(6, "").upper()
    suggested = suggest_mode_for_freq(freq_hz)
    if suggested is None:
        return None
    if mode == "AUTO":
        return ("AUTO mode where explicit mode is preferred", suggested)
    allowed = next(
        (allowed for lo, hi, _, allowed in BAND_MODE_RULES if lo <= freq_hz <= hi),
        set(),
    )
    if mode and allowed and mode not in allowed:
        return (f"Mode '{mode}' invalid for {freq_hz / 1_000_000:.4f} MHz", suggested)
    return None


def audit_mode_issue_with_rr(
    entry: "FreqEntry",
    rr_ref: Dict[int, Dict[str, Any]],
) -> Optional[Tuple[str, str, str]]:
    """If entry frequency matches RR reference data, return (issue, suggested, source).
    Source is "rr" when RR data contradicts the entry, "band" when band rules apply.
    Returns None when nothing to flag."""
    if entry.entry_type != "C-Freq":
        return None
    rec = entry.record
    try:
        freq_hz = int(rec.get_field(5, "0"))
    except ValueError:
        return None
    if freq_hz <= 0:
        return None
    mode = rec.get_field(6, "").upper()
    rr = rr_ref.get(freq_hz)
    if rr is not None:
        rr_mode = (rr.get("mode") or "").upper()
        if rr_mode and rr_mode != mode and rr_mode in {"FM", "NFM", "AM", "AUTO"}:
            rr_desc = rr.get("name") or f"{freq_hz / 1_000_000:.4f} MHz"
            return (
                f"RR lists mode '{rr_mode}' for {rr_desc}; HPD has '{mode or 'blank'}'",
                rr_mode,
                "rr",
            )
        if rr_mode and rr_mode == mode:
            return None
    band_issue = audit_mode_issues(entry)
    if band_issue is not None:
        issue, suggested = band_issue
        return (issue, suggested, "band")
    return None


def diff_cfreq_with_rr(
    entry_name: str,
    entry_mode: str,
    entry_tone: str,
    entry_service_type: int,
    rr_name: str,
    rr_mode: str,
    rr_tone: str,
    rr_service_type: Optional[int],
) -> Dict[str, Tuple[Any, Any]]:
    """Detect meaningful differences between existing C-Freq and RR data.

    - name: update if RR differs (non-empty)
    - mode: update if differs; prefer RR value
    - tone: update if RR provides a different non-empty tone
    - service_type: update if RR suggests a different integer type
    """
    changes: Dict[str, Tuple[Any, Any]] = {}
    if rr_name and rr_name.strip() and rr_name.strip() != (entry_name or "").strip():
        changes["name"] = (entry_name, rr_name.strip())
    rr_mode_norm = (rr_mode or "").strip().upper()
    existing_mode_norm = (entry_mode or "").strip().upper()
    if rr_mode_norm and rr_mode_norm != existing_mode_norm:
        changes["mode"] = (entry_mode, rr_mode_norm)
    rr_tone_norm = (rr_tone or "").strip()
    existing_tone_norm = (entry_tone or "").strip()
    if rr_tone_norm and rr_tone_norm != existing_tone_norm:
        changes["tone"] = (entry_tone, rr_tone_norm)
    if isinstance(rr_service_type, int) and rr_service_type > 0:
        if rr_service_type != entry_service_type:
            changes["service_type"] = (entry_service_type, rr_service_type)
    return changes


def diff_tgid_with_rr(
    entry_name: str,
    entry_mode: str,
    entry_service_type: int,
    rr_name: str,
    rr_mode: str,
    rr_service_type: Optional[int],
) -> Dict[str, Tuple[Any, Any]]:
    """Return map of field -> (old, new) for fields that should be updated from RR.

    Rules:
    - name: update if RR name differs (non-empty)
    - mode: update if existing is 'ALL' (generic) and RR is specific (D/T/DE/ANALOG), or if concrete modes mismatch
    - service_type: update if RR suggests a different concrete value
    """
    changes: Dict[str, Tuple[Any, Any]] = {}
    if rr_name and rr_name.strip() and rr_name.strip() != (entry_name or "").strip():
        changes["name"] = (entry_name, rr_name.strip())
    if rr_mode:
        rr_raw = rr_mode.strip()
        rr_n = _normalize_tgid_mode_for_diff(rr_raw)
        ex_n = _normalize_tgid_mode_for_diff(entry_mode)
        if not ex_n:
            ex_n = "ALL"
        if rr_n and rr_n != ex_n:
            concrete = frozenset({"DIGITAL", "ANALOG"})
            # Always write the canonical HPD token (DIGITAL/ANALOG/ALL), not
            # the RR short code, so the scanner parses it correctly.
            new_value = rr_n if rr_n in concrete or rr_n == "ALL" else rr_raw
            if ex_n == "ALL" and rr_n in concrete:
                changes["mode"] = (entry_mode, new_value)
            elif ex_n in concrete and rr_n in concrete:
                changes["mode"] = (entry_mode, new_value)
    if isinstance(rr_service_type, int) and rr_service_type > 0:
        if rr_service_type != entry_service_type:
            changes["service_type"] = (entry_service_type, rr_service_type)
    return changes


def entry_matches_bulk_filter(
    entry: "FreqEntry",
    entry_types: Set[str],
    service_types: Optional[Set[int]],
    county_id: Optional[int],
    system_id: Optional[str],
    avoid_state: Optional[str],
) -> bool:
    """Generic predicate for bulk operations."""
    if entry_types and entry.entry_type not in entry_types:
        return False
    if service_types is not None and entry.service_type not in service_types:
        return False
    if system_id is not None and entry.system_id != system_id:
        return False
    if county_id is not None:
        system_county = None
        if entry.system_id:
            system_county = entry.system_id if entry.system_type == "Conventional" else None
        if system_county != str(county_id):
            return False
    if avoid_state is not None:
        current_avoid = entry.record.get_field(4, "Off")
        if current_avoid != avoid_state:
            return False
    return True


def entry_passes_button_filter(
    service_type: int,
    active_button_types: Set[int],
    include_others: bool,
) -> bool:
    """Return True if an entry with this service type should appear with the given button filters."""
    if service_type in active_button_types:
        return True
    if service_type in SCANNABLE_TYPES and service_type not in active_button_types:
        return False
    return bool(include_others)


# ---------------------------------------------------------------------------
# RadioReference URL parsing
# ---------------------------------------------------------------------------

RR_SERVICE_MAP = {
    "police": 2,
    "law enforcement": 2,
    "sheriff": 2,
    "fire": 3,
    "ems": 4,
    "emergency medical": 4,
    "public works": 14,
    "highway": 14,
    "transportation": 14,
    "property management": 14,
    "security": 14,
    "industrial": 14,
    "business": 14,
}


def fetch_radioreference_data(url: str) -> Optional[Dict[str, Any]]:
    if not re.match(r"^https?://(www\.)?radioreference\.com/", url):
        raise ValueError("URL must be a radioreference.com link.")
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "scanner-manager/0.1 (+python urllib)",
            "Accept": "text/html",
        },
    )
    with urllib.request.urlopen(req, timeout=12) as resp:
        html = resp.read().decode("utf-8", errors="replace")
    lower_url = url.lower()
    parsed: Optional[Dict[str, Any]] = None
    if "/fcc/callsign/" in lower_url:
        parsed = _parse_rr_fcc_callsign(html)
        if parsed is not None:
            parsed["kind"] = "fcc_callsign"
            # Enrich with the callsign from the URL itself, which survives
            # even when the page body doesn't repeat it verbatim.
            cs_match = re.search(r"/fcc/callsign/([A-Za-z0-9]+)", url)
            if cs_match:
                parsed["fcc_callsign"] = cs_match.group(1).upper()
                for freq in parsed.get("frequencies") or []:
                    freq.setdefault("fcc_callsign", cs_match.group(1).upper())
                    if parsed.get("licensee"):
                        freq.setdefault("licensee", parsed["licensee"])
    elif "/db/aid/" in lower_url or "/db/cid/" in lower_url:
        parsed = _parse_rr_category_aid(html)
        if parsed is not None:
            parsed["kind"] = "category"
    elif "/db/ctid/" in lower_url or "/db/browse/" in lower_url:
        parsed = _parse_rr_conventional_ctid(html)
        if parsed is not None:
            parsed["kind"] = "conventional_multi"
    elif "/db/sid/" in lower_url or "/db/tid/" in lower_url:
        parsed = _parse_rr_trs_sid(html)
        if parsed is not None:
            parsed["kind"] = "trs"
    if parsed is not None:
        parsed.setdefault("source_url", url)
    return parsed


def _strip_tags(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html)


def _collapse_ws(text: str) -> str:
    return " ".join(text.replace("&nbsp;", " ").split())


def _parse_rr_fcc_callsign(html: str) -> Optional[Dict[str, Any]]:
    licensee = _extract_labeled_value(html, "Licensee")
    radio_service = _extract_labeled_value(html, "Radio Service")
    notes = _extract_labeled_value(html, "Notes")
    county = _extract_labeled_value(html, "County")
    state = _extract_labeled_value(html, "State")

    frequencies: List[Dict[str, Any]] = []
    classes_wanted = {"FB", "FB2", "FB8", "FXO", "MO"}
    classes_secondary = {"FX1"}
    seen: Set[Tuple[str, str]] = set()
    for row_match in re.finditer(r"<tr[^>]*>(.*?)</tr>", html, re.DOTALL | re.IGNORECASE):
        row = row_match.group(1)
        cells = [
            _collapse_ws(_strip_tags(cell))
            for cell in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.DOTALL | re.IGNORECASE)
        ]
        if len(cells) < 5:
            continue
        freq_match = re.search(r"^(\d{2,4}\.\d+)$", cells[1].replace(",", "")) if len(cells) > 1 else None
        if not freq_match:
            continue
        try:
            mhz = float(freq_match.group(1))
        except ValueError:
            continue
        if not (25.0 <= mhz <= 1300.0):
            continue
        emission = cells[2] if len(cells) > 2 else ""
        fclass = cells[3] if len(cells) > 3 else ""
        lat = cells[6] if len(cells) > 6 else ""
        lon = cells[7] if len(cells) > 7 else ""
        city = cells[8] if len(cells) > 8 else ""
        key = (freq_match.group(1), fclass)
        if key in seen:
            continue
        seen.add(key)
        frequencies.append(
            {
                "mhz": mhz,
                "emission": emission,
                "class": fclass,
                "lat": lat,
                "lon": lon,
                "city": city,
                "mode": _emission_to_mode(emission),
                "tone": "",
                "name": licensee or "",
            }
        )

    if frequencies:
        def priority(item: Dict[str, Any]) -> Tuple[int, float]:
            fclass = item.get("class", "")
            tier = 0 if fclass in classes_wanted else (1 if fclass in classes_secondary else 2)
            return (tier, item.get("mhz", 0.0))

        frequencies.sort(key=priority)

    suggested = _guess_service_type(f"{radio_service} {notes} {licensee}")

    # Propagate licensee onto every row so downstream imports get the cross-ref.
    for freq in frequencies:
        if licensee:
            freq["licensee"] = licensee
        if county:
            freq["county"] = county

    return {
        "name": licensee or "",
        "licensee": licensee or "",
        "frequencies": frequencies,
        "county": county,
        "state": state,
        "suggested_service_type": suggested,
    }


def _emission_to_mode(emission: str) -> str:
    if not emission:
        return "NFM"
    digital_hints = ("F1D", "F1E", "D7W", "GXE", "G1D")
    if any(hint in emission for hint in digital_hints):
        return "NFM"
    if "F3E" in emission or "F2E" in emission:
        if emission.startswith("20K") or emission.startswith("25K"):
            return "FM"
        return "NFM"
    return "NFM"


def _guess_service_type(text: str) -> Optional[int]:
    if not text:
        return None
    lowered = text.lower()
    for keyword, service_id in RR_SERVICE_MAP.items():
        if keyword in lowered:
            return service_id
    return None


def _extract_cfreq_rows_from_html(html_segment: str) -> List[Dict[str, Any]]:
    """Extract conventional-frequency rows from a RadioReference HTML fragment.

    Also captures the FCC callsign and licensee/tag anchor text from the
    License cell (index 1) so later cross-referencing can identify
    operators by callsign and licensee name.
    """
    frequencies: List[Dict[str, Any]] = []
    for row_match in re.finditer(r"<tr[^>]*>(.*?)</tr>", html_segment, re.DOTALL | re.IGNORECASE):
        row = row_match.group(1)
        raw_cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.DOTALL | re.IGNORECASE)
        cells = [_collapse_ws(_strip_tags(c)) for c in raw_cells]
        if len(cells) < 7:
            continue
        freq_text = cells[0].replace(",", "")
        m = re.match(r"^(\d{2,4}\.\d+)$", freq_text)
        if not m:
            continue
        try:
            mhz = float(m.group(1))
        except ValueError:
            continue
        if not (25.0 <= mhz <= 1300.0):
            continue

        callsign = ""
        licensee_text = ""
        if len(raw_cells) > 1:
            cs_match = re.search(
                r"/db/fcc/callsign/([A-Za-z0-9]+)", raw_cells[1], re.IGNORECASE,
            )
            if cs_match:
                callsign = cs_match.group(1).upper()
            lic_match = re.search(
                r"<a[^>]*/db/fcc/callsign/[^>]*>([^<]+)</a>",
                raw_cells[1],
                re.IGNORECASE,
            )
            if lic_match:
                licensee_text = _collapse_ws(_strip_tags(lic_match.group(1)))
            elif cells[1]:
                licensee_text = cells[1]

        tone_text = cells[3] if len(cells) > 3 else ""
        alpha = cells[4] if len(cells) > 4 else ""
        desc = cells[5] if len(cells) > 5 else ""
        mode_text = cells[6] if len(cells) > 6 else ""
        tag = cells[7] if len(cells) > 7 else ""
        name = desc or alpha or ""
        frequencies.append(
            {
                "mhz": mhz,
                "mode": _rr_mode_to_hpd(mode_text),
                "tone": _rr_tone_to_hpd(tone_text),
                "name": name,
                "alpha": alpha,
                "tag": tag,
                "fcc_callsign": callsign,
                "licensee": licensee_text,
                "licensee_text": licensee_text,
                "suggested_service_type": _guess_service_type(f"{tag} {desc}") or 14,
            }
        )
    return frequencies


def _parse_rr_category_aid(html: str) -> Optional[Dict[str, Any]]:
    title = _extract_category_title(html)
    frequencies = _extract_cfreq_rows_from_html(html)
    if not frequencies:
        return None
    return {
        "group_name": title or "RadioReference Group",
        "frequencies": frequencies,
    }


def _parse_rr_conventional_ctid(html: str) -> Optional[Dict[str, Any]]:
    """Parse a RR county/browse page into multiple categories of conventional frequencies.

    Tries subsection heading tags (h3, h4, h2) in order and groups frequency rows
    under each subsection. Falls back to a single category when no subsections
    produce usable rows.
    """
    title = _extract_category_title(html)
    categories: List[Dict[str, Any]] = []
    seen_total_rows = 0
    for heading_tag in ("h3", "h4", "h5", "h2"):
        cat_pattern = re.compile(
            rf"<{heading_tag}[^>]*>(?P<title>.*?)</{heading_tag}>"
            rf"(?P<after>.*?)(?=<{heading_tag}[^>]*>|<footer|$)",
            re.DOTALL | re.IGNORECASE,
        )
        tmp: List[Dict[str, Any]] = []
        for m in cat_pattern.finditer(html):
            cat_title = _clean_rr_category_title(m.group("title"))
            if not cat_title or cat_title.lower().startswith("premium subscription"):
                continue
            freqs = _extract_cfreq_rows_from_html(m.group("after"))
            if not freqs:
                continue
            tmp.append({"name": cat_title, "frequencies": freqs})
            seen_total_rows += len(freqs)
        if tmp:
            categories = tmp
            break
    if not categories:
        freqs = _extract_cfreq_rows_from_html(html)
        if freqs:
            categories = [
                {"name": title or "RadioReference Frequencies", "frequencies": freqs}
            ]
    if not categories:
        return None
    return {"title": title, "categories": categories}


def _parse_rr_trs_sid(html: str) -> Optional[Dict[str, Any]]:
    """Parse a RadioReference trunked system (sid) page into categories + talkgroups."""
    system_name = ""
    page_title_match = re.search(
        r"<title[^>]*>(.*?)</title>", html, re.DOTALL | re.IGNORECASE
    )
    if page_title_match:
        raw_title = _collapse_ws(_strip_tags(page_title_match.group(1)))
        primary = raw_title.split(",", 1)[0].strip()
        if primary:
            system_name = primary
    if not system_name:
        heading_match = re.search(
            r"<h[12][^>]*>(.*?)</h[12]>", html, re.DOTALL | re.IGNORECASE
        )
        if heading_match:
            system_name = _collapse_ws(_strip_tags(heading_match.group(1)))
    categories: List[Dict[str, Any]] = []
    category_pattern = re.compile(
        r"<h5[^>]*>(?P<title>.*?)</h5>(?P<after>.*?)(?=<h5[^>]*>|<footer|$)",
        re.DOTALL | re.IGNORECASE,
    )
    for m in category_pattern.finditer(html):
        title = _clean_rr_category_title(m.group("title"))
        if not title or title.lower() in ("premium subscription required",):
            continue
        segment = m.group("after")
        talkgroups = _extract_rr_trs_talkgroups(segment)
        if not talkgroups:
            continue
        categories.append({"name": title, "talkgroups": talkgroups})
    if not categories:
        return None
    return {"system_name": system_name or "RadioReference Trunk System", "categories": categories}


RR_CATEGORY_TITLE_TRAIL_PATTERNS = (
    "view talkgroup category details",
    "view subcategory details",
    "view details",
)


def _clean_rr_category_title(title_html: str) -> str:
    """Strip inline <a> link text and known trailing UI phrases from a category title."""
    without_anchors = re.sub(
        r"<a[^>]*>.*?</a>", "", title_html, flags=re.DOTALL | re.IGNORECASE
    )
    text = _collapse_ws(_strip_tags(without_anchors))
    lowered = text.lower()
    for phrase in RR_CATEGORY_TITLE_TRAIL_PATTERNS:
        if lowered.endswith(phrase):
            text = text[: len(text) - len(phrase)].rstrip()
            break
    return text.strip()


def _extract_rr_trs_talkgroups(html_segment: str) -> List[Dict[str, Any]]:
    """Pull talkgroup rows from a category segment of a RR trunk page.

    Handles two column layouts:
      * P25 / Motorola / LTR (6 cols): DEC | HEX | Mode | Alpha Tag | Description | Tag
      * EDACS / EDACS-Ext. Addr. (5 cols): DEC | Mode | Alpha Tag | Description | Tag

    The Mode column index is auto-detected per-table from the header row, with a
    per-row fallback that checks whether cell[1] looks like a hex id or a mode
    token — so parsing still works if a particular table is missing <th>s.
    """
    talkgroups: List[Dict[str, Any]] = []
    mode_col: Optional[int] = None  # resolved from header when available
    for row_match in re.finditer(r"<tr[^>]*>(.*?)</tr>", html_segment, re.DOTALL | re.IGNORECASE):
        row = row_match.group(1)
        cell_matches = list(
            re.finditer(r"<(t[dh])[^>]*>(.*?)</\1>", row, re.DOTALL | re.IGNORECASE)
        )
        if not cell_matches:
            continue
        is_header_row = any(
            m.group(1).lower() == "th" for m in cell_matches
        )
        cells = [_collapse_ws(_strip_tags(m.group(2))) for m in cell_matches]

        if is_header_row:
            headers = [c.strip().lower() for c in cells]
            for idx, h in enumerate(headers):
                if h == "mode":
                    mode_col = idx
                    break
            continue

        if len(cells) < 5:
            continue

        dec_text = cells[0].replace(",", "").strip()
        if not dec_text.isdigit():
            continue
        try:
            tgid = int(dec_text)
        except ValueError:
            continue
        if tgid <= 0:
            continue

        if mode_col is not None and mode_col < len(cells):
            resolved_mode_col = mode_col
        else:
            resolved_mode_col = 2 if _cell_looks_like_hex_id(cells[1]) else 1

        raw_mode = cells[resolved_mode_col].strip() if resolved_mode_col < len(cells) else ""
        alpha_idx = resolved_mode_col + 1
        desc_idx = resolved_mode_col + 2
        tag_idx = resolved_mode_col + 3
        alpha = cells[alpha_idx] if alpha_idx < len(cells) else ""
        desc = cells[desc_idx] if desc_idx < len(cells) else ""
        tag = cells[tag_idx] if tag_idx < len(cells) else ""
        name = desc or alpha or ""
        mode = _rr_trs_mode_to_hpd(raw_mode)
        talkgroups.append(
            {
                "tgid": tgid,
                "name": name,
                "alpha": alpha,
                "mode": mode,
                "mode_raw": raw_mode,
                "tag": tag,
                "encrypted": is_rr_mode_encrypted(raw_mode),
                "suggested_service_type": _tag_to_service_type(tag),
            }
        )
    return talkgroups


_RR_MODE_TOKENS = {
    "A", "AE", "D", "DE", "T", "TE", "TD", "TDMA", "DMR",
    "ALL", "ANALOG", "DIGITAL", "P25", "P-25",
}


def _cell_looks_like_hex_id(cell: str) -> bool:
    """Heuristic: does this cell look like the HEX id column (P25/Moto) rather than Mode?

    RR HEX cells are compact hex numbers (e.g. '0A1', '12F4', '1000'). Mode cells are
    short alphabetic tokens (e.g. 'D', 'DE', 'T', 'TDMA', 'A'). Hex cells can contain
    the letters A-F, which overlap with Mode ('A','D'), so we require either a digit
    or a length > 2 to classify as hex.
    """
    s = (cell or "").strip().upper()
    if not s:
        return False
    if s in _RR_MODE_TOKENS:
        return False
    if not all(ch in "0123456789ABCDEF" for ch in s):
        return False
    if any(ch.isdigit() for ch in s):
        return True
    return len(s) > 2


def is_rr_mode_encrypted(rr_mode: str) -> bool:
    """True when RadioReference Mode indicates encrypted audio (BT885 can't decode)."""
    if not rr_mode:
        return False
    upper = rr_mode.strip().upper()
    return upper in {"DE", "TE", "AE"}


def _normalize_tgid_mode_for_diff(mode: str) -> str:
    """Normalize TGID mode strings so legacy/short values compare equal to what
    actually lives on the SD card (ALL / ANALOG / DIGITAL).

    The BearTracker 885 HPD TGID Mode column uses the long names exclusively;
    short forms like D / T / TD / DE only ever come from RadioReference or
    older half-baked imports, and should be considered equivalent to DIGITAL
    (or ANALOG for A/AE) for comparison purposes.
    """
    m = (mode or "").strip().upper()
    if not m:
        return ""
    if m in ("D", "TD", "T", "TDMA", "DE", "DMR"):
        return "DIGITAL"
    if m in ("A", "AE"):
        return "ANALOG"
    return m


def _rr_trs_mode_to_hpd(mode_text: str) -> str:
    """Map RadioReference trunk 'Mode' cell to a BearTracker HPD TGID mode.

    The HPD file only accepts ALL / ANALOG / DIGITAL — there is no separate
    TDMA token on this scanner, TDMA is inferred from the trunk system type
    (P25Standard). So RadioReference 'D', 'T', 'TD', 'TDMA', P25 Phase 2, etc.
    all collapse to 'DIGITAL' on disk.

    DE / TE / AE still map to DIGITAL / ANALOG respectively for storage, but
    encryption is flagged separately via is_rr_mode_encrypted() so the import
    UI can warn / skip / avoid / delete those rows.
    """
    if not mode_text:
        return "ALL"
    upper = mode_text.strip().upper()
    compact = re.sub(r"[\s\-_/]+", "", upper)

    if upper == "ALL":
        return "ALL"
    if upper == "AE":
        return "ANALOG"
    if upper in ("A", "ANALOG"):
        return "ANALOG"
    if upper in ("TE", "DE") or upper.startswith("DE/") or upper.startswith("DE "):
        return "DIGITAL"
    if upper in ("T", "TD", "D", "DMR") or "TDMA" in upper or "TDMA" in compact:
        return "DIGITAL"
    if "PHASE2" in compact or "PHASE 2" in upper:
        return "DIGITAL"
    if upper.startswith("P25"):
        return "DIGITAL"
    return "ALL"


def _tag_to_service_type(tag: str) -> Optional[int]:
    if not tag:
        return None
    lowered = tag.strip().lower()
    mapping = {
        "law dispatch": 2,
        "police dispatch": 2,
        "law tac": 7,
        "law talk": 23,
        "fire dispatch": 3,
        "fire-tac": 8,
        "fire-talk": 24,
        "ems dispatch": 4,
        "ems-tac": 9,
        "ems-talk": 25,
        "public works": 14,
        "multi-tac": 6,
        "multi-talk": 22,
        "multi dispatch": 1,
        "transportation": 14,
        "security": 14,
        "business": 14,
        "utilities": 14,
        "hospital": 4,
        "emergency ops": 14,
    }
    if lowered in mapping:
        return mapping[lowered]
    return _guess_service_type(tag)


def _extract_category_title(html: str) -> str:
    for heading_tag in ("h1", "h2", "h3"):
        match = re.search(rf"<{heading_tag}[^>]*>(.*?)</{heading_tag}>", html, re.DOTALL | re.IGNORECASE)
        if match:
            text = _collapse_ws(_strip_tags(match.group(1)))
            if text:
                return text
    return ""


def _rr_mode_to_hpd(mode_text: str) -> str:
    if not mode_text:
        return "NFM"
    upper = mode_text.strip().upper()
    if upper == "FM":
        return "FM"
    if upper in ("FMN", "NFM"):
        return "NFM"
    if upper in ("AM",):
        return "AM"
    if upper in ("DMR", "NXDN", "P25", "MOTOTRBO"):
        return "AUTO"
    return "NFM"


def _rr_tone_to_hpd(tone_text: str) -> str:
    if not tone_text:
        return ""
    cleaned = tone_text.strip()
    pl_match = re.match(r"^(\d+\.?\d*)\s*PL$", cleaned, re.IGNORECASE)
    if pl_match:
        return f"TONE=C{pl_match.group(1)}"
    dpl_match = re.match(r"^(\d+)\s*DPL$", cleaned, re.IGNORECASE)
    if dpl_match:
        return f"TONE=D{dpl_match.group(1)}"
    return ""


def _extract_labeled_value(html: str, label: str) -> str:
    pattern = re.compile(
        rf"{re.escape(label)}\s*:?\s*</[^>]+>\s*<[^>]+>(.*?)</",
        re.IGNORECASE | re.DOTALL,
    )
    match = pattern.search(html)
    if not match:
        return ""
    return _collapse_ws(_strip_tags(match.group(1)))

# ---------------------------------------------------------------------------
# Main GUI Application
# ---------------------------------------------------------------------------

class ScannerManagerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self._base_title = f"{APP_NAME} v{APP_VERSION}"
        self.root.title(self._base_title)
        self.root.geometry("1280x820")
        self.root.minsize(900, 600)
        self._build_menubar()

        self.hpd = HpdFile()
        self.config = HpdConfig()
        self.config_loaded = False
        self.zip_lookup = ZipCountyLookup(
            Path(__file__).resolve().parent,
            bundled_dir=bundled_resources_dir(),
        )

        self._selected_entry: Optional[FreqEntry] = None
        self._selected_group: Optional[GroupNode] = None
        self._selected_system: Optional[SystemNode] = None
        self._tree_id_map: Dict[str, object] = {}
        self._show_scannable_only = tk.BooleanVar(value=False)
        self._button_police = tk.BooleanVar(value=True)
        self._button_fire = tk.BooleanVar(value=True)
        self._button_ems = tk.BooleanVar(value=True)
        self._button_dot = tk.BooleanVar(value=True)
        self._button_multi = tk.BooleanVar(value=True)
        self._include_others = tk.BooleanVar(value=True)
        self._exclude_avoided = tk.BooleanVar(value=False)
        self._sd_space_var = tk.StringVar(value="")
        self._last_reconcile_audit: Optional[Path] = None
        self._state_id_list: List[int] = []

        self._location_filter_enabled = tk.BooleanVar(value=False)
        self._zip_var = tk.StringVar()
        self._county_var = tk.StringVar(value="(Auto from ZIP)")
        self._county_choices: List[Tuple[int, str]] = []
        self._active_zip: Optional[str] = None
        self._active_county_id: Optional[int] = None
        self._active_coords: Optional[Tuple[float, float]] = None
        self._coverage_tolerance_var = tk.IntVar(value=0)
        self._updater_path_var = tk.StringVar()
        self._merge_report: Optional[Dict[str, int]] = None
        self._firmware_zip_table = FirmwareZipTable()
        self._firmware_zip_loaded = False
        self._firmware_city_table = FirmwareCityTable()
        self._firmware_city_loaded = False
        # Resolve the writable state dir. When running from a PyInstaller
        # frozen bundle, ``__file__`` is inside ``_MEIPASS`` (a temp dir)
        # and isn't writable across runs, so we fall back to the dir
        # containing the EXE itself. That keeps app_settings.json, the
        # metastore, and session snapshots next to the binary - which is
        # the convention most Windows users expect.
        if getattr(sys, "frozen", False):
            self._script_dir = Path(sys.executable).resolve().parent
        else:
            self._script_dir = Path(__file__).resolve().parent
        self._custom_locations = CustomLocationsStore(self._script_dir)
        self._app_settings_path = self._script_dir / "app_settings.json"
        self._app_settings = self._load_app_settings()
        self._city_index = ScannerCityIndex()
        self._city_index_state_id: Optional[int] = None
        self._city_var = tk.StringVar()

        # Metastore (event-sourced change log). Global sidecar is always on;
        # per-HPD sidecars attach on load via _attach_meta_for_hpd().
        self._global_meta = GlobalMetaStore(
            self._script_dir / GlobalMetaStore.DEFAULT_FILENAME
        )
        self._meta: Optional[MetaStore] = None
        # Paths that have already received a session snapshot this run.
        self._session_snapshot_paths: Set[str] = set()
        self._session_snapshot_enabled = tk.BooleanVar(
            value=bool(self._app_settings.get("session_snapshot_enabled", True))
        )

        # Legacy `max_backups` setting is no longer consulted; leave the
        # key in app_settings.json for forward-compat but don't surface it.

        self._build_gui()
        saved_path = self._app_settings.get("sd_path", "")
        if saved_path and os.path.isdir(saved_path):
            self._set_status(f"Ready. Last SD card path: {saved_path}. Click Load.")
        else:
            self._set_status("Ready. Browse to your SD card's BCDx36HP folder to begin.")
        self._refresh_sd_space()
        # Show the first-run alpha notice once. Deferred via after()
        # so the main window is on screen before the modal opens.
        if not self._app_settings.get("first_run_seen"):
            self.root.after(250, self._show_first_run_notice)

    # ---- GUI Construction -------------------------------------------------

    def _build_menubar(self) -> None:
        """Top-level Help menu. We only add what's truly universally
        useful here; per-feature commands stay on the toolbars.
        """
        menubar = tk.Menu(self.root)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(
            label="Open Wiki", command=self._on_help_wiki,
        )
        help_menu.add_command(
            label="Report an Issue...", command=self._on_help_report_issue,
        )
        help_menu.add_separator()
        help_menu.add_command(
            label="Donate / Support...", command=self._on_help_donate,
        )
        help_menu.add_separator()
        help_menu.add_command(
            label=f"About {APP_NAME}...", command=self._on_help_about,
        )
        menubar.add_cascade(label="Help", menu=help_menu)

        self.root.configure(menu=menubar)

    def _build_gui(self):
        style = ttk.Style()
        style.configure("Treeview", rowheight=22)

        self._build_toolbar()
        self._build_main_area()
        self._build_status_bar()

    def _build_toolbar(self):
        row1 = ttk.Frame(self.root, padding=(5, 5, 5, 2))
        row1.pack(fill=tk.X, side=tk.TOP)
        ttk.Label(row1, text="SD Card Folder:").pack(side=tk.LEFT)
        self._path_var = tk.StringVar(value=self._app_settings.get("sd_path", ""))
        ttk.Entry(row1, textvariable=self._path_var, width=50).pack(side=tk.LEFT, padx=(5, 2))
        ttk.Button(row1, text="Browse", command=self._on_browse).pack(side=tk.LEFT, padx=2)
        ttk.Button(row1, text="Load", command=self._on_load).pack(side=tk.LEFT, padx=2)
        ttk.Separator(row1, orient=tk.VERTICAL).pack(side=tk.LEFT, padx=8, fill=tk.Y)
        ttk.Label(row1, text="State:").pack(side=tk.LEFT)
        self._state_var = tk.StringVar()
        self._state_combo = ttk.Combobox(
            row1, textvariable=self._state_var, state="readonly", width=22,
        )
        self._state_combo.pack(side=tk.LEFT, padx=(5, 2))
        self._state_combo.bind("<<ComboboxSelected>>", self._on_state_selected)
        ttk.Separator(row1, orient=tk.VERTICAL).pack(side=tk.LEFT, padx=8, fill=tk.Y)
        ttk.Button(row1, text="Save", command=self._on_save).pack(side=tk.LEFT, padx=2)
        ttk.Button(
            row1, text="Run Update Pipeline",
            command=self._on_run_update_pipeline,
        ).pack(side=tk.LEFT, padx=2)
        ttk.Button(
            row1, text="Uniden Tools...",
            command=self._on_open_uniden_tools,
        ).pack(side=tk.LEFT, padx=2)
        ttk.Separator(row1, orient=tk.VERTICAL).pack(side=tk.LEFT, padx=8, fill=tk.Y)
        ttk.Button(
            row1, text="Workspace...",
            command=self._on_manage_workspaces,
        ).pack(side=tk.LEFT, padx=2)
        ttk.Button(
            row1, text="Sync from SD",
            command=self._on_sync_from_sd,
        ).pack(side=tk.LEFT, padx=2)
        ttk.Button(
            row1, text="Sync to SD",
            command=self._on_sync_to_sd,
        ).pack(side=tk.LEFT, padx=2)
        ttk.Separator(row1, orient=tk.VERTICAL).pack(side=tk.LEFT, padx=8, fill=tk.Y)
        ttk.Button(
            row1, text="RR API...",
            command=self._on_open_rr_settings,
        ).pack(side=tk.LEFT, padx=2)
        ttk.Button(
            row1, text="RR Pull...",
            command=self._on_open_rr_pull,
        ).pack(side=tk.LEFT, padx=2)

        row2 = ttk.Frame(self.root, padding=(5, 2, 5, 2))
        row2.pack(fill=tk.X, side=tk.TOP)
        ttk.Label(row2, text="ZIP:").pack(side=tk.LEFT)
        ttk.Entry(row2, textvariable=self._zip_var, width=8).pack(side=tk.LEFT, padx=(4, 2))
        ttk.Button(row2, text="Lookup", command=self._on_zip_lookup).pack(side=tk.LEFT, padx=2)
        ttk.Separator(row2, orient=tk.VERTICAL).pack(side=tk.LEFT, padx=8, fill=tk.Y)
        ttk.Label(row2, text="City:").pack(side=tk.LEFT)
        ttk.Entry(row2, textvariable=self._city_var, width=14).pack(side=tk.LEFT, padx=(4, 2))
        ttk.Button(row2, text="City Lookup", command=self._on_city_lookup).pack(side=tk.LEFT, padx=2)
        ttk.Button(row2, text="Cities...", command=self._on_manage_cities).pack(side=tk.LEFT, padx=2)
        ttk.Separator(row2, orient=tk.VERTICAL).pack(side=tk.LEFT, padx=8, fill=tk.Y)
        ttk.Label(row2, text="County:").pack(side=tk.LEFT)
        self._county_combo = ttk.Combobox(
            row2, textvariable=self._county_var, state="readonly", width=24
        )
        self._county_combo["values"] = ["(Auto from ZIP)"]
        self._county_combo.current(0)
        self._county_combo.bind("<<ComboboxSelected>>", self._on_county_override_changed)
        self._county_combo.pack(side=tk.LEFT, padx=(4, 2))
        ttk.Checkbutton(
            row2, text="Apply Location Filter",
            variable=self._location_filter_enabled,
            command=self._on_filter_changed,
        ).pack(side=tk.LEFT, padx=4)
        ttk.Label(row2, text="Extra mi:").pack(side=tk.LEFT, padx=(8, 0))
        ttk.Spinbox(
            row2, from_=0, to=200, increment=5, width=5,
            textvariable=self._coverage_tolerance_var,
            command=self._on_filter_changed,
        ).pack(side=tk.LEFT, padx=(2, 2))

        row3 = ttk.Frame(self.root, padding=(5, 2, 5, 4))
        row3.pack(fill=tk.X, side=tk.TOP)
        ttk.Label(row3, text="Scanner buttons:").pack(side=tk.LEFT)
        for label, var in (
            ("Police (2)", self._button_police),
            ("Fire (3)", self._button_fire),
            ("EMS (4)", self._button_ems),
            ("DOT (14)", self._button_dot),
            ("Multi (1)", self._button_multi),
        ):
            ttk.Checkbutton(
                row3, text=label, variable=var, command=self._on_filter_changed,
            ).pack(side=tk.LEFT, padx=3)
        ttk.Separator(row3, orient=tk.VERTICAL).pack(side=tk.LEFT, padx=8, fill=tk.Y)
        ttk.Checkbutton(
            row3, text="Include other types",
            variable=self._include_others,
            command=self._on_filter_changed,
        ).pack(side=tk.LEFT, padx=3)
        ttk.Checkbutton(
            row3, text="Exclude avoided",
            variable=self._exclude_avoided,
            command=self._on_filter_changed,
        ).pack(side=tk.LEFT, padx=3)
        ttk.Button(
            row3, text="Export Effective Scan Set...",
            command=self._on_export_scan_set,
        ).pack(side=tk.RIGHT, padx=5)
        ttk.Button(
            row3, text="Discovery...",
            command=self._on_view_discovery,
        ).pack(side=tk.RIGHT, padx=2)
        ttk.Button(
            row3, text="Alerts...",
            command=self._on_view_alerts,
        ).pack(side=tk.RIGHT, padx=2)
        ttk.Button(
            row3, text="Heatmap...",
            command=self._on_coverage_heatmap,
        ).pack(side=tk.RIGHT, padx=2)
        ttk.Button(
            row3, text="Map...",
            command=self._on_coverage_map,
        ).pack(side=tk.RIGHT, padx=2)
        ttk.Button(
            row3, text="Bulk Remap...",
            command=self._on_bulk_remap,
        ).pack(side=tk.RIGHT, padx=2)
        ttk.Button(
            row3, text="Audit Modes",
            command=self._on_mode_band_audit,
        ).pack(side=tk.RIGHT, padx=2)
        ttk.Button(
            row3, text="Changes...",
            command=self._on_show_changes,
        ).pack(side=tk.RIGHT, padx=2)
        ttk.Button(
            row3, text="Restore Session...",
            command=self._on_restore_session_snapshot,
        ).pack(side=tk.RIGHT, padx=2)
        ttk.Button(
            row3, text="Audit",
            command=self._on_show_last_audit,
        ).pack(side=tk.RIGHT, padx=2)

    def _build_main_area(self):
        paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        left = ttk.Frame(paned)
        paned.add(left, weight=3)

        right = ttk.Frame(paned)
        paned.add(right, weight=2)

        self._build_tree(left)
        self._build_right_panel(right)

    def _build_tree(self, parent: ttk.Frame):
        cols = ("freq_tgid", "mode", "service")
        self.tree = ttk.Treeview(
            parent, columns=cols, selectmode="browse", show="tree headings",
        )
        self.tree.heading("#0", text="Name", anchor=tk.W)
        self.tree.heading("freq_tgid", text="Freq / TGID", anchor=tk.W)
        self.tree.heading("mode", text="Mode", anchor=tk.W)
        self.tree.heading("service", text="Service Type", anchor=tk.W)

        self.tree.column("#0", width=350, minwidth=200)
        self.tree.column("freq_tgid", width=130, minwidth=80)
        self.tree.column("mode", width=60, minwidth=50)
        self.tree.column("service", width=160, minwidth=100)

        self.tree.tag_configure("scannable", foreground="#006400")
        self.tree.tag_configure("nonscannable", foreground="#888888")
        self.tree.tag_configure("system", font=("TkDefaultFont", 10, "bold"))
        self.tree.tag_configure("group", font=("TkDefaultFont", 9, "bold"))
        self.tree.tag_configure(
            "group_in_range", font=("TkDefaultFont", 9, "bold"), foreground="#006400"
        )
        self.tree.tag_configure(
            "group_nearby", font=("TkDefaultFont", 9, "bold"), foreground="#b8860b"
        )
        self.tree.tag_configure(
            "group_out_range", font=("TkDefaultFont", 9, "bold"), foreground="#b22222"
        )
        self.tree.tag_configure(
            "group_no_geo", font=("TkDefaultFont", 9, "bold"), foreground="#606060"
        )

        vsb = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        hsb = ttk.Scrollbar(parent, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(xscrollcommand=hsb.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        parent.grid_rowconfigure(0, weight=1)
        parent.grid_columnconfigure(0, weight=1)

        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self.tree.bind("<Button-3>", self._on_tree_right_click)

    def _build_right_panel(self, parent: ttk.Frame):
        parent.grid_rowconfigure(0, weight=1)
        parent.grid_rowconfigure(1, weight=1)
        parent.grid_columnconfigure(0, weight=1)

        self._build_details_panel(parent)
        self._build_add_panel(parent)

    def _build_details_panel(self, parent: ttk.Frame):
        frame = ttk.LabelFrame(parent, text="Selected Entry Details", padding=10)
        frame.grid(row=0, column=0, sticky="nsew", pady=(0, 5))

        self._detail_labels: Dict[str, ttk.Label] = {}
        detail_fields = [
            ("Type:", "type"),
            ("Name:", "name"),
            ("Frequency / TGID:", "freq"),
            ("Mode:", "mode"),
            ("Tone / NAC:", "tone"),
            ("Service Type:", "service"),
            ("Avoid:", "avoid"),
            ("Group:", "group"),
        ]
        for i, (label_text, key) in enumerate(detail_fields):
            ttk.Label(frame, text=label_text, font=("TkDefaultFont", 9, "bold")).grid(
                row=i, column=0, sticky=tk.W, pady=2,
            )
            lbl = ttk.Label(frame, text="—")
            lbl.grid(row=i, column=1, sticky=tk.W, padx=(10, 0), pady=2)
            self._detail_labels[key] = lbl

        sep_row = len(detail_fields)
        ttk.Separator(frame, orient=tk.HORIZONTAL).grid(
            row=sep_row, column=0, columnspan=3, sticky="ew", pady=8,
        )

        edit_row = sep_row + 1
        ttk.Label(frame, text="Change Service Type:").grid(
            row=edit_row, column=0, sticky=tk.W, pady=2,
        )
        self._edit_stype_var = tk.StringVar()
        self._edit_stype_combo = ttk.Combobox(
            frame, textvariable=self._edit_stype_var, state="readonly", width=22,
            values=[s[1] for s in SERVICE_CHOICES],
        )
        self._edit_stype_combo.grid(row=edit_row, column=1, sticky=tk.W, padx=(10, 0))

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=edit_row + 1, column=0, columnspan=2, pady=8)
        ttk.Button(btn_frame, text="Update Service Type", command=self._on_update_service).pack(
            side=tk.LEFT, padx=3,
        )
        ttk.Button(btn_frame, text="Toggle Avoid", command=self._on_toggle_avoid).pack(
            side=tk.LEFT, padx=3,
        )
        ttk.Button(btn_frame, text="Edit...", command=self._on_edit_selected).pack(
            side=tk.LEFT, padx=3,
        )
        ttk.Button(btn_frame, text="Delete", command=self._on_delete_selected).pack(
            side=tk.LEFT, padx=3,
        )

        ttk.Separator(frame, orient=tk.HORIZONTAL).grid(
            row=edit_row + 2, column=0, columnspan=2, sticky="ew", pady=(6, 6)
        )
        ttk.Label(
            frame,
            text=SERVICE_TYPE_HELP_TEXT,
            foreground="#555555",
            justify=tk.LEFT,
            wraplength=360,
        ).grid(row=edit_row + 3, column=0, columnspan=2, sticky=tk.W)

    def _build_add_panel(self, parent: ttk.Frame):
        frame = ttk.LabelFrame(parent, text="Add New Entry (from RadioReference)", padding=10)
        frame.grid(row=1, column=0, sticky="nsew", pady=(5, 0))

        self._add_type_var = tk.StringVar(value="Conventional")
        type_frame = ttk.Frame(frame)
        type_frame.grid(row=0, column=0, columnspan=2, sticky=tk.W, pady=(0, 5))
        ttk.Radiobutton(
            type_frame, text="Conventional Frequency", variable=self._add_type_var,
            value="Conventional", command=self._on_add_type_changed,
        ).pack(side=tk.LEFT, padx=(0, 15))
        ttk.Radiobutton(
            type_frame, text="Trunked Talkgroup", variable=self._add_type_var,
            value="Trunked", command=self._on_add_type_changed,
        ).pack(side=tk.LEFT)

        url_row = 1
        ttk.Label(frame, text="RadioReference URL:").grid(row=url_row, column=0, sticky=tk.W, pady=2)
        url_frame = ttk.Frame(frame)
        url_frame.grid(row=url_row, column=1, sticky=tk.W, padx=(10, 0), pady=2)
        self._add_rr_url_var = tk.StringVar()
        ttk.Entry(url_frame, textvariable=self._add_rr_url_var, width=28).pack(side=tk.LEFT)
        ttk.Button(url_frame, text="Fetch", command=self._on_fetch_rr_url).pack(side=tk.LEFT, padx=(4, 0))

        row = url_row + 1
        ttk.Label(frame, text="Name / Description:").grid(row=row, column=0, sticky=tk.W, pady=2)
        self._add_name_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self._add_name_var, width=30).grid(
            row=row, column=1, sticky=tk.W, padx=(10, 0), pady=2,
        )

        row += 1
        self._add_freq_label = ttk.Label(frame, text="Frequency (MHz):")
        self._add_freq_label.grid(row=row, column=0, sticky=tk.W, pady=2)
        self._add_freq_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self._add_freq_var, width=20).grid(
            row=row, column=1, sticky=tk.W, padx=(10, 0), pady=2,
        )

        row += 1
        ttk.Label(frame, text="Mode:").grid(row=row, column=0, sticky=tk.W, pady=2)
        self._add_mode_var = tk.StringVar(value="NFM")
        self._add_mode_combo = ttk.Combobox(
            frame, textvariable=self._add_mode_var, state="readonly", width=10,
            values=MODE_CHOICES_CONV,
        )
        self._add_mode_combo.grid(row=row, column=1, sticky=tk.W, padx=(10, 0), pady=2)

        row += 1
        self._add_tone_label = ttk.Label(frame, text="Tone (e.g. TONE=C156.7):")
        self._add_tone_label.grid(row=row, column=0, sticky=tk.W, pady=2)
        self._add_tone_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self._add_tone_var, width=20).grid(
            row=row, column=1, sticky=tk.W, padx=(10, 0), pady=2,
        )

        row += 1
        ttk.Label(frame, text="Service Type:").grid(row=row, column=0, sticky=tk.W, pady=2)
        self._add_stype_var = tk.StringVar()
        ttk.Combobox(
            frame, textvariable=self._add_stype_var, state="readonly", width=22,
            values=[s[1] for s in SERVICE_CHOICES],
        ).grid(row=row, column=1, sticky=tk.W, padx=(10, 0), pady=2)

        row += 1
        btn_row = ttk.Frame(frame)
        btn_row.grid(row=row, column=0, columnspan=2, pady=10)
        ttk.Button(btn_row, text="Add to Selected Group", command=self._on_add_entry).pack(
            side=tk.LEFT, padx=3
        )
        ttk.Button(btn_row, text="Create New Group...", command=self._on_create_group).pack(
            side=tk.LEFT, padx=3
        )

        row += 1
        self._add_hint = ttk.Label(
            frame,
            text=(
                "Tips: pick a group to add single entries, or a county/system to create "
                "a new sub-group. Paste a RadioReference URL to auto-fill or bulk-import."
            ),
            foreground="#666666",
            wraplength=360,
            justify=tk.LEFT,
        )
        self._add_hint.grid(row=row, column=0, columnspan=2, sticky=tk.W)

    def _build_status_bar(self):
        status_frame = ttk.Frame(self.root)
        status_frame.pack(fill=tk.X, side=tk.BOTTOM)
        self._status_var = tk.StringVar()
        ttk.Label(
            status_frame, textvariable=self._status_var, relief=tk.SUNKEN,
            anchor=tk.W, padding=(5, 2),
        ).pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._card_state_var = tk.StringVar(value="")
        self._card_state_label = ttk.Label(
            status_frame, textvariable=self._card_state_var, relief=tk.SUNKEN,
            anchor=tk.E, padding=(5, 2), foreground="#666666",
        )
        self._card_state_label.pack(side=tk.LEFT)
        # Pipeline-health pill: click to open the DataPipelineDialog.
        self._pipeline_health_var = tk.StringVar(value="Pipeline: ?")
        self._pipeline_health_label = tk.Label(
            status_frame, textvariable=self._pipeline_health_var,
            relief=tk.SUNKEN, anchor=tk.E, padx=6, pady=1,
            foreground="#fff", background="#888", cursor="hand2",
        )
        self._pipeline_health_label.pack(side=tk.LEFT, padx=(0, 2))
        self._pipeline_health_label.bind(
            "<Button-1>", lambda _e: self._on_open_data_pipeline()
        )
        ttk.Label(
            status_frame, textvariable=self._sd_space_var, relief=tk.SUNKEN,
            anchor=tk.E, padding=(5, 2), foreground="#333333",
        ).pack(side=tk.LEFT)

    # ---- Event Handlers ---------------------------------------------------

    def _load_app_settings(self) -> Dict[str, Any]:
        if not self._app_settings_path.exists():
            return {}
        try:
            with self._app_settings_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        return {}

    def _save_app_settings(self):
        try:
            with self._app_settings_path.open("w", encoding="utf-8") as f:
                json.dump(self._app_settings, f, indent=2)
        except Exception:
            pass

    def _remember_sd_path(self, folder: str):
        if folder and os.path.isdir(folder):
            self._app_settings["sd_path"] = folder
            self._save_app_settings()
            self._refresh_sd_space()

    # ------------------------------------------------------------------
    # Virtual SD card / workspace lifecycle
    # ------------------------------------------------------------------

    def _active_profile(self) -> Optional[Dict[str, Any]]:
        pid = getattr(self._global_meta, "active_profile_id", None)
        if not pid:
            return None
        return self._global_meta.get_profile(pid)

    def _profile_baseline(
        self, profile: Dict[str, Any]
    ) -> Dict[str, "sdcard.FileState"]:
        return sdcard.file_states_from_json(profile.get("file_state") or {})

    def _update_profile_baseline(
        self, profile: Dict[str, Any], workspace_root: str
    ) -> None:
        states = sdcard.capture_file_state(workspace_root)
        profile["file_state"] = sdcard.file_states_to_json(states)
        profile["last_sync_at"] = datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )

    def _detect_card_identity(self) -> "sdcard.CardIdentity":
        folder = (self._path_var.get() or "").strip()
        return sdcard.probe_card_identity(folder)

    def _on_manage_workspaces(self):
        """Open the workspace picker: list profiles + clone/open/remove."""
        dlg = WorkspaceManagerDialog(self.root, self)
        if dlg.result is None:
            return
        action = dlg.result.get("action")
        if action == "open":
            self._open_profile(dlg.result["profile_id"])
        elif action == "clone":
            self._clone_current_card_as_new_profile(
                name=dlg.result["name"],
                workspace_dir=dlg.result["workspace_dir"],
            )
        elif action == "remove":
            self._global_meta.remove_profile(dlg.result["profile_id"])
            self._global_meta.save()
            self._set_status("Removed workspace profile.")

    def _clone_current_card_as_new_profile(
        self,
        *,
        name: str,
        workspace_dir: str,
    ) -> None:
        card_root = (self._path_var.get() or "").strip()
        if not card_root or not os.path.isdir(card_root):
            messagebox.showerror(
                "Clone",
                "Point the SD card folder at a real, connected card before cloning.",
            )
            return
        workspace_dir = os.path.abspath(workspace_dir)
        os.makedirs(workspace_dir, exist_ok=True)
        self._set_status(f"Cloning SD card to {workspace_dir}...")
        self.root.update_idletasks()
        report = sdcard.clone_card_to_workspace(card_root, workspace_dir)
        if report.errors:
            messagebox.showerror(
                "Clone failed",
                "Some files could not be copied:\n\n"
                + "\n".join(f"{rel}: {msg}" for rel, msg in report.errors[:12]),
            )
            return
        ident = sdcard.probe_card_identity(card_root)
        pid = uuid.uuid4().hex
        profile = {
            "profile_id": pid,
            "name": name,
            "workspace_dir": workspace_dir,
            "card_volume_serial": ident.volume_serial,
            "content_fingerprint": ident.content_fingerprint,
            "target_model": ident.target_model,
            "last_synced_card_path": card_root,
        }
        self._update_profile_baseline(profile, workspace_dir)
        self._global_meta.upsert_profile(profile)
        self._global_meta.set_active_profile(pid)
        self._global_meta.save()
        self._set_status(
            f"Cloned {len(report.copied)} file(s) into workspace '{name}'."
        )
        self._open_profile(pid)

    def _open_profile(self, profile_id: str) -> None:
        profile = self._global_meta.get_profile(profile_id)
        if profile is None:
            messagebox.showerror("Workspace", "Profile not found.")
            return
        workspace_dir = profile.get("workspace_dir") or ""
        if not workspace_dir or not os.path.isdir(workspace_dir):
            messagebox.showerror(
                "Workspace",
                "The workspace folder for this profile is missing:\n"
                f"{workspace_dir}",
            )
            return
        self._global_meta.set_active_profile(profile_id)
        self._global_meta.save()
        self._path_var.set(workspace_dir)
        self._remember_sd_path(workspace_dir)
        self._try_load_config(workspace_dir)
        self._set_status(
            f"Opened workspace '{profile.get('name') or profile_id}'. "
            f"Pick a state + Load to browse."
        )
        self._refresh_sd_space()

    # --- Sync -----------------------------------------------------------

    def _on_sync_from_sd(self) -> None:
        profile = self._active_profile()
        if profile is None:
            messagebox.showinfo(
                "Sync",
                "Open a workspace first (Workspace... > Clone or Open).",
            )
            return
        card_root = self._prompt_card_for_sync(profile)
        if not card_root:
            return
        baseline = self._profile_baseline(profile)
        self._set_status("Pulling changes from SD card...")
        self.root.update_idletasks()
        report, diffs = sdcard.sync_pull(
            card_root=card_root,
            workspace_root=profile["workspace_dir"],
            baseline=baseline,
        )
        self._handle_sync_result(
            profile, report, diffs,
            card_root=card_root,
            direction="pull",
        )

    def _on_sync_to_sd(self) -> None:
        profile = self._active_profile()
        if profile is None:
            messagebox.showinfo(
                "Sync",
                "Open a workspace first (Workspace... > Clone or Open).",
            )
            return
        card_root = self._prompt_card_for_sync(profile)
        if not card_root:
            return
        baseline = self._profile_baseline(profile)
        self._set_status("Pushing workspace HPD files to SD card...")
        self.root.update_idletasks()
        report, diffs = sdcard.sync_push(
            card_root=card_root,
            workspace_root=profile["workspace_dir"],
            baseline=baseline,
        )
        self._handle_sync_result(
            profile, report, diffs,
            card_root=card_root,
            direction="push",
        )

    def _prompt_card_for_sync(
        self, profile: Dict[str, Any]
    ) -> Optional[str]:
        """Ask the user to point at an SD card root for syncing.

        Defaults to the last-seen card path; if that's stale we fall back
        to the app's top-level SD path so the user rarely has to type.
        """
        hint = (
            profile.get("last_synced_card_path")
            or (self._path_var.get() or "").strip()
        )
        if hint and os.path.isdir(hint) and hint != profile.get("workspace_dir"):
            # One-click path: if the hint is a card (not the workspace we
            # just opened) and it exists, use it directly.
            return hint
        folder = filedialog.askdirectory(
            title="Select the SD card root for sync",
            initialdir=hint if hint and os.path.isdir(hint) else None,
        )
        return folder or None

    def _handle_sync_result(
        self,
        profile: Dict[str, Any],
        report: "sdcard.SyncReport",
        diffs: List["sdcard.FileDiff"],
        *,
        card_root: str,
        direction: str,
    ) -> None:
        if report.errors:
            messagebox.showerror(
                "Sync errors",
                "\n".join(f"{rel}: {msg}" for rel, msg in report.errors[:12]),
            )
        # Log external HPD changes into the active MetaStore, if we have one.
        for rel in report.external_changes:
            if self._meta is not None:
                self._meta.record(
                    op=OP_EXTERNAL_CHANGE,
                    target_id=f"file:{rel}",
                    payload={"direction": direction, "relpath": rel},
                    target_name=rel,
                    summary=f"Card-side change pulled into workspace ({rel})",
                    source="sync_pull",
                )
                self._meta.flush()
        if report.conflicts:
            dlg = SyncConflictDialog(
                self.root, report=report, diffs=diffs, direction=direction
            )
            # Persist user's decisions: "take_card", "take_workspace", "skip".
            decisions = (dlg.result or {}).get("decisions") or {}
            for rel, decision in decisions.items():
                if decision == "take_card":
                    try:
                        src = Path(card_root) / rel
                        dst = Path(profile["workspace_dir"]) / rel
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src, dst)
                    except Exception as exc:
                        messagebox.showerror(
                            "Sync", f"Could not take card copy of {rel}: {exc}"
                        )
                elif decision == "take_workspace":
                    try:
                        src = Path(profile["workspace_dir"]) / rel
                        dst = Path(card_root) / rel
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src, dst)
                    except Exception as exc:
                        messagebox.showerror(
                            "Sync", f"Could not push workspace copy of {rel}: {exc}"
                        )
        # Update baseline to reflect the new state after sync.
        self._update_profile_baseline(profile, profile["workspace_dir"])
        profile["last_synced_card_path"] = card_root
        self._global_meta.upsert_profile(profile)
        self._global_meta.save()
        # If we pushed, stamp all uncommitted events as committed.
        if direction == "push" and self._meta is not None:
            self._meta.mark_events_committed()
            self._meta.flush()
        summary = (
            f"Sync {direction}: {len(report.copied)} copied, "
            f"{len(report.skipped_same)} unchanged, "
            f"{len(report.conflicts)} conflict(s), "
            f"{len(report.external_changes)} external change(s)."
        )
        self._set_status(summary)

    def _on_browse(self):
        initial = self._path_var.get().strip() or self._app_settings.get("sd_path", "")
        folder = filedialog.askdirectory(
            title="Select BCDx36HP folder on SD card",
            initialdir=initial if initial and os.path.isdir(initial) else None,
        )
        if folder:
            self._path_var.set(folder)
            self._remember_sd_path(folder)
            self._try_load_config(folder)

    def _on_load(self):
        folder = self._path_var.get().strip()
        if not folder or not os.path.isdir(folder):
            messagebox.showerror("Error", "Please select a valid BCDx36HP folder.")
            return

        self._remember_sd_path(folder)
        self._try_load_config(folder)

        if not self.config_loaded:
            messagebox.showerror("Error", "Could not find hpdb.cfg in HPDB subfolder.")
            return

        sid = self._get_selected_state_id()
        if sid is None:
            messagebox.showinfo("Info", "Please select a state from the dropdown first.")
            return

        self._load_state_hpd(sid)

    def _try_load_config(self, folder: str):
        if self.config_loaded:
            return

        cfg = os.path.join(folder, "HPDB", "hpdb.cfg")
        if not os.path.exists(cfg):
            cfg2 = os.path.join(folder, "hpdb.cfg")
            if os.path.exists(cfg2):
                cfg = cfg2
            else:
                return

        try:
            self.config.load(cfg)
            self.config_loaded = True
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load config:\n{e}")
            return

        state_items = []
        self._state_id_list = []
        for sid in sorted(self.config.state_files.keys()):
            name = self.config.get_state_name(sid)
            state_items.append(name)
            self._state_id_list.append(sid)

        self._state_combo["values"] = state_items

        florida_idx = None
        for i, sid in enumerate(self._state_id_list):
            if sid == 12:
                florida_idx = i
                break

        if florida_idx is not None:
            self._state_combo.current(florida_idx)
        elif state_items:
            self._state_combo.current(0)

        self._refresh_county_options()

    def _on_state_selected(self, event=None):
        self._refresh_county_options()
        if self._location_filter_enabled.get() and self.hpd.systems:
            self._populate_tree()

    def _get_selected_state_id(self) -> Optional[int]:
        idx = self._state_combo.current()
        if idx < 0 or idx >= len(self._state_id_list):
            return None
        return self._state_id_list[idx]

    def _on_tree_select(self, event=None):
        sel = self.tree.selection()
        if not sel:
            return

        item_id = sel[0]
        obj = self._tree_id_map.get(item_id)

        if isinstance(obj, FreqEntry):
            self._selected_entry = obj
            self._selected_system = None
            self._show_entry_details(obj)
            parent_id = self.tree.parent(item_id)
            parent_obj = self._tree_id_map.get(parent_id)
            if isinstance(parent_obj, GroupNode):
                self._selected_group = parent_obj
        elif isinstance(obj, GroupNode):
            self._selected_group = obj
            self._selected_entry = None
            self._selected_system = None
            self._show_group_details(obj)
        elif isinstance(obj, SystemNode):
            self._selected_group = None
            self._selected_entry = None
            self._selected_system = obj
            self._show_system_details(obj)

    def _on_tree_right_click(self, event):
        item_id = self.tree.identify_row(event.y)
        if not item_id:
            return
        self.tree.selection_set(item_id)
        self._on_tree_select()
        obj = self._tree_id_map.get(item_id)
        menu = tk.Menu(self.root, tearoff=0)
        if isinstance(obj, FreqEntry):
            menu.add_command(label="Edit entry...", command=self._on_edit_selected)
            menu.add_command(label="Toggle Avoid", command=self._on_toggle_avoid)
            menu.add_separator()
            menu.add_command(label="Delete entry", command=self._on_delete_selected)
        elif isinstance(obj, GroupNode):
            menu.add_command(label="Edit group...", command=self._on_edit_selected)
            menu.add_separator()
            menu.add_command(label="Bulk: update service type", command=self._on_update_service)
            menu.add_command(label="Bulk: toggle avoid", command=self._on_toggle_avoid)
            menu.add_separator()
            link_info = self._group_link_info(obj)
            if link_info:
                menu.add_command(
                    label=f"RadioReference: {link_info['rr_url']}",
                    state="disabled",
                )
                menu.add_command(
                    label="Refresh from RadioReference",
                    command=self._on_refresh_group_from_rr,
                )
                menu.add_command(
                    label="Diff against RadioReference...",
                    command=self._on_diff_group_against_rr,
                )
                menu.add_command(
                    label="Unlink from RadioReference",
                    command=self._on_unlink_group_from_rr,
                )
            else:
                menu.add_command(
                    label="Link to RadioReference...",
                    command=self._on_link_group_to_rr,
                )
            menu.add_separator()
            menu.add_command(label="Delete group", command=self._on_delete_selected)
        elif isinstance(obj, SystemNode):
            menu.add_command(label="Edit system...", command=self._on_edit_selected)
            menu.add_separator()
            menu.add_command(label="Bulk: update service type", command=self._on_update_service)
            menu.add_command(label="Bulk: toggle avoid", command=self._on_toggle_avoid)
            menu.add_separator()
            menu.add_command(label="Delete system...", command=self._on_delete_selected)
        else:
            return
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _on_edit_selected(self):
        if self._selected_entry is not None:
            dlg = EntryEditDialog(self.root, self._selected_entry)
            if dlg.result is None:
                return
            self._do_edit_entry(
                self._selected_entry,
                name=dlg.result["name"] or None,
                identity_value=dlg.result["identity_value"],
                mode=dlg.result["mode"] or None,
                tone=dlg.result.get("tone"),
            )
            self._refresh_entry_in_tree(self._selected_entry)
            self._show_entry_details(self._selected_entry)
            self._set_status(f"Updated entry: {self._selected_entry.name}")
            return
        if self._selected_group is not None:
            group = self._selected_group
            dlg = GroupEditDialog(self.root, group)
            if dlg.result is None:
                return
            self._do_edit_group(
                group,
                name=dlg.result["name"] or None,
                lat=dlg.result["lat"],
                lon=dlg.result["lon"],
                range_miles=dlg.result["range_miles"],
            )
            updated_name = group.name
            self._populate_tree()
            self._set_status(f"Updated group: {updated_name}")
            return
        if self._selected_system is not None:
            system = self._selected_system
            dlg = SystemEditDialog(self.root, system)
            if dlg.result is None:
                return
            self._do_edit_system(system, name=dlg.result["name"])
            updated_name = system.name
            self._populate_tree()
            self._set_status(f"Updated system: {updated_name}")
            return
        messagebox.showinfo("Edit", "Select an entry, group, or system to edit.")

    def _on_delete_selected(self):
        if self._selected_entry is not None:
            entry = self._selected_entry
            name = entry.name
            if not messagebox.askyesno(
                "Delete Entry",
                f"Delete entry '{name}' ({entry.entry_type})?\n"
                "This change is tracked in Changes... and can be reverted.",
            ):
                return
            self._do_delete_entry(entry)
            self._selected_entry = None
            self._populate_tree()
            self._set_status(f"Deleted entry: {name}")
            return
        if self._selected_group is not None:
            group = self._selected_group
            count = len(group.entries)
            name = group.name
            if not messagebox.askyesno(
                "Delete Group",
                f"Delete group '{name}' and all {count} entries under it?\n"
                "This change is tracked in Changes... and can be reverted.",
            ):
                return
            self._do_delete_group(group)
            self._selected_group = None
            self._populate_tree()
            self._set_status(f"Deleted group: {name}")
            return
        if self._selected_system is not None:
            system = self._selected_system
            name = system.name
            group_count = len(system.groups)
            entry_count = sum(len(g.entries) for g in system.groups)
            if not messagebox.askyesno(
                "Delete System",
                f"Delete system '{name}' and EVERYTHING beneath it?\n\n"
                f"\u2022 {group_count} group(s)\n"
                f"\u2022 {entry_count} entrie(s)\n"
                f"\u2022 all sites, area assignments, and rectangles\n\n"
                "This change is tracked in Changes... and can be reverted.",
            ):
                return
            self._do_delete_system(system)
            self._selected_system = None
            self._refresh_ui_after_mutation(
                status_msg=f"Deleted system: {name}"
            )
            return
        messagebox.showinfo("Delete", "Select an entry, group, or system to delete.")

    # ---- Group ↔ RadioReference linking (Phase C) -------------------------

    def _group_link_info(self, group: GroupNode) -> Optional[Dict[str, Any]]:
        if self._meta is None:
            return None
        key = self._group_key_for(group)
        return self._meta.group_link_for(key)

    @staticmethod
    def _rr_kind_from_url(url: str) -> str:
        u = (url or "").lower()
        if "/db/sid/" in u:
            return "trs"
        if "/db/aid/" in u:
            return "category"
        if "/db/browse/ctid/" in u or "/db/ctid/" in u:
            return "conventional_multi"
        if "/db/fcc/callsign/" in u:
            return "fcc_callsign"
        return "unknown"

    def _on_link_group_to_rr(self):
        group = self._selected_group
        if group is None:
            messagebox.showinfo("Link", "Select a group first.")
            return
        if self._meta is None:
            messagebox.showwarning(
                "MetaStore",
                "Group linking requires an HPD with an active MetaStore.",
            )
            return

        existing = self._group_link_info(group)
        initial = existing.get("rr_url") if existing else ""
        candidates = self._guess_rr_urls_for_group(group)
        url: Optional[str] = None
        if candidates and not initial:
            picker = RadioReferenceAutoGuessDialog(self, group, candidates)
            url = picker.result
            if url is None:
                return  # user cancelled
            if url == "":
                url = self._prompt_rr_url(group, initial or "")
        else:
            url = self._prompt_rr_url(group, initial or "")
        if not url:
            return
        url = url.strip()
        kind = self._rr_kind_from_url(url)
        group_key = self._group_key_for(group)
        self._meta.set_group_link(group_key, rr_url=url, rr_kind=kind)
        self._log_event(
            op=OP_LINK_RR,
            target_id=group_key,
            target_name=group.name,
            payload={"link": {"rr_url": url, "rr_kind": kind}},
            summary=f"Linked '{group.name}' to {url}",
        )
        self._set_status(f"Linked group '{group.name}' to {url}")
        if messagebox.askyesno(
            "Refresh now?",
            "Fetch from RadioReference now and open the reconciler?",
        ):
            self._refresh_group_from_rr(group, url)

    def _prompt_rr_url(self, group: GroupNode, initial: str) -> Optional[str]:
        from tkinter import simpledialog
        return simpledialog.askstring(
            "Link to RadioReference",
            f"RadioReference URL for group '{group.name}':\n"
            "(paste a /db/sid/, /db/aid/, /db/ctid/ or /db/fcc/callsign/ URL)",
            initialvalue=initial,
            parent=self.root,
        )

    def _guess_rr_urls_for_group(self, group: GroupNode) -> List[Dict[str, Any]]:
        """Produce ranked candidate RR URLs for a group.

        Sources (in order of confidence):
          1. ``source_url`` previously recorded for any entry in the group
          2. ``fcc_callsign`` on any entry in the group -> /db/fcc/callsign/<CS>
          3. Fuzzy licensee match on global index (via entry refs)
          4. Recent RR URLs whose fetched titles fuzzily match the group name
        """
        if self._meta is None:
            return []

        seen: Set[str] = set()
        candidates: List[Dict[str, Any]] = []

        def add(url: str, source: str, confidence: float, detail: str):
            if not url or url in seen:
                return
            seen.add(url)
            candidates.append(
                {
                    "url": url,
                    "source": source,
                    "confidence": confidence,
                    "detail": detail,
                }
            )

        callsigns: Set[str] = set()
        licensees: Set[str] = set()
        for entry in group.entries:
            eid = self._entry_id_for(entry)
            ref = self._meta.ref_for(eid) or {}
            for url in ref.get("source_urls") or []:
                add(url, "entry-source", 0.95, f"Imported from here ({entry.name})")
            if ref.get("fcc_callsign"):
                callsigns.add(ref["fcc_callsign"].upper())
            if ref.get("licensee"):
                licensees.add(ref["licensee"])

        for cs in callsigns:
            add(
                f"https://www.radioreference.com/db/fcc/callsign/{cs}",
                "callsign",
                0.9,
                f"Derived from FCC callsign {cs}",
            )

        gm = self._global_meta
        if gm is not None:
            for licensee in licensees:
                for key, score, ids in gm.fuzzy_licensee_candidates(licensee, min_score=0.8):
                    for eid in ids:
                        other_ref = self._meta.ref_for(eid) or {}
                        for url in other_ref.get("source_urls") or []:
                            add(
                                url,
                                "fuzzy-licensee",
                                0.7 * score,
                                f"Fuzzy licensee match ({int(score*100)}%) to {key}",
                            )
                        if other_ref.get("fcc_callsign"):
                            add(
                                f"https://www.radioreference.com/db/fcc/callsign/"
                                f"{other_ref['fcc_callsign']}",
                                "fuzzy-licensee",
                                0.65 * score,
                                f"Fuzzy match -> CS {other_ref['fcc_callsign']}",
                            )

            probe = group.name or ""
            if probe:
                probe_tokens = set(GlobalMetaStore._tokens(probe))
                for url in gm.recent_rr_urls[-50:]:
                    if not url or url in seen:
                        continue
                    url_tokens = set(GlobalMetaStore._tokens(url))
                    if not probe_tokens or not url_tokens:
                        continue
                    inter = len(probe_tokens & url_tokens)
                    if inter == 0:
                        continue
                    score = inter / len(probe_tokens | url_tokens)
                    if score >= 0.25:
                        add(
                            url, "recent-url", 0.4 + 0.3 * score,
                            f"Recent URL match (tok score {score:.2f})",
                        )

        candidates.sort(key=lambda c: c["confidence"], reverse=True)
        return candidates[:25]

    def _on_unlink_group_from_rr(self):
        group = self._selected_group
        if group is None or self._meta is None:
            return
        info = self._group_link_info(group)
        if not info:
            return
        if not messagebox.askyesno(
            "Unlink",
            f"Remove RadioReference link for '{group.name}'?",
        ):
            return
        group_key = self._group_key_for(group)
        removed = self._meta.clear_group_link(group_key)
        if removed is not None:
            self._log_event(
                op=OP_UNLINK_RR,
                target_id=group_key,
                target_name=group.name,
                payload={"link": removed},
                summary=f"Unlinked '{group.name}' from RadioReference",
            )
            self._set_status(f"Unlinked group '{group.name}' from RadioReference.")

    def _on_refresh_group_from_rr(self):
        group = self._selected_group
        if group is None:
            return
        info = self._group_link_info(group)
        if not info:
            messagebox.showinfo("Refresh", "This group isn't linked to RadioReference yet.")
            return
        self._refresh_group_from_rr(group, info["rr_url"])

    def _refresh_group_from_rr(self, group: GroupNode, url: str) -> None:
        self._set_status(f"Fetching {url} ...")
        self.root.update_idletasks()
        try:
            parsed = fetch_radioreference_data(url)
        except Exception as exc:
            messagebox.showerror("Fetch Error", f"Could not fetch URL:\n{exc}")
            self._set_status("RadioReference fetch failed.")
            return
        if not parsed:
            messagebox.showinfo(
                "No Data",
                "Could not extract usable fields from this page.",
            )
            return
        kind = parsed.get("kind")
        if kind == "category":
            self._handle_rr_category(parsed)
        elif kind == "conventional_multi":
            self._handle_rr_conventional_multi(parsed)
        elif kind == "trs":
            self._handle_rr_trs(parsed)
        elif kind == "fcc_callsign":
            self._handle_rr_category({
                "kind": "category",
                "group_name": parsed.get("licensee") or group.name,
                "frequencies": parsed.get("frequencies") or [],
            })
        else:
            messagebox.showinfo("Refresh", f"Unsupported RR page kind: {kind!r}")
            return
        if self._meta is not None:
            self._meta.set_group_link(
                self._group_key_for(group),
                rr_url=url,
                rr_kind=self._rr_kind_from_url(url),
            )

    def _on_diff_group_against_rr(self):
        group = self._selected_group
        if group is None:
            return
        info = self._group_link_info(group)
        if not info:
            messagebox.showinfo("Diff", "Link the group to RadioReference first.")
            return
        RadioReferenceDiffDialog(self, group, info["rr_url"])

    def _collect_entries_for_action(self) -> Tuple[str, List[FreqEntry]]:
        if self._selected_entry is not None:
            return ("entry", [self._selected_entry])
        if self._selected_group is not None:
            return ("group", list(self._selected_group.entries))
        sys_node = getattr(self, "_selected_system", None)
        if sys_node is not None:
            entries = [e for g in sys_node.groups for e in g.entries]
            return ("system", entries)
        return ("none", [])

    def _on_update_service(self):
        stype_str = self._edit_stype_var.get()
        if not stype_str:
            return
        new_type = int(stype_str.split(" - ")[0])
        scope, entries = self._collect_entries_for_action()
        if scope == "none" or not entries:
            messagebox.showinfo("Info", "Select an entry, group, or system first.")
            return
        if scope != "entry":
            if not messagebox.askyesno(
                "Bulk Update",
                f"Apply service type {service_label(new_type)} to {len(entries)} entries in this {scope}?",
            ):
                return
        txn = self._new_txn_id()
        source = "bulk" if scope != "entry" else "manual"
        changed = 0
        batch_ctx = self._meta.batch() if self._meta is not None else nullcontext()
        with batch_ctx:
            for entry in entries:
                if self._do_set_service(entry, new_type, source=source, txn_id=txn):
                    changed += 1
                self._refresh_entry_in_tree(entry)
        if self._selected_entry:
            self._show_entry_details(self._selected_entry)
        self._set_status(
            f"Updated service type to {service_label(new_type)} for {changed} entries ({scope})"
        )

    def _on_toggle_avoid(self):
        scope, entries = self._collect_entries_for_action()
        if scope == "none" or not entries:
            messagebox.showinfo("Info", "Select an entry, group, or system first.")
            return
        if scope == "entry":
            entry = self._selected_entry
            current = entry.record.get_field(4, "Off")
            new_avoid = "On" if current == "Off" else "Off"
            self._do_set_avoid(entry, new_avoid)
            self._show_entry_details(entry)
            self._refresh_entry_in_tree(entry)
            self._set_status("Toggled avoid state")
            return
        choice = messagebox.askyesnocancel(
            "Bulk Avoid",
            f"Set avoid state for {len(entries)} entries in this {scope}?\n"
            "Yes = Avoid ON (skip all)\n"
            "No = Avoid OFF (scan all)\n"
            "Cancel = do nothing",
        )
        if choice is None:
            return
        target = "On" if choice else "Off"
        txn = self._new_txn_id()
        changed = 0
        batch_ctx = self._meta.batch() if self._meta is not None else nullcontext()
        with batch_ctx:
            for entry in entries:
                if self._do_set_avoid(entry, target, source="bulk", txn_id=txn):
                    changed += 1
                self._refresh_entry_in_tree(entry)
        self._set_status(f"Set avoid={target} for {changed} entries ({scope})")

    def _on_add_type_changed(self):
        if self._add_type_var.get() == "Conventional":
            self._add_freq_label.config(text="Frequency (MHz):")
            self._add_mode_combo["values"] = MODE_CHOICES_CONV
            self._add_mode_var.set("NFM")
            self._add_tone_label.config(text="Tone (e.g. TONE=C156.7):")
        else:
            self._add_freq_label.config(text="Talkgroup ID:")
            self._add_mode_combo["values"] = MODE_CHOICES_TGID
            self._add_mode_var.set("ALL")
            self._add_tone_label.config(text="(Not used for TGID)")

    def _on_fetch_rr_url(self):
        url = self._add_rr_url_var.get().strip()
        if not url:
            messagebox.showinfo("Info", "Paste a RadioReference URL first.")
            return
        self._set_status(f"Fetching {url} ...")
        self.root.update_idletasks()
        try:
            parsed = fetch_radioreference_data(url)
        except Exception as exc:
            messagebox.showerror("Fetch Error", f"Could not fetch URL:\n{exc}")
            self._set_status("RadioReference fetch failed.")
            return
        if not parsed:
            messagebox.showinfo(
                "No Data",
                "Could not extract usable fields from this page. The page format may be unsupported.",
            )
            self._set_status("RadioReference fetch returned no usable data.")
            return
        if parsed.get("kind") == "category":
            self._handle_rr_category(parsed)
            return
        if parsed.get("kind") == "conventional_multi":
            self._handle_rr_conventional_multi(parsed)
            return
        if parsed.get("kind") == "trs":
            self._handle_rr_trs(parsed)
            return
        frequencies = parsed.get("frequencies") or []
        if not frequencies:
            messagebox.showinfo("No Frequencies", "No frequencies found on that page.")
            return
        if len(frequencies) == 1:
            chosen = frequencies[0]
        else:
            chosen = self._prompt_pick_frequency(frequencies)
            if chosen is None:
                return
        name = parsed.get("name") or chosen.get("name") or ""
        if chosen.get("city") and name and chosen["city"].lower() not in name.lower():
            name = f"{name} ({chosen['city']})"
        self._add_name_var.set(name.strip())
        self._add_type_var.set("Conventional")
        self._on_add_type_changed()
        self._add_freq_var.set(f"{chosen['mhz']:.4f}")
        self._add_mode_var.set(chosen.get("mode") or "NFM")
        self._add_tone_var.set(chosen.get("tone") or "")
        stype_guess = parsed.get("suggested_service_type")
        if isinstance(stype_guess, int):
            for label in [s[1] for s in SERVICE_CHOICES]:
                if label.startswith(f"{stype_guess} "):
                    self._add_stype_var.set(label)
                    break
        self._set_status(f"Fetched {name.strip() or url}")

    def _location_mismatch_reason(
        self,
        system: Optional[SystemNode] = None,
        group: Optional[GroupNode] = None,
    ) -> Optional[str]:
        """Return a human-readable warning if the given system/group doesn't match
        the active location filter. Returns None when everything lines up."""
        if not self._location_filter_enabled.get():
            return None
        target_system = system
        if target_system is None and group is not None:
            for sys_node in self.hpd.systems:
                if group in sys_node.groups:
                    target_system = sys_node
                    break
        if target_system is None:
            return None

        active_county = self._active_county_id
        if active_county and target_system.county_ids and active_county not in target_system.county_ids:
            county_name = next(
                (name for cid, name in self._county_choices if cid == active_county),
                f"CountyId {active_county}",
            )
            return (
                f"Active county is {county_name}, but the target system '{target_system.name}' "
                "belongs to a different county."
            )

        if self._active_coords and group is not None and group.lat is not None and group.lon is not None:
            distance = haversine_miles(
                self._active_coords[0], self._active_coords[1], group.lat, group.lon
            )
            tolerance = max(self._coverage_tolerance_miles(), group.range_miles or 0.0)
            if distance > tolerance + 50:
                return (
                    f"Group '{group.name}' is {distance:.0f} miles from the active ZIP/City. "
                    "It will not likely be heard from this location."
                )
        return None

    def _confirm_location_mismatch(
        self,
        system: Optional[SystemNode] = None,
        group: Optional[GroupNode] = None,
    ) -> bool:
        reason = self._location_mismatch_reason(system=system, group=group)
        if reason is None:
            return True
        return messagebox.askyesno("Location Mismatch", f"{reason}\n\nContinue anyway?")

    def _resolve_target_system(self) -> Optional[SystemNode]:
        if self._selected_system is not None:
            return self._selected_system
        if self._selected_group is not None:
            for sys_node in self.hpd.systems:
                if self._selected_group in sys_node.groups:
                    return sys_node
        if self._selected_entry is not None:
            for sys_node in self.hpd.systems:
                for group in sys_node.groups:
                    if self._selected_entry in group.entries:
                        return sys_node
        return None

    def _on_create_group(self):
        system = self._resolve_target_system()
        if system is None:
            messagebox.showinfo(
                "Info",
                "Select a county/system (or a group within it) before creating a new sub-group.",
            )
            return
        if system.system_type != "Conventional":
            messagebox.showwarning(
                "Unsupported",
                "Creating groups is currently supported for conventional (county) systems only.",
            )
            return
        from tkinter import simpledialog

        name = simpledialog.askstring(
            "Create Group",
            f"New group name under {system.name}:",
            parent=self.root,
        )
        if not name:
            return
        if not self._confirm_location_mismatch(system=system):
            return
        try:
            group = self._do_add_cgroup(system, name.strip())
        except Exception as exc:
            messagebox.showerror("Error", f"Could not create group:\n{exc}")
            return
        self._populate_tree()
        self._set_status(f"Created group '{group.name}' under {system.name}.")

    def _handle_rr_category(self, parsed: Dict[str, Any]):
        frequencies = parsed.get("frequencies") or []
        if not frequencies:
            messagebox.showinfo("No Frequencies", "No frequencies found on that page.")
            return
        system = self._resolve_target_system()
        if system is None or system.system_type != "Conventional":
            messagebox.showinfo(
                "Select System",
                "Select a conventional county system first.",
            )
            return
        if not self._confirm_location_mismatch(system=system):
            return
        wrapped = {
            "title": parsed.get("group_name") or "RadioReference Group",
            "categories": [
                {
                    "name": parsed.get("group_name") or "RadioReference Group",
                    "frequencies": frequencies,
                }
            ],
        }
        dialog = ConventionalImportSelectionDialog(self, system, wrapped)
        if not dialog.result:
            return
        source_url = parsed.get("source_url") or self._add_rr_url_var.get().strip()
        source_kind = "rr_category" if "/aid/" in source_url else "rr_ctid"
        self._apply_cfreq_import(
            system, dialog.result, source=source_kind, source_url=source_url,
        )

    def _handle_rr_conventional_multi(self, parsed: Dict[str, Any]):
        categories = parsed.get("categories") or []
        if not categories:
            messagebox.showinfo("No Frequencies", "No frequencies found on that page.")
            return
        system = self._resolve_target_system()
        if system is None or system.system_type != "Conventional":
            messagebox.showinfo(
                "Select System",
                "Select a conventional county system first.",
            )
            return
        if not self._confirm_location_mismatch(system=system):
            return
        dialog = ConventionalImportSelectionDialog(self, system, parsed)
        if not dialog.result:
            return
        source_url = parsed.get("source_url") or self._add_rr_url_var.get().strip()
        source_kind = "rr_ctid" if "/ctid/" in source_url else "rr_category"
        self._apply_cfreq_import(
            system, dialog.result, source=source_kind, source_url=source_url,
        )

    def _apply_cfreq_import(
        self,
        system: SystemNode,
        selection: List[Tuple[str, List[Dict[str, Any]]]],
        *,
        source: str = "rr_category",
        source_url: str = "",
    ):
        existing_names = {g.name.strip().lower(): g for g in system.groups}
        freq_added = 0
        freq_updated = 0
        freq_skipped = 0
        groups_created: List[str] = []

        default_group_lat, default_group_lon, default_group_range = (
            self._infer_tgroup_geo_defaults(system)
        )

        import_txn = self._new_txn_id()
        added_records: List[Dict[str, Any]] = []
        updated_records: List[Dict[str, Any]] = []

        # Single batch + composite event: all per-entry mutations skip
        # logging; one OP_IMPORT_APPLY captures the whole delta and is the
        # sole revertable record (see _revert_import_apply).
        batch_ctx = self._meta.batch() if self._meta is not None else nullcontext()
        with batch_ctx:
            for cat_name, freqs in selection:
                if not freqs:
                    continue
                key = cat_name.strip().lower()
                new_freqs = [f for f in freqs if f.get("__action__") == "new"]
                group: Optional[GroupNode] = existing_names.get(key)
                if new_freqs and group is None:
                    try:
                        group = self._do_add_cgroup(
                            system,
                            cat_name.strip(),
                            lat=default_group_lat,
                            lon=default_group_lon,
                            range_miles=default_group_range,
                            source=source,
                            txn_id=import_txn,
                            log=False,
                        )
                        groups_created.append(self._group_key_for(group))
                        existing_names[key] = group
                    except Exception as exc:
                        messagebox.showerror(
                            "Error", f"Could not create group '{cat_name}':\n{exc}"
                        )
                        continue

                for freq in freqs:
                    action = freq.get("__action__")
                    try:
                        freq_hz = int(freq["__freq_hz__"])
                    except Exception:
                        try:
                            freq_hz = int(round(float(freq["mhz"]) * 1_000_000))
                        except Exception:
                            freq_skipped += 1
                            continue
                    if action == "new":
                        if group is None:
                            freq_skipped += 1
                            continue
                        try:
                            stype = freq.get("suggested_service_type")
                            if not isinstance(stype, int):
                                stype = 14
                            entry = self._do_add_cfreq(
                                group=group,
                                name=freq.get("name") or freq.get("alpha") or "",
                                freq_hz=freq_hz,
                                mode=freq.get("mode") or "NFM",
                                tone=freq.get("tone") or "",
                                service_type=stype,
                                source=source,
                                txn_id=import_txn,
                                log=False,
                            )
                            added_records.append({
                                "id": self._entry_id_for(entry),
                                "snapshot": self._entry_snapshot(entry),
                                "record_fields": list(entry.record.fields),
                                "group_key": self._group_key_for(group),
                            })
                            freq_added += 1
                            self._record_callsign_ref(freq, entry, source_url=source_url)
                        except Exception:
                            freq_skipped += 1
                            continue
                    elif action == "update":
                        existing = freq.get("__existing__")
                        changes = freq.get("__changes__", {})
                        if existing is None or not changes:
                            freq_skipped += 1
                            continue
                        try:
                            before = self._entry_snapshot(existing)
                            if "name" in changes:
                                new_name = changes["name"][1]
                                existing.record.set_field(3, new_name)
                                existing.name = new_name
                            if "mode" in changes:
                                existing.record.set_field(6, changes["mode"][1])
                            if "tone" in changes:
                                existing.record.set_field(7, changes["tone"][1])
                            if "service_type" in changes:
                                self.hpd.update_service_type(
                                    existing, changes["service_type"][1]
                                )
                            else:
                                self.hpd.has_changes = True
                            after = self._entry_snapshot(existing)
                            updated_records.append({
                                "id": self._entry_id_for(existing),
                                "before": before,
                                "after": after,
                            })
                            freq_updated += 1
                            self._record_callsign_ref(freq, existing, source_url=source_url)
                        except Exception:
                            freq_skipped += 1
                            continue
                    else:
                        freq_skipped += 1

            if (added_records or updated_records) and self._meta is not None:
                self._log_event(
                    op=OP_IMPORT_APPLY,
                    target_id="",
                    target_name=source_url or "Conventional import",
                    summary=(
                        f"Conventional import: +{freq_added} added, "
                        f"~{freq_updated} updated, {len(groups_created)} new group(s)"
                    ),
                    source=source,
                    txn_id=import_txn,
                    payload={
                        "source_url": source_url,
                        "added": added_records,
                        "updated": updated_records,
                        "groups_created": groups_created,
                        "entry_type": "C-Freq",
                    },
                )

        if source_url and self._global_meta is not None:
            self._global_meta.push_recent_rr_url(source_url)
            self._global_meta.save()

        self._populate_tree()
        self._set_status(
            f"Conventional import: +{freq_added} new, ~{freq_updated} updated, "
            f"skipped {freq_skipped}."
        )
        messagebox.showinfo(
            "Conventional Import",
            f"Created {len(groups_created)} new group(s).\n"
            f"Added {freq_added} new frequencies.\n"
            f"Updated {freq_updated} existing frequencies.\n"
            f"Skipped {freq_skipped}.",
        )

    def _handle_rr_trs(self, parsed: Dict[str, Any]):
        categories = parsed.get("categories") or []
        if not categories:
            messagebox.showinfo("No Talkgroups", "No talkgroup categories found on that page.")
            return
        system = self._resolve_target_system()
        if system is None or system.system_type != "Trunk":
            messagebox.showinfo(
                "Select Trunk System",
                "Select a trunked system in the tree first. New T-Groups will be added under it.",
            )
            return
        if not self._confirm_location_mismatch(system=system):
            return
        dialog = TrunkedImportSelectionDialog(self, system, parsed)
        if not dialog.result:
            return
        source_url = parsed.get("source_url") or self._add_rr_url_var.get().strip()
        self._apply_trs_import(
            system, dialog.result, source="rr_sid", source_url=source_url,
        )

    def _infer_tgroup_geo_defaults(
        self, system: SystemNode
    ) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        for site in system.sites:
            if site.lat is not None and site.lon is not None:
                return site.lat, site.lon, site.range_miles
        for group in system.groups:
            if group.lat is not None and group.lon is not None:
                return group.lat, group.lon, group.range_miles
        return None, None, None

    def _existing_tgids_by_group(self, system: SystemNode) -> Dict[str, Set[int]]:
        result: Dict[str, Set[int]] = {}
        for group in system.groups:
            key = group.name.strip().lower()
            tgids: Set[int] = set()
            for entry in group.entries:
                if entry.entry_type != "TGID":
                    continue
                try:
                    tgids.add(int(entry.record.get_field(5, "")))
                except ValueError:
                    continue
            result[key] = tgids
        return result

    def _existing_system_tgids(self, system: SystemNode) -> Set[int]:
        all_tgids: Set[int] = set()
        for group in system.groups:
            for entry in group.entries:
                if entry.entry_type != "TGID":
                    continue
                try:
                    all_tgids.add(int(entry.record.get_field(5, "")))
                except ValueError:
                    continue
        return all_tgids

    def _apply_trs_import(
        self, system: SystemNode, selection: List[Tuple[str, List[Dict[str, Any]]]],
        *,
        source: str = "rr_sid",
        source_url: str = "",
    ):
        existing_names = {g.name.strip().lower(): g for g in system.groups}
        groups_created: List[str] = []
        tgids_added = 0
        tgids_updated = 0
        tgids_skipped = 0

        default_lat, default_lon, default_range = self._infer_tgroup_geo_defaults(system)

        import_txn = self._new_txn_id()
        added_records: List[Dict[str, Any]] = []
        updated_records: List[Dict[str, Any]] = []
        avoid_records: List[Dict[str, Any]] = []
        deleted_records: List[Dict[str, Any]] = []

        tgids_avoided = 0
        tgids_deleted = 0
        batch_ctx = self._meta.batch() if self._meta is not None else nullcontext()
        with batch_ctx:
            for cat_name, talkgroups in selection:
                if not talkgroups:
                    continue
                key = cat_name.strip().lower()
                group = existing_names.get(key)
                needs_new_group = any(item.get("__action__") == "new" for item in talkgroups)
                if group is None and needs_new_group:
                    try:
                        group = self._do_add_tgroup(
                            system,
                            cat_name.strip(),
                            lat=default_lat,
                            lon=default_lon,
                            range_miles=default_range,
                            source=source,
                            txn_id=import_txn,
                            log=False,
                        )
                        groups_created.append(self._group_key_for(group))
                        existing_names[key] = group
                    except Exception as exc:
                        messagebox.showerror(
                            "Error", f"Could not create T-Group '{cat_name}':\n{exc}"
                        )
                        continue
                elif group is not None:
                    if (
                        group.lat is None
                        and group.lon is None
                        and default_lat is not None
                        and default_lon is not None
                    ):
                        try:
                            self._do_edit_group(
                                group,
                                lat=default_lat,
                                lon=default_lon,
                                range_miles=default_range,
                                source=source,
                                txn_id=import_txn,
                                log=False,
                            )
                        except Exception:
                            pass
                for tg in talkgroups:
                    action = tg.get("__action__")
                    try:
                        tgid_val = int(tg["tgid"])
                    except Exception:
                        continue
                    if action == "new":
                        if group is None:
                            tgids_skipped += 1
                            continue
                        try:
                            stype = tg.get("suggested_service_type")
                            if not isinstance(stype, int):
                                stype = 1
                            entry = self._do_add_tgid(
                                group=group,
                                name=tg.get("name") or tg.get("alpha") or f"TGID {tgid_val}",
                                tgid=tgid_val,
                                mode=tg.get("mode") or "ALL",
                                service_type=stype,
                                source=source,
                                txn_id=import_txn,
                                log=False,
                            )
                            added_records.append({
                                "id": self._entry_id_for(entry),
                                "snapshot": self._entry_snapshot(entry),
                                "record_fields": list(entry.record.fields),
                                "group_key": self._group_key_for(group),
                            })
                            tgids_added += 1
                        except Exception:
                            continue
                    elif action == "update":
                        existing = tg.get("__existing__")
                        changes = tg.get("__changes__", {})
                        if existing is None or not changes:
                            tgids_skipped += 1
                            continue
                        try:
                            before = self._entry_snapshot(existing)
                            if "name" in changes:
                                new_name = changes["name"][1]
                                existing.record.set_field(3, new_name)
                                existing.name = new_name
                            if "mode" in changes:
                                existing.record.set_field(6, changes["mode"][1])
                            if "service_type" in changes:
                                new_stype = changes["service_type"][1]
                                self.hpd.update_service_type(existing, new_stype)
                            else:
                                self.hpd.has_changes = True
                            after = self._entry_snapshot(existing)
                            updated_records.append({
                                "id": self._entry_id_for(existing),
                                "before": before,
                                "after": after,
                            })
                            tgids_updated += 1
                        except Exception:
                            continue
                    elif action == "avoid_encrypted":
                        existing = tg.get("__existing__")
                        if existing is None:
                            tgids_skipped += 1
                            continue
                        try:
                            before_avoid = existing.record.get_field(4, "Off")
                            if self._do_set_avoid(
                                existing,
                                "On",
                                source=source,
                                txn_id=import_txn,
                                log=False,
                            ):
                                avoid_records.append({
                                    "id": self._entry_id_for(existing),
                                    "before": {"avoid": before_avoid},
                                    "after": {"avoid": "On"},
                                })
                                tgids_avoided += 1
                        except Exception:
                            continue
                    elif action == "delete_encrypted":
                        existing = tg.get("__existing__")
                        if existing is None:
                            tgids_skipped += 1
                            continue
                        try:
                            eid = self._entry_id_for(existing)
                            name = existing.name
                            record_fields = list(existing.record.fields)
                            snapshot = self._entry_snapshot(existing)
                            group_key = None
                            for sys_node in self.hpd.systems:
                                for g in sys_node.groups:
                                    if existing in g.entries:
                                        group_key = self._group_key_for(g)
                                        break
                                if group_key:
                                    break
                            self._do_delete_entry(
                                existing,
                                source=source,
                                txn_id=import_txn,
                                log=False,
                            )
                            deleted_records.append({
                                "id": eid,
                                "name": name,
                                "snapshot": snapshot,
                                "record_fields": record_fields,
                                "group_key": group_key,
                            })
                            tgids_deleted += 1
                        except Exception:
                            continue
                    else:
                        tgids_skipped += 1

            if (
                added_records
                or updated_records
                or avoid_records
                or deleted_records
            ) and self._meta is not None:
                self._log_event(
                    op=OP_IMPORT_APPLY,
                    target_id="",
                    target_name=source_url or "Trunked import",
                    summary=(
                        f"Trunked import: +{tgids_added} added, ~{tgids_updated} updated, "
                        f"{len(groups_created)} new group(s), "
                        f"{tgids_avoided} avoided, {tgids_deleted} deleted"
                    ),
                    source=source,
                    txn_id=import_txn,
                    payload={
                        "source_url": source_url,
                        "added": added_records,
                        "updated": updated_records,
                        "avoided": avoid_records,
                        "deleted": deleted_records,
                        "groups_created": groups_created,
                        "entry_type": "TGID",
                    },
                )
        if source_url and self._global_meta is not None:
            self._global_meta.push_recent_rr_url(source_url)
            self._global_meta.save()

        self._populate_tree()
        self._set_status(
            f"Trunked import: +{tgids_added} new, ~{tgids_updated} updated, "
            f"avoided {tgids_avoided}, deleted {tgids_deleted}, skipped {tgids_skipped}."
        )
        messagebox.showinfo(
            "Trunked Import",
            f"Created {groups_created} new group(s).\n"
            f"Added {tgids_added} new talkgroups.\n"
            f"Updated {tgids_updated} existing talkgroups.\n"
            f"Set Avoid=On on {tgids_avoided} now-encrypted entries.\n"
            f"Deleted {tgids_deleted} encrypted entries.\n"
            f"Skipped {tgids_skipped}.",
        )

    def _prompt_pick_frequency(self, frequencies: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        top = tk.Toplevel(self.root)
        top.title("Select Frequency")
        top.transient(self.root)
        top.grab_set()
        tk.Label(top, text="Multiple frequencies found. Pick one:").pack(padx=10, pady=(10, 4))
        listbox = tk.Listbox(top, width=60, height=min(12, len(frequencies)))
        for freq in frequencies:
            listbox.insert(
                tk.END,
                f"{freq['mhz']:.4f} MHz  {freq.get('mode', '')}  {freq.get('class', '')}  {freq.get('city', '')}",
            )
        listbox.pack(padx=10, pady=4, fill=tk.BOTH, expand=True)
        listbox.selection_set(0)
        result: List[Optional[Dict[str, Any]]] = [None]

        def on_ok():
            sel = listbox.curselection()
            if sel:
                result[0] = frequencies[sel[0]]
            top.destroy()

        def on_cancel():
            top.destroy()

        btns = ttk.Frame(top)
        btns.pack(pady=(4, 10))
        ttk.Button(btns, text="Use", command=on_ok).pack(side=tk.LEFT, padx=4)
        ttk.Button(btns, text="Cancel", command=on_cancel).pack(side=tk.LEFT, padx=4)
        self.root.wait_window(top)
        return result[0]

    def _on_add_entry(self):
        if not self._selected_group:
            messagebox.showinfo("Info", "Select a group (bold item) in the tree first.")
            return
        if not self._confirm_location_mismatch(group=self._selected_group):
            return

        name = self._add_name_var.get().strip()
        if not name:
            messagebox.showwarning("Missing", "Please enter a name / description.")
            return

        stype_str = self._add_stype_var.get()
        if not stype_str:
            messagebox.showwarning("Missing", "Please select a service type.")
            return
        service_type = int(stype_str.split(" - ")[0])

        add_type = self._add_type_var.get()
        group = self._selected_group

        if add_type == "Conventional":
            if group.group_type != "C-Group":
                messagebox.showwarning(
                    "Wrong group",
                    "Select a Conventional group (under a county) to add a frequency.",
                )
                return

            freq_text = self._add_freq_var.get().strip()
            if not freq_text:
                messagebox.showwarning("Missing", "Please enter a frequency in MHz.")
                return
            try:
                freq_hz = parse_freq_mhz(freq_text)
            except ValueError:
                messagebox.showerror("Invalid", "Could not parse frequency. Enter a number in MHz (e.g. 460.050)")
                return

            mode = self._add_mode_var.get()
            tone = self._add_tone_var.get().strip()

            entry = self._do_add_cfreq(group, name, freq_hz, mode, tone, service_type)
            self._add_entry_to_tree(group, entry)
            self._set_status(f"Added: {name} — {format_freq(freq_hz)} [{service_label(service_type)}]")

        else:
            if group.group_type != "T-Group":
                messagebox.showwarning(
                    "Wrong group",
                    "Select a Trunked group (under a trunk system) to add a talkgroup.",
                )
                return

            tgid_text = self._add_freq_var.get().strip()
            if not tgid_text:
                messagebox.showwarning("Missing", "Please enter a talkgroup ID.")
                return
            try:
                tgid = int(tgid_text)
            except ValueError:
                messagebox.showerror("Invalid", "Talkgroup ID must be an integer.")
                return

            mode = self._add_mode_var.get()

            entry = self._do_add_tgid(group, name, tgid, mode, service_type)
            self._add_entry_to_tree(group, entry)
            self._set_status(f"Added: {name} — TGID {tgid} [{service_label(service_type)}]")

        self._add_name_var.set("")
        self._add_freq_var.set("")
        self._add_tone_var.set("")

    def _on_save(self):
        if not self.hpd.filepath:
            messagebox.showinfo("Info", "No file loaded.")
            return

        if not self.hpd.has_changes:
            messagebox.showinfo("Info", "No changes to save.")
            return

        confirm = messagebox.askyesno(
            "Confirm Save",
            f"Save changes to:\n{self.hpd.filepath}\n\n"
            "Changes are tracked in Changes... and a session snapshot "
            "was captured when this file was first loaded.",
        )
        if not confirm:
            return

        try:
            self.hpd.save()
            committed_count = 0
            if self._meta is not None:
                committed_count = self._meta.mark_events_committed()
                self._meta.flush()
            extra = f" ({committed_count} change(s) committed)" if committed_count else ""
            self._set_status(
                f"Saved {os.path.basename(self.hpd.filepath)}{extra}"
            )
            self._refresh_sd_space()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save:\n{e}")

    def _on_filter_changed(self):
        if self.hpd.systems:
            self._populate_tree()
        self._update_filter_status()

    def _on_zip_lookup(self):
        zip_code = self._zip_var.get().strip()
        normalized = self.zip_lookup.normalize_zip(zip_code)
        if len(normalized) != 5:
            messagebox.showwarning("ZIP Code", "Enter a valid 5-digit ZIP code.")
            return
        folder = self._path_var.get().strip()
        if not self.config_loaded:
            if not folder or not os.path.isdir(folder):
                messagebox.showerror("Error", "Select your BCDx36HP folder first.")
                return
            self._try_load_config(folder)
            if not self.config_loaded:
                messagebox.showerror("Error", "Could not load hpdb.cfg from selected folder.")
                return

        self._load_firmware_zip_table(folder)
        preferred_state_id = self._state_id_from_firmware_zip(normalized)
        coords = self._firmware_zip_table.coords_for_zip(normalized)
        self._active_coords = coords
        match = self.zip_lookup.resolve(normalized, self.config, preferred_state_id=preferred_state_id)
        self._active_zip = normalized
        if not match and preferred_state_id is not None:
            match = {
                "state_id": preferred_state_id,
                "county_id": None,
                "county_name": "",
                "source": "firmware-only",
            }
        if not match:
            self._active_county_id = None
            self._set_status(
                f"Could not resolve ZIP {normalized}. Verify internet access or provide zip_county_map.json."
            )
            return

        state_id = match["state_id"]
        county_id = match["county_id"]
        self._set_state_by_id(state_id)
        self._refresh_county_options()
        self._active_county_id = county_id if isinstance(county_id, int) else None
        if self._active_county_id is not None:
            self._set_county_combo_to_id(self._active_county_id)
        else:
            self._county_var.set("(Auto from ZIP)")
        self._location_filter_enabled.set(True)
        self._load_state_hpd(state_id, suppress_message=True)
        source = match.get("source", "local")
        county_name = match.get("county_name")
        coord_text = ""
        if coords:
            coord_text = f" @ ({coords[0]:.3f}, {coords[1]:.3f})"
        if self._active_county_id is not None:
            county_name = county_name or f"CountyId {self._active_county_id}"
            msg = f"ZIP {normalized} resolved to {county_name} ({source}){coord_text}; showing effective scan set."
        else:
            msg = (
                f"ZIP {normalized} resolved state via {source}{coord_text}; showing effective scan set by coverage."
            )
        self._set_status(msg)
        if self.hpd.systems:
            self._populate_tree()

    def _refresh_county_options(self):
        sid = self._get_selected_state_id()
        items = ["(Auto from ZIP)"]
        self._county_choices = []
        if sid is not None and self.config_loaded:
            self._county_choices = self.config.get_counties_for_state(sid)
            items.extend(name for _, name in self._county_choices)
        self._county_combo["values"] = items
        if self._county_var.get() not in items:
            self._county_var.set("(Auto from ZIP)")

    def _set_county_combo_to_id(self, county_id: int):
        for cid, name in self._county_choices:
            if cid == county_id:
                self._county_var.set(name)
                return
        self._county_var.set("(Auto from ZIP)")

    def _on_county_override_changed(self, event=None):
        selected = self._county_var.get()
        if selected == "(Auto from ZIP)":
            if self._active_zip:
                match = self.zip_lookup.resolve(self._active_zip, self.config)
                self._active_county_id = match["county_id"] if match else None
            else:
                self._active_county_id = None
        else:
            for county_id, name in self._county_choices:
                if name == selected:
                    self._active_county_id = county_id
                    break
        if self._location_filter_enabled.get() and self.hpd.systems:
            self._populate_tree()
        self._update_filter_status()

    def _update_filter_status(self):
        if not self._location_filter_enabled.get():
            return
        parts = ["Location filter enabled"]
        if self._active_zip:
            parts.append(f"ZIP {self._active_zip}")
        if self._active_county_id:
            county_name = next(
                (name for cid, name in self._county_choices if cid == self._active_county_id),
                f"CountyId {self._active_county_id}",
            )
            parts.append(county_name)
        self._set_status(" | ".join(parts))

    def _load_state_hpd(self, sid: int, suppress_message: bool = False) -> bool:
        hpd_path = self.config.state_files.get(sid)
        if not hpd_path or not os.path.exists(hpd_path):
            if not suppress_message:
                messagebox.showerror(
                    "Error", f"No HPD file found for this state (expected s_{sid:06d}.hpd)"
                )
            return False
        if self.hpd.filepath == hpd_path and self.hpd.systems:
            return True
        try:
            self.hpd.load(hpd_path)
        except Exception as e:
            if not suppress_message:
                messagebox.showerror("Error", f"Failed to load HPD file:\n{e}")
            return False
        self._attach_meta_for_hpd(hpd_path)
        self._populate_tree()
        if not suppress_message:
            self._set_status(
                f"Loaded {os.path.basename(hpd_path)} — "
                f"{len(self.hpd.records)} lines, "
                f"{len(self.hpd.systems)} systems"
            )
            self._update_filter_status()
        return True

    def _set_state_by_id(self, state_id: int):
        for i, sid in enumerate(self._state_id_list):
            if sid == state_id:
                self._state_combo.current(i)
                return

    def _load_firmware_zip_table(self, folder: str):
        if self._firmware_zip_loaded:
            return
        self._firmware_zip_loaded = self._firmware_zip_table.load_from_sd(folder)

    def _load_firmware_city_table(self, folder: str):
        if self._firmware_city_loaded:
            return
        self._firmware_city_loaded = self._firmware_city_table.load_from_sd(folder)

    def _ensure_city_index(self, state_id: int):
        if self._city_index_state_id == state_id and self._city_index.by_state_name:
            return
        self._city_index = ScannerCityIndex()
        self._city_index.build(self.hpd, state_id)
        self._city_index_state_id = state_id

    def _state_id_from_firmware_zip(self, zip_code: str) -> Optional[int]:
        abbrev = self._firmware_zip_table.state_abbrev_for_zip(zip_code)
        if not abbrev:
            return None
        for sid, (_, state_abbrev) in self.config.states.items():
            if state_abbrev.upper() == abbrev.upper():
                return sid
        return None

    def _on_city_lookup(self):
        name = self._city_var.get().strip()
        if not name:
            messagebox.showwarning("City", "Enter a city name first.")
            return
        folder = self._path_var.get().strip()
        if not self.config_loaded:
            if not folder or not os.path.isdir(folder):
                messagebox.showerror("Error", "Select your BCDx36HP folder first.")
                return
            self._try_load_config(folder)
            if not self.config_loaded:
                messagebox.showerror("Error", "Could not load hpdb.cfg from selected folder.")
                return
        if folder:
            self._load_firmware_city_table(folder)
        state_id = self._get_selected_state_id()
        if state_id is None:
            messagebox.showinfo("City", "Pick a state from the State dropdown first.")
            return
        self._load_state_hpd(state_id, suppress_message=True)
        self._ensure_city_index(state_id)
        match = resolve_city_offline(
            name,
            self.config,
            self._custom_locations,
            self._firmware_city_table,
            self._city_index,
            state_id=state_id,
        )
        if not match:
            self._set_status(
                f"City '{name}' not in scanner database for this state. Add a custom location via Cities..."
            )
            return
        self._active_zip = None
        self._active_coords = (match["lat"], match["lon"])
        self._active_county_id = None
        self._location_filter_enabled.set(True)
        source = match.get("source", "offline")
        self._set_status(
            f"City '{name}' resolved via {source} @ ({match['lat']:.3f}, {match['lon']:.3f}); showing coverage scan set."
        )
        if self.hpd.systems:
            self._populate_tree()

    def _on_manage_cities(self):
        folder = self._path_var.get().strip()
        if folder:
            self._load_firmware_city_table(folder)
        CityManagerDialog(self)

    @staticmethod
    def _normalize_county_name(name: str) -> str:
        clean = " ".join(name.strip().lower().split())
        clean = clean.replace(" county", "")
        return clean

    def _on_select_updater_path(self):
        """Legacy single-override picker. Persists as an override in the
        Uniden tool registry (preferred tool = whichever this exe
        matches; we assume BT885 by default)."""
        path = filedialog.askopenfilename(
            title="Select Uniden updater executable",
            filetypes=[("Executable", "*.exe"), ("All Files", "*.*")],
        )
        if not path:
            return
        self._updater_path_var.set(path)
        # Also stash in uniden_tools_overrides so the registry picks it up.
        overrides = dict(self._app_settings.get("uniden_tools_overrides") or {})
        lower = os.path.basename(path).lower()
        tool_id = (
            uniden_tools.TOOL_SENTINEL
            if "sentinel" in lower
            else uniden_tools.TOOL_BT885
        )
        overrides[tool_id] = path
        self._app_settings["uniden_tools_overrides"] = overrides
        self._save_app_settings()
        self._set_status(
            f"Updater path set: {os.path.basename(path)} ({tool_id})"
        )

    def _tool_overrides(self) -> Dict[str, str]:
        return dict(self._app_settings.get("uniden_tools_overrides") or {})

    def _detect_updater_path(self) -> Optional[str]:
        """Return the exe path of the preferred Uniden updater.

        Picks BT885 Update Manager when present (native for our scanner),
        falls back to Sentinel otherwise so existing installations keep
        working. Honors app_settings overrides.
        """
        tools = uniden_tools.detect_installed_tools(
            repo_root=self._script_dir,
            overrides=self._tool_overrides(),
        )
        preferred_order = (
            uniden_tools.TOOL_BT885,
            uniden_tools.TOOL_SENTINEL,
        )
        for preferred in preferred_order:
            for tool in tools:
                if tool.tool_id == preferred and tool.installed:
                    return tool.exe_path
        return None

    def _on_open_uniden_tools(self):
        """Open the Uniden Tools registry dialog."""
        UnidenToolsDialog(self.root, self)

    # ---- RadioReference API credentials ----------------------------------

    _RR_KEYRING_SERVICE = "scanner-manager:radioreference"

    def _rr_username(self) -> str:
        return str(self._app_settings.get("rr_username") or "").strip()

    def _rr_app_key(self) -> str:
        return str(self._app_settings.get("rr_app_key") or "").strip()

    def _rr_password(self) -> str:
        """Fetch the RR password.

        Prefers Windows Credential Manager via ``keyring``; falls back to
        an in-memory value set during this session (never persisted).
        Returns '' when nothing is available.
        """
        username = self._rr_username()
        if not username:
            return ""
        in_memory = getattr(self, "_rr_password_cache", "") or ""
        try:
            import keyring  # type: ignore
            value = keyring.get_password(self._RR_KEYRING_SERVICE, username)
            if value:
                return value
        except Exception:
            pass
        return in_memory

    def _set_rr_password(self, username: str, password: str) -> None:
        """Store the RR password in keyring; cache in-memory as fallback."""
        self._rr_password_cache = password
        try:
            import keyring  # type: ignore
            if password:
                keyring.set_password(
                    self._RR_KEYRING_SERVICE, username, password
                )
            else:
                try:
                    keyring.delete_password(
                        self._RR_KEYRING_SERVICE, username
                    )
                except Exception:
                    pass
        except Exception:
            # No keyring backend available; in-memory cache is all we have.
            pass

    def _rr_credentials(self) -> "Optional[rr_api.RRCredentials]":
        """Assemble a validated :class:`rr_api.RRCredentials` or return
        ``None`` when anything is missing. Never raises."""
        if rr_api is None:
            return None
        try:
            creds = rr_api.RRCredentials(
                app_key=self._rr_app_key(),
                username=self._rr_username(),
                password=self._rr_password(),
            )
            creds.validate()
            return creds
        except Exception:
            return None

    def _rr_client(self) -> "Optional[rr_api.RadioReferenceClient]":
        """Build a SOAP client when credentials + zeep are available.

        Returns ``None`` when we should fall back to the HTML scraper.
        """
        if rr_api is None:
            return None
        creds = self._rr_credentials()
        if creds is None:
            return None
        try:
            return rr_api.RadioReferenceClient(creds)
        except rr_api.RRUnavailableError:
            return None
        except Exception:
            return None

    def _on_open_rr_settings(self):
        """Open the RadioReference API credentials dialog."""
        RadioReferenceSettingsDialog(self.root, self)

    # ---- Data Pipeline control panel ------------------------------------

    def _pipeline_health_snapshot(self) -> Dict[str, Any]:
        """Compute the health state used by :class:`DataPipelineDialog`
        and the status-bar indicator. Returns a dict with the keys:

          ``tools``: ``{'rows': [{display_name, installed, version}]}``
          ``rr``: ``{'configured', 'premium', 'username', 'expires', ...}``
          ``vsd``: ``{'profile', 'pending_events', 'card': {...}}``
          ``health``: one of 'green', 'amber', 'red'.
        """
        tools = uniden_tools.detect_installed_tools(
            repo_root=self._script_dir,
            overrides=self._tool_overrides(),
        )
        tools_info = {
            "rows": [
                {
                    "tool_id": t.tool_id,
                    "display_name": t.display_name,
                    "installed": t.installed,
                    "version": t.version,
                }
                for t in tools
            ],
            "any_installed": any(t.installed for t in tools),
        }

        rr_info: Dict[str, Any] = {
            "zeep_missing": rr_api is None,
            "configured": bool(
                self._rr_app_key() and self._rr_username() and self._rr_password()
            ),
            "username": self._rr_username(),
            "premium": False,
            "expires": "",
        }
        if rr_api is not None and rr_info["configured"]:
            client = self._rr_client()
            if client is not None:
                try:
                    data = client.get_user_data()
                    rr_info["premium"] = client.is_premium()
                    rr_info["expires"] = (
                        data.get("expirationDate") or data.get("expires") or ""
                    )
                except Exception:
                    pass

        profile = self._active_profile()
        folder = (self._path_var.get() or "").strip()
        card_connected = False
        card_target = ""
        if folder and os.path.isdir(folder):
            ident = sdcard.probe_card_identity(folder)
            if profile is not None:
                card_connected = bool(
                    (ident.volume_serial
                     and ident.volume_serial == profile.get("card_volume_serial"))
                    or (ident.content_fingerprint
                        and ident.content_fingerprint
                        == profile.get("content_fingerprint"))
                )
            else:
                card_connected = ident.has_any_id()
            card_target = ident.target_model or ""
        pending = None
        if self._meta is not None:
            try:
                pending = len(self._meta.uncommitted_events())
            except Exception:
                pending = None
        vsd_info: Dict[str, Any] = {
            "profile": profile,
            "pending_events": pending,
            "card": {
                "connected": card_connected,
                "target_model": card_target,
            },
        }

        # Roll up a 3-state health: green when core bits work, amber when
        # partial, red when nothing is wired up.
        if tools_info["any_installed"] and (
            rr_info["premium"] or rr_info["configured"] or True
        ) and (profile is None or card_connected or pending == 0):
            base = "green"
        else:
            base = "amber"
        if not tools_info["any_installed"]:
            base = "amber"
        if not tools_info["any_installed"] and rr_api is None:
            base = "red"
        return {
            "tools": tools_info,
            "rr": rr_info,
            "vsd": vsd_info,
            "health": base,
        }

    def _on_open_data_pipeline(self):
        DataPipelineDialog(self.root, self)

    def _on_open_rr_pull(self):
        """Open the bulk-pull dialog (API: pull a county or state)."""
        if rr_api is None:
            messagebox.showerror(
                "RR API",
                "The 'zeep' package is not installed; bulk pulls require "
                "the API path. Install via: pip install -r requirements.txt",
            )
            return
        client = self._rr_client()
        if client is None:
            messagebox.showerror(
                "RR API",
                "RadioReference credentials are not configured. "
                "Open 'RR API...' to set them up.",
            )
            return
        RadioReferencePullDialog(self.root, self, client)

    def _fetch_rr_url_preferred(self, url: str) -> Optional[Dict[str, Any]]:
        """Fetch a RadioReference URL, preferring the SOAP API when
        credentials are configured and ``zeep`` is installed. Falls
        through to the HTML scraper on any API failure so the legacy
        flow keeps working for free-tier users.

        Returns the scraper-shape dict the existing import pipeline
        expects (keys vary by kind; see ``fetch_radioreference_data``).
        On API hits, the returned dict additionally includes an
        ``"_api_import"`` key holding the raw :class:`HpdImport` dict,
        so callers that understand the API shape can use it directly.
        """
        client = self._rr_client()
        if client is not None:
            try:
                imp = rr_api.fetch_via_url(client, url)
                envelope = {
                    "kind": f"api_{imp.source}",
                    "title": imp.title,
                    "_api_import": imp.to_dict(),
                }
                return envelope
            except Exception as exc:
                # Fall through to scraper on any API failure so free-tier
                # users (and any RR outage) are never blocked.
                self._set_status(
                    f"RR API failed ({exc.__class__.__name__}); "
                    "falling back to HTML."
                )
        return fetch_radioreference_data(url)

    def _on_run_update_pipeline(self):
        """Toolbar handler: run the full push \u2192 run \u2192 pull \u2192 reconcile
        pipeline using whichever Uniden tool is preferred for this
        scanner family (BT885 first, Sentinel fallback)."""
        self._run_update_pipeline()

    def _on_run_updater_and_reconcile(self):
        if not self.hpd.filepath:
            messagebox.showinfo("Info", "Load an HPD file first.")
            return

        updater_path = self._detect_updater_path()
        if not updater_path:
            messagebox.showerror(
                "Updater Not Found",
                "Could not find the Uniden updater executable. Use 'Updater Path...' to set it.",
            )
            return

        snapshot = self.hpd.snapshot_customizations()
        target_hpd_path = self.hpd.filepath
        self._set_status("Launching official updater...")
        self.root.config(cursor="watch")

        def worker():
            try:
                proc = subprocess.Popen([updater_path], shell=False)
                exit_code = proc.wait()
                if exit_code != 0:
                    self.root.after(
                        0,
                        lambda: messagebox.showerror(
                            "Updater Failed",
                            f"Updater exited with code {exit_code}. No merge was applied.",
                        ),
                    )
                    return
                if not os.path.exists(target_hpd_path):
                    self.root.after(
                        0,
                        lambda: messagebox.showerror(
                            "Update Error",
                            "Updated HPD file was not found after updater completion.",
                        ),
                    )
                    return
                self.hpd.load(target_hpd_path)
                self._attach_meta_for_hpd(target_hpd_path, is_restore=False)
                # One batch around the whole replay + summary event so a
                # large replay doesn't rewrite the sidecar per reapplied
                # event.
                batch_ctx = (
                    self._meta.batch() if self._meta is not None else nullcontext()
                )
                with batch_ctx:
                    replay_report = self._replay_events_after_update()
                    self._merge_report = self.hpd.apply_customizations(snapshot)
                    self._merge_report.update(replay_report)
                    if self.hpd.has_changes:
                        self.hpd.save()
                    try:
                        self._log_event(
                            op=OP_EXTERNAL_CHANGE,
                            target_id=f"updater::{int(time.time())}",
                            target_name=os.path.basename(updater_path),
                            summary=(
                                f"Uniden updater ran: "
                                f"replayed={replay_report.get('replayed', 0)}, "
                                f"missed={replay_report.get('missed', 0)}, "
                                f"safety_reapplied="
                                f"{self._merge_report.get('reapplied', 0)}, "
                                f"inserted="
                                f"{self._merge_report.get('inserted', 0)}"
                            ),
                            source="updater",
                            payload={
                                "updater_path": updater_path,
                                "hpd_path": target_hpd_path,
                                "replay": replay_report,
                                "safety_net": {
                                    k: self._merge_report.get(k, 0)
                                    for k in ("reapplied", "inserted", "unresolved")
                                },
                            },
                        )
                    except Exception:
                        pass
                audit_path = self._write_reconcile_audit(
                    target_hpd_path, snapshot, self._merge_report
                )
                self._last_reconcile_audit = audit_path
                self.root.after(0, self._populate_tree)
                self.root.after(0, self._show_merge_report)
                self.root.after(0, self._refresh_sd_space)
                # If a workspace profile is active and the loaded HPD
                # lives inside the workspace, pull card-side firmware /
                # ancillary updates back into the workspace so the
                # "virtual SD" stays current. HPD itself was already
                # replaced above via apply_customizations.
                profile = self._active_profile()
                if profile:
                    ws_dir = profile.get("workspace_dir") or ""
                    try:
                        hpd_inside_ws = (
                            ws_dir
                            and os.path.commonpath(
                                [os.path.abspath(ws_dir),
                                 os.path.abspath(target_hpd_path)]
                            ) == os.path.abspath(ws_dir)
                        )
                    except ValueError:
                        hpd_inside_ws = False
                    if hpd_inside_ws:
                        self.root.after(0, self._post_updater_pull, profile)
            except Exception as exc:
                err_msg = f"Update/reconcile failed:\n{exc}"
                self.root.after(0, lambda: messagebox.showerror("Update Error", err_msg))
            finally:
                self.root.after(0, lambda: self.root.config(cursor=""))

        threading.Thread(target=worker, daemon=True).start()

    def _show_merge_report(self):
        report = self._merge_report or {}
        msg = (
            "Event replay:\n"
            f"  Replayed: {report.get('replayed', 0)}\n"
            f"  Missed:   {report.get('missed', 0)}\n"
            f"    deletions={report.get('deletions', 0)}, "
            f"avoids={report.get('avoids', 0)}, "
            f"services={report.get('services', 0)}, "
            f"edits={report.get('edits', 0)}, "
            f"additions={report.get('additions', 0)}\n\n"
            "Safety-net pass:\n"
            f"  Reapplied edits:        {report.get('reapplied', 0)}\n"
            f"  Reinserted user entries:{report.get('inserted', 0)}\n"
            f"  Unresolved entries:     {report.get('unresolved', 0)}"
        )
        self._set_status("Update and reconcile complete.")
        messagebox.showinfo("Reconcile Report", msg)

    # ---- Full pipeline (push -> run -> pull -> reconcile) ---------------

    def _run_update_pipeline(self, *, tool_id: Optional[str] = None) -> None:
        """Full four-stage data pipeline:

        1. If a workspace is active, push workspace HPDs to the card (only
           HPD files; conflicts block the push).
        2. Launch the selected Uniden tool, wait for it to exit.
        3. Sync-pull any ancillary card-side changes back into the
           workspace (logs ``OP_EXTERNAL_CHANGE`` events).
        4. Re-apply MetaStore customizations via ``apply_customizations``
           and surface one merged report.
        """
        if not self.hpd.filepath:
            messagebox.showinfo(
                "Pipeline", "Load an HPD file first."
            )
            return

        tools = uniden_tools.detect_installed_tools(
            repo_root=self._script_dir,
            overrides=self._tool_overrides(),
        )
        selected: Optional[uniden_tools.UnidenTool] = None
        if tool_id:
            for tool in tools:
                if tool.tool_id == tool_id and tool.installed:
                    selected = tool
                    break
        if selected is None:
            for tool in tools:
                if tool.installed:
                    selected = tool
                    break
        if selected is None:
            messagebox.showerror(
                "Pipeline",
                "No Uniden tool is installed. Open 'Uniden Tools...' and "
                "install one first.",
            )
            return

        profile = self._active_profile()
        push_report: Optional["sdcard.SyncReport"] = None
        push_diffs: List["sdcard.FileDiff"] = []
        card_root: Optional[str] = None
        # Stage 1 — push (only when there's a workspace + card)
        if profile:
            card_root = self._prompt_card_for_sync(profile)
            if card_root:
                baseline = self._profile_baseline(profile)
                push_report, push_diffs = sdcard.sync_push(
                    card_root=card_root,
                    workspace_root=profile["workspace_dir"],
                    baseline=baseline,
                )
                if push_report.conflicts:
                    if not messagebox.askyesno(
                        "Pipeline — conflicts on card",
                        (
                            f"{len(push_report.conflicts)} file(s) on the "
                            "card diverged from the last sync. Continue "
                            "launching the Uniden tool anyway? "
                            "(Your changes will not be pushed until resolved.)"
                        ),
                    ):
                        return
                else:
                    self._update_profile_baseline(
                        profile, profile["workspace_dir"]
                    )
                    self._global_meta.save()

        snapshot = self.hpd.snapshot_customizations()
        target_hpd_path = self.hpd.filepath
        self._set_status(
            f"Pipeline: launching {selected.display_name}..."
        )
        self.root.config(cursor="watch")

        def worker():
            stage = "launch"
            try:
                exit_code = uniden_tools.run_tool(selected, wait=True)
                if exit_code != 0:
                    err_code = exit_code
                    self.root.after(
                        0,
                        lambda: messagebox.showerror(
                            "Pipeline",
                            f"{selected.display_name} exited with code {err_code}."
                            " No merge was applied.",
                        ),
                    )
                    return
                stage = "reconcile"
                if not os.path.exists(target_hpd_path):
                    self.root.after(
                        0,
                        lambda: messagebox.showerror(
                            "Pipeline",
                            "Updated HPD file was not found after the tool exited.",
                        ),
                    )
                    return
                self.hpd.load(target_hpd_path)
                self._attach_meta_for_hpd(target_hpd_path, is_restore=False)
                # Event replay first (source of truth), then the legacy
                # snapshot-based pass as a safety net for user-added
                # entries / anything not covered by reversible events.
                # Wrapped in a single batch so even a heavy replay
                # results in one sidecar write at the end.
                batch_ctx = (
                    self._meta.batch() if self._meta is not None else nullcontext()
                )
                with batch_ctx:
                    replay_report = self._replay_events_after_update()
                    self._merge_report = self.hpd.apply_customizations(snapshot)
                    self._merge_report.update(replay_report)
                    if self.hpd.has_changes:
                        self.hpd.save()
                    # Single row in the Changes panel for the whole
                    # pipeline; revertable via the session snapshot taken
                    # just before the tool launched.
                    try:
                        self._log_event(
                            op=OP_EXTERNAL_CHANGE,
                            target_id=f"pipeline::{int(time.time())}",
                            target_name=selected.display_name,
                            summary=(
                                f"Uniden update pipeline: "
                                f"replayed={replay_report.get('replayed', 0)}, "
                                f"missed={replay_report.get('missed', 0)}, "
                                f"safety_reapplied="
                                f"{self._merge_report.get('reapplied', 0)}, "
                                f"inserted="
                                f"{self._merge_report.get('inserted', 0)}"
                            ),
                            source="pipeline",
                            payload={
                                "tool_id": selected.tool_id,
                                "tool_version": selected.version or "",
                                "hpd_path": target_hpd_path,
                                "replay": replay_report,
                                "safety_net": {
                                    k: self._merge_report.get(k, 0)
                                    for k in ("reapplied", "inserted", "unresolved")
                                },
                            },
                        )
                    except Exception:
                        pass
                audit_path = self._write_reconcile_audit(
                    target_hpd_path, snapshot, self._merge_report
                )
                self._last_reconcile_audit = audit_path
                self.root.after(0, self._populate_tree)
                self.root.after(0, self._refresh_sd_space)
                stage = "pull"
                pull_summary: Dict[str, Any] = {}
                if profile and card_root:
                    baseline = self._profile_baseline(profile)
                    pull_report, pull_diffs = sdcard.sync_pull(
                        card_root=card_root,
                        workspace_root=profile["workspace_dir"],
                        baseline=baseline,
                    )
                    pull_summary = {
                        "copied": len(pull_report.copied),
                        "conflicts": len(pull_report.conflicts),
                        "external_changes": len(pull_report.external_changes),
                    }
                    self.root.after(
                        0,
                        lambda: self._handle_sync_result(
                            profile, pull_report, pull_diffs,
                            card_root=card_root,
                            direction="pull",
                        ),
                    )
                self.root.after(
                    0,
                    lambda: self._show_pipeline_report(
                        selected, push_report, self._merge_report, pull_summary
                    ),
                )
            except Exception as exc:
                err_msg = f"Pipeline failed during {stage}:\n{exc}"
                self.root.after(
                    0, lambda: messagebox.showerror("Pipeline", err_msg)
                )
            finally:
                self.root.after(0, lambda: self.root.config(cursor=""))

        threading.Thread(target=worker, daemon=True).start()

    def _show_pipeline_report(
        self,
        tool: "uniden_tools.UnidenTool",
        push_report: Optional["sdcard.SyncReport"],
        merge_report: Optional[Dict[str, int]],
        pull_summary: Dict[str, Any],
    ) -> None:
        lines = [f"Tool: {tool.display_name} ({tool.version or '?'})"]
        lines.append("")
        if push_report is not None:
            lines.append(
                f"Push (workspace \u2192 card): copied={len(push_report.copied)}, "
                f"conflicts={len(push_report.conflicts)}, "
                f"errors={len(push_report.errors)}"
            )
        else:
            lines.append("Push (workspace \u2192 card): skipped (no workspace/card).")
        merge = merge_report or {}
        lines.append(
            "Reconcile (event replay):"
            f" replayed={merge.get('replayed', 0)},"
            f" missed={merge.get('missed', 0)}"
            f" [deletions={merge.get('deletions', 0)},"
            f" avoids={merge.get('avoids', 0)},"
            f" services={merge.get('services', 0)},"
            f" edits={merge.get('edits', 0)},"
            f" additions={merge.get('additions', 0)}]"
        )
        lines.append(
            "Reconcile (safety net):"
            f" reapplied={merge.get('reapplied', 0)},"
            f" inserted={merge.get('inserted', 0)},"
            f" unresolved={merge.get('unresolved', 0)}"
        )
        if pull_summary:
            lines.append(
                f"Pull (card \u2192 workspace): copied={pull_summary.get('copied', 0)}, "
                f"external={pull_summary.get('external_changes', 0)}, "
                f"conflicts={pull_summary.get('conflicts', 0)}"
            )
        else:
            lines.append("Pull (card \u2192 workspace): skipped.")
        self._set_status("Pipeline complete.")
        messagebox.showinfo("Pipeline report", "\n".join(lines))

    def _post_updater_pull(self, profile: Dict[str, Any]) -> None:
        """After the Uniden updater writes a new HPD on the workspace,
        pull any card-side ancillary changes (firmware, CityTable, etc.)
        back into the workspace so the virtual SD stays a faithful mirror.

        Safe to call even when no physical card is attached; it just
        no-ops in that case.
        """
        card_root = (
            profile.get("last_synced_card_path")
            or (self._path_var.get() or "").strip()
        )
        if not card_root or not os.path.isdir(card_root):
            return
        if os.path.abspath(card_root) == os.path.abspath(
            profile.get("workspace_dir") or ""
        ):
            return  # updater ran against the workspace directly, nothing to pull
        baseline = self._profile_baseline(profile)
        report, diffs = sdcard.sync_pull(
            card_root=card_root,
            workspace_root=profile["workspace_dir"],
            baseline=baseline,
        )
        if report.copied or report.conflicts:
            self._handle_sync_result(
                profile, report, diffs,
                card_root=card_root,
                direction="pull",
            )

    # ---- MetaStore integration --------------------------------------------

    def _attach_meta_for_hpd(self, hpd_path: str, is_restore: bool = False) -> None:
        """Attach (or reload) the MetaStore sidecar for an HPD file.

        Called once per HPD load. Writes a session snapshot on first load
        of this path in this session, then captures baselines for all
        currently-present entries/groups.
        """
        self._meta = MetaStore()
        self._meta.bind(hpd_path)
        self._backfill_committed_from_hpd_mtime(hpd_path)
        if self._session_snapshot_enabled.get():
            key = os.path.normcase(os.path.abspath(hpd_path))
            if is_restore or key not in self._session_snapshot_paths:
                try:
                    write_session_snapshot(hpd_path)
                    self._session_snapshot_paths.add(key)
                except Exception:
                    pass
        self._capture_baselines()
        self._meta.flush()

    def _backfill_committed_from_hpd_mtime(self, hpd_path: str) -> None:
        """Stamp legacy events (no committed_at) as committed at the HPD's
        mtime. Rationale: we are loading an HPD from disk that already
        reflects every event persisted to the sidecar; treating them as
        committed keeps the Changes panel honest for files last touched by
        an older build of the app.
        """
        if self._meta is None or not self._meta.events:
            return
        if not any(e.committed_at is None for e in self._meta.events):
            return
        try:
            mtime = os.path.getmtime(hpd_path)
            stamp = datetime.utcfromtimestamp(mtime).replace(
                microsecond=0
            ).isoformat() + "Z"
        except Exception:
            stamp = None
        self._meta.mark_events_committed(stamp)

    def _capture_baselines(self) -> None:
        """On first attachment, ensure every system/entry/group has a baseline row."""
        if self._meta is None:
            return
        new_baselines = 0
        for sys_node in self.hpd.systems:
            sid = self._system_key_for(sys_node)
            if not self._meta.has_baseline(sid):
                self._meta.ensure_baseline(
                    sid,
                    origin="first_load",
                    snapshot=self._system_snapshot(sys_node),
                    record_fields=list(sys_node.record.fields),
                    group_ref={
                        "system_id": sys_node.system_id,
                        "system_type": sys_node.system_type,
                    },
                )
                new_baselines += 1
            for group in sys_node.groups:
                gid = self._group_key_for(group)
                if not self._meta.has_baseline(gid):
                    self._meta.ensure_baseline(
                        gid,
                        origin="first_load",
                        snapshot=self._group_snapshot(group),
                        record_fields=list(group.record.fields),
                        group_ref={
                            "system_id": sys_node.system_id,
                            "system_name": sys_node.name,
                            "group_type": group.group_type,
                        },
                    )
                    new_baselines += 1
                for entry in group.entries:
                    eid = self._entry_id_for(entry)
                    if self._meta.has_baseline(eid):
                        continue
                    self._meta.ensure_baseline(
                        eid,
                        origin="first_load",
                        snapshot=self._entry_snapshot(entry),
                        record_fields=list(entry.record.fields),
                        group_ref={
                            "system_id": entry.system_id,
                            "group_id": entry.group_id,
                            "group_name": entry.group_name,
                            "system_name": entry.system_name,
                            "group_type": entry.group_type,
                            "entry_type": entry.entry_type,
                        },
                    )
                    new_baselines += 1
        if new_baselines:
            self._meta.mark_dirty()

    # --- id / snapshot helpers ---

    def _entry_id_for(self, entry: FreqEntry) -> str:
        return entry_id_for(
            entry.entry_type,
            entry.system_id or "",
            entry.group_id or "",
            entry.record.get_field(5, ""),
        )

    def _group_key_for(self, group: GroupNode) -> str:
        return group_id_for(group.system_id or "", group.group_id or "")

    def _system_key_for(self, sys_node: SystemNode) -> str:
        return system_id_for(sys_node.system_id or "")

    def _entry_snapshot(self, entry: FreqEntry) -> Dict[str, Any]:
        rec = entry.record
        snap: Dict[str, Any] = {
            "entry_type": entry.entry_type,
            "name": entry.name,
            "service_type": entry.service_type,
            "avoid": rec.get_field(4, "Off"),
            "identity_value": rec.get_field(5, ""),
            "mode": rec.get_field(6, ""),
            "group_id": entry.group_id,
            "group_name": entry.group_name,
            "system_id": entry.system_id,
            "system_name": entry.system_name,
        }
        if entry.entry_type == "C-Freq":
            snap["tone"] = rec.get_field(7, "")
        return snap

    def _group_snapshot(self, group: GroupNode) -> Dict[str, Any]:
        return {
            "group_type": group.group_type,
            "name": group.name,
            "lat": group.lat,
            "lon": group.lon,
            "range_miles": group.range_miles,
            "system_id": group.system_id,
            "system_name": group.system_name,
        }

    def _system_snapshot(self, sys_node: SystemNode) -> Dict[str, Any]:
        return {
            "system_type": sys_node.system_type,
            "system_id": sys_node.system_id,
            "name": sys_node.name,
            "group_count": len(sys_node.groups),
            "entry_count": sum(len(g.entries) for g in sys_node.groups),
        }

    # --- lookup helpers ---

    def _find_entry_by_id(self, entry_id: str) -> Optional[FreqEntry]:
        if not entry_id:
            return None
        for sys_node in self.hpd.systems:
            for group in sys_node.groups:
                for entry in group.entries:
                    if self._entry_id_for(entry) == entry_id:
                        return entry
        return None

    def _find_group_by_key(self, group_key: str) -> Optional[GroupNode]:
        if not group_key:
            return None
        for sys_node in self.hpd.systems:
            for group in sys_node.groups:
                if self._group_key_for(group) == group_key:
                    return group
        return None

    def _find_system_by_key(self, sys_key: str) -> Optional[SystemNode]:
        if not sys_key:
            return None
        for sys_node in self.hpd.systems:
            if self._system_key_for(sys_node) == sys_key:
                return sys_node
        return None

    # --- post-update event replay ---
    #
    # The Uniden updater rewrites HPDs from scratch and wipes every user
    # customization (deletions, avoids, service types, renames, adds).
    # After the file reloads, we walk the MetaStore event log and
    # re-execute every non-reverted reversible event against the fresh
    # tree. Raw `self.hpd.*` mutations are used so we don't double-log.

    @staticmethod
    def _replay_norm(text: str) -> str:
        return " ".join((text or "").strip().lower().split())

    def _find_entry_after_update(
        self, event: "Event"
    ) -> Optional[FreqEntry]:
        """Locate an entry in the freshly reloaded tree that corresponds to
        the target of an event. Tries, in order:
        1. Stable target_id match (same system_id/group_id/identity).
        2. Baseline snapshot: entry_type + normalized system/group name +
           identity_value.
        3. Event payload snapshot: same fields.
        """
        hit = self._find_entry_by_id(event.target_id or "")
        if hit is not None:
            return hit

        def _match_from_snap(snap: Dict[str, Any]) -> Optional[FreqEntry]:
            if not snap:
                return None
            et = (snap.get("entry_type") or "").upper()
            identity = str(snap.get("identity_value") or "")
            sys_name = self._replay_norm(snap.get("system_name", ""))
            grp_name = self._replay_norm(snap.get("group_name", ""))
            if not (et and identity and sys_name and grp_name):
                return None
            for sys_node in self.hpd.systems:
                if self._replay_norm(sys_node.name) != sys_name:
                    continue
                for group in sys_node.groups:
                    if self._replay_norm(group.name) != grp_name:
                        continue
                    for entry in group.entries:
                        if entry.entry_type.upper() != et:
                            continue
                        if entry.record.get_field(5, "") == identity:
                            return entry
            return None

        baseline = (
            self._meta.get_baseline(event.target_id)
            if self._meta is not None else None
        )
        if baseline is not None:
            hit = _match_from_snap(baseline.snapshot or {})
            if hit is not None:
                return hit

        hit = _match_from_snap((event.payload or {}).get("snapshot") or {})
        if hit is not None:
            return hit
        hit = _match_from_snap((event.payload or {}).get("after") or {})
        if hit is not None:
            return hit
        return None

    def _find_group_after_update(
        self, event: "Event"
    ) -> Optional[GroupNode]:
        hit = self._find_group_by_key(event.target_id or "")
        if hit is not None:
            return hit

        def _match(snap: Dict[str, Any]) -> Optional[GroupNode]:
            if not snap:
                return None
            sys_name = self._replay_norm(snap.get("system_name", ""))
            grp_name = self._replay_norm(snap.get("name", ""))
            if not (sys_name and grp_name):
                return None
            for sys_node in self.hpd.systems:
                if self._replay_norm(sys_node.name) != sys_name:
                    continue
                for group in sys_node.groups:
                    if self._replay_norm(group.name) == grp_name:
                        return group
            return None

        baseline = (
            self._meta.get_baseline(event.target_id)
            if self._meta is not None else None
        )
        if baseline is not None:
            hit = _match(baseline.snapshot or {})
            if hit is not None:
                return hit
        hit = _match((event.payload or {}).get("snapshot") or {})
        if hit is not None:
            return hit
        return None

    def _find_system_after_update(
        self, event: "Event"
    ) -> Optional[SystemNode]:
        hit = self._find_system_by_key(event.target_id or "")
        if hit is not None:
            return hit
        # Fallback by normalized system name from baseline or payload.
        name_candidates: List[str] = []
        if self._meta is not None:
            baseline = self._meta.get_baseline(event.target_id)
            if baseline is not None:
                name_candidates.append(baseline.snapshot.get("name", ""))
        payload = event.payload or {}
        for snap_key in ("snapshot", "before", "after"):
            snap = payload.get(snap_key) or {}
            name_candidates.append(snap.get("name", ""))
        for raw in name_candidates:
            norm = self._replay_norm(raw)
            if not norm:
                continue
            for sys_node in self.hpd.systems:
                if self._replay_norm(sys_node.name) == norm:
                    return sys_node
        return None

    def _find_group_for_reinsert(
        self, event: "Event"
    ) -> Optional[GroupNode]:
        """Locate the containing group when re-inserting an add_entry or
        re-creating a deleted entry/group child."""
        payload = event.payload or {}
        group_key = payload.get("group_key") or ""
        hit = self._find_group_by_key(group_key)
        if hit is not None:
            return hit
        snap = payload.get("snapshot") or {}
        sys_name = self._replay_norm(snap.get("system_name", ""))
        grp_name = self._replay_norm(snap.get("group_name", ""))
        if not (sys_name and grp_name):
            return None
        for sys_node in self.hpd.systems:
            if self._replay_norm(sys_node.name) != sys_name:
                continue
            for group in sys_node.groups:
                if self._replay_norm(group.name) == grp_name:
                    return group
        return None

    def _replay_events_after_update(self) -> Dict[str, int]:
        """Re-execute every non-reverted reversible event from the
        MetaStore against the freshly reloaded HPD tree.

        Uses raw ``self.hpd.*`` operations so no new events are written;
        we're re-enacting the existing change log, not appending to it.
        """
        report = {
            "replayed": 0,
            "missed": 0,
            "deletions": 0,
            "avoids": 0,
            "services": 0,
            "edits": 0,
            "additions": 0,
        }
        if self._meta is None or not self._meta.events:
            return report

        events = sorted(self._meta.events, key=lambda e: e.ts or "")

        for evt in events:
            if evt.reverted:
                continue
            try:
                ok = self._replay_single_event(evt, report)
            except Exception:
                ok = False
            if ok:
                report["replayed"] += 1
            else:
                report["missed"] += 1
        return report

    def _replay_single_event(
        self, evt: "Event", report: Dict[str, int]
    ) -> bool:
        op = evt.op
        payload = evt.payload or {}
        after = payload.get("after") or {}

        if op == OP_DELETE_ENTRY:
            entry = self._find_entry_after_update(evt)
            if entry is None:
                return True  # already gone — desired state achieved
            self.hpd.delete_entry(entry)
            report["deletions"] += 1
            return True

        if op == OP_DELETE_GROUP:
            group = self._find_group_after_update(evt)
            if group is None:
                return True
            self.hpd.delete_group(group)
            report["deletions"] += 1
            return True

        if op == OP_DELETE_SYSTEM:
            system = self._find_system_after_update(evt)
            if system is None:
                return True
            self.hpd.delete_system(system)
            report["deletions"] += 1
            return True

        if op == OP_SET_AVOID:
            entry = self._find_entry_after_update(evt)
            if entry is None:
                return False
            target_avoid = after.get("avoid") or "Off"
            current = entry.record.get_field(4, "Off")
            if current != target_avoid:
                entry.record.set_field(4, target_avoid)
                self.hpd.has_changes = True
            report["avoids"] += 1
            return True

        if op == OP_SET_SERVICE:
            entry = self._find_entry_after_update(evt)
            if entry is None:
                return False
            svc_raw = after.get("service_type")
            try:
                svc = int(svc_raw)
            except (TypeError, ValueError):
                return False
            if entry.service_type != svc:
                self.hpd.update_service_type(entry, svc)
            report["services"] += 1
            return True

        if op == OP_EDIT_ENTRY:
            entry = self._find_entry_after_update(evt)
            if entry is None:
                return False
            self.hpd.edit_entry(
                entry,
                name=after.get("name"),
                identity_value=(
                    str(after.get("identity_value"))
                    if after.get("identity_value") is not None else None
                ),
                mode=after.get("mode"),
                tone=after.get("tone"),
            )
            # Also reapply avoid + service_type captured in `after` so a
            # single edit event restores the full row.
            if "avoid" in after:
                entry.record.set_field(4, after.get("avoid") or "Off")
                self.hpd.has_changes = True
            if "service_type" in after:
                try:
                    svc = int(after.get("service_type"))
                    if entry.service_type != svc:
                        self.hpd.update_service_type(entry, svc)
                except (TypeError, ValueError):
                    pass
            report["edits"] += 1
            return True

        if op == OP_EDIT_GROUP:
            group = self._find_group_after_update(evt)
            if group is None:
                return False
            self.hpd.edit_group(
                group,
                name=after.get("name"),
                lat=after.get("lat"),
                lon=after.get("lon"),
                range_miles=after.get("range_miles"),
            )
            report["edits"] += 1
            return True

        if op == OP_EDIT_SYSTEM:
            system = self._find_system_after_update(evt)
            if system is None:
                return False
            self.hpd.edit_system(system, name=after.get("name"))
            report["edits"] += 1
            return True

        if op == OP_ADD_ENTRY:
            snap = payload.get("snapshot") or {}
            et = (snap.get("entry_type") or "").upper()
            identity = str(snap.get("identity_value") or "").strip()
            if not (et and identity):
                return False
            existing = self._find_entry_after_update(evt)
            if existing is not None:
                return True  # already present
            group = self._find_group_for_reinsert(evt)
            if group is None:
                return False
            try:
                if et == "C-FREQ":
                    entry = self.hpd.add_cfreq(
                        group=group,
                        name=snap.get("name") or "",
                        freq_hz=int(identity),
                        mode=snap.get("mode") or "NFM",
                        tone=snap.get("tone") or "",
                        service_type=int(snap.get("service_type") or 0),
                    )
                else:
                    entry = self.hpd.add_tgid(
                        group=group,
                        name=snap.get("name") or "",
                        tgid=int(identity),
                        mode=snap.get("mode") or "ALL",
                        service_type=int(snap.get("service_type") or 0),
                    )
                if snap.get("avoid"):
                    entry.record.set_field(4, snap.get("avoid"))
                    self.hpd.has_changes = True
            except Exception:
                return False
            report["additions"] += 1
            return True

        # Unhandled op types (OP_ADD_GROUP, OP_IMPORT_APPLY, etc.) — leave
        # for the snapshot-based safety-net pass.
        return False

    # --- event log recording ---

    def _log_event(
        self,
        *,
        op: str,
        target_id: str,
        target_name: str = "",
        payload: Optional[Dict[str, Any]] = None,
        summary: str = "",
        source: str = "manual",
        txn_id: Optional[str] = None,
    ) -> Optional[Event]:
        if self._meta is None:
            return None
        event = self._meta.record(
            op=op,
            target_id=target_id,
            target_name=target_name,
            payload=payload or {},
            summary=summary,
            source=source,
            txn_id=txn_id,
        )
        self._meta.flush()
        return event

    def _new_txn_id(self) -> Optional[str]:
        if self._meta is None:
            return None
        return self._meta.new_txn_id()

    # --- mutation wrappers ---

    def _do_edit_entry(
        self,
        entry: FreqEntry,
        *,
        name: Optional[str] = None,
        identity_value: Optional[str] = None,
        mode: Optional[str] = None,
        tone: Optional[str] = None,
        source: str = "manual",
        txn_id: Optional[str] = None,
        log: bool = True,
    ) -> None:
        before = self._entry_snapshot(entry)
        target_id = self._entry_id_for(entry)
        self.hpd.edit_entry(
            entry, name=name, identity_value=identity_value, mode=mode, tone=tone
        )
        after = self._entry_snapshot(entry)
        # Entry id may have changed if identity_value was edited; use the new id.
        new_target_id = self._entry_id_for(entry)
        if not log:
            return
        summary = self._diff_summary(before, after)
        self._log_event(
            op=OP_EDIT_ENTRY,
            target_id=new_target_id,
            target_name=entry.name,
            summary=summary or "Edited entry",
            source=source,
            txn_id=txn_id,
            payload={
                "before": before,
                "after": after,
                "prev_target_id": target_id if target_id != new_target_id else None,
            },
        )

    def _do_edit_group(
        self,
        group: GroupNode,
        *,
        name: Optional[str] = None,
        lat: Optional[float] = None,
        lon: Optional[float] = None,
        range_miles: Optional[float] = None,
        source: str = "manual",
        txn_id: Optional[str] = None,
        log: bool = True,
    ) -> None:
        before = self._group_snapshot(group)
        self.hpd.edit_group(
            group, name=name, lat=lat, lon=lon, range_miles=range_miles
        )
        after = self._group_snapshot(group)
        if not log:
            return
        self._log_event(
            op=OP_EDIT_GROUP,
            target_id=self._group_key_for(group),
            target_name=group.name,
            summary=self._diff_summary(before, after) or "Edited group",
            source=source,
            txn_id=txn_id,
            payload={"before": before, "after": after},
        )

    def _do_set_service(
        self,
        entry: FreqEntry,
        new_type: int,
        *,
        source: str = "manual",
        txn_id: Optional[str] = None,
        log: bool = True,
    ) -> bool:
        if entry.service_type == new_type:
            return False
        before_stype = entry.service_type
        self.hpd.update_service_type(entry, new_type)
        if not log:
            return True
        self._log_event(
            op=OP_SET_SERVICE,
            target_id=self._entry_id_for(entry),
            target_name=entry.name,
            summary=f"Service type {before_stype} -> {new_type}",
            source=source,
            txn_id=txn_id,
            payload={
                "before": {"service_type": before_stype},
                "after": {"service_type": new_type},
            },
        )
        return True

    def _do_set_avoid(
        self,
        entry: FreqEntry,
        new_avoid: str,
        *,
        source: str = "manual",
        txn_id: Optional[str] = None,
        log: bool = True,
    ) -> bool:
        before = entry.record.get_field(4, "Off")
        if before == new_avoid:
            return False
        entry.record.set_field(4, new_avoid)
        self.hpd.has_changes = True
        if not log:
            return True
        self._log_event(
            op=OP_SET_AVOID,
            target_id=self._entry_id_for(entry),
            target_name=entry.name,
            summary=f"Avoid {before} -> {new_avoid}",
            source=source,
            txn_id=txn_id,
            payload={"before": {"avoid": before}, "after": {"avoid": new_avoid}},
        )
        return True

    def _do_add_cfreq(
        self,
        group: GroupNode,
        name: str,
        freq_hz: int,
        mode: str,
        tone: str,
        service_type: int,
        *,
        source: str = "manual",
        txn_id: Optional[str] = None,
        log: bool = True,
    ) -> FreqEntry:
        entry = self.hpd.add_cfreq(group, name, freq_hz, mode, tone, service_type)
        self._log_add_entry(entry, group, source=source, txn_id=txn_id, log=log)
        return entry

    def _do_add_tgid(
        self,
        group: GroupNode,
        name: str,
        tgid: int,
        mode: str,
        service_type: int,
        *,
        source: str = "manual",
        txn_id: Optional[str] = None,
        log: bool = True,
    ) -> FreqEntry:
        entry = self.hpd.add_tgid(group, name, tgid, mode, service_type)
        self._log_add_entry(entry, group, source=source, txn_id=txn_id, log=log)
        return entry

    def _log_add_entry(
        self,
        entry: FreqEntry,
        group: GroupNode,
        *,
        source: str = "manual",
        txn_id: Optional[str] = None,
        log: bool = True,
    ) -> None:
        target_id = self._entry_id_for(entry)
        if self._meta is not None:
            # Baseline ensures revert of a later edit finds the starting
            # shape; we keep this even when `log=False` (composite-import
            # flow) so per-entry reverts still work after a future edit.
            if not self._meta.has_baseline(target_id):
                self._meta.ensure_baseline(
                    target_id,
                    origin="manual_add",
                    snapshot=self._entry_snapshot(entry),
                    record_fields=list(entry.record.fields),
                    group_ref={
                        "system_id": entry.system_id,
                        "group_id": entry.group_id,
                        "group_name": entry.group_name,
                        "system_name": entry.system_name,
                        "group_type": entry.group_type,
                        "entry_type": entry.entry_type,
                    },
                )
        if not log:
            return
        self._log_event(
            op=OP_ADD_ENTRY,
            target_id=target_id,
            target_name=entry.name,
            summary=f"Added {entry.entry_type} {entry.name}",
            source=source,
            txn_id=txn_id,
            payload={
                "snapshot": self._entry_snapshot(entry),
                "record_fields": list(entry.record.fields),
                "group_key": self._group_key_for(group),
            },
        )

    def _do_add_cgroup(
        self,
        system: SystemNode,
        name: str,
        lat: Optional[float] = None,
        lon: Optional[float] = None,
        range_miles: Optional[float] = None,
        *,
        source: str = "manual",
        txn_id: Optional[str] = None,
        log: bool = True,
    ) -> GroupNode:
        group = self.hpd.add_cgroup(system, name, lat=lat, lon=lon, range_miles=range_miles)
        self._log_add_group(group, system, source=source, txn_id=txn_id, log=log)
        return group

    def _do_add_tgroup(
        self,
        system: SystemNode,
        name: str,
        lat: Optional[float] = None,
        lon: Optional[float] = None,
        range_miles: Optional[float] = None,
        *,
        source: str = "manual",
        txn_id: Optional[str] = None,
        log: bool = True,
    ) -> GroupNode:
        group = self.hpd.add_tgroup(system, name, lat=lat, lon=lon, range_miles=range_miles)
        self._log_add_group(group, system, source=source, txn_id=txn_id, log=log)
        return group

    def _log_add_group(
        self,
        group: GroupNode,
        system: SystemNode,
        *,
        source: str = "manual",
        txn_id: Optional[str] = None,
        log: bool = True,
    ) -> None:
        gid = self._group_key_for(group)
        if self._meta is not None and not self._meta.has_baseline(gid):
            self._meta.ensure_baseline(
                gid,
                origin="manual_add",
                snapshot=self._group_snapshot(group),
                record_fields=list(group.record.fields),
                group_ref={
                    "system_id": system.system_id,
                    "system_name": system.name,
                    "group_type": group.group_type,
                },
            )
        if not log:
            return
        self._log_event(
            op=OP_ADD_GROUP,
            target_id=gid,
            target_name=group.name,
            summary=f"Added {group.group_type} {group.name}",
            source=source,
            txn_id=txn_id,
            payload={
                "snapshot": self._group_snapshot(group),
                "record_fields": list(group.record.fields),
                "system_key": self._system_key_for(system),
            },
        )

    def _do_delete_entry(
        self,
        entry: FreqEntry,
        *,
        source: str = "manual",
        txn_id: Optional[str] = None,
        log: bool = True,
    ) -> None:
        eid = self._entry_id_for(entry)
        name = entry.name
        record_fields = list(entry.record.fields)
        snapshot = self._entry_snapshot(entry)
        group_key = None
        for sys_node in self.hpd.systems:
            for group in sys_node.groups:
                if entry in group.entries:
                    group_key = self._group_key_for(group)
                    break
            if group_key:
                break
        self.hpd.delete_entry(entry)
        if not log:
            return
        self._log_event(
            op=OP_DELETE_ENTRY,
            target_id=eid,
            target_name=name,
            summary=f"Deleted entry {name}",
            source=source,
            txn_id=txn_id,
            payload={
                "snapshot": snapshot,
                "record_fields": record_fields,
                "group_key": group_key,
            },
        )

    def _do_edit_system(
        self,
        system: SystemNode,
        *,
        name: Optional[str] = None,
        source: str = "manual",
        txn_id: Optional[str] = None,
        log: bool = True,
    ) -> None:
        before = self._system_snapshot(system)
        self.hpd.edit_system(system, name=name)
        after = self._system_snapshot(system)
        if not log:
            return
        summary = self._diff_summary(before, after) or "Edited system"
        self._log_event(
            op=OP_EDIT_SYSTEM,
            target_id=self._system_key_for(system),
            target_name=system.name,
            summary=summary,
            source=source,
            txn_id=txn_id,
            payload={"before": before, "after": after},
        )

    def _do_delete_system(
        self,
        system: SystemNode,
        *,
        source: str = "manual",
        txn_id: Optional[str] = None,
        log: bool = True,
    ) -> None:
        """Cascading delete of a system with full revert payload."""
        sys_key = self._system_key_for(system)
        name = system.name
        group_count = len(system.groups)
        entry_count = sum(len(g.entries) for g in system.groups)
        snapshot = self._system_snapshot(system)
        raw_payload = self.hpd.delete_system(system)
        if not log:
            return
        self._log_event(
            op=OP_DELETE_SYSTEM,
            target_id=sys_key,
            target_name=name,
            summary=(
                f"Deleted system {name} "
                f"({group_count} group(s), {entry_count} entries)"
            ),
            source=source,
            txn_id=txn_id,
            payload={
                "snapshot": snapshot,
                "group_count": group_count,
                "entry_count": entry_count,
                "system_blob": raw_payload,
            },
        )

    def _do_delete_group(
        self,
        group: GroupNode,
        *,
        source: str = "manual",
        txn_id: Optional[str] = None,
        log: bool = True,
    ) -> None:
        gid = self._group_key_for(group)
        name = group.name
        system_key = None
        for sys_node in self.hpd.systems:
            if group in sys_node.groups:
                system_key = self._system_key_for(sys_node)
                break
        group_record_fields = list(group.record.fields)
        child_payloads = [
            {
                "target_id": self._entry_id_for(e),
                "record_fields": list(e.record.fields),
                "snapshot": self._entry_snapshot(e),
                "entry_type": e.entry_type,
                "name": e.name,
            }
            for e in group.entries
        ]
        snapshot = self._group_snapshot(group)
        self.hpd.delete_group(group)
        if not log:
            return
        self._log_event(
            op=OP_DELETE_GROUP,
            target_id=gid,
            target_name=name,
            summary=f"Deleted group {name} with {len(child_payloads)} entries",
            source=source,
            txn_id=txn_id,
            payload={
                "snapshot": snapshot,
                "record_fields": group_record_fields,
                "system_key": system_key,
                "children": child_payloads,
            },
        )

    def _record_callsign_ref(
        self,
        freq: Dict[str, Any],
        entry: FreqEntry,
        *,
        source_url: str = "",
    ) -> None:
        """Persist FCC callsign/licensee metadata for an imported entry."""
        if self._meta is None:
            return
        callsign = (freq.get("fcc_callsign") or "").strip().upper()
        licensee = (freq.get("licensee") or freq.get("licensee_text") or "").strip()
        if not callsign and not licensee and not source_url:
            return
        eid = self._entry_id_for(entry)
        self._meta.set_ref(
            eid,
            fcc_callsign=callsign or None,
            licensee=licensee or None,
            source_url=source_url or None,
            name=entry.name,
        )
        if callsign:
            self._global_meta.index_callsign(callsign, eid)
        if licensee:
            self._global_meta.index_licensee(licensee, eid)

    @staticmethod
    def _diff_summary(before: Dict[str, Any], after: Dict[str, Any]) -> str:
        parts: List[str] = []
        for key in before:
            if key in after and before[key] != after[key]:
                b = before[key]
                a = after[key]
                parts.append(f"{key}: {b!r} -> {a!r}")
        return "; ".join(parts)

    # ---- Cross-reference lookup (Phase B) ---------------------------------

    def _entry_for_id(self, entry_id: str) -> Tuple[Optional[FreqEntry], str]:
        """Return (entry, group_name) for a stored entry_id, or (None, "")."""
        entry = self._find_entry_by_id(entry_id)
        if entry is None:
            return (None, "")
        for sys_node in self.hpd.systems:
            for group in sys_node.groups:
                if entry in group.entries:
                    return (entry, group.name)
        return (entry, "")

    def crossref_hint_for_rr_row(
        self,
        rr_row: Dict[str, Any],
        *,
        fallback_name: str = "",
        fuzzy_threshold: float = 0.85,
    ) -> Optional[Dict[str, Any]]:
        """Look up an RR row (freq/talkgroup) against the GlobalMetaStore indexes.

        Returns a hint dict when a confident cross-reference is found,
        else None. Callsign hits are authoritative; fuzzy licensee hits
        require fallback_name/licensee and clear the threshold.

        Shape:
          {
            "kind": "callsign" | "fuzzy",
            "score": float,
            "label": str,
            "entry_ids": List[str],
            "matched_entry": Optional[FreqEntry],
            "matched_group": str,
          }
        """
        gm = getattr(self, "_global_meta", None)
        if gm is None:
            return None

        callsign = (rr_row.get("fcc_callsign") or "").strip().upper()
        if callsign:
            ids = gm.callsign_lookup(callsign)
            if ids:
                entry, group_name = self._entry_for_id(ids[0])
                matched = entry.name if entry else ""
                label = f"CS {callsign}"
                if matched:
                    label = f"{label} -> {matched}"
                return {
                    "kind": "callsign",
                    "score": 1.0,
                    "label": label,
                    "entry_ids": list(ids),
                    "matched_entry": entry,
                    "matched_group": group_name,
                }

        licensee = (rr_row.get("licensee") or rr_row.get("licensee_text") or "").strip()
        if not licensee:
            licensee = (fallback_name or "").strip()
        if licensee:
            candidates = gm.fuzzy_licensee_candidates(licensee, min_score=fuzzy_threshold)
            if candidates:
                key, score, ids = candidates[0]
                entry: Optional[FreqEntry] = None
                group_name = ""
                if ids:
                    entry, group_name = self._entry_for_id(ids[0])
                pct = int(round(score * 100))
                label = f"~{pct}% {key}"
                if entry is not None:
                    label = f"{label} -> {entry.name}"
                return {
                    "kind": "fuzzy",
                    "score": score,
                    "label": label,
                    "entry_ids": list(ids),
                    "matched_entry": entry,
                    "matched_group": group_name,
                }
        return None

    # ---- Revert engine ----------------------------------------------------

    def _apply_entry_snapshot(self, entry: FreqEntry, snap: Dict[str, Any]) -> None:
        rec = entry.record
        if "name" in snap:
            rec.set_field(3, str(snap["name"] or ""))
            entry.name = str(snap["name"] or "")
        if "avoid" in snap:
            rec.set_field(4, str(snap["avoid"] or "Off"))
        if "identity_value" in snap:
            rec.set_field(5, str(snap["identity_value"] or ""))
        if "mode" in snap:
            rec.set_field(6, str(snap["mode"] or ""))
        if entry.entry_type == "C-Freq" and "tone" in snap:
            rec.set_field(7, str(snap.get("tone") or ""))
        if "service_type" in snap:
            try:
                self.hpd.update_service_type(entry, int(snap["service_type"]))
            except (ValueError, TypeError):
                pass
        self.hpd.has_changes = True

    def _apply_group_snapshot(self, group: GroupNode, snap: Dict[str, Any]) -> None:
        changes: Dict[str, Any] = {}
        if "name" in snap:
            changes["name"] = snap["name"]
        if "lat" in snap:
            changes["lat"] = snap["lat"]
        if "lon" in snap:
            changes["lon"] = snap["lon"]
        if "range_miles" in snap:
            changes["range_miles"] = snap["range_miles"]
        self.hpd.edit_group(
            group,
            name=changes.get("name"),
            lat=changes.get("lat"),
            lon=changes.get("lon"),
            range_miles=changes.get("range_miles"),
        )

    def _reinsert_entry_from_payload(self, payload: Dict[str, Any]) -> bool:
        group = self._find_group_by_key(payload.get("group_key") or "")
        if group is None:
            return False
        snap = payload.get("snapshot") or {}
        try:
            if snap.get("entry_type") == "C-Freq":
                freq_hz = int(str(snap.get("identity_value") or "0"))
                entry = self.hpd.add_cfreq(
                    group,
                    name=str(snap.get("name") or ""),
                    freq_hz=freq_hz,
                    mode=str(snap.get("mode") or "NFM"),
                    tone=str(snap.get("tone") or ""),
                    service_type=int(snap.get("service_type") or 14),
                )
            else:
                tgid_val = int(str(snap.get("identity_value") or "0"))
                entry = self.hpd.add_tgid(
                    group,
                    name=str(snap.get("name") or ""),
                    tgid=tgid_val,
                    mode=str(snap.get("mode") or "ALL"),
                    service_type=int(snap.get("service_type") or 1),
                )
            entry.record.set_field(4, str(snap.get("avoid") or "Off"))
            self.hpd.has_changes = True
        except Exception:
            return False
        return True

    def _reinsert_group_from_payload(self, payload: Dict[str, Any]) -> Optional[GroupNode]:
        system = self._find_system_by_key(payload.get("system_key") or "")
        if system is None:
            return None
        snap = payload.get("snapshot") or {}
        try:
            if snap.get("group_type") == "C-Group":
                group = self.hpd.add_cgroup(
                    system,
                    name=str(snap.get("name") or ""),
                    lat=snap.get("lat"),
                    lon=snap.get("lon"),
                    range_miles=snap.get("range_miles"),
                )
            else:
                group = self.hpd.add_tgroup(
                    system,
                    name=str(snap.get("name") or ""),
                    lat=snap.get("lat"),
                    lon=snap.get("lon"),
                    range_miles=snap.get("range_miles"),
                )
        except Exception:
            return None
        for child in payload.get("children") or []:
            child_group_key = self._group_key_for(group)
            child_payload = dict(child)
            child_payload["group_key"] = child_group_key
            # Ensure child snapshot has updated group_id since the new group has id=0.
            snap_child = dict(child.get("snapshot") or {})
            snap_child["group_id"] = group.group_id
            child_payload["snapshot"] = snap_child
            self._reinsert_entry_from_payload(child_payload)
        return group

    def revert_event(
        self,
        event: Event,
        *,
        force: bool = False,
        cascade_txn: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """Apply the inverse of `event`.

        Returns (success, message). When `force=False`, bails out if later
        active events touch the same target and the caller hasn't chosen
        a resolution.
        """
        if self._meta is None:
            return False, "No metastore attached."
        if event.reverted:
            return False, "This change has already been reverted."
        if event.op == OP_REVERT or event.op == OP_BULK_REVERT:
            return False, "Cannot revert a revert event. Find the original change instead."
        if not force:
            later = self._meta.later_active_events_on(event.event_id)
            if later:
                summary = ", ".join(f"#{e.event_id}" for e in later[:5])
                return False, f"Later changes touch this target ({summary}). Use cascade or force."

        op = event.op
        payload = event.payload or {}
        msg = ""
        ok = False
        try:
            if op == OP_EDIT_ENTRY:
                target = self._find_entry_by_id(event.target_id)
                if target is None:
                    prev = payload.get("prev_target_id")
                    if prev:
                        target = self._find_entry_by_id(prev)
                if target is None:
                    msg = "Could not find the entry to revert."
                else:
                    self._apply_entry_snapshot(target, payload.get("before") or {})
                    ok = True
                    msg = f"Reverted edit on {target.name}"
            elif op == OP_EDIT_GROUP:
                target = self._find_group_by_key(event.target_id)
                if target is None:
                    msg = "Could not find the group to revert."
                else:
                    self._apply_group_snapshot(target, payload.get("before") or {})
                    ok = True
                    msg = f"Reverted edit on group {target.name}"
            elif op == OP_EDIT_SYSTEM:
                target = self._find_system_by_key(event.target_id)
                if target is None:
                    msg = "Could not find the system to revert."
                else:
                    before = payload.get("before") or {}
                    prev_name = before.get("name")
                    if prev_name is not None:
                        self.hpd.edit_system(target, name=str(prev_name))
                    ok = True
                    msg = f"Reverted edit on system {target.name}"
            elif op == OP_DELETE_SYSTEM:
                blob = payload.get("system_blob") or {}
                restored = self.hpd.reinsert_system_from_payload(blob)
                if restored is not None:
                    ok = True
                    msg = (
                        f"Restored system {restored.name} with "
                        f"{len(restored.groups)} group(s) and "
                        f"{sum(len(g.entries) for g in restored.groups)} entries"
                    )
                else:
                    msg = "Could not restore deleted system."
            elif op == OP_SET_SERVICE:
                target = self._find_entry_by_id(event.target_id)
                if target is None:
                    msg = "Could not find the entry."
                else:
                    before = (payload.get("before") or {}).get("service_type")
                    if before is not None:
                        self.hpd.update_service_type(target, int(before))
                        ok = True
                        msg = f"Service type reverted on {target.name}"
            elif op == OP_SET_AVOID:
                target = self._find_entry_by_id(event.target_id)
                if target is None:
                    msg = "Could not find the entry."
                else:
                    before = (payload.get("before") or {}).get("avoid", "Off")
                    target.record.set_field(4, before)
                    self.hpd.has_changes = True
                    ok = True
                    msg = f"Avoid reverted on {target.name}"
            elif op == OP_ADD_ENTRY:
                target = self._find_entry_by_id(event.target_id)
                if target is None:
                    msg = "Entry no longer present (already deleted)."
                else:
                    self.hpd.delete_entry(target)
                    ok = True
                    msg = f"Removed added entry {event.target_name}"
            elif op == OP_ADD_GROUP:
                target = self._find_group_by_key(event.target_id)
                if target is None:
                    msg = "Group no longer present."
                else:
                    if target.entries:
                        msg = f"Group {target.name} now contains {len(target.entries)} entries; refusing to auto-delete."
                        ok = False
                    else:
                        self.hpd.delete_group(target)
                        ok = True
                        msg = f"Removed added group {event.target_name}"
            elif op == OP_DELETE_ENTRY:
                if self._reinsert_entry_from_payload(payload):
                    ok = True
                    msg = f"Restored deleted entry {event.target_name}"
                else:
                    msg = "Could not restore entry (group missing?)"
            elif op == OP_DELETE_GROUP:
                grp = self._reinsert_group_from_payload(payload)
                if grp is not None:
                    ok = True
                    msg = f"Restored deleted group {event.target_name} with {len(grp.entries)} entries"
                else:
                    msg = "Could not restore group (system missing?)"
            elif op == OP_IMPORT_APPLY:
                ok, msg = self._revert_import_apply(payload)
            elif op == OP_LINK_RR:
                self._meta.clear_group_link(event.target_id)
                ok = True
                msg = f"Unlinked {event.target_name}"
            elif op == OP_UNLINK_RR:
                link = payload.get("link") or {}
                if link.get("rr_url"):
                    self._meta.group_links[event.target_id] = dict(link)
                    self._meta.mark_dirty()
                    ok = True
                    msg = f"Restored RR link on {event.target_name}"
                else:
                    msg = "Original link info missing."
            else:
                msg = f"Don't know how to revert {op}."
        except Exception as exc:
            msg = f"Revert failed: {exc}"
            ok = False

        if ok:
            self._meta.mark_reverted(event.event_id)
            # Record a revert event so the revert itself is revertable.
            revert_txn = cascade_txn or self._new_txn_id()
            self._meta.record(
                op=OP_REVERT,
                target_id=event.target_id,
                target_name=event.target_name,
                summary=f"Reverted #{event.event_id}",
                source="manual",
                txn_id=revert_txn,
                payload={"target_event_id": event.event_id},
            )
            self._meta.flush()
        return ok, msg

    def _revert_import_apply(
        self, payload: Dict[str, Any]
    ) -> Tuple[bool, str]:
        removed = 0
        reverted = 0
        avoid_reverted = 0
        restored = 0
        failed = 0
        for add in payload.get("added") or []:
            target = self._find_entry_by_id(add.get("id") or "")
            if target is None:
                continue
            try:
                self.hpd.delete_entry(target)
                removed += 1
            except Exception:
                failed += 1
        for upd in payload.get("updated") or []:
            target = self._find_entry_by_id(upd.get("id") or "")
            if target is None:
                failed += 1
                continue
            try:
                self._apply_entry_snapshot(target, upd.get("before") or {})
                reverted += 1
            except Exception:
                failed += 1
        for av in payload.get("avoided") or []:
            target = self._find_entry_by_id(av.get("id") or "")
            if target is None:
                failed += 1
                continue
            try:
                before_avoid = (av.get("before") or {}).get("avoid", "Off")
                target.record.set_field(4, before_avoid)
                self.hpd.has_changes = True
                avoid_reverted += 1
            except Exception:
                failed += 1
        # Restore encrypted-delete actions by re-inserting into the group
        for dl in payload.get("deleted") or []:
            try:
                group = self._find_group_by_key(dl.get("group_key") or "")
                if group is None:
                    failed += 1
                    continue
                fields = list(dl.get("record_fields") or [])
                snap = dl.get("snapshot") or {}
                if not fields:
                    failed += 1
                    continue
                entry_type = snap.get("entry_type") or "TGID"
                if entry_type == "TGID":
                    try:
                        tgid_val = int(snap.get("identity_value") or 0)
                    except Exception:
                        tgid_val = 0
                    self.hpd.add_tgid(
                        group,
                        snap.get("name") or dl.get("name") or "",
                        tgid_val,
                        snap.get("mode") or "ALL",
                        int(snap.get("service_type") or 1),
                    )
                else:
                    try:
                        freq_hz = int(snap.get("identity_value") or 0)
                    except Exception:
                        freq_hz = 0
                    self.hpd.add_cfreq(
                        group,
                        snap.get("name") or dl.get("name") or "",
                        freq_hz,
                        snap.get("mode") or "NFM",
                        snap.get("tone") or "",
                        int(snap.get("service_type") or 14),
                    )
                restored += 1
            except Exception:
                failed += 1
        groups = payload.get("groups_created") or []
        group_removed = 0
        for gkey in groups:
            grp = self._find_group_by_key(gkey)
            if grp is not None and not grp.entries:
                try:
                    self.hpd.delete_group(grp)
                    group_removed += 1
                except Exception:
                    pass
        return True, (
            f"Reverted import: removed {removed} added, "
            f"reverted {reverted} updated, restored {restored} deleted, "
            f"un-avoided {avoid_reverted}, removed {group_removed} empty groups "
            f"(failures: {failed})"
        )

    def revert_cascade(self, event: Event) -> Tuple[bool, str]:
        """Revert this event + all later active events touching the same target.

        Reverts in reverse chronological order under one shared revert txn.
        """
        if self._meta is None:
            return False, "No metastore."
        later = self._meta.later_active_events_on(event.event_id)
        chain = list(reversed(later)) + [event]
        txn = self._new_txn_id()
        ok_count = 0
        fails: List[str] = []
        for ev in chain:
            ok, msg = self.revert_event(ev, force=True, cascade_txn=txn)
            if ok:
                ok_count += 1
            else:
                fails.append(f"#{ev.event_id}: {msg}")
        status = f"Reverted {ok_count}/{len(chain)} change(s)."
        if fails:
            status += " Issues: " + "; ".join(fails[:5])
        return ok_count > 0, status

    def revert_to_point(self, pivot_event_id: str) -> Tuple[bool, str]:
        """Revert every active event strictly after pivot_event_id, newest-first."""
        if self._meta is None:
            return False, "No metastore."
        seen_pivot = False
        newer: List[Event] = []
        for e in self._meta.events:
            if e.event_id == pivot_event_id:
                seen_pivot = True
                continue
            if not seen_pivot:
                continue
            if e.op in (OP_REVERT, OP_BULK_REVERT):
                continue
            if e.reverted:
                continue
            newer.append(e)
        if not newer:
            return False, "No later changes to revert."
        txn = self._new_txn_id()
        ok_count = 0
        fails: List[str] = []
        for ev in reversed(newer):
            ok, msg = self.revert_event(ev, force=True, cascade_txn=txn)
            if ok:
                ok_count += 1
            else:
                fails.append(f"#{ev.event_id}: {msg}")
        # Record the bulk revert marker
        self._meta.record(
            op=OP_BULK_REVERT,
            target_id="",
            target_name="Revert to point",
            summary=f"Reverted {ok_count} events after #{pivot_event_id}",
            source="manual",
            txn_id=txn,
            payload={"pivot_event_id": pivot_event_id, "reverted_count": ok_count},
        )
        self._meta.flush()
        status = f"Reverted {ok_count}/{len(newer)} change(s) after #{pivot_event_id}."
        if fails:
            status += " Issues: " + "; ".join(fails[:5])
        return ok_count > 0, status

    # ---- Tree Population --------------------------------------------------

    def _populate_tree(self):
        self.tree.delete(*self.tree.get_children())
        self._tree_id_map.clear()
        self._selected_entry = None
        self._selected_group = None

        apply_location = self._location_filter_enabled.get() and (
            self._active_county_id is not None or self._active_coords is not None
        )

        ordered_systems: List[Tuple[SystemNode, Optional[float]]] = []
        for sys_node in self.hpd.systems:
            if apply_location and not self._system_matches_location(sys_node):
                continue
            distance = None
            if self._active_coords is not None:
                distance = nearest_distance_miles(
                    sys_node, self._active_coords[0], self._active_coords[1]
                )
            ordered_systems.append((sys_node, distance))

        if apply_location and self._active_coords is not None:
            ordered_systems.sort(key=lambda item: (item[1] if item[1] is not None else float("inf")))

        ranking_on = apply_location and self._active_coords is not None
        for idx, (sys_node, distance) in enumerate(ordered_systems):
            sys_prefix = "CONV" if sys_node.system_type == "Conventional" else "TRUNK"
            rank_prefix = f"#{idx + 1} " if ranking_on else ""
            if apply_location:
                scope = self._system_scope_label(sys_node)
                if distance is not None:
                    sys_text = (
                        f"{rank_prefix}[{scope}][{sys_prefix}] "
                        f"{sys_node.name} ({distance:.1f} mi)"
                    )
                else:
                    sys_text = (
                        f"{rank_prefix}[{scope}][{sys_prefix}] {sys_node.name}"
                    )
            else:
                sys_text = f"[{sys_prefix}] {sys_node.name}"

            tolerance = self._coverage_tolerance_miles()
            visible_groups: List[Tuple[GroupNode, List[FreqEntry], Dict[str, Any]]] = []
            for g in sys_node.groups:
                entries = [e for e in g.entries if self._entry_passes_button_filter(e)]
                if not entries:
                    continue
                info = self._group_coverage_info(g, tolerance)
                if apply_location and self._active_coords is not None:
                    if info["status"] == "out_range":
                        continue
                visible_groups.append((g, entries, info))
            if not visible_groups:
                continue

            if ranking_on:
                visible_groups.sort(
                    key=lambda item: (
                        item[2]["distance"]
                        if item[2].get("distance") is not None
                        else float("inf")
                    )
                )

            sys_id = self.tree.insert(
                "", tk.END, text=sys_text, tags=("system",), open=False,
            )
            self._tree_id_map[sys_id] = sys_node

            for grp, entries_to_show, info in visible_groups:
                grp_text = grp.name
                if apply_location and self._active_coords is not None and info["has_geo"]:
                    if info["range_miles"] is not None:
                        grp_text = (
                            f"{grp.name}  "
                            f"[{info['distance']:.1f} mi / {info['range_miles']:.1f} mi range]"
                        )
                    else:
                        grp_text = f"{grp.name}  [{info['distance']:.1f} mi]"
                tag_name = "group"
                if apply_location and self._active_coords is not None:
                    tag_name = {
                        "in_range": "group_in_range",
                        "nearby": "group_nearby",
                        "out_range": "group_out_range",
                        "no_geo": "group_no_geo",
                    }.get(info["status"], "group")
                grp_id = self.tree.insert(
                    sys_id, tk.END, text=grp_text, tags=(tag_name,), open=False,
                )
                self._tree_id_map[grp_id] = grp

                for entry in entries_to_show:
                    self._insert_entry_item(grp_id, entry)

    def _group_coverage_info(self, group: GroupNode, tolerance: float) -> Dict[str, Any]:
        info: Dict[str, Any] = {
            "has_geo": False,
            "distance": None,
            "range_miles": group.range_miles,
            "status": "no_geo",
        }
        if self._active_coords is None:
            return info
        lat, lon = self._active_coords
        if group.rectangles and any(
            rectangle_contains_point(r, lat, lon) for r in group.rectangles
        ):
            info["has_geo"] = True
            info["status"] = "in_range"
            if group.lat is not None and group.lon is not None:
                info["distance"] = haversine_miles(lat, lon, group.lat, group.lon)
            else:
                info["distance"] = 0.0
            return info
        if group.lat is None or group.lon is None:
            return info
        info["has_geo"] = True
        d = haversine_miles(lat, lon, group.lat, group.lon)
        info["distance"] = d
        rng = group.range_miles or 0.0
        if rng > 0 and d <= rng:
            info["status"] = "in_range"
        elif rng > 0 and d <= rng + tolerance:
            info["status"] = "nearby"
        elif rng <= 0 and d <= tolerance:
            info["status"] = "nearby"
        else:
            info["status"] = "out_range"
        return info

    def _system_matches_location(self, sys_node: SystemNode) -> bool:
        tolerance = self._coverage_tolerance_miles()
        if self._active_coords is not None:
            covered, delta = system_covers_point(
                sys_node, self._active_coords[0], self._active_coords[1]
            )
            if covered:
                return True
            if system_has_geo(sys_node):
                if delta != float("inf") and delta <= tolerance:
                    return True
                return False
            if self._active_county_id and self._active_county_id in sys_node.county_ids:
                return True
            return not sys_node.county_ids and not sys_node.state_ids
        if self._active_county_id is None:
            return True
        if sys_node.county_ids:
            return self._active_county_id in sys_node.county_ids
        sid = self._get_selected_state_id()
        if sys_node.state_ids and sid is not None:
            return sid in sys_node.state_ids
        return True

    def _system_scope_label(self, sys_node: SystemNode) -> str:
        tolerance = self._coverage_tolerance_miles()
        if self._active_coords is not None:
            covered, delta = system_covers_point(
                sys_node, self._active_coords[0], self._active_coords[1]
            )
            if covered:
                return "COVERAGE"
            if system_has_geo(sys_node) and delta != float("inf") and delta <= tolerance:
                return "NEARBY"
        if self._active_county_id and self._active_county_id in sys_node.county_ids:
            return "LOCAL"
        if not sys_node.county_ids and sys_node.state_ids:
            return "STATEWIDE"
        if not sys_node.county_ids and not sys_node.state_ids:
            return "WIDE"
        return "OTHER"

    def _coverage_tolerance_miles(self) -> float:
        try:
            return max(0, int(self._coverage_tolerance_var.get()))
        except Exception:
            return 0

    def _active_button_types(self) -> Set[int]:
        active: Set[int] = set()
        if self._button_police.get():
            active.add(2)
        if self._button_fire.get():
            active.add(3)
        if self._button_ems.get():
            active.add(4)
        if self._button_dot.get():
            active.add(14)
        if self._button_multi.get():
            active.add(1)
        return active

    def _entry_passes_button_filter(self, entry: FreqEntry) -> bool:
        if not entry_passes_button_filter(
            entry.service_type,
            self._active_button_types(),
            bool(self._include_others.get()),
        ):
            return False
        if self._exclude_avoided.get() and entry.record.get_field(4, "Off") == "On":
            return False
        return True

    def _on_export_scan_set(self):
        if not self.hpd.systems:
            messagebox.showinfo("Export", "Load an HPD file first.")
            return
        target = filedialog.asksaveasfilename(
            title="Export Effective Scan Set",
            defaultextension=".csv",
            filetypes=[("CSV file", "*.csv"), ("Text file", "*.txt"), ("All Files", "*.*")],
        )
        if not target:
            return
        rows = list(self._iter_effective_scan_rows())
        columns = [
            "Scope", "System", "System Type", "Group", "Entry Type",
            "Name", "Identity Value", "Mode", "Tone", "Service Type",
            "Service Name", "Avoid", "Lat", "Lon", "Range (mi)",
            "Distance (mi)",
        ]
        fmt = "csv" if target.lower().endswith(".csv") else "txt"
        try:
            if fmt == "csv":
                import csv
                with open(target, "w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow(columns)
                    for row in rows:
                        writer.writerow(row)
            else:
                with open(target, "w", encoding="utf-8") as f:
                    f.write("\t".join(columns) + "\n")
                    for row in rows:
                        f.write("\t".join(str(v) for v in row) + "\n")
        except Exception as exc:
            messagebox.showerror("Export", f"Could not write file:\n{exc}")
            return
        self._set_status(f"Exported {len(rows)} entries to {os.path.basename(target)}")

    def _iter_effective_scan_rows(self):
        apply_location = self._location_filter_enabled.get() and (
            self._active_county_id is not None or self._active_coords is not None
        )
        for sys_node in self.hpd.systems:
            if apply_location and not self._system_matches_location(sys_node):
                continue
            scope = self._system_scope_label(sys_node) if apply_location else ""
            sys_distance = ""
            if self._active_coords is not None:
                d = nearest_distance_miles(sys_node, self._active_coords[0], self._active_coords[1])
                if d is not None:
                    sys_distance = f"{d:.2f}"
            for group in sys_node.groups:
                # Group-level coverage info (distance/range) comes from the
                # same helper the tree uses, so the CSV mirrors on-screen
                # ranges rather than just system-nearest distance.
                info = self._group_coverage_info(
                    group, self._coverage_tolerance_miles()
                )
                if apply_location and self._active_coords is not None:
                    if info["status"] == "out_range":
                        continue
                distance_mi = sys_distance
                if info.get("distance") is not None:
                    distance_mi = f"{info['distance']:.2f}"
                lat_s = "" if group.lat is None else f"{group.lat:.6f}"
                lon_s = "" if group.lon is None else f"{group.lon:.6f}"
                range_s = "" if not group.range_miles else f"{group.range_miles:.2f}"
                for entry in group.entries:
                    if not self._entry_passes_button_filter(entry):
                        continue
                    rec = entry.record
                    if entry.entry_type == "C-Freq":
                        freq_hz = HpdFile._parse_int(rec.get_field(5, "0"))
                        identity = f"{freq_hz / 1_000_000:.4f} MHz" if freq_hz else ""
                        tone = rec.get_field(7, "")
                    elif entry.entry_type == "TGID":
                        identity = f"TGID {rec.get_field(5, '')}"
                        tone = ""
                    else:
                        identity = ""
                        tone = ""
                    mode = rec.get_field(6, "")
                    avoid = rec.get_field(4, "Off")
                    service_name = SERVICE_TYPES.get(
                        entry.service_type, f"Type {entry.service_type}"
                    )
                    yield (
                        scope,
                        sys_node.name,
                        sys_node.system_type,
                        group.name,
                        entry.entry_type,
                        entry.name,
                        identity,
                        mode,
                        tone,
                        entry.service_type,
                        service_name,
                        avoid,
                        lat_s,
                        lon_s,
                        range_s,
                        distance_mi,
                    )

    def _insert_entry_item(self, parent_id: str, entry: FreqEntry) -> str:
        rec = entry.record
        tag = "scannable" if is_scannable(entry.service_type) else "nonscannable"

        if entry.entry_type == "C-Freq":
            freq_hz = HpdFile._parse_int(rec.get_field(5, "0"))
            freq_display = format_freq(freq_hz)
            mode = rec.get_field(6, "")
        elif entry.entry_type == "TGID":
            tgid_val = rec.get_field(5, "")
            freq_display = f"TGID {tgid_val}"
            mode = tgid_mode_label(rec.get_field(6, ""))
        else:
            freq_display = ""
            mode = ""

        svc = service_label(entry.service_type)

        item_id = self.tree.insert(
            parent_id, tk.END, text=entry.name,
            values=(freq_display, mode, svc),
            tags=(tag,),
        )
        self._tree_id_map[item_id] = entry
        return item_id

    def _add_entry_to_tree(self, group: GroupNode, entry: FreqEntry):
        for tree_id, obj in self._tree_id_map.items():
            if obj is group:
                item_id = self._insert_entry_item(tree_id, entry)
                self.tree.see(item_id)
                self.tree.selection_set(item_id)
                break

    def _refresh_entry_in_tree(self, entry: FreqEntry):
        for tree_id, obj in self._tree_id_map.items():
            if obj is entry:
                rec = entry.record
                tag = "scannable" if is_scannable(entry.service_type) else "nonscannable"

                if entry.entry_type == "C-Freq":
                    freq_hz = HpdFile._parse_int(rec.get_field(5, "0"))
                    freq_display = format_freq(freq_hz)
                    mode = rec.get_field(6, "")
                elif entry.entry_type == "TGID":
                    freq_display = f"TGID {rec.get_field(5, '')}"
                    mode = tgid_mode_label(rec.get_field(6, ""))
                else:
                    freq_display = ""
                    mode = ""

                svc = service_label(entry.service_type)
                self.tree.item(tree_id, values=(freq_display, mode, svc), tags=(tag,))
                break

    # ---- Details Display --------------------------------------------------

    def _show_entry_details(self, entry: FreqEntry):
        rec = entry.record
        self._detail_labels["type"].config(text=entry.entry_type)
        self._detail_labels["name"].config(text=entry.name)

        if entry.entry_type == "C-Freq":
            freq_hz = HpdFile._parse_int(rec.get_field(5, "0"))
            self._detail_labels["freq"].config(text=format_freq(freq_hz))
            self._detail_labels["mode"].config(text=rec.get_field(6, "—"))
            self._detail_labels["tone"].config(text=rec.get_field(7, "—") or "—")
        elif entry.entry_type == "TGID":
            self._detail_labels["freq"].config(text=f"TGID {rec.get_field(5, '')}")
            raw_mode = rec.get_field(6, "")
            self._detail_labels["mode"].config(text=tgid_mode_label(raw_mode) if raw_mode else "—")
            self._detail_labels["tone"].config(text="—")

        self._detail_labels["service"].config(text=service_label(entry.service_type))
        self._detail_labels["avoid"].config(text=rec.get_field(4, "Off"))

        group_name = "—"
        for sys_node in self.hpd.systems:
            for grp in sys_node.groups:
                if entry in grp.entries:
                    group_name = grp.name
                    break
        self._detail_labels["group"].config(text=group_name)

        for i, (code, _label) in enumerate(SERVICE_CHOICES):
            if code == entry.service_type:
                self._edit_stype_combo.current(i)
                break

    def _show_group_details(self, group: GroupNode):
        self._detail_labels["type"].config(text=group.group_type)
        self._detail_labels["name"].config(text=group.name)
        self._detail_labels["freq"].config(text=f"{len(group.entries)} entries")
        self._detail_labels["mode"].config(text="—")
        self._detail_labels["tone"].config(text="—")
        self._detail_labels["service"].config(text="—")
        self._detail_labels["avoid"].config(text="—")
        self._detail_labels["group"].config(text="—")

    def _show_system_details(self, sys_node: SystemNode):
        total = sum(len(g.entries) for g in sys_node.groups)
        self._detail_labels["type"].config(text=sys_node.system_type)
        self._detail_labels["name"].config(text=sys_node.name)
        self._detail_labels["freq"].config(text=f"{len(sys_node.groups)} groups, {total} entries")
        self._detail_labels["mode"].config(text="—")
        self._detail_labels["tone"].config(text="—")
        self._detail_labels["service"].config(text="—")
        self._detail_labels["avoid"].config(text="—")
        self._detail_labels["group"].config(text="—")

    def _clear_details_panel(self) -> None:
        """Blank the detail labels. Used after reverts that may delete the
        currently-selected row."""
        for key in ("type", "name", "freq", "mode", "tone", "service", "avoid", "group"):
            lbl = self._detail_labels.get(key)
            if lbl is not None:
                lbl.config(text="—")

    def _refresh_ui_after_mutation(self, status_msg: Optional[str] = None) -> None:
        """Rebuild the main tree + detail panel after an operation that may
        have added/removed rows (revert, bulk import, restore). The previous
        selection references may now be stale, so we drop them."""
        self._selected_entry = None
        self._selected_group = None
        self._populate_tree()
        self._clear_details_panel()
        if status_msg is not None:
            self._set_status(status_msg)

    # ---- Helpers ----------------------------------------------------------

    def _set_status(self, msg: str):
        self._status_var.set(msg)

    def _sd_space_root(self) -> Optional[Path]:
        folder = (self._path_var.get() or "").strip()
        if not folder:
            folder = self._app_settings.get("sd_path", "") or ""
        if not folder:
            return None
        p = Path(folder)
        if not p.exists():
            return None
        while p != p.parent and not p.anchor.rstrip("\\/") == str(p).rstrip("\\/"):
            p = p.parent
        try:
            p.resolve()
            return p
        except Exception:
            return None

    def _refresh_sd_space(self):
        root = self._sd_space_root()
        if root is None:
            self._sd_space_var.set("")
            self._refresh_card_state()
            return
        try:
            usage = shutil.disk_usage(str(root))
        except Exception:
            self._sd_space_var.set("")
            self._refresh_card_state()
            return
        free_gb = usage.free / (1024 ** 3)
        total_gb = usage.total / (1024 ** 3)
        used_pct = (1.0 - usage.free / usage.total) * 100 if usage.total else 0
        self._sd_space_var.set(
            f"SD {root}: {free_gb:.1f} / {total_gb:.1f} GB free ({used_pct:.0f}% used)"
        )
        self._refresh_card_state()

    def _refresh_card_state(self) -> None:
        """Update the card-state label to reflect workspace vs physical
        card status."""
        profile = self._active_profile()
        folder = (self._path_var.get() or "").strip()
        if profile is None:
            if folder and os.path.isdir(folder):
                ident = sdcard.probe_card_identity(folder)
                if ident.has_any_id():
                    self._card_state_var.set(
                        f"Card: connected ({ident.target_model or 'unknown'})"
                    )
                else:
                    self._card_state_var.set("Card: folder loaded")
            else:
                self._card_state_var.set("")
            return
        name = profile.get("name") or "workspace"
        ws_dir = profile.get("workspace_dir") or ""
        # Does the current path point at a physical card matching this
        # profile? Try detection.
        card_match = False
        if folder and os.path.isdir(folder) and folder != ws_dir:
            ident = sdcard.probe_card_identity(folder)
            card_match = bool(
                (ident.volume_serial and ident.volume_serial == profile.get("card_volume_serial"))
                or (ident.content_fingerprint and ident.content_fingerprint == profile.get("content_fingerprint"))
            )
        pending = 0
        if self._meta is not None:
            pending = len(self._meta.uncommitted_events())
        bits = [f"Workspace: {name}"]
        if card_match:
            bits.append("card connected")
        else:
            bits.append("card detached")
        if pending:
            bits.append(f"{pending} pending")
        self._card_state_var.set(" · ".join(bits))
        self._refresh_pipeline_health()

    def _refresh_pipeline_health(self) -> None:
        """Recompute the pipeline-health pill from the snapshot helper."""
        try:
            snap = self._pipeline_health_snapshot()
        except Exception:
            return
        health = snap.get("health", "amber")
        label = getattr(self, "_pipeline_health_label", None)
        if label is None:
            return
        color = {"green": "#2a6", "amber": "#b80", "red": "#b33"}.get(
            health, "#666"
        )
        self._pipeline_health_var.set(f"Pipeline: {health}")
        try:
            label.configure(background=color)
        except Exception:
            pass

    def _write_reconcile_audit(
        self,
        hpd_path: str,
        snapshot: List[EntryCustomization],
        report: Dict[str, int],
    ) -> Path:
        audit_dir = Path(hpd_path).parent
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        audit_path = audit_dir / f"{Path(hpd_path).name}.reconcile_{ts}.log"
        lines: List[str] = []
        lines.append(f"Reconcile audit for {hpd_path}")
        lines.append(f"Timestamp: {datetime.now().isoformat(timespec='seconds')}")
        lines.append(f"Report: reapplied={report.get('reapplied', 0)} "
                     f"inserted={report.get('inserted', 0)} "
                     f"unresolved={report.get('unresolved', 0)}")
        lines.append(f"Customizations considered: {len(snapshot)}")
        lines.append("")
        lines.append("Customization details (entry_type, system, group, identity, service, avoid, user_added):")
        for c in snapshot:
            lines.append(
                f"- {c.entry_type}\t{c.system_name}\t{c.group_name}\t{c.identity_value}\t"
                f"svc={c.service_type}\tavoid={c.avoid}\tuser_added={c.is_user_added}"
            )
        try:
            audit_path.write_text("\n".join(lines), encoding="utf-8")
        except Exception:
            pass
        return audit_path

    def _on_show_last_audit(self):
        if not self._last_reconcile_audit or not self._last_reconcile_audit.exists():
            messagebox.showinfo("Audit", "No reconcile audit available. Run a reconcile first.")
            return
        try:
            content = self._last_reconcile_audit.read_text(encoding="utf-8")
        except Exception as e:
            messagebox.showerror("Audit", f"Could not read audit log:\n{e}")
            return
        self._show_text_dialog(f"Reconcile Audit - {self._last_reconcile_audit.name}", content)

    def _show_text_dialog(self, title: str, content: str):
        top = tk.Toplevel(self.root)
        top.title(title)
        top.geometry("720x500")
        text = tk.Text(top, wrap="none")
        text.insert("1.0", content)
        text.configure(state="disabled")
        text.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        ttk.Button(top, text="Close", command=top.destroy).pack(pady=(0, 8))

    def _on_show_changes(self):
        """Open the event-sourced Changes panel."""
        if self._meta is None or self.hpd.filepath is None:
            messagebox.showinfo(
                "Changes",
                "Load an HPD file first. Changes are tracked per file.",
            )
            return
        ChangesPanelDialog(self)

    def _on_restore_session_snapshot(self):
        """Restore the single .session.bak safety snapshot for the active HPD."""
        if not self.hpd.filepath:
            messagebox.showinfo("Restore Session", "No HPD file loaded.")
            return
        snap = session_snapshot_path(self.hpd.filepath)
        if not snap.exists():
            messagebox.showinfo(
                "Restore Session",
                "No session snapshot exists for this file. "
                "A session snapshot is created automatically when a file is loaded.",
            )
            return
        if not messagebox.askyesno(
            "Restore Session Snapshot",
            f"Replace the current file with the session snapshot from:\n"
            f"{snap}\n\n"
            "Unsaved changes in memory will also be lost.\n"
            "A new session snapshot will be created on next load.",
        ):
            return
        try:
            import shutil as _sh
            _sh.copy2(str(snap), self.hpd.filepath)
            self.hpd.load(self.hpd.filepath)
            self._attach_meta_for_hpd(self.hpd.filepath, is_restore=True)
            self._populate_tree()
            self._set_status(
                f"Restored {os.path.basename(self.hpd.filepath)} from session snapshot."
            )
            self._refresh_sd_space()
        except Exception as exc:
            messagebox.showerror("Restore Session", f"Restore failed:\n{exc}")

    def _on_view_discovery(self):
        DiscoveryViewerDialog(self)

    def _on_view_alerts(self):
        AlertsViewerDialog(self)

    def _on_coverage_heatmap(self):
        if not self.hpd.systems:
            messagebox.showinfo("Coverage Heatmap", "Load an HPD file first.")
            return
        CoverageHeatmapDialog(self)

    def _on_coverage_map(self):
        if not self.hpd.systems:
            messagebox.showinfo("Coverage Map", "Load an HPD file first.")
            return
        CoverageMapDialog(self)

    # -- Help menu handlers --------------------------------------------------

    def _on_help_wiki(self) -> None:
        webbrowser.open(APP_WIKI_URL)

    def _on_help_report_issue(self) -> None:
        title = urllib.parse.quote(f"[{APP_VERSION}] ")
        body = urllib.parse.quote(
            "### What happened?\n\n"
            "### Steps to reproduce\n\n"
            "### Expected behavior\n\n"
            "### Environment\n"
            f"- Scanner Manager: v{APP_VERSION}\n"
            f"- OS: {sys.platform}\n"
            f"- Python: {sys.version.split()[0]}\n"
        )
        webbrowser.open(
            f"{APP_ISSUES_URL}/new?title={title}&body={body}"
        )

    def _on_help_donate(self) -> None:
        DonateDialog(self)

    def _on_help_about(self) -> None:
        AboutDialog(self)

    def _show_first_run_notice(self) -> None:
        """One-shot alpha welcome modal. Persists a flag in app_settings.json
        so it's shown exactly once per install.
        """
        top = tk.Toplevel(self.root)
        top.title(f"Welcome to {APP_NAME} (Alpha)")
        top.transient(self.root)
        top.grab_set()
        top.resizable(False, False)

        frm = ttk.Frame(top, padding=16)
        frm.pack(fill=tk.BOTH, expand=True)
        ttk.Label(
            frm, text=f"{APP_NAME} v{APP_VERSION} - alpha release",
            font=("TkDefaultFont", 12, "bold"),
        ).pack(anchor=tk.W, pady=(0, 6))
        ttk.Label(
            frm,
            text=(
                "Thanks for helping test the alpha! A few quick notes before "
                "you start:\n\n"
                "  - This tool writes to your scanner's SD card. Please make "
                "a full file-copy backup of the card before using it.\n"
                "  - Every edit is logged and individually revertable from "
                "the Changes... dialog; a per-session .session.bak snapshot "
                "is also written so you can roll back the HPD file.\n"
                "  - The 'Workspaces / Virtual SD card' feature lets you "
                "experiment without touching the physical card at all until "
                "you're happy.\n"
                "  - Please report bugs, regressions, and suggestions on "
                "GitHub. Include the scanner model and a description of "
                "what you were doing when things broke."
            ),
            wraplength=520, justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(0, 10))

        btns = ttk.Frame(frm)
        btns.pack(fill=tk.X, pady=(6, 0))
        ttk.Button(
            btns, text="Open Wiki",
            command=lambda: webbrowser.open(APP_WIKI_URL),
        ).pack(side=tk.LEFT)
        ttk.Button(
            btns, text="Report an Issue",
            command=self._on_help_report_issue,
        ).pack(side=tk.LEFT, padx=4)

        def _dismiss() -> None:
            self._app_settings["first_run_seen"] = True
            try:
                self._save_app_settings()
            except Exception:
                pass
            top.destroy()

        ttk.Button(btns, text="Got it", command=_dismiss).pack(
            side=tk.RIGHT
        )
        top.protocol("WM_DELETE_WINDOW", _dismiss)

    def _on_bulk_remap(self):
        if not self.hpd.systems:
            messagebox.showinfo("Bulk Remap", "Load an HPD file first.")
            return
        BulkRemapDialog(self)

    def _on_mode_band_audit(self):
        if not self.hpd.systems:
            messagebox.showinfo("Audit", "Load an HPD file first.")
            return
        ModeBandAuditorDialog(self)


class RadioReferenceAutoGuessDialog:
    """Present ranked RadioReference URL candidates for a group.

    ``result`` is one of:
      * ``None`` - user cancelled
      * ``""`` - user chose to enter a URL manually
      * a non-empty URL string - user picked a candidate
    """

    def __init__(
        self,
        app: "ScannerManagerApp",
        group: GroupNode,
        candidates: List[Dict[str, Any]],
    ):
        self.app = app
        self.group = group
        self.candidates = candidates
        self.result: Optional[str] = None

        self.top = tk.Toplevel(app.root)
        self.top.title(f"Suggest RadioReference Link - {group.name}")
        self.top.transient(app.root)
        self.top.geometry("860x420")
        self.top.grab_set()

        header = ttk.Frame(self.top, padding=8)
        header.pack(fill=tk.X)
        ttk.Label(
            header,
            text=(
                f"Candidate RadioReference URLs for group '{group.name}'. "
                "Higher confidence = derived from a past import or callsign."
            ),
            wraplength=820, justify=tk.LEFT,
        ).pack(anchor=tk.W)

        tree_frame = ttk.Frame(self.top, padding=8)
        tree_frame.pack(fill=tk.BOTH, expand=True)
        columns = ("confidence", "source", "url", "detail")
        self.tree = ttk.Treeview(
            tree_frame, columns=columns, show="headings", selectmode="browse"
        )
        for col, label, width, anchor in (
            ("confidence", "Confidence", 90, tk.CENTER),
            ("source", "Source", 120, tk.W),
            ("url", "URL", 380, tk.W),
            ("detail", "Detail", 240, tk.W),
        ):
            self.tree.heading(col, text=label)
            self.tree.column(col, width=width, anchor=anchor)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        sb.pack(side=tk.LEFT, fill=tk.Y)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.bind("<Double-1>", lambda _e: self._on_accept())

        for c in self.candidates:
            self.tree.insert(
                "", tk.END,
                values=(
                    f"{int(round(c['confidence'] * 100))}%",
                    c["source"],
                    c["url"],
                    c.get("detail", ""),
                ),
            )
        if self.candidates:
            first = self.tree.get_children("")[0]
            self.tree.selection_set(first)

        footer = ttk.Frame(self.top, padding=8)
        footer.pack(fill=tk.X)
        ttk.Button(footer, text="Use Selected", command=self._on_accept).pack(side=tk.LEFT)
        ttk.Button(
            footer, text="Enter URL Manually...", command=self._on_manual,
        ).pack(side=tk.LEFT, padx=4)
        ttk.Button(footer, text="Cancel", command=self._on_cancel).pack(side=tk.RIGHT)

        app.root.wait_window(self.top)

    def _on_accept(self) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        url = self.tree.set(sel[0], "url")
        self.result = url
        self.top.destroy()

    def _on_manual(self) -> None:
        self.result = ""
        self.top.destroy()

    def _on_cancel(self) -> None:
        self.result = None
        self.top.destroy()


class RadioReferenceDiffDialog:
    """Read-only diff between a local group and its linked RadioReference page."""

    STATUS_ADDED = "ADDED"
    STATUS_REMOVED = "REMOVED"
    STATUS_CHANGED = "CHANGED"
    STATUS_SAME = "SAME"

    def __init__(self, app: "ScannerManagerApp", group: GroupNode, url: str):
        self.app = app
        self.group = group
        self.url = url
        self.system = next(
            (s for s in app.hpd.systems if group in s.groups), None
        )
        self.parsed: Optional[Dict[str, Any]] = None

        self.top = tk.Toplevel(app.root)
        self.top.title(f"RadioReference Diff - {group.name}")
        self.top.transient(app.root)
        self.top.geometry("980x620")
        self.top.grab_set()

        header = ttk.Frame(self.top, padding=8)
        header.pack(fill=tk.X)
        ttk.Label(
            header,
            text=f"Group: {group.name}    URL: {url}",
            wraplength=940, justify=tk.LEFT,
        ).pack(anchor=tk.W)
        self.summary_var = tk.StringVar(value="Fetching RadioReference page...")
        ttk.Label(
            header, textvariable=self.summary_var, foreground="#333333",
        ).pack(anchor=tk.W, pady=(4, 0))

        tree_frame = ttk.Frame(self.top, padding=8)
        tree_frame.pack(fill=tk.BOTH, expand=True)
        columns = ("status", "ident", "local", "rr", "detail")
        self.tree = ttk.Treeview(
            tree_frame, columns=columns, show="headings", selectmode="browse"
        )
        for col, label, width, anchor in (
            ("status", "Status", 100, tk.W),
            ("ident", "Freq/TGID", 110, tk.W),
            ("local", "Local", 220, tk.W),
            ("rr", "RadioReference", 220, tk.W),
            ("detail", "Details", 260, tk.W),
        ):
            self.tree.heading(col, text=label)
            self.tree.column(col, width=width, anchor=anchor)
        self.tree.tag_configure("added", foreground="#1a7f37")
        self.tree.tag_configure("removed", foreground="#b22222")
        self.tree.tag_configure("changed", foreground="#b8860b")
        self.tree.tag_configure("same", foreground="#808080")
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        sb.pack(side=tk.LEFT, fill=tk.Y)
        self.tree.configure(yscrollcommand=sb.set)

        footer = ttk.Frame(self.top, padding=8)
        footer.pack(fill=tk.X)
        ttk.Button(footer, text="Refresh", command=self._on_refresh).pack(side=tk.LEFT)
        ttk.Button(
            footer, text="Open Reconciler...", command=self._on_open_reconciler,
        ).pack(side=tk.LEFT, padx=4)
        ttk.Button(footer, text="Close", command=self.top.destroy).pack(side=tk.RIGHT)

        self.top.after(50, self._fetch_and_populate)
        app.root.wait_window(self.top)

    def _fetch_and_populate(self) -> None:
        try:
            parsed = fetch_radioreference_data(self.url)
        except Exception as exc:
            messagebox.showerror(
                "Fetch Error", f"Could not fetch RadioReference page:\n{exc}",
                parent=self.top,
            )
            self.summary_var.set("Fetch failed.")
            return
        if not parsed:
            self.summary_var.set("No usable data from the RadioReference page.")
            return
        self.parsed = parsed
        self._populate()

    def _on_refresh(self) -> None:
        for iid in self.tree.get_children(""):
            self.tree.delete(iid)
        self.summary_var.set("Refreshing...")
        self.top.update_idletasks()
        self._fetch_and_populate()

    def _on_open_reconciler(self) -> None:
        if not self.parsed:
            return
        self.top.destroy()
        self.app._refresh_group_from_rr(self.group, self.url)

    def _flatten_cfreq_rows(self) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        if not self.parsed:
            return rows
        if self.parsed.get("frequencies"):
            rows.extend(self.parsed["frequencies"])
        for cat in self.parsed.get("categories") or []:
            for f in cat.get("frequencies") or []:
                rows.append(f)
        return rows

    def _flatten_tg_rows(self) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        if not self.parsed:
            return rows
        for cat in self.parsed.get("categories") or []:
            for tg in cat.get("talkgroups") or []:
                rows.append(tg)
        return rows

    def _populate(self) -> None:
        is_trunked_group = any(
            e.entry_type == "TGID" for e in self.group.entries
        )
        rr_mode = "tgid" if (
            is_trunked_group
            or (self.parsed and self.parsed.get("kind") == "trs")
        ) else "cfreq"

        added = removed = changed = same = 0
        if rr_mode == "cfreq":
            local_by_hz: Dict[int, FreqEntry] = {}
            for e in self.group.entries:
                if e.entry_type != "C-Freq":
                    continue
                try:
                    hz = int(e.record.get_field(5, ""))
                except ValueError:
                    continue
                local_by_hz[hz] = e
            seen: Set[int] = set()
            for rr in self._flatten_cfreq_rows():
                try:
                    hz = int(round(float(rr.get("mhz") or 0) * 1_000_000))
                except Exception:
                    continue
                if hz <= 0:
                    continue
                seen.add(hz)
                existing = local_by_hz.get(hz)
                rr_name = rr.get("name") or rr.get("alpha") or ""
                rr_mode_str = rr.get("mode") or ""
                ident = f"{hz / 1_000_000:.4f} MHz"
                if existing is None:
                    self.tree.insert(
                        "", tk.END,
                        values=(self.STATUS_ADDED, ident, "",
                                f"{rr_name} / {rr_mode_str}", "New on RR"),
                        tags=("added",),
                    )
                    added += 1
                else:
                    changes = diff_cfreq_with_rr(
                        existing.name,
                        existing.record.get_field(6, ""),
                        existing.record.get_field(7, ""),
                        existing.service_type,
                        rr_name,
                        rr_mode_str,
                        rr.get("tone") or "",
                        rr.get("suggested_service_type")
                        if isinstance(rr.get("suggested_service_type"), int) else None,
                    )
                    if changes:
                        detail = ", ".join(
                            f"{k}: {changes[k][0]!r}->{changes[k][1]!r}"
                            for k in sorted(changes)
                        )
                        self.tree.insert(
                            "", tk.END,
                            values=(self.STATUS_CHANGED, ident,
                                    f"{existing.name} / {existing.record.get_field(6, '')}",
                                    f"{rr_name} / {rr_mode_str}",
                                    detail),
                            tags=("changed",),
                        )
                        changed += 1
                    else:
                        self.tree.insert(
                            "", tk.END,
                            values=(self.STATUS_SAME, ident,
                                    existing.name, rr_name, ""),
                            tags=("same",),
                        )
                        same += 1
            for hz, e in local_by_hz.items():
                if hz in seen:
                    continue
                self.tree.insert(
                    "", tk.END,
                    values=(self.STATUS_REMOVED, f"{hz / 1_000_000:.4f} MHz",
                            e.name, "", "Missing on RR"),
                    tags=("removed",),
                )
                removed += 1
        else:
            local_by_tgid: Dict[int, FreqEntry] = {}
            for e in self.group.entries:
                if e.entry_type != "TGID":
                    continue
                try:
                    tgid = int(e.record.get_field(5, ""))
                except ValueError:
                    continue
                local_by_tgid[tgid] = e
            seen_tgids: Set[int] = set()
            for rr in self._flatten_tg_rows():
                try:
                    tgid = int(rr.get("tgid") or 0)
                except Exception:
                    continue
                if tgid <= 0:
                    continue
                seen_tgids.add(tgid)
                existing = local_by_tgid.get(tgid)
                rr_name = rr.get("name") or rr.get("alpha") or ""
                rr_mode_str = rr.get("mode") or ""
                ident = f"TGID {tgid}"
                if existing is None:
                    status = self.STATUS_ADDED
                    detail = "Encrypted" if rr.get("encrypted") else "New on RR"
                    self.tree.insert(
                        "", tk.END,
                        values=(status, ident, "",
                                f"{rr_name} / {tgid_mode_label(rr_mode_str) or rr_mode_str}",
                                detail),
                        tags=("added",),
                    )
                    added += 1
                else:
                    changes = diff_tgid_with_rr(
                        existing.name,
                        existing.record.get_field(6, ""),
                        existing.service_type,
                        rr_name,
                        rr_mode_str,
                        rr.get("suggested_service_type")
                        if isinstance(rr.get("suggested_service_type"), int) else None,
                    )
                    if changes:
                        detail = ", ".join(
                            f"{k}: {changes[k][0]!r}->{changes[k][1]!r}"
                            for k in sorted(changes)
                        )
                        if rr.get("encrypted"):
                            detail = f"[enc] {detail}"
                        self.tree.insert(
                            "", tk.END,
                            values=(self.STATUS_CHANGED, ident,
                                    f"{existing.name} / "
                                    f"{tgid_mode_label(existing.record.get_field(6, '')) or ''}",
                                    f"{rr_name} / "
                                    f"{tgid_mode_label(rr_mode_str) or rr_mode_str}",
                                    detail),
                            tags=("changed",),
                        )
                        changed += 1
                    else:
                        self.tree.insert(
                            "", tk.END,
                            values=(self.STATUS_SAME, ident,
                                    existing.name, rr_name, ""),
                            tags=("same",),
                        )
                        same += 1
            for tgid, e in local_by_tgid.items():
                if tgid in seen_tgids:
                    continue
                self.tree.insert(
                    "", tk.END,
                    values=(self.STATUS_REMOVED, f"TGID {tgid}",
                            e.name, "", "Missing on RR"),
                    tags=("removed",),
                )
                removed += 1

        self.summary_var.set(
            f"Diff: {added} added, {removed} removed, {changed} changed, {same} same"
        )


class ConventionalImportSelectionDialog:
    """Select / reconcile conventional frequencies against RadioReference data."""

    CHECK_ON = "\u2611"
    CHECK_OFF = "\u2610"

    def __init__(
        self,
        app: "ScannerManagerApp",
        system: SystemNode,
        parsed: Dict[str, Any],
    ):
        self.app = app
        self.system = system
        self.parsed = parsed
        self.categories = parsed.get("categories") or []
        self.result: List[Tuple[str, List[Dict[str, Any]]]] = []
        self._item_meta: Dict[str, Dict[str, Any]] = {}

        self.update_mode_var = tk.BooleanVar(value=True)
        self.update_name_var = tk.BooleanVar(value=False)
        self.update_tone_var = tk.BooleanVar(value=True)
        self.update_service_var = tk.BooleanVar(value=False)

        self._existing_by_freq: Dict[int, FreqEntry] = {}
        for group in system.groups:
            for entry in group.entries:
                if entry.entry_type != "C-Freq":
                    continue
                try:
                    freq_hz = int(entry.record.get_field(5, ""))
                except ValueError:
                    continue
                if freq_hz <= 0:
                    continue
                self._existing_by_freq[freq_hz] = entry

        self.top = tk.Toplevel(app.root)
        self.top.title("Conventional Frequencies: Import / Reconcile")
        self.top.transient(app.root)
        self.top.geometry("1040x640")
        self.top.grab_set()

        header = ttk.Frame(self.top, padding=8)
        header.pack(fill=tk.X)
        source = parsed.get("title") or parsed.get("group_name") or "RadioReference"
        ttk.Label(
            header,
            text=(
                f"Source: {source}    Target system: '{system.name}'    "
                "Click a row to toggle. Existing entries compared against RR."
            ),
            wraplength=1000, justify=tk.LEFT,
        ).pack(side=tk.TOP, anchor=tk.W)

        policy = ttk.Frame(self.top, padding=(8, 0, 8, 0))
        policy.pack(fill=tk.X)
        ttk.Label(policy, text="Update fields on existing entries:").pack(side=tk.LEFT)
        ttk.Checkbutton(
            policy, text="Mode", variable=self.update_mode_var,
            command=self._on_policy_changed,
        ).pack(side=tk.LEFT, padx=4)
        ttk.Checkbutton(
            policy, text="Tone", variable=self.update_tone_var,
            command=self._on_policy_changed,
        ).pack(side=tk.LEFT, padx=4)
        ttk.Checkbutton(
            policy, text="Name (may overwrite user edits)",
            variable=self.update_name_var, command=self._on_policy_changed,
        ).pack(side=tk.LEFT, padx=4)
        ttk.Checkbutton(
            policy, text="Service type (overwrites user button mapping)",
            variable=self.update_service_var, command=self._on_policy_changed,
        ).pack(side=tk.LEFT, padx=4)

        tools = ttk.Frame(self.top, padding=(8, 0, 8, 0))
        tools.pack(fill=tk.X)
        ttk.Button(tools, text="Select New + Updates", command=self._on_select_new_and_updates).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(tools, text="Select Updates Only", command=self._on_select_updates_only).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(tools, text="Select All", command=self._on_select_all).pack(side=tk.LEFT, padx=2)
        ttk.Button(tools, text="Clear All", command=self._on_clear_all).pack(side=tk.LEFT, padx=2)
        self.summary_var = tk.StringVar()
        ttk.Label(tools, textvariable=self.summary_var, foreground="#333333").pack(side=tk.RIGHT)

        tree_frame = ttk.Frame(self.top, padding=8)
        tree_frame.pack(fill=tk.BOTH, expand=True)
        columns = (
            "check", "action", "freq", "name", "mode", "tone",
            "tag", "service", "target_group", "crossref",
        )
        self.tree = ttk.Treeview(
            tree_frame, columns=columns, show="tree headings", selectmode="browse"
        )
        self.tree.heading("#0", text="Category")
        self.tree.column("#0", width=200, stretch=False)
        for col, label, width, anchor in (
            ("check", "", 34, tk.CENTER),
            ("action", "Action", 160, tk.W),
            ("freq", "Freq MHz", 90, tk.E),
            ("name", "Name", 180, tk.W),
            ("mode", "Mode", 60, tk.CENTER),
            ("tone", "Tone", 110, tk.W),
            ("tag", "Tag", 110, tk.W),
            ("service", "Service", 110, tk.W),
            ("target_group", "Target Group", 180, tk.W),
            ("crossref", "Cross-ref", 200, tk.W),
        ):
            self.tree.heading(col, text=label)
            self.tree.column(col, width=width, anchor=anchor)
        self.tree.tag_configure("category", font=("TkDefaultFont", 9, "bold"))
        self.tree.tag_configure("update_available", foreground="#b8860b")
        self.tree.tag_configure("same", foreground="#808080")
        self.tree.tag_configure("crossref_callsign", background="#eaf5ff")
        self.tree.tag_configure("crossref_fuzzy", background="#fff8e1")
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        sb.pack(side=tk.LEFT, fill=tk.Y)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.bind("<Button-1>", self._on_click)

        footer = ttk.Frame(self.top, padding=8)
        footer.pack(fill=tk.X)
        ttk.Button(footer, text="Import Selected", command=self._on_confirm).pack(side=tk.LEFT)
        ttk.Button(footer, text="Cancel", command=self.top.destroy).pack(side=tk.RIGHT)

        self._populate()
        self._refresh_summary()
        app.root.wait_window(self.top)

    def _filter_changes_by_policy(
        self, raw: Dict[str, Tuple[Any, Any]]
    ) -> Dict[str, Tuple[Any, Any]]:
        result: Dict[str, Tuple[Any, Any]] = {}
        if self.update_mode_var.get() and "mode" in raw:
            result["mode"] = raw["mode"]
        if self.update_tone_var.get() and "tone" in raw:
            result["tone"] = raw["tone"]
        if self.update_name_var.get() and "name" in raw:
            result["name"] = raw["name"]
        if self.update_service_var.get() and "service_type" in raw:
            result["service_type"] = raw["service_type"]
        return result

    def _target_group_name_for_existing(self, entry: FreqEntry) -> str:
        for sys_node in self.app.hpd.systems:
            for group in sys_node.groups:
                if entry in group.entries:
                    return group.name
        return "(existing)"

    def _populate(self):
        self._crossref_counts = {"callsign": 0, "fuzzy": 0}
        for cat in self.categories:
            cat_name = cat.get("name") or "Imported"
            cat_id = self.tree.insert(
                "", tk.END, text=cat_name,
                values=(self.CHECK_ON, "", "", "", "", "", "", "", "", ""),
                tags=("category",), open=True,
            )
            self._item_meta[cat_id] = {"type": "category"}
            for freq in cat.get("frequencies", []):
                try:
                    freq_hz = int(round(float(freq["mhz"]) * 1_000_000))
                except Exception:
                    continue
                existing = self._existing_by_freq.get(freq_hz)
                service = freq.get("suggested_service_type")
                raw_changes: Dict[str, Tuple[Any, Any]] = {}
                changes: Dict[str, Tuple[Any, Any]] = {}
                action = "new"
                if existing is not None:
                    raw_changes = diff_cfreq_with_rr(
                        existing.name,
                        existing.record.get_field(6, ""),
                        existing.record.get_field(7, ""),
                        existing.service_type,
                        freq.get("name") or freq.get("alpha") or "",
                        freq.get("mode") or "",
                        freq.get("tone") or "",
                        service if isinstance(service, int) else None,
                    )
                    changes = self._filter_changes_by_policy(raw_changes)
                    action = "update" if changes else "same"

                if action == "new":
                    checked = True
                    action_text = "New"
                    row_tags: Tuple[str, ...] = ()
                elif action == "update":
                    checked = True
                    change_text = ", ".join(
                        f"{k}: {changes[k][0]!r}→{changes[k][1]!r}" for k in sorted(changes)
                    )
                    action_text = f"Update ({change_text})"
                    row_tags = ("update_available",)
                else:
                    checked = False
                    action_text = "Same (skip)"
                    row_tags = ("same",)

                target_group = (
                    self._target_group_name_for_existing(existing)
                    if existing is not None else cat_name
                )
                service_text = service_label(service) if isinstance(service, int) else ""
                hint = self.app.crossref_hint_for_rr_row(
                    freq, fallback_name=cat_name
                ) if existing is None else None
                crossref_text = hint["label"] if hint else ""
                if hint is not None:
                    kind = hint.get("kind")
                    if kind == "callsign":
                        self._crossref_counts["callsign"] += 1
                        row_tags = row_tags + ("crossref_callsign",)
                    elif kind == "fuzzy":
                        self._crossref_counts["fuzzy"] += 1
                        row_tags = row_tags + ("crossref_fuzzy",)
                iid = self.tree.insert(
                    cat_id, tk.END, text="",
                    values=(
                        self.CHECK_ON if checked else self.CHECK_OFF,
                        action_text,
                        f"{freq['mhz']:.4f}",
                        freq.get("name") or freq.get("alpha") or "",
                        freq.get("mode") or "",
                        freq.get("tone") or "",
                        freq.get("tag", ""),
                        service_text,
                        target_group,
                        crossref_text,
                    ),
                    tags=row_tags,
                )
                self._item_meta[iid] = {
                    "type": "cfreq",
                    "parent": cat_id,
                    "data": freq,
                    "freq_hz": freq_hz,
                    "checked": checked,
                    "action": action,
                    "changes": changes,
                    "raw_changes": raw_changes,
                    "existing": existing,
                    "crossref": hint,
                }
            self._refresh_category(cat_id)

    def _refresh_category(self, cat_id: str):
        children = self.tree.get_children(cat_id)
        if not children:
            self.tree.set(cat_id, "check", self.CHECK_OFF)
            return
        total = len(children)
        checked = sum(1 for c in children if self._item_meta[c].get("checked"))
        if checked == 0:
            mark = self.CHECK_OFF
        elif checked == total:
            mark = self.CHECK_ON
        else:
            mark = "\u25A3"
        self.tree.set(cat_id, "check", mark)

    def _refresh_summary(self):
        total = 0
        new_sel = 0
        update_sel = 0
        updates_available = 0
        for meta in self._item_meta.values():
            if meta.get("type") != "cfreq":
                continue
            total += 1
            if meta.get("action") == "update":
                updates_available += 1
            if meta.get("checked"):
                if meta.get("action") == "new":
                    new_sel += 1
                elif meta.get("action") == "update":
                    update_sel += 1
        xref = getattr(self, "_crossref_counts", {"callsign": 0, "fuzzy": 0})
        extra = ""
        if xref["callsign"] or xref["fuzzy"]:
            extra = f"   |  xref: {xref['callsign']} callsign, {xref['fuzzy']} fuzzy"
        self.summary_var.set(
            f"{total} frequencies; {new_sel} new, {update_sel}/{updates_available} updates"
            + extra
        )

    def _toggle_cfreq(self, iid: str, value: Optional[bool] = None):
        meta = self._item_meta[iid]
        if meta.get("type") != "cfreq":
            return
        new_val = value if value is not None else not meta.get("checked", False)
        meta["checked"] = new_val
        self.tree.set(iid, "check", self.CHECK_ON if new_val else self.CHECK_OFF)
        self._refresh_category(meta["parent"])
        self._refresh_summary()

    def _toggle_category(self, cat_id: str, value: Optional[bool] = None):
        children = self.tree.get_children(cat_id)
        if not children:
            return
        if value is None:
            current = self.tree.set(cat_id, "check")
            new_val = current != self.CHECK_ON
        else:
            new_val = value
        for c in children:
            self._toggle_cfreq(c, new_val)

    def _on_click(self, event):
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        meta = self._item_meta.get(iid)
        if not meta:
            return
        if meta.get("type") == "category":
            self._toggle_category(iid)
        else:
            self._toggle_cfreq(iid)

    def _on_select_all(self):
        for iid, meta in self._item_meta.items():
            if meta.get("type") == "cfreq":
                self._toggle_cfreq(iid, True)

    def _on_select_new_and_updates(self):
        for iid, meta in self._item_meta.items():
            if meta.get("type") != "cfreq":
                continue
            self._toggle_cfreq(iid, meta.get("action") in ("new", "update"))

    def _on_select_updates_only(self):
        for iid, meta in self._item_meta.items():
            if meta.get("type") != "cfreq":
                continue
            self._toggle_cfreq(iid, meta.get("action") == "update")

    def _on_clear_all(self):
        for iid, meta in self._item_meta.items():
            if meta.get("type") == "cfreq":
                self._toggle_cfreq(iid, False)

    def _on_policy_changed(self):
        for iid in self.tree.get_children(""):
            self.tree.delete(iid)
        self._item_meta.clear()
        self._populate()
        self._refresh_summary()

    def _on_confirm(self):
        selection: List[Tuple[str, List[Dict[str, Any]]]] = []
        new_count = 0
        update_count = 0
        for cat_id in self.tree.get_children(""):
            cat_name = self.tree.item(cat_id, "text")
            items: List[Dict[str, Any]] = []
            for child in self.tree.get_children(cat_id):
                meta = self._item_meta[child]
                if not meta.get("checked"):
                    continue
                action = meta.get("action")
                if action not in ("new", "update"):
                    continue
                payload = dict(meta["data"])
                payload["__action__"] = action
                payload["__changes__"] = meta.get("changes", {})
                payload["__existing__"] = meta.get("existing")
                payload["__freq_hz__"] = meta.get("freq_hz")
                items.append(payload)
                if action == "new":
                    new_count += 1
                elif action == "update":
                    update_count += 1
            if items:
                selection.append((cat_name, items))
        if not selection:
            messagebox.showinfo("Import", "No frequencies selected.", parent=self.top)
            return
        if not messagebox.askyesno(
            "Import Selected",
            f"Add {new_count} new frequencies and update {update_count} existing "
            f"frequencies in '{self.system.name}'?",
            parent=self.top,
        ):
            return
        self.result = selection
        self.top.destroy()


class TrunkedImportSelectionDialog:
    """Dialog to review and check/uncheck talkgroups from a RadioReference trunk page."""

    CHECK_ON = "\u2611"
    CHECK_OFF = "\u2610"

    def __init__(
        self,
        app: "ScannerManagerApp",
        system: SystemNode,
        parsed: Dict[str, Any],
    ):
        self.app = app
        self.system = system
        self.parsed = parsed
        self.categories = parsed.get("categories") or []
        self.result: List[Tuple[str, List[Dict[str, Any]]]] = []
        self._item_meta: Dict[str, Dict[str, Any]] = {}

        # Default: only overwrite "mode" on existing entries. Name and service_type
        # are user customizations (reconciler-style): preserved unless opted in.
        self.update_mode_var = tk.BooleanVar(value=True)
        self.update_name_var = tk.BooleanVar(value=False)
        self.update_service_var = tk.BooleanVar(value=False)
        # Existing entries now reported as encrypted by RR: suggest Avoid by default.
        # "skip" = leave as-is, "avoid" = set Avoid=On, "delete" = remove entry.
        self.encrypted_policy_var = tk.StringVar(value="avoid")

        self._existing_by_tgid: Dict[int, FreqEntry] = {}
        for group in system.groups:
            for entry in group.entries:
                if entry.entry_type != "TGID":
                    continue
                try:
                    tgid_val = int(entry.record.get_field(5, ""))
                except ValueError:
                    continue
                self._existing_by_tgid[tgid_val] = entry

        self.top = tk.Toplevel(app.root)
        self.top.title("Select Talkgroups to Import")
        self.top.transient(app.root)
        self.top.geometry("1020x620")
        self.top.grab_set()

        header = ttk.Frame(self.top, padding=8)
        header.pack(fill=tk.X)
        system_name = parsed.get("system_name", "RadioReference Trunk System")
        self.summary_var = tk.StringVar()
        ttk.Label(
            header,
            text=(
                f"Source: {system_name}    Target trunk: '{system.name}'    "
                "Click a row to toggle. Encrypted (DE/TE/AE) rows are off by default."
            ),
            wraplength=980, justify=tk.LEFT,
        ).pack(side=tk.TOP, anchor=tk.W)

        policy = ttk.Frame(self.top, padding=(8, 0, 8, 0))
        policy.pack(fill=tk.X)
        ttk.Label(policy, text="Update fields on existing entries:").pack(side=tk.LEFT)
        ttk.Checkbutton(
            policy, text="Mode (safe: fixes ALL → DIGITAL / ANALOG; D/T both = DIGITAL)",
            variable=self.update_mode_var, command=self._on_policy_changed,
        ).pack(side=tk.LEFT, padx=4)
        ttk.Checkbutton(
            policy, text="Name (may overwrite user edits)",
            variable=self.update_name_var, command=self._on_policy_changed,
        ).pack(side=tk.LEFT, padx=4)
        ttk.Checkbutton(
            policy, text="Service type (overwrites user button mapping)",
            variable=self.update_service_var, command=self._on_policy_changed,
        ).pack(side=tk.LEFT, padx=4)

        policy2 = ttk.Frame(self.top, padding=(8, 0, 8, 0))
        policy2.pack(fill=tk.X)
        ttk.Label(
            policy2,
            text="Existing entries now encrypted (RR shows DE/TE/AE):",
        ).pack(side=tk.LEFT)
        for label, value in (
            ("Skip", "skip"),
            ("Set Avoid=On", "avoid"),
            ("Delete from HPD", "delete"),
        ):
            ttk.Radiobutton(
                policy2, text=label, value=value,
                variable=self.encrypted_policy_var,
                command=self._on_policy_changed,
            ).pack(side=tk.LEFT, padx=4)

        tools = ttk.Frame(self.top, padding=(8, 0, 8, 0))
        tools.pack(fill=tk.X)
        ttk.Button(tools, text="Select All Unencrypted", command=self._on_select_unencrypted).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(tools, text="Select Updates Only", command=self._on_select_updates_only).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(tools, text="Select All", command=self._on_select_all).pack(side=tk.LEFT, padx=2)
        ttk.Button(tools, text="Clear All", command=self._on_clear_all).pack(side=tk.LEFT, padx=2)
        ttk.Label(tools, textvariable=self.summary_var, foreground="#333333").pack(side=tk.RIGHT)

        tree_frame = ttk.Frame(self.top, padding=8)
        tree_frame.pack(fill=tk.BOTH, expand=True)
        columns = ("check", "action", "tgid", "name", "mode", "tag", "service", "crossref")
        self.tree = ttk.Treeview(
            tree_frame, columns=columns, show="tree headings", selectmode="browse"
        )
        self.tree.heading("#0", text="Category")
        self.tree.column("#0", width=220, stretch=False)
        for col, label, width, anchor in (
            ("check", "", 34, tk.CENTER),
            ("action", "Action", 130, tk.W),
            ("tgid", "TGID", 70, tk.E),
            ("name", "Name", 260, tk.W),
            ("mode", "Mode", 70, tk.CENTER),
            ("tag", "Tag", 130, tk.W),
            ("service", "Service", 130, tk.W),
            ("crossref", "Cross-ref", 180, tk.W),
        ):
            self.tree.heading(col, text=label)
            self.tree.column(col, width=width, anchor=anchor)
        self.tree.tag_configure("encrypted", foreground="#b22222")
        self.tree.tag_configure("encrypted_action", foreground="#8b0000", background="#fff5f5")
        self.tree.tag_configure("category", font=("TkDefaultFont", 9, "bold"))
        self.tree.tag_configure("update_available", foreground="#b8860b")
        self.tree.tag_configure("same", foreground="#808080")
        self.tree.tag_configure("crossref_callsign", background="#eaf5ff")
        self.tree.tag_configure("crossref_fuzzy", background="#fff8e1")
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        sb.pack(side=tk.LEFT, fill=tk.Y)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.bind("<Button-1>", self._on_click)

        footer = ttk.Frame(self.top, padding=8)
        footer.pack(fill=tk.X)
        ttk.Button(footer, text="Import Selected", command=self._on_confirm).pack(side=tk.LEFT)
        ttk.Button(footer, text="Cancel", command=self.top.destroy).pack(side=tk.RIGHT)

        self._populate()
        self._refresh_summary()
        app.root.wait_window(self.top)

    def _populate(self):
        self._crossref_counts = {"callsign": 0, "fuzzy": 0}
        system_name_hint = (self.parsed.get("system_name") or "").strip()
        for cat in self.categories:
            cat_name = cat.get("name") or "Imported"
            cat_id = self.tree.insert(
                "", tk.END, text=cat_name, values=(self.CHECK_ON, "", "", "", "", "", "", ""),
                tags=("category",), open=True,
            )
            self._item_meta[cat_id] = {"type": "category"}
            for tg in cat.get("talkgroups", []):
                # Show RR's raw token alongside the HPD label so the user sees
                # e.g. "T → DIGITAL (D / T TDMA)" intent at a glance.
                rr_raw = (tg.get("mode_raw") or "").strip()
                hpd_mode = tg.get("mode") or ""
                hpd_label = tgid_mode_label(hpd_mode) if hpd_mode else ""
                if rr_raw and hpd_label:
                    mode_text = f"{rr_raw} → {hpd_label}"
                else:
                    mode_text = hpd_label or rr_raw
                if tg.get("encrypted"):
                    mode_text = f"{mode_text} (enc)"
                service = tg.get("suggested_service_type")
                service_label_text = service_label(service) if isinstance(service, int) else ""

                tgid_val = tg.get("tgid")
                existing = self._existing_by_tgid.get(int(tgid_val)) if tgid_val else None
                action = "new"
                raw_changes: Dict[str, Tuple[Any, Any]] = {}
                changes: Dict[str, Tuple[Any, Any]] = {}
                if existing is not None:
                    raw_changes = diff_tgid_with_rr(
                        existing.name,
                        existing.record.get_field(6, ""),
                        existing.service_type,
                        tg.get("name") or tg.get("alpha") or "",
                        tg.get("mode") or "",
                        service if isinstance(service, int) else None,
                    )
                    changes = self._filter_changes_by_policy(raw_changes)
                    action = "update" if changes else "same"
                if tg.get("encrypted"):
                    if existing is not None:
                        policy = self.encrypted_policy_var.get()
                        if policy == "avoid":
                            current_avoid = existing.record.get_field(4, "Off")
                            action = "avoid_encrypted" if current_avoid != "On" else "same_encrypted"
                        elif policy == "delete":
                            action = "delete_encrypted"
                        else:
                            action = "same_encrypted"
                    else:
                        action = "encrypted"

                if action == "new":
                    checked = True
                    action_text = "New"
                    row_tags: Tuple[str, ...] = ()
                elif action == "update":
                    checked = True
                    change_keys = sorted(changes.keys())
                    change_text = ", ".join(
                        f"{k}: {changes[k][0]!r}→{changes[k][1]!r}" for k in change_keys
                    )
                    action_text = f"Update ({change_text})"
                    row_tags = ("update_available",)
                elif action == "same":
                    checked = False
                    action_text = "Same (skip)"
                    row_tags = ("same",)
                elif action == "avoid_encrypted":
                    checked = True
                    action_text = "Encrypted - set Avoid=On"
                    row_tags = ("encrypted_action",)
                elif action == "delete_encrypted":
                    checked = True
                    action_text = "Encrypted - DELETE"
                    row_tags = ("encrypted_action",)
                elif action == "same_encrypted":
                    checked = False
                    action_text = "Encrypted (already avoided or skipped)"
                    row_tags = ("encrypted",)
                else:
                    checked = False
                    action_text = "Encrypted (skip)"
                    row_tags = ("encrypted",)

                hint = self.app.crossref_hint_for_rr_row(
                    tg,
                    fallback_name=cat_name or system_name_hint,
                ) if existing is None else None
                crossref_text = hint["label"] if hint else ""
                if hint is not None:
                    kind = hint.get("kind")
                    if kind == "callsign":
                        self._crossref_counts["callsign"] += 1
                        row_tags = row_tags + ("crossref_callsign",)
                    elif kind == "fuzzy":
                        self._crossref_counts["fuzzy"] += 1
                        row_tags = row_tags + ("crossref_fuzzy",)
                iid = self.tree.insert(
                    cat_id, tk.END, text="",
                    values=(
                        self.CHECK_ON if checked else self.CHECK_OFF,
                        action_text,
                        tg["tgid"],
                        tg.get("name") or tg.get("alpha") or f"TGID {tg['tgid']}",
                        mode_text,
                        tg.get("tag", ""),
                        service_label_text,
                        crossref_text,
                    ),
                    tags=row_tags,
                )
                self._item_meta[iid] = {
                    "type": "tg",
                    "parent": cat_id,
                    "data": tg,
                    "checked": checked,
                    "action": action,
                    "changes": changes,
                    "raw_changes": raw_changes,
                    "existing": existing,
                    "crossref": hint,
                }
            self._refresh_category(cat_id)

    def _filter_changes_by_policy(
        self, raw: Dict[str, Tuple[Any, Any]]
    ) -> Dict[str, Tuple[Any, Any]]:
        result: Dict[str, Tuple[Any, Any]] = {}
        if self.update_mode_var.get() and "mode" in raw:
            result["mode"] = raw["mode"]
        if self.update_name_var.get() and "name" in raw:
            result["name"] = raw["name"]
        if self.update_service_var.get() and "service_type" in raw:
            result["service_type"] = raw["service_type"]
        return result

    def _on_policy_changed(self):
        # Rebuild the tree with the new policy applied to all rows.
        for iid in self.tree.get_children(""):
            self.tree.delete(iid)
        self._item_meta.clear()
        self._populate()
        self._refresh_summary()

    def _refresh_category(self, cat_id: str):
        children = self.tree.get_children(cat_id)
        if not children:
            self.tree.set(cat_id, "check", self.CHECK_OFF)
            return
        total = len(children)
        checked = sum(1 for c in children if self._item_meta[c].get("checked"))
        if checked == 0:
            mark = self.CHECK_OFF
        elif checked == total:
            mark = self.CHECK_ON
        else:
            mark = "\u25A3"
        self.tree.set(cat_id, "check", mark)

    def _refresh_summary(self):
        total = 0
        new_sel = 0
        update_sel = 0
        avoid_sel = 0
        delete_sel = 0
        encrypted = 0
        updates_available = 0
        for meta in self._item_meta.values():
            if meta.get("type") != "tg":
                continue
            total += 1
            if meta["data"].get("encrypted"):
                encrypted += 1
            if meta.get("action") == "update":
                updates_available += 1
            if meta.get("checked"):
                action = meta.get("action")
                if action == "new":
                    new_sel += 1
                elif action == "update":
                    update_sel += 1
                elif action == "avoid_encrypted":
                    avoid_sel += 1
                elif action == "delete_encrypted":
                    delete_sel += 1
        xref = getattr(self, "_crossref_counts", {"callsign": 0, "fuzzy": 0})
        extra = ""
        if xref["callsign"] or xref["fuzzy"]:
            extra = f"   |  xref: {xref['callsign']} callsign, {xref['fuzzy']} fuzzy"
        self.summary_var.set(
            f"{total} talkgroups; {new_sel} new, {update_sel}/{updates_available} updates, "
            f"{avoid_sel} avoid-encrypted, {delete_sel} delete-encrypted, "
            f"{encrypted} total encrypted"
            + extra
        )

    def _toggle_tg(self, iid: str, value: Optional[bool] = None):
        meta = self._item_meta[iid]
        if meta.get("type") != "tg":
            return
        new_val = value if value is not None else not meta.get("checked", False)
        meta["checked"] = new_val
        self.tree.set(iid, "check", self.CHECK_ON if new_val else self.CHECK_OFF)
        self._refresh_category(meta["parent"])
        self._refresh_summary()

    def _toggle_category(self, cat_id: str, value: Optional[bool] = None):
        children = self.tree.get_children(cat_id)
        if not children:
            return
        if value is None:
            current = self.tree.set(cat_id, "check")
            new_val = current != self.CHECK_ON
        else:
            new_val = value
        for c in children:
            self._toggle_tg(c, new_val)

    def _on_click(self, event):
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        meta = self._item_meta.get(iid)
        if not meta:
            return
        if meta.get("type") == "category":
            self._toggle_category(iid)
        else:
            self._toggle_tg(iid)

    def _on_select_all(self):
        for iid, meta in self._item_meta.items():
            if meta.get("type") == "tg":
                self._toggle_tg(iid, True)

    def _on_select_unencrypted(self):
        for iid, meta in self._item_meta.items():
            if meta.get("type") != "tg":
                continue
            if meta["data"].get("encrypted", False):
                self._toggle_tg(iid, False)
            elif meta.get("action") in ("new", "update"):
                self._toggle_tg(iid, True)
            else:
                self._toggle_tg(iid, False)

    def _on_select_updates_only(self):
        for iid, meta in self._item_meta.items():
            if meta.get("type") != "tg":
                continue
            if meta.get("action") == "update" and not meta["data"].get("encrypted", False):
                self._toggle_tg(iid, True)
            else:
                self._toggle_tg(iid, False)

    def _on_clear_all(self):
        for iid, meta in self._item_meta.items():
            if meta.get("type") == "tg":
                self._toggle_tg(iid, False)

    def _on_confirm(self):
        selection: List[Tuple[str, List[Dict[str, Any]]]] = []
        new_count = 0
        update_count = 0
        avoid_count = 0
        delete_count = 0
        for cat_id in self.tree.get_children(""):
            cat_name = self.tree.item(cat_id, "text")
            items: List[Dict[str, Any]] = []
            for child in self.tree.get_children(cat_id):
                meta = self._item_meta[child]
                if not meta.get("checked"):
                    continue
                action = meta.get("action")
                if action not in ("new", "update", "avoid_encrypted", "delete_encrypted"):
                    continue
                payload = dict(meta["data"])
                payload["__action__"] = action
                payload["__changes__"] = meta.get("changes", {})
                payload["__existing__"] = meta.get("existing")
                items.append(payload)
                if action == "new":
                    new_count += 1
                elif action == "update":
                    update_count += 1
                elif action == "avoid_encrypted":
                    avoid_count += 1
                elif action == "delete_encrypted":
                    delete_count += 1
            if items:
                selection.append((cat_name, items))
        if not selection:
            messagebox.showinfo(
                "Import", "No talkgroups selected.", parent=self.top
            )
            return
        summary_parts = []
        if new_count:
            summary_parts.append(f"{new_count} new")
        if update_count:
            summary_parts.append(f"{update_count} updates")
        if avoid_count:
            summary_parts.append(f"{avoid_count} avoid-encrypted")
        if delete_count:
            summary_parts.append(f"{delete_count} DELETE encrypted")
        prompt = (
            "Proceed with:\n  " + "\n  ".join(summary_parts)
            + f"\nunder '{self.system.name}'?"
        )
        if delete_count:
            prompt += "\n\nDeletion is permanent once you Save."
        if not messagebox.askyesno("Import Selected", prompt, parent=self.top):
            return
        self.result = selection
        self.top.destroy()


class ModeBandAuditorDialog:
    """Flag entries whose mode doesn't match the frequency band and offer quick-fix."""

    def __init__(self, app: "ScannerManagerApp"):
        self.app = app
        self.top = tk.Toplevel(app.root)
        self.top.title("Mode / Band Audit")
        self.top.transient(app.root)
        self.top.geometry("1020x560")

        self._rr_reference: Dict[int, Dict[str, Any]] = {}
        self._rr_sources: List[str] = []

        header = ttk.Frame(self.top, padding=8)
        header.pack(fill=tk.X)
        self.summary_var = tk.StringVar()
        ttk.Label(header, textvariable=self.summary_var).pack(side=tk.LEFT)
        ttk.Button(header, text="Refresh", command=self._refresh).pack(side=tk.RIGHT)

        ref_row = ttk.Frame(self.top, padding=(8, 0, 8, 0))
        ref_row.pack(fill=tk.X)
        self.rr_status_var = tk.StringVar(value="RR reference: none loaded")
        ttk.Label(ref_row, textvariable=self.rr_status_var, foreground="#555555").pack(side=tk.LEFT)
        ttk.Button(ref_row, text="Add RR Reference URL...", command=self._on_add_rr_reference).pack(
            side=tk.RIGHT, padx=2
        )
        ttk.Button(ref_row, text="Clear RR Reference", command=self._on_clear_rr_reference).pack(
            side=tk.RIGHT, padx=2
        )

        tree_frame = ttk.Frame(self.top)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)
        columns = ("system", "group", "name", "freq", "mode", "suggested", "source", "issue")
        self.tree = ttk.Treeview(
            tree_frame, columns=columns, show="headings", selectmode="extended",
        )
        for col, label, width in (
            ("system", "System", 150),
            ("group", "Group", 160),
            ("name", "Name", 140),
            ("freq", "Freq (MHz)", 90),
            ("mode", "Mode", 60),
            ("suggested", "Suggested", 80),
            ("source", "Source", 70),
            ("issue", "Issue", 240),
        ):
            self.tree.heading(col, text=label)
            self.tree.column(col, width=width, anchor=tk.W)
        self.tree.tag_configure("source_rr", foreground="#8b0000")
        self.tree.tag_configure("source_band", foreground="#606060")
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        sb.pack(side=tk.LEFT, fill=tk.Y)
        self.tree.configure(yscrollcommand=sb.set)

        footer = ttk.Frame(self.top, padding=8)
        footer.pack(fill=tk.X)
        ttk.Button(footer, text="Apply Suggested to Selected", command=self._on_fix_selected).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(footer, text="Apply Suggested to All", command=self._on_fix_all).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(footer, text="Close", command=self.top.destroy).pack(side=tk.RIGHT)

        self._issues: List[Tuple[FreqEntry, str, str]] = []
        self._refresh()

    def _refresh(self):
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        self._issues = []
        total = 0
        rr_flags = 0
        band_flags = 0
        for sys_node in self.app.hpd.systems:
            for group in sys_node.groups:
                for entry in group.entries:
                    if entry.entry_type != "C-Freq":
                        continue
                    total += 1
                    result = audit_mode_issue_with_rr(entry, self._rr_reference)
                    if result is None:
                        continue
                    issue, suggested, source = result
                    rec = entry.record
                    try:
                        freq_mhz = int(rec.get_field(5, "0")) / 1_000_000
                    except ValueError:
                        freq_mhz = 0
                    if source == "rr":
                        rr_flags += 1
                        row_tag = "source_rr"
                    else:
                        band_flags += 1
                        row_tag = "source_band"
                    self._issues.append((entry, issue, suggested))
                    self.tree.insert(
                        "",
                        tk.END,
                        values=(
                            sys_node.name,
                            group.name,
                            entry.name,
                            f"{freq_mhz:.4f}",
                            rec.get_field(6, ""),
                            suggested,
                            source.upper(),
                            issue,
                        ),
                        tags=(str(id(entry)), row_tag),
                    )
        self.summary_var.set(
            f"Reviewed {total} conventional entries; "
            f"flagged {len(self._issues)} ({rr_flags} RR, {band_flags} band)."
        )
        if self._rr_sources:
            summary = (
                f"RR reference: {len(self._rr_reference)} frequencies from "
                f"{len(self._rr_sources)} URL(s)"
            )
        else:
            summary = "RR reference: none loaded"
        self.rr_status_var.set(summary)

    def _on_add_rr_reference(self):
        from tkinter import simpledialog

        url = simpledialog.askstring(
            "Add RR Reference URL",
            "Paste a RadioReference category URL (e.g. .../db/aid/3161):",
            parent=self.top,
        )
        if not url:
            return
        try:
            parsed = fetch_radioreference_data(url)
        except Exception as exc:
            messagebox.showerror("Fetch", f"Could not fetch URL:\n{exc}", parent=self.top)
            return
        if not parsed or parsed.get("kind") != "category":
            messagebox.showinfo(
                "Fetch",
                "Only RadioReference category (aid/cid) URLs are supported for audit reference.",
                parent=self.top,
            )
            return
        added = 0
        for freq in parsed.get("frequencies") or []:
            try:
                freq_hz = int(round(float(freq["mhz"]) * 1_000_000))
            except Exception:
                continue
            self._rr_reference[freq_hz] = {
                "mode": freq.get("mode") or "",
                "name": freq.get("name") or freq.get("alpha") or "",
                "tone": freq.get("tone") or "",
                "tag": freq.get("tag", ""),
            }
            added += 1
        self._rr_sources.append(url)
        self._refresh()
        messagebox.showinfo(
            "RR Reference",
            f"Loaded {added} frequencies from {parsed.get('group_name', 'URL')}.",
            parent=self.top,
        )

    def _on_clear_rr_reference(self):
        self._rr_reference.clear()
        self._rr_sources.clear()
        self._refresh()

    def _entries_for_iids(self, iids) -> List[Tuple[FreqEntry, str]]:
        result: List[Tuple[FreqEntry, str]] = []
        id_map = {str(id(ent)): (ent, suggested) for ent, _, suggested in self._issues}
        for iid in iids:
            tags = self.tree.item(iid, "tags")
            if not tags:
                continue
            key = tags[0]
            if key in id_map:
                result.append(id_map[key])
        return result

    def _apply_fix(self, pairs: List[Tuple[FreqEntry, str]]):
        if not pairs:
            return 0
        if not messagebox.askyesno(
            "Apply Mode Fix",
            f"Apply suggested mode to {len(pairs)} entries?",
            parent=self.top,
        ):
            return 0
        applied = 0
        for entry, suggested in pairs:
            entry.record.set_field(6, suggested)
            self.app.hpd.has_changes = True
            applied += 1
        self.app._populate_tree()
        self.app._set_status(f"Mode audit: applied suggested mode to {applied} entries.")
        self._refresh()
        return applied

    def _on_fix_selected(self):
        pairs = self._entries_for_iids(self.tree.selection())
        if not pairs:
            messagebox.showinfo("Audit", "Select one or more flagged entries first.", parent=self.top)
            return
        self._apply_fix(pairs)

    def _on_fix_all(self):
        pairs = [(ent, suggested) for ent, _, suggested in self._issues]
        self._apply_fix(pairs)


class BulkRemapDialog:
    """Filter entries by type/service/scope and apply a remap action in bulk."""

    def __init__(self, app: "ScannerManagerApp"):
        self.app = app
        self.top = tk.Toplevel(app.root)
        self.top.title("Bulk Remap")
        self.top.transient(app.root)
        self.top.geometry("680x520")

        frm = ttk.Frame(self.top, padding=8)
        frm.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frm, text="Entry types:").grid(row=0, column=0, sticky=tk.W, pady=4)
        type_frame = ttk.Frame(frm)
        type_frame.grid(row=0, column=1, columnspan=3, sticky=tk.W)
        self.include_cfreq = tk.BooleanVar(value=True)
        self.include_tgid = tk.BooleanVar(value=True)
        ttk.Checkbutton(type_frame, text="C-Freq", variable=self.include_cfreq).pack(side=tk.LEFT, padx=4)
        ttk.Checkbutton(type_frame, text="TGID", variable=self.include_tgid).pack(side=tk.LEFT, padx=4)

        ttk.Label(frm, text="Service types (comma-separated, blank=all):").grid(
            row=1, column=0, sticky=tk.W, pady=4
        )
        self.service_filter = tk.StringVar(value="")
        ttk.Entry(frm, textvariable=self.service_filter, width=30).grid(
            row=1, column=1, columnspan=3, sticky=tk.W
        )

        ttk.Label(frm, text="System scope:").grid(row=2, column=0, sticky=tk.W, pady=4)
        self.scope_var = tk.StringVar(value="all")
        ttk.Radiobutton(frm, text="All systems", variable=self.scope_var, value="all").grid(
            row=2, column=1, sticky=tk.W
        )
        ttk.Radiobutton(
            frm, text="Current location filter only",
            variable=self.scope_var, value="location",
        ).grid(row=2, column=2, sticky=tk.W)
        ttk.Radiobutton(
            frm, text="Selected system only",
            variable=self.scope_var, value="selected",
        ).grid(row=2, column=3, sticky=tk.W)

        ttk.Label(frm, text="Avoid state filter:").grid(row=3, column=0, sticky=tk.W, pady=4)
        self.avoid_filter = tk.StringVar(value="any")
        for i, (label, value) in enumerate(
            (("Any", "any"), ("Off only", "Off"), ("On only", "On"))
        ):
            ttk.Radiobutton(frm, text=label, variable=self.avoid_filter, value=value).grid(
                row=3, column=1 + i, sticky=tk.W
            )

        ttk.Separator(frm, orient=tk.HORIZONTAL).grid(
            row=4, column=0, columnspan=4, sticky="ew", pady=6
        )

        ttk.Label(frm, text="Action:").grid(row=5, column=0, sticky=tk.W, pady=4)
        self.action_var = tk.StringVar(value="remap")
        ttk.Radiobutton(
            frm, text="Remap service type to", variable=self.action_var, value="remap",
        ).grid(row=5, column=1, sticky=tk.W)
        self.new_service_var = tk.StringVar()
        ttk.Combobox(
            frm, textvariable=self.new_service_var, state="readonly", width=22,
            values=[s[1] for s in SERVICE_CHOICES],
        ).grid(row=5, column=2, columnspan=2, sticky=tk.W)
        ttk.Radiobutton(
            frm, text="Set avoid On", variable=self.action_var, value="avoid_on",
        ).grid(row=6, column=1, sticky=tk.W)
        ttk.Radiobutton(
            frm, text="Set avoid Off", variable=self.action_var, value="avoid_off",
        ).grid(row=6, column=2, sticky=tk.W)

        ttk.Separator(frm, orient=tk.HORIZONTAL).grid(
            row=7, column=0, columnspan=4, sticky="ew", pady=6
        )

        self.preview_var = tk.StringVar(value="Preview: (click Preview to count)")
        ttk.Label(frm, textvariable=self.preview_var, foreground="#333333").grid(
            row=8, column=0, columnspan=4, sticky=tk.W, pady=4
        )

        btns = ttk.Frame(frm)
        btns.grid(row=9, column=0, columnspan=4, pady=8)
        ttk.Button(btns, text="Preview", command=self._on_preview).pack(side=tk.LEFT, padx=4)
        ttk.Button(btns, text="Apply", command=self._on_apply).pack(side=tk.LEFT, padx=4)
        ttk.Button(btns, text="Close", command=self.top.destroy).pack(side=tk.LEFT, padx=4)

    def _collect_filter(self) -> Dict[str, Any]:
        types: Set[str] = set()
        if self.include_cfreq.get():
            types.add("C-Freq")
        if self.include_tgid.get():
            types.add("TGID")
        svc_text = (self.service_filter.get() or "").strip()
        service_types: Optional[Set[int]] = None
        if svc_text:
            try:
                service_types = {int(x.strip()) for x in svc_text.split(",") if x.strip()}
            except ValueError:
                service_types = None
        avoid_state = None if self.avoid_filter.get() == "any" else self.avoid_filter.get()
        return {
            "entry_types": types,
            "service_types": service_types,
            "avoid_state": avoid_state,
        }

    def _iter_candidates(self) -> List[FreqEntry]:
        flt = self._collect_filter()
        scope = self.scope_var.get()
        location_systems: Optional[Set[int]] = None
        if scope == "location":
            location_systems = set()
            for i, sys_node in enumerate(self.app.hpd.systems):
                if self.app._system_matches_location(sys_node):
                    location_systems.add(i)
        selected_system_id = None
        if scope == "selected" and self.app._selected_system is not None:
            selected_system_id = self.app._selected_system.system_id
        elif scope == "selected" and self.app._selected_group is not None:
            selected_system_id = self.app._selected_group.system_id
        elif scope == "selected" and self.app._selected_entry is not None:
            selected_system_id = self.app._selected_entry.system_id

        candidates: List[FreqEntry] = []
        for i, sys_node in enumerate(self.app.hpd.systems):
            if scope == "location" and location_systems is not None and i not in location_systems:
                continue
            if scope == "selected" and selected_system_id is not None and sys_node.system_id != selected_system_id:
                continue
            for group in sys_node.groups:
                for entry in group.entries:
                    if not entry_matches_bulk_filter(
                        entry,
                        flt["entry_types"],
                        flt["service_types"],
                        county_id=None,
                        system_id=None,
                        avoid_state=flt["avoid_state"],
                    ):
                        continue
                    candidates.append(entry)
        return candidates

    def _on_preview(self):
        candidates = self._iter_candidates()
        self.preview_var.set(f"Preview: {len(candidates)} entries match the filter")

    def _on_apply(self):
        candidates = self._iter_candidates()
        if not candidates:
            messagebox.showinfo("Bulk Remap", "No entries match the filter.", parent=self.top)
            return
        action = self.action_var.get()
        if action == "remap":
            stype_str = self.new_service_var.get()
            if not stype_str:
                messagebox.showwarning("Bulk Remap", "Pick a service type first.", parent=self.top)
                return
            new_type = int(stype_str.split(" - ")[0])
            desc = f"remap service type to {service_label(new_type)}"
        elif action in ("avoid_on", "avoid_off"):
            target = "On" if action == "avoid_on" else "Off"
            desc = f"set avoid={target}"
        else:
            return

        if not messagebox.askyesno(
            "Bulk Remap",
            f"Apply '{desc}' to {len(candidates)} entries?",
            parent=self.top,
        ):
            return

        # Route through the event log so bulk remaps are revertable and
        # auditable. Wrap in a single MetaStore batch so the whole
        # operation emits one sidecar write regardless of candidate count.
        txn = self.app._new_txn_id()
        changed = 0
        batch_ctx = (
            self.app._meta.batch() if self.app._meta is not None else nullcontext()
        )
        with batch_ctx:
            if action == "remap":
                for entry in candidates:
                    if self.app._do_set_service(
                        entry, new_type, source="bulk_remap", txn_id=txn,
                    ):
                        changed += 1
            else:
                target = "On" if action == "avoid_on" else "Off"
                for entry in candidates:
                    if self.app._do_set_avoid(
                        entry, target, source="bulk_remap", txn_id=txn,
                    ):
                        changed += 1

        self.app._populate_tree()
        self.app._set_status(
            f"Bulk remap applied to {changed} of {len(candidates)} entries."
        )
        self.preview_var.set(f"Applied to {changed} entries.")


class DiscoveryViewerDialog:
    """Viewer for scanner discovery folders (Conventional / Trunk)."""

    def __init__(self, app: "ScannerManagerApp"):
        self.app = app
        self.top = tk.Toplevel(app.root)
        self.top.title("Discovery Logs")
        self.top.transient(app.root)
        self.top.geometry("900x600")

        sd_folder = (app._path_var.get() or "").strip()
        self.discovery_root = Path(sd_folder) / "discovery" if sd_folder else None
        self.groups = (
            discover_log_files(self.discovery_root)
            if self.discovery_root and self.discovery_root.exists()
            else {"Conventional": [], "Trunk": []}
        )

        header_frame = ttk.Frame(self.top, padding=(8, 8, 8, 0))
        header_frame.pack(fill=tk.X)
        total = sum(len(v) for v in self.groups.values())
        if not self.discovery_root or not self.discovery_root.exists():
            summary = "No discovery folder found. Select a valid SD card folder first."
        elif total == 0:
            summary = (
                f"Discovery folder found at {self.discovery_root}, but no logs yet. "
                "Run Discovery Mode on the scanner to generate logs."
            )
        else:
            summary = (
                f"Discovery root: {self.discovery_root}    "
                f"Conventional: {len(self.groups['Conventional'])}    "
                f"Trunk: {len(self.groups['Trunk'])}"
            )
        ttk.Label(header_frame, text=summary, wraplength=860, justify=tk.LEFT).pack(side=tk.LEFT)

        paned = ttk.PanedWindow(self.top, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        left = ttk.Frame(paned)
        paned.add(left, weight=1)
        self.file_tree = ttk.Treeview(
            left, columns=("name", "size", "modified"), show="tree headings", selectmode="browse"
        )
        self.file_tree.heading("name", text="File")
        self.file_tree.heading("size", text="Size")
        self.file_tree.heading("modified", text="Modified")
        self.file_tree.column("#0", width=140, stretch=False)
        self.file_tree.column("name", width=220)
        self.file_tree.column("size", width=80, anchor=tk.E)
        self.file_tree.column("modified", width=160)
        self.file_tree.pack(fill=tk.BOTH, expand=True)
        self.file_tree.bind("<<TreeviewSelect>>", self._on_select)

        right = ttk.Frame(paned)
        paned.add(right, weight=2)
        self.preview = tk.Text(right, wrap="none")
        self.preview.configure(state="disabled")
        self.preview.pack(fill=tk.BOTH, expand=True)

        for kind, files in self.groups.items():
            kind_id = self.file_tree.insert("", tk.END, text=kind, open=True)
            for p in files:
                try:
                    stat = p.stat()
                    size_kb = f"{stat.st_size / 1024:.1f} KB"
                    modified = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    size_kb = ""
                    modified = ""
                self.file_tree.insert(
                    kind_id, tk.END, text="", values=(p.name, size_kb, modified),
                    tags=(str(p),),
                )

        footer = ttk.Frame(self.top, padding=8)
        footer.pack(fill=tk.X)
        ttk.Button(footer, text="Export Selected...", command=self._on_export).pack(side=tk.LEFT)
        ttk.Button(footer, text="Close", command=self.top.destroy).pack(side=tk.RIGHT)

    def _selected_path(self) -> Optional[Path]:
        sel = self.file_tree.selection()
        if not sel:
            return None
        tags = self.file_tree.item(sel[0], "tags")
        if not tags:
            return None
        return Path(tags[0])

    def _on_select(self, event=None):
        path = self._selected_path()
        if not path or not path.exists():
            return
        info = parse_discovery_file(path)
        lines: List[str] = []
        lines.append(f"File: {info['path']}")
        lines.append(f"Size: {info['size_bytes']} bytes")
        lines.append(f"Modified: {info['modified']}")
        if info["header"]:
            lines.append("")
            lines.append("Header:")
            for k, v in info["header"].items():
                lines.append(f"  {k}: {v}")
        if info["counts"]:
            lines.append("")
            lines.append("Record counts:")
            for rt, ct in sorted(info["counts"].items()):
                lines.append(f"  {rt}: {ct}")
        if info["records"]:
            lines.append("")
            lines.append("Records:")
            for rec_type, fields in info["records"][:400]:
                lines.append(
                    f"  {rec_type}\t" + "\t".join(fields[1:]) if len(fields) > 1 else f"  {rec_type}"
                )
            if len(info["records"]) > 400:
                lines.append(f"... ({len(info['records']) - 400} more)")
        elif info["raw_preview"]:
            lines.append("")
            lines.append("Raw preview (first 2000 bytes as text):")
            lines.append(info["raw_preview"])
        self.preview.configure(state="normal")
        self.preview.delete("1.0", tk.END)
        self.preview.insert("1.0", "\n".join(lines))
        self.preview.configure(state="disabled")

    def _on_export(self):
        path = self._selected_path()
        if not path or not path.exists():
            messagebox.showinfo("Export", "Select a discovery file first.", parent=self.top)
            return
        target = filedialog.asksaveasfilename(
            title="Export Discovery Log",
            defaultextension=".txt",
            initialfile=f"{path.name}.txt",
            filetypes=[("Text", "*.txt"), ("All Files", "*.*")],
        )
        if not target:
            return
        info = parse_discovery_file(path)
        try:
            with open(target, "w", encoding="utf-8") as f:
                f.write(f"File: {info['path']}\n")
                f.write(f"Size: {info['size_bytes']} bytes\n")
                f.write(f"Modified: {info['modified']}\n\n")
                for k, v in info["header"].items():
                    f.write(f"{k}\t{v}\n")
                for _, fields in info["records"]:
                    f.write("\t".join(fields) + "\n")
                if not info["records"] and info["raw_preview"]:
                    f.write("\n[RAW PREVIEW]\n")
                    f.write(info["raw_preview"])
        except Exception as exc:
            messagebox.showerror("Export", f"Failed to export:\n{exc}", parent=self.top)


class AlertsViewerDialog:
    """Viewer for the SD card ``alert/`` folder.

    Mirrors ``DiscoveryViewerDialog`` - file list on the left, contents
    on the right - but uses the simpler flat-folder layout of alert
    payloads (no Conventional/Trunk split).
    """

    MAX_PREVIEW_BYTES = 8192

    def __init__(self, app: "ScannerManagerApp"):
        self.app = app
        self.top = tk.Toplevel(app.root)
        self.top.title("Alerts")
        self.top.transient(app.root)
        self.top.geometry("900x600")

        sd_folder = (app._path_var.get() or "").strip()
        self.alert_root = Path(sd_folder) / "alert" if sd_folder else None
        self.files = (
            discover_alert_files(self.alert_root)
            if self.alert_root and self.alert_root.exists()
            else []
        )

        header_frame = ttk.Frame(self.top, padding=(8, 8, 8, 0))
        header_frame.pack(fill=tk.X)
        if not self.alert_root or not self.alert_root.exists():
            summary = "No alert folder found. Select a valid SD card folder first."
        elif not self.files:
            summary = (
                f"Alert folder found at {self.alert_root}, but no files are present."
            )
        else:
            summary = (
                f"Alert root: {self.alert_root}    Files: {len(self.files)}"
            )
        ttk.Label(
            header_frame, text=summary, wraplength=860, justify=tk.LEFT
        ).pack(side=tk.LEFT)

        paned = ttk.PanedWindow(self.top, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        left = ttk.Frame(paned)
        paned.add(left, weight=1)
        self.file_tree = ttk.Treeview(
            left,
            columns=("name", "size", "modified"),
            show="tree headings",
            selectmode="browse",
        )
        self.file_tree.heading("name", text="File")
        self.file_tree.heading("size", text="Size")
        self.file_tree.heading("modified", text="Modified")
        self.file_tree.column("#0", width=140, stretch=False)
        self.file_tree.column("name", width=220)
        self.file_tree.column("size", width=80, anchor=tk.E)
        self.file_tree.column("modified", width=160)
        self.file_tree.pack(fill=tk.BOTH, expand=True)
        self.file_tree.bind("<<TreeviewSelect>>", self._on_select)

        right = ttk.Frame(paned)
        paned.add(right, weight=2)
        self.preview = tk.Text(right, wrap="none")
        self.preview.configure(state="disabled")
        self.preview.pack(fill=tk.BOTH, expand=True)

        folders: Dict[str, str] = {}
        if self.alert_root and self.files:
            for p in self.files:
                try:
                    rel_parent = p.parent.relative_to(self.alert_root)
                except Exception:
                    rel_parent = Path(".")
                key = str(rel_parent)
                if key not in folders:
                    label = key if key != "." else "(root)"
                    folders[key] = self.file_tree.insert(
                        "", tk.END, text=label, open=True
                    )
                try:
                    stat = p.stat()
                    size_kb = f"{stat.st_size / 1024:.1f} KB"
                    modified = datetime.fromtimestamp(stat.st_mtime).strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )
                except Exception:
                    size_kb = ""
                    modified = ""
                self.file_tree.insert(
                    folders[key],
                    tk.END,
                    text="",
                    values=(p.name, size_kb, modified),
                    tags=(str(p),),
                )

        footer = ttk.Frame(self.top, padding=8)
        footer.pack(fill=tk.X)
        ttk.Button(
            footer, text="Export Selected...", command=self._on_export
        ).pack(side=tk.LEFT)
        ttk.Button(footer, text="Close", command=self.top.destroy).pack(
            side=tk.RIGHT
        )

    def _selected_path(self) -> Optional[Path]:
        sel = self.file_tree.selection()
        if not sel:
            return None
        tags = self.file_tree.item(sel[0], "tags")
        if not tags:
            return None
        return Path(tags[0])

    def _render_preview(self, path: Path) -> str:
        try:
            stat = path.stat()
        except Exception:
            return f"File: {path}\n(could not stat)"
        lines: List[str] = [
            f"File: {path}",
            f"Size: {stat.st_size} bytes",
            f"Modified: {datetime.fromtimestamp(stat.st_mtime).isoformat(timespec='seconds')}",
            "",
        ]
        try:
            data = path.read_bytes()
        except Exception as exc:
            lines.append(f"(could not read: {exc})")
            return "\n".join(lines)
        chunk = data[: self.MAX_PREVIEW_BYTES]
        try:
            text = chunk.decode("utf-8")
            lines.append(text)
        except UnicodeDecodeError:
            try:
                text = chunk.decode("latin-1", errors="replace")
                lines.append("(shown as Latin-1 — file is not UTF-8)")
                lines.append(text)
            except Exception:
                lines.append("(binary - cannot preview)")
        if len(data) > self.MAX_PREVIEW_BYTES:
            lines.append("")
            lines.append(
                f"... ({len(data) - self.MAX_PREVIEW_BYTES} more bytes)"
            )
        return "\n".join(lines)

    def _on_select(self, event=None):
        path = self._selected_path()
        if not path or not path.exists():
            return
        self.preview.configure(state="normal")
        self.preview.delete("1.0", tk.END)
        self.preview.insert("1.0", self._render_preview(path))
        self.preview.configure(state="disabled")

    def _on_export(self):
        path = self._selected_path()
        if not path or not path.exists():
            messagebox.showinfo(
                "Export", "Select an alert file first.", parent=self.top
            )
            return
        target = filedialog.asksaveasfilename(
            title="Export Alert File",
            initialfile=path.name,
            filetypes=[("All Files", "*.*")],
        )
        if not target:
            return
        try:
            shutil.copy2(path, target)
            self.app._set_status(f"Exported alert file to {target}")
        except Exception as exc:
            messagebox.showerror(
                "Export", f"Failed to export:\n{exc}", parent=self.top
            )


class CoverageHeatmapDialog:
    """Pure-Python coverage heatmap around the active ZIP/City coordinate.

    Renders a 200x200 grid on a Tk canvas. Each pixel's intensity is the
    count of group/site coverage circles that overlap the pixel's real-
    world location. No external deps; uses the existing
    ``lat``/``lon``/``range_miles`` data on groups and sites.
    """

    GRID = 200
    DEFAULT_SPAN_MI = 50.0

    def __init__(self, app: "ScannerManagerApp"):
        self.app = app
        if app._active_coords is None:
            messagebox.showinfo(
                "Coverage Heatmap",
                "Apply a ZIP or City location filter first so the heatmap "
                "has a center point.",
            )
            return
        self.center_lat, self.center_lon = app._active_coords
        self.top = tk.Toplevel(app.root)
        self.top.title("Coverage Heatmap")
        self.top.transient(app.root)

        header = ttk.Frame(self.top, padding=(8, 8, 8, 4))
        header.pack(fill=tk.X)
        ttk.Label(
            header,
            text=(
                f"Center: {self.center_lat:.4f}, {self.center_lon:.4f}    "
                "Span (mi):"
            ),
        ).pack(side=tk.LEFT)
        self.span_var = tk.StringVar(value=str(int(self.DEFAULT_SPAN_MI)))
        entry = ttk.Entry(header, textvariable=self.span_var, width=6)
        entry.pack(side=tk.LEFT, padx=4)
        ttk.Button(header, text="Render", command=self._render).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(header, text="Close", command=self.top.destroy).pack(
            side=tk.RIGHT
        )

        # A square canvas sized to the grid. Each grid cell is one pixel.
        self.canvas = tk.Canvas(
            self.top, width=self.GRID, height=self.GRID,
            background="#101010", highlightthickness=0,
        )
        self.canvas.pack(padx=8, pady=4)
        self.legend = ttk.Label(self.top, text="", padding=(8, 0, 8, 8))
        self.legend.pack(fill=tk.X)

        self._render()

    def _iter_coverage_circles(self):
        """Yield (lat, lon, range_miles) for every group/site with geo."""
        for sys_node in self.app.hpd.systems:
            for site in sys_node.sites:
                if site.lat is not None and site.lon is not None and site.range_miles:
                    yield site.lat, site.lon, site.range_miles
            for group in sys_node.groups:
                if group.lat is not None and group.lon is not None and group.range_miles:
                    yield group.lat, group.lon, group.range_miles

    def _render(self):
        try:
            span = float(self.span_var.get())
        except ValueError:
            span = self.DEFAULT_SPAN_MI
        span = max(5.0, min(span, 500.0))

        circles = list(self._iter_coverage_circles())
        if not circles:
            self.canvas.delete("all")
            self.canvas.create_text(
                self.GRID / 2, self.GRID / 2,
                text="No geo data", fill="#888888",
            )
            self.legend.configure(text="No group/site has lat/lon + range.")
            return

        # Build the intensity grid: for each pixel, count circles that
        # contain it. Precompute each cell's real-world lat/lon.
        mi_per_cell = (span * 2.0) / self.GRID
        # 1 mile in lat direction ~= 1/69.172 degrees
        mi_per_deg_lat = 69.172
        # longitude degree length varies with latitude
        import math
        mi_per_deg_lon = max(1.0, 69.172 * math.cos(math.radians(self.center_lat)))

        half = span
        # Grid cell (row=0 at top = north). Counts saved sparsely by row.
        counts = [[0] * self.GRID for _ in range(self.GRID)]
        max_count = 0
        for (clat, clon, crange) in circles:
            # Pre-filter: skip circles clearly outside the grid bounding box
            dlat_mi = (clat - self.center_lat) * mi_per_deg_lat
            dlon_mi = (clon - self.center_lon) * mi_per_deg_lon
            if abs(dlat_mi) - crange > span or abs(dlon_mi) - crange > span:
                continue
            for r in range(self.GRID):
                pixel_lat_mi = half - (r + 0.5) * mi_per_cell
                lat_diff_mi = pixel_lat_mi - dlat_mi
                if abs(lat_diff_mi) > crange:
                    continue
                dx_max = (crange * crange - lat_diff_mi * lat_diff_mi) ** 0.5
                min_x_mi = dlon_mi - dx_max
                max_x_mi = dlon_mi + dx_max
                col_lo = int(((min_x_mi + half) / mi_per_cell))
                col_hi = int(((max_x_mi + half) / mi_per_cell))
                col_lo = max(0, col_lo)
                col_hi = min(self.GRID - 1, col_hi)
                for c in range(col_lo, col_hi + 1):
                    counts[r][c] += 1
                    if counts[r][c] > max_count:
                        max_count = counts[r][c]

        # Render
        self.canvas.delete("all")
        if max_count == 0:
            self.canvas.create_text(
                self.GRID / 2, self.GRID / 2,
                text="(no coverage overlaps this span)",
                fill="#888888",
            )
            self.legend.configure(text="No coverage circles intersect this span.")
            return

        # Use an image for fast per-pixel rendering.
        img = tk.PhotoImage(width=self.GRID, height=self.GRID)
        self._img = img  # keep reference so GC doesn't drop it
        for r in range(self.GRID):
            row_colors: List[str] = []
            for c in range(self.GRID):
                n = counts[r][c]
                if n == 0:
                    row_colors.append("#101010")
                else:
                    t = n / max_count
                    # Blue (cold) -> green -> yellow -> red gradient
                    if t < 0.5:
                        g = int(t * 2 * 255)
                        b = 255 - g
                        col = f"#{0:02x}{g:02x}{b:02x}"
                    else:
                        u = (t - 0.5) * 2
                        r_c = int(u * 255)
                        g = 255 - int(u * 128)
                        col = f"#{r_c:02x}{g:02x}{0:02x}"
                    row_colors.append(col)
            img.put("{" + " ".join(row_colors) + "}", to=(0, r))
        self.canvas.create_image(0, 0, anchor=tk.NW, image=img)

        # Center cross-hair
        half_px = self.GRID // 2
        self.canvas.create_line(
            half_px - 6, half_px, half_px + 6, half_px, fill="#ffffff"
        )
        self.canvas.create_line(
            half_px, half_px - 6, half_px, half_px + 6, fill="#ffffff"
        )

        self.legend.configure(
            text=(
                f"{len(circles)} coverage circles — "
                f"darkest = no overlap, brightest = {max_count} overlapping "
                f"systems. Span = {span:.0f} mi on each axis."
            )
        )


class CoverageMapDialog:
    """Real-tile coverage map built on tkintermapview.

    Optional: requires ``tkintermapview`` to be installed. The host will
    pull tiles from OpenStreetMap by default; each group/site with
    ``lat``/``lon``/``range_miles`` data is drawn as a circle (polygon
    approximation) plus a labeled marker.
    """

    def __init__(self, app: "ScannerManagerApp"):
        self.app = app
        try:
            import tkintermapview  # type: ignore
        except Exception:
            messagebox.showinfo(
                "Coverage Map",
                "Install the optional 'tkintermapview' package to use this "
                "view (pip install tkintermapview). The pure-Python "
                "'Heatmap...' dialog works without any extra dependency.",
            )
            return

        self.top = tk.Toplevel(app.root)
        self.top.title("Coverage Map")
        self.top.transient(app.root)
        self.top.geometry("900x650")

        header = ttk.Frame(self.top, padding=6)
        header.pack(fill=tk.X)
        ttk.Label(header, text="Tile server:").pack(side=tk.LEFT)
        self.tile_var = tk.StringVar(value="OpenStreetMap")
        tile_cb = ttk.Combobox(
            header, textvariable=self.tile_var, width=24, state="readonly",
            values=("OpenStreetMap", "Google (normal)", "Google (satellite)"),
        )
        tile_cb.pack(side=tk.LEFT, padx=4)
        tile_cb.bind("<<ComboboxSelected>>", lambda _e: self._apply_tile())
        ttk.Button(header, text="Refresh", command=self._redraw).pack(
            side=tk.LEFT, padx=6
        )
        ttk.Button(header, text="Close", command=self.top.destroy).pack(
            side=tk.RIGHT
        )

        self._map_module = tkintermapview
        self.map = tkintermapview.TkinterMapView(
            self.top, width=880, height=580, corner_radius=0
        )
        self.map.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        # Default center: active coords, else the first group/site with
        # geo, else Washington, DC as a harmless fallback.
        center = self._pick_center()
        self.map.set_position(center[0], center[1])
        self.map.set_zoom(8)

        self._polygons: List = []
        self._markers: List = []
        self._redraw()

    def _pick_center(self) -> Tuple[float, float]:
        if self.app._active_coords is not None:
            return self.app._active_coords
        for sys_node in self.app.hpd.systems:
            for site in sys_node.sites:
                if site.lat is not None and site.lon is not None:
                    return (site.lat, site.lon)
            for group in sys_node.groups:
                if group.lat is not None and group.lon is not None:
                    return (group.lat, group.lon)
        return (38.9072, -77.0369)

    def _apply_tile(self):
        choice = self.tile_var.get()
        if choice == "Google (normal)":
            self.map.set_tile_server(
                "https://mt0.google.com/vt/lyrs=m&hl=en&x={x}&y={y}&z={z}",
                max_zoom=22,
            )
        elif choice == "Google (satellite)":
            self.map.set_tile_server(
                "https://mt0.google.com/vt/lyrs=s&hl=en&x={x}&y={y}&z={z}",
                max_zoom=22,
            )
        else:
            self.map.set_tile_server(
                "https://a.tile.openstreetmap.org/{z}/{x}/{y}.png",
                max_zoom=19,
            )

    @staticmethod
    def _circle_points(
        lat: float, lon: float, range_miles: float, sides: int = 48
    ) -> List[Tuple[float, float]]:
        import math
        mi_per_deg_lat = 69.172
        mi_per_deg_lon = max(1.0, 69.172 * math.cos(math.radians(lat)))
        pts: List[Tuple[float, float]] = []
        for i in range(sides):
            theta = (i / sides) * 2.0 * math.pi
            dlat = (range_miles * math.sin(theta)) / mi_per_deg_lat
            dlon = (range_miles * math.cos(theta)) / mi_per_deg_lon
            pts.append((lat + dlat, lon + dlon))
        return pts

    def _redraw(self):
        for p in self._polygons:
            try:
                p.delete()
            except Exception:
                pass
        for m in self._markers:
            try:
                m.delete()
            except Exception:
                pass
        self._polygons.clear()
        self._markers.clear()

        drawn = 0
        for sys_node in self.app.hpd.systems:
            items = []
            for site in sys_node.sites:
                if site.lat is not None and site.lon is not None and site.range_miles:
                    items.append(
                        (site.lat, site.lon, site.range_miles,
                         f"{sys_node.name} - {site.name}".strip(" -"))
                    )
            for group in sys_node.groups:
                if group.lat is not None and group.lon is not None and group.range_miles:
                    items.append(
                        (group.lat, group.lon, group.range_miles,
                         f"{sys_node.name} - {group.name}".strip(" -"))
                    )
            for (lat, lon, r_mi, label) in items:
                pts = self._circle_points(lat, lon, float(r_mi))
                poly = self.map.set_polygon(
                    pts,
                    outline_color="#0a84ff",
                    fill_color="#0a84ff",
                    border_width=1,
                )
                # tkintermapview polygons default to ~40% opacity fill.
                self._polygons.append(poly)
                marker = self.map.set_marker(lat, lon, text=label)
                self._markers.append(marker)
                drawn += 1

        if self.app._active_coords is not None:
            clat, clon = self.app._active_coords
            self._markers.append(
                self.map.set_marker(clat, clon, text="(you)", marker_color_circle="red")
            )

        self.top.title(f"Coverage Map - {drawn} coverage circles")


class EntryEditDialog:
    """Edit name, freq/tgid, mode, tone for a FreqEntry."""

    def __init__(self, parent: tk.Misc, entry: FreqEntry):
        self.entry = entry
        self.result: Optional[Dict[str, Any]] = None
        self.top = tk.Toplevel(parent)
        self.top.title(f"Edit {entry.entry_type}")
        self.top.transient(parent)
        self.top.grab_set()

        rec = entry.record
        frame = ttk.Frame(self.top, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)

        self.name_var = tk.StringVar(value=entry.name)
        ttk.Label(frame, text="Name:").grid(row=0, column=0, sticky=tk.W, pady=2)
        ttk.Entry(frame, textvariable=self.name_var, width=32).grid(row=0, column=1, sticky=tk.EW, padx=4)

        row = 1
        self.identity_var = tk.StringVar(value=rec.get_field(5, ""))
        if entry.entry_type == "C-Freq":
            ttk.Label(frame, text="Frequency (MHz):").grid(row=row, column=0, sticky=tk.W, pady=2)
            try:
                freq_hz = int(self.identity_var.get())
                self.identity_var.set(f"{freq_hz / 1_000_000:.4f}")
            except Exception:
                pass
        else:
            ttk.Label(frame, text="TGID:").grid(row=row, column=0, sticky=tk.W, pady=2)
        ttk.Entry(frame, textvariable=self.identity_var, width=18).grid(row=row, column=1, sticky=tk.W, padx=4)

        row += 1
        raw_mode = rec.get_field(6, "")
        if entry.entry_type == "C-Freq":
            mode_values = MODE_CHOICES_CONV
            self._mode_is_labeled = False
            self.mode_var = tk.StringVar(value=raw_mode)
        else:
            mode_values = MODE_CHOICES_TGID_LABELS
            self._mode_is_labeled = True
            self.mode_var = tk.StringVar(value=tgid_mode_label(raw_mode) if raw_mode else "")
        ttk.Label(frame, text="Mode:").grid(row=row, column=0, sticky=tk.W, pady=2)
        combo_width = 22 if entry.entry_type == "TGID" else 10
        ttk.Combobox(
            frame, textvariable=self.mode_var, values=mode_values, state="readonly",
            width=combo_width,
        ).grid(row=row, column=1, sticky=tk.W, padx=4)
        if entry.entry_type == "TGID":
            ttk.Label(
                frame,
                text="(D) = P25 Phase I FDMA    (T) = P25 Phase II TDMA\n"
                     "The scanner auto-detects D vs T from the trunk system type,\n"
                     "so DIGITAL covers both. TDMA on BT885 has no separate mode.",
                foreground="#555555", justify=tk.LEFT,
            ).grid(row=row, column=2, sticky=tk.W, padx=8)

        self.tone_var = tk.StringVar(value=rec.get_field(7, "") if entry.entry_type == "C-Freq" else "")
        if entry.entry_type == "C-Freq":
            row += 1
            ttk.Label(frame, text="Tone:").grid(row=row, column=0, sticky=tk.W, pady=2)
            ttk.Entry(frame, textvariable=self.tone_var, width=18).grid(row=row, column=1, sticky=tk.W, padx=4)

        row += 1
        btns = ttk.Frame(frame)
        btns.grid(row=row, column=0, columnspan=2, pady=(10, 0))
        ttk.Button(btns, text="OK", command=self._on_ok).pack(side=tk.LEFT, padx=4)
        ttk.Button(btns, text="Cancel", command=self.top.destroy).pack(side=tk.LEFT, padx=4)

        frame.columnconfigure(1, weight=1)
        parent.wait_window(self.top)

    def _on_ok(self):
        identity_text = self.identity_var.get().strip()
        if self.entry.entry_type == "C-Freq":
            try:
                identity_value = str(parse_freq_mhz(identity_text))
            except Exception:
                messagebox.showerror("Invalid", "Frequency must be a number in MHz.", parent=self.top)
                return
        else:
            if not identity_text.isdigit():
                messagebox.showerror("Invalid", "TGID must be an integer.", parent=self.top)
                return
            identity_value = identity_text
        raw_mode = self.mode_var.get()
        stored_mode = tgid_mode_canonical(raw_mode) if getattr(self, "_mode_is_labeled", False) else raw_mode
        self.result = {
            "name": self.name_var.get().strip(),
            "identity_value": identity_value,
            "mode": stored_mode,
            "tone": self.tone_var.get().strip() if self.entry.entry_type == "C-Freq" else None,
        }
        self.top.destroy()


class GroupEditDialog:
    """Edit name / lat / lon / range_miles for a GroupNode."""

    def __init__(self, parent: tk.Misc, group: GroupNode):
        self.group = group
        self.result: Optional[Dict[str, Any]] = None
        self.top = tk.Toplevel(parent)
        self.top.title(f"Edit {group.group_type}")
        self.top.transient(parent)
        self.top.grab_set()

        frame = ttk.Frame(self.top, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)

        self.name_var = tk.StringVar(value=group.name)
        self.lat_var = tk.StringVar(value="" if group.lat is None else f"{group.lat:.6f}")
        self.lon_var = tk.StringVar(value="" if group.lon is None else f"{group.lon:.6f}")
        self.range_var = tk.StringVar(
            value="" if group.range_miles is None else f"{group.range_miles:.1f}"
        )

        for i, (label, var) in enumerate(
            (("Name:", self.name_var), ("Lat:", self.lat_var), ("Lon:", self.lon_var), ("Range (mi):", self.range_var))
        ):
            ttk.Label(frame, text=label).grid(row=i, column=0, sticky=tk.W, pady=2)
            ttk.Entry(frame, textvariable=var, width=26).grid(row=i, column=1, sticky=tk.EW, padx=4)

        btns = ttk.Frame(frame)
        btns.grid(row=4, column=0, columnspan=2, pady=(10, 0))
        ttk.Button(btns, text="OK", command=self._on_ok).pack(side=tk.LEFT, padx=4)
        ttk.Button(btns, text="Cancel", command=self.top.destroy).pack(side=tk.LEFT, padx=4)

        frame.columnconfigure(1, weight=1)
        parent.wait_window(self.top)

    def _on_ok(self):
        def _opt_float(text: str, label: str, lo: float, hi: float) -> Optional[float]:
            s = text.strip()
            if not s:
                return None
            try:
                v = float(s)
            except ValueError as exc:
                raise ValueError(f"{label} must be numeric.") from exc
            if not (lo <= v <= hi):
                raise ValueError(f"{label} out of range.")
            return v

        try:
            lat = _opt_float(self.lat_var.get(), "Lat", -90.0, 90.0)
            lon = _opt_float(self.lon_var.get(), "Lon", -180.0, 180.0)
            range_miles = _opt_float(self.range_var.get(), "Range", 0.0, 5000.0)
        except ValueError as exc:
            messagebox.showerror("Invalid", str(exc), parent=self.top)
            return

        self.result = {
            "name": self.name_var.get().strip(),
            "lat": lat,
            "lon": lon,
            "range_miles": range_miles,
        }
        self.top.destroy()


class SystemEditDialog:
    """Edit a SystemNode's top-level fields (currently just name)."""

    def __init__(self, parent: tk.Misc, system: SystemNode):
        self.system = system
        self.result: Optional[Dict[str, Any]] = None
        self.top = tk.Toplevel(parent)
        self.top.title(f"Edit {system.system_type} system")
        self.top.transient(parent)
        self.top.grab_set()

        frame = ttk.Frame(self.top, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)

        self.name_var = tk.StringVar(value=system.name)
        ttk.Label(frame, text="Name:").grid(row=0, column=0, sticky=tk.W, pady=2)
        ttk.Entry(frame, textvariable=self.name_var, width=36).grid(
            row=0, column=1, sticky=tk.EW, padx=4
        )

        info_lines = [
            f"Type: {system.system_type}",
            f"System ID: {system.system_id}",
            f"Groups: {len(system.groups)}",
            f"Entries: {sum(len(g.entries) for g in system.groups)}",
        ]
        ttk.Label(
            frame, text="\n".join(info_lines), justify=tk.LEFT,
            foreground="#555555",
        ).grid(row=1, column=0, columnspan=2, sticky=tk.W, pady=(8, 0))

        btns = ttk.Frame(frame)
        btns.grid(row=2, column=0, columnspan=2, pady=(10, 0))
        ttk.Button(btns, text="OK", command=self._on_ok).pack(side=tk.LEFT, padx=4)
        ttk.Button(btns, text="Cancel", command=self.top.destroy).pack(side=tk.LEFT, padx=4)

        frame.columnconfigure(1, weight=1)
        parent.wait_window(self.top)

    def _on_ok(self):
        new_name = self.name_var.get().strip()
        if not new_name:
            messagebox.showerror("Invalid", "Name cannot be empty.", parent=self.top)
            return
        self.result = {"name": new_name}
        self.top.destroy()


class RadioReferenceSettingsDialog:
    """Configure the RadioReference SOAP API credentials.

    App key is stored plain in ``app_settings.json``; username + password
    are stored via ``keyring`` (Windows Credential Manager). When
    ``keyring`` is not installed we fall back to an in-memory cache that
    lives only for the current session.
    """

    def __init__(self, parent: tk.Misc, app: "ScannerManagerApp"):
        self.app = app
        self.top = tk.Toplevel(parent)
        self.top.title("RadioReference API")
        self.top.transient(parent)
        self.top.grab_set()
        self.top.geometry("540x340")

        frame = ttk.Frame(self.top, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            frame,
            text=(
                "Premium RadioReference accounts can query the SOAP API "
                "directly. When configured, imports hit the API; otherwise "
                "the app falls through to HTML scraping.\n\n"
                "The app key is stored in app_settings.json; your password "
                "is stored in the Windows Credential Manager (never in our "
                "JSON)."
            ),
            wraplength=500,
            justify=tk.LEFT,
            foreground="#444",
        ).pack(fill=tk.X, pady=(0, 8))

        self._app_key_var = tk.StringVar(value=self.app._rr_app_key())
        self._username_var = tk.StringVar(value=self.app._rr_username())
        self._password_var = tk.StringVar(value=self.app._rr_password())
        self._status_var = tk.StringVar()

        grid = ttk.Frame(frame)
        grid.pack(fill=tk.X)
        ttk.Label(grid, text="App Key").grid(row=0, column=0, sticky=tk.W, pady=3)
        ttk.Entry(grid, textvariable=self._app_key_var, width=44).grid(
            row=0, column=1, sticky=tk.EW, pady=3, padx=(8, 0)
        )
        ttk.Label(grid, text="Username").grid(row=1, column=0, sticky=tk.W, pady=3)
        ttk.Entry(grid, textvariable=self._username_var, width=44).grid(
            row=1, column=1, sticky=tk.EW, pady=3, padx=(8, 0)
        )
        ttk.Label(grid, text="Password").grid(row=2, column=0, sticky=tk.W, pady=3)
        ttk.Entry(
            grid, textvariable=self._password_var, show="*", width=44,
        ).grid(row=2, column=1, sticky=tk.EW, pady=3, padx=(8, 0))
        grid.columnconfigure(1, weight=1)

        status = ttk.Label(
            frame, textvariable=self._status_var,
            foreground="#2a6", wraplength=500,
        )
        status.pack(fill=tk.X, pady=(8, 0))

        btns = ttk.Frame(frame)
        btns.pack(fill=tk.X, pady=(10, 0))
        ttk.Button(btns, text="Test", command=self._on_test).pack(
            side=tk.LEFT, padx=3
        )
        ttk.Button(btns, text="Save", command=self._on_save).pack(
            side=tk.LEFT, padx=3
        )
        ttk.Button(btns, text="Clear", command=self._on_clear).pack(
            side=tk.LEFT, padx=3
        )
        ttk.Button(btns, text="Close", command=self.top.destroy).pack(
            side=tk.RIGHT, padx=3
        )
        parent.wait_window(self.top)

    def _apply_to_settings(self) -> None:
        self.app._app_settings["rr_app_key"] = self._app_key_var.get().strip()
        self.app._app_settings["rr_username"] = self._username_var.get().strip()
        self.app._save_app_settings()
        self.app._set_rr_password(
            self._username_var.get().strip(),
            self._password_var.get(),
        )

    def _on_save(self) -> None:
        self._apply_to_settings()
        self._status_var.set("Saved.")

    def _on_clear(self) -> None:
        self._app_key_var.set("")
        self._username_var.set("")
        self._password_var.set("")
        self._apply_to_settings()
        self._status_var.set("Cleared.")

    def _on_test(self) -> None:
        if rr_api is None:
            self._status_var.set(
                "rr_api module unavailable (install zeep: "
                "pip install -r requirements.txt)."
            )
            return
        self._apply_to_settings()
        client = self.app._rr_client()
        if client is None:
            self._status_var.set(
                "Cannot build client — check credentials and that 'zeep' "
                "is installed."
            )
            return
        try:
            premium = client.is_premium()
            data = client.get_user_data()
            expires = data.get("expirationDate") or data.get("expires") or ""
            if premium:
                self._status_var.set(
                    f"Authenticated. Premium: yes. Expires: {expires or 'n/a'}"
                )
            else:
                self._status_var.set(
                    "Authenticated but account is not Premium — API will "
                    "be disabled."
                )
        except Exception as exc:
            self._status_var.set(f"Test failed: {exc}")


class DataPipelineDialog:
    """Single-pane view of the full data pipeline health: installed
    Uniden tools, RadioReference API authentication state, the active
    Virtual-SD workspace, and a one-click 'Refresh everything' that
    chains RR pull \u2192 Uniden updater \u2192 workspace sync."""

    def __init__(self, parent: tk.Misc, app: "ScannerManagerApp"):
        self.app = app
        self.top = tk.Toplevel(parent)
        self.top.title("Data Pipeline")
        self.top.transient(parent)
        self.top.grab_set()
        self.top.geometry("720x520")

        outer = ttk.Frame(self.top, padding=10)
        outer.pack(fill=tk.BOTH, expand=True)

        self._summary_var = tk.StringVar()
        ttk.Label(
            outer, textvariable=self._summary_var,
            font=("TkDefaultFont", 11, "bold"),
        ).pack(fill=tk.X, pady=(0, 6))

        sections = ttk.Frame(outer)
        sections.pack(fill=tk.BOTH, expand=True)

        tools_lf = ttk.LabelFrame(
            sections, text="Uniden desktop apps", padding=8
        )
        tools_lf.pack(fill=tk.X, pady=3)
        self._tools_text = tk.Text(
            tools_lf, height=4, wrap="word", relief="flat",
            background=self.top.cget("background"),
        )
        self._tools_text.pack(fill=tk.X)
        self._tools_text.configure(state="disabled")

        rr_lf = ttk.LabelFrame(
            sections, text="RadioReference API", padding=8
        )
        rr_lf.pack(fill=tk.X, pady=3)
        self._rr_text = tk.Text(
            rr_lf, height=3, wrap="word", relief="flat",
            background=self.top.cget("background"),
        )
        self._rr_text.pack(fill=tk.X)
        self._rr_text.configure(state="disabled")

        vsd_lf = ttk.LabelFrame(
            sections, text="Virtual SD card / workspaces", padding=8
        )
        vsd_lf.pack(fill=tk.BOTH, expand=True, pady=3)
        self._vsd_text = tk.Text(
            vsd_lf, height=6, wrap="word", relief="flat",
            background=self.top.cget("background"),
        )
        self._vsd_text.pack(fill=tk.BOTH, expand=True)
        self._vsd_text.configure(state="disabled")

        btns = ttk.Frame(outer)
        btns.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(
            btns, text="Refresh everything",
            command=self._on_refresh_everything,
        ).pack(side=tk.LEFT, padx=3)
        ttk.Button(
            btns, text="Uniden Tools...",
            command=self._on_open_tools,
        ).pack(side=tk.LEFT, padx=3)
        ttk.Button(
            btns, text="RR API...",
            command=self._on_open_rr,
        ).pack(side=tk.LEFT, padx=3)
        ttk.Button(
            btns, text="Workspace...",
            command=self._on_open_workspaces,
        ).pack(side=tk.LEFT, padx=3)
        ttk.Button(
            btns, text="Recheck",
            command=self._refresh,
        ).pack(side=tk.LEFT, padx=3)
        ttk.Button(btns, text="Close", command=self.top.destroy).pack(
            side=tk.RIGHT, padx=3
        )

        self._refresh()
        parent.wait_window(self.top)

    # -- health snapshot ----------------------------------------------------

    def _snapshot(self) -> Dict[str, Any]:
        return self.app._pipeline_health_snapshot()

    def _refresh(self) -> None:
        snap = self._snapshot()
        health = snap["health"]
        self._summary_var.set(f"Pipeline health: {health.upper()}")
        # (tkinter Label foreground isn't dynamic on StringVar; set directly)
        self._set_text(
            self._tools_text,
            _format_tools_section(snap["tools"]),
        )
        self._set_text(
            self._rr_text,
            _format_rr_section(snap["rr"]),
        )
        self._set_text(
            self._vsd_text,
            _format_vsd_section(snap["vsd"]),
        )

    def _set_text(self, widget: tk.Text, content: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", tk.END)
        widget.insert("1.0", content)
        widget.configure(state="disabled")

    # -- button handlers ----------------------------------------------------

    def _on_refresh_everything(self) -> None:
        # Currently this just kicks off the push\u2192run\u2192pull pipeline with
        # the default tool. When Phase 3 wiring for RR bulk-refresh is
        # fully in-app we'll prepend that step here.
        self.top.destroy()
        self.app._run_update_pipeline()

    def _on_open_tools(self) -> None:
        self.top.destroy()
        self.app._on_open_uniden_tools()

    def _on_open_rr(self) -> None:
        self.top.destroy()
        self.app._on_open_rr_settings()

    def _on_open_workspaces(self) -> None:
        self.top.destroy()
        self.app._on_manage_workspaces()


def _format_tools_section(info: Dict[str, Any]) -> str:
    rows = info.get("rows") or []
    if not rows:
        return "No Uniden tools detected. Click 'Uniden Tools...' to install one."
    lines: List[str] = []
    for row in rows:
        marker = "\u2713" if row["installed"] else "\u2717"
        ver = row.get("version") or ("" if row["installed"] else "not installed")
        lines.append(f"  {marker} {row['display_name']}  {ver}")
    return "\n".join(lines)


def _format_rr_section(info: Dict[str, Any]) -> str:
    if info.get("zeep_missing"):
        return (
            "zeep package not installed \u2014 API disabled. Install via: "
            "pip install -r requirements.txt"
        )
    if not info.get("configured"):
        return "Not configured. Open 'RR API...' to enter credentials."
    if info.get("premium"):
        return (
            f"Authenticated as {info['username']}. "
            f"Premium expires: {info.get('expires') or 'unknown'}"
        )
    return (
        f"Authenticated as {info['username']}, but account is not Premium. "
        "Falling back to HTML scraping."
    )


def _format_vsd_section(info: Dict[str, Any]) -> str:
    profile = info.get("profile")
    lines: List[str] = []
    if profile is None:
        lines.append("No workspace profile is active.")
    else:
        lines.append(f"Active profile: {profile.get('name') or profile.get('profile_id')}")
        lines.append(f"Workspace: {profile.get('workspace_dir') or ''}")
        last_sync = profile.get("last_sync_at") or "never"
        lines.append(f"Last sync: {last_sync}")
    pending = info.get("pending_events")
    if pending is not None:
        lines.append(f"Pending (uncommitted) events: {pending}")
    card = info.get("card") or {}
    lines.append(
        "Card: " + (
            f"connected ({card.get('target_model') or 'unknown'})"
            if card.get("connected") else "detached"
        )
    )
    return "\n".join(lines)


class RadioReferencePullDialog:
    """Bulk-pull helper for RR Premium subscribers.

    The scraper can't usefully fetch "every system in a county" or
    "every county in a state" as a single URL — those pages are
    navigation hubs. With an authenticated API client we can list
    them and let the user copy the matching RR URLs back into the
    regular import flow.
    """

    def __init__(
        self,
        parent: tk.Misc,
        app: "ScannerManagerApp",
        client: "rr_api.RadioReferenceClient",
    ):
        self.app = app
        self.client = client
        self.top = tk.Toplevel(parent)
        self.top.title("RadioReference — Bulk Pull")
        self.top.transient(parent)
        self.top.grab_set()
        self.top.geometry("720x480")

        outer = ttk.Frame(self.top, padding=10)
        outer.pack(fill=tk.BOTH, expand=True)

        form = ttk.Frame(outer)
        form.pack(fill=tk.X)
        self._mode_var = tk.StringVar(value="county")
        ttk.Radiobutton(
            form, text="County", value="county",
            variable=self._mode_var,
        ).pack(side=tk.LEFT)
        ttk.Radiobutton(
            form, text="State", value="state",
            variable=self._mode_var,
        ).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Label(form, text="ID:").pack(side=tk.LEFT, padx=(14, 4))
        self._id_var = tk.StringVar()
        ttk.Entry(form, textvariable=self._id_var, width=10).pack(
            side=tk.LEFT
        )
        ttk.Button(form, text="Fetch", command=self._on_fetch).pack(
            side=tk.LEFT, padx=8
        )
        ttk.Label(
            outer,
            text=(
                "Numeric IDs: find a county on radioreference.com and look for "
                "'cid=123' in the URL; states likewise use 'sid'."
            ),
            foreground="#666",
        ).pack(fill=tk.X, pady=(2, 6))

        columns = ("title", "kind", "id", "url")
        self.tree = ttk.Treeview(
            outer, columns=columns, show="headings", selectmode="browse",
        )
        for col, w, lbl in (
            ("title", 260, "Title"),
            ("kind", 90, "Kind"),
            ("id", 80, "ID"),
            ("url", 260, "URL"),
        ):
            self.tree.heading(col, text=lbl)
            self.tree.column(col, width=w, anchor=tk.W, stretch=True)
        self.tree.pack(fill=tk.BOTH, expand=True, pady=(6, 0))

        btns = ttk.Frame(outer)
        btns.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(btns, text="Copy URL", command=self._on_copy_url).pack(
            side=tk.LEFT, padx=3
        )
        ttk.Button(btns, text="Close", command=self.top.destroy).pack(
            side=tk.RIGHT, padx=3
        )
        parent.wait_window(self.top)

    def _on_fetch(self) -> None:
        ident = (self._id_var.get() or "").strip()
        if not ident:
            return
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        mode = self._mode_var.get()
        try:
            if mode == "county":
                raw = self.client.get_county_systems(ident)
                imp = self.client.to_hpd_import(
                    raw, source="county", source_id=ident
                )
            else:
                raw = self.client.get_state_systems(ident)
                imp = self.client.to_hpd_import(
                    raw, source="state", source_id=ident
                )
        except Exception as exc:
            messagebox.showerror("RR Pull", str(exc), parent=self.top)
            return
        for entry in imp.entries:
            kind = entry.get("system_kind") or entry.get("type") or mode
            if kind in ("trs", "trs_ref"):
                ident_field = entry.get("sid") or ""
                url = (
                    f"https://www.radioreference.com/db/sid/{ident_field}"
                    if ident_field
                    else ""
                )
            elif kind == "ctid":
                ident_field = entry.get("ctid") or ""
                url = (
                    f"https://www.radioreference.com/db/ctid/{ident_field}"
                    if ident_field
                    else ""
                )
            elif kind == "county_ref":
                ident_field = entry.get("cid") or ""
                url = (
                    f"https://www.radioreference.com/db/county/{ident_field}"
                    if ident_field
                    else ""
                )
            else:
                ident_field = entry.get("id") or ""
                url = ""
            self.tree.insert(
                "", "end",
                values=(
                    entry.get("title") or entry.get("group") or "",
                    kind,
                    ident_field,
                    url,
                ),
            )

    def _on_copy_url(self) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        url = self.tree.item(sel[0], "values")[3]
        if not url:
            return
        self.top.clipboard_clear()
        self.top.clipboard_append(url)
        self.app._set_status(f"Copied: {url}")


class AboutDialog:
    """Small modal showing app name, version, tagline, and a Donate button."""

    def __init__(self, app: "ScannerManagerApp"):
        self.app = app
        self.top = tk.Toplevel(app.root)
        self.top.title(f"About {APP_NAME}")
        self.top.transient(app.root)
        self.top.grab_set()
        self.top.resizable(False, False)

        frm = ttk.Frame(self.top, padding=16)
        frm.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            frm, text=APP_NAME,
            font=("TkDefaultFont", 14, "bold"),
        ).pack(anchor=tk.W)
        ttk.Label(
            frm, text=f"Version {APP_VERSION}",
            foreground="#555",
        ).pack(anchor=tk.W, pady=(2, 8))
        ttk.Label(
            frm, text=APP_TAGLINE, wraplength=420,
        ).pack(anchor=tk.W)
        ttk.Label(
            frm,
            text=(
                "Unofficial, community-built. Not affiliated with or endorsed "
                "by Uniden America Corporation. See DISCLAIMER.md for details."
            ),
            wraplength=420, foreground="#666",
        ).pack(anchor=tk.W, pady=(10, 8))

        links = ttk.Frame(frm)
        links.pack(anchor=tk.W, pady=(2, 8))
        ttk.Button(
            links, text="GitHub",
            command=lambda: webbrowser.open(APP_GITHUB_URL),
        ).pack(side=tk.LEFT, padx=2)
        ttk.Button(
            links, text="Wiki",
            command=lambda: webbrowser.open(APP_WIKI_URL),
        ).pack(side=tk.LEFT, padx=2)
        ttk.Button(
            links, text="Report an Issue",
            command=app._on_help_report_issue,
        ).pack(side=tk.LEFT, padx=2)

        btns = ttk.Frame(frm)
        btns.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(
            btns, text="Donate / Support...",
            command=self._on_donate,
        ).pack(side=tk.LEFT)
        ttk.Button(btns, text="Close", command=self.top.destroy).pack(
            side=tk.RIGHT
        )

    def _on_donate(self) -> None:
        self.top.destroy()
        DonateDialog(self.app)


class DonateDialog:
    """Modal listing PayPal + crypto donation targets with Copy buttons.

    If the optional ``qrcode`` dependency is installed, each crypto row
    also shows a QR code rendered on a Tk canvas. Without ``qrcode`` the
    dialog still works - it just omits the QR art.
    """

    _CRYPTO_ROWS: List[Tuple[str, str, str]] = [
        (
            "Bitcoin (BTC)",
            DONATE_BTC_ADDR,
            f"bitcoin:{DONATE_BTC_ADDR}",
        ),
        (
            "Ethereum (ETH)",
            DONATE_ETH_ADDR,
            f"ethereum:{DONATE_ETH_ADDR}",
        ),
        (
            "Tether (USDT, ERC-20)",
            DONATE_USDT_ERC20_ADDR,
            f"ethereum:{DONATE_USDT_ERC20_ADDR}",
        ),
    ]

    def __init__(self, app: "ScannerManagerApp"):
        self.app = app
        self.top = tk.Toplevel(app.root)
        self.top.title("Support the Project")
        self.top.transient(app.root)
        self.top.grab_set()
        self.top.resizable(False, False)

        frm = ttk.Frame(self.top, padding=16)
        frm.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            frm, text="Caffeinate the developer",
            font=("TkDefaultFont", 13, "bold"),
        ).pack(anchor=tk.W)
        ttk.Label(
            frm,
            text=(
                "If this project saved you time, please consider supporting "
                "my caffeine habit. PayPal is easiest; crypto is also "
                "appreciated. Any amount is genuinely appreciated."
            ),
            wraplength=500, foreground="#555",
        ).pack(anchor=tk.W, pady=(4, 10))

        paypal_row = ttk.Frame(frm)
        paypal_row.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(
            paypal_row, text="PayPal:", width=22, anchor=tk.W,
        ).pack(side=tk.LEFT)
        ttk.Button(
            paypal_row, text=DONATE_PAYPAL_URL,
            command=lambda: webbrowser.open(DONATE_PAYPAL_URL),
        ).pack(side=tk.LEFT)
        ttk.Button(
            paypal_row, text="Copy link",
            command=lambda: self._copy(DONATE_PAYPAL_URL, "PayPal link"),
        ).pack(side=tk.LEFT, padx=4)

        ttk.Separator(frm, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=4)

        self._qr_images: List[Any] = []  # keep GC refs for tk.PhotoImage
        qr_cls = self._load_qr()

        for label, addr, qr_data in self._CRYPTO_ROWS:
            row = ttk.Frame(frm)
            row.pack(fill=tk.X, pady=4)
            ttk.Label(row, text=label, width=22, anchor=tk.W).pack(
                side=tk.LEFT, anchor=tk.N
            )
            right = ttk.Frame(row)
            right.pack(side=tk.LEFT, fill=tk.X, expand=True)

            addr_entry = ttk.Entry(right, width=56)
            addr_entry.insert(0, addr)
            addr_entry.configure(state="readonly")
            addr_entry.pack(side=tk.TOP, anchor=tk.W)

            btns = ttk.Frame(right)
            btns.pack(side=tk.TOP, anchor=tk.W, pady=(2, 0))
            ttk.Button(
                btns, text="Copy address",
                command=lambda a=addr, lbl=label: self._copy(a, lbl),
            ).pack(side=tk.LEFT)
            if qr_cls is not None:
                canvas = self._render_qr(right, qr_cls, qr_data)
                if canvas is not None:
                    canvas.pack(side=tk.RIGHT, padx=8)

        if qr_cls is None:
            ttk.Label(
                frm,
                text=(
                    "(Install the optional 'qrcode' package for scannable "
                    "QR codes next to each address.)"
                ),
                foreground="#888",
            ).pack(anchor=tk.W, pady=(8, 0))

        ttk.Separator(frm, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=(10, 6))
        ttk.Button(
            frm, text="Close", command=self.top.destroy,
        ).pack(side=tk.RIGHT)

    @staticmethod
    def _load_qr():
        try:
            import qrcode  # type: ignore
            return qrcode
        except Exception:
            return None

    def _render_qr(self, parent: tk.Misc, qrcode_mod: Any, data: str):
        """Render ``data`` as a QR code on a Tk canvas. Returns the
        canvas widget or ``None`` on failure.
        """
        try:
            qr = qrcode_mod.QRCode(
                border=1, box_size=1,
                error_correction=qrcode_mod.constants.ERROR_CORRECT_M,
            )
            qr.add_data(data)
            qr.make(fit=True)
            matrix = qr.get_matrix()
        except Exception:
            return None
        if not matrix:
            return None
        rows = len(matrix)
        cols = len(matrix[0])
        pixel = 3
        size_px = cols * pixel
        canvas = tk.Canvas(
            parent, width=size_px, height=size_px,
            background="white", highlightthickness=0,
        )
        img = tk.PhotoImage(width=size_px, height=size_px)
        self._qr_images.append(img)
        for y in range(rows):
            row_colors = []
            for x in range(cols):
                cell = "#000000" if matrix[y][x] else "#ffffff"
                row_colors.extend([cell] * pixel)
            row_str = "{" + " ".join(row_colors) + "}"
            for py in range(y * pixel, (y + 1) * pixel):
                img.put(row_str, to=(0, py))
        canvas.create_image(0, 0, image=img, anchor=tk.NW)
        return canvas

    def _copy(self, value: str, label: str) -> None:
        self.top.clipboard_clear()
        self.top.clipboard_append(value)
        self.app._set_status(f"Copied {label} to clipboard.")


class UnidenInstallerDownloadDialog:
    """Downloads a Uniden installer from the pinned manifest URL, verifies
    its SHA-256, and returns the cached path ready for ``install_tool``.

    Presents a progress bar, a Cancel button, and a secondary
    "Browse for installer..." button so users on corporate networks
    (or those who already have a local copy) can side-load without
    going through the download.
    """

    @classmethod
    def run(
        cls,
        parent: tk.Misc,
        descriptor: Dict[str, Any],
        app: "ScannerManagerApp",
    ) -> Optional[str]:
        dlg = cls(parent, descriptor, app)
        parent.wait_window(dlg.top)
        return dlg.result

    def __init__(
        self,
        parent: tk.Misc,
        descriptor: Dict[str, Any],
        app: "ScannerManagerApp",
    ):
        self.parent = parent
        self.descriptor = descriptor
        self.app = app
        self.result: Optional[str] = None
        self._cancel = False
        self._worker: Optional[threading.Thread] = None

        self.top = tk.Toplevel(parent)
        self.top.title("Download Uniden Installer")
        self.top.transient(parent)
        self.top.grab_set()
        self.top.geometry("520x260")

        frm = ttk.Frame(self.top, padding=12)
        frm.pack(fill=tk.BOTH, expand=True)

        display_name = descriptor.get("display_name") or descriptor.get("tool_id")
        version = descriptor.get("version") or ""
        header = f"{display_name}"
        if version:
            header += f"  (v{version})"
        ttk.Label(frm, text=header, font=("TkDefaultFont", 11, "bold")).pack(
            anchor=tk.W, pady=(0, 4)
        )
        ttk.Label(
            frm,
            text=(
                "Scanner Manager does not redistribute Uniden's installers. "
                "With your permission it can download the installer directly "
                "from Uniden's CDN, verify the file against a pinned SHA-256 "
                "hash, and cache it for future use."
            ),
            wraplength=480, justify=tk.LEFT, foreground="#555",
        ).pack(anchor=tk.W, pady=(0, 6))

        url = descriptor.get("download_url") or ""
        url_row = ttk.Frame(frm)
        url_row.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(url_row, text="Source:", width=10).pack(side=tk.LEFT)
        url_entry = ttk.Entry(url_row)
        url_entry.insert(0, url)
        url_entry.configure(state="readonly")
        url_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.status_var = tk.StringVar(value="Ready.")
        ttk.Label(
            frm, textvariable=self.status_var, foreground="#333",
        ).pack(anchor=tk.W, pady=(4, 2))

        self.progress = ttk.Progressbar(
            frm, mode="determinate", length=480, maximum=100
        )
        self.progress.pack(fill=tk.X, pady=(0, 6))

        btns = ttk.Frame(frm)
        btns.pack(fill=tk.X, pady=(6, 0))
        self.download_btn = ttk.Button(
            btns, text="Download & Verify",
            command=self._start_download,
        )
        self.download_btn.pack(side=tk.LEFT)
        ttk.Button(
            btns, text="Browse for installer...",
            command=self._on_browse,
        ).pack(side=tk.LEFT, padx=6)
        ttk.Button(
            btns, text="Open vendor page",
            command=self._on_open_vendor,
        ).pack(side=tk.LEFT, padx=6)
        self.close_btn = ttk.Button(
            btns, text="Cancel", command=self._on_close,
        )
        self.close_btn.pack(side=tk.RIGHT)
        self.top.protocol("WM_DELETE_WINDOW", self._on_close)

    def _start_download(self) -> None:
        if self._worker and self._worker.is_alive():
            return
        self.download_btn.configure(state=tk.DISABLED)
        self.status_var.set("Starting download...")
        self._cancel = False

        def progress_cb(fetched: int, total: int) -> bool:
            if self._cancel:
                return False
            pct = 0.0
            if total > 0:
                pct = min(100.0, fetched * 100.0 / total)
            self.top.after(0, self._update_progress, fetched, total, pct)
            return True

        def worker() -> None:
            try:
                path = uniden_tools.download_installer(
                    self.descriptor, progress_cb=progress_cb,
                )
                self.top.after(0, self._on_download_ok, str(path))
            except KeyboardInterrupt:
                self.top.after(0, self._on_cancelled)
            except Exception as exc:
                self.top.after(0, self._on_download_failed, str(exc))

        self._worker = threading.Thread(target=worker, daemon=True)
        self._worker.start()

    def _update_progress(self, fetched: int, total: int, pct: float) -> None:
        self.progress["value"] = pct
        if total > 0:
            self.status_var.set(
                f"Downloading... {fetched/1024/1024:.1f} / "
                f"{total/1024/1024:.1f} MB ({pct:.1f}%)"
            )
        else:
            self.status_var.set(
                f"Downloading... {fetched/1024/1024:.1f} MB"
            )

    def _on_download_ok(self, path: str) -> None:
        self.progress["value"] = 100.0
        self.status_var.set(
            f"Verified and cached: {path}"
        )
        self.result = path
        self.close_btn.configure(text="Close")
        self.app._set_status(
            f"Installer cached and verified at {path}"
        )
        # Close automatically so the Install flow can continue.
        self.top.after(600, self.top.destroy)

    def _on_download_failed(self, message: str) -> None:
        self.download_btn.configure(state=tk.NORMAL)
        self.status_var.set("Download failed.")
        messagebox.showerror(
            "Download failed", message, parent=self.top
        )

    def _on_cancelled(self) -> None:
        self.download_btn.configure(state=tk.NORMAL)
        self.status_var.set("Cancelled.")
        self.progress["value"] = 0

    def _on_browse(self) -> None:
        path = filedialog.askopenfilename(
            title="Select installer (setup.exe or .zip)",
            filetypes=[
                ("Installer", "*.exe"),
                ("Zip archive", "*.zip"),
                ("All Files", "*.*"),
            ],
            parent=self.top,
        )
        if not path:
            return
        p = Path(path)
        expected = (self.descriptor.get("sha256") or "").strip().lower()
        if expected and not uniden_tools.verify_installer(p, expected):
            if not messagebox.askyesno(
                "Hash mismatch",
                (
                    "The selected file's SHA-256 does not match the value "
                    "pinned for this tool. Run it anyway?\n\n"
                    "Only say Yes if you trust the source."
                ),
                parent=self.top,
            ):
                return
        self.result = str(p)
        self.top.destroy()

    def _on_open_vendor(self) -> None:
        url = self.descriptor.get("vendor_page") or self.descriptor.get(
            "download_url"
        )
        if url:
            webbrowser.open(url)

    def _on_close(self) -> None:
        if self._worker and self._worker.is_alive():
            self._cancel = True
            self.status_var.set("Cancelling...")
            return
        self.top.destroy()


class UnidenToolsDialog:
    """Registry of installed / installable Uniden desktop apps.

    Rows show: display name, scanner family, installed path + version, and
    action buttons for Launch / Launch + Auto-Sync / Install / Open data
    folder. Overrides get persisted into ``app_settings.json`` under
    ``uniden_tools_overrides``.
    """

    def __init__(self, parent: tk.Misc, app: "ScannerManagerApp"):
        self.app = app
        self.top = tk.Toplevel(parent)
        self.top.title("Uniden Tools")
        self.top.transient(parent)
        self.top.grab_set()
        self.top.geometry("820x360")

        frame = ttk.Frame(self.top, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            frame,
            text=(
                "Uniden ships two scanner companion apps that both read from "
                "RadioReference. Scanner Manager detects their installs and "
                "orchestrates the push \u2192 update \u2192 pull cycle for you."
            ),
            wraplength=780,
            justify=tk.LEFT,
            foreground="#444",
        ).pack(fill=tk.X, pady=(0, 6))

        if not IS_WINDOWS:
            ttk.Label(
                frame,
                text=(
                    "\u26a0  Uniden Sentinel and the BT885 Update Manager are "
                    "Windows-only applications. This panel cannot launch or "
                    "install them on "
                    f"{'macOS' if IS_MACOS else 'this platform'}. Everything "
                    "else in Scanner Manager (HPD editing, RadioReference "
                    "import, ZIP/GPS simulation, workspaces) works here; you "
                    "just won't be able to drive Uniden's vendor tools from "
                    "this host. Run Scanner Manager on Windows to use them."
                ),
                wraplength=780,
                justify=tk.LEFT,
                foreground="#a33",
            ).pack(fill=tk.X, pady=(0, 6))

        columns = ("name", "family", "version", "path")
        self.tree = ttk.Treeview(
            frame, columns=columns, show="headings",
            height=6, selectmode="browse",
        )
        headings = {
            "name": "Tool",
            "family": "Scanner Family",
            "version": "Version",
            "path": "Install Path",
        }
        widths = {"name": 180, "family": 220, "version": 90, "path": 300}
        for col in columns:
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, width=widths[col], anchor=tk.W, stretch=True)
        self.tree.pack(fill=tk.BOTH, expand=True)
        self.tree.tag_configure("missing", foreground="#a33")

        self._tools: List["uniden_tools.UnidenTool"] = []
        self._refresh()

        btns = ttk.Frame(frame)
        btns.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(btns, text="Launch", command=self._on_launch).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(
            btns, text="Launch + Auto-Sync",
            command=self._on_launch_and_sync,
        ).pack(side=tk.LEFT, padx=4)
        ttk.Button(
            btns, text="Install...", command=self._on_install
        ).pack(side=tk.LEFT, padx=4)
        ttk.Button(
            btns, text="Override Path...", command=self._on_override
        ).pack(side=tk.LEFT, padx=4)
        ttk.Button(
            btns, text="Open Data Folder",
            command=self._on_open_data_dir,
        ).pack(side=tk.LEFT, padx=4)
        ttk.Button(btns, text="Refresh", command=self._refresh).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(btns, text="Close", command=self.top.destroy).pack(
            side=tk.RIGHT, padx=4
        )
        parent.wait_window(self.top)

    def _refresh(self) -> None:
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        self._tools = uniden_tools.detect_installed_tools(
            repo_root=self.app._script_dir,
            overrides=self.app._tool_overrides(),
        )
        for tool in self._tools:
            tags = () if tool.installed else ("missing",)
            version = tool.version or ("installed" if tool.installed else "not installed")
            self.tree.insert(
                "", "end", iid=tool.tool_id,
                values=(
                    tool.display_name,
                    tool.scanner_family,
                    version,
                    tool.exe_path or "\u2014",
                ),
                tags=tags,
            )

    def _selected_tool(self) -> Optional["uniden_tools.UnidenTool"]:
        sel = self.tree.selection()
        if not sel:
            return None
        tid = sel[0]
        for tool in self._tools:
            if tool.tool_id == tid:
                return tool
        return None

    def _on_launch(self) -> None:
        tool = self._selected_tool()
        if tool is None:
            messagebox.showinfo("Launch", "Select a tool first.", parent=self.top)
            return
        if not tool.installed:
            messagebox.showinfo(
                "Not installed",
                "This tool is not installed yet. Use Install... to run the "
                "bundled installer.",
                parent=self.top,
            )
            return
        try:
            uniden_tools.run_tool(tool, wait=False)
            self.app._set_status(f"Launched {tool.display_name}.")
        except Exception as exc:
            messagebox.showerror("Launch failed", str(exc), parent=self.top)

    def _on_launch_and_sync(self) -> None:
        tool = self._selected_tool()
        if tool is None:
            messagebox.showinfo("Launch", "Select a tool first.", parent=self.top)
            return
        if not tool.installed:
            messagebox.showinfo(
                "Not installed",
                "Install the tool first.",
                parent=self.top,
            )
            return
        self.top.destroy()
        self.app._run_update_pipeline(tool_id=tool.tool_id)

    def _on_install(self) -> None:
        tool = self._selected_tool()
        if tool is None:
            messagebox.showinfo("Install", "Select a tool first.", parent=self.top)
            return
        # Prefer a cached / local copy if we already have one; otherwise
        # route the user through the download dialog which will fetch,
        # verify, and hand back a runnable path.
        if not tool.bundled_installer:
            resolution = uniden_tools.resolve_installer(tool.tool_id)
            if resolution.descriptor is None:
                messagebox.showerror(
                    "No installer",
                    "No installer manifest entry was found for this tool "
                    "and no local copy is available. Drop the setup files "
                    "into the scanner-manager folder and try again.",
                    parent=self.top,
                )
                return
            installer_path = UnidenInstallerDownloadDialog.run(
                self.top, resolution.descriptor, self.app,
            )
            if installer_path is None:
                return
            tool.bundled_installer = installer_path
        if not messagebox.askyesno(
            "Install",
            (
                f"Launch the installer for {tool.display_name}?\n\n"
                f"{tool.bundled_installer}\n\n"
                "Windows will prompt for elevation."
            ),
            parent=self.top,
        ):
            return
        try:
            uniden_tools.install_tool(tool, wait=True)
        except Exception as exc:
            messagebox.showerror("Install failed", str(exc), parent=self.top)
            return
        self._refresh()

    def _on_override(self) -> None:
        tool = self._selected_tool()
        if tool is None:
            messagebox.showinfo(
                "Override", "Select a tool first.", parent=self.top
            )
            return
        path = filedialog.askopenfilename(
            title=f"Select {tool.display_name} executable",
            filetypes=[("Executable", "*.exe"), ("All Files", "*.*")],
            parent=self.top,
        )
        if not path:
            return
        overrides = self.app._tool_overrides()
        overrides[tool.tool_id] = path
        self.app._app_settings["uniden_tools_overrides"] = overrides
        self.app._save_app_settings()
        self._refresh()

    def _on_open_data_dir(self) -> None:
        tool = self._selected_tool()
        if tool is None:
            messagebox.showinfo(
                "Open", "Select a tool first.", parent=self.top
            )
            return
        target = tool.data_dir or (
            os.path.dirname(tool.exe_path) if tool.exe_path else None
        )
        if not target or not os.path.isdir(target):
            messagebox.showinfo(
                "Open", "No data folder discovered yet.", parent=self.top
            )
            return
        try:
            open_in_file_manager(target)
        except Exception as exc:
            messagebox.showerror("Open", str(exc), parent=self.top)


class WorkspaceManagerDialog:
    """Pick an existing workspace profile, clone a new one, or remove."""

    def __init__(self, parent: tk.Misc, app: "ScannerManagerApp"):
        self.app = app
        self.result: Optional[Dict[str, Any]] = None
        self.top = tk.Toplevel(parent)
        self.top.title("Scanner Workspaces")
        self.top.transient(parent)
        self.top.grab_set()
        self.top.geometry("760x420")

        frame = ttk.Frame(self.top, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)

        info = ttk.Label(
            frame,
            text=(
                "Workspaces let you clone the SD card into a local folder so "
                "you can keep editing while the card is out. Each profile "
                "remembers the card that created it so sync can find its way home."
            ),
            wraplength=720,
            justify=tk.LEFT,
            foreground="#444",
        )
        info.pack(fill=tk.X, pady=(0, 8))

        columns = ("name", "target", "workspace", "last_sync", "card")
        self.tree = ttk.Treeview(
            frame, columns=columns, show="headings", height=10, selectmode="browse"
        )
        headings = {
            "name": "Profile",
            "target": "Target Model",
            "workspace": "Workspace",
            "last_sync": "Last Sync",
            "card": "Card Connected?",
        }
        widths = {
            "name": 160, "target": 120,
            "workspace": 260, "last_sync": 120, "card": 90,
        }
        for col in columns:
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, width=widths[col], anchor=tk.W, stretch=True)
        self.tree.pack(fill=tk.BOTH, expand=True)

        self._populate()

        btns = ttk.Frame(frame)
        btns.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(btns, text="Open Selected", command=self._on_open).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(btns, text="Clone from current SD...",
                   command=self._on_clone).pack(side=tk.LEFT, padx=4)
        ttk.Button(btns, text="Remove Selected", command=self._on_remove).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(btns, text="Close", command=self.top.destroy).pack(
            side=tk.RIGHT, padx=4
        )
        parent.wait_window(self.top)

    def _populate(self) -> None:
        for item_id in self.tree.get_children():
            self.tree.delete(item_id)
        ident = self.app._detect_card_identity()
        for profile in self.app._global_meta.list_profiles():
            matches_card = bool(
                ident.has_any_id()
                and (
                    (ident.volume_serial and ident.volume_serial == profile.get("card_volume_serial"))
                    or (ident.content_fingerprint and ident.content_fingerprint == profile.get("content_fingerprint"))
                )
            )
            self.tree.insert(
                "", "end",
                iid=profile["profile_id"],
                values=(
                    profile.get("name") or "(unnamed)",
                    profile.get("target_model") or "—",
                    profile.get("workspace_dir") or "—",
                    profile.get("last_sync_at") or "never",
                    "yes" if matches_card else "no",
                ),
            )

    def _selected_profile_id(self) -> Optional[str]:
        sel = self.tree.selection()
        return sel[0] if sel else None

    def _on_open(self) -> None:
        pid = self._selected_profile_id()
        if not pid:
            messagebox.showinfo("Open", "Select a profile first.", parent=self.top)
            return
        self.result = {"action": "open", "profile_id": pid}
        self.top.destroy()

    def _on_remove(self) -> None:
        pid = self._selected_profile_id()
        if not pid:
            messagebox.showinfo(
                "Remove", "Select a profile to remove.", parent=self.top
            )
            return
        profile = self.app._global_meta.get_profile(pid)
        if not messagebox.askyesno(
            "Remove profile",
            f"Remove profile '{(profile or {}).get('name') or pid}' from the "
            "registry?\n\nThe workspace folder is NOT deleted from disk.",
            parent=self.top,
        ):
            return
        self.result = {"action": "remove", "profile_id": pid}
        self.top.destroy()

    def _on_clone(self) -> None:
        card_root = (self.app._path_var.get() or "").strip()
        if not card_root or not os.path.isdir(card_root):
            messagebox.showerror(
                "Clone",
                "Point the SD Card Folder at a real card first.",
                parent=self.top,
            )
            return
        default_name = (
            sdcard.probe_card_identity(card_root).target_model
            or "Beartracker Workspace"
        )
        from tkinter import simpledialog
        name = simpledialog.askstring(
            "Clone SD",
            "Name for this scanner profile:",
            initialvalue=default_name,
            parent=self.top,
        )
        if not name:
            return
        initial_dir = os.path.join(
            os.path.dirname(card_root) or os.path.expanduser("~"),
            "scanner-workspaces",
        )
        os.makedirs(initial_dir, exist_ok=True)
        ws_dir = filedialog.askdirectory(
            title="Choose a folder to hold the workspace (a new subfolder will be created)",
            initialdir=initial_dir,
            parent=self.top,
        )
        if not ws_dir:
            return
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_") or "workspace"
        workspace_dir = os.path.join(ws_dir, safe_name)
        if os.path.exists(workspace_dir) and os.listdir(workspace_dir):
            if not messagebox.askyesno(
                "Clone",
                f"{workspace_dir} already exists and is not empty. "
                "Cloning may overwrite files. Continue?",
                parent=self.top,
            ):
                return
        self.result = {
            "action": "clone",
            "name": name,
            "workspace_dir": workspace_dir,
        }
        self.top.destroy()


class SyncConflictDialog:
    """3-way conflict resolution dialog for Sync pull/push.

    For each conflicting file the user picks ``take_card``,
    ``take_workspace``, or ``skip``. Non-conflicting files are shown as
    context so the user understands what just happened.
    """

    def __init__(
        self,
        parent: tk.Misc,
        *,
        report: "sdcard.SyncReport",
        diffs: List["sdcard.FileDiff"],
        direction: str,
    ):
        self.report = report
        self.diffs = diffs
        self.direction = direction
        self.result: Optional[Dict[str, Any]] = None
        self.top = tk.Toplevel(parent)
        self.top.title(f"Sync {direction} — resolve conflicts")
        self.top.transient(parent)
        self.top.grab_set()
        self.top.geometry("820x520")

        frame = ttk.Frame(self.top, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            frame,
            text=(
                "These files were modified on both sides since the last sync. "
                "Choose which version wins for each, or skip to leave the file alone."
            ),
            wraplength=780,
            justify=tk.LEFT,
        ).pack(fill=tk.X, pady=(0, 6))

        self.tree = ttk.Treeview(
            frame, columns=("file", "decision"), show="headings",
            height=14, selectmode="extended",
        )
        self.tree.heading("file", text="File")
        self.tree.heading("decision", text="Decision")
        self.tree.column("file", width=540, anchor=tk.W)
        self.tree.column("decision", width=220, anchor=tk.W)
        self.tree.pack(fill=tk.BOTH, expand=True)

        self._decisions: Dict[str, str] = {}
        for rel in report.conflicts:
            self._decisions[rel] = "skip"
            self.tree.insert("", "end", iid=rel, values=(rel, "skip"))

        btns = ttk.Frame(frame)
        btns.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(
            btns, text="Take CARD version",
            command=lambda: self._apply_to_selection("take_card"),
        ).pack(side=tk.LEFT, padx=4)
        ttk.Button(
            btns, text="Take WORKSPACE version",
            command=lambda: self._apply_to_selection("take_workspace"),
        ).pack(side=tk.LEFT, padx=4)
        ttk.Button(
            btns, text="Skip",
            command=lambda: self._apply_to_selection("skip"),
        ).pack(side=tk.LEFT, padx=4)
        ttk.Button(btns, text="Apply & Close", command=self._on_ok).pack(
            side=tk.RIGHT, padx=4
        )
        ttk.Button(btns, text="Cancel", command=self.top.destroy).pack(
            side=tk.RIGHT, padx=4
        )
        parent.wait_window(self.top)

    def _apply_to_selection(self, decision: str) -> None:
        sel = self.tree.selection() or tuple(self.tree.get_children())
        for iid in sel:
            self._decisions[iid] = decision
            current = list(self.tree.item(iid, "values"))
            current[1] = decision
            self.tree.item(iid, values=current)

    def _on_ok(self) -> None:
        self.result = {"decisions": dict(self._decisions)}
        self.top.destroy()


class ChangesPanelDialog:
    """Reverse-chronological Changes panel backed by the MetaStore event log.

    Supports filters, per-row Revert, multi-select Revert, Revert to this
    point, and a details drawer showing before/after.
    """

    _OP_LABELS = {
        OP_EDIT_ENTRY: "Edit entry",
        OP_EDIT_GROUP: "Edit group",
        OP_EDIT_SYSTEM: "Edit system",
        OP_ADD_ENTRY: "Add entry",
        OP_ADD_GROUP: "Add group",
        OP_DELETE_ENTRY: "Delete entry",
        OP_DELETE_GROUP: "Delete group",
        OP_DELETE_SYSTEM: "Delete system",
        OP_SET_AVOID: "Avoid",
        OP_SET_SERVICE: "Service type",
        OP_IMPORT_APPLY: "Import",
        OP_LINK_RR: "Link RR",
        OP_UNLINK_RR: "Unlink RR",
        OP_EXTERNAL_CHANGE: "External change",
        OP_REVERT: "Revert",
        OP_BULK_REVERT: "Bulk revert",
    }

    def __init__(self, app: "ScannerManagerApp"):
        self.app = app
        self.top = tk.Toplevel(app.root)
        self.top.title(
            f"Changes - {os.path.basename(app.hpd.filepath)}"
            if app.hpd.filepath
            else "Changes"
        )
        self.top.transient(app.root)
        self.top.geometry("1000x620")

        # -- filter bar --
        filters = ttk.Frame(self.top, padding=8)
        filters.pack(fill=tk.X)
        ttk.Label(filters, text="Filter:").pack(side=tk.LEFT)
        self.op_filter_var = tk.StringVar(value="All")
        op_vals = ["All"] + list(self._OP_LABELS.values())
        ttk.Combobox(
            filters, textvariable=self.op_filter_var, values=op_vals,
            state="readonly", width=16,
        ).pack(side=tk.LEFT, padx=4)
        self.source_filter_var = tk.StringVar(value="All")
        ttk.Combobox(
            filters, textvariable=self.source_filter_var,
            values=["All", "manual", "bulk", "rr_category", "rr_ctid", "rr_sid", "rr_callsign"],
            state="readonly", width=14,
        ).pack(side=tk.LEFT, padx=4)
        self.status_filter_var = tk.StringVar(value="Active")
        ttk.Combobox(
            filters, textvariable=self.status_filter_var,
            values=["Active", "Reverted", "All"],
            state="readonly", width=10,
        ).pack(side=tk.LEFT, padx=4)
        self.committed_filter_var = tk.StringVar(value="All")
        ttk.Combobox(
            filters, textvariable=self.committed_filter_var,
            values=["All", "Saved", "Pending"],
            state="readonly", width=10,
        ).pack(side=tk.LEFT, padx=4)
        self.search_var = tk.StringVar()
        ttk.Label(filters, text="Search:").pack(side=tk.LEFT, padx=(12, 2))
        search_entry = ttk.Entry(filters, textvariable=self.search_var, width=22)
        search_entry.pack(side=tk.LEFT, padx=2)
        search_entry.bind("<Return>", lambda e: self._refresh())
        ttk.Button(filters, text="Apply", command=self._refresh).pack(side=tk.LEFT, padx=4)
        for var in (
            self.op_filter_var,
            self.source_filter_var,
            self.status_filter_var,
            self.committed_filter_var,
        ):
            var.trace_add("write", lambda *args: self._refresh())

        # -- main treeview --
        frame = ttk.Frame(self.top)
        frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)
        cols = ("ts", "op", "target", "source", "status", "saved", "summary")
        self.tree = ttk.Treeview(
            frame, columns=cols, show="headings", selectmode="extended"
        )
        self.tree.heading("ts", text="Time")
        self.tree.heading("op", text="Op")
        self.tree.heading("target", text="Target")
        self.tree.heading("source", text="Source")
        self.tree.heading("status", text="Status")
        self.tree.heading("saved", text="Saved")
        self.tree.heading("summary", text="Summary")
        self.tree.column("ts", width=140)
        self.tree.column("op", width=90)
        self.tree.column("target", width=180)
        self.tree.column("source", width=90)
        self.tree.column("status", width=70)
        self.tree.column("saved", width=70, anchor=tk.CENTER)
        self.tree.column("summary", width=320)
        self.tree.tag_configure("pending", background="#fff7d6")
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.tree.yview)
        sb.pack(side=tk.LEFT, fill=tk.Y)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._refresh_details())

        # -- details drawer --
        details_frame = ttk.LabelFrame(self.top, text="Details", padding=6)
        details_frame.pack(fill=tk.BOTH, expand=False, padx=8, pady=(0, 4))
        self.details_text = tk.Text(details_frame, height=8, wrap="word")
        self.details_text.pack(fill=tk.BOTH, expand=True)
        self.details_text.configure(state="disabled")

        # -- bottom buttons --
        bottom = ttk.Frame(self.top, padding=8)
        bottom.pack(fill=tk.X)
        ttk.Button(bottom, text="Revert selected", command=self._on_revert_selected).pack(side=tk.LEFT, padx=4)
        ttk.Button(bottom, text="Revert to this point", command=self._on_revert_to_point).pack(side=tk.LEFT, padx=4)
        ttk.Button(bottom, text="Refresh", command=self._refresh).pack(side=tk.LEFT, padx=4)
        ttk.Button(
            bottom, text="Open Data Pipeline...",
            command=self._on_open_pipeline_for_selected,
        ).pack(side=tk.LEFT, padx=4)
        ttk.Button(bottom, text="Close", command=self.top.destroy).pack(side=tk.RIGHT, padx=4)

        self._refresh()

    def _refresh(self):
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        if self.app._meta is None:
            return
        op_filter = self.op_filter_var.get()
        src_filter = self.source_filter_var.get()
        status_filter = self.status_filter_var.get()
        committed_filter = self.committed_filter_var.get()
        search = self.search_var.get().strip().lower()
        pending_count = 0
        saved_count = 0
        for event in self.app._meta.events_reverse():
            op_label = self._OP_LABELS.get(event.op, event.op)
            if op_filter != "All" and op_filter != op_label:
                continue
            if src_filter != "All" and src_filter != event.source:
                continue
            if status_filter == "Active" and event.reverted:
                continue
            if status_filter == "Reverted" and not event.reverted:
                continue
            if committed_filter == "Saved" and not event.committed:
                continue
            if committed_filter == "Pending" and event.committed:
                continue
            haystack = " ".join([
                event.target_name or "",
                event.summary or "",
                event.target_id or "",
            ]).lower()
            if search and search not in haystack:
                continue
            status = "reverted" if event.reverted else "active"
            saved_label = "yes" if event.committed else "pending"
            tags: Tuple[str, ...] = () if event.committed else ("pending",)
            if event.committed:
                saved_count += 1
            else:
                pending_count += 1
            self.tree.insert(
                "",
                tk.END,
                iid=event.event_id,
                values=(
                    event.ts,
                    op_label,
                    event.target_name or event.target_id,
                    event.source,
                    status,
                    saved_label,
                    event.summary,
                ),
                tags=tags,
            )
        dirty = getattr(self.app.hpd, "has_changes", False)
        self.top.title(
            (
                f"Changes - {os.path.basename(self.app.hpd.filepath)}"
                if self.app.hpd.filepath
                else "Changes"
            )
            + (
                f"  [{pending_count} pending, {saved_count} saved"
                + (" * unsaved" if dirty else "")
                + "]"
            )
        )
        self._refresh_details()

    def _refresh_details(self):
        self.details_text.configure(state="normal")
        self.details_text.delete("1.0", tk.END)
        sel = self.tree.selection()
        if not sel or self.app._meta is None:
            self.details_text.configure(state="disabled")
            return
        event = self.app._meta.get_event(sel[0])
        if event is None:
            self.details_text.configure(state="disabled")
            return
        import json as _json
        commit_line = (
            f"Saved:  yes (at {event.committed_at})"
            if event.committed
            else "Saved:  pending (not yet written to HPD)"
        )
        txt = (
            f"Event: {event.event_id}  (txn {event.txn_id})\n"
            f"Op:    {event.op}\n"
            f"Target: {event.target_name or event.target_id}\n"
            f"Time:   {event.ts}\n"
            f"Source: {event.source}\n"
            f"Status: {'reverted' if event.reverted else 'active'}\n"
            f"{commit_line}\n"
            f"Summary: {event.summary}\n"
            f"----\n"
            f"{_json.dumps(event.payload, indent=2, default=str)}"
        )
        self.details_text.insert("1.0", txt)
        self.details_text.configure(state="disabled")

    def _selected_events(self) -> List[Event]:
        if self.app._meta is None:
            return []
        result: List[Event] = []
        for iid in self.tree.selection():
            ev = self.app._meta.get_event(iid)
            if ev is not None:
                result.append(ev)
        return result

    def _on_open_pipeline_for_selected(self) -> None:
        """Deep-link into the Data Pipeline dialog for the selected
        event. Primarily useful for ``OP_EXTERNAL_CHANGE`` rows (the
        card-side changes introduced by Uniden's tools), where the user
        wants to see which tool ran and when the workspace last synced."""
        self.app._on_open_data_pipeline()

    def _on_revert_selected(self):
        events = self._selected_events()
        if not events:
            messagebox.showinfo("Revert", "Select one or more changes.", parent=self.top)
            return
        events.sort(key=lambda e: e.ts, reverse=True)
        messages: List[str] = []
        for event in events:
            ok, msg = self.app.revert_event(event)
            if not ok and "cascade" in msg.lower():
                choice = messagebox.askyesnocancel(
                    "Later changes exist",
                    f"#{event.event_id} ({event.op}) has later changes on the same target.\n\n"
                    f"{msg}\n\n"
                    "Yes = Revert the whole chain (cascade)\n"
                    "No = Force revert this one only (may leave inconsistent state)\n"
                    "Cancel = Skip",
                    parent=self.top,
                )
                if choice is None:
                    messages.append(f"#{event.event_id}: skipped")
                    continue
                if choice:
                    ok, msg = self.app.revert_cascade(event)
                else:
                    ok, msg = self.app.revert_event(event, force=True)
            messages.append(f"#{event.event_id}: {msg}")
        self.app._refresh_ui_after_mutation(
            status_msg="Reverted change(s); save to write to SD card."
        )
        self._refresh()
        messagebox.showinfo(
            "Revert Result",
            "\n".join(messages[:20]) + (
                f"\n... ({len(messages) - 20} more)" if len(messages) > 20 else ""
            ),
            parent=self.top,
        )

    def _on_revert_to_point(self):
        events = self._selected_events()
        if len(events) != 1:
            messagebox.showinfo(
                "Revert to point",
                "Select exactly one change. Everything AFTER it will be reverted.",
                parent=self.top,
            )
            return
        pivot = events[0]
        if not messagebox.askyesno(
            "Revert to this point",
            f"Revert every change made AFTER #{pivot.event_id} "
            f"({pivot.ts} - {pivot.summary})?\n\n"
            "Changes will be reverted newest-first as one batch.",
            parent=self.top,
        ):
            return
        ok, msg = self.app.revert_to_point(pivot.event_id)
        self.app._refresh_ui_after_mutation(
            status_msg="Reverted to point; save to write to SD card."
        )
        self._refresh()
        messagebox.showinfo("Revert to point", msg, parent=self.top)


class CityManagerDialog:
    """Dialog for listing/editing firmware and custom city locations."""

    def __init__(self, app: "ScannerManagerApp"):
        self.app = app
        self.top = tk.Toplevel(app.root)
        self.top.title("Cities")
        self.top.transient(app.root)
        self.top.geometry("620x480")

        state_id = app._get_selected_state_id()
        default_abbrev = ""
        if state_id is not None:
            _, default_abbrev = app.config.states.get(state_id, ("", ""))

        filter_frame = ttk.Frame(self.top, padding=8)
        filter_frame.pack(fill=tk.X)
        ttk.Label(filter_frame, text="State:").pack(side=tk.LEFT)
        self.state_var = tk.StringVar(value=default_abbrev)
        ttk.Entry(filter_frame, textvariable=self.state_var, width=6).pack(side=tk.LEFT, padx=(4, 8))
        ttk.Button(filter_frame, text="Refresh", command=self._refresh).pack(side=tk.LEFT)
        firmware_state = "loaded" if app._firmware_city_table.is_loaded() else "not loaded"
        ttk.Label(filter_frame, text=f"Firmware CityTable: {firmware_state}").pack(side=tk.LEFT, padx=(12, 0))

        list_frame = ttk.Frame(self.top)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)
        columns = ("source", "state", "name", "lat", "lon")
        self.tree = ttk.Treeview(list_frame, columns=columns, show="headings", selectmode="browse")
        self.tree.heading("source", text="Source")
        self.tree.heading("state", text="ST")
        self.tree.heading("name", text="Name / City ID")
        self.tree.heading("lat", text="Lat")
        self.tree.heading("lon", text="Lon")
        self.tree.column("source", width=80)
        self.tree.column("state", width=40)
        self.tree.column("name", width=240)
        self.tree.column("lat", width=80)
        self.tree.column("lon", width=80)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.tree.yview)
        sb.pack(side=tk.LEFT, fill=tk.Y)
        self.tree.configure(yscrollcommand=sb.set)

        add_frame = ttk.LabelFrame(self.top, text="Add Custom Location", padding=8)
        add_frame.pack(fill=tk.X, padx=8, pady=4)
        self.new_name = tk.StringVar()
        self.new_lat = tk.StringVar()
        self.new_lon = tk.StringVar()
        ttk.Label(add_frame, text="Name:").grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(add_frame, textvariable=self.new_name, width=24).grid(row=0, column=1, padx=4)
        ttk.Label(add_frame, text="Lat:").grid(row=0, column=2, sticky=tk.W)
        ttk.Entry(add_frame, textvariable=self.new_lat, width=10).grid(row=0, column=3, padx=4)
        ttk.Label(add_frame, text="Lon:").grid(row=0, column=4, sticky=tk.W)
        ttk.Entry(add_frame, textvariable=self.new_lon, width=10).grid(row=0, column=5, padx=4)
        ttk.Button(add_frame, text="Add", command=self._on_add).grid(row=0, column=6, padx=4)
        ttk.Button(add_frame, text="Delete Selected", command=self._on_delete).grid(row=0, column=7, padx=4)

        export_frame = ttk.Frame(self.top, padding=8)
        export_frame.pack(fill=tk.X)
        ttk.Button(
            export_frame, text="Export patched CityTable.dat",
            command=self._on_export_city_table,
        ).pack(side=tk.LEFT)
        ttk.Label(
            export_frame,
            text=(
                "Export writes to CityTable_V1_00_00.custom.dat by default. "
                "Uniden updater may overwrite edits."
            ),
            foreground="#666666",
        ).pack(side=tk.LEFT, padx=(8, 0))

        close_frame = ttk.Frame(self.top)
        close_frame.pack(fill=tk.X, pady=(4, 8))
        ttk.Button(close_frame, text="Close", command=self.top.destroy).pack(side=tk.RIGHT, padx=8)

        self._refresh()

    def _current_state_abbrev(self) -> str:
        return (self.state_var.get() or "").strip().upper()

    def _current_state_id(self) -> Optional[int]:
        abbrev = self._current_state_abbrev()
        if not abbrev:
            return None
        for sid, (_, sabbrev) in self.app.config.states.items():
            if sabbrev.upper() == abbrev:
                return sid
        return None

    def _refresh(self):
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        abbrev = self._current_state_abbrev()
        state_id = self._current_state_id()
        firmware_records = self.app._firmware_city_table.by_state.get(abbrev, []) if abbrev else []
        for rec in firmware_records[:2000]:
            self.tree.insert(
                "", tk.END,
                values=("firmware", rec.state_abbrev, f"city_id={rec.city_id}", f"{rec.lat:.4f}", f"{rec.lon:.4f}"),
            )
        for loc in self.app._custom_locations.locations:
            if state_id is None or loc["state_id"] == state_id:
                self.tree.insert(
                    "", tk.END,
                    values=("custom", self._abbrev_for_state_id(loc["state_id"]), loc["name"], f"{loc['lat']:.4f}", f"{loc['lon']:.4f}"),
                )

    def _abbrev_for_state_id(self, state_id: int) -> str:
        _, abbrev = self.app.config.states.get(state_id, ("", ""))
        return abbrev

    def _on_add(self):
        name = self.new_name.get().strip()
        if not name:
            messagebox.showwarning("Add", "Enter a name.")
            return
        state_id = self._current_state_id()
        if state_id is None:
            messagebox.showwarning("Add", "Set a valid state abbreviation first.")
            return
        try:
            lat = float(self.new_lat.get())
            lon = float(self.new_lon.get())
        except ValueError:
            messagebox.showwarning("Add", "Lat/Lon must be numeric.")
            return
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            messagebox.showwarning("Add", "Lat/Lon out of range.")
            return
        self.app._custom_locations.add(name, state_id, lat, lon)
        self.new_name.set("")
        self.new_lat.set("")
        self.new_lon.set("")
        self._refresh()

    def _on_delete(self):
        sel = self.tree.selection()
        if not sel:
            return
        values = self.tree.item(sel[0], "values")
        if not values or values[0] != "custom":
            messagebox.showinfo("Delete", "Only custom locations can be deleted here.")
            return
        name = values[2]
        state_abbrev = values[1]
        state_id = None
        for sid, (_, sabbrev) in self.app.config.states.items():
            if sabbrev.upper() == state_abbrev:
                state_id = sid
                break
        if state_id is None:
            return
        self.app._custom_locations.remove(name, state_id)
        self._refresh()

    def _on_export_city_table(self):
        if not self.app._firmware_city_table.is_loaded():
            messagebox.showerror("Export", "Firmware CityTable not loaded.")
            return
        if not messagebox.askyesno(
            "Export CityTable",
            "This will write a patched CityTable.dat that includes your custom locations. "
            "A backup of the original will be created. "
            "Uniden's updater may overwrite edits on next refresh. Continue?",
        ):
            return
        original_path = self.app._firmware_city_table.source_path
        if original_path is None:
            messagebox.showerror("Export", "Cannot determine source path.")
            return
        default_target = original_path.with_name(original_path.stem + ".custom.dat")
        overwrite = messagebox.askyesno(
            "Export CityTable",
            f"Overwrite original CityTable at:\n{original_path}\n\n"
            f"Click Yes to overwrite (backup will be created).\n"
            f"Click No to write to:\n{default_target}",
        )
        target_path = original_path if overwrite else default_target
        extras: List[CityRecord] = []
        base_id = 60000
        for loc in self.app._custom_locations.locations:
            abbrev = self._abbrev_for_state_id(loc["state_id"]) or "XX"
            if len(abbrev) != 2:
                continue
            extras.append(
                CityRecord(
                    state_abbrev=abbrev,
                    city_id=base_id,
                    lat=float(loc["lat"]),
                    lon=float(loc["lon"]),
                )
            )
            base_id += 1
        try:
            written = self.app._firmware_city_table.export_patched(
                target_path, extras, make_backup=overwrite
            )
        except Exception as exc:
            messagebox.showerror("Export", f"Could not export CityTable:\n{exc}")
            return
        messagebox.showinfo("Export", f"Wrote patched CityTable to:\n{written}")


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

def _crash_log_dir() -> Path:
    """Directory where the global exception hook writes crash logs.

    Honors ``%LOCALAPPDATA%`` on Windows and falls back to the user's
    home directory on other platforms. A ``SCANNER_MANAGER_LOG_DIR``
    environment override is honored by tests.
    """
    override = os.environ.get("SCANNER_MANAGER_LOG_DIR")
    if override:
        return Path(override)
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "scanner-manager" / "logs"
    return Path.home() / ".scanner-manager" / "logs"


def _write_crash_log(exc_type, exc_value, exc_tb) -> Path:
    """Serialize an uncaught traceback + context to a timestamped log
    file and return its path. Never raises - a crash reporter that
    crashes its reporting path is worse than useless.
    """
    import traceback
    log_dir = _crash_log_dir()
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        log_dir = Path.home()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = log_dir / f"crash-{stamp}.log"
    try:
        with log_path.open("w", encoding="utf-8") as f:
            f.write(f"# {APP_NAME} v{APP_VERSION} crash log\n")
            f.write(f"# Timestamp: {datetime.now().isoformat()}\n")
            f.write(f"# Platform : {sys.platform}\n")
            f.write(f"# Python   : {sys.version.split()[0]}\n")
            f.write("\n")
            traceback.print_exception(
                exc_type, exc_value, exc_tb, file=f,
            )
    except OSError:
        pass
    return log_path


def _install_crash_hook(root: tk.Tk, app: "ScannerManagerApp") -> None:
    """Route Tk callback exceptions through our crash-log writer and
    give the user a one-click path to file the bug report.
    """

    def handler(exc_type, exc_value, exc_tb):
        log_path = _write_crash_log(exc_type, exc_value, exc_tb)
        try:
            if not messagebox.askyesno(
                "Unexpected error",
                (
                    f"{APP_NAME} hit an unexpected error and saved a crash "
                    f"log to:\n\n{log_path}\n\n"
                    "Open the GitHub issue form with these details "
                    "pre-filled? (You can attach the log file.)"
                ),
                parent=root,
            ):
                return
        except Exception:
            return
        import traceback
        tb_text = "".join(
            traceback.format_exception(exc_type, exc_value, exc_tb)
        )[-1200:]
        title = urllib.parse.quote(
            f"[{APP_VERSION}] {exc_type.__name__}: {exc_value}"
        )
        body = urllib.parse.quote(
            "### What happened?\n(please describe what you were doing)\n\n"
            "### Environment\n"
            f"- {APP_NAME}: v{APP_VERSION}\n"
            f"- OS: {sys.platform}\n"
            f"- Python: {sys.version.split()[0]}\n"
            f"- Log file: `{log_path}`\n\n"
            "### Traceback\n"
            f"```\n{tb_text}\n```\n"
        )
        webbrowser.open(f"{APP_ISSUES_URL}/new?title={title}&body={body}")

    root.report_callback_exception = handler


def main():
    root = tk.Tk()
    app = ScannerManagerApp(root)
    _install_crash_hook(root, app)

    def on_close():
        if app.hpd.has_changes:
            if not messagebox.askyesno("Unsaved Changes", "You have unsaved changes. Quit anyway?"):
                return
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
