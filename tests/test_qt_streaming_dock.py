"""Extended smoke + interaction tests for gui/streaming/streaming_dock.py."""

from __future__ import annotations

import os
from unittest.mock import MagicMock

import numpy as np
import pytest

pytestmark = pytest.mark.qt

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PySide6 = pytest.importorskip("PySide6")  # noqa: N816
pytest.importorskip("pytestqt")
pytest.importorskip("fastapi")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QMessageBox  # noqa: E402

from audio.capture import AudioFrame  # noqa: E402
from scanner_drivers.serial_main import GlgEvent, GsiSnapshot  # noqa: E402
from scanner_drivers.serial_sub import WaterfallFrame  # noqa: E402


@pytest.fixture
def auto_msgbox(monkeypatch):
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)


def _fake_frame(peak: float = 0.75) -> AudioFrame:
    pcm = np.array([[peak]], dtype=np.float32)
    return AudioFrame(pcm=pcm, sample_rate=48000, channels=1, rms=peak, peak=peak)


def test_local_ip_fallback(monkeypatch):
    from gui.streaming import streaming_dock as sd

    class _BrokenSocket:
        def __enter__(self):
            raise OSError("no route")

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(sd.socket, "socket", lambda *a, **k: _BrokenSocket())
    assert sd._local_ip() == "127.0.0.1"


def test_refresh_devices_empty(qtbot, monkeypatch):
    from gui.streaming.streaming_dock import StreamingDock

    monkeypatch.setattr(
        "gui.streaming.streaming_dock.list_input_devices", lambda: []
    )
    dock = StreamingDock()
    qtbot.addWidget(dock)
    dock._refresh_devices()
    assert not dock._device_combo.isEnabled()
    assert not dock._capture_btn.isEnabled()


def test_refresh_devices_populates_combo(qtbot, monkeypatch):
    from audio.capture import AudioDeviceInfo
    from gui.streaming.streaming_dock import StreamingDock

    dev = AudioDeviceInfo(
        index=3,
        name="Fake Mic",
        host_api="WASAPI",
        max_input_channels=2,
        default_samplerate=48000.0,
    )
    monkeypatch.setattr(
        "gui.streaming.streaming_dock.list_input_devices", lambda: [dev]
    )
    dock = StreamingDock()
    qtbot.addWidget(dock)
    dock._refresh_devices()
    assert dock._device_combo.isEnabled()
    assert dock._device_combo.currentData() == 3


def test_toggle_capture_start_stop(qtbot, monkeypatch):
    from audio.capture import AudioDeviceInfo
    from gui.streaming.streaming_dock import StreamingDock

    class _FakeCapture:
        def __init__(self, **_kwargs):
            self._cb = None
            self.started = False

        def set_callback(self, cb):
            self._cb = cb

        def start(self):
            self.started = True

        def stop(self):
            self.started = False

    dev = AudioDeviceInfo(
        index=0,
        name="Fake Mic",
        host_api="WASAPI",
        max_input_channels=1,
        default_samplerate=48000.0,
    )
    monkeypatch.setattr(
        "gui.streaming.streaming_dock.list_input_devices", lambda: [dev]
    )
    monkeypatch.setattr(
        "gui.streaming.streaming_dock.AudioCapture", _FakeCapture
    )
    monkeypatch.setattr(
        "gui.streaming.streaming_dock.make_encoder",
        lambda **_k: MagicMock(feed=lambda _f: None, drain=lambda: b"enc"),
    )
    dock = StreamingDock()
    qtbot.addWidget(dock)

    qtbot.mouseClick(dock._capture_btn, Qt.MouseButton.LeftButton)
    assert dock._capture is not None
    assert dock._capture_btn.text() == "Stop capture"

    qtbot.mouseClick(dock._capture_btn, Qt.MouseButton.LeftButton)
    assert dock._capture is None
    assert dock._capture_btn.text() == "Start capture"


def test_on_audio_frame_updates_level_and_pushes(qtbot):
    from gui.streaming.streaming_dock import StreamingDock

    dock = StreamingDock()
    qtbot.addWidget(dock)
    pushed = []
    dock._encoder = MagicMock(feed=lambda _f: None, drain=lambda: b"chunk")
    dock._server = MagicMock(push_audio_chunk=pushed.append)
    dock._on_audio_frame(_fake_frame(0.8))
    assert pushed == [b"chunk"]
    assert dock._level_bar.value() == 80


def test_push_telemetry_when_server_running(qtbot):
    from gui.streaming.streaming_dock import StreamingDock

    dock = StreamingDock()
    qtbot.addWidget(dock)
    server = MagicMock(is_running=True)
    pushed = []
    server.push_telemetry = pushed.append
    dock._server = server

    snap = GsiSnapshot(mode="Scan", system_name="Test")
    dock.push_gsi(snap)
    assert pushed and pushed[0]["kind"] == "gsi"

    dock.push_glg(GlgEvent(is_receiving=True, frq="154445000"))
    assert any(p.get("kind") == "glg" for p in pushed)

    dock.push_waterfall(WaterfallFrame(samples=list(range(128))))
    assert any(p.get("kind") == "waterfall" for p in pushed)


