"""Build provenance metadata for release artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _git_sha(repo_root: Path) -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return out.strip()
    except (OSError, subprocess.CalledProcessError):
        return os.environ.get("CI_COMMIT_SHA", "unknown")


def _lockfile_sha256(repo_root: Path) -> str | None:
    lock = repo_root / "requirements.lock"
    if not lock.is_file():
        return None
    digest = hashlib.sha256(lock.read_bytes()).hexdigest()
    return digest


def _package_version() -> str:
    try:
        from importlib.metadata import version

        return version("beartracker-885-scanner-manager")
    except Exception:
        return os.environ.get("SCANNER_MANAGER_VERSION", "unknown")


def build_provenance(
    *,
    build_type: str,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Return provenance dict for ``build-provenance.json``."""
    root = repo_root or _repo_root()
    sys.path.insert(0, str(root / "scripts"))
    from build_paths import os_folder  # noqa: E402

    return {
        "version": _package_version(),
        "git_sha": _git_sha(root),
        "ci_pipeline_id": os.environ.get("CI_PIPELINE_ID"),
        "ci_job_id": os.environ.get("CI_JOB_ID"),
        "python_version": platform.python_version(),
        "lockfile_sha256": _lockfile_sha256(root),
        "build_type": build_type,
        "platform": os_folder(),
        "built_at": datetime.now(timezone.utc).isoformat(),
    }


def write_provenance(path: Path, *, build_type: str, repo_root: Path | None = None) -> Path:
    """Write ``build-provenance.json`` next to release artifacts."""
    data = build_provenance(build_type=build_type, repo_root=repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path
