"""Live serial-mode mirror dock (SDS100/200 only).

UI surface:

- Device picker / connect / disconnect controls (auto-fills with
  detected MAIN + SUB ports for the active profile)
- :class:`GsiMirrorWidget` - latest snapshot
- :class:`MetersWidget` - RSSI + signal bars
- :class:`GlgFeedWidget` - rolling call list
- :class:`WaterfallWidget` - FFT magnitude over time

The dock is hidden by the main window when the active profile reports
``supports_serial_mode == False``.

Signals exposed for the streaming dock + status header to consume
without owning the controllers themselves:

- :attr:`gsiUpdated(GsiSnapshot)`
- :attr:`glgUpdated(GlgEvent)`
- :attr:`waterfallUpdated(WaterfallFrame)`
- :attr:`connectionStateChanged(str)`  - "red" / "yellow" / "green"
"""

from __future__ import annotations

import json
import logging
import os
import platform
import sys
import time
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from device_manager import Device
from scanner_drivers.serial_main import (
    GlgEvent,
    GsiSnapshot,
    MainDriverError,
    SerialMainDriver,
)
from scanner_drivers.serial_sub import (
    SerialSubDriver,
    SubDriverError,
    WaterfallFrame,
)
from scanner_drivers.usb_detect import (
    DetectedPort,
    enumerate_ports,
    find_ports_for_profile,
)
from scanner_profiles import ScannerProfile

from scanner_drivers.serial_sub import IqFrame

from .controllers import MainPollerController, SubPollerController
from .scanner_control import ScannerControlWidget
from .widgets import (
    GlgFeedWidget,
    GsiMirrorWidget,
    IqWaterfallWidget,
    MetersWidget,
    WaterfallWidget,
)

logger = logging.getLogger(__name__)


