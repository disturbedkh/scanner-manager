"""Smoke + behavior tests for the Live dock's virtual scanner faceplate."""

from __future__ import annotations

import os
from typing import List, Optional

import pytest

pytestmark = pytest.mark.qt

pytest.importorskip("pytestqt")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gui.live.virtual_scanner import (  # noqa: E402
    KeypadWidget,
    LcdScreenWidget,
    SoftKeyBar,
    VirtualScannerPanel,
    _line_to_html,
    _sanitize_lcd_text,
)
from scanner_drivers.serial_main import (  # noqa: E402
    GsiSnapshot,
    ScreenLine,
    ScreenSnapshot,
    SerialMainDriver,
)


class _FakeSerial:
    def __init__(self, responses: Optional[List] = None) -> None:
        self.writes: List[bytes] = []
        self._buffer = bytearray()
        self.responses = list(responses or [])

    def reset_input_buffer(self) -> None:
        self._buffer.clear()

    def write(self, data: bytes) -> int:
        self.writes.append(bytes(data))
        if self.responses:
            response = self.responses.pop(0)
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
        return None


def test_line_to_html_marks_reverse_and_underline():
    html = _line_to_html("AB", "*_")
    assert "background-color:#f2c200" in html
    assert "text-decoration:underline" in html


def test_sanitize_lcd_text_replaces_nonprintable_with_space():
    # U+FFFD (replacement char for icon bytes) and a raw control byte
    # both collapse to spaces, preserving length for mode alignment.
    assert _sanitize_lcd_text("AB\ufffdC") == "AB C"
    assert _sanitize_lcd_text("X\x01Y") == "X Y"
    assert len(_sanitize_lcd_text("12:34 \ufffd\ufffd")) == len("12:34 \ufffd\ufffd")


def test_lcd_sanitizes_screen_glyphs(qtbot):
    lcd = LcdScreenWidget()
    qtbot.addWidget(lcd)
    snap = ScreenSnapshot(
        dsp_form="0",
        lines=[ScreenLine(text="Jun25 14:58 \ufffd\ufffd", mode="")],
    )
    lcd.update_screen(snap)
    body = lcd._body.text()
    assert "\ufffd" not in body
    # Spaces render as &nbsp;, so check the printable tokens survive.
    assert "Jun25" in body
    assert "14:58" in body


def test_lcd_renders_screen_snapshot(qtbot):
    lcd = LcdScreenWidget()
    qtbot.addWidget(lcd)
    snap = ScreenSnapshot(
        dsp_form="11",
        lines=[
            ScreenLine(text="Police Detectives", mode="*" * 17, large_font=True),
            ScreenLine(text="852.4125 MHz", mode="", large_font=True),
        ],
    )
    lcd.update_screen(snap)
    body = lcd._body.text()
    assert "Police" in body
    assert "852.4125" in body


def test_lcd_gsi_overlay(qtbot):
    lcd = LcdScreenWidget()
    qtbot.addWidget(lcd)
    snap = GsiSnapshot(
        frequency_hz=852_412_500, signal_pct=80, is_receiving=True
    )
    lcd.update_gsi(snap)
    assert "852.41250 MHz" in lcd._freq_label.text()
    assert lcd._signal_bar.value() == 80


def test_keypad_starts_disabled_and_enables_with_driver(qtbot):
    kp = KeypadWidget()
    qtbot.addWidget(kp)
    assert not kp._func_btn.isEnabled()
    assert all(not b.isEnabled() for b in kp._buttons)

    fake = _FakeSerial()
    driver = SerialMainDriver(fake)
    kp.set_driver(driver)
    assert kp._func_btn.isEnabled()
    assert all(b.isEnabled() for b in kp._buttons)


def test_keypad_sends_key(qtbot):
    fake = _FakeSerial(responses=[b"KEY,OK\r"])
    driver = SerialMainDriver(fake)
    kp = KeypadWidget()
    qtbot.addWidget(kp)
    messages: list = []
    kp.statusMessage.connect(messages.append)
    kp.set_driver(driver)
    kp._on_key("M", "P")
    # Wait for the worker thread to fully finish (status emitted + the
    # QThread drained) so it doesn't outlive the widget at teardown.
    qtbot.waitUntil(lambda: bool(messages), timeout=2000)
    qtbot.waitUntil(lambda: not kp._workers, timeout=2000)
    assert fake.writes == [b"KEY,M,P\r"]


def test_keypad_func_modifier_prefixes_key(qtbot):
    fake = _FakeSerial(responses=[b"KEY,OK\r", b"KEY,OK\r"])
    driver = SerialMainDriver(fake)
    kp = KeypadWidget()
    qtbot.addWidget(kp)
    messages: list = []
    kp.statusMessage.connect(messages.append)
    kp.set_driver(driver)
    kp._func_btn.setChecked(True)
    kp._on_key("1", "P")
    qtbot.waitUntil(lambda: bool(messages), timeout=2000)
    qtbot.waitUntil(lambda: not kp._workers, timeout=2000)
    assert fake.writes == [b"KEY,F,P\r", b"KEY,1,P\r"]
    # Func auto-resets after use.
    assert not kp._func_btn.isChecked()


def test_soft_key_bar_disabled_without_driver(qtbot):
    bar = SoftKeyBar()
    qtbot.addWidget(bar)
    assert len(bar._buttons) == 3
    assert [b._code for b in bar._buttons] == ["A", "B", "C"]
    assert all(not b.isEnabled() for b in bar._buttons)
    bar.set_active(True)
    assert all(b.isEnabled() for b in bar._buttons)


def test_soft_key_bar_routes_through_keypad(qtbot):
    fake = _FakeSerial(responses=[b"KEY,OK\r"])
    driver = SerialMainDriver(fake)
    kp = KeypadWidget()
    qtbot.addWidget(kp)
    bar = SoftKeyBar()
    qtbot.addWidget(bar)
    bar.bind_keypad(kp)
    messages: list = []
    kp.statusMessage.connect(messages.append)
    kp.set_driver(driver)
    bar.set_active(True)

    # Activating the System soft key (code "A") dispatches through the
    # keypad's shared send path.
    bar._buttons[0].keyActivated.emit("A", "P")
    qtbot.waitUntil(lambda: bool(messages), timeout=2000)
    qtbot.waitUntil(lambda: not kp._workers, timeout=2000)
    assert fake.writes == [b"KEY,A,P\r"]


def test_panel_fans_out_driver_and_updates(qtbot):
    fake = _FakeSerial(responses=[b"VOL,7\r", b"SQL,3\r"])
    driver = SerialMainDriver(fake)
    panel = VirtualScannerPanel()
    qtbot.addWidget(panel)
    panel.set_driver(driver)
    assert panel._keypad._func_btn.isEnabled()
    assert panel._knobs._vol_slider.isEnabled()
    assert all(b.isEnabled() for b in panel._softkeys._buttons)
    # Let the knob read-back workers finish before teardown.
    qtbot.waitUntil(lambda: panel._knobs._vol_value.text() == "7", timeout=2000)
    qtbot.waitUntil(lambda: not panel._knobs._workers, timeout=2000)

    panel.update_screen(
        ScreenSnapshot(dsp_form="1", lines=[ScreenLine(text="Scan", mode="")])
    )
    assert "Scan" in panel._lcd._body.text()

    panel.set_driver(None)
    assert not panel._keypad._func_btn.isEnabled()
    assert all(not b.isEnabled() for b in panel._softkeys._buttons)
