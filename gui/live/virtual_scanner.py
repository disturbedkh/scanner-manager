"""Virtual SDS100 faceplate for the Live dock.

Three widgets compose a ProScan-style "software scanner":

- :class:`LcdScreenWidget` - reconstructs the scanner LCD from the
  ``STS`` text readout (with reverse-video / underline honored) and
  overlays ``GSI``-derived status (signal bars, RX indicator,
  frequency / TGID, soft-key labels).
- :class:`KeypadWidget` - the full physical keypad as clickable
  buttons. Every documented key code is wired, with a Func modifier
  and long-press support, so the scanner is fully controllable from
  the PC. Sends go through the validated
  :meth:`SerialMainDriver.send_key` path.
- :class:`SoftKeyBar` - the System/Dept/Channel context soft keys as
  clickable buttons beneath the screen.
- :class:`VirtualScannerPanel` - arranges the LCD + soft keys (left) and
  the Volume/Squelch knobs + keypad (right) into the dock's faceplate.
"""

from __future__ import annotations

import logging
from html import escape
from typing import List, Optional, Tuple

from PySide6.QtCore import QElapsedTimer, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from scanner_drivers.serial_main import (
    KEYPAD_KEYS,
    GsiSnapshot,
    ScreenSnapshot,
    SerialMainDriver,
)

from .scanner_control import ScannerControlWidget, _SerialCallWorker

logger = logging.getLogger(__name__)

# Long-press threshold: holding a button past this many milliseconds
# sends the key with the "L" (long) press mode instead of "P".
_LONG_PRESS_MS = 600

# Shared LCD styling fragments.
_RX_IDLE_STYLE = "color: #555; font-weight: bold;"
_RX_ACTIVE_STYLE = "color: #3ddc84; font-weight: bold;"


# ---------------------------------------------------------------------------
# LCD screen
# ---------------------------------------------------------------------------


def _sanitize_lcd_text(text: str) -> str:
    """Replace non-renderable characters with spaces.

    The scanner's status bar uses private icon bytes (battery, GPS,
    S-meter glyphs) that decode to U+FFFD; the monospace font draws
    those as tofu boxes. Map anything outside printable ASCII to a
    space, preserving length so the positionally-aligned ``mode`` string
    stays in sync.
    """
    return "".join(ch if 0x20 <= ord(ch) <= 0x7E else " " for ch in text)


def _classify_mode(mode_char: str) -> str:
    if mode_char == "*":
        return "reverse"
    if mode_char == "_":
        return "underline"
    return "normal"


def _render_segment(style: str, chars: str) -> str:
    safe = escape(chars).replace(" ", "&nbsp;")
    if style == "reverse":
        return (
            '<span style="background-color:#f2c200;color:#101218;">'
            f"{safe}</span>"
        )
    if style == "underline":
        return f'<span style="text-decoration:underline;">{safe}</span>'
    return safe


def _line_to_html(text: str, mode: str) -> str:
    """Render one ``(text, mode)`` STS line as styled HTML.

    Mode characters are positionally aligned with the text: ``'*'``
    reverse video (rendered as a highlighted bar, mimicking the
    scanner's yellow selection highlight), ``'_'`` underline, anything
    else normal. Consecutive same-style characters are grouped into a
    single span to keep the markup small.
    """
    if not text:
        return "&nbsp;"
    mode = (mode or "").ljust(len(text))
    segments: List[Tuple[str, str]] = []  # (style_key, chars)
    for ch, m in zip(text, mode):
        style = _classify_mode(m)
        if segments and segments[-1][0] == style:
            segments[-1] = (style, segments[-1][1] + ch)
        else:
            segments.append((style, ch))
    return "".join(_render_segment(style, chars) for style, chars in segments)