class LiveDock(QWidget):
    """Phase 3 live serial-mode dock."""

    gsiUpdated = Signal(GsiSnapshot)
    glgUpdated = Signal(GlgEvent)
    waterfallUpdated = Signal(WaterfallFrame)
    iqUpdated = Signal(IqFrame)
    connectionStateChanged = Signal(str)
    firmwareDetected = Signal(str, str)  # (main_version, sub_version)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._profile: Optional[ScannerProfile] = None
        self._main_controller: Optional[MainPollerController] = None
        self._sub_controller: Optional[SubPollerController] = None
        self._build_ui()
        self._set_unsupported_message()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_active_profile(self, profile: ScannerProfile) -> None:
        self._profile = profile
        if not profile.supports_serial_mode:
            self.disconnect()
            self._set_unsupported_message()
            return
        self._set_supported_message()
        self.refresh_ports()

    def request_close(self) -> bool:
        self.disconnect()
        return True

    def disconnect(self) -> None:
        if self._main_controller is not None:
            self._main_controller.close()
            self._main_controller = None
        if self._sub_controller is not None:
            self._sub_controller.close()
            self._sub_controller = None
        # Drop the driver reference from the control panel so its
        # buttons grey out.
        if hasattr(self, "_control"):
            self._control.set_driver(None)
        self._connect_btn.setEnabled(True)
        self._disconnect_btn.setEnabled(False)
        if hasattr(self, "_diag_btn"):
            self._diag_btn.setEnabled(False)
        self._status_label.setText("Disconnected.")
        self.connectionStateChanged.emit("yellow")

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        controls = QWidget()
        crow = QHBoxLayout(controls)
        crow.setContentsMargins(0, 0, 0, 0)

        crow.addWidget(QLabel("MAIN port:"))
        self._main_combo = QComboBox()
        self._main_combo.setMinimumWidth(160)
        crow.addWidget(self._main_combo)

        crow.addWidget(QLabel("SUB port:"))
        self._sub_combo = QComboBox()
        self._sub_combo.setMinimumWidth(160)
        crow.addWidget(self._sub_combo)

        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.clicked.connect(self.refresh_ports)
        crow.addWidget(self._refresh_btn)

        self._connect_btn = QPushButton("Connect")
        self._connect_btn.clicked.connect(self._on_connect_clicked)
        crow.addWidget(self._connect_btn)

        self._disconnect_btn = QPushButton("Disconnect")
        self._disconnect_btn.setEnabled(False)
        self._disconnect_btn.clicked.connect(self.disconnect)
        crow.addWidget(self._disconnect_btn)

        # Diagnostic capture - dumps raw GSI/GLG/FFT bytes to a file
        # so we can debug field-level parsing against your firmware.
        self._diag_btn = QPushButton("Diagnostic capture…")
        self._diag_btn.setEnabled(False)
        self._diag_btn.setToolTip(
            "Capture raw GSI/GLG/FFT bytes from the live drivers to a "
            "JSON file. Click during an active call so the capture "
            "contains receive-state data."
        )
        self._diag_btn.clicked.connect(self._on_diagnostic_capture)
        crow.addWidget(self._diag_btn)

        crow.addStretch(1)
        layout.addWidget(controls)

        self._status_label = QLabel("")
        self._status_label.setWordWrap(True)
        self._status_label.setStyleSheet("color: #555;")
        layout.addWidget(self._status_label)

        # Splitter layout (all axes user-resizable):
        #
        #   +------------------+----------------------------+
        #   | Scanner          |  Mirror | Meters            |
        #   | control          |---------+-------------------|
        #   | (vol/sql/        |  GLG feed                  |
        #   |  hold/scan/...)  |                            |
        #   +------------------+----------------------------+
        #   |  Waterfall (FFT)                              |
        #   +-----------------------------------------------+
        self._control = ScannerControlWidget()
        self._control.statusMessage.connect(self._status_label.setText)

        right_top = QWidget()
        rtg = QGridLayout(right_top)
        rtg.setContentsMargins(0, 0, 0, 0)
        self._mirror = GsiMirrorWidget()
        rtg.addWidget(self._mirror, 0, 0)
        self._meters = MetersWidget()
        rtg.addWidget(self._meters, 0, 1)
        self._feed = GlgFeedWidget()
        rtg.addWidget(self._feed, 1, 0, 1, 2)
        rtg.setRowStretch(1, 1)
        rtg.setColumnStretch(0, 2)
        rtg.setColumnStretch(1, 1)

        top_h_splitter = QSplitter(Qt.Horizontal)
        top_h_splitter.addWidget(self._control)
        top_h_splitter.addWidget(right_top)
        top_h_splitter.setStretchFactor(0, 1)
        top_h_splitter.setStretchFactor(1, 3)
        top_h_splitter.setHandleWidth(6)

        # Spectrum / waterfall stack: an SDR-style I/Q view (mirrors
        # the SDS100's built-in spectrum screen) and the legacy
        # raw-`m` waterfall, switchable from a combo box. Default to
        # the I/Q view because it actually maps frequency to the X
        # axis instead of just bin index.
        wf_box = QWidget()
        wf_layout = QVBoxLayout(wf_box)
        wf_layout.setContentsMargins(0, 0, 0, 0)

        wf_toolbar = QHBoxLayout()
        wf_toolbar.addWidget(QLabel("Spectrum source:"))
        self._wf_mode_combo = QComboBox()
        self._wf_mode_combo.addItem("SDR I/Q narrow (`d`, ~16 kHz BW)", "d")
        self._wf_mode_combo.addItem("SDR I/Q wide (`v`, ~960 kHz BW)", "v")
        self._wf_mode_combo.addItem("Raw `m` time-domain rFFT (legacy)", "m")
        self._wf_mode_combo.currentIndexChanged.connect(self._on_wf_mode_changed)
        wf_toolbar.addWidget(self._wf_mode_combo)

        self._wf_peak_reset_btn = QPushButton("Reset peak hold")
        self._wf_peak_reset_btn.clicked.connect(self._on_reset_peak_hold)
        wf_toolbar.addWidget(self._wf_peak_reset_btn)

        wf_toolbar.addStretch(1)
        wf_layout.addLayout(wf_toolbar)

        self._iq_waterfall = IqWaterfallWidget(sample_rate_hz=16_000.0)
        self._waterfall = WaterfallWidget()

        self._wf_stack = QStackedWidget()
        self._wf_stack.addWidget(self._iq_waterfall)   # index 0 (default)
        self._wf_stack.addWidget(self._waterfall)      # index 1
        wf_layout.addWidget(self._wf_stack, stretch=1)

        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(top_h_splitter)
        splitter.addWidget(wf_box)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setHandleWidth(6)
        layout.addWidget(splitter, stretch=1)

    def _set_unsupported_message(self) -> None:
        self._status_label.setText(
            "Live serial-mode mirror is unavailable on this scanner. "
            "Switch to an SDS100/200 device to see GSI/GLG/FFT here."
        )
        for w in (self._main_combo, self._sub_combo, self._connect_btn,
                  self._disconnect_btn, self._refresh_btn):
            w.setEnabled(False)
        if hasattr(self, "_control"):
            self._control.set_driver(None)

    def _set_supported_message(self) -> None:
        for w in (self._main_combo, self._sub_combo, self._connect_btn,
                  self._refresh_btn):
            w.setEnabled(True)
        self._status_label.setText(
            "Put your scanner in Serial Mode (Menu → Settings → Set Serial Port → Sub & Main)."
        )

    # ------------------------------------------------------------------
    # Port discovery
    # ------------------------------------------------------------------

    def refresh_ports(self) -> None:
        if self._profile is None:
            return
        all_ports = enumerate_ports()
        matched = find_ports_for_profile(self._profile)

        self._main_combo.clear()
        self._sub_combo.clear()

        # Populate every visible port; mark detected matches with a hint.
        for combo, default_port, label in (
            (self._main_combo, matched.main, "MAIN"),
            (self._sub_combo, matched.sub, "SUB"),
        ):
            for port in all_ports:
                tag = " (detected)" if default_port and port.device == default_port.device else ""
                combo.addItem(f"{port.device} - {port.description}{tag}", userData=port.device)
            if default_port is not None:
                idx = combo.findData(default_port.device)
                if idx >= 0:
                    combo.setCurrentIndex(idx)

        if not all_ports:
            self._status_label.setText(
                "No serial ports visible. Make sure the scanner is plugged in "
                "and in Serial Mode (Menu → Set Serial Port)."
            )
            self.connectionStateChanged.emit("red")
        elif matched.is_complete:
            self._status_label.setText(
                f"Detected MAIN={matched.main.device} + SUB={matched.sub.device}. "
                "Click Connect."
            )
            self.connectionStateChanged.emit("yellow")
        elif matched.has_any:
            present = matched.main.device if matched.main else matched.sub.device
            self._status_label.setText(
                f"Found {present} but not the matching pair. Confirm Serial Mode is "
                "set to 'Sub & Main' on the scanner."
            )
            self.connectionStateChanged.emit("yellow")
        else:
            self._status_label.setText(
                f"{len(all_ports)} port(s) visible but none match Uniden's USB IDs."
            )
            self.connectionStateChanged.emit("red")

    # ------------------------------------------------------------------
    # Connect / poll
    # ------------------------------------------------------------------

    def _on_connect_clicked(self) -> None:
        main_device = self._main_combo.currentData()
        sub_device = self._sub_combo.currentData()
        if not main_device:
            QMessageBox.warning(self, "Connect", "Pick a MAIN port first.")
            return
        try:
            main_driver = SerialMainDriver.open(main_device)
        except MainDriverError as exc:
            QMessageBox.critical(self, "Connect", str(exc))
            self.connectionStateChanged.emit("red")
            return

        # Optional: test the link with MDL/VER
        try:
            model = main_driver.query_model()
            fw = main_driver.query_firmware().get("version", "")
            self._status_label.setText(
                f"Connected to {model or 'scanner'} (FW {fw or '?'}) on {main_device}."
            )
            self.firmwareDetected.emit(fw, "")
        except Exception as exc:
            logger.warning("Probe failed after connect: %s", exc)
            self._status_label.setText(
                f"Connected to {main_device} but probe failed: {exc}"
            )

        self._main_controller = MainPollerController(main_driver, parent=self)
        self._main_controller.gsiUpdated.connect(self._on_gsi)
        self._main_controller.glgUpdated.connect(self._on_glg)
        self._main_controller.failed.connect(self._on_main_failed)
        self._main_controller.start()
        # Bind the live driver into the scanner-control panel so the
        # user can drive VOL / SQL / KEY from the GUI. The driver's
        # internal lock makes this safe alongside the polling loop.
        self._control.set_driver(main_driver)

        if sub_device:
            try:
                sub_driver = SerialSubDriver.open(sub_device)
                # Use the spectrum-source combo's current value so the
                # user's last choice persists across connect cycles.
                wf_mode = self._wf_mode_combo.currentData() or "d"
                self._sub_controller = SubPollerController(
                    sub_driver, mode=wf_mode, parent=self
                )
                self._sub_controller.waterfallUpdated.connect(self._on_waterfall)
                self._sub_controller.iqUpdated.connect(self._on_iq_frame)
                self._sub_controller.failed.connect(self._on_sub_failed)
                self._sub_controller.start()
            except SubDriverError as exc:
                logger.warning("SUB driver open failed: %s", exc)
                self._status_label.setText(
                    self._status_label.text()
                    + f"  (SUB port skipped: {exc})"
                )

        self._connect_btn.setEnabled(False)
        self._disconnect_btn.setEnabled(True)
        self._diag_btn.setEnabled(True)
        self.connectionStateChanged.emit("green")

    # ------------------------------------------------------------------
    # Signal handlers
    # ------------------------------------------------------------------

    def _on_gsi(self, snap: GsiSnapshot) -> None:
        self._mirror.update_snapshot(snap)
        self._meters.update_snapshot(snap)
        # Forward the tuned VC frequency to the I/Q waterfall so its
        # X axis is labelled in MHz instead of relative kHz offsets.
        if snap.frequency_hz:
            self._iq_waterfall.set_center_frequency(float(snap.frequency_hz))
        self.gsiUpdated.emit(snap)

    def _on_glg(self, evt: GlgEvent) -> None:
        self._feed.append_event(evt)
        self.glgUpdated.emit(evt)

    def _on_waterfall(self, frame: WaterfallFrame) -> None:
        self._waterfall.add_frame(frame)
        self.waterfallUpdated.emit(frame)

    def _on_iq_frame(self, frame: IqFrame) -> None:
        self._iq_waterfall.add_frame(frame)
        self.iqUpdated.emit(frame)

    def _on_wf_mode_changed(self, _index: int) -> None:
        mode = self._wf_mode_combo.currentData() or "d"
        # Show the matching widget in the stack.
        if mode == "m":
            self._wf_stack.setCurrentWidget(self._waterfall)
        else:
            self._wf_stack.setCurrentWidget(self._iq_waterfall)
        # Different sample-rate hint for narrow vs wide I/Q.
        self._iq_waterfall.set_sample_rate(960_000.0 if mode == "v" else 16_000.0)
        # Push the new mode into the live controller if connected.
        if self._sub_controller is not None:
            self._sub_controller.set_mode(mode)

    def _on_reset_peak_hold(self) -> None:
        self._iq_waterfall.reset_peak_hold()

    # ------------------------------------------------------------------
    # Diagnostic capture
    # ------------------------------------------------------------------

    def _on_diagnostic_capture(self) -> None:
        """Capture raw GSI / GLG / FFT bytes to a JSON file.

        This bypasses the parser entirely so we can compare what the
        scanner actually emits against what our parser thinks it
        emitted. Use it during a live call to capture receive-state
        data; on idle you'll just get the empty-record stub which is
        still useful for smoke-testing the round trip.
        """
        if self._main_controller is None:
            QMessageBox.information(
                self,
                "Diagnostic capture",
                "Connect the scanner first.",
            )
            return

        default_name = f"sds-capture-{time.strftime('%Y%m%d-%H%M%S')}.json"
        target, _ = QFileDialog.getSaveFileName(
            self,
            "Save scanner diagnostic capture",
            default_name,
            "JSON capture (*.json)",
        )
        if not target:
            return

        capture: dict = {
            "schema": 1,
            "captured_at": time.time(),
            "host": {
                "platform": platform.platform(),
                "python": sys.version.split()[0],
                "executable": sys.executable,
                "pid": os.getpid(),
            },
            "main_port": self._main_combo.currentData(),
            "sub_port": self._sub_combo.currentData(),
            "gsi_samples": [],
            "glg_samples": [],
            "fft_samples": [],
            "errors": [],
        }

        # Pause the polling timers so we don't fight ourselves on the
        # serial bus while capturing. The driver's internal lock would
        # otherwise serialise our diagnostic queries behind the polled
        # ones, which is fine but slow.
        was_main_running = self._main_controller is not None
        was_sub_running = self._sub_controller is not None
        try:
            if was_main_running:
                self._main_controller.stop()
            if was_sub_running:
                self._sub_controller.stop()

            main_driver = self._main_controller.driver
            for i in range(5):
                try:
                    raw_gsi = main_driver.send_query("GSI")
                    snap = main_driver.poll_gsi()
                    capture["gsi_samples"].append({
                        "iteration": i,
                        "raw_bytes_hex": raw_gsi.hex(),
                        "raw_text": raw_gsi.decode("utf-8", errors="replace"),
                        "parsed": {
                            "mode": snap.mode,
                            "system_name": snap.system_name,
                            "department_name": snap.department_name,
                            "tg_name": snap.tg_name,
                            "tgid": snap.tgid,
                            "unit_id": snap.unit_id,
                            "rssi_dbm": snap.rssi_dbm,
                            "signal_pct": snap.signal_pct,
                            "is_receiving": snap.is_receiving,
                            "frequency_hz": snap.frequency_hz,
                            "properties_keys": sorted(snap.properties.keys()),
                        },
                    })
                except Exception as exc:  # noqa: BLE001
                    capture["errors"].append(f"GSI iteration {i}: {exc!r}")
                time.sleep(0.05)

            for i in range(5):
                try:
                    evt = main_driver.poll_glg()
                    capture["glg_samples"].append({
                        "iteration": i,
                        "raw_text": evt.raw,
                        "parsed": {
                            "frq": evt.frq,
                            "mod": evt.mod,
                            "name1": evt.name1,
                            "name2": evt.name2,
                            "name3": evt.name3,
                            "sql": evt.sql,
                            "mut": evt.mut,
                            "sys_tag": evt.sys_tag,
                            "chan_tag": evt.chan_tag,
                            "p25_nac": evt.p25_nac,
                            "is_receiving": evt.is_receiving,
                        },
                    })
                except Exception as exc:  # noqa: BLE001
                    capture["errors"].append(f"GLG iteration {i}: {exc!r}")
                time.sleep(0.05)

            # Probe a few additional read-only commands that are on
            # our docs but not currently surfaced - they may carry
            # the receive-state info we're missing from GSI.
            for cmd in ("STS", "PWR", "MNU", "GLT", "PWR"):
                try:
                    raw = main_driver.send_query(cmd)
                    capture.setdefault("aux_queries", []).append({
                        "cmd": cmd,
                        "raw_text": raw.decode("utf-8", errors="replace"),
                    })
                except Exception as exc:  # noqa: BLE001
                    capture.setdefault("aux_queries", []).append({
                        "cmd": cmd,
                        "error": repr(exc),
                    })

            if was_sub_running and self._sub_controller is not None:
                sub_driver = self._sub_controller.driver
                for i in range(3):
                    try:
                        raw = sub_driver.send_command("m")
                        capture["fft_samples"].append({
                            "iteration": i,
                            "byte_count": len(raw),
                            "raw_text_excerpt": raw.decode(
                                "ascii", errors="replace"
                            )[:1024],
                        })
                    except Exception as exc:  # noqa: BLE001
                        capture["errors"].append(f"FFT iteration {i}: {exc!r}")
                    time.sleep(0.1)
        finally:
            if was_main_running and self._main_controller is not None:
                self._main_controller.start()
            if was_sub_running and self._sub_controller is not None:
                self._sub_controller.start()

        try:
            Path(target).write_text(
                json.dumps(capture, indent=2, sort_keys=True),
                encoding="utf-8",
            )
        except OSError as exc:
            QMessageBox.critical(
                self, "Diagnostic capture", f"Could not write {target}: {exc}"
            )
            return

        logger.info("Diagnostic capture written to %s", target)
        QMessageBox.information(
            self,
            "Diagnostic capture",
            (
                f"Wrote {len(capture['gsi_samples'])} GSI + "
                f"{len(capture['glg_samples'])} GLG + "
                f"{len(capture['fft_samples'])} FFT samples to:\n\n{target}\n\n"
                "Share this file so the parsers can be tuned to your "
                "firmware's actual output."
            ),
        )

    def _on_main_failed(self, message: str) -> None:
        self._status_label.setText(f"MAIN poller stopped: {message}")
        self.connectionStateChanged.emit("yellow")

    def _on_sub_failed(self, message: str) -> None:
        self._status_label.setText(f"SUB poller stopped: {message}")
