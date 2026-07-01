"""PyInstaller output paths: build/<OS>/<Release|Development>/.

Used by packaging/scanner-manager.spec and documented for CI release jobs.
Set SCANNER_MANAGER_BUILD_TYPE=Release for tag builds; default is Development.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_BUILD_TYPES = frozenset({"Release", "Development"})


def os_folder() -> str:
    """Return Windows, macOS, or Linux for the current platform."""
    if sys.platform == "win32":
        return "Windows"
    if sys.platform == "darwin":
        return "macOS"
    return "Linux"


def _env_build_type() -> str:
    """Release or Development (from SCANNER_MANAGER_BUILD_TYPE)."""
    raw = os.environ.get("SCANNER_MANAGER_BUILD_TYPE", "Development").strip()
    if raw not in _BUILD_TYPES:
        return "Development"
    return raw


def build_type() -> str:
    """Release or Development (from SCANNER_MANAGER_BUILD_TYPE)."""
    return _env_build_type()


def dist_dir(repo_root: Path | str, *, build_type: str | None = None) -> Path:
    """Final PyInstaller artifacts: build/<OS>/<Type>/."""
    root = Path(repo_root).resolve()
    bt = build_type if build_type is not None else _env_build_type()
    return root / "build" / os_folder() / bt


def work_dir(repo_root: Path | str, *, build_type: str | None = None) -> Path:
    """PyInstaller intermediate files: build/<OS>/<Type>/.pyinstaller-work/."""
    return dist_dir(repo_root, build_type=build_type) / ".pyinstaller-work"
