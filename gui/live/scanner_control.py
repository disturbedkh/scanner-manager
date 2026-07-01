"""Volume / Squelch control widget for the Live dock.

Exposes the two user-initiated, validated knob commands against a
:class:`scanner_drivers.serial_main.SerialMainDriver`:

- Volume slider (0-15)  -> ``VOL,n``
- Squelch slider (0-15) -> ``SQL,n``

Navigation and every other front-panel button now live on the full
:class:`gui.live.virtual_scanner.KeypadWidget`; this widget is just the
two analog knobs that don't map cleanly onto momentary key presses.

All sends happen on a short-lived QThread (:class:`_SerialCallWorker`)
so the UI never blocks on serial I/O. The driver's internal lock makes
this safe alongside the polling loop.
"""

from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from scanner_drivers.serial_main import (
    SQUELCH_RANGE,
    VOLUME_RANGE,
    SerialMainDriver,
)

logger = logging.getLogger(__name__)


class _SerialCallWorker(QThread):
    """Run a single driver method on a worker thread.

    The driver's own lock makes concurrent calls safe; we just want
    to keep blocking serial I/O off the GUI thread.
    """

    finished_with_result = Signal(object, str)  # (result, error_message)

    def __init__(self, fn, *args, **kwargs) -> None:
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs

    def run(self) -> None:
        try:
            result = self._fn(*self._args, **self._kwargs)
            self.finished_with_result.emit(result, "")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Scanner control call failed: %s", exc)
            self.finished_with_result.emit(None, str(exc))


class ScannerControlWidget(QGroupBox):
    """Volume / Squelch sliders bound to a live MAIN driver.

    The widget is disabled until a driver is bound via
    :meth:`set_driver`. When the Live dock disconnects, call
    ``set_driver(None)`` to grey out the controls.
    """

    statusMessage = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__("Volume / Squelch", parent)
        self._driver: Optional[SerialMainDriver] = None
        self._workers: list = []  # keep refs so QThreads aren't gc'd mid-run
        self._build_ui()
        self.set_driver(None)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_driver(self, driver: Optional[SerialMainDriver]) -> None:
        self._driver = driver
        enabled = driver is not None
        for w in (self._vol_slider, self._sql_slider, self._read_state_btn):
            w.setEnabled(enabled)
        if enabled:
            self.read_current_state()
        else:
            self._vol_value.setText("--")
            self._sql_value.setText("--")

    def read_current_state(self) -> None:
        """Re-query the scanner for current VOL / SQL and update the
        sliders. Safe to call any time the driver is bound."""
        if self._driver is None:
            return
        worker = _SerialCallWorker(self._driver.query_volume)
        worker.finished_with_result.connect(self._on_volume_read)
        self._track_worker(worker)
        worker.start()

        sql_worker = _SerialCallWorker(self._driver.query_squelch)
        sql_worker.finished_with_result.connect(self._on_squelch_read)
        self._track_worker(sql_worker)
        sql_worker.start()

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 12, 8, 8)
        layout.setSpacing(8)

        layout.addLayout(
            self._build_slider_row("Volume", VOLUME_RANGE, "vol")
        )
        layout.addLayout(
            self._build_slider_row("Squelch", SQUELCH_RANGE, "sql")
        )

        bottom_row = QHBoxLayout()
        bottom_row.addStretch(1)
        self._read_state_btn = QPushButton("Re-read VOL / SQL")
        self._read_state_btn.clicked.connect(self.read_current_state)
        bottom_row.addWidget(self._read_state_btn)
        layout.addLayout(bottom_row)

        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

    def _build_slider_row(self, label: str, value_range, prefix: str):
        row = QHBoxLayout()
        name = QLabel(label)
        name.setMinimumWidth(60)
        row.addWidget(name)

        slider = QSlider(Qt.Horizontal)
        slider.setRange(*value_range)
        slider.setSingleStep(1)
        slider.setPageStep(1)
        slider.setTickPosition(QSlider.TicksBelow)
        slider.setTickInterval(1)
        row.addWidget(slider, 1)

        value = QLabel("--")
        value.setMinimumWidth(28)
        value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row.addWidget(value)

        if prefix == "vol":
            self._vol_slider = slider
            self._vol_value = value
            slider.sliderReleased.connect(self._on_vol_committed)
        else:
            self._sql_slider = slider
            self._sql_value = value
            slider.sliderReleased.connect(self._on_sql_committed)
        return row

    # ------------------------------------------------------------------
    # Slot handlers
    # ------------------------------------------------------------------

    def _on_vol_committed(self) -> None:
        if self._driver is None:
            return
        level = int(self._vol_slider.value())
        self._vol_value.setText(str(level))
        worker = _SerialCallWorker(self._driver.set_volume, level)
        worker.finished_with_result.connect(
            lambda result, err: self._on_set_done("VOL", level, result, err)
        )
        self._track_worker(worker)
        worker.start()

    def _on_sql_committed(self) -> None:
        if self._driver is None:
            return
        level = int(self._sql_slider.value())
        self._sql_value.setText(str(level))
        worker = _SerialCallWorker(self._driver.set_squelch, level)
        worker.finished_with_result.connect(
            lambda result, err: self._on_set_done("SQL", level, result, err)
        )
        self._track_worker(worker)
        worker.start()

    def _on_set_done(self, op: str, value, result, err: str) -> None:
        if err:
            self.statusMessage.emit(f"{op} failed: {err}")
        elif value is None:
            self.statusMessage.emit(f"{op} sent.")
        else:
            self.statusMessage.emit(f"{op} = {value}")

    def _on_volume_read(self, result, err: str) -> None:
        self._apply_read(self._vol_slider, self._vol_value, result, err)

    def _on_squelch_read(self, result, err: str) -> None:
        self._apply_read(self._sql_slider, self._sql_value, result, err)

    def _apply_read(self, slider, value_label, result, err: str) -> None:
        if err or result is None:
            value_label.setText("?")
            return
        try:
            level = int(result)
        except (TypeError, ValueError):
            return
        # Block signals so setting the value doesn't fire sliderReleased
        # -> set_* round-trip.
        slider.blockSignals(True)
        slider.setValue(level)
        slider.blockSignals(False)
        value_label.setText(str(level))

    # ------------------------------------------------------------------
    # Worker bookkeeping
    # ------------------------------------------------------------------

    def _track_worker(self, worker: QThread) -> None:
        self._workers.append(worker)

        def _cleanup():
            try:
                self._workers.remove(worker)
            except ValueError:
                pass

        worker.finished.connect(_cleanup)
