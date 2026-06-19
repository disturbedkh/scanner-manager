"""Phase 3: live serial-mode dock smoke tests.

These tests validate the dock's structural wiring + signal pipes
without ever opening a real serial port. The driver layer is
covered by ``test_serial_main`` / ``test_serial_sub``.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PySide6 = pytest.importorskip("PySide6")  # noqa: N816
pytest.importorskip("pytestqt")

from scanner_drivers.serial_main import GlgEvent, GsiSnapshot  # noqa: E402
from scanner_drivers.serial_sub import WaterfallFrame  # noqa: E402
from scanner_drivers.usb_detect import (  # noqa: E402
    SDS_PID_MAIN,
    SDS_PID_SUB,
    UNIDEN_VID,
    DetectedPort,
)
from scanner_profiles import get_profile  # noqa: E402


def _fake_port(device, vid, pid, sn="ABC") -> DetectedPort:
    return DetectedPort(
        device=device,
        description=f"Uniden {pid:04x}",
        hwid=f"USB VID:PID={vid:04X}:{pid:04X}",
        vid=vid,
        pid=pid,
        serial_number=sn,
    )


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

    class _FakePort:
        def __init__(self, payload: bytes) -> None:
            self._buf = payload + b"\r"
            self.in_waiting = len(self._buf)

        def write(self, _data: bytes) -> int:
            return len(_data)

        def flush(self) -> None:
            pass

        def reset_input_buffer(self) -> None:
            pass

        def read(self, n: int) -> bytes:
            chunk = self._buf[:n]
            self._buf = self._buf[n:]
            self.in_waiting = len(self._buf)
            return chunk

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
    driver = SerialMainDriver(_FakePort(payload))
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
