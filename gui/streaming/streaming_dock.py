"""Audio + telemetry streaming dock (Phase 4).

UI surface:

- Soundcard input picker + level meter
- Encoder picker (codec + bitrate)
- Local listener: start/stop server + URL + QR code
- Broadcastify push: mount + password + start/stop
- Icecast push: host/port/mount/password + start/stop
- Telemetry feed: counts of connected listeners

Lifecycle: each piece is started lazily via toggle buttons. The dock
owns the AudioCapture, the AudioEncoder, the StreamingServer, and
any active push targets. Closing the dock tears them all down
(:meth:`request_close` is wired via the main window's closeEvent).
"""

from __future__ import annotations

import logging
import socket
from dataclasses import asdict
from typing import Optional

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from audio.capture import AudioCapture, AudioFrame, list_input_devices
from audio.encoder import make_encoder
from scanner_drivers.serial_main import GlgEvent, GsiSnapshot
from scanner_drivers.serial_sub import WaterfallFrame
from scanner_profiles import ScannerProfile
from streaming.broadcastify import BroadcastifyPusher
from streaming.icecast import IcecastPusher
from streaming.server import StreamingServer

logger = logging.getLogger(__name__)

# Well-known DNS used only to pick a routable local IP (UDP connect trick).
_CONNECTIVITY_PROBE_HOST = "one.one.one.one"
_FORM_STATUS_LABEL = "Status:"
_IDLE_STATUS = "Idle."


