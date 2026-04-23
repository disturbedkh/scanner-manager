"""Tests for the global crash log writer.

We only test the log-writing layer here, not the Tk exception hook
itself (which is purely wiring). The log writer is deliberately
side-effect-minimal and safe to call without a display.
"""
from __future__ import annotations

import re

import scanner_manager


def _raise_and_capture():
    """Raise an exception and return the (type, value, tb) triple."""
    import sys
    try:
        raise ValueError("synthetic crash for test")
    except ValueError:
        return sys.exc_info()


def test_crash_log_dir_honors_env_override(monkeypatch, tmp_path):
    target = tmp_path / "custom-logs"
    monkeypatch.setenv("SCANNER_MANAGER_LOG_DIR", str(target))
    assert scanner_manager._crash_log_dir() == target


def test_write_crash_log_creates_file_with_expected_shape(
    monkeypatch, tmp_path
):
    target = tmp_path / "logs"
    monkeypatch.setenv("SCANNER_MANAGER_LOG_DIR", str(target))
    exc_type, exc_value, exc_tb = _raise_and_capture()

    log_path = scanner_manager._write_crash_log(exc_type, exc_value, exc_tb)

    assert log_path.parent == target, (
        f"log should land in override dir, got {log_path}"
    )
    assert log_path.exists()
    assert log_path.name.startswith("crash-")
    assert log_path.name.endswith(".log")
    # Filename should carry the timestamp format crash-YYYYMMDD-HHMMSS.log.
    assert re.match(r"^crash-\d{8}-\d{6}\.log$", log_path.name), log_path.name

    text = log_path.read_text(encoding="utf-8")
    assert "Scanner Manager" in text
    assert f"v{scanner_manager.APP_VERSION}" in text
    assert "ValueError: synthetic crash for test" in text
    assert "_raise_and_capture" in text, (
        "Traceback should include the raising frame"
    )


def test_write_crash_log_does_not_raise_on_bad_dir(monkeypatch, tmp_path):
    """Even if the override path can't be created we must not bubble
    the error up - a crash reporter that crashes on its way out is
    worse than useless.
    """
    # Point at a path that cannot be created because the parent is a file.
    blocker = tmp_path / "not-a-dir"
    blocker.write_bytes(b"sentinel")
    monkeypatch.setenv(
        "SCANNER_MANAGER_LOG_DIR", str(blocker / "logs")
    )
    exc_type, exc_value, exc_tb = _raise_and_capture()
    # Should not raise.
    log_path = scanner_manager._write_crash_log(exc_type, exc_value, exc_tb)
    assert log_path is not None
