"""Phase 3: live serial-mode dock smoke tests.

These tests validate the dock's structural wiring + signal pipes
without ever opening a real serial port. The driver layer is
covered by ``test_serial_main`` / ``test_serial_sub``.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.qt

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PySide6 = pytest.importorskip("PySide6")  # noqa: N816
pytest.importorskip("pytestqt")

from PySide6.QtCore import Qt  # noqa: E402

from scanner_drivers.serial_main import GlgEvent, GsiSnapshot  # noqa: E402
from scanner_drivers.serial_sub import WaterfallFrame  # noqa: E402
from scanner_drivers.usb_detect import (  # noqa: E402
    SDS_PID_MAIN,
    SDS_PID_SUB,
    UNIDEN_VID,
    DetectedPort,
)
from scanner_profiles import get_profile  # noqa: E402


@pytest.fixture
def auto_msgbox(monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)


def _fake_port(device, vid, pid, sn="ABC") -> DetectedPort:
    return DetectedPort(
        device=device,
        description=f"Uniden {pid:04x}",
        hwid=f"USB VID:PID={vid:04X}:{pid:04X}",
        vid=vid,
        pid=pid,
        serial_number=sn,
    )


class _MinimalFakePort:
    """Serial port stub for live-driver tests; I/O methods are intentional no-ops."""

    in_waiting = 0

    def write(self, _data: bytes) -> int:
        return len(_data)

    def flush(self) -> None:
        return None  # stub: no hardware buffer

    def reset_input_buffer(self) -> None:
        return None  # stub

    def close(self) -> None:
        return None  # stub

    def read(self, _n: int) -> bytes:
        return b""


class _PayloadFakePort(_MinimalFakePort):
    def __init__(self, payload: bytes) -> None:
        self._buf = payload + b"\r"
        self.in_waiting = len(self._buf)

    def read(self, n: int) -> bytes:
        chunk = self._buf[:n]
        self._buf = self._buf[n:]
        self.in_waiting = len(self._buf)
        return chunk


def _raise_gsi_boom() -> None:
    raise RuntimeError("gsi boom")


def _raise_iq_fail() -> None:
    raise RuntimeError("iq fail")


def test_live_dock_hides_when_profile_unsupported(qtbot) -> None:
    from gui.live.live_dock import LiveDock

    dock = LiveDock()
    qtbot.addWidget(dock)
    dock.set_active_profile(get_profile("uniden_bt885"))
    # BT885 has no serial mode; controls should be disabled.
    assert not dock._connect_btn.isEnabled()
    assert not dock._refresh_btn.isEnabled()


def test_live_dock_shows_for_sds(qtbot) -> None:
    from gui.live.live_dock import LiveDock

    dock = LiveDock()
    qtbot.addWidget(dock)

    # Pretend two Uniden ports exist
    fake_ports = [
        _fake_port("COM4", UNIDEN_VID, SDS_PID_MAIN),
        _fake_port("COM3", UNIDEN_VID, SDS_PID_SUB),
    ]
    with patch("gui.live.live_dock.enumerate_ports", return_value=fake_ports), patch(
        "gui.live.live_dock.find_ports_for_profile",
        return_value=__import__(
            "scanner_drivers.usb_detect", fromlist=["ScannerPorts"]
        ).ScannerPorts(main=fake_ports[0], sub=fake_ports[1]),
    ):
        dock.set_active_profile(get_profile("uniden_sds100"))

    assert dock._connect_btn.isEnabled()
    assert dock._refresh_btn.isEnabled()
    # Each combo should contain both detected ports
    main_choices = [
        dock._main_combo.itemData(i) for i in range(dock._main_combo.count())
    ]
    assert "COM4" in main_choices
    sub_choices = [
        dock._sub_combo.itemData(i) for i in range(dock._sub_combo.count())
    ]
    assert "COM3" in sub_choices


def test_live_dock_diagnostic_button_disabled_until_connected(qtbot) -> None:
    """Diagnostic capture requires live drivers - greyed out otherwise."""
    from gui.live.live_dock import LiveDock

    dock = LiveDock()
    qtbot.addWidget(dock)
    dock.set_active_profile(get_profile("uniden_sds100"))
    assert hasattr(dock, "_diag_btn")
    assert not dock._diag_btn.isEnabled()


def test_live_dock_emits_connection_state_changed(qtbot) -> None:
    from gui.live.live_dock import LiveDock

    dock = LiveDock()
    qtbot.addWidget(dock)
    received = []
    dock.connectionStateChanged.connect(received.append)

    with patch("gui.live.live_dock.enumerate_ports", return_value=[]), patch(
        "gui.live.live_dock.find_ports_for_profile",
        return_value=__import__(
            "scanner_drivers.usb_detect", fromlist=["ScannerPorts"]
        ).ScannerPorts(),
    ):
        dock.set_active_profile(get_profile("uniden_sds100"))

    assert "red" in received  # no ports visible -> red LED


def test_gsi_mirror_widget_renders_snapshot(qtbot) -> None:
    from gui.live.widgets import GsiMirrorWidget

    widget = GsiMirrorWidget()
    qtbot.addWidget(widget)
    snap = GsiSnapshot(
        mode="Scan",
        system_name="Miami-Dade P25",
        department_name="Fire Dispatch",
        tg_name="FD East",
        tgid="1234",
        unit_id="5556666",
        rssi_dbm=-72,
        signal_pct=55,
        is_receiving=True,
        frequency_hz=154_445_000,
    )
    widget.update_snapshot(snap)
    assert widget._system.text() == "Miami-Dade P25"
    assert widget._tg.text() == "FD East"
    assert "MHz" in widget._freq.text()
    assert widget._rx.text() == "YES"


def test_gsi_mirror_widget_empty_frequency_and_not_receiving(qtbot) -> None:
    from gui.live.widgets import GsiMirrorWidget

    widget = GsiMirrorWidget()
    qtbot.addWidget(widget)
    snap = GsiSnapshot(
        mode="Scan",
        site_name="Simulcast",
        is_receiving=False,
        frequency_hz=0,
    )
    widget.update_snapshot(snap)
    assert widget._site.text() == "Simulcast"
    assert widget._freq.text() == "—"
    assert widget._rx.text() == "no"


def test_glg_feed_keeps_non_numeric_frq_and_skips_idle(qtbot) -> None:
    from gui.live.widgets import GlgFeedWidget

    feed = GlgFeedWidget()
    qtbot.addWidget(feed)
    feed.append_event(
        GlgEvent(frq="not-a-number", mod="FM", name3="Test", is_receiving=True)
    )
    assert "not-a-number" in feed._list.item(0).text()
    feed.append_event(
        GlgEvent(frq="154445000", mod="FM", name3="Idle", is_receiving=False)
    )
    assert feed._list.count() == 1


def test_glg_feed_renders_tgid_when_value_is_below_rf_floor(qtbot) -> None:
    """FRQ_TGID < 25 MHz is a talkgroup ID, not RF. Display accordingly."""
    from gui.live.widgets import GlgFeedWidget

    feed = GlgFeedWidget()
    qtbot.addWidget(feed)
    feed.append_event(
        GlgEvent(
            frq="2057",
            mod="P25",
            name1="Simulcast",
            name2="Gainesville Police Department",
            name3="A1 Primary",
            is_receiving=True,
        )
    )
    assert feed._list.count() == 1
    text = feed._list.item(0).text()
    assert "TGID 2057" in text
    assert "MHz" not in text  # no fake megahertz!


def test_glg_feed_renders_real_frequency_for_conventional_channel(qtbot) -> None:
    from gui.live.widgets import GlgFeedWidget

    feed = GlgFeedWidget()
    qtbot.addWidget(feed)
    feed.append_event(
        GlgEvent(
            frq="154445000",
            mod="FM",
            name3="Local FD",
            is_receiving=True,
        )
    )
    text = feed._list.item(0).text()
    assert "154.44500 MHz" in text


def test_glg_feed_filters_idle_events(qtbot) -> None:
    from gui.live.widgets import GlgFeedWidget

    feed = GlgFeedWidget()
    qtbot.addWidget(feed)
    # Idle event - should not insert a row
    feed.append_event(GlgEvent(is_receiving=False))
    assert feed._list.count() == 0
    # Receiving - should add one
    feed.append_event(
        GlgEvent(
            frq="154445000",
            mod="FM",
            name3="FD East",
            is_receiving=True,
        )
    )
    assert feed._list.count() == 1
    # Same signature - should NOT duplicate
    feed.append_event(
        GlgEvent(
            frq="154445000",
            mod="FM",
            name3="FD East",
            is_receiving=True,
        )
    )
    assert feed._list.count() == 1


def test_meters_widget_handles_missing_values(qtbot) -> None:
    from gui.live.widgets import MetersWidget

    widget = MetersWidget()
    qtbot.addWidget(widget)
    widget.update_snapshot(GsiSnapshot())
    assert widget._rssi_label.text() == "—"
    assert widget._signal_bar.value() == 0


def test_waterfall_widget_accepts_frames_without_pyqtgraph_crash(qtbot) -> None:
    """Even if pyqtgraph is missing, calling add_frame() must not crash."""
    from gui.live.widgets import WaterfallWidget

    widget = WaterfallWidget()
    qtbot.addWidget(widget)
    widget.add_frame(WaterfallFrame(samples=[1, 2, 3, 4, 5]))
    widget.add_frame(WaterfallFrame(samples=[5, 4, 3, 2, 1]))


def test_waterfall_widget_applies_colormap_when_pyqtgraph_present(qtbot) -> None:
    """The waterfall must paint with the Turbo colormap (LUT set) and
    the FFT-of-time-domain pipeline must turn a synthetic carrier into
    a clearly elevated bin."""
    pytest.importorskip("pyqtgraph")
    pytest.importorskip("numpy")
    import math

    from gui.live.widgets import HAS_PYQTGRAPH, WaterfallWidget

    if not HAS_PYQTGRAPH:
        pytest.skip("pyqtgraph not available at runtime")
    widget = WaterfallWidget(history_rows=8)
    qtbot.addWidget(widget)
    assert widget._colormap is not None
    assert widget._image_item is not None

    # Synthesize a 256-sample sinusoid at bin ~32 of a 256-pt FFT.
    n = 256
    bin_target = 32
    samples = [
        int(15000 * math.sin(2 * math.pi * bin_target * i / n))
        for i in range(n)
    ]
    widget.add_frame(WaterfallFrame(samples=samples))
    widget.add_frame(WaterfallFrame(samples=samples))

    levels = widget._image_item.getLevels()
    assert levels is not None
    lo, hi = levels
    # Real signal vs noise floor: hi must be meaningfully above lo.
    assert hi > lo + 5.0

    # Lookup table must be a 256-entry RGBA palette (Turbo, not grayscale).
    lut = widget._image_item.lut
    assert lut is not None
    assert lut.shape[0] == 256

    # The bin count is now N//2 + 1 (rFFT), not N.
    assert widget._sample_count == n // 2 + 1


def test_gsi_mirror_widget_renders_real_sds_snapshot(qtbot) -> None:
    """End-to-end smoke from the real SDS schema -> the mirror UI."""
    from gui.live.widgets import GsiMirrorWidget
    from scanner_drivers.serial_main import SerialMainDriver

    payload = (
        b"<ScannerInfo Mode=\"Trunk Scan\">"
        b"<MonitorList Name=\"Home\"/>"
        b"<System Name=\"Gainesville Simulcast\" SystemType=\"P25 Trunk\"/>"
        b"<Department Name=\"Gainesville Police Department\"/>"
        b"<TGID Name=\"A1 Primary\" TGID=\"TGID:2057\"/>"
        b"<UnitID Uid=\"5556666\"/>"
        b"<SiteFrequency Freq=\"851012500\"/>"
        b"<Property VOL=\"7\" SQL=\"3\" Sig=\"5\" Mute=\"UnMute\" Rssi=\"-72\"/>"
        b"</ScannerInfo>"
    )
    driver = SerialMainDriver(_PayloadFakePort(payload))
    snap = driver.poll_gsi()
    widget = GsiMirrorWidget()
    qtbot.addWidget(widget)
    widget.update_snapshot(snap)
    assert widget._system.text() == "Gainesville Simulcast"
    assert widget._department.text() == "Gainesville Police Department"
    assert widget._tg.text() == "A1 Primary"
    assert widget._tgid.text() == "2057"
    assert widget._rx.text() == "YES"
    assert "MHz" in widget._freq.text()


def test_iq_waterfall_widget_uses_hz_axis_and_complex_fft(qtbot) -> None:
    """The new SDR-style waterfall must:

    1. Label the bottom axis with frequency (MHz), not bin index.
    2. Run a complex (windowed) FFT of I + jQ, not an rFFT of either
       channel alone - so a single-tone I/Q at +1 kHz lands in a
       distinct bin offset from DC.
    """
    pytest.importorskip("pyqtgraph")
    pytest.importorskip("numpy")
    import math

    from gui.live.widgets import HAS_PYQTGRAPH, IqWaterfallWidget
    from scanner_drivers.serial_sub import IqFrame

    if not HAS_PYQTGRAPH:
        pytest.skip("pyqtgraph not available at runtime")

    widget = IqWaterfallWidget(history_rows=4, sample_rate_hz=16_000.0)
    qtbot.addWidget(widget)
    widget.set_center_frequency(852_125_000.0)

    n = 256
    f0 = 1000.0
    fs = 16_000.0
    i = [int(15000 * math.cos(2 * math.pi * f0 * k / fs)) for k in range(n)]
    q = [int(15000 * math.sin(2 * math.pi * f0 * k / fs)) for k in range(n)]
    widget.add_frame(IqFrame(i_samples=i, q_samples=q, source="d"))
    widget.add_frame(IqFrame(i_samples=i, q_samples=q, source="d"))

    assert widget._fft_size == n
    bottom_label = widget._spectrum_plot.getAxis("bottom").labelText
    assert "Frequency" in bottom_label
    # Image levels must be set (levels=False, real-FFT-of-IQ pipeline
    # produces a real magnitude history).
    levels = widget._image_item.getLevels()
    assert levels is not None

    # The spectrum line plot's X-data is what the human reads against
    # the labelled MHz axis - assert it's centred on the tuned VC
    # frequency, NOT on bin index 0..N.
    xdata, _ = widget._spectrum_curve.getData()
    assert xdata is not None
    midpoint = float(xdata[xdata.size // 2])
    assert 851.0 < midpoint < 853.0, (
        f"X-axis midpoint {midpoint} should be near 852.125 MHz, "
        f"not centred at the bin-index origin"
    )
    # And the span should be ~16 kHz wide (0.016 MHz) at fs=16 kHz.
    span = float(xdata[-1] - xdata[0])
    assert 0.005 < span < 0.05, f"X-axis span {span} MHz looks wrong"


def test_iq_waterfall_widget_handles_missing_center_frequency(qtbot) -> None:
    """Before the first GSI snapshot lands the X axis should fall
    back to baseband Hz (centred at 0) instead of crashing.
    """
    pytest.importorskip("pyqtgraph")
    pytest.importorskip("numpy")

    from gui.live.widgets import HAS_PYQTGRAPH, IqWaterfallWidget
    from scanner_drivers.serial_sub import IqFrame

    if not HAS_PYQTGRAPH:
        pytest.skip("pyqtgraph not available at runtime")

    widget = IqWaterfallWidget(history_rows=2, sample_rate_hz=16_000.0)
    qtbot.addWidget(widget)
    widget.add_frame(IqFrame(i_samples=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
                             q_samples=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
                             source="d"))
    # Should not raise; image has been drawn at least once.
    assert widget._image_item is not None


def _iq_tone(amplitude: float, n: int = 256, f0: float = 1000.0,
             fs: float = 16_000.0):
    """Build parallel I/Q lists for a single complex tone."""
    import math

    i = [int(amplitude * math.cos(2 * math.pi * f0 * k / fs)) for k in range(n)]
    q = [int(amplitude * math.sin(2 * math.pi * f0 * k / fs)) for k in range(n)]
    return i, q


def test_iq_waterfall_resets_state_on_source_change(qtbot) -> None:
    """Switching spectrum source (16 kHz <-> 960 kHz) must drop the
    accumulated peak-hold / history / locked FFT size so a stronger
    wide session's peak-hold trace can't 'stick' on the narrow view.
    """
    pytest.importorskip("pyqtgraph")
    np = pytest.importorskip("numpy")

    from gui.live.widgets import HAS_PYQTGRAPH, IqWaterfallWidget
    from scanner_drivers.serial_sub import IqFrame

    if not HAS_PYQTGRAPH:
        pytest.skip("pyqtgraph not available at runtime")

    widget = IqWaterfallWidget(history_rows=4, sample_rate_hz=16_000.0)
    qtbot.addWidget(widget)
    widget.set_center_frequency(852_125_000.0)

    # Build a strong peak on the narrow source.
    i, q = _iq_tone(15000.0)
    widget.add_frame(IqFrame(i_samples=i, q_samples=q, source="d"))
    widget.add_frame(IqFrame(i_samples=i, q_samples=q, source="d"))
    strong_peak = float(np.asarray(widget._peak_hold).max())
    assert widget._fft_size is not None
    assert len(widget._frames) > 0

    # Simulate the source switch (live_dock calls set_sample_rate()).
    widget.set_sample_rate(960_000.0)
    assert widget._peak_hold is None
    assert widget._peak_times is None
    assert widget._fft_size is None
    assert len(widget._frames) == 0

    # Switch back to narrow and feed a much weaker signal; the rebuilt
    # peak-hold must reflect the weak frames, not the stale strong one.
    widget.set_sample_rate(16_000.0)
    wi, wq = _iq_tone(150.0)
    widget.add_frame(IqFrame(i_samples=wi, q_samples=wq, source="d"))
    widget.add_frame(IqFrame(i_samples=wi, q_samples=wq, source="d"))
    weak_peak = float(np.asarray(widget._peak_hold).max())
    assert weak_peak < strong_peak - 5.0, (
        f"peak-hold stuck at stale level: weak={weak_peak} strong={strong_peak}"
    )


def test_iq_waterfall_marker_tracks_center_frequency(qtbot) -> None:
    """The green center-frequency Marker line should appear at the tuned
    VC frequency (MHz) once a centre is known."""
    pytest.importorskip("pyqtgraph")
    pytest.importorskip("numpy")

    from gui.live.widgets import HAS_PYQTGRAPH, IqWaterfallWidget

    if not HAS_PYQTGRAPH:
        pytest.skip("pyqtgraph not available at runtime")

    widget = IqWaterfallWidget(history_rows=4, sample_rate_hz=16_000.0)
    qtbot.addWidget(widget)
    # Hidden before a centre frequency is known.
    assert not widget._marker_spectrum.isVisible()

    widget.set_center_frequency(852_125_000.0)
    assert widget._marker_spectrum.isVisible()
    assert widget._marker_waterfall.isVisible()
    assert abs(float(widget._marker_spectrum.value()) - 852.125) < 1e-6
    assert abs(float(widget._marker_waterfall.value()) - 852.125) < 1e-6


def test_iq_waterfall_max_hold_time_expires_old_peak(qtbot) -> None:
    """A finite Max-Hold-Time must let a peak decay back toward the live
    spectrum once it ages past the window."""
    import time

    pytest.importorskip("pyqtgraph")
    np = pytest.importorskip("numpy")

    from gui.live.widgets import HAS_PYQTGRAPH, IqWaterfallWidget
    from scanner_drivers.serial_sub import IqFrame

    if not HAS_PYQTGRAPH:
        pytest.skip("pyqtgraph not available at runtime")

    widget = IqWaterfallWidget(history_rows=8, sample_rate_hz=16_000.0)
    qtbot.addWidget(widget)
    widget.set_center_frequency(852_125_000.0)
    widget.set_max_hold_time(0.05)

    # Strong frame seeds a high peak.
    i, q = _iq_tone(15000.0)
    widget.add_frame(IqFrame(i_samples=i, q_samples=q, source="d"))
    strong_peak = float(np.asarray(widget._peak_hold).max())

    # Let the peak age past the hold window, then feed weak frames.
    time.sleep(0.12)
    wi, wq = _iq_tone(150.0)
    widget.add_frame(IqFrame(i_samples=wi, q_samples=wq, source="d"))
    decayed_peak = float(np.asarray(widget._peak_hold).max())
    assert decayed_peak < strong_peak - 5.0, (
        f"peak failed to decay: decayed={decayed_peak} strong={strong_peak}"
    )


# ------------------------------------------------------------------
# gui/live/controllers.py
# ------------------------------------------------------------------


def test_main_poller_controller_emits_gsi_and_glg(qtbot) -> None:
    from PySide6.QtWidgets import QWidget

    from gui.live.controllers import MainPollerController
    from scanner_drivers.serial_main import GlgEvent, GsiSnapshot, SerialMainDriver

    driver = SerialMainDriver(_MinimalFakePort())
    snap = GsiSnapshot(mode="Scan", system_name="Test")
    evt = GlgEvent(frq="154445000", is_receiving=True)
    driver.poll_gsi = lambda: snap  # type: ignore[method-assign]
    driver.poll_glg = lambda: evt  # type: ignore[method-assign]

    host = QWidget()
    qtbot.addWidget(host)
    ctrl = MainPollerController(driver, gsi_interval_ms=10, glg_interval_ms=10, parent=host)
    gsi_seen = []
    glg_seen = []
    ctrl.gsiUpdated.connect(gsi_seen.append)
    ctrl.glgUpdated.connect(glg_seen.append)
    ctrl.start()
    qtbot.waitUntil(lambda: bool(gsi_seen and glg_seen), timeout=2000)
    ctrl.close()
    assert gsi_seen[0].system_name == "Test"
    assert glg_seen[0].frq == "154445000"


def test_main_poller_controller_failed_on_gsi_error(qtbot) -> None:
    from PySide6.QtWidgets import QWidget

    from gui.live.controllers import MainPollerController
    from scanner_drivers.serial_main import GlgEvent, SerialMainDriver

    driver = SerialMainDriver(_MinimalFakePort())
    driver.poll_gsi = _raise_gsi_boom  # type: ignore[method-assign]
    driver.poll_glg = lambda: GlgEvent()  # type: ignore[method-assign]

    host = QWidget()
    qtbot.addWidget(host)
    ctrl = MainPollerController(driver, gsi_interval_ms=10, glg_interval_ms=1000, parent=host)
    failures = []
    ctrl.failed.connect(failures.append)
    ctrl.start()
    qtbot.waitUntil(lambda: bool(failures), timeout=2000)
    ctrl.close()
    assert "GSI" in failures[0]


def test_sub_poller_controller_modes(qtbot) -> None:
    from PySide6.QtWidgets import QWidget

    from gui.live.controllers import SubPollerController
    from scanner_drivers.serial_sub import IqFrame, SerialSubDriver, WaterfallFrame

    driver = SerialSubDriver(_MinimalFakePort())
    wf = WaterfallFrame(samples=[1, 2, 3])
    iq = IqFrame(i_samples=[1], q_samples=[2], source="d")
    driver.fetch_waterfall_frame = lambda: wf  # type: ignore[method-assign]
    driver.fetch_iq_pairs = lambda: iq  # type: ignore[method-assign]
    driver.fetch_wide_iq = lambda: iq  # type: ignore[method-assign]

    host = QWidget()
    qtbot.addWidget(host)
    wf_ctrl = SubPollerController(driver, interval_ms=10, mode="m", parent=host)
    wf_seen = []
    wf_ctrl.waterfallUpdated.connect(wf_seen.append)
    wf_ctrl.start()
    qtbot.waitUntil(lambda: bool(wf_seen), timeout=2000)
    wf_ctrl.close()

    iq_ctrl = SubPollerController(driver, interval_ms=10, mode="d", parent=host)
    iq_seen = []
    iq_ctrl.iqUpdated.connect(iq_seen.append)
    iq_ctrl.start()
    qtbot.waitUntil(lambda: bool(iq_seen), timeout=2000)
    iq_ctrl.set_mode("v")
    assert iq_ctrl.mode == "v"
    iq_ctrl.close()


def test_sub_poller_controller_failed_on_poll_error(qtbot) -> None:
    from PySide6.QtWidgets import QWidget

    from gui.live.controllers import SubPollerController
    from scanner_drivers.serial_sub import SerialSubDriver

    driver = SerialSubDriver(_MinimalFakePort())
    driver.fetch_iq_pairs = _raise_iq_fail  # type: ignore[method-assign]

    host = QWidget()
    qtbot.addWidget(host)
    ctrl = SubPollerController(driver, interval_ms=10, mode="d", parent=host)
    failures = []
    ctrl.failed.connect(failures.append)
    ctrl.start()
    qtbot.waitUntil(lambda: bool(failures), timeout=2000)
    ctrl.close()
    assert "FFT" in failures[0]


# ------------------------------------------------------------------
# gui/live/live_dock.py connect + handlers
# ------------------------------------------------------------------


def test_live_dock_connect_and_disconnect_with_mocks(qtbot, monkeypatch) -> None:
    from gui.live.live_dock import LiveDock
    from scanner_drivers.serial_main import GlgEvent, GsiSnapshot, SerialMainDriver
    from scanner_drivers.serial_sub import IqFrame, SerialSubDriver, WaterfallFrame
    from scanner_drivers.usb_detect import SDS_PID_MAIN, SDS_PID_SUB, UNIDEN_VID

    fake_ports = [
        _fake_port("COM4", UNIDEN_VID, SDS_PID_MAIN),
        _fake_port("COM3", UNIDEN_VID, SDS_PID_SUB),
    ]

    def _open_main(device):
        d = SerialMainDriver(_MinimalFakePort())
        d.query_model = lambda: "SDS100"  # type: ignore[method-assign]
        d.query_firmware = lambda: {"version": "1.25.99"}  # type: ignore[method-assign]
        d.poll_gsi = lambda: GsiSnapshot(mode="Scan", system_name="Sys", frequency_hz=154_445_000)  # type: ignore[method-assign]
        d.poll_glg = lambda: GlgEvent(is_receiving=True, frq="154445000", name3="FD")  # type: ignore[method-assign]
        return d

    def _open_sub(device):
        d = SerialSubDriver(_MinimalFakePort())
        d.fetch_iq_pairs = lambda: IqFrame(i_samples=[1, 2], q_samples=[3, 4], source="d")  # type: ignore[method-assign]
        d.fetch_waterfall_frame = lambda: WaterfallFrame(samples=[1, 2, 3])  # type: ignore[method-assign]
        return d

    monkeypatch.setattr("gui.live.live_dock.SerialMainDriver.open", _open_main)
    monkeypatch.setattr("gui.live.live_dock.SerialSubDriver.open", _open_sub)

    dock = LiveDock()
    qtbot.addWidget(dock)
    with patch("gui.live.live_dock.enumerate_ports", return_value=fake_ports), patch(
        "gui.live.live_dock.find_ports_for_profile",
        return_value=__import__(
            "scanner_drivers.usb_detect", fromlist=["ScannerPorts"]
        ).ScannerPorts(main=fake_ports[0], sub=fake_ports[1]),
    ):
        dock.set_active_profile(get_profile("uniden_sds100"))

    qtbot.mouseClick(dock._connect_btn, Qt.MouseButton.LeftButton)
    assert not dock._connect_btn.isEnabled()
    assert dock._disconnect_btn.isEnabled()
    assert dock._diag_btn.isEnabled()

    gsi = []
    dock.gsiUpdated.connect(gsi.append)
    qtbot.waitUntil(lambda: dock._mirror._system.text() != "—", timeout=3000)

    dock._wf_mode_combo.setCurrentIndex(2)
    dock._on_wf_mode_changed(2)
    dock._on_reset_peak_hold()

    dock.disconnect()
    assert dock._connect_btn.isEnabled()
    assert not dock._disconnect_btn.isEnabled()


def test_live_dock_connect_without_main_port_shows_warning(qtbot, monkeypatch) -> None:
    from PySide6.QtWidgets import QMessageBox

    from gui.live.live_dock import LiveDock

    dock = LiveDock()
    qtbot.addWidget(dock)
    dock.set_active_profile(get_profile("uniden_sds100"))
    dock._main_combo.clear()
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.append(a))
    qtbot.mouseClick(dock._connect_btn, Qt.MouseButton.LeftButton)
    assert warned


def test_live_dock_refresh_ports_partial_match(qtbot, monkeypatch) -> None:
    from gui.live.live_dock import LiveDock
    from scanner_drivers.usb_detect import SDS_PID_MAIN, UNIDEN_VID

    fake_ports = [_fake_port("COM9", UNIDEN_VID, SDS_PID_MAIN)]
    matched = __import__(
        "scanner_drivers.usb_detect", fromlist=["ScannerPorts"]
    ).ScannerPorts(main=fake_ports[0])

    dock = LiveDock()
    qtbot.addWidget(dock)
    with patch("gui.live.live_dock.enumerate_ports", return_value=fake_ports), patch(
        "gui.live.live_dock.find_ports_for_profile", return_value=matched
    ):
        dock.set_active_profile(get_profile("uniden_sds100"))
    assert "matching pair" in dock._status_label.text().lower()


def test_live_dock_main_and_sub_failure_handlers(qtbot) -> None:
    from gui.live.live_dock import LiveDock

    dock = LiveDock()
    qtbot.addWidget(dock)
    states = []
    dock.connectionStateChanged.connect(states.append)
    dock._on_main_failed("GSI: timeout")
    assert "MAIN poller stopped" in dock._status_label.text()
    dock._on_sub_failed("FFT: timeout")
    assert "SUB poller stopped" in dock._status_label.text()


def test_live_dock_request_close_disconnects(qtbot) -> None:
    from gui.live.live_dock import LiveDock

    dock = LiveDock()
    qtbot.addWidget(dock)
    dock.set_active_profile(get_profile("uniden_sds100"))
    assert dock.request_close() is True


def test_live_dock_diagnostic_capture_writes_json(
    qtbot, monkeypatch, tmp_path: Path, auto_msgbox
) -> None:
    from PySide6.QtWidgets import QFileDialog

    from gui.live.controllers import MainPollerController, SubPollerController
    from gui.live.live_dock import LiveDock
    from scanner_drivers.serial_main import GlgEvent, GsiSnapshot, SerialMainDriver
    from scanner_drivers.serial_sub import SerialSubDriver

    main_driver = SerialMainDriver(_MinimalFakePort())
    payload = b"<ScannerInfo Mode=\"Scan\"/>"
    main_driver.send_query = lambda cmd: payload  # type: ignore[method-assign]
    main_driver.poll_gsi = lambda: GsiSnapshot(mode="Scan", system_name="Cap")  # type: ignore[method-assign]
    main_driver.poll_glg = lambda: GlgEvent(is_receiving=True, frq="154445000")  # type: ignore[method-assign]

    sub_driver = SerialSubDriver(_MinimalFakePort())
    sub_driver.send_command = lambda cmd: b"12345"  # type: ignore[method-assign]

    out = tmp_path / "capture.json"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", lambda *a, **k: (str(out), "")
    )

    dock = LiveDock()
    qtbot.addWidget(dock)
    dock.set_active_profile(get_profile("uniden_sds100"))
    dock._main_controller = MainPollerController(main_driver, parent=dock)
    dock._sub_controller = SubPollerController(sub_driver, parent=dock)
    dock._connect_btn.setEnabled(False)
    dock._disconnect_btn.setEnabled(True)
    dock._diag_btn.setEnabled(True)

    with patch("gui.live.live_dock.time.sleep", lambda _s: None):
        dock._on_diagnostic_capture()

    assert out.exists()
    data = __import__("json").loads(out.read_text(encoding="utf-8"))
    assert data["gsi_samples"]
    assert data["glg_samples"]
    assert data["fft_samples"]

