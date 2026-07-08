"""Per-feature widgets for the live serial-mode dock.

- :class:`GsiMirrorWidget` - table of the latest GSI snapshot fields.
- :class:`GlgFeedWidget` - rolling list of recent GLG events.
- :class:`MetersWidget` - RSSI / signal-strength bar meters.
- :class:`WaterfallWidget` - rolling FFT magnitude image (pyqtgraph).
"""

from __future__ import annotations

import collections
import logging
import time
from typing import Any, Deque, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from scanner_drivers.serial_main import GlgEvent, GsiSnapshot
from scanner_drivers.serial_sub import IqFrame, WaterfallFrame

logger = logging.getLogger(__name__)

try:
    import numpy as np
    import pyqtgraph as pg
    HAS_PYQTGRAPH = True
except Exception:  # pragma: no cover - optional dep
    HAS_PYQTGRAPH = False


# Recomputing two full-image percentiles on every waterfall frame is the
# dominant per-frame cost. Display levels drift slowly, so recompute only
# every few frames and on a strided subsample of the image.
_LEVEL_REFRESH_FRAMES = 8
_LEVEL_SUBSAMPLE = 4


class _LevelTracker:
    """Caches robust percentile display levels for a rolling image."""

    def __init__(
        self, lo_pct: float, hi_pct: float, default: tuple[float, float]
    ) -> None:
        self._lo_pct = lo_pct
        self._hi_pct = hi_pct
        self._default = default
        self._levels = default
        self._counter = 0

    def reset(self) -> None:
        self._levels = self._default
        self._counter = 0

    def update(self, arr) -> tuple[float, float]:
        if self._counter % _LEVEL_REFRESH_FRAMES == 0:
            sample = arr.ravel()[::_LEVEL_SUBSAMPLE]
            try:
                lo = float(np.percentile(sample, self._lo_pct))
                hi = float(np.percentile(sample, self._hi_pct))
                if hi <= lo:
                    hi = lo + 1.0
                self._levels = (lo, hi)
            except Exception:
                self._levels = self._default
        self._counter += 1
        return self._levels


def _trim_iq_arrays(frame: IqFrame, n: int):
    i = np.asarray(frame.i_samples[:n], dtype=np.float32)
    q = np.asarray(frame.q_samples[:n], dtype=np.float32)
    nz = np.flatnonzero(np.abs(i) + np.abs(q))
    if nz.size:
        cut = nz[-1] + 1
        i, q = i[:cut], q[:cut]
    return i, q


# int16 full-scale magnitude. The SUB port returns signed 16-bit
# samples, so a full-scale tone has amplitude 2**15.
_INT16_FULL_SCALE = 32768.0


def _log_spectrum_from_iq(i, q):
    i = i - float(i.mean())
    q = q - float(q.mean())
    complex_signal = i + 1j * q
    window = np.hanning(complex_signal.size)
    windowed = complex_signal * window
    spectrum = np.fft.fftshift(np.fft.fft(windowed))
    # Calibrate to dBFS: a full-scale complex tone through the same
    # window produces |X| == full_scale * sum(window) at its bin, so
    # dividing by that reference maps full scale to 0 dBFS and pushes
    # the noise floor well negative (instead of the old ~+200 counts).
    ref = _INT16_FULL_SCALE * float(window.sum()) + 1e-9
    return 20.0 * np.log10(np.abs(spectrum) / ref + 1e-12)


