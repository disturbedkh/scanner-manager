"""Smoke tests for the Live dock's scanner-control panel."""

from __future__ import annotations

import os
from typing import List, Optional

import pytest

pytestmark = pytest.mark.qt

pytest.importorskip("pytestqt")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gui.live.scanner_control import ScannerControlWidget  # noqa: E402
from scanner_drivers.serial_main import (  # noqa: E402
    SAFE_CONTROL_KEYS,
    SerialMainDriver,
)


# Reuse the FakeSerial from the driver tests
class _FakeSerial:
    def __init__(self, responses: Optional[List] = None) -> None:
        self.writes: List[bytes] = []
        self._buffer = bytearray()
        self.responses = list(responses or [])
        self.closed = False

    def reset_input_buffer(self) -> None:
        self._buffer.clear()

    def write(self, data: bytes) -> int:
        self.writes.append(bytes(data))
        if self.responses:
            response = self.responses.pop(0)
            if callable(response):
                response = response(data)
            self._buffer.extend(response)
        return len(data)

    def flush(self) -> None:
        return None

    @property
    def in_waiting(self) -> int:
        return len(self._buffer)

    def read(self, n: int = 1) -> bytes:
        out = bytes(self._buffer[:n])
        del self._buffer[:n]
        return out

    def close(self) -> None:
        self.closed = True


def test_widget_starts_disabled(qtbot):
    w = ScannerControlWidget()
    qtbot.addWidget(w)
    assert not w._vol_slider.isEnabled()
    assert not w._sql_slider.isEnabled()
    for btn in (w._hold_btn, w._scan_btn, w._avoid_btn,
                w._prev_btn, w._next_btn, w._replay_btn):
        assert not btn.isEnabled()


def test_set_driver_enables_controls(qtbot):
    fake = _FakeSerial(responses=[b"VOL,7\r", b"SQL,3\r"])
    driver = SerialMainDriver(fake)
    w = ScannerControlWidget()
    qtbot.addWidget(w)
    w.set_driver(driver)
    assert w._vol_slider.isEnabled()
    assert w._hold_btn.isEnabled()
    # Drop the driver -> controls go back to disabled.
    w.set_driver(None)
    assert not w._vol_slider.isEnabled()


def test_safe_control_keys_match_driver_whitelist():
    """Sanity check: every label the widget will surface must resolve
    to a key code that the driver accepts.
    """
    fake = _FakeSerial(responses=[b"KEY,OK\r"] * len(SAFE_CONTROL_KEYS))
    driver = SerialMainDriver(fake)
    for _label, (key, mode) in SAFE_CONTROL_KEYS.items():
        # Should NOT raise.
        driver.send_key(key, mode)


def test_widget_does_not_crash_when_buttons_clicked_without_driver(qtbot):
    w = ScannerControlWidget()
    qtbot.addWidget(w)
    # All buttons disabled, but force-click via the slot directly to
    # confirm it no-ops gracefully.
    w._on_key_clicked("Hold / Resume")
    w._on_vol_committed()
    w._on_sql_committed()


def test_hold_button_label_resolves_via_safe_control_keys():
    assert "Hold / Resume" in SAFE_CONTROL_KEYS
    key, mode = SAFE_CONTROL_KEYS["Hold / Resume"]
    assert key == "H"
    assert mode == "P"


def test_vol_sql_and_key_commands_with_driver(qtbot):
    fake = _FakeSerial(
        responses=[
            b"VOL,7\r",
            b"SQL,3\r",
            b"VOL,OK\r",
            b"SQL,OK\r",
            b"KEY,OK\r",
        ]
    )
    driver = SerialMainDriver(fake)
    w = ScannerControlWidget()
    qtbot.addWidget(w)
    messages: list = []
    w.statusMessage.connect(messages.append)
    w.set_driver(driver)

    qtbot.waitUntil(lambda: w._vol_value.text() == "7", timeout=3000)
    qtbot.waitUntil(lambda: w._sql_value.text() == "3", timeout=3000)

    w._vol_slider.setValue(9)
    w._on_vol_committed()
    qtbot.waitUntil(lambda: any("VOL" in m for m in messages), timeout=2000)

    w._sql_slider.setValue(5)
    w._on_sql_committed()
    qtbot.waitUntil(lambda: sum("SQL" in m for m in messages) >= 1, timeout=2000)

    w._on_key_clicked("Hold / Resume")
    qtbot.waitUntil(lambda: any("KEY" in m for m in messages), timeout=2000)


def test_read_state_handles_driver_errors(qtbot):
    class _BrokenSerial(_FakeSerial):
        def write(self, data: bytes) -> int:
            raise OSError("serial gone")

    driver = SerialMainDriver(_BrokenSerial())
    w = ScannerControlWidget()
    qtbot.addWidget(w)
    w.set_driver(driver)
    qtbot.waitUntil(lambda: w._vol_value.text() == "?", timeout=2000)
    assert w._sql_value.text() == "?"


def test_unknown_key_label_emits_status(qtbot):
    fake = _FakeSerial(responses=[b"VOL,1\r", b"SQL,1\r"])
    driver = SerialMainDriver(fake)
    w = ScannerControlWidget()
    qtbot.addWidget(w)
    messages: list = []
    w.statusMessage.connect(messages.append)
    w.set_driver(driver)
    w._on_key_clicked("Not A Real Button")
    qtbot.waitUntil(lambda: bool(messages), timeout=2000)
    assert any("Unknown key" in m for m in messages)