def test_push_waterfall_skips_empty_samples(qtbot):
    from gui.streaming.streaming_dock import StreamingDock

    dock = StreamingDock()
    qtbot.addWidget(dock)
    server = MagicMock(is_running=True)
    dock._server = server
    dock.push_waterfall(WaterfallFrame(samples=[]))
    server.push_telemetry.assert_not_called()


def test_toggle_listener_start_stop(qtbot, monkeypatch):
    from gui.streaming.streaming_dock import StreamingDock

    class _FakeServer:
        instances = []

        def __init__(self, host="0.0.0.0", port=8765):
            self.host = host
            self.port = port
            self._running = False
            _FakeServer.instances.append(self)

        def set_encoder(self, _enc):
            pass  # test double: intentionally empty

        def start_in_thread(self):
            self._running = True

        def stop(self):
            self._running = False

        @property
        def is_running(self):
            return self._running

        def listener_counts(self):
            return {"audio": 0, "telemetry": 0}

    monkeypatch.setattr(
        "gui.streaming.streaming_dock.StreamingServer", _FakeServer
    )
    monkeypatch.setattr(
        "gui.streaming.streaming_dock._local_ip", lambda: "listener.test"
    )

    dock = StreamingDock()
    qtbot.addWidget(dock)
    dock._port_spin.setValue(9000)

    qtbot.mouseClick(dock._listener_btn, Qt.MouseButton.LeftButton)
    assert dock._server is not None
    assert "listener.test:9000" in dock._listener_url.text()
    assert dock._listener_btn.text() == "Stop LAN listener"

    qtbot.mouseClick(dock._listener_btn, Qt.MouseButton.LeftButton)
    assert dock._server is None
    assert dock._listener_btn.text() == "Start LAN listener"


def test_refresh_listener_counts(qtbot):
    from gui.streaming.streaming_dock import StreamingDock

    dock = StreamingDock()
    qtbot.addWidget(dock)
    dock._server = MagicMock(listener_counts=lambda: {"audio": 2, "telemetry": 1})
    dock._refresh_listener_counts()
    assert "audio=2" in dock._listener_counts.text()
    assert "telemetry=1" in dock._listener_counts.text()


def test_broadcastify_requires_credentials(qtbot, monkeypatch):
    from gui.streaming.streaming_dock import StreamingDock

    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.append(a))
    dock = StreamingDock()
    qtbot.addWidget(dock)
    qtbot.mouseClick(dock._bf_btn, Qt.MouseButton.LeftButton)
    assert warned


def test_broadcastify_toggle(qtbot, monkeypatch):
    from gui.streaming.streaming_dock import StreamingDock

    class _FakePusher:
        def __init__(self, mount, password):
            self.mount = mount
            self.started = False

        def start(self):
            self.started = True

        def stop(self):
            self.started = False

    monkeypatch.setattr(
        "gui.streaming.streaming_dock.BroadcastifyPusher", _FakePusher
    )
    dock = StreamingDock()
    qtbot.addWidget(dock)
    dock._bf_mount.setText("/12345")
    dock._bf_pass.setText("secret")

    qtbot.mouseClick(dock._bf_btn, Qt.MouseButton.LeftButton)
    assert dock._broadcastify is not None
    assert dock._bf_btn.text() == "Stop Broadcastify push"

    qtbot.mouseClick(dock._bf_btn, Qt.MouseButton.LeftButton)
    assert dock._broadcastify is None


def test_icecast_toggle(qtbot, monkeypatch):
    from gui.streaming.streaming_dock import StreamingDock

    class _FakeIce:
        def __init__(self, **_k):
            pass  # test double: intentionally empty

        def start(self):
            pass  # test double: intentionally empty

        def stop(self):
            pass  # test double: intentionally empty

    monkeypatch.setattr("gui.streaming.streaming_dock.IcecastPusher", _FakeIce)
    dock = StreamingDock()
    qtbot.addWidget(dock)
    dock._ic_host.setText("localhost")
    dock._ic_mount.setText("/live")
    dock._ic_pass.setText("pass")

    qtbot.mouseClick(dock._ic_btn, Qt.MouseButton.LeftButton)
    assert dock._ic_btn.text() == "Stop Icecast push"
    qtbot.mouseClick(dock._ic_btn, Qt.MouseButton.LeftButton)
    assert dock._ic_btn.text() == "Start Icecast push"


def test_set_active_profile_is_noop(qtbot):
    from gui.streaming.streaming_dock import StreamingDock
    from scanner_profiles import get_profile

    dock = StreamingDock()
    qtbot.addWidget(dock)
    dock.set_active_profile(get_profile("uniden_sds100"))