class LcdScreenWidget(QFrame):
    """Reconstructed scanner LCD driven by STS + GSI."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("lcdScreen")
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet(
            "#lcdScreen {"
            " background-color: #0a0e14;"
            " border: 2px solid #2a2f3a;"
            " border-radius: 8px;"
            "}"
        )
        self.setMinimumHeight(220)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        layout.addLayout(self._build_header())

        self._body = QLabel("")
        self._body.setTextFormat(Qt.RichText)
        self._body.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self._body.setWordWrap(False)
        self._body.setStyleSheet(
            "font-family: 'Consolas','DejaVu Sans Mono',monospace;"
            " font-size: 13px; color: #e8c547;"
        )
        self._body.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self._body, 1)

        self._set_placeholder()

    # -- build helpers --------------------------------------------------

    def _build_header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        header.setSpacing(8)

        self._rx_label = QLabel("\u25cf")  # filled circle
        self._rx_label.setStyleSheet(_RX_IDLE_STYLE)
        header.addWidget(self._rx_label)

        self._freq_label = QLabel("")
        self._freq_label.setStyleSheet(
            "color: #6cd3ff; font-weight: bold; font-size: 13px;"
        )
        header.addWidget(self._freq_label)

        header.addStretch(1)

        self._signal_bar = QProgressBar()
        self._signal_bar.setRange(0, 100)
        self._signal_bar.setValue(0)
        self._signal_bar.setTextVisible(False)
        self._signal_bar.setFixedSize(90, 12)
        self._signal_bar.setStyleSheet(
            "QProgressBar { background:#11151c; border:1px solid #2a2f3a;"
            " border-radius:3px; }"
            "QProgressBar::chunk { background:#3ddc84; border-radius:2px; }"
        )
        header.addWidget(self._signal_bar)
        return header

    def _set_placeholder(self) -> None:
        self._body.setText(
            '<span style="color:#5a6472;">Connect the scanner to mirror'
            " its screen here.</span>"
        )

    # -- updates --------------------------------------------------------

    def update_screen(self, snap: ScreenSnapshot) -> None:
        if not snap.lines:
            return
        rows = [
            _line_to_html(_sanitize_lcd_text(line.text), line.mode)
            for line in snap.lines
        ]
        self._body.setText("<div>" + "<br>".join(rows) + "</div>")

    def update_gsi(self, snap: GsiSnapshot) -> None:
        if snap.is_receiving:
            self._rx_label.setStyleSheet(_RX_ACTIVE_STYLE)
            self._rx_label.setToolTip("Receiving")
        else:
            self._rx_label.setStyleSheet(_RX_IDLE_STYLE)
            self._rx_label.setToolTip("Idle")

        if snap.frequency_hz:
            self._freq_label.setText(f"{snap.frequency_hz / 1e6:.5f} MHz")
        elif snap.tgid:
            self._freq_label.setText(f"TGID {snap.tgid}")
        else:
            self._freq_label.setText("")

        self._signal_bar.setValue(
            max(0, min(100, snap.signal_pct)) if snap.signal_pct is not None else 0
        )

    def clear(self) -> None:
        self._rx_label.setStyleSheet(_RX_IDLE_STYLE)
        self._freq_label.setText("")
        self._signal_bar.setValue(0)
        self._set_placeholder()


# ---------------------------------------------------------------------------
# Keypad
# ---------------------------------------------------------------------------


class _KeyButton(QPushButton):
    """Push button that reports its key code plus a press mode.

    A short click reports mode ``"P"``; holding past
    :data:`_LONG_PRESS_MS` reports ``"L"`` (long press), matching the
    physical front panel's short/long behavior.
    """

    keyActivated = Signal(str, str)  # (code, press_mode)

    def __init__(self, code: str, label: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(label, parent)
        self._code = code
        self._timer = QElapsedTimer()
        self.setToolTip(f"KEY,{code}  (hold for long press)")
        self.pressed.connect(self._timer.restart)
        self.released.connect(self._on_released)

    def _on_released(self) -> None:
        mode = "L" if self._timer.elapsed() >= _LONG_PRESS_MS else "P"
        self.keyActivated.emit(self._code, mode)


# Faceplate layout: (row, col, rowspan, colspan, code). Mirrors the
# SDS100 front panel - rotary row, number pad, and the function column
# on the right. The System/Dept/Channel soft keys (A/B/C) live in the
# separate SoftKeyBar directly beneath the screen.
_KEYPAD_LAYOUT: List[Tuple[int, int, int, int, str]] = [
    # Rotary row
    (1, 0, 1, 1, "<"), (1, 1, 1, 1, "^"), (1, 2, 1, 1, ">"),
    # Number pad
    (2, 0, 1, 1, "1"), (2, 1, 1, 1, "2"), (2, 2, 1, 1, "3"),
    (3, 0, 1, 1, "4"), (3, 1, 1, 1, "5"), (3, 2, 1, 1, "6"),
    (4, 0, 1, 1, "7"), (4, 1, 1, 1, "8"), (4, 2, 1, 1, "9"),
    (5, 0, 1, 1, "."), (5, 1, 1, 1, "0"), (5, 2, 1, 1, "E"),
    # Function column (right side)
    (2, 3, 1, 1, "M"), (3, 3, 1, 1, "L"),
    (4, 3, 1, 1, "Y"), (5, 3, 1, 1, "V"),
    # Extra row (less-common keys)
    (6, 0, 1, 1, "Z"), (6, 1, 1, 1, "T"),
    (6, 2, 1, 1, "R"), (6, 3, 1, 1, "Q"),
]


class KeypadWidget(QGroupBox):
    """Full SDS100 keypad as clickable buttons.

    Bind a driver with :meth:`set_driver`; the buttons grey out when no
    driver is present. The Func toggle prefixes the next key with a
    ``KEY,F`` press, replicating the device's FUNC+key combinations.
    """

    statusMessage = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__("Keypad", parent)
        self._driver: Optional[SerialMainDriver] = None
        self._workers: list = []
        self._buttons: List[_KeyButton] = []
        self._build_ui()
        self.set_driver(None)

    # -- build ----------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 12, 8, 8)
        outer.setSpacing(8)

        self._func_btn = QPushButton("FUNC")
        self._func_btn.setCheckable(True)
        self._func_btn.setToolTip(
            "When active, the next key is sent as a Func combination "
            "(KEY,F then the key)."
        )
        self._func_btn.setStyleSheet(
            "QPushButton:checked { background:#f2c200; color:#101218;"
            " font-weight:bold; }"
        )
        top = QHBoxLayout()
        top.addWidget(self._func_btn)
        top.addStretch(1)
        outer.addLayout(top)

        grid = QGridLayout()
        grid.setSpacing(5)
        for row, col, rowspan, colspan, code in _KEYPAD_LAYOUT:
            btn = _KeyButton(code, KEYPAD_KEYS.get(code, code))
            btn.setMinimumWidth(56)
            btn.setMinimumHeight(34)
            btn.keyActivated.connect(self._on_key)
            grid.addWidget(btn, row, col, rowspan, colspan)
            self._buttons.append(btn)
        for c in range(4):
            grid.setColumnStretch(c, 1)
        outer.addLayout(grid)

        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

    # -- public API -----------------------------------------------------

    def set_driver(self, driver: Optional[SerialMainDriver]) -> None:
        self._driver = driver
        enabled = driver is not None
        self._func_btn.setEnabled(enabled)
        if not enabled:
            self._func_btn.setChecked(False)
        for btn in self._buttons:
            btn.setEnabled(enabled)

    # -- internals ------------------------------------------------------

    def _on_key(self, code: str, mode: str) -> None:
        self.dispatch_key(code, mode)

    def dispatch_key(self, code: str, mode: str) -> None:
        """Send ``code`` with the current Func modifier applied.

        Shared entry point for both the keypad's own buttons and the
        external :class:`SoftKeyBar`, so Func combinations and worker
        bookkeeping behave identically wherever a key originates.
        """
        if self._driver is None:
            return
        use_func = self._func_btn.isChecked() and code != "F"
        codes: List[Tuple[str, str]] = []
        if use_func:
            codes.append(("F", "P"))
        codes.append((code, mode))

        worker = _SerialCallWorker(self._send_sequence, codes)
        label = KEYPAD_KEYS.get(code, code)
        prefix = "Func + " if use_func else ""
        suffix = " (long)" if mode == "L" else ""
        worker.finished_with_result.connect(
            lambda result, err, lbl=f"{prefix}{label}{suffix}": self._on_sent(lbl, err)
        )
        self._track_worker(worker)
        worker.start()

        if use_func:
            self._func_btn.setChecked(False)

    def _send_sequence(self, codes: List[Tuple[str, str]]) -> bool:
        ok = True
        for code, mode in codes:
            ok = self._driver.send_key(code, mode) and ok
        return ok

    def _on_sent(self, label: str, err: str) -> None:
        if err:
            self.statusMessage.emit(f"Key {label} failed: {err}")
        else:
            self.statusMessage.emit(f"Key {label} sent.")

    def _track_worker(self, worker) -> None:
        self._workers.append(worker)

        def _cleanup():
            try:
                self._workers.remove(worker)
            except ValueError:
                pass

        worker.finished.connect(_cleanup)


# ---------------------------------------------------------------------------
# Soft keys (under the screen)
# ---------------------------------------------------------------------------


# The three context soft keys, in physical left-to-right order.
_SOFT_KEYS: List[Tuple[str, str]] = [
    ("A", "System"),
    ("B", "Dept"),
    ("C", "Channel"),
]


class SoftKeyBar(QWidget):
    """The System / Dept / Channel context soft keys as clickable buttons.

    Rendered directly beneath the LCD to mirror the physical SDS100,
    where these keys sit under the screen and their captions are drawn on
    the display's bottom line. Presses route through the keypad's
    :meth:`KeypadWidget.dispatch_key`, so the Func modifier and worker
    bookkeeping are shared with the rest of the keypad.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._buttons: List[_KeyButton] = []
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        for code, caption in _SOFT_KEYS:
            btn = _KeyButton(code, caption)
            btn.setMinimumHeight(34)
            self._buttons.append(btn)
            row.addWidget(btn, 1)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self.set_active(False)

    def bind_keypad(self, keypad: "KeypadWidget") -> None:
        for btn in self._buttons:
            btn.keyActivated.connect(keypad.dispatch_key)

    def set_active(self, enabled: bool) -> None:
        for btn in self._buttons:
            btn.setEnabled(enabled)


