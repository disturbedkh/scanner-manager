"""Firmware library + version parsing.

The Uniden FTP servers store firmware blobs as flat directory entries
named ``<MODEL>_V<MAJ>_<MIN>_<PAT>.bin`` (Main MCU) or
``<MODEL>-SUB_V<MAJ>_<MIN>_<PAT>.firm`` (Sub MCU). HPDB snapshots
follow ``MasterHpdb_<MM>_<DD>_<YYYY>.gz``.

This module:

- Parses filenames into typed ``FirmwareVersion`` / ``HpdbVersion``
  records.
- Filters per-family file globs.
- Manages a local on-disk cache under
  ``<user_data>/firmware_cache/<family>/<kind>_<version>/`` with
  SHA-256 verification.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)


_VERSION_RE = re.compile(
    r"^(?P<model>[A-Za-z0-9-]+?)(?P<sub>-SUB)?_V(?P<major>\d+)_(?P<minor>\d+)_(?P<patch>\d+)\.(?P<ext>bin|firm)$"
)
_HPDB_RE = re.compile(r"^MasterHpdb_(?P<mm>\d{2})_(?P<dd>\d{2})_(?P<yyyy>\d{4})\.gz$")
_TABLE_RE = re.compile(
    r"^(?P<kind>CityTable|ZipTable|BC-WF1)_V(?P<major>\d+)_(?P<minor>\d+)_(?P<patch>\d+)\.(?:dat|bin)$",
    re.IGNORECASE,
)
_SENTINEL_APP_RE = re.compile(
    r"^BCDx36HP_Sentinel_V(?P<major>\d+)_(?P<minor>\d+)_(?P<patch>\d+)\.app$"
)


@dataclass(frozen=True, order=True)
class FirmwareVersion:
    """Sortable version triple parsed from a filename."""

    sort_key: Tuple[int, int, int] = field(compare=True)
    model: str = field(default="", compare=False)
    kind: str = field(default="", compare=False)  # "main" / "sub"
    extension: str = field(default="", compare=False)
    filename: str = field(default="", compare=False)

    @classmethod
    def parse(cls, filename: str) -> Optional["FirmwareVersion"]:
        m = _VERSION_RE.match(filename)
        if not m:
            return None
        major = int(m.group("major"))
        minor = int(m.group("minor"))
        patch = int(m.group("patch"))
        kind = "sub" if m.group("sub") else "main"
        return cls(
            sort_key=(major, minor, patch),
            model=m.group("model").upper(),
            kind=kind,
            extension=m.group("ext"),
            filename=filename,
        )

    def version_string(self) -> str:
        major, minor, patch = self.sort_key
        return f"{major}.{minor:02d}.{patch:02d}"


@dataclass(frozen=True, order=True)
class HpdbVersion:
    """Sortable date parsed from ``MasterHpdb_MM_DD_YYYY.gz``."""

    sort_key: date = field(compare=True)
    filename: str = field(default="", compare=False)

    @classmethod
    def parse(cls, filename: str) -> Optional["HpdbVersion"]:
        m = _HPDB_RE.match(filename)
        if not m:
            return None
        try:
            d = date(int(m.group("yyyy")), int(m.group("mm")), int(m.group("dd")))
        except ValueError:
            return None
        return cls(sort_key=d, filename=filename)

    def date_string(self) -> str:
        return self.sort_key.isoformat()


@dataclass(frozen=True, order=True)
class TableVersion:
    sort_key: Tuple[int, int, int] = field(compare=True)
    kind: str = field(default="", compare=False)  # CityTable / ZipTable / BC-WF1
    filename: str = field(default="", compare=False)

    @classmethod
    def parse(cls, filename: str) -> Optional["TableVersion"]:
        m = _TABLE_RE.match(filename)
        if not m:
            return None
        return cls(
            sort_key=(int(m.group("major")), int(m.group("minor")), int(m.group("patch"))),
            kind=m.group("kind"),
            filename=filename,
        )


# Per-family model fingerprints. The FTP filenames use these tokens
# verbatim (e.g. SDS-100 has a hyphen, BCD436HP doesn't).
FAMILY_MAIN_MODELS = {
    "uniden_sds100": ("SDS-100", "SDS200", "SDS150"),
    "uniden_bt885": (),  # BT885 has no firmware on FTP yet
}

FAMILY_HPDB_ENDPOINT = {
    "uniden_sds100": "sentinel",   # ftp.homepatrol.com
    "uniden_bt885": "bt885",       # ftp.uniden.com
}


def filter_main_firmware(
    listing: Iterable, family_id: str
) -> List[FirmwareVersion]:
    """Return Main firmware entries that belong to ``family_id``.

    ``listing`` may be a list of ``FtpEntry`` objects (from
    :mod:`firmware.ftp_client`) or bare filename strings.
    """
    accepted = FAMILY_MAIN_MODELS.get(family_id, ())
    out: List[FirmwareVersion] = []
    for entry in listing:
        name = getattr(entry, "name", entry)
        version = FirmwareVersion.parse(name)
        if version is None:
            continue
        if version.kind != "main":
            continue
        if accepted and version.model not in accepted:
            continue
        out.append(version)
    return sorted(out)


def filter_sub_firmware(
    listing: Iterable, family_id: str
) -> List[FirmwareVersion]:
    """Return Sub firmware entries for the given family."""
    accepted = FAMILY_MAIN_MODELS.get(family_id, ())
    out: List[FirmwareVersion] = []
    for entry in listing:
        name = getattr(entry, "name", entry)
        version = FirmwareVersion.parse(name)
        if version is None:
            continue
        if version.kind != "sub":
            continue
        if accepted and version.model not in accepted:
            continue
        out.append(version)
    return sorted(out)


def filter_hpdb(listing: Iterable) -> List[HpdbVersion]:
    out: List[HpdbVersion] = []
    for entry in listing:
        name = getattr(entry, "name", entry)
        v = HpdbVersion.parse(name)
        if v is not None:
            out.append(v)
    return sorted(out)


def latest(versions: Sequence) -> Optional:
    """Return the largest item in ``versions`` (by ``sort_key``)."""
    if not versions:
        return None
    return max(versions)


def _user_cache_root() -> Path:
    from core.paths import cache_dir

    return cache_dir() / "firmware_cache"


class FirmwareCache:
    """Persistent on-disk cache of downloaded firmware blobs.

    Layout::

        <root>/<family>/<kind>_<version>/<filename>
        <root>/<family>/<kind>_<version>/<filename>.sha256
    """

    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = Path(root) if root else _user_cache_root()
        self.root.mkdir(parents=True, exist_ok=True)

    def _entry_dir(self, family_id: str, version: FirmwareVersion) -> Path:
        return (
            self.root
            / family_id
            / f"{version.kind}_{version.version_string().replace('.', '_')}"
        )

    def has(self, family_id: str, version: FirmwareVersion) -> bool:
        path = self.path_for(family_id, version)
        return path.exists()

    def path_for(self, family_id: str, version: FirmwareVersion) -> Path:
        return self._entry_dir(family_id, version) / version.filename

    def store(
        self,
        family_id: str,
        version: FirmwareVersion,
        blob_bytes: bytes,
    ) -> Path:
        target = self.path_for(family_id, version)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_bytes(blob_bytes)
        os.replace(tmp, target)
        digest = hashlib.sha256(blob_bytes).hexdigest()
        target.with_suffix(target.suffix + ".sha256").write_text(digest, encoding="ascii")
        return target

    def verify(self, family_id: str, version: FirmwareVersion) -> bool:
        target = self.path_for(family_id, version)
        sidecar = target.with_suffix(target.suffix + ".sha256")
        if not target.exists() or not sidecar.exists():
            return False
        try:
            expected = sidecar.read_text(encoding="ascii").strip()
        except Exception:
            return False
        actual = hashlib.sha256(target.read_bytes()).hexdigest()
        return actual == expected
