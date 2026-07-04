"""Single source of truth for application identity at runtime.

The version is resolved in priority order:

1. Installed distribution metadata via :func:`importlib.metadata.version`.
   This is the authoritative path for both ``pip install`` runs and the
   frozen PyInstaller build (the spec bundles the ``*.dist-info`` via
   ``copy_metadata`` so this keeps working inside the EXE).
2. ``[project].version`` read straight from ``pyproject.toml`` when running
   from a source checkout that was never installed (``tomllib`` ships with
   Python 3.11+, which is our floor).
3. A clearly-bogus sentinel, so a missing version is obvious rather than a
   stale hardcoded string.

Keeping this in one place means ``pyproject.toml`` is the only place a
human edits the version; nothing else hardcodes it.
"""

from __future__ import annotations

from pathlib import Path

APP_NAME = "Scanner Manager"
DIST_NAME = "beartracker-885-scanner-manager"
_UNKNOWN = "0.0.0+unknown"


def _version_from_pyproject() -> str | None:
    """Best-effort read of ``[project].version`` from the repo pyproject."""
    try:
        import tomllib
    except ImportError:
        return None
    try:
        root = Path(__file__).resolve().parents[1]
        data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # Missing/unreadable file or malformed TOML (TOMLDecodeError < ValueError).
        return None
    version = data.get("project", {}).get("version")
    return str(version) if version else None


def get_version() -> str:
    """Return the application version from the single source of truth."""
    try:
        from importlib.metadata import PackageNotFoundError, version
    except ImportError:
        return _version_from_pyproject() or _UNKNOWN
    try:
        return version(DIST_NAME)
    except PackageNotFoundError:
        return _version_from_pyproject() or _UNKNOWN
