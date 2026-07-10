"""Virtual SD card model.

See ``virtual_sd/__init__.py`` for the high-level rationale. This
module is the data layer; UI integration lives in
``gui/firmware/firmware_dock.py`` (firmware staging) and the future
``gui/storage/`` panels (HPDB / config staging).

Layout on disk (one tree per device)::

    <data_dir>/virtual-cards/<device_id>/   # see core.paths.virtual_sd_root
        .staged.json         <- manifest of pending changes
        pending/             <- staged files, organised mirroring the
            BCDx36HP/...        physical card's relative paths so an
            UpgFlash/...        rsync-style apply is trivial.
            HPDB/...

When :meth:`VirtualCard.apply_to_physical` runs, it walks ``pending/``
and rsyncs each entry into the device's ``sd_card_path``. Each apply
that succeeds wipes the corresponding row from the manifest.
"""

from __future__ import annotations

import json
import logging
import shutil
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from core._util import atomic_write_json, sha256_file

if TYPE_CHECKING:  # pragma: no cover
    from core.device_manager import Device

logger = logging.getLogger(__name__)

MANIFEST_FILENAME = ".staged.json"
PENDING_SUBDIR = "pending"


class VirtualCardError(RuntimeError):
    """Raised by VirtualCard operations that can't recover (bad path,
    missing physical card on apply, manifest corruption, etc.).
    """


class StageKind(str, Enum):
    """Coarse-grained payload type for a staged file. Drives both the
    UI's pending-changes table grouping and the apply-time validator
    (e.g. ``MAIN_FIRMWARE`` payloads must land on a valid Sentinel
    SD card layout).
    """

    MAIN_FIRMWARE = "main_firmware"
    SUB_FIRMWARE = "sub_firmware"
    HPDB = "hpdb"
    CONFIG = "config"
    FAVORITES = "favorites"
    OTHER = "other"


@dataclass
class StagedFile:
    """One row in the staging manifest.

    ``relative_path`` is the destination *under the SD card root*. We
    store both the staged copy (in ``pending/<relative_path>``) and
    the metadata so a future apply knows exactly where to drop the
    file on the physical card.
    """

    id: str
    relative_path: str
    kind: str  # StageKind.value
    source_label: str
    sha256: str
    size_bytes: int
    staged_at: float
    note: str = ""
    source_url: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)


def default_root_dir() -> Path:
    """Where virtual cards live by default.

    Honours ``SCANNER_MANAGER_VIRTUAL_SD_ROOT``; otherwise
    :func:`core.paths.virtual_sd_root` (XDG data, legacy
    ``~/.scanner-manager/virtual-cards`` preserved when present).
    """
    from core.paths import virtual_sd_root

    return virtual_sd_root()


