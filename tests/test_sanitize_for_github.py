"""Tests for scripts/sanitize_for_github.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import sanitize_for_github as san  # noqa: E402

_SAMPLE_SESSION = """\
# SDS100 passive serial probe
# When     : 2026-04-27T14:30:17
# Host     : MINILAPTOP
# Port     : COM5  (baud=115200, 8N1)
# Output   : C:\\Users\\khutt\\OneDrive\\Desktop\\Projects\\scanner-manager\\AI\\Dev\\RE\\sessions\\out.txt
# Probe ID : 20260427T143017
"""


def test_sanitize_session_headers() -> None:
    rel = "Metacache/Dev/RE/sessions/sample.txt"
    out = san.sanitize_session_text(_SAMPLE_SESSION, rel)
    assert "khutt" not in out.lower()
    assert "MINILAPTOP" not in out
    assert "# Host     : <HOST>" in out
    assert "# Output   : <repo>/Metacache/Dev/RE/sessions/sample.txt" in out


def test_sanitize_analysis_dump_repo_root() -> None:
    payload = {"repo_root": "C:\\Users\\khutt\\scanner-manager", "version": 1}
    out = san.sanitize_analysis_dump(json.dumps(payload))
    data = json.loads(out)
    assert data["repo_root"] == "<repo>"
    assert "khutt" not in out.lower()


def test_audit_repo_clean_after_sanitize(tmp_path: Path) -> None:
    rel = "Metacache/Dev/RE/sessions/clean.txt"
    path = tmp_path / rel
    path.parent.mkdir(parents=True)
    path.write_text(
        san.sanitize_session_text(_SAMPLE_SESSION, rel),
        encoding="utf-8",
    )
    hits = san.audit_repo(
        tmp_path,
        ["khutt", "MAINGAMINGPC", "MiniLaptop", "G:\\scanner-manager", "C:\\Users\\khutt"],
    )
    assert hits == []
