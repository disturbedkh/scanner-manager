"""Shared pytest helpers."""

from __future__ import annotations

from pathlib import Path


def fixtures_dir() -> Path:
    """Return the ``tests/fixtures`` directory."""
    return Path(__file__).resolve().parent / "fixtures"
