"""Discover mounted removable volumes that look like Uniden SD cards.

Used by the Qt Add Device dialog so Linux users (and Windows removable
drives) can pick a card without hunting through ``/media`` or Explorer.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import List, Optional, Sequence

logger = logging.getLogger(__name__)

_SCANNER_INF = Path("BCDx36HP") / "scanner.inf"
_HPDB_CFG = Path("HPDB") / "hpdb.cfg"
_HPDB_CFG_NESTED = Path("BCDx36HP") / "HPDB" / "hpdb.cfg"


def normalize_card_root(path: str | Path) -> Path:
    """If *path* is a ``BCDx36HP`` folder, return its parent; else *path*."""
    root = Path(path).expanduser()
    try:
        root = root.resolve()
    except OSError:
        root = root.absolute()
    if root.name.upper() == "BCDX36HP" and root.parent != root:
        return root.parent
    return root


def has_uniden_layout(root: Path) -> bool:
    """True if *root* looks like a Uniden card (or contains BCDx36HP)."""
    if not root.is_dir():
        return False
    candidates = (
        root / "scanner.inf",  # root is already BCDx36HP
        root / _SCANNER_INF,
        root / _HPDB_CFG,
        root / _HPDB_CFG_NESTED,
    )
    for candidate in candidates:
        if candidate.is_file():
            return True
    try:
        for child in root.iterdir():
            if child.is_file() and child.name.lower() == "scanner.inf":
                return True
            if child.is_dir() and child.name.upper() == "BCDX36HP":
                if (child / "scanner.inf").is_file() or (
                    child / "HPDB" / "hpdb.cfg"
                ).is_file():
                    return True
            if child.is_dir() and child.name.upper() == "HPDB":
                if (child / "hpdb.cfg").is_file():
                    return True
    except OSError:
        return False
    return False


def _linux_mount_roots(user: Optional[str] = None) -> List[Path]:
    name = user or os.environ.get("USER") or os.environ.get("USERNAME") or ""
    roots: List[Path] = []
    for base in (
        Path("/media") / name,
        Path("/run/media") / name,
        Path("/media"),
        Path("/mnt"),
    ):
        if not base.is_dir():
            continue
        try:
            for child in sorted(base.iterdir()):
                if child.is_dir():
                    roots.append(child)
        except OSError as exc:
            logger.debug("skip mount base %s: %s", base, exc)
    seen: set[str] = set()
    out: List[Path] = []
    for r in roots:
        key = str(r)
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def _windows_removable_roots() -> List[Path]:
    """Return drive roots with ``GetDriveTypeW == DRIVE_REMOVABLE``."""
    try:
        import ctypes
        import string
    except Exception:
        return []
    drive_removable = 2
    roots: List[Path] = []
    get_drive_type = ctypes.windll.kernel32.GetDriveTypeW
    for letter in string.ascii_uppercase:
        root = f"{letter}:\\"
        try:
            if get_drive_type(ctypes.c_wchar_p(root)) == drive_removable:
                roots.append(Path(root))
        except Exception:
            continue
    return roots


def candidate_mount_roots() -> List[Path]:
    """OS-specific list of likely removable / automount roots."""
    if sys.platform.startswith("linux"):
        return _linux_mount_roots()
    if sys.platform == "win32":
        return _windows_removable_roots()
    volumes = Path("/Volumes")
    if volumes.is_dir():
        try:
            return [p for p in sorted(volumes.iterdir()) if p.is_dir()]
        except OSError:
            return []
    return []


def discover_uniden_cards(
    search_roots: Optional[Sequence[Path]] = None,
) -> List[Path]:
    """Return card roots that contain a Uniden layout.

    Each path is normalized (``BCDx36HP`` parent preferred).
    """
    roots = list(search_roots) if search_roots is not None else candidate_mount_roots()
    found: List[Path] = []
    seen: set[str] = set()
    for root in roots:
        try:
            if not root.is_dir():
                continue
        except OSError:
            continue
        for candidate in (root, root / "BCDx36HP"):
            try:
                if not candidate.is_dir():
                    continue
            except OSError:
                continue
            if not has_uniden_layout(candidate):
                continue
            card = normalize_card_root(candidate)
            key = str(card)
            if key in seen:
                continue
            seen.add(key)
            found.append(card)
    return found
