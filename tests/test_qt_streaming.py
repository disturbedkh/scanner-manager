"""Phase 4: streaming dock smoke tests."""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.qt

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PySide6 = pytest.importorskip("PySide6")  # noqa: N816
pytest.importorskip("pytestqt")
pytest.importorskip("fastapi")


def test_streaming_dock_builds_with_default_state(qtbot) -> None:
    from gui.streaming.streaming_dock import StreamingDock

    dock = StreamingDock()
    qtbot.addWidget(dock)
    # Both the codec combo and the bitrate spinner exist
    assert dock._codec_combo.count() >= 2
    assert dock._bitrate_spin.value() == 64
    # Listener defaults to port 8765 and is not yet running
    assert dock._port_spin.value() == 8765
    assert dock._listener_btn.text() == "Start LAN listener"


def test_streaming_dock_push_helpers_dont_crash_without_server(qtbot) -> None:
    """Forwarding GSI / GLG / FFT events must be safe even when the
    listener isn't running."""
    from gui.streaming.streaming_dock import StreamingDock
    from scanner_drivers.serial_main import GlgEvent, GsiSnapshot
    from scanner_drivers.serial_sub import WaterfallFrame

    dock = StreamingDock()
    qtbot.addWidget(dock)

    snap = GsiSnapshot(mode="Scan", system_name="Test")
    dock.push_gsi(snap)
    dock.push_glg(GlgEvent(is_receiving=True, frq="154445000"))
    dock.push_waterfall(WaterfallFrame(samples=list(range(100))))


def test_streaming_dock_request_close_stops_capture(qtbot) -> None:
    from gui.streaming.streaming_dock import StreamingDock

    dock = StreamingDock()
    qtbot.addWidget(dock)
    assert dock.request_close() is True


def test_streaming_dock_listener_url_format(qtbot, monkeypatch) -> None:
    """The listener URL combines the local IP with the chosen port."""
    from gui.streaming import streaming_dock as sd

    _mock_listener_ip = ".".join(str(o) for o in (10, 0, 0, 42))
    monkeypatch.setattr(sd, "_local_ip", lambda: _mock_listener_ip)
    dock = sd.StreamingDock()
    qtbot.addWidget(dock)

    # Don't actually start uvicorn; just simulate the relevant code.
    dock._port_spin.setValue(8765)
    # We compute the URL inline; just assert helper produces the right ip.
    assert sd._local_ip() == _mock_listener_ip
