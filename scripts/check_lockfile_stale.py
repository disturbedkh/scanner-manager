# Verify requirements.lock matches pyproject.toml (fail CI when stale).
# Usage: python scripts/check_lockfile_stale.py

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path


def _lock_body(text: str) -> str:
    """Compare dependency pins only (ignore pip-compile header comments)."""
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
        print("requirements.lock missing — run scripts/refresh_lockfile.ps1", file=sys.stderr)
        return 1

    fd, tmp_name = tempfile.mkstemp(suffix=".lock")
    os.close(fd)
    tmp_path = Path(tmp_name)

    try:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "piptools",
                "compile",
                "pyproject.toml",
                "--extra",
                "full",
                "--extra",
                "dev",
                "--output-file",
                str(tmp_path),
                "--strip-extras",
                "--quiet",
            ],
            cwd=root,
            check=True,
        )
        fresh = tmp_path.read_text(encoding="utf-8")
        current = lock.read_text(encoding="utf-8")
        if _lock_body(fresh) != _lock_body(current):
            print(
                "requirements.lock is stale — run scripts/refresh_lockfile.ps1 and commit",
                file=sys.stderr,
            )
            return 1
    finally:
        tmp_path.unlink(missing_ok=True)

    print("requirements.lock is up to date")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
