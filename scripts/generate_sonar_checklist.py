"""Write a SonarCloud issue checklist JSON file from MCP export on stdin.

Pipe the ``issues`` array (or full search response) from ``user-Sonarcloud`` MCP:

    # Example: save MCP JSON to issues.json, then:
    python scripts/generate_sonar_checklist.py .sonar/issues_checklist_r5.json < issues.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def _load_issues(payload: object) -> list[dict]:
    if isinstance(payload, dict):
        issues = payload.get("issues")
        if isinstance(issues, list):
            return issues
    if isinstance(payload, list):
        return payload
    raise SystemExit("stdin JSON must be an issues list or {\"issues\": [...]} object")


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: generate_sonar_checklist.py OUTPUT.json < export.json")
    out = Path(sys.argv[1])
    payload = json.load(sys.stdin)
    issues = _load_issues(payload)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"issues": issues}, indent=2) + "\n", encoding="utf-8")
    open_count = sum(1 for item in issues if item.get("status") == "OPEN")
    print(f"Wrote {len(issues)} issues ({open_count} OPEN) to {out}")


if __name__ == "__main__":
    main()
