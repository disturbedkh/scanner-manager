"""Scanner-control widget for the Live dock.

Exposes user-initiated, validated control commands against a
:class:`scanner_drivers.serial_main.SerialMainDriver`:

- Volume slider (0-15)  -> ``VOL,n``
- Squelch slider (0-15) -> ``SQL,n``
- Hold / Resume button  -> ``KEY,H,P``
- Avoid current button  -> ``KEY,.,P``
- Previous / Next       -> ``KEY,< / >,P``
- Replay                -> ``KEY,^,P``

All sends happen on a short-lived QThread so the UI never blocks on
serial I/O. The widget only allows what the driver's
:data:`SAFE_KEY_NAMES` whitelist permits, so even if we add more
buttons later the scanner-state mutation surface stays bounded.
"""

from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
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
    SAFE_CONTROL_KEYS,
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
    """Volume / Squelch sliders + navigation buttons.

    The widget is disabled until a driver is bound via
    :meth:`set_driver`. When the Live dock disconnects, call
    ``set_driver(None)`` to grey out the controls.
    """

    statusMessage = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__("Scanner control", parent)
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
        for w in (
            self._vol_slider, self._sql_slider,
            self._hold_btn, self._scan_btn, self._avoid_btn,
            self._prev_btn, self._next_btn, self._replay_btn,
            self._read_state_btn,
        ):
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

        # ---- Volume slider row ----
        vol_row = QHBoxLayout()
        vol_label = QLabel("Volume")
        vol_label.setMinimumWidth(60)
        vol_row.addWidget(vol_label)
        self._vol_slider = QSlider(Qt.Horizontal)
        self._vol_slider.setRange(*VOLUME_RANGE)
        self._vol_slider.setSingleStep(1)
        self._vol_slider.setPageStep(1)
        self._vol_slider.setTickPosition(QSlider.TicksBelow)
        self._vol_slider.setTickInterval(1)
        self._vol_slider.sliderReleased.connect(self._on_vol_committed)
        vol_row.addWidget(self._vol_slider, 1)
        self._vol_value = QLabel("--")
        self._vol_value.setMinimumWidth(28)
        self._vol_value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        vol_row.addWidget(self._vol_value)
        layout.addLayout(vol_row)

        # ---- Squelch slider row ----
        sql_row = QHBoxLayout()
        sql_label = QLabel("Squelch")
        sql_label.setMinimumWidth(60)
        sql_row.addWidget(sql_label)
        self._sql_slider = QSlider(Qt.Horizontal)
        self._sql_slider.setRange(*SQUELCH_RANGE)
        self._sql_slider.setSingleStep(1)
        self._sql_slider.setPageStep(1)
        self._sql_slider.setTickPosition(QSlider.TicksBelow)
        self._sql_slider.setTickInterval(1)
        self._sql_slider.sliderReleased.connect(self._on_sql_committed)
        sql_row.addWidget(self._sql_slider, 1)
        self._sql_value = QLabel("--")
        self._sql_value.setMinimumWidth(28)
        self._sql_value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        sql_row.addWidget(self._sql_value)
        layout.addLayout(sql_row)

        # ---- Separator ----
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        layout.addWidget(sep)

        # ---- Navigation buttons grid ----
        nav = QGridLayout()
        nav.setSpacing(4)

        # Map labels -> KEY codes via SAFE_CONTROL_KEYS so the
        # whitelist is the single source of truth.
        self._hold_btn = self._make_key_button("Hold / Resume")
        self._scan_btn = self._make_key_button("Scan")
        self._avoid_btn = self._make_key_button("Avoid")
        self._prev_btn = self._make_key_button("Previous")
        self._next_btn = self._make_key_button("Next")
        self._replay_btn = self._make_key_button("Replay")

        nav.addWidget(self._hold_btn, 0, 0)
        nav.addWidget(self._scan_btn, 0, 1)
        nav.addWidget(self._avoid_btn, 0, 2)
        nav.addWidget(self._prev_btn, 1, 0)
        nav.addWidget(self._next_btn, 1, 1)
        nav.addWidget(self._replay_btn, 1, 2)

        for col in range(3):
            nav.setColumnStretch(col, 1)
        layout.addLayout(nav)

        # ---- Re-read button ----
        bottom_row = QHBoxLayout()
        bottom_row.addStretch(1)
        self._read_state_btn = QPushButton("Re-read VOL / SQL")
        self._read_state_btn.clicked.connect(self.read_current_state)
        bottom_row.addWidget(self._read_state_btn)
        layout.addLayout(bottom_row)

        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

    def _make_key_button(self, label: str) -> QPushButton:
        btn = QPushButton(label)
        btn.clicked.connect(lambda _checked=False, lbl=label: self._on_key_clicked(lbl))
        return btn

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

    def _on_key_clicked(self, label: str) -> None:
        if self._driver is None:
            return
        try:
            key, mode = SAFE_CONTROL_KEYS[label]
        except KeyError:
            self.statusMessage.emit(f"Unknown key {label!r}")
            return
        worker = _SerialCallWorker(self._driver.send_key, key, mode)
        worker.finished_with_result.connect(
            lambda result, err: self._on_set_done(f"KEY {label}", None, result, err)
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
        if err or result is None:
            self._vol_value.setText("?")
            return
        try:
            level = int(result)
        except (TypeError, ValueError):
            return
        # Block signals so setting the slider value doesn't fire
        # sliderReleased -> set_volume round-trip.
        self._vol_slider.blockSignals(True)
        self._vol_slider.setValue(level)
        self._vol_slider.blockSignals(False)
        self._vol_value.setText(str(level))

    def _on_squelch_read(self, result, err: str) -> None:
        if err or result is None:
            self._sql_value.setText("?")
            return
        try:
            level = int(result)
        except (TypeError, ValueError):
            return
        self._sql_slider.blockSignals(True)
        self._sql_slider.setValue(level)
        self._sql_slider.blockSignals(False)
        self._sql_value.setText(str(level))

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