class GsiMirrorWidget(QGroupBox):
    """Read-only mirror of the most recent GSI snapshot."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__("Scanner state (GSI)", parent)
        form = QFormLayout(self)
        self._mode = QLabel("—")
        self._system = QLabel("—")
        self._site = QLabel("—")
        self._department = QLabel("—")
        self._tg = QLabel("—")
        self._tgid = QLabel("—")
        self._unit = QLabel("—")
        self._freq = QLabel("—")
        self._rx = QLabel("—")

        form.addRow("Mode:", self._mode)
        form.addRow("System:", self._system)
        form.addRow("Site:", self._site)
        form.addRow("Department:", self._department)
        form.addRow("Talkgroup:", self._tg)
        form.addRow("TGID:", self._tgid)
        form.addRow("Unit ID:", self._unit)
        form.addRow("Frequency:", self._freq)
        form.addRow("Receiving:", self._rx)

    def update_snapshot(self, snap: GsiSnapshot) -> None:
        self._mode.setText(snap.mode or "—")
        self._system.setText(snap.system_name or "—")
        self._site.setText(snap.site_name or "—")
        self._department.setText(snap.department_name or "—")
        self._tg.setText(snap.tg_name or "—")
        self._tgid.setText(snap.tgid or "—")
        self._unit.setText(snap.unit_id or "—")
        if snap.frequency_hz:
            self._freq.setText(f"{snap.frequency_hz / 1e6:.5f} MHz")
        else:
            self._freq.setText("—")
        self._rx.setText("YES" if snap.is_receiving else "no")
        self._rx.setStyleSheet(
            "color: #198754; font-weight: bold;" if snap.is_receiving else "color: #777;"
        )


class GlgFeedWidget(QGroupBox):
    """Append-only list of recent GLG receive events."""

    def __init__(self, max_rows: int = 200, parent: Optional[QWidget] = None) -> None:
        super().__init__("Recent calls (GLG)", parent)
        self._max_rows = max_rows
        layout = QVBoxLayout(self)
        self._list = QListWidget()
        self._list.setAlternatingRowColors(True)
        layout.addWidget(self._list)
        self._last_signature: Optional[str] = None

    def append_event(self, evt: GlgEvent) -> None:
        if not evt.is_receiving:
            return
        signature = (
            f"{evt.frq}|{evt.name1}|{evt.name2}|{evt.name3}|{evt.sys_tag}|{evt.chan_tag}"
        )
        if signature == self._last_signature:
            return
        self._last_signature = signature
        ts = time.strftime("%H:%M:%S")
        # The GLG schema names this column FRQ_TGID: it carries the
        # talkgroup ID on trunked systems and a real frequency on
        # conventional channels. Discriminate by magnitude - any value
        # below the lowest scanner band (~25 MHz) is a TGID, not RF.
        freq_label = evt.frq
        if evt.frq.isdigit():
            try:
                value = int(evt.frq)
                if value < 25_000_000:
                    freq_label = f"TGID {value}"
                else:
                    freq_label = f"{value / 1e6:.5f} MHz"
            except ValueError:
                freq_label = evt.frq
        bits = [ts, freq_label, evt.mod or "—"]
        if evt.name1 or evt.name2 or evt.name3:
            bits.append(f"{evt.name1} > {evt.name2} > {evt.name3}")
        text = "  |  ".join(b for b in bits if b)
        item = QListWidgetItem(text)
        self._list.insertItem(0, item)
        while self._list.count() > self._max_rows:
            self._list.takeItem(self._list.count() - 1)


class MetersWidget(QGroupBox):
    """RSSI dBm + signal-strength bar meters."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__("Signal", parent)
        layout = QFormLayout(self)
        self._rssi_label = QLabel("—")
        self._signal_bar = QProgressBar()
        self._signal_bar.setRange(0, 100)
        self._signal_bar.setValue(0)
        self._signal_bar.setTextVisible(True)
        self._signal_bar.setFormat("%v / 100")

        layout.addRow("RSSI (dBm):", self._rssi_label)
        layout.addRow("Signal:", self._signal_bar)

    def update_snapshot(self, snap: GsiSnapshot) -> None:
        self._rssi_label.setText(
            f"{snap.rssi_dbm} dBm" if snap.rssi_dbm is not None else "—"
        )
        if snap.signal_pct is not None:
            self._signal_bar.setValue(max(0, min(100, snap.signal_pct)))
        else:
            self._signal_bar.setValue(0)


