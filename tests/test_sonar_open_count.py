"""Optional regression guard for SonarCloud OPEN issue count."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

BASELINE_PATH = Path(__file__).resolve().parents[1] / ".sonar" / "issues_checklist_r4.json"
BASELINE_OPEN = 57


@pytest.mark.skipif(
    not os.environ.get("SONARCLOUD_TOKEN"),
    reason="SONARCLOUD_TOKEN not set",
)
def test_sonar_open_count_not_above_baseline() -> None:
    """Fail when Cloud OPEN issues exceed the Round 4 baseline file."""
    token = os.environ["SONARCLOUD_TOKEN"]
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    baseline_open = sum(1 for item in baseline["issues"] if item.get("status") == "OPEN")
    assert baseline_open == BASELINE_OPEN, (
        f"Baseline file lists {baseline_open} OPEN; expected {BASELINE_OPEN} "
        f"({BASELINE_PATH.name}). Re-export via SonarCloud MCP after remediation."
    )
    try:
        import urllib.request

        req = urllib.request.Request(
            "https://sonarcloud.io/api/issues/search?"
            "componentKeys=disturbedkh_scanner-manager&branch=main&statuses=OPEN&ps=1",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode())
    except OSError as exc:
        pytest.skip(f"SonarCloud API unavailable: {exc}")
    total = int(payload.get("total", baseline_open))
    assert total <= baseline_open, (
        f"SonarCloud OPEN {total} exceeds baseline {baseline_open}; "
        "refresh fixes or update .sonar/issues_checklist_r4.json after remediation."
    )
