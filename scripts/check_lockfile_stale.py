# Verify requirements.lock matches pyproject.toml (fail CI when stale).
# Usage: python scripts/check_lockfile_stale.py
#
# Uses ``uv pip compile --universal`` so OS markers (e.g. pywin32) stay
# in the lock. Requires ``uv`` on PATH (GitLab/GitHub images install it
# or the job must provide it).
#
# Compiles into a copy of the current lock so uv keeps existing pins
# (same as refreshing in place). A pyproject.toml change that alters
# the resolved set still fails the body comparison.

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def _lock_body(text: str) -> str:
    """Compare dependency pins only (ignore compile header comments)."""
    lines: list[str] = []
    for line in text.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    lock = root / "requirements.lock"
    if not lock.is_file():
        print(
            "requirements.lock missing — run scripts/refresh_lockfile.sh "
            "or scripts/refresh_lockfile.ps1",
            file=sys.stderr,
        )
        return 1

    if not shutil.which("uv"):
        print(
            "uv is required to verify requirements.lock — "
            "install https://docs.astral.sh/uv/",
            file=sys.stderr,
        )
        return 1

    fd, tmp_name = tempfile.mkstemp(suffix=".lock")
    os.close(fd)
    tmp_path = Path(tmp_name)

    try:
        # Seed with current lock so uv treats existing pins as constraints
        # (matches in-place refresh behavior).
        shutil.copyfile(lock, tmp_path)
        subprocess.run(
            [
                "uv",
                "pip",
                "compile",
                "pyproject.toml",
                "--universal",
                "--python-version",
                "3.11",
                "--extra",
                "full",
                "--extra",
                "dev",
                "--output-file",
                str(tmp_path),
                "--strip-extras",
            ],
            cwd=root,
            check=True,
            capture_output=True,
        )
        fresh = tmp_path.read_text(encoding="utf-8")
        current = lock.read_text(encoding="utf-8")
        if _lock_body(fresh) != _lock_body(current):
            print(
                "requirements.lock is stale — run scripts/refresh_lockfile.sh "
                "or scripts/refresh_lockfile.ps1 and commit",
                file=sys.stderr,
            )
            return 1
    finally:
        tmp_path.unlink(missing_ok=True)

    print("requirements.lock is up to date")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
