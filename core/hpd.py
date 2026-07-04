"""HPD file data model, parser, geo helpers, and hpdb.cfg config.

Extracted from ``legacy_tk.scanner_manager`` so the HPD file format is owned by
the UI-free ``core`` package. Both the PySide6 GUI and the legacy Tk app
consume these classes from here; ``legacy_tk.scanner_manager`` re-exports the
public names for backward compatibility.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Record-type tokens (column 0 of an HPD line) + shared field literals.
# Centralized so the parser, writers, and reverters share one definition
# (also satisfies SonarQube python:S1192 duplicate-literal checks).
# ---------------------------------------------------------------------------
_REC_TARGET_MODEL = "TargetModel"
_REC_FORMAT_VERSION = "FormatVersion"
_REC_DATE_MODIFIED = "DateModified"
_REC_CONVENTIONAL = "Conventional"
_REC_TRUNK = "Trunk"
_REC_AREA_STATE = "AreaState"
_REC_AREA_COUNTY = "AreaCounty"
_REC_CGROUP = "C-Group"
_REC_TGROUP = "T-Group"
_REC_CFREQ = "C-Freq"
_REC_TGID = "TGID"
_REC_SITE = "Site"
_REC_TFREQ = "T-Freq"
_REC_RECTANGLE = "Rectangle"
_FIELD_OFF = "Off"
_UNKNOWN = "Unknown"

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
    identity_value: str
    mode: str = ""
    tone: str = ""
    is_user_added: bool = False

# ---------------------------------------------------------------------------
# HPD File Parser / Writer
# ---------------------------------------------------------------------------

@dataclass
class _BuildState:
    """Mutable cursor threaded through the per-record tree builders."""
    current_system: Optional[SystemNode] = None
    current_group: Optional[GroupNode] = None
    current_site: Optional[SiteNode] = None


_STATE_ID_RE = re.compile(r"StateId=(-?\d+)")
_COUNTY_ID_RE = re.compile(r"CountyId=(-?\d+)")


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
        state = _BuildState()
        consumers = self._record_consumers()
        for rec in self.records:
            consume = consumers.get(rec.record_type)
            if consume is not None:
                consume(rec, state)

    def _record_consumers(self) -> Dict[str, Any]:
        """Map each HPD record type to the method that folds it into the tree."""
        return {
            _REC_TARGET_MODEL: self._consume_header,
            _REC_FORMAT_VERSION: self._consume_header,
            _REC_DATE_MODIFIED: self._consume_header,
            _REC_CONVENTIONAL: self._consume_system,
            _REC_TRUNK: self._consume_system,
            _REC_AREA_STATE: self._consume_area,
            _REC_AREA_COUNTY: self._consume_area,
            _REC_CGROUP: self._consume_group,
            _REC_TGROUP: self._consume_group,
            _REC_CFREQ: self._consume_freq,
            _REC_TGID: self._consume_freq,
            _REC_SITE: self._consume_site,
            _REC_TFREQ: self._consume_tfreq,
            _REC_RECTANGLE: self._consume_rectangle,
        }

    def _consume_header(self, rec: HpdRecord, _state: _BuildState) -> None:
        self.header_records.append(rec)

    def _consume_system(self, rec: HpdRecord, state: _BuildState) -> None:
        # record_type is _REC_CONVENTIONAL or _REC_TRUNK (the two keys mapped here).
        system = SystemNode(
            record=rec,
            name=rec.get_field(3, _UNKNOWN),
            system_type=rec.record_type,
            system_id=self._extract_id(rec.fields[1]),
        )
        self.systems.append(system)
        state.current_system = system
        state.current_group = None
        state.current_site = None

    def _consume_area(self, rec: HpdRecord, state: _BuildState) -> None:
        system = state.current_system
        if system is None:
            return
        system.area_records.append(rec)
        state_id, county_id = self._extract_area_ids(rec.fields)
        if state_id is not None:
            system.state_ids.add(state_id)
        if county_id is not None:
            system.county_ids.add(county_id)

    def _consume_group(self, rec: HpdRecord, state: _BuildState) -> None:
        # record_type is _REC_CGROUP or _REC_TGROUP (both mapped here).
        system = state.current_system
        lat, lon, rng = self._extract_geo(rec.fields, 5)
        group = GroupNode(
            record=rec,
            name=rec.get_field(3, _UNKNOWN),
            group_type=rec.record_type,
            group_id=self._extract_id(rec.fields[1]),
            parent_id=self._extract_id(rec.fields[2]),
            system_id=system.system_id if system else "",
            system_type=system.system_type if system else "",
            system_name=system.name if system else "",
            lat=lat, lon=lon, range_miles=rng,
        )
        if system:
            system.groups.append(group)
        state.current_group = group
        state.current_site = None

    def _consume_freq(self, rec: HpdRecord, state: _BuildState) -> None:
        # C-Freq stores service type in field 8, TGID in field 7.
        idx = 8 if rec.record_type == _REC_CFREQ else 7
        system = state.current_system
        group = state.current_group
        entry = FreqEntry(
            record=rec,
            name=rec.get_field(3, ""),
            service_type=self._parse_int(rec.get_field(idx, "0")),
            entry_type=rec.record_type,
            group_id=group.group_id if group else "",
            group_type=group.group_type if group else "",
            group_name=group.name if group else "",
            system_id=system.system_id if system else "",
            system_type=system.system_type if system else "",
            system_name=system.name if system else "",
        )
        if group:
            group.entries.append(entry)

    def _consume_site(self, rec: HpdRecord, state: _BuildState) -> None:
        lat, lon, rng = self._extract_geo(rec.fields, 5)
        site = SiteNode(
            record=rec,
            name=rec.get_field(3, _UNKNOWN),
            site_id=self._extract_id(rec.fields[1]),
            lat=lat, lon=lon, range_miles=rng,
        )
        if state.current_system:
            state.current_system.sites.append(site)
        state.current_site = site
        state.current_group = None

    def _consume_tfreq(self, rec: HpdRecord, state: _BuildState) -> None:
        if state.current_site:
            state.current_site.freqs.append(rec)

    def _consume_rectangle(self, rec: HpdRecord, _state: _BuildState) -> None:
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
                target_key = (_REC_CGROUP, value)
                break
            if key == "TGroupId":
                target_key = (_REC_TGROUP, value)
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
        if system.system_type != _REC_TRUNK:
            raise ValueError("T-Groups can only be added to trunked systems.")
        trunk_id = system.system_id
        lat_str = f"{lat:.6f}" if lat is not None else ""
        lon_str = f"{lon:.6f}" if lon is not None else ""
        range_str = f"{range_miles:.1f}" if range_miles is not None else ""
        fields = [
            _REC_TGROUP,
            "TGroupId=0",
            f"TrunkId={trunk_id}",
            name,
            _FIELD_OFF,
            lat_str,
            lon_str,
            range_str,
        ]
        raw = "\t".join(fields)
        insert_idx = self._find_system_end(system)
        rec = HpdRecord(
            line_index=insert_idx, raw_line=raw,
            record_type=_REC_TGROUP, fields=fields, modified=True,
        )
        self.records.insert(insert_idx, rec)
        group = GroupNode(
            record=rec, name=name, group_type=_REC_TGROUP,
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
        if system.system_type != _REC_CONVENTIONAL:
            raise ValueError("Groups can only be added to conventional systems.")
        county_id = system.system_id
        lat_str = f"{lat:.6f}" if lat is not None else ""
        lon_str = f"{lon:.6f}" if lon is not None else ""
        range_str = f"{range_miles:.1f}" if range_miles is not None else ""
        fields = [
            _REC_CGROUP,
            "CGroupId=0",
            f"CountyId={county_id}",
            name,
            _FIELD_OFF,
            lat_str,
            lon_str,
            range_str,
            "Circle",
        ]
        raw = "\t".join(fields)
        insert_idx = self._find_system_end(system)
        rec = HpdRecord(
            line_index=insert_idx, raw_line=raw,
            record_type=_REC_CGROUP, fields=fields, modified=True,
        )
        self.records.insert(insert_idx, rec)
        group = GroupNode(
            record=rec, name=name, group_type=_REC_CGROUP,
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
            _REC_CFREQ,
            "CFreqId=0",
            f"CGroupId={group_id}",
            name,
            _FIELD_OFF,
            str(freq_hz),
            mode,
            tone,
            str(service_type),
        ]
        raw = "\t".join(fields)
        insert_idx = self._find_group_end(group)
        rec = HpdRecord(
            line_index=insert_idx, raw_line=raw,
            record_type=_REC_CFREQ, fields=fields, modified=True,
        )
        self.records.insert(insert_idx, rec)
        entry = FreqEntry(
            record=rec, name=name, service_type=service_type,
            entry_type=_REC_CFREQ,
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
            _REC_TGID,
            "Tid=0",
            f"TGroupId={group_id}",
            name,
            _FIELD_OFF,
            str(tgid),
            mode,
            str(service_type),
        ] + [""] * 8 + ["Any"]
        raw = "\t".join(fields)
        insert_idx = self._find_group_end(group)
        rec = HpdRecord(
            line_index=insert_idx, raw_line=raw,
            record_type=_REC_TGID, fields=fields, modified=True,
        )
        self.records.insert(insert_idx, rec)
        entry = FreqEntry(
            record=rec, name=name, service_type=service_type,
            entry_type=_REC_TGID,
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
        if entry.entry_type == _REC_CFREQ:
            rec.set_field(8, str(new_type))
        elif entry.entry_type == _REC_TGID:
            rec.set_field(7, str(new_type))
        entry.service_type = new_type
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
        if entry.entry_type == _REC_CFREQ and tone is not None:
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

    def _collect_system_record_ids(self, system: SystemNode) -> Set[int]:
        owned_ids: Set[int] = {id(system.record)}
        for rec in system.area_records:
            owned_ids.add(id(rec))
        for site in system.sites:
            owned_ids.add(id(site.record))
            for freq_rec in site.freqs:
                owned_ids.add(id(freq_rec))
        for group in system.groups:
            owned_ids.add(id(group.record))
            for entry in group.entries:
                owned_ids.add(id(entry.record))
        return owned_ids

    @staticmethod
    def _rectangle_group_ref(rec: "HpdRecord") -> Optional[Tuple[str, str]]:
        if rec.record_type != _REC_RECTANGLE:
            return None
        for field_str in rec.fields[1:]:
            if "=" not in field_str:
                continue
            key, value = field_str.split("=", 1)
            if key == "CGroupId":
                return (_REC_CGROUP, value)
            if key == "TGroupId":
                return (_REC_TGROUP, value)
        return None

    def _records_owned_by_system(
        self, system: SystemNode
    ) -> List["HpdRecord"]:
        """Every HpdRecord that belongs to the given system, in the order
        they appear in ``self.records``. Used by delete_system + revert."""
        owned_ids = self._collect_system_record_ids(system)
        group_keys = {(g.group_type, g.group_id) for g in system.groups}
        for rec in self.records:
            ref = self._rectangle_group_ref(rec)
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
                    if entry.entry_type == _REC_CFREQ:
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
                            identity_value=identity,
                            mode=mode,
                            tone=tone,
                            is_user_added=self._is_user_added_id(id_field),
                        )
                    )
        return snapshot

    def _lookup_custom_entry(
        self,
        custom: EntryCustomization,
        entry_map: Dict[Tuple[str, str, str, str], FreqEntry],
        fallback_map: Dict[Tuple[str, str, str, str], FreqEntry],
    ) -> Optional[FreqEntry]:
        entry = entry_map.get(self._custom_key(custom))
        if entry is not None:
            return entry
        return fallback_map.get(self._custom_fallback_key(custom))

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
            entry = self._lookup_custom_entry(custom, entry_map, fallback_map)

            if entry is not None:
                if entry.service_type != custom.service_type:
                    self.update_service_type(entry, custom.service_type)
                    reapplied += 1
                continue

            if custom.is_user_added and self._reinsert_custom_entry(custom):
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
            if custom.entry_type == _REC_CFREQ:
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
            self.has_changes = True
            return entry is not None
        except Exception:
            logger.exception("Failed to reinsert custom entry %r", custom.name)
            return False

    def _find_group_by_ids(self, custom: EntryCustomization) -> Optional[GroupNode]:
        for sys_node in self.systems:
            if custom.system_id and sys_node.system_id == custom.system_id:
                for group in sys_node.groups:
                    if custom.group_id and group.group_id == custom.group_id:
                        return group
        return None

    def _find_group_by_names(self, custom: EntryCustomization) -> Optional[GroupNode]:
        for sys_node in self.systems:
            if self._norm(sys_node.name) != self._norm(custom.system_name):
                continue
            for group in sys_node.groups:
                if self._norm(group.name) == self._norm(custom.group_name):
                    return group
        return None

    def _find_group(self, custom: EntryCustomization) -> Optional[GroupNode]:
        by_id = self._find_group_by_ids(custom)
        if by_id is not None:
            return by_id
        return self._find_group_by_names(custom)

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
            if "StateId=" in field_value:
                match = _STATE_ID_RE.search(field_value)
                if match:
                    state_id = HpdFile._parse_int(match.group(1))
            if "CountyId=" in field_value:
                match = _COUNTY_ID_RE.search(field_value)
                if match:
                    county_id = HpdFile._parse_int(match.group(1))
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


def _geo_point_coverage(
    lat: float,
    lon: float,
    point_lat: Optional[float],
    point_lon: Optional[float],
    range_miles: Optional[float],
    best_delta: float,
    covered: bool,
) -> Tuple[bool, float]:
    if point_lat is None or point_lon is None:
        return covered, best_delta
    d = haversine_miles(lat, lon, point_lat, point_lon)
    rng = range_miles or 0.0
    delta = d - rng
    if delta < best_delta:
        best_delta = delta
    if rng > 0 and d <= rng:
        covered = True
    return covered, best_delta


def system_covers_point(sys_node: "SystemNode", lat: float, lon: float) -> Tuple[bool, float]:
    """Return (covered, best_delta_miles). best_delta is min(distance - range)."""
    best_delta = float("inf")
    covered = False
    for group in sys_node.groups:
        for rect in group.rectangles:
            if rectangle_contains_point(rect, lat, lon):
                covered = True
                best_delta = min(best_delta, 0.0)
        covered, best_delta = _geo_point_coverage(
            lat, lon, group.lat, group.lon, group.range_miles, best_delta, covered
        )
    for site in sys_node.sites:
        covered, best_delta = _geo_point_coverage(
            lat, lon, site.lat, site.lon, site.range_miles, best_delta, covered
        )
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

    def _register_state_file(self, sid: int, hpdb_dir: str) -> None:
        hpd_file = os.path.join(hpdb_dir, f"s_{sid:06d}.hpd")
        if os.path.exists(hpd_file):
            self.state_files[sid] = hpd_file

    def _parse_state_info(self, fields: List[str], hpdb_dir: str) -> None:
        sid = self._extract_int(fields[1])
        name = fields[3] if len(fields) > 3 else ""
        abbrev = fields[4] if len(fields) > 4 else ""
        self.states[sid] = (name, abbrev)
        self._register_state_file(sid, hpdb_dir)

    def _parse_county_info(self, fields: List[str]) -> None:
        cid = self._extract_int(fields[1])
        sid = self._extract_int(fields[2])
        name = fields[3] if len(fields) > 3 else ""
        self.counties[cid] = (name, sid)

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
                    self._parse_state_info(fields, hpdb_dir)
                elif fields[0] == "CountyInfo":
                    self._parse_county_info(fields)

    def get_state_name(self, sid: int) -> str:
        name, abbrev = self.states.get(sid, (_UNKNOWN, ""))
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