def _local_ip() -> str:
    """Best-effort: pick a routable local IP for the listener URL."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect((_CONNECTIVITY_PROBE_HOST, 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


class StreamingDock(QWidget):
    """Audio capture + LAN listener + optional push targets."""

    # Peak audio level (0-100). Emitted from the PortAudio callback
    # thread; Qt uses a queued connection cross-thread so the progress
    # bar is only ever touched on the GUI thread.
    _levelChanged = Signal(int)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._capture: Optional[AudioCapture] = None
        self._encoder = None
        self._server: Optional[StreamingServer] = None
        self._broadcastify: Optional[BroadcastifyPusher] = None
        self._icecast: Optional[IcecastPusher] = None
        self._latest_gsi: Optional[GsiSnapshot] = None

        self._build_ui()

        self._levelChanged.connect(self._on_level_changed)

        self._listener_timer = QTimer(self)
        self._listener_timer.setInterval(1500)
        self._listener_timer.timeout.connect(self._refresh_listener_counts)
        self._listener_timer.start()

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        tabs = QTabWidget()
        tabs.addTab(self._build_audio_tab(), "Audio")
        tabs.addTab(self._build_listener_tab(), "Local listener")
        tabs.addTab(self._build_push_tab(), "Push (Broadcastify / Icecast)")
        layout.addWidget(tabs, stretch=1)

    def _build_audio_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        device_box = QGroupBox("Soundcard input")
        form = QFormLayout(device_box)

        self._device_combo = QComboBox()
        self._device_combo.setMinimumWidth(280)
        form.addRow("Input device:", self._device_combo)

        rate_row = QHBoxLayout()
        self._rate_combo = QComboBox()
        for r in (16000, 22050, 44100, 48000):
            self._rate_combo.addItem(f"{r} Hz", userData=r)
        self._rate_combo.setCurrentIndex(self._rate_combo.findData(48000))
        rate_row.addWidget(self._rate_combo)
        rate_row.addStretch(1)
        form.addRow("Sample rate:", _wrap_layout(rate_row))

        self._channels_combo = QComboBox()
        self._channels_combo.addItem("Mono (1)", userData=1)
        self._channels_combo.addItem("Stereo (2)", userData=2)
        form.addRow("Channels:", self._channels_combo)

        self._codec_combo = QComboBox()
        for label, value in (
            ("MP3 (lameenc)", "mp3"),
            ("Opus (pyogg)", "opus"),
            ("WAV / PCM (always available)", "wav"),
        ):
            self._codec_combo.addItem(label, userData=value)
        form.addRow("Codec:", self._codec_combo)

        self._bitrate_spin = QSpinBox()
        self._bitrate_spin.setRange(8, 320)
        self._bitrate_spin.setValue(64)
        self._bitrate_spin.setSuffix(" kbps")
        form.addRow("Bitrate:", self._bitrate_spin)

        layout.addWidget(device_box)

        meter_box = QGroupBox("Level")
        mlayout = QVBoxLayout(meter_box)
        self._level_bar = QProgressBar()
        self._level_bar.setRange(0, 100)
        self._level_bar.setFormat("%v%%")
        mlayout.addWidget(self._level_bar)
        layout.addWidget(meter_box)

        btn_row = QHBoxLayout()
        self._refresh_devices_btn = QPushButton("Refresh devices")
        self._refresh_devices_btn.clicked.connect(self._refresh_devices)
        btn_row.addWidget(self._refresh_devices_btn)

        self._capture_btn = QPushButton("Start capture")
        self._capture_btn.clicked.connect(self._on_toggle_capture)
        btn_row.addWidget(self._capture_btn)

        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        self._capture_status = QLabel("")
        self._capture_status.setStyleSheet("color: #555;")
        self._capture_status.setWordWrap(True)
        layout.addWidget(self._capture_status)
        layout.addStretch(1)

        self._refresh_devices()
        return page

    def _build_listener_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        box = QGroupBox("LAN listener (FastAPI + uvicorn)")
        form = QFormLayout(box)

        self._port_spin = QSpinBox()
        self._port_spin.setRange(1, 65535)
        self._port_spin.setValue(8765)
        form.addRow("Port:", self._port_spin)

        self._listener_status = QLabel("Not running.")
        form.addRow(_FORM_STATUS_LABEL, self._listener_status)

        self._listener_url = QLineEdit("")
        self._listener_url.setReadOnly(True)
        form.addRow("Listener URL:", self._listener_url)

        self._listener_counts = QLabel("audio=0  telemetry=0")
        form.addRow("Connected:", self._listener_counts)

        layout.addWidget(box)

        btn_row = QHBoxLayout()
        self._listener_btn = QPushButton("Start LAN listener")
        self._listener_btn.clicked.connect(self._on_toggle_listener)
        btn_row.addWidget(self._listener_btn)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)
        layout.addStretch(1)
        return page

    def _build_push_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        bf_box = QGroupBox("Broadcastify push")
        bform = QFormLayout(bf_box)
        self._bf_mount = QLineEdit()
        self._bf_mount.setPlaceholderText("/12345")
        bform.addRow("Mount:", self._bf_mount)
        self._bf_pass = QLineEdit()
        self._bf_pass.setEchoMode(QLineEdit.Password)
        bform.addRow("Password:", self._bf_pass)
        self._bf_btn = QPushButton("Start Broadcastify push")
        self._bf_btn.clicked.connect(self._on_toggle_broadcastify)
        bform.addRow(self._bf_btn)
        self._bf_status = QLabel(_IDLE_STATUS)
        self._bf_status.setWordWrap(True)
        bform.addRow(_FORM_STATUS_LABEL, self._bf_status)
        layout.addWidget(bf_box)

        ic_box = QGroupBox("Generic Icecast push")
        iform = QFormLayout(ic_box)
        self._ic_host = QLineEdit("icecast.example.com")
        iform.addRow("Host:", self._ic_host)
        self._ic_port = QSpinBox()
        self._ic_port.setRange(1, 65535)
        self._ic_port.setValue(8000)
        iform.addRow("Port:", self._ic_port)
        self._ic_mount = QLineEdit("/scanner.mp3")
        iform.addRow("Mount:", self._ic_mount)
        self._ic_pass = QLineEdit()
        self._ic_pass.setEchoMode(QLineEdit.Password)
        iform.addRow("Password:", self._ic_pass)
        self._ic_btn = QPushButton("Start Icecast push")
        self._ic_btn.clicked.connect(self._on_toggle_icecast)
        iform.addRow(self._ic_btn)
        self._ic_status = QLabel(_IDLE_STATUS)
        self._ic_status.setWordWrap(True)
        iform.addRow(_FORM_STATUS_LABEL, self._ic_status)
        layout.addWidget(ic_box)

        creds_note = QLabel(
            "<i>Credentials are not persisted across sessions. To save them "
            "encrypted in the OS keychain, install the optional "
            "<code>keyring</code> package and re-enter once.</i>"
        )
        creds_note.setWordWrap(True)
        layout.addWidget(creds_note)
        layout.addStretch(1)
        return page

    # ------------------------------------------------------------------
    # Public API used by MainWindow
    # ------------------------------------------------------------------

    def set_active_profile(self, profile: ScannerProfile) -> None:
        # Streaming dock works for every profile that has audio output.
        # We don't need to swap encoders; we DO want to update the
        # listener URL when the user picks a profile that's bound to
        # a card in a different network namespace - leave that for
        # Phase 6.
        pass

    def request_close(self) -> bool:
        self.stop_capture()
        self.stop_listener()
        self.stop_broadcastify()
        self.stop_icecast()
        return True

    # ------------------------------------------------------------------
    # Telemetry pipe (called by MainWindow when the live dock fires)
    # ------------------------------------------------------------------

    def push_gsi(self, snap: GsiSnapshot) -> None:
        self._latest_gsi = snap
        if self._server is not None and self._server.is_running:
            payload = asdict(snap)
            payload["kind"] = "gsi"
            payload.pop("raw_xml", None)  # don't bloat the websocket
            self._server.push_telemetry(payload)

    def push_glg(self, evt: GlgEvent) -> None:
        if self._server is not None and self._server.is_running:
            payload = asdict(evt)
            payload["kind"] = "glg"
            payload.pop("raw", None)
            self._server.push_telemetry(payload)

    def push_waterfall(self, frame: WaterfallFrame) -> None:
        if self._server is None or not self._server.is_running:
            return
        # Downsample for telemetry: 64 bins is plenty for a browser
        if not frame.samples:
            return
        n = len(frame.samples)
        step = max(1, n // 64)
        compact = frame.samples[::step][:64]
        self._server.push_telemetry(
            {"kind": "waterfall", "bins": compact, "ts": frame.captured_at}
        )

    # ------------------------------------------------------------------
    # Audio capture
    # ------------------------------------------------------------------

    def _refresh_devices(self) -> None:
        self._device_combo.clear()
        devices = list_input_devices()
        if not devices:
            self._device_combo.addItem("(no input devices found)", userData=None)
            self._device_combo.setEnabled(False)
            self._capture_btn.setEnabled(False)
            return
        self._device_combo.setEnabled(True)
        self._capture_btn.setEnabled(True)
        for dev in devices:
            self._device_combo.addItem(
                f"{dev.name}  [{dev.host_api}]  ({dev.max_input_channels} ch)",
                userData=dev.index,
            )

    def _on_toggle_capture(self) -> None:
        if self._capture is not None:
            self.stop_capture()
            return
        device_index = self._device_combo.currentData()
        sample_rate = int(self._rate_combo.currentData() or 48000)
        channels = int(self._channels_combo.currentData() or 1)
        codec = self._codec_combo.currentData() or "wav"
        bitrate = int(self._bitrate_spin.value())

        try:
            self._encoder = make_encoder(
                codec=codec,
                sample_rate=sample_rate,
                channels=channels,
                bitrate_kbps=bitrate,
            )
            capture = AudioCapture(
                device_index=device_index,
                sample_rate=sample_rate,
                channels=channels,
            )
            capture.set_callback(self._on_audio_frame)
            capture.start()
            self._capture = capture
        except Exception as exc:
            QMessageBox.critical(self, "Audio capture", f"Failed to start: {exc}")
            self._capture = None
            self._encoder = None
            return

        if self._server is not None:
            self._server.set_encoder(self._encoder)
        self._capture_btn.setText("Stop capture")
        self._capture_status.setText(
            f"Capturing {sample_rate} Hz {'mono' if channels == 1 else 'stereo'}, codec={codec}, bitrate={bitrate} kbps"
        )

    def stop_capture(self) -> None:
        if self._capture is None:
            return
        try:
            self._capture.stop()
        finally:
            self._capture = None
            self._encoder = None
        self._capture_btn.setText("Start capture")
        self._capture_status.setText("Capture stopped.")

    def _distribute_audio_chunk(self, chunk: bytes) -> None:
        if self._server is not None:
            self._server.push_audio_chunk(chunk)
        if self._broadcastify is not None:
            self._broadcastify.feed(chunk)
        if self._icecast is not None:
            self._icecast.feed(chunk)

    def _emit_level(self, frame: AudioFrame) -> None:
        """Compute the peak level and hand it to the GUI thread.

        Runs on the PortAudio callback thread. Emitting a signal lets Qt
        marshal the widget update onto the GUI thread (queued when
        cross-thread) so the ``QProgressBar`` is never touched off-thread.
        """
        try:
            level = int(min(100, frame.peak * 100))
        except Exception:
            level = 0
        self._levelChanged.emit(level)

    def _on_level_changed(self, level: int) -> None:
        try:
            self._level_bar.setValue(level)
        except Exception:
            pass

    def _on_audio_frame(self, frame: AudioFrame) -> None:
        if self._encoder is not None:
            try:
                self._encoder.feed(frame)
                chunk = self._encoder.drain()
            except Exception:
                logger.exception("Encoder failed")
                chunk = b""
            if chunk:
                self._distribute_audio_chunk(chunk)
        self._emit_level(frame)

    # ------------------------------------------------------------------
    # LAN listener
    # ------------------------------------------------------------------

    def _on_toggle_listener(self) -> None:
        if self._server is not None and self._server.is_running:
            self.stop_listener()
            return
        port = int(self._port_spin.value())
        try:
            server = StreamingServer(host="0.0.0.0", port=port)
            if self._encoder is not None:
                server.set_encoder(self._encoder)
            server.start_in_thread()
        except Exception as exc:
            QMessageBox.critical(self, "Listener", f"Failed to start: {exc}")
            return
        self._server = server
        self._listener_btn.setText("Stop LAN listener")
        ip = _local_ip()
        url = f"http://{ip}:{port}/viewer"  # NOSONAR - local LAN HTTP listener for on-prem viewer
        self._listener_url.setText(url)
        self._listener_status.setText("Running.")

    def stop_listener(self) -> None:
        if self._server is None:
            return
        try:
            self._server.stop()
        finally:
            self._server = None
        self._listener_btn.setText("Start LAN listener")
        self._listener_status.setText("Not running.")
        self._listener_url.setText("")
        self._listener_counts.setText("audio=0  telemetry=0")

    def _refresh_listener_counts(self) -> None:
        if self._server is None:
            return
        counts = self._server.listener_counts()
        self._listener_counts.setText(
            f"audio={counts.get('audio', 0)}  telemetry={counts.get('telemetry', 0)}"
        )

    # ------------------------------------------------------------------
    # Broadcastify + Icecast push
    # ------------------------------------------------------------------

    def _on_toggle_broadcastify(self) -> None:
        if self._broadcastify is not None:
            self.stop_broadcastify()
            return
        mount = self._bf_mount.text().strip()
        password = self._bf_pass.text()
        if not mount or not password:
            QMessageBox.warning(self, "Broadcastify", "Mount + password required.")
            return
        try:
            pusher = BroadcastifyPusher(mount=mount, password=password)
            pusher.start()
        except Exception as exc:
            QMessageBox.critical(self, "Broadcastify", f"Failed to start: {exc}")
            return
        self._broadcastify = pusher
        self._bf_btn.setText("Stop Broadcastify push")
        self._bf_status.setText("Connecting…")

    def stop_broadcastify(self) -> None:
        if self._broadcastify is None:
            return
        try:
            self._broadcastify.stop()
        finally:
            self._broadcastify = None
        self._bf_btn.setText("Start Broadcastify push")
        self._bf_status.setText(_IDLE_STATUS)

    def _on_toggle_icecast(self) -> None:
        if self._icecast is not None:
            self.stop_icecast()
            return
        host = self._ic_host.text().strip()
        port = int(self._ic_port.value())
        mount = self._ic_mount.text().strip()
        password = self._ic_pass.text()
        if not (host and mount and password):
            QMessageBox.warning(self, "Icecast", "Host, mount, password are required.")
            return
        try:
            pusher = IcecastPusher(
                host=host, port=port, mount=mount, password=password,
                content_type=self._encoder.mime_type if self._encoder else "audio/mpeg",
            )
            pusher.start()
        except Exception as exc:
            QMessageBox.critical(self, "Icecast", f"Failed to start: {exc}")
            return
        self._icecast = pusher
        self._ic_btn.setText("Stop Icecast push")
        self._ic_status.setText("Connecting…")

    def stop_icecast(self) -> None:
        if self._icecast is None:
            return
        try:
            self._icecast.stop()
        finally:
            self._icecast = None
        self._ic_btn.setText("Start Icecast push")
        self._ic_status.setText(_IDLE_STATUS)


def _wrap_layout(layout):
    w = QWidget()
    w.setLayout(layout)
    return w
