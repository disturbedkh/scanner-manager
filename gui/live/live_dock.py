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

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from scanner_drivers.serial_main import (
    GlgEvent,
    GsiSnapshot,
    MainDriverError,
    SerialMainDriver,
)
from scanner_drivers.serial_sub import (
    IqFrame,
    SerialSubDriver,
    SubDriverError,
    WaterfallFrame,
)
from scanner_drivers.usb_detect import (
    enumerate_ports,
    find_ports_for_profile,
)
from scanner_profiles import ScannerProfile

from .controllers import MainPollerController, SubPollerController
from .virtual_scanner import VirtualScannerPanel
from .widgets import (
    GlgFeedWidget,
    GsiMirrorWidget,
    IqWaterfallWidget,
    MetersWidget,
    WaterfallWidget,
)

logger = logging.getLogger(__name__)

_DIAG_CAPTURE_TITLE = "Diagnostic capture"
_PORT_REFRESH_DEBOUNCE_MS = 300


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
        self._port_refresh_timer = QTimer(self)
        self._port_refresh_timer.setSingleShot(True)
        self._port_refresh_timer.setInterval(_PORT_REFRESH_DEBOUNCE_MS)
        self._port_refresh_timer.timeout.connect(self._on_port_refresh_timer)
        self._port_refresh_rescheduled = False
        self._build_ui()
        self._set_unsupported_message()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_active_profile(self, profile: ScannerProfile) -> None:
        self._profile = profile
        if not profile.supports_serial_mode:
            self._port_refresh_timer.stop()
            self._port_refresh_rescheduled = False
            self.disconnect()
            self._set_unsupported_message()
            return
        self._set_supported_message()
        self._schedule_refresh_ports()

    def _schedule_refresh_ports(self) -> None:
        """Debounce port enumeration on rapid profile switches.

        The first switch in a burst refreshes immediately; further switches
        within ``_PORT_REFRESH_DEBOUNCE_MS`` coalesce into one trailing refresh.
        """
        if self._port_refresh_timer.isActive():
            self._port_refresh_rescheduled = True
            self._port_refresh_timer.stop()
        else:
            self.refresh_ports()
        self._port_refresh_timer.start()

    def _on_port_refresh_timer(self) -> None:
        if self._port_refresh_rescheduled:
            self.refresh_ports()
        self._port_refresh_rescheduled = False

    def _on_manual_refresh(self) -> None:
        """Refresh ports immediately; cancel any pending debounced refresh."""
        self._port_refresh_timer.stop()
        self._port_refresh_rescheduled = False
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

        self._main_combo = QComboBox()
        self._main_combo.setMinimumWidth(120)
        self._main_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._sub_combo = QComboBox()
        self._sub_combo.setMinimumWidth(120)
        self._sub_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.clicked.connect(self._on_manual_refresh)
        self._connect_btn = QPushButton("Connect")
        self._connect_btn.clicked.connect(self._on_connect_clicked)
        self._disconnect_btn = QPushButton("Disconnect")
        self._disconnect_btn.setEnabled(False)
        self._disconnect_btn.clicked.connect(self.disconnect)
        self._diag_btn = QPushButton("Diagnostic capture…")
        self._diag_btn.setEnabled(False)
        self._diag_btn.setToolTip(
            "Capture raw GSI/GLG/FFT bytes from the live drivers to a "
            "JSON file. Click during an active call so the capture "
            "contains receive-state data."
        )
        self._diag_btn.clicked.connect(self._on_diagnostic_capture)

        controls = QWidget()
        grid = QGridLayout(controls)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(4)
        grid.addWidget(QLabel("MAIN port:"), 0, 0)
        grid.addWidget(self._main_combo, 0, 1)
        grid.addWidget(QLabel("SUB port:"), 0, 2)
        grid.addWidget(self._sub_combo, 0, 3)
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        for btn in (
            self._refresh_btn,
            self._connect_btn,
            self._disconnect_btn,
            self._diag_btn,
        ):
            btn_row.addWidget(btn)
        btn_row.addStretch(1)
        grid.addLayout(btn_row, 1, 0, 1, 4)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        layout.addWidget(controls)

        self._status_label = QLabel("")
        self._status_label.setWordWrap(True)
        self._status_label.setStyleSheet("color: #555;")
        layout.addWidget(self._status_label)

        # Two inner tabs under the shared connection header:
        #
        #   Live - Control     -> the virtual scanner faceplate
        #   Live - Monitoring  -> GSI + Signal + recent calls + waterfall
        self._live_tabs = QTabWidget()
        self._live_tabs.setDocumentMode(True)
        self._live_tabs.addTab(self._build_control_page(), "Live - Control")
        self._live_tabs.addTab(self._build_monitoring_page(), "Live - Monitoring")
        layout.addWidget(self._live_tabs, stretch=1)

    def _build_control_page(self) -> QWidget:
        """The virtual scanner faceplate, centred so the keypad keeps a
        sensible width on wide windows."""
        self._control = VirtualScannerPanel()
        self._control.setMaximumWidth(960)
        self._control.statusMessage.connect(self._status_label.setText)

        page = QWidget()
        row = QHBoxLayout(page)
        row.setContentsMargins(0, 0, 0, 0)
        row.addStretch(1)
        row.addWidget(self._control)
        row.addStretch(1)
        return page

    def _build_monitoring_page(self) -> QWidget:
        """Passive displays: GSI state + Signal, recent calls, and the
        spectrum / waterfall stack - vertically resizable."""
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

        # Peak/Max-hold decay window (mirrors the native scanner's
        # "Set Max Hold Time": 3 s / 10 s / Infinite). Default Infinite.
        wf_toolbar.addWidget(QLabel("Max hold:"))
        self._wf_maxhold_combo = QComboBox()
        self._wf_maxhold_combo.addItem("Infinite", None)
        self._wf_maxhold_combo.addItem("10 s", 10.0)
        self._wf_maxhold_combo.addItem("3 s", 3.0)
        self._wf_maxhold_combo.currentIndexChanged.connect(self._on_max_hold_changed)
        wf_toolbar.addWidget(self._wf_maxhold_combo)

        wf_toolbar.addStretch(1)
        wf_layout.addLayout(wf_toolbar)

        self._iq_waterfall = IqWaterfallWidget(sample_rate_hz=16_000.0)
        self._waterfall = WaterfallWidget()

        self._wf_stack = QStackedWidget()
        self._wf_stack.addWidget(self._iq_waterfall)   # index 0 (default)
        self._wf_stack.addWidget(self._waterfall)      # index 1
        wf_layout.addWidget(self._wf_stack, stretch=1)

        self._mirror = GsiMirrorWidget()
        self._meters = MetersWidget()
        self._feed = GlgFeedWidget()

        # 2x2 grid built from nested splitters (all axes user-resizable):
        #
        #   +-----------------+--------------------------+
        #   | GSI mirror      | Spectrum / waterfall      |
        #   +-----------------+--------------------------+
        #   | Recent calls    | Signal meters             |
        #   +-----------------+--------------------------+
        top_row = QSplitter(Qt.Horizontal)
        top_row.addWidget(self._mirror)
        top_row.addWidget(wf_box)
        top_row.setStretchFactor(0, 1)
        top_row.setStretchFactor(1, 2)
        top_row.setHandleWidth(6)

        bottom_row = QSplitter(Qt.Horizontal)
        bottom_row.addWidget(self._feed)
        bottom_row.addWidget(self._meters)
        bottom_row.setStretchFactor(0, 2)
        bottom_row.setStretchFactor(1, 1)
        bottom_row.setHandleWidth(6)

        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(top_row)
        splitter.addWidget(bottom_row)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setHandleWidth(6)

        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.addWidget(splitter)
        return page

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

    def _populate_port_combo(
        self, combo, all_ports, default_port
    ) -> None:
        for port in all_ports:
            tag = (
                " (detected)"
                if default_port and port.device == default_port.device
                else ""
            )
            combo.addItem(
                f"{port.device} - {port.description}{tag}",
                userData=port.device,
            )
        if default_port is not None:
            idx = combo.findData(default_port.device)
            if idx >= 0:
                combo.setCurrentIndex(idx)

    def _update_port_discovery_status(
        self, all_ports, matched
    ) -> None:
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

    def refresh_ports(self) -> None:
        if self._profile is None:
            return
        all_ports = enumerate_ports()
        matched = find_ports_for_profile(self._profile)

        self._main_combo.clear()
        self._sub_combo.clear()

        for combo, default_port, _label in (
            (self._main_combo, matched.main, "MAIN"),
            (self._sub_combo, matched.sub, "SUB"),
        ):
            self._populate_port_combo(combo, all_ports, default_port)

        self._update_port_discovery_status(all_ports, matched)

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
        self._main_controller.stsUpdated.connect(self._on_sts)
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
        self._control.update_gsi(snap)
        # Forward the tuned VC frequency to the I/Q waterfall so its
        # X axis is labelled in MHz instead of relative kHz offsets.
        if snap.frequency_hz:
            self._iq_waterfall.set_center_frequency(float(snap.frequency_hz))
        self.gsiUpdated.emit(snap)

    def _on_sts(self, snap) -> None:
        self._control.update_screen(snap)

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
        # Show the matching widget in the stack, clearing the target
        # widget's history so a previous source doesn't bleed across.
        if mode == "m":
            self._waterfall.reset_history()
            self._wf_stack.setCurrentWidget(self._waterfall)
        else:
            self._wf_stack.setCurrentWidget(self._iq_waterfall)
        # Different sample-rate hint for narrow vs wide I/Q. Note that
        # set_sample_rate() also resets the I/Q widget's history so the
        # peak-hold trace from the previous bandwidth can't stick.
        self._iq_waterfall.set_sample_rate(960_000.0 if mode == "v" else 16_000.0)
        # Push the new mode into the live controller if connected.
        if self._sub_controller is not None:
            self._sub_controller.set_mode(mode)

    def _on_reset_peak_hold(self) -> None:
        self._iq_waterfall.reset_peak_hold()

    def _on_max_hold_changed(self, _index: int) -> None:
        self._iq_waterfall.set_max_hold_time(self._wf_maxhold_combo.currentData())

    # ------------------------------------------------------------------
    # Diagnostic capture
    # ------------------------------------------------------------------

    def _fill_diagnostic_capture(
        self, capture: dict, main_driver, sub_driver
    ) -> None:
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

        if sub_driver is not None:
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
                _DIAG_CAPTURE_TITLE,
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
            sub_driver = (
                self._sub_controller.driver
                if was_sub_running and self._sub_controller is not None
                else None
            )
            self._fill_diagnostic_capture(capture, main_driver, sub_driver)
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
                self, _DIAG_CAPTURE_TITLE, f"Could not write {target}: {exc}"
            )
            return

        logger.info("Diagnostic capture written to %s", target)
        QMessageBox.information(
            self,
            _DIAG_CAPTURE_TITLE,
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