def _build_turbo_colormap():
    """Approximation of Google's Turbo colormap.

    pyqtgraph 0.13 ships ``pg.colormap.get('CET-L8')`` and friends,
    but the matplotlib-style Turbo isn't always present on every
    install. Hand-rolling 9 stops gives us a stable, dependency-free
    colormap that looks good for SDR FFT data: deep blue noise floor,
    cyan / green mid-band, yellow / red signals.
    """
    if not HAS_PYQTGRAPH:
        return None
    try:
        cmap = pg.colormap.get("turbo", source="matplotlib")
        if cmap is not None:
            return cmap
    except Exception:
        pass
    stops = np.array([0.0, 0.13, 0.25, 0.38, 0.50, 0.63, 0.75, 0.88, 1.0])
    colors = np.array(
        [
            [48, 18, 59, 255],
            [70, 100, 245, 255],
            [50, 175, 240, 255],
            [55, 220, 175, 255],
            [180, 235, 75, 255],
            [255, 200, 35, 255],
            [255, 130, 25, 255],
            [220, 60, 20, 255],
            [122, 4, 3, 255],
        ],
        dtype=np.ubyte,
    )
    return pg.ColorMap(stops, colors)


class WaterfallWidget(QGroupBox):
    """Rolling FFT magnitude image rendered with pyqtgraph.

    Each new :class:`WaterfallFrame` becomes the next row in a
    rolling history (newest at the top). The data pipeline is:

    1. Pad / truncate every frame to a stable bin count so the
       image array is rectangular.
    2. Compute a log-magnitude (≈ dBFS) view so the noise floor
       sits in a narrow band and real signals pop above it.
    3. Lock the colour-mapping levels to the rolling
       ``(p10, p99.5)`` percentiles of the *whole* image so a
       single tall transient can't blow out the contrast.
    4. Apply a Turbo colormap so a deep-blue noise floor flips
       to yellow / red the instant a transmission lands.

    When pyqtgraph isn't installed we fall back to a status label.
    """

    def __init__(
        self,
        history_rows: int = 256,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__("FFT waterfall (SUB port)", parent)
        layout = QVBoxLayout(self)
        self._history_rows = history_rows
        self._frames: Deque = collections.deque(maxlen=history_rows)
        self._sample_count: Optional[int] = None
        self._levels = _LevelTracker(20.0, 99.0, (0.0, 90.0))
        self._range_set = False

        if not HAS_PYQTGRAPH:
            layout.addWidget(QLabel("Install pyqtgraph + numpy for the waterfall plot."))
            self._image_item = None
            self._plot = None
            self._colormap = None
            return

        self._plot = pg.PlotWidget()
        self._plot.setLabel("bottom", "FFT bin")
        self._plot.setLabel("left", "History (frame)")
        self._plot.invertY(True)
        # Dark background makes the Turbo colormap pop.
        self._plot.setBackground("#101218")
        self._plot.getPlotItem().getViewBox().setMouseEnabled(x=False, y=False)
        self._image_item = pg.ImageItem(axisOrder="row-major")
        self._plot.addItem(self._image_item)
        self._colormap = _build_turbo_colormap()
        if self._colormap is not None:
            try:
                self._image_item.setLookupTable(self._colormap.getLookupTable(0.0, 1.0, 256))
            except Exception:
                logger.exception("waterfall colormap apply failed; falling back to grayscale")
        layout.addWidget(self._plot)

    def add_frame(self, frame: WaterfallFrame) -> None:
        if not HAS_PYQTGRAPH or self._image_item is None:
            return
        if not frame.samples:
            return

        # The SUB-port `m` command actually returns SIGNED int16
        # *time-domain* samples (verified via dev_mcp capture; values
        # range -32k..+32k, including big negatives like -14965). The
        # decompile-derived "FFT magnitude" label was wrong. To turn
        # this into a useful waterfall we need to:
        #
        #   1. Drop the trailing zero-padded run that the firmware
        #      always appends.
        #   2. Compute the magnitude of the rFFT to get a real spectrum.
        #   3. Convert to dBFS for visual contrast.
        raw = np.asarray(frame.samples, dtype=np.float32)
        # Trim trailing zeros that the SDS pads the buffer with.
        nz = np.flatnonzero(raw)
        if nz.size:
            raw = raw[: nz[-1] + 1]
        if raw.size < 8:
            return

        # DC-block: the time-domain stream from the SDS DSP often has
        # a small DC bias that would otherwise dominate bin 0.
        raw = raw - float(raw.mean())

        # Real-input FFT: gives us len(raw)//2 + 1 magnitude bins.
        # Calibrate to dBFS: an rFFT of a full-scale real tone peaks at
        # ~full_scale * N / 2, so divide by that reference up front. The
        # rolling image then carries true dBFS magnitudes.
        ref = _INT16_FULL_SCALE * (raw.size / 2.0) + 1e-9
        spectrum = np.abs(np.fft.rfft(raw)) / ref

        # Lock the bin count to the first frame's spectrum width so the
        # rolling image stays rectangular.
        if self._sample_count is None:
            self._sample_count = spectrum.size
        n = self._sample_count
        if spectrum.size < n:
            spectrum = np.pad(spectrum, (0, n - spectrum.size))
        elif spectrum.size > n:
            spectrum = spectrum[:n]

        # Convert just this row to dBFS and store it, so log10 runs on one
        # new row per frame instead of the whole rolling history.
        log_row = 20.0 * np.log10(spectrum + 1e-12)
        self._frames.append(log_row)

        log_arr = np.asarray(self._frames, dtype=np.float32)

        # Robust percentile clipping: low edge at p20 keeps the noise
        # floor near "blue", high edge at p99 lets transient bursts
        # saturate the colormap without a single bin blowing it out.
        # Levels are cached and refreshed periodically (see _LevelTracker).
        lo, hi = self._levels.update(log_arr)

        self._image_item.setImage(log_arr, autoLevels=False, levels=(lo, hi))
        self._image_item.setRect(
            pg.QtCore.QRectF(0, 0, log_arr.shape[1], log_arr.shape[0])
        )
        if not self._range_set:
            self._plot.setXRange(0, log_arr.shape[1], padding=0)
            self._plot.setYRange(0, self._history_rows, padding=0)
            self._range_set = True

    def reset_history(self) -> None:
        """Drop all accumulated rows and re-lock the bin count.

        Call this when switching into this widget so a previous
        session's frame width / range doesn't bleed into the new one.
        """
        self._frames.clear()
        self._sample_count = None
        self._levels.reset()
        self._range_set = False


class IqWaterfallWidget(QGroupBox):
    """SDR-style waterfall driven by complex baseband I/Q samples.

    Mirrors what the SDS100/200 shows on its built-in spectrum screen:
    the X axis is **frequency** (centred on the tuned VC frequency),
    the Y axis is **time** (newest at top), and the colormap is
    Turbo. Live peak-hold trace is overlaid above the heatmap.

    Data source: the SUB port's ``d`` (narrow ~16 kHz BW) or ``v``
    (wide ~960 kHz BW) commands, parsed into :class:`IqFrame`.
    """

    def __init__(
        self,
        history_rows: int = 256,
        sample_rate_hz: float = 16_000.0,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__("FFT waterfall (I/Q SDR view)", parent)
        layout = QVBoxLayout(self)
        self._history_rows = history_rows
        self._sample_rate = float(sample_rate_hz)
        self._center_hz: Optional[float] = None
        self._frames: Deque = collections.deque(maxlen=history_rows)
        self._peak_hold: Optional[Any] = None
        self._peak_times: Optional[Any] = None
        self._max_hold_secs: Optional[float] = None
        self._fft_size: Optional[int] = None
        self._levels = _LevelTracker(20.0, 99.0, (-60.0, 0.0))
        self._range_set = False

        if not HAS_PYQTGRAPH:
            layout.addWidget(QLabel("Install pyqtgraph + numpy for the I/Q waterfall."))
            self._image_item = None
            self._spectrum_curve = None
            self._marker_spectrum = None
            self._marker_waterfall = None
            return

        # Top: instantaneous spectrum + peak hold (line plot)
        self._spectrum_plot = pg.PlotWidget()
        self._spectrum_plot.setBackground("#101218")
        self._spectrum_plot.setLabel("bottom", "Frequency (MHz)")
        self._spectrum_plot.setLabel("left", "dBFS")
        self._spectrum_plot.setMaximumHeight(160)
        self._spectrum_curve = self._spectrum_plot.plot(pen=pg.mkPen("#5cd6ff", width=1))
        self._peak_curve = self._spectrum_plot.plot(pen=pg.mkPen("#ffd34d", width=1, style=Qt.DashLine))
        # Center-frequency Marker (mirrors the native green Marker that
        # marks the tuned VC frequency). Hidden until a centre is known.
        self._marker_spectrum = pg.InfiniteLine(
            angle=90, movable=False, pen=pg.mkPen("#3ad53a", width=1)
        )
        self._marker_spectrum.setVisible(False)
        self._spectrum_plot.addItem(self._marker_spectrum)
        layout.addWidget(self._spectrum_plot)

        # Bottom: rolling waterfall (image plot)
        self._plot = pg.PlotWidget()
        self._plot.setBackground("#101218")
        self._plot.setLabel("bottom", "Frequency (MHz)")
        self._plot.setLabel("left", "History (frame)")
        self._plot.invertY(True)
        self._plot.getPlotItem().getViewBox().setMouseEnabled(x=False, y=False)
        self._image_item = pg.ImageItem(axisOrder="row-major")
        self._plot.addItem(self._image_item)
        self._marker_waterfall = pg.InfiniteLine(
            angle=90, movable=False, pen=pg.mkPen("#3ad53a", width=1)
        )
        self._marker_waterfall.setVisible(False)
        self._plot.addItem(self._marker_waterfall)
        self._colormap = _build_turbo_colormap()
        if self._colormap is not None:
            try:
                self._image_item.setLookupTable(
                    self._colormap.getLookupTable(0.0, 1.0, 256)
                )
            except Exception:
                logger.exception("I/Q waterfall colormap apply failed")
        layout.addWidget(self._plot, stretch=1)

    def set_center_frequency(self, hz: Optional[float]) -> None:
        """Set the tuned (centre) frequency in Hz. Call from GsiSnapshot
        or PWR responses so the X-axis labels make sense.
        """
        new_center = float(hz) if hz else None
        if new_center == self._center_hz:
            return
        self._center_hz = new_center
        self._range_set = False  # rebuild axis on next frame
        self._update_marker()

    def set_sample_rate(self, hz: float) -> None:
        """Switch the I/Q bandwidth hint (16 kHz narrow vs 960 kHz wide).

        A sample-rate change means a different spectrum source / span,
        so we drop all accumulated state - otherwise a stronger wide
        session's peak-hold trace would 'stick' when returning to the
        narrow source (the bins only ever rise under a running max).
        """
        self._sample_rate = float(hz)
        self.reset_history()

    def set_max_hold_time(self, secs: Optional[float]) -> None:
        """Set the peak-hold decay window (native 'Set Max Hold Time').

        ``None`` (or a non-positive value) means Infinite hold, matching
        the prior behaviour where peaks only ever rise.
        """
        self._max_hold_secs = float(secs) if secs and secs > 0 else None

    def reset_history(self) -> None:
        """Clear the rolling history, peak-hold, and locked bin count.

        Used on a spectrum-source switch so stale frames / peaks from
        the previous bandwidth don't bleed into the new view.
        """
        self._frames.clear()
        self._peak_hold = None
        self._peak_times = None
        self._fft_size = None
        self._levels.reset()
        self._range_set = False

    def _update_marker(self) -> None:
        if self._image_item is None or self._marker_spectrum is None:
            return
        if self._center_hz is not None:
            x = self._center_hz / 1e6
            self._marker_spectrum.setPos(x)
            self._marker_waterfall.setPos(x)
            self._marker_spectrum.setVisible(True)
            self._marker_waterfall.setVisible(True)
        else:
            self._marker_spectrum.setVisible(False)
            self._marker_waterfall.setVisible(False)

    def _update_peak_hold(self, log_spec) -> None:
        """Update the peak-hold trace with optional max-hold-time decay.

        Mirrors the native 'Set Max Hold Time' (3 s / 10 s / Infinite)
        option: each bin remembers when its current peak was set, and
        once that peak is older than ``_max_hold_secs`` it drops back to
        the live value. With Infinite hold this is just a running max.
        """
        now = time.monotonic()
        if (
            self._peak_hold is None
            or self._peak_times is None
            or self._peak_hold.shape != log_spec.shape
        ):
            self._peak_hold = log_spec.copy()
            self._peak_times = np.full(log_spec.shape, now, dtype=np.float64)
            return
        if self._max_hold_secs is not None:
            stale = (now - self._peak_times) > self._max_hold_secs
            self._peak_hold[stale] = log_spec[stale]
            self._peak_times[stale] = now
        rising = log_spec >= self._peak_hold
        self._peak_hold[rising] = log_spec[rising]
        self._peak_times[rising] = now

    def _frequency_axis_mhz(self):
        """Per-bin X-axis values in MHz, centred on the tuned VC freq
        when known, else baseband (centred on 0)."""
        if self._center_hz is not None:
            half_bw = self._sample_rate / 2.0
            return np.linspace(
                (self._center_hz - half_bw) / 1e6,
                (self._center_hz + half_bw) / 1e6,
                self._fft_size,
            )
        half = self._fft_size // 2
        xs = np.arange(-half, self._fft_size - half, dtype=np.float64)
        return xs * (self._sample_rate / self._fft_size) / 1e6

    def add_frame(self, frame: IqFrame) -> None:
        if not HAS_PYQTGRAPH or self._image_item is None:
            return
        n = frame.sample_count
        if n < 8:
            return

        i, q = _trim_iq_arrays(frame, n)
        if i.size < 8:
            return
        log_spec = _log_spectrum_from_iq(i, q)

        # Lock width across frames.
        if self._fft_size is None:
            self._fft_size = log_spec.size
        if log_spec.size < self._fft_size:
            log_spec = np.pad(log_spec, (0, self._fft_size - log_spec.size))
        elif log_spec.size > self._fft_size:
            log_spec = log_spec[: self._fft_size]

        self._frames.append(log_spec)
        history = np.asarray(self._frames, dtype=np.float32)

        self._update_peak_hold(log_spec)
        xs = self._frequency_axis_mhz()

        # Update line plots.
        self._spectrum_curve.setData(xs, log_spec)
        self._peak_curve.setData(xs, self._peak_hold)

        # Update waterfall image. Levels via robust percentiles, cached
        # and refreshed periodically (see _LevelTracker).
        lo, hi = self._levels.update(history)

        self._image_item.setImage(history, autoLevels=False, levels=(lo, hi))
        # Map the image's pixel coords to the same MHz axis as the line plot.
        x0 = float(xs[0])
        width_mhz = float(xs[-1] - xs[0])
        self._image_item.setRect(
            pg.QtCore.QRectF(x0, 0, width_mhz, history.shape[0])
        )
        if not self._range_set:
            self._plot.setXRange(x0, x0 + width_mhz, padding=0)
            self._plot.setYRange(0, self._history_rows, padding=0)
            self._spectrum_plot.setXRange(x0, x0 + width_mhz, padding=0)
            self._range_set = True
            self._update_marker()

    def reset_peak_hold(self) -> None:
        self._peak_hold = None
        self._peak_times = None
