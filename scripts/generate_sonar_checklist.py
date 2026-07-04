"""Write a SonarCloud issue checklist JSON file from MCP export on stdin.

Pipe the ``issues`` array (or full search response) from ``user-Sonarcloud`` MCP:

    # Example: save MCP JSON to issues.json, then:
    python scripts/generate_sonar_checklist.py issues_checklist_r6.json < issues.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SONAR_BASE = REPO_ROOT / ".sonar"


def _load_issues(payload: object) -> list[dict]:
    if isinstance(payload, dict):
        issues = payload.get("issues")
        if isinstance(issues, list):
            return issues
    if isinstance(payload, list):
        return payload
    raise SystemExit("stdin JSON must be an issues list or {\"issues\": [...]} object")


def _validate_basename(name: str) -> str:
    if not name or name in {".", ".."}:
        raise SystemExit("output must be a non-empty basename")
    if "/" in name or "\\" in name or ".." in name:
        raise SystemExit("output must be a basename without path separators or ..")
    return name


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: generate_sonar_checklist.py OUTPUT.json < export.json")
    basename = _validate_basename(Path(sys.argv[1]).name)
    payload = json.load(sys.stdin)
    issues = _load_issues(payload)
    from core.path_utils import safe_write_text

    out = safe_write_text(
        SONAR_BASE,
        basename,
        json.dumps({"issues": issues}, indent=2) + "\n",
    )
    open_count = sum(1 for item in issues if item.get("status") == "OPEN")
    print(f"Wrote {len(issues)} issues ({open_count} OPEN) to {out}")


if __name__ == "__main__":
    main()
