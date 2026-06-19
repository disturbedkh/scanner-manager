"""Shared pytest configuration for tiered CI jobs."""

from __future__ import annotations

import os

import pytest


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Unmarked tests default to the ``unit`` tier."""
    for item in items:
        if not any(item.iter_markers()):
            item.add_marker(pytest.mark.unit)


def pytest_configure(config: pytest.Config) -> None:
    if os.environ.get("RUN_SERIAL_TESTS") == "1":
        return
    config.addinivalue_line(
        "markers",
        "requires_serial: needs COM port / hardware (skipped in CI)",
    )


def pytest_runtest_setup(item: pytest.Item) -> None:
    if "requires_serial" in item.keywords and os.environ.get("RUN_SERIAL_TESTS") != "1":
        pytest.skip("requires_serial tests need RUN_SERIAL_TESTS=1")
