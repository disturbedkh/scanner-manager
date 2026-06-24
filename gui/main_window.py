"""Top-level Qt main window for Scanner Manager.

Phase 1 ships the structural shell:

- Top header (device selector, connection LED, FW pill, Update button).
- Central mode stack: Storage (HPDB editor) vs Live (serial mirror + streaming tabs).
- Bottom dock: firmware (hidden; opens as standalone window).
- Menu bar: File, Devices, Tools, Help.

Per-dock content arrives in later phases:

- Phase 2: editor dock (HPDB tree, RR import, coverage)
- Phase 3: live dock (GSI mirror, GLG feed, FFT waterfall)
- Phase 4: streaming dock (audio + telemetry server)
- Phase 5: firmware dock (FTP discovery + update wizard)

The window subscribes to the header's :attr:`HeaderBar.deviceChanged`
signal and, on switch:

1. Calls ``scanner_profiles.set_active_profile(...)`` so the rest of
   the app sees the new profile.
2. Emits :attr:`MainWindow.activeDeviceChanged` for child docks to
   rebuild themselves.
3. Updates per-dock visibility based on the new profile's
   ``supports_*`` flags (e.g. live + streaming docks hide for BT885
   in the current support matrix).
"""

from __future__ import annotations

import logging
import webbrowser
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QDockWidget,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QStackedWidget,
    QStatusBar,
    QTabWidget,
    QWidget,
)

from core.device_manager import Device, DeviceManager
from scanner_profiles import ScannerProfile, set_active_profile

from .devices_dialog import AddDeviceDialog, ManageDevicesDialog
from .dialogs.changes import ChangesPanelDialog
from .dialogs.city_manager import CityManagerDialog
from .dialogs.profile_snapshots import ProfileSnapshotsDialog
from .dialogs.report_issue import ReportIssueDialog
from .dialogs.uniden_tools import UnidenToolsDialog
from .dialogs.update_available import UpdateAvailableDialog
from .dialogs.workspaces import WorkspaceManagerDialog
from .editor.editor_dock import EditorDock
from .firmware.firmware_dock import FirmwareDock
from .header import HeaderBar
from .live.live_dock import LiveDock
from .streaming.streaming_dock import StreamingDock
from .windows import CoverageWindow, FirmwareWindow, LogWindow

logger = logging.getLogger(__name__)

_STORAGE_PAGE = 0
_LIVE_PAGE = 1

# Bumped when the central layout contract changes (About + startup log).
LAYOUT_MODE = "stacked-v2"
LAYOUT_MODE_LABEL = "stacked central (v2)"


