"""Background polling controllers for the live serial dock.

Each controller wraps a :mod:`scanner_drivers` driver and drives it at a
fixed cadence, emitting Qt signals on every poll.

Polling cadence is still scheduled by a :class:`~PySide6.QtCore.QTimer`
on the GUI thread, but the *blocking* serial round-trip runs on a
short-lived :class:`SerialCallWorker` thread so the event loop never
stalls (pyserial reads can block up to the driver's read deadline,
~1.5 s). A per-command in-flight guard gives natural backpressure: a new
poll is skipped while the previous one for the same command is still
outstanding, so slow hardware can never pile up worker threads.

The driver's own lock serialises these worker-thread polls with the
GUI-thread VOL/SQL/KEY commands, so concurrent access is safe.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

from PySide6.QtCore import QObject, QThread, QTimer, Signal

from scanner_drivers.serial_main import (
    GlgEvent,
    GsiSnapshot,
    ScreenSnapshot,
    SerialMainDriver,
)
from scanner_drivers.serial_sub import IqFrame, SerialSubDriver, WaterfallFrame

logger = logging.getLogger(__name__)


class SerialCallWorker(QThread):
    """Run a single driver method on a worker thread.

    The driver's own lock makes concurrent calls safe; this just keeps
    blocking serial I/O off the GUI thread. Shared by the live pollers
    here and the scanner-control knobs in
    :mod:`gui.live.scanner_control`.
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
            logger.warning("Serial call failed: %s", exc)
            self.finished_with_result.emit(None, str(exc))


class _PollMixin:
    """Shared worker-spawn / backpressure logic for the pollers.

    Mixed into a ``QObject`` subclass that provides ``self._driver``, the
    ``self._stopped`` / ``self._inflight`` / ``self._workers`` state
    (initialised via :meth:`_init_poll_state`), a ``failed`` signal, and
    a ``stop()`` that halts its timers.
    """

    def _init_poll_state(self, driver) -> None:
        self._driver = driver
        self._stopped = True
        self._inflight: set[str] = set()
        self._workers: list[SerialCallWorker] = []

    @property
    def driver(self):
        """Read-only accessor used by the diagnostic-capture path so it
        can drop one-off raw queries down the wire (serialised with the
        pollers by the driver's own lock)."""
        return self._driver

    def _spawn(self, key: str, fn: Callable, on_result: Callable) -> None:
        # GUI thread; cheap. Skip if stopped or the previous poll for this
        # command is still outstanding, else run the blocking call on a
        # short-lived worker so the event loop keeps ticking.
        if self._stopped or key in self._inflight:
            return
        self._inflight.add(key)
        worker = SerialCallWorker(fn)
        worker.finished_with_result.connect(
            lambda result, err, k=key, cb=on_result: self._finish(k, cb, result, err)
        )
        self._track(worker)
        worker.start()

    def _finish(self, key: str, on_result: Callable, result, err: str) -> None:
        self._inflight.discard(key)
        if self._stopped:
            return
        if err:
            logger.warning("%s poll failed: %s", key, err)
            self.stop()
            self.failed.emit(f"{key}: {err}")
            return
        on_result(result)

    def _track(self, worker: SerialCallWorker) -> None:
        self._workers.append(worker)
        worker.finished.connect(lambda: self._forget(worker))

    def _forget(self, worker: SerialCallWorker) -> None:
        try:
            self._workers.remove(worker)
        except ValueError:
            pass

    def _await_workers(self, timeout_ms: int = 2000) -> None:
        # Let in-flight polls finish before the driver is closed so a
        # worker never reads a closed handle.
        for worker in list(self._workers):
            worker.wait(timeout_ms)

    def close(self) -> None:
        self.stop()
        self._await_workers()
        try:
            self._driver.close()
        except Exception:
            pass


class MainPollerController(_PollMixin, QObject):
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
        self._init_poll_state(driver)

        self._gsi_timer = QTimer(self)
        self._gsi_timer.setInterval(gsi_interval_ms)
        self._gsi_timer.timeout.connect(self._tick_gsi)

        self._glg_timer = QTimer(self)
        self._glg_timer.setInterval(glg_interval_ms)
        self._glg_timer.timeout.connect(self._tick_glg)

        self._sts_timer = QTimer(self)
        self._sts_timer.setInterval(sts_interval_ms)
        self._sts_timer.timeout.connect(self._tick_sts)

    def start(self) -> None:
        self._stopped = False
        self._gsi_timer.start()
        self._glg_timer.start()
        self._sts_timer.start()

    def stop(self) -> None:
        self._stopped = True
        self._gsi_timer.stop()
        self._glg_timer.stop()
        self._sts_timer.stop()

    def _tick_gsi(self) -> None:
        self._spawn("GSI", self._driver.poll_gsi, self.gsiUpdated.emit)

    def _tick_glg(self) -> None:
        self._spawn("GLG", self._driver.poll_glg, self.glgUpdated.emit)

    def _tick_sts(self) -> None:
        self._spawn("STS", self._driver.poll_status, self.stsUpdated.emit)


class SubPollerController(_PollMixin, QObject):
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
        self._init_poll_state(driver)
        self._mode = mode if mode in ("m", "d", "v") else "d"

        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._tick)

    @property
    def mode(self) -> str:
        return self._mode

    def set_mode(self, mode: str) -> None:
        if mode in ("m", "d", "v"):
            self._mode = mode

    def start(self) -> None:
        self._stopped = False
        self._timer.start()

    def stop(self) -> None:
        self._stopped = True
        self._timer.stop()

    def _tick(self) -> None:
        # Capture the on_result target for the current mode so a mid-flight
        # mode switch still routes the fetched frame to the right widget.
        if self._mode == "m":
            self._spawn("FFT", self._driver.fetch_waterfall_frame,
                        self.waterfallUpdated.emit)
        elif self._mode == "v":
            self._spawn("FFT", self._driver.fetch_wide_iq, self.iqUpdated.emit)
        else:
            self._spawn("FFT", self._driver.fetch_iq_pairs, self.iqUpdated.emit)
