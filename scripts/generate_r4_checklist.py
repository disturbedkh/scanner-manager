"""Write .sonar/issues_checklist_r4.json from SonarCloud MCP snapshot (2026-07-04)."""
from __future__ import annotations

import json
from pathlib import Path

# user-Sonarcloud MCP: disturbedkh_scanner-manager / main / OPEN / total=57
_ROWS = [
    ("AZ8szLmEyU4aPEVU5zRC", "pythonsecurity:S8707", "Metacache/Dev/RE/tools/firmware/extract_dispatch.py", "MAJOR", 150),
    ("AZ8szLyeyU4aPEVU5zRL", "python:S3776", "legacy_tk/scanner_manager.py", "CRITICAL", 1958),
    ("AZ8szLyeyU4aPEVU5zRN", "python:S1172", "legacy_tk/scanner_manager.py", "MAJOR", 2870),
    ("AZ8szLyeyU4aPEVU5zRM", "python:S1172", "legacy_tk/scanner_manager.py", "MAJOR", 2871),
    ("AZ8szLzhyU4aPEVU5zRQ", "python:S1172", "legacy_tk/sm_helpers.py", "MAJOR", 295),
    ("AZ8szLzhyU4aPEVU5zRR", "python:S3776", "legacy_tk/sm_helpers.py", "CRITICAL", 415),
    ("AZ8szLzhyU4aPEVU5zRS", "python:S3776", "legacy_tk/sm_helpers.py", "CRITICAL", 455),
    ("AZ8szLzhyU4aPEVU5zRT", "python:S3776", "legacy_tk/sm_helpers.py", "CRITICAL", 489),
    ("AZ8szLzhyU4aPEVU5zRU", "python:S3776", "legacy_tk/sm_helpers.py", "CRITICAL", 894),
    ("AZ8szLzhyU4aPEVU5zRV", "python:S3776", "legacy_tk/sm_helpers.py", "CRITICAL", 937),
    ("AZ8szLzhyU4aPEVU5zRW", "python:S3776", "legacy_tk/sm_helpers.py", "CRITICAL", 1024),
    ("AZ8szLzhyU4aPEVU5zRX", "python:S3776", "legacy_tk/sm_helpers.py", "CRITICAL", 1158),
    ("AZ8szLzhyU4aPEVU5zRY", "python:S3776", "legacy_tk/sm_helpers.py", "CRITICAL", 1210),
    ("AZ8szLzhyU4aPEVU5zRZ", "python:S3776", "legacy_tk/sm_helpers.py", "CRITICAL", 1284),
    ("AZ8szLzhyU4aPEVU5zRa", "python:S3776", "legacy_tk/sm_helpers.py", "CRITICAL", 1361),
    ("AZ8szLzhyU4aPEVU5zRb", "python:S3776", "legacy_tk/sm_helpers.py", "CRITICAL", 1408),
    ("AZ8szLzhyU4aPEVU5zRc", "python:S3776", "legacy_tk/sm_helpers.py", "CRITICAL", 1437),
    ("AZ8szLzhyU4aPEVU5zRd", "python:S3776", "legacy_tk/sm_helpers.py", "CRITICAL", 1455),
    ("AZ8szLzhyU4aPEVU5zRe", "python:S1172", "legacy_tk/sm_helpers.py", "MAJOR", 1561),
    ("AZ8szLwTyU4aPEVU5zRJ", "pythonsecurity:S2083", "scripts/pin_uniden_hashes.py", "BLOCKER", 116),
    ("AZ8szLxAyU4aPEVU5zRK", "pythonsecurity:S2083", "scripts/sanitize_for_github.py", "BLOCKER", 193),
    ("AZ8szLq8yU4aPEVU5zRD", "python:S1186", "tests/test_security_paths.py", "CRITICAL", 117),
    ("AZ8szLq8yU4aPEVU5zRE", "python:S1186", "tests/test_security_paths.py", "CRITICAL", 123),
    ("AZ8szLq8yU4aPEVU5zRF", "python:S1186", "tests/test_security_paths.py", "CRITICAL", 126),
    ("AZ8szLq8yU4aPEVU5zRG", "python:S1186", "tests/test_security_paths.py", "CRITICAL", 129),
    ("AZ8szLy1yU4aPEVU5zRO", "python:S6019", "legacy_tk/rr_html_parsers.py", "MAJOR", 43),
    ("AZ8szLy1yU4aPEVU5zRP", "python:S6353", "legacy_tk/rr_html_parsers.py", "MINOR", 46),
    ("AZ8szLsIyU4aPEVU5zRH", "python:S1244", "tests/test_legacy_tk_helpers.py", "MAJOR", 36),
    ("AZ8szLsIyU4aPEVU5zRI", "python:S1244", "tests/test_legacy_tk_helpers.py", "MAJOR", 147),
    ("AZ8soFvxGDXFdEz1cbwP", "python:S1172", "legacy_tk/scanner_manager.py", "MAJOR", 2510),
    ("AZ8soFvxGDXFdEz1cbwO", "python:S1172", "legacy_tk/scanner_manager.py", "MAJOR", 2511),
    ("AZ8soFvxGDXFdEz1cbwQ", "python:S1172", "legacy_tk/scanner_manager.py", "MAJOR", 4056),
    ("AZ8soFvxGDXFdEz1cbwR", "python:S1172", "legacy_tk/scanner_manager.py", "MAJOR", 4056),
    ("AZ8soFuoGDXFdEz1cbv7", "python:S8786", "legacy_tk/geo_tables.py", "MAJOR", 644),
    ("AZ8soFwDGDXFdEz1cbwZ", "python:S3776", "legacy_tk/import_dialogs.py", "CRITICAL", 205),
    ("AZ8soFwDGDXFdEz1cbwb", "python:S3776", "legacy_tk/import_dialogs.py", "CRITICAL", 558),
    ("AZ8sYd8u8tc1zsIwO_6I", "python:S5332", "firmware/ftp_client.py", "MINOR", 180),
    ("AZ8qKx40_PZEko83iUWS", "text:S8565", "pyproject.toml", "MAJOR", 0),
    ("AZ8qKxuk_PZEko83iUTz", "python:S3776", "Metacache/Dev/RE/tools/probes/sub_probe.py", "CRITICAL", 414),
    ("AZ8qKx5y_PZEko83iUXA", "python:S3776", "legacy_tk/scanner_manager.py", "CRITICAL", 462),
    ("AZ8qKx5y_PZEko83iUWu", "python:S1066", "legacy_tk/scanner_manager.py", "MAJOR", 2086),
    ("AZ8qKx5y_PZEko83iUXU", "python:S3776", "legacy_tk/scanner_manager.py", "CRITICAL", 2211),
    ("AZ8qKx5y_PZEko83iUXX", "python:S3776", "legacy_tk/scanner_manager.py", "CRITICAL", 2964),
    ("AZ8qKx5y_PZEko83iUXa", "python:S3776", "legacy_tk/scanner_manager.py", "CRITICAL", 3560),
    ("AZ8qKx5y_PZEko83iUXc", "python:S3776", "legacy_tk/scanner_manager.py", "CRITICAL", 3696),
    ("AZ8qKx5y_PZEko83iUXb", "python:S1481", "legacy_tk/scanner_manager.py", "MINOR", 3738),
    ("AZ8qKx5y_PZEko83iUXf", "python:S3776", "legacy_tk/scanner_manager.py", "CRITICAL", 4171),
    ("AZ8qKx5y_PZEko83iUXg", "python:S3776", "legacy_tk/scanner_manager.py", "CRITICAL", 4224),
    ("AZ8qKx5y_PZEko83iUXh", "python:S3776", "legacy_tk/scanner_manager.py", "CRITICAL", 4259),
    ("AZ8qKx5y_PZEko83iUXj", "python:S3776", "legacy_tk/scanner_manager.py", "CRITICAL", 4958),
    ("AZ8qKx5y_PZEko83iUXl", "python:S3776", "legacy_tk/scanner_manager.py", "CRITICAL", 5181),
    ("AZ8qKx5y_PZEko83iUXm", "python:S3776", "legacy_tk/scanner_manager.py", "CRITICAL", 5256),
    ("AZ8qKx5y_PZEko83iUXs", "python:S3776", "legacy_tk/scanner_manager.py", "CRITICAL", 5719),
    ("AZ8qKx5y_PZEko83iUX1", "python:S3776", "legacy_tk/scanner_manager.py", "CRITICAL", 6676),
    ("AZ8qKx5y_PZEko83iUWw", "python:S1066", "legacy_tk/scanner_manager.py", "MAJOR", 8113),
    ("AZ8qKx5y_PZEko83iUWx", "python:S1066", "legacy_tk/scanner_manager.py", "MAJOR", 8574),
    ("AZ8qKx5y_PZEko83iUX9", "python:S1172", "legacy_tk/scanner_manager.py", "MAJOR", 9425),
]

PROJECT = "disturbedkh_scanner-manager"
OUT = Path(__file__).resolve().parents[1] / ".sonar" / "issues_checklist_r4.json"


def main() -> None:
    issues = []
    for key, rule, component, severity, line in _ROWS:
        entry = {
            "key": key,
            "rule": rule,
            "project": PROJECT,
            "component": f"{PROJECT}:{component}",
            "severity": severity,
            "status": "OPEN",
            "message": "",
            "cleanCodeAttribute": "",
            "cleanCodeAttributeCategory": "",
            "author": "33725942+disturbedkh@users.noreply.github.com",
            "creationDate": "2026-07-04T11:02:57+0000",
        }
        if line:
            entry["textRange"] = {"startLine": line, "endLine": line}
        issues.append(entry)
    assert len(issues) == 57, len(issues)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({"issues": issues}, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(issues)} OPEN issues to {OUT}")


if __name__ == "__main__":
    main()
