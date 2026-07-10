"""Cross-platform user data directories (XDG / AppData / Application Support).

Env overrides (highest priority when set):

- ``SCANNER_MANAGER_CONFIG_DIR``
- ``SCANNER_MANAGER_CACHE_DIR``
- ``SCANNER_MANAGER_STATE_DIR``
- ``SCANNER_MANAGER_DATA_DIR``
- ``SCANNER_MANAGER_LOG_DIR`` (state/logs)
- ``SCANNER_MANAGER_VIRTUAL_SD_ROOT`` (virtual cards; see :func:`virtual_sd_root`)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_APP = "scanner-manager"


def _env_path(name: str) -> Path | None:
    raw = os.environ.get(name, "").strip()
    return Path(raw).expanduser() if raw else None


def config_dir() -> Path:
    """User config (devices.json, workspaces, city overrides, snapshots)."""
    override = _env_path("SCANNER_MANAGER_CONFIG_DIR")
    if override is not None:
        return override
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
        return base / _APP
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / _APP
    xdg = os.environ.get("XDG_CONFIG_HOME", "").strip()
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / _APP


def cache_dir() -> Path:
    """Download / firmware / installer caches."""
    override = _env_path("SCANNER_MANAGER_CACHE_DIR")
    if override is not None:
        return override
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
        return base / _APP / "cache"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / _APP
    xdg = os.environ.get("XDG_CACHE_HOME", "").strip()
    base = Path(xdg) if xdg else Path.home() / ".cache"
    return base / _APP


def state_dir() -> Path:
    """Crash logs and other mutable state."""
    override = _env_path("SCANNER_MANAGER_STATE_DIR") or _env_path("SCANNER_MANAGER_LOG_DIR")
    if override is not None:
        return override
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
        return base / _APP
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Logs" / _APP
    xdg = os.environ.get("XDG_STATE_HOME", "").strip()
    base = Path(xdg) if xdg else Path.home() / ".local" / "state"
    return base / _APP


def data_dir() -> Path:
    """Persistent user data (virtual cards, card backups, shared installers)."""
    override = _env_path("SCANNER_MANAGER_DATA_DIR")
    if override is not None:
        return override
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
        return base / _APP / "data"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / _APP / "data"
    xdg = os.environ.get("XDG_DATA_HOME", "").strip()
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / _APP


def virtual_sd_root() -> Path:
    """Default root for virtual SD card profiles.

    Honors ``SCANNER_MANAGER_VIRTUAL_SD_ROOT``. If the legacy
    ``~/.scanner-manager/virtual-cards`` directory already exists, keep
    using it so existing profiles are not orphaned.
    """
    override = _env_path("SCANNER_MANAGER_VIRTUAL_SD_ROOT")
    if override is not None:
        return override
    legacy = Path.home() / ".scanner-manager" / "virtual-cards"
    if legacy.is_dir():
        return legacy
    return data_dir() / "virtual-cards"