class MainWindow(QMainWindow):
    """Multi-scanner manager main window."""

    activeDeviceChanged = Signal(Device, ScannerProfile)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Scanner Manager")
        self.resize(1280, 820)

        self._device_manager = DeviceManager()
        self._current_device: Optional[Device] = None

        self._build_header()
        self._build_docks()
        self._build_menus()
        self._build_status_bar()

        # Now that every dock + listener is wired up, fire the initial
        # device-changed broadcast so the docks pick up the default
        # device on boot.
        self._header.refresh_devices()

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build_header(self) -> None:
        self._header = HeaderBar(self._device_manager, parent=self)
        # Qt main window doesn't have a "top region" outside menus; we
        # add the header as a docked widget pinned to the top with
        # all features disabled so it acts as a fixed header strip.
        header_dock = QDockWidget("", self)
        header_dock.setObjectName("header_dock")
        header_dock.setWidget(self._header)
        header_dock.setFeatures(QDockWidget.NoDockWidgetFeatures)
        header_dock.setTitleBarWidget(QWidget())  # hide title bar
        self.addDockWidget(Qt.TopDockWidgetArea, header_dock)

        self._header.deviceChanged.connect(self._on_device_changed)
        self._header.addDeviceRequested.connect(self._on_add_device)
        self._header.manageDevicesRequested.connect(self._on_manage_devices)
        self._header.updateFirmwareRequested.connect(self._on_update_firmware)
        self._header.connectionModeChanged.connect(self._on_connection_mode_changed)
        self._current_connection_mode = "storage"

    def _build_docks(self) -> None:
        # Storage-mode editor (HPDB tree, coverage, profile side panels).
        self._editor_dock = EditorDock(parent=self)
        self._editor_dock.manageDevicesRequested.connect(self._on_manage_devices)

        # Live-mode surface: serial mirror + streaming tabs (full central width).
        self._live_dock = LiveDock(parent=self)
        self._streaming_dock = StreamingDock(parent=self)
        self._live_dock.connectionStateChanged.connect(
            lambda state: self._header.set_connection_state(state)
        )
        self._live_dock.firmwareDetected.connect(
            lambda main_v, sub_v: self._header.set_firmware_version(main_v or None, sub_v or None)
        )
        self._live_dock.gsiUpdated.connect(self._streaming_dock.push_gsi)
        self._live_dock.glgUpdated.connect(self._streaming_dock.push_glg)
        self._live_dock.waterfallUpdated.connect(self._streaming_dock.push_waterfall)

        live_tabs = QTabWidget()
        live_tabs.setDocumentMode(True)
        live_tabs.addTab(self._live_dock, "Live (Serial Mode)")
        live_tabs.addTab(self._streaming_dock, "Streaming")
        self._live_host = live_tabs

        self._mode_stack = QStackedWidget()
        self._mode_stack.addWidget(self._editor_dock)
        self._mode_stack.addWidget(self._live_host)
        self.setCentralWidget(self._mode_stack)

        # Firmware dock (Phase 5) - bottom
        self._firmware_dock = FirmwareDock(parent=self)
        self._firmware_dock_container = self._wrap_in_dock(
            "Firmware", "firmware_dock", self._firmware_dock
        )
        self.addDockWidget(Qt.BottomDockWidgetArea, self._firmware_dock_container)

        # Log + Coverage are owned but rendered in standalone windows
        # (View > Log window… and Tools > Coverage window…). The log
        # view itself stays a child of the main window when its
        # standalone window is closed, so messages keep accumulating.
        log_widget = QPlainTextEdit()
        log_widget.setReadOnly(True)
        log_widget.setPlaceholderText("App log messages appear here…")
        self._log_view = log_widget
        # Hidden parking widget so the log_view always has a parent.
        self._hidden_log_host = QWidget(self)
        self._hidden_log_host.setVisible(False)
        log_widget.setParent(self._hidden_log_host)
        self._log_window: Optional[LogWindow] = None
        self._coverage_window: Optional[CoverageWindow] = None
        self._firmware_window: Optional[FirmwareWindow] = None

    def _wrap_in_dock(self, title: str, name: str, widget: QWidget) -> QDockWidget:
        dock = QDockWidget(title, self)
        dock.setObjectName(name)
        dock.setWidget(widget)
        dock.setAllowedAreas(Qt.AllDockWidgetAreas)
        return dock

    def _build_menus(self) -> None:
        menubar = self.menuBar()

        file_menu = menubar.addMenu("&File")
        self._save_action = QAction("&Save", self)
        self._save_action.setShortcut(QKeySequence.Save)
        self._save_action.triggered.connect(lambda: self._editor_dock.save_current())
        file_menu.addAction(self._save_action)
        file_menu.addSeparator()
        quit_action = QAction("&Quit", self)
        quit_action.setShortcut(QKeySequence.Quit)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        devices_menu = menubar.addMenu("&Devices")
        add_action = QAction("&Add device…", self)
        add_action.triggered.connect(self._on_add_device)
        devices_menu.addAction(add_action)
        manage_action = QAction("&Manage devices…", self)
        manage_action.triggered.connect(self._on_manage_devices)
        devices_menu.addAction(manage_action)

        view_menu = menubar.addMenu("&View")
        log_window_action = QAction("&Log window…", self)
        log_window_action.triggered.connect(self._on_show_log_window)
        view_menu.addAction(log_window_action)

        tools_menu = menubar.addMenu("&Tools")
        self._firmware_window_action = QAction("&Firmware updater…", self)
        self._firmware_window_action.setShortcut("Ctrl+Shift+F")
        self._firmware_window_action.triggered.connect(self._on_show_firmware_window)
        tools_menu.addAction(self._firmware_window_action)

        coverage_window_action = QAction("&Coverage window…", self)
        coverage_window_action.triggered.connect(self._on_show_coverage_window)
        tools_menu.addAction(coverage_window_action)
        tools_menu.addSeparator()

        workspaces_action = QAction("&Workspaces…", self)
        workspaces_action.triggered.connect(self._on_workspaces)
        tools_menu.addAction(workspaces_action)

        snapshots_action = QAction("Profile &snapshots…", self)
        snapshots_action.triggered.connect(self._on_snapshots)
        tools_menu.addAction(snapshots_action)

        changes_action = QAction("Recent &changes…", self)
        changes_action.triggered.connect(self._on_changes)
        tools_menu.addAction(changes_action)

        city_action = QAction("City / ZIP &overrides…", self)
        city_action.triggered.connect(self._on_city_manager)
        tools_menu.addAction(city_action)

        uniden_action = QAction("&Uniden tools…", self)
        uniden_action.triggered.connect(self._on_uniden_tools)
        tools_menu.addAction(uniden_action)

        help_menu = menubar.addMenu("&Help")
        wiki_action = QAction("Open &Wiki", self)
        wiki_action.triggered.connect(
            lambda: webbrowser.open("https://github.com/disturbedkh/scanner-manager/wiki")
        )
        help_menu.addAction(wiki_action)

        check_updates = QAction("Check for &updates…", self)
        check_updates.triggered.connect(self._on_check_updates)
        help_menu.addAction(check_updates)

        report_action = QAction("&Report issue…", self)
        report_action.triggered.connect(self._on_report_issue)
        help_menu.addAction(report_action)

        about_action = QAction("&About Scanner Manager", self)
        about_action.triggered.connect(self._on_about)
        help_menu.addAction(about_action)

    def _build_status_bar(self) -> None:
        bar = QStatusBar()
        self.setStatusBar(bar)
        bar.showMessage("Ready")

    # ------------------------------------------------------------------
    # Header signal handlers
    # ------------------------------------------------------------------

    def _on_device_changed(self, device: Device) -> None:
        if device is None:
            return
        self._current_device = device
        profile = device.resolve_profile()
        set_active_profile(profile)
        logger.info("Active device -> %s (%s)", device.label, profile.display_name)
        self.statusBar().showMessage(
            f"Active: {profile.display_name} — {device.label}"
        )

        # Reflect the profile's allowed modes on the header switcher,
        # then resolve the device's persisted preference into a concrete
        # mode (clamped to what the profile supports).
        modes = profile.supported_connection_modes()
        self._header.set_supported_connection_modes(modes)
        persisted = (device.connection_mode or "auto").lower()
        if persisted == "auto" or persisted not in modes:
            # Sensible default: serial-capable scanners boot into Live;
            # storage-only scanners (BT885) into Storage.
            persisted = modes[0] if modes else "storage"
        self._header.set_connection_mode(persisted)
        self._current_connection_mode = persisted

        # Push the new device through to docks that care.
        self._editor_dock.set_active_device(device, profile)
        self._live_dock.set_active_profile(profile)
        self._firmware_dock.set_active_device(device, profile)
        self._apply_mode_visibility(profile, persisted)
        self.activeDeviceChanged.emit(device, profile)

    def _on_connection_mode_changed(self, mode: str) -> None:
        """Operator picked Live or Storage from the header switcher."""
        if mode == self._current_connection_mode:
            return
        self._current_connection_mode = mode
        device = self._current_device
        if device is None:
            return
        # Persist the preference per-device.
        device.connection_mode = mode
        try:
            self._device_manager.update_device(device)
        except Exception:
            logger.exception("Could not persist connection_mode for device")

        # Live mode and serial-mode connect can co-exist with storage's
        # editor only by reading the SD card *path*, not by talking to
        # the scanner over USB - the device firmware can only do one or
        # the other at a time. Tear down the active live serial session
        # when entering Storage so the operator can put the scanner into
        # Mass Storage mode without a "port in use" error.
        if mode == "storage":
            try:
                self._live_dock.disconnect()
            except Exception:
                logger.exception("LiveDock.disconnect() failed during mode switch")
        self._apply_mode_visibility(device.resolve_profile(), mode)

    def _apply_mode_visibility(self, profile: ScannerProfile, mode: str) -> None:
        """Swap the central mode stack between Storage and Live surfaces.

        Mutual exclusion rules (mirrors the radio's hardware constraint):

        - **Live mode**: full-width Live + Streaming tabs; HPDB editor hidden.
        - **Storage mode**: full-width HPDB editor; Live surface hidden.
        """
        in_storage = mode == "storage"
        show_storage = in_storage or not profile.supports_serial_mode

        self._mode_stack.setCurrentIndex(
            _STORAGE_PAGE if show_storage else _LIVE_PAGE
        )

        # Firmware bottom dock stays hidden; updater opens from Tools.
        self._firmware_dock_container.setVisible(False)

        if hasattr(self, "_save_action"):
            self._save_action.setEnabled(show_storage)
        if hasattr(self, "_firmware_window_action"):
            self._firmware_window_action.setEnabled(in_storage)

    def _on_add_device(self) -> None:
        dialog = AddDeviceDialog(self._device_manager, parent=self)
        if dialog.exec() == AddDeviceDialog.Accepted:
            new = dialog.created_device
            self._header.refresh_devices()
            if new is not None:
                self._header.select_device(new.id)

    def _on_manage_devices(self) -> None:
        dialog = ManageDevicesDialog(self._device_manager, parent=self)
        dialog.devicesChanged.connect(self._header.refresh_devices)
        dialog.exec()

    def _on_update_firmware(self) -> None:
        # Header "Check for updates…" launches the standalone firmware
        # window. We auto-switch into Storage mode first because the
        # radio's USB cannot serve both the Mass Storage SD card and
        # the CDC serial interface at once - the updater needs the
        # former.
        if self._current_connection_mode != "storage":
            self._header.set_connection_mode("storage")
            self._on_connection_mode_changed("storage")
        self._on_show_firmware_window()

    # ------------------------------------------------------------------
    # Standalone windows (Coverage / Log)
    # ------------------------------------------------------------------

    def _on_show_log_window(self) -> None:
        if self._log_window is not None and self._log_window.isVisible():
            self._log_window.raise_()
            self._log_window.activateWindow()
            return
        # The log_view's parent flips between hidden host and the
        # standalone window; the view itself persists.
        self._log_window = LogWindow(self._log_view, parent=None)
        self._log_window.closed.connect(self._on_log_window_closed)
        self._log_window.show()

    def _on_log_window_closed(self) -> None:
        # Re-attach the view to the hidden host so messages still
        # accumulate without a visible parent.
        self._log_view.setParent(self._hidden_log_host)
        self._log_window = None

    def _on_show_coverage_window(self) -> None:
        if self._coverage_window is not None and self._coverage_window.isVisible():
            self._coverage_window.raise_()
            self._coverage_window.activateWindow()
            return
        coverage_widget = self._editor_dock.coverage_panel()
        self._coverage_window = CoverageWindow(
            coverage_widget,
            original_parent=self._editor_dock,
            parent=None,
        )
        self._coverage_window.closed.connect(self._on_coverage_window_closed)
        self._coverage_window.show()
        # Trigger a refresh so the window has live data on first open.
        self._editor_dock.refresh_coverage()

    def _on_show_firmware_window(self) -> None:
        if self._firmware_window is not None and self._firmware_window.isVisible():
            self._firmware_window.raise_()
            self._firmware_window.activateWindow()
            return
        # Borrow the firmware widget from its hidden bottom dock so its
        # state (selected device, downloaded cache, FTP listing) survives.
        original_parent = self._firmware_dock_container
        self._firmware_window = FirmwareWindow(
            self._firmware_dock,
            original_parent=original_parent,
            parent=None,
        )
        self._firmware_window.closed.connect(self._on_firmware_window_closed)
        self._firmware_window.show()

    def _on_firmware_window_closed(self) -> None:
        self._firmware_window = None
        # The window already re-parented the firmware panel back into
        # its hidden bottom dock; nothing else to do.

    def _on_coverage_window_closed(self) -> None:
        # CoverageWindow already re-parented the panel back to the
        # editor dock in its closeEvent; we just drop the reference.
        self._coverage_window = None
        # If the active profile uses the embedded coverage panel,
        # make sure it's visible in the editor again.
        try:
            if self._current_device:
                p = self._current_device.resolve_profile()
                if p.supports_coverage_simulation:
                    self._editor_dock.coverage_panel().setVisible(True)
        except Exception:
            pass

    def _on_about(self) -> None:
        QMessageBox.about(
            self,
            "About Scanner Manager",
            "<h3>Scanner Manager (Qt rebuild)</h3>"
            "<p>Multi-scanner manager for Uniden SDS100/200 and BearTracker 885.</p>"
            "<p>Phased rebuild on top of the existing scanner_profiles "
            "backend - see <code>Metacache/Dev/MULTI_DEVICE_GUI.md</code>.</p>"
            f"<p><b>Layout:</b> {LAYOUT_MODE_LABEL} ({LAYOUT_MODE})</p>",
        )

    # ------------------------------------------------------------------
    # Tools / Help dialogs
    # ------------------------------------------------------------------

    def _on_workspaces(self) -> None:
        dlg = WorkspaceManagerDialog(parent=self)
        dlg.exec()

    def _on_snapshots(self) -> None:
        if self._current_device is None:
            QMessageBox.information(self, "No device", "Select or add a device first.")
            return
        from pathlib import Path
        card_root = Path(self._current_device.sd_card_path) if self._current_device.sd_card_path else None
        dlg = ProfileSnapshotsDialog(
            scanner_profile_id=self._current_device.scanner_profile_id,
            card_root=card_root,
            parent=self,
        )
        dlg.exec()

    def _on_changes(self) -> None:
        # Pull the active HPD path from the editor dock; if none open,
        # surface the empty-store view so the user still sees the UI.
        active = getattr(self._editor_dock, "current_hpd_path", None)
        path = active() if callable(active) else (active or "")
        dlg = ChangesPanelDialog(hpd_path=path, parent=self)
        dlg.exec()

    def _on_city_manager(self) -> None:
        dlg = CityManagerDialog(parent=self)
        dlg.exec()

    def _on_uniden_tools(self) -> None:
        dlg = UnidenToolsDialog(parent=self)
        dlg.exec()

    def _on_check_updates(self) -> None:
        try:
            from importlib.metadata import PackageNotFoundError, version
            try:
                current = version("beartracker-885-scanner-manager")
            except PackageNotFoundError:
                current = "dev"
        except Exception:
            current = "dev"

        try:
            import core.app_updater as updater
            info = updater.check_for_update(current)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Update check failed: %s", exc)
            info = None

        if info is None:
            mode = UpdateAvailableDialog.MODE_OFFLINE
        elif getattr(info, "version", None) and info.version != current:
            mode = UpdateAvailableDialog.MODE_AVAILABLE
        else:
            mode = UpdateAvailableDialog.MODE_CURRENT
        dlg = UpdateAvailableDialog(
            info=info, current_version=current, mode=mode, parent=self
        )
        dlg.exec()

    def _on_report_issue(self) -> None:
        dlg = ReportIssueDialog(parent=self)
        dlg.exec()

    # ------------------------------------------------------------------
    # Close handling
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        # Allow each dock to abort the close (e.g. unsaved changes).
        for child in (self._editor_dock, self._live_dock, self._streaming_dock):
            close_handler = getattr(child, "request_close", None)
            if callable(close_handler) and not close_handler():
                event.ignore()
                return
        event.accept()