# ---------------------------------------------------------------------------
# Composite faceplate
# ---------------------------------------------------------------------------


class VirtualScannerPanel(QWidget):
    """Two columns side by side, mirroring the physical SDS100.

    Left: the LCD monitor with the System/Dept/Channel soft keys directly
    beneath it (a blank line apart). Right: the Volume/Squelch knobs above
    the full keypad.
    """

    statusMessage = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Left column: LCD monitor on top, then a blank line, then the
        # context soft keys directly beneath the screen.
        left_col = QVBoxLayout()
        left_col.setContentsMargins(0, 0, 0, 0)
        left_col.setSpacing(8)

        self._lcd = LcdScreenWidget()
        left_col.addWidget(self._lcd, 1)

        left_col.addSpacing(12)  # blank line, like the physical faceplate

        self._softkeys = SoftKeyBar()
        left_col.addWidget(self._softkeys)

        layout.addLayout(left_col, 1)

        # Right column: audio knobs above the full keypad, top-aligned so
        # the stack stays compact.
        right_col = QVBoxLayout()
        right_col.setContentsMargins(0, 0, 0, 0)
        right_col.setSpacing(8)

        self._knobs = ScannerControlWidget()
        self._knobs.statusMessage.connect(self.statusMessage)
        right_col.addWidget(self._knobs)

        self._keypad = KeypadWidget()
        self._keypad.statusMessage.connect(self.statusMessage)
        right_col.addWidget(self._keypad)
        right_col.addStretch(1)

        self._softkeys.bind_keypad(self._keypad)

        layout.addLayout(right_col, 0)

        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)

    # -- public API -----------------------------------------------------

    def set_driver(self, driver: Optional[SerialMainDriver]) -> None:
        self._knobs.set_driver(driver)
        self._keypad.set_driver(driver)
        self._softkeys.set_active(driver is not None)
        if driver is None:
            self._lcd.clear()

    def update_screen(self, snap: ScreenSnapshot) -> None:
        self._lcd.update_screen(snap)

    def update_gsi(self, snap: GsiSnapshot) -> None:
        self._lcd.update_gsi(snap)
