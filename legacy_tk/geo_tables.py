"""ZIP/county lookup and firmware city tables for legacy Tk."""

from __future__ import annotations

import json
import re
import struct
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.hpd import HpdConfig, HpdFile
from core.metastore import write_session_snapshot


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
        self.file_record_size: int = self.RECORD_SIZE
        self.source_path: Optional[Path] = None

    @property
    def record_size(self) -> int:
        """Alias for :attr:`file_record_size` (tests and RE tools)."""
        return self.file_record_size

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
        self.file_record_size = rec_size
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
        body = bytearray(source[start + len(self.START_MARKER): end])
        rec_size = getattr(self, "file_record_size", None) or self.RECORD_SIZE
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
