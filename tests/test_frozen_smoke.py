"""Contract tests for frozen ``--smoke`` mode (source-tree path)."""

from __future__ import annotations

from gui.app import run_smoke


def test_run_smoke_from_source_tree() -> None:
    assert run_smoke() == 0
