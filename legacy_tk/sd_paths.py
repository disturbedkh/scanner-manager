"""Safe SD-card folder path resolution for legacy Tk."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

_MAX_PARENT_WALK = 64


def resolve_existing_folder(raw: str) -> Optional[Path]:
    """Resolve ``raw`` to an existing directory, or return None."""
    text = (raw or "").strip()
    if not text:
        return None
    try:
        resolved = Path(text).expanduser().resolve(strict=False)
    except (OSError, RuntimeError):
        return None
    if not resolved.is_dir():
        return None
    return resolved


def filesystem_space_root(folder: Path) -> Path:
    """Return the mount/volume root for ``folder`` (bounded parent walk)."""
    current = folder
    for _ in range(_MAX_PARENT_WALK):
        parent = current.parent
        if parent == current:
            break
        current = parent
    return current


def validated_sd_folder(raw: str) -> Optional[str]:
    """Return a normalized SD folder path when ``raw`` is a valid directory."""
    resolved = resolve_existing_folder(raw)
    if resolved is None:
        return None
    return str(resolved)
