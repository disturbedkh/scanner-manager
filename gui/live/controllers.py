"""Background polling controllers for the live serial dock.

Each controller wraps a :mod:`scanner_drivers` driver and a
:class:`PySide6.QtCore.QTimer`, emitting Qt signals on every poll.

Why timers instead of QThreads? The drivers' I/O is millisecond-scale
(USB CDC) and pyserial doesn't release the GIL during reads. A
``QTimer`` on the main thread keeps things simple, the GUI never
blocks, and the operator can easily stop polling by tearing down the
controller.
"""

from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import QObject, QTimer, Signal

from scanner_drivers.serial_main import (
    GlgEvent,
    GsiSnapshot,
    ScreenSnapshot,
    SerialMainDriver,
)
from scanner_drivers.serial_sub import IqFrame, SerialSubDriver, WaterfallFrame

logger = logging.getLogger(__name__)


class MainPollerController(QObject):
    """Polls GSI + GLG + STS on the MAIN port at fixed cadences."""

    gsiUpdated = Signal(GsiSnapshot)
    glgUpdated = Signal(GlgEvent)
    stsUpdated = Signal(ScreenSnapshot)
    failed = Signal(str)

    def __init__(
        self,
        driver: SerialMainDriver,
        gsi_interval_ms: int = 200,   # 5 Hz
        glg_interval_ms: int = 250,   # 4 Hz
        sts_interval_ms: int = 333,   # 3 Hz - screen mirror cadence
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._driver = driver

        self._gsi_timer = QTimer(self)
        self._gsi_timer.setInterval(gsi_interval_ms)
        self._gsi_timer.timeout.connect(self._poll_gsi)

        self._glg_timer = QTimer(self)
        self._glg_timer.setInterval(glg_interval_ms)
        self._glg_timer.timeout.connect(self._poll_glg)

        self._sts_timer = QTimer(self)
        self._sts_timer.setInterval(sts_interval_ms)
        self._sts_timer.timeout.connect(self._poll_sts)

    @property
    def driver(self) -> SerialMainDriver:
        """Public read-only accessor used by the diagnostic-capture
        path so it can drop one-off raw queries down the wire without
        rebuilding the polling state."""
        return self._driver

    def start(self) -> None:
        self._gsi_timer.start()
        self._glg_timer.start()
        self._sts_timer.start()

    def stop(self) -> None:
        self._gsi_timer.stop()
        self._glg_timer.stop()
        self._sts_timer.stop()

    def close(self) -> None:
        self.stop()
        try:
            self._driver.close()
        except Exception:
            pass

    def _poll_gsi(self) -> None:
        try:
            snap = self._driver.poll_gsi()
        except Exception as exc:
            logger.exception("GSI poll failed")
            self.failed.emit(f"GSI: {exc}")
            self.stop()
            return
        self.gsiUpdated.emit(snap)

    def _poll_glg(self) -> None:
        try:
            evt = self._driver.poll_glg()
        except Exception as exc:
            logger.exception("GLG poll failed")
            self.failed.emit(f"GLG: {exc}")
            self.stop()
            return
        self.glgUpdated.emit(evt)

    def _poll_sts(self) -> None:
        try:
            snap = self._driver.poll_status()
        except Exception as exc:
            logger.exception("STS poll failed")
            self.failed.emit(f"STS: {exc}")
            self.stop()
            return
        self.stsUpdated.emit(snap)


class SubPollerController(QObject):
    """Polls the SUB port for spectrum frames.

    Two modes:

    - ``mode="m"``  - the historical `m` command (signed time-domain
      samples; we run rFFT in :class:`gui.live.widgets.WaterfallWidget`).
    - ``mode="d"``  - narrow I/Q pairs from `d`, fed to
      :class:`gui.live.widgets.IqWaterfallWidget`. This is the "SDR
      view" that mirrors the radio's built-in spectrum screen.
    - ``mode="v"``  - wide I/Q pairs from `v` (~960 kHz BW). Same
      consumer widget; the widget rescales its sample-rate hint.

    The mode is chosen at construction so callers can swap in/out
    without restarting the timer.
    """

    waterfallUpdated = Signal(WaterfallFrame)
    iqUpdated = Signal(IqFrame)
    failed = Signal(str)

    def __init__(
        self,
        driver: SerialSubDriver,
        interval_ms: int = 100,    # 10 Hz; SUB's `m` returns ~1k samples
        mode: str = "d",
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._driver = driver
        self._mode = mode if mode in ("m", "d", "v") else "d"

        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._poll)

    @property
    def driver(self) -> SerialSubDriver:
        """Read-only accessor for the diagnostic-capture path."""
        return self._driver

    @property
    def mode(self) -> str:
        return self._mode

    def set_mode(self, mode: str) -> None:
        if mode in ("m", "d", "v"):
            self._mode = mode

    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def close(self) -> None:
        self.stop()
        try:
            self._driver.close()
        except Exception:
            pass

    def _poll(self) -> None:
        try:
            if self._mode == "m":
                frame = self._driver.fetch_waterfall_frame()
                self.waterfallUpdated.emit(frame)
            elif self._mode == "d":
                iq = self._driver.fetch_iq_pairs()
                self.iqUpdated.emit(iq)
            elif self._mode == "v":
                iq = self._driver.fetch_wide_iq()
                self.iqUpdated.emit(iq)
        except Exception as exc:
            logger.exception("SUB poll failed (mode=%s)", self._mode)
            self.failed.emit(f"FFT: {exc}")
            self.stop()
