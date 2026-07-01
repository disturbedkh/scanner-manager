"""Session cache for parsed HPDB trees (device-switch performance).

Caches in-memory :class:`HpdFile` instances and the built
:class:`PySide6.QtGui.QStandardItemModel` keyed by
``(device_id, hpdb_dir, mtime fingerprint)``. Fingerprint is the max
``st_mtime`` of ``hpdb.cfg`` and every ``s_*.hpd`` in the HPDB directory.

**Model storage choice:** we keep the live ``QStandardItemModel`` instance
rather than rebuilding from ``hpd_files`` on restore. Tree rows hold
``UserRole`` payloads that reference the same ``HpdFile`` objects stored
in ``hpd_files``; restoring both together avoids a full Qt rebuild on
cache hit.

**Wave 2 call sites** (not wired in Wave 1):

- After ``EditorDock.save_all`` / ``save_current``: ``tree.invalidate_cache()``
- After ``EditorDock._on_reload``: ``tree.invalidate_cache(device_id=...)``
- Optional: ``HpdbSessionCache.invalidate(device_id=..., hpdb_dir=...)`` for
  card-specific clears without touching the tree widget.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from PySide6.QtGui import QStandardItemModel

CacheKey = Tuple[str, Path, str]


def hpdb_fingerprint(hpdb_dir: Path) -> str:
    """Return a string fingerprint from HPDB file mtimes."""
    mtimes: list[float] = []
    cfg = hpdb_dir / "hpdb.cfg"
    if cfg.is_file():
        mtimes.append(cfg.stat().st_mtime)
    for path in sorted(hpdb_dir.glob("s_*.hpd")):
        if path.is_file():
            mtimes.append(path.stat().st_mtime)
    if not mtimes:
        return "empty"
    return f"{max(mtimes):.6f}"


@dataclass(frozen=True)
class CachedHpdb:
    """One cached HPDB parse + Qt tree model."""

    hpd_files: Dict[int, Any]
    hpd_config: Optional[Any]
    model: QStandardItemModel
    fingerprint: str


class HpdbSessionCache:
    """Process-wide cache of parsed HPDB data keyed by device + directory."""

    def __init__(self) -> None:
        self._entries: Dict[CacheKey, CachedHpdb] = {}

    def get(self, device_id: str, hpdb_dir: Path) -> Optional[CachedHpdb]:
        """Return a cache entry when fingerprint still matches disk."""
        resolved = hpdb_dir.resolve()
        fingerprint = hpdb_fingerprint(resolved)
        key = (device_id, resolved, fingerprint)
        cached = self._entries.get(key)
        if cached is not None and cached.fingerprint == fingerprint:
            return cached
        return None

    def put(
        self,
        device_id: str,
        hpdb_dir: Path,
        hpd_files: Dict[int, Any],
        hpd_config: Optional[Any],
        model: QStandardItemModel,
    ) -> None:
        """Store parsed HPDB state for later restore."""
        resolved = hpdb_dir.resolve()
        fingerprint = hpdb_fingerprint(resolved)
        key = (device_id, resolved, fingerprint)
        self._entries[key] = CachedHpdb(
            hpd_files=dict(hpd_files),
            hpd_config=hpd_config,
            model=model,
            fingerprint=fingerprint,
        )

    def invalidate(
        self,
        device_id: Optional[str] = None,
        hpdb_dir: Optional[Path] = None,
    ) -> None:
        """Drop cache entries; omit both args to clear everything."""
        if device_id is None and hpdb_dir is None:
            self._entries.clear()
            return

        resolved = hpdb_dir.resolve() if hpdb_dir is not None else None
        drop = [
            key
            for key in self._entries
            if (device_id is None or key[0] == device_id)
            and (resolved is None or key[1] == resolved)
        ]
        for key in drop:
            del self._entries[key]


_session_cache: Optional[HpdbSessionCache] = None


def get_hpdb_session_cache() -> HpdbSessionCache:
    """Return the process-wide HPDB session cache singleton."""
    global _session_cache
    if _session_cache is None:
        _session_cache = HpdbSessionCache()
    return _session_cache