class VirtualCard:
    """Per-device staging-and-apply layer.

    Construct via :meth:`from_device` (the common path) or directly
    with :meth:`open_at` if you have the workspace path.
    """

    def __init__(self, root: Path, device_id: str) -> None:
        self._root = Path(root)
        self._device_id = device_id
        self._root.mkdir(parents=True, exist_ok=True)
        (self._root / PENDING_SUBDIR).mkdir(exist_ok=True)
        self._manifest_path = self._root / MANIFEST_FILENAME
        self._manifest: List[StagedFile] = []
        self._reload()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def from_device(
        cls,
        device: "Device",
        root_dir: Optional[Path] = None,
    ) -> "VirtualCard":
        """Open or create the virtual card folder for a device. The
        device's ``id`` is used as the subdirectory name so multiple
        SDS100s with the same SD-card content stay isolated.
        """
        if root_dir is None:
            root_dir = default_root_dir()
        ws = Path(root_dir) / str(device.id)
        return cls(ws, device.id)

    @classmethod
    def open_at(cls, path: Path, device_id: str = "") -> "VirtualCard":
        return cls(Path(path), device_id or path.name)

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------

    @property
    def root(self) -> Path:
        return self._root

    @property
    def pending_dir(self) -> Path:
        return self._root / PENDING_SUBDIR

    @property
    def device_id(self) -> str:
        return self._device_id

    # ------------------------------------------------------------------
    # Manifest I/O
    # ------------------------------------------------------------------

    def _reload(self) -> None:
        if not self._manifest_path.exists():
            self._manifest = []
            return
        try:
            raw = json.loads(self._manifest_path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning(
                "Virtual card manifest %s is corrupt; treating as empty.",
                self._manifest_path,
            )
            self._manifest = []
            return
        rows: List[StagedFile] = []
        for entry in raw.get("staged", []):
            try:
                rows.append(StagedFile(**entry))
            except TypeError:
                logger.warning("Skipping unparseable staged row: %r", entry)
        self._manifest = rows

    def _save(self) -> None:
        payload = {
            "version": 1,
            "device_id": self._device_id,
            "saved_at": time.time(),
            "staged": [asdict(s) for s in self._manifest],
        }
        atomic_write_json(self._manifest_path, payload)

    # ------------------------------------------------------------------
    # Staging
    # ------------------------------------------------------------------

    def stage(
        self,
        source: Path,
        relative_path: str,
        kind: StageKind = StageKind.OTHER,
        source_label: str = "",
        note: str = "",
        source_url: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> StagedFile:
        """Copy ``source`` into the staging area at ``relative_path``,
        register it in the manifest, and return a :class:`StagedFile`.

        ``relative_path`` is the desired location *relative to the SD
        card root*; it'll be created as ``pending/<relative_path>``
        verbatim. Forward slashes only; backslashes are rejected to
        avoid cross-platform footguns.
        """
        source = Path(source)
        if not source.exists():
            raise VirtualCardError(f"Source does not exist: {source}")
        if not source.is_file():
            raise VirtualCardError(
                f"Only individual files can be staged (got dir): {source}"
            )
        if "\\" in relative_path:
            raise VirtualCardError(
                f"relative_path must use forward slashes: {relative_path!r}"
            )
        relative_path = relative_path.lstrip("/")
        if not relative_path:
            raise VirtualCardError("relative_path may not be empty")

        dest = self.pending_dir / relative_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        # Use copy2 to preserve mtime - the firmware updater inspects
        # mtimes when sniffing for "is this newer than the card?".
        shutil.copy2(source, dest)

        sha = _hash_file(dest)
        size = dest.stat().st_size
        row = StagedFile(
            id=str(uuid.uuid4()),
            relative_path=relative_path,
            kind=kind.value if isinstance(kind, StageKind) else str(kind),
            source_label=source_label or source.name,
            sha256=sha,
            size_bytes=size,
            staged_at=time.time(),
            note=note,
            source_url=source_url,
            extra=dict(extra or {}),
        )
        self._manifest.append(row)
        self._save()
        logger.info(
            "Staged %s (%s, %d bytes) -> %s on virtual card %s",
            row.source_label, row.kind, row.size_bytes,
            row.relative_path, self._device_id,
        )
        return row

    def list_pending(self) -> List[StagedFile]:
        """Return a copy of the staging manifest (newest-first)."""
        return sorted(self._manifest, key=lambda r: r.staged_at, reverse=True)

    def get(self, staged_id: str) -> Optional[StagedFile]:
        for row in self._manifest:
            if row.id == staged_id:
                return row
        return None

    def discard(self, staged_id: str) -> bool:
        """Remove a staged entry + its file. No-op if unknown.

        Returns True if a row was removed.
        """
        keep: List[StagedFile] = []
        removed: Optional[StagedFile] = None
        for row in self._manifest:
            if row.id == staged_id:
                removed = row
            else:
                keep.append(row)
        if removed is None:
            return False
        path = self.pending_dir / removed.relative_path
        try:
            if path.exists():
                path.unlink()
        except Exception:
            logger.exception("Could not unlink %s", path)
        self._manifest = keep
        self._save()
        return True

    def discard_all(self) -> int:
        """Drop every staged file. Returns the count removed."""
        count = len(self._manifest)
        if count == 0:
            return 0
        # Wipe pending/ contents entirely - faster than walking the
        # manifest and safer than rmtree on the parent.
        if self.pending_dir.exists():
            shutil.rmtree(self.pending_dir)
        self.pending_dir.mkdir(parents=True, exist_ok=True)
        self._manifest = []
        self._save()
        return count

    # ------------------------------------------------------------------
    # Apply to physical
    # ------------------------------------------------------------------

    def _apply_staged_row(
        self,
        row: StagedFile,
        sd_card_root: Path,
        report: ApplyReport,
    ) -> bool:
        src = self.pending_dir / row.relative_path
        dst = sd_card_root / row.relative_path
        try:
            if not src.exists():
                raise VirtualCardError(
                    f"Staged file vanished before apply: {src}"
                )
            dst.parent.mkdir(parents=True, exist_ok=True)
            if (dst.exists() and row.kind in
                    (StageKind.MAIN_FIRMWARE.value,
                     StageKind.SUB_FIRMWARE.value)):
                backup = dst.with_suffix(dst.suffix + ".bak")
                try:
                    shutil.copy2(dst, backup)
                except Exception:
                    logger.exception("Could not backup %s", dst)
            shutil.copy2(src, dst)
            report.applied.append(row)
            return True
        except Exception as exc:
            logger.exception("apply_to_physical failed for %s", row.relative_path)
            report.failed.append((row, str(exc)))
            return False

    def apply_to_physical(
        self,
        sd_card_root: Path,
        only_kinds: Optional[List[StageKind]] = None,
        dry_run: bool = False,
    ) -> "ApplyReport":
        """rsync staged files into the physical SD card.

        - ``sd_card_root`` is e.g. ``D:/`` or
          ``/Volumes/SCANNER`` - the same path as ``Device.sd_card_path``.
        - ``only_kinds`` filters which staged kinds to apply (None =
          everything).
        - ``dry_run`` returns the plan without touching the card.

        Successfully applied rows are removed from the manifest. Any
        row that fails to copy is left in place so the operator can
        retry without re-downloading.
        """
        sd_card_root = Path(sd_card_root)
        if not sd_card_root.exists():
            raise VirtualCardError(
                f"Physical SD card path does not exist: {sd_card_root}"
            )
        if not sd_card_root.is_dir():
            raise VirtualCardError(
                f"Physical SD card path is not a directory: {sd_card_root}"
            )
        kind_set = {k.value for k in (only_kinds or [])} or None

        plan: List[StagedFile] = []
        for row in self._manifest:
            if kind_set is not None and row.kind not in kind_set:
                continue
            plan.append(row)

        report = ApplyReport(planned=list(plan))
        if dry_run:
            return report

        keep: List[StagedFile] = list(self._manifest)
        for row in plan:
            if self._apply_staged_row(row, sd_card_root, report):
                keep = [k for k in keep if k.id != row.id]

        self._manifest = keep
        self._save()
        return report


@dataclass
class ApplyReport:
    """Result of :meth:`VirtualCard.apply_to_physical`. Suitable for
    rendering in a confirmation dialog after the apply runs.
    """

    planned: List[StagedFile] = field(default_factory=list)
    applied: List[StagedFile] = field(default_factory=list)
    failed: List = field(default_factory=list)  # list[tuple[StagedFile, str]]

    @property
    def ok(self) -> bool:
        return not self.failed

    def summary(self) -> str:
        if not self.planned:
            return "Nothing to apply (no staged files matched filter)."
        lines = [
            f"Planned: {len(self.planned)}",
            f"Applied: {len(self.applied)}",
            f"Failed:  {len(self.failed)}",
        ]
        if self.failed:
            lines.append("")
            lines.append("Failures:")
            for row, msg in self.failed:
                lines.append(f"  - {row.relative_path}: {msg}")
        return "\n".join(lines)


def _hash_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    return sha256_file(path, chunk_size=chunk_size)
