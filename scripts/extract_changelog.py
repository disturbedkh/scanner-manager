"""Extract CHANGELOG section for a release tag."""

from __future__ import annotations

import re
import sys
from pathlib import Path


def extract(version: str) -> str:
    changelog = Path(__file__).resolve().parents[1] / "CHANGELOG.md"
    text = changelog.read_text(encoding="utf-8")
    version = version.lstrip("v")
    pat = re.compile(
        rf"^##\s*\[?{re.escape(version)}\]?.*?$(.*?)(?=^##\s*\[|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pat.search(text)
    if match:
        return match.group(1).strip() + "\n"
    return f"See CHANGELOG.md for version {version}.\n"


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: extract_changelog.py vX.Y.Z", file=sys.stderr)
        return 1
    sys.stdout.write(extract(sys.argv[1]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
