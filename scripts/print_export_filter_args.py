#!/usr/bin/env python3
"""Print git-filter-repo --invert-paths arguments from metacache_export_rules.yaml."""

from __future__ import annotations

from pathlib import Path

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    raise SystemExit("PyYAML required") from exc


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    rules_path = root / "scripts" / "metacache_export_rules.yaml"
    rules = yaml.safe_load(rules_path.read_text(encoding="utf-8"))
    gi = rules.get("gitignore_only", {})
    for path in gi.get("paths", []):
        print(f"PATH\t{path}")
    for glob in gi.get("path_globs", []):
        print(f"GLOB\t{glob}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
