"""Top-of-window device-selector header.

Sketched in ``AI/Dev/MULTI_DEVICE_GUI.md``::

    +------------------------------------------------------------------+
    | [Uniden SDS100 - Home] [v]   FW: Main 1.26.01 / Sub 1.03.15  [?] |
    |       ^- selector dropdown   ^- live status of connected scanner  |
    +------------------------------------------------------------------+

The combobox lists every Device the user has registered (one or more
:class:`device_manager.Device` rows). Picking a different entry emits
:attr:`HeaderBar.deviceChanged` with the new ``Device``; the main
window listens and rebinds the active scanner profile + rebuilds
the docks.
"""

from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QWidget,
)

from core.device_manager import Device, DeviceManager

logger = logging.getLogger(__name__)


class StatusLight(QWidget):
    """Three-state coloured dot used for the connection LED.

    States:
        - ``"red"``     - no scanner detected
        - ``"yellow"``  - scanner detected on disk but not in serial mode
        - ``"green"``   - scanner reachable on serial port
        - ``"unknown"`` - grey (initial / not applicable)
    """

    _COLORS = {
        "red": QColor("#d9534f"),
        "yellow": QColor("#f0ad4e"),
        "green": QColor("#5cb85c"),
        "unknown": QColor("#999999"),
    }

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._state = "unknown"
        self.setFixedSize(14, 14)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setToolTip("Scanner connection status")

    def set_state(self, state: str, tooltip: Optional[str] = None) -> None:
        if state not in self._COLORS:
            state = "unknown"
        self._state = state
        if tooltip is not None:
            self.setToolTip(tooltip)
        self.update()

    def state(self) -> str:
        return self._state

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt naming)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setBrush(self._COLORS[self._state])
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(1, 1, self.width() - 2, self.height() - 2)
        painter.end()


class ModeSwitcher(QWidget):
    """Segmented Live / Storage selector for the header bar.

    The radio is mutually exclusive between Serial Mode and Mass
    Storage on the hardware side, so this control gates entire
    groups of docks in :class:`gui.main_window.MainWindow`. Buttons
    for unsupported modes (e.g. Live on a BT885) are disabled.
    """

    modeChanged = Signal(str)

    _LABELS = {
        "live": "Live",
        "storage": "Storage",
    }
    _TOOLTIPS = {
        "live": "Live serial mirror (radio in Serial Mode). "
                "Disables editor/firmware - the SD card isn't accessible "
                "while serial is active.",
        "storage": "Mass storage editor + firmware updater. "
                   "Disables live serial - the radio's SD card is mounted "
                   "instead.",
    }

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons = {}
        for mode, label in self._LABELS.items():
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setToolTip(self._TOOLTIPS[mode])
            btn.setProperty("mode_value", mode)
            btn.setMinimumWidth(70)
            btn.clicked.connect(lambda _checked=False, m=mode: self._on_clicked(m))
            self._buttons[mode] = btn
            self._group.addButton(btn)
            layout.addWidget(btn)

        # Match the look of a segmented control.
        self.setStyleSheet(
            """
            QPushButton {
                padding: 4px 10px;
                border: 1px solid #888;
                background: #2a2a2a;
                color: #ddd;
            }
            QPushButton:checked {
                background: #3b78c7;
                color: white;
                border-color: #2c5fa5;
            }
            QPushButton:disabled {
                color: #777;
                background: #222;
            }
            """
        )

    def set_supported_modes(self, modes) -> None:
        """Enable/disable buttons based on the active profile's
        ``supported_connection_modes`` tuple. Must be called before
        :meth:`set_current_mode` to avoid emitting from a disabled mode.
        """
        for mode, btn in self._buttons.items():
            btn.setEnabled(mode in modes)

    def set_current_mode(self, mode: str) -> None:
        """Programmatic select. Does not emit ``modeChanged``."""
        btn = self._buttons.get(mode)
        if btn is None or not btn.isEnabled():
            # Fall back to the first enabled button.
            for fallback in self._buttons.values():
                if fallback.isEnabled():
                    btn = fallback
                    break
        if btn is None:
            return
        was = self.blockSignals(True)
        try:
            btn.setChecked(True)
        finally:
            self.blockSignals(was)

    def current_mode(self) -> str:
        for mode, btn in self._buttons.items():
            if btn.isChecked():
                return mode
        return "storage"

    def _on_clicked(self, mode: str) -> None:
        self.modeChanged.emit(mode)


class HeaderBar(QWidget):
    """The top scanner-selector strip.

    Signals:
        deviceChanged(Device): emitted when the user picks a different
            device from the combobox. The argument is the new
            :class:`device_manager.Device`.
        addDeviceRequested(): user clicked "Add Device".
        manageDevicesRequested(): user clicked "Manage devices".
        updateFirmwareRequested(): user clicked "Update".
    """

    deviceChanged = Signal(Device)
    addDeviceRequested = Signal()
    manageDevicesRequested = Signal()
    updateFirmwareRequested = Signal()
    connectionModeChanged = Signal(str)  # "live" or "storage"

    def __init__(
        self,
        device_manager: DeviceManager,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._dm = device_manager
        self._populating = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(8)

        layout.addWidget(QLabel("Scanner:"))

        self._combo = QComboBox()
        self._combo.setMinimumWidth(280)
        self._combo.currentIndexChanged.connect(self._on_combo_changed)
        layout.addWidget(self._combo, stretch=1)

        self._add_btn = QToolButton()
        self._add_btn.setText("Add…")
        self._add_btn.setToolTip("Add a new scanner / SD card profile")
        self._add_btn.clicked.connect(self.addDeviceRequested.emit)
        layout.addWidget(self._add_btn)

        self._manage_btn = QToolButton()
        self._manage_btn.setText("Manage")
        self._manage_btn.setToolTip("Edit, rename, or remove devices")
        self._manage_btn.clicked.connect(self.manageDevicesRequested.emit)
        layout.addWidget(self._manage_btn)

        # vertical divider
        sep = QWidget()
        sep.setFixedWidth(1)
        sep.setStyleSheet("background-color: #c8c8c8;")
        sep.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        layout.addWidget(sep)

        layout.addWidget(QLabel("Mode:"))
        self._mode_switcher = ModeSwitcher()
        self._mode_switcher.modeChanged.connect(self.connectionModeChanged.emit)
        layout.addWidget(self._mode_switcher)

        sep2 = QWidget()
        sep2.setFixedWidth(1)
        sep2.setStyleSheet("background-color: #c8c8c8;")
        sep2.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        layout.addWidget(sep2)

        self._status_light = StatusLight()
        layout.addWidget(self._status_light)

        self._status_label = QLabel("No device")
        self._status_label.setStyleSheet("color: #555;")
        layout.addWidget(self._status_label)

        layout.addStretch(1)

        self._fw_label = QLabel("FW: —")
        self._fw_label.setStyleSheet("color: #333;")
        layout.addWidget(self._fw_label)

        self._update_btn = QPushButton("Check for updates…")
        self._update_btn.setToolTip("Check Uniden's update server for new firmware / HPDB")
        self._update_btn.clicked.connect(self.updateFirmwareRequested.emit)
        layout.addWidget(self._update_btn)

        # NOTE: callers (MainWindow) must wire signals first, then
        # call refresh_devices() to fire the initial deviceChanged.
        # We populate the combo silently here so the widget shows
        # something while callers finish wiring.
        self._populate_silently()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def refresh_devices(self) -> None:
        """Re-read the device list from disk and repopulate the combo.

        Fires :attr:`deviceChanged` for the new current selection so
        listeners get a fresh snapshot.
        """
        self._populate_silently()
        if self._combo.isEnabled():
            current = self.current_device()
            if current is not None:
                self.deviceChanged.emit(current)

    def _populate_silently(self) -> None:
        """Populate the combo without firing any signals."""
        self._populating = True
        try:
            self._combo.clear()
            devices = self._dm.list_devices()
            if not devices:
                self._combo.addItem(
                    "(No devices configured — click Add…)", userData=None
                )
                self._combo.setEnabled(False)
                self._update_btn.setEnabled(False)
                self._set_status("unknown", "No device configured")
                self._fw_label.setText("FW: —")
                return
            self._combo.setEnabled(True)
            self._update_btn.setEnabled(True)
            for d in devices:
                profile = d.resolve_profile()
                label = f"{profile.display_name} — {d.label}"
                self._combo.addItem(label, userData=d.id)
            default = self._dm.get_default()
            if default is not None:
                idx = next(
                    (
                        i
                        for i in range(self._combo.count())
                        if self._combo.itemData(i) == default.id
                    ),
                    0,
                )
                self._combo.setCurrentIndex(idx)
        finally:
            self._populating = False

    def current_device(self) -> Optional[Device]:
        device_id = self._combo.currentData()
        if not device_id:
            return None
        return self._dm.get_device(device_id)

    def select_device(self, device_id: str) -> None:
        """Programmatically switch to a device. No-op if unknown."""
        for i in range(self._combo.count()):
            if self._combo.itemData(i) == device_id:
                self._combo.setCurrentIndex(i)
                return

    def set_connection_state(
        self, state: str, summary: Optional[str] = None
    ) -> None:
        """Update the LED + status text. Called by the live-mode driver."""
        self._set_status(state, summary or self._default_status_text(state))

    def set_supported_connection_modes(self, modes) -> None:
        """Forward to the mode switcher: greys out modes the active
        profile doesn't support.
        """
        self._mode_switcher.set_supported_modes(modes)

    def set_connection_mode(self, mode: str) -> None:
        """Programmatically pick a mode (no signal emitted)."""
        self._mode_switcher.set_current_mode(mode)

    def current_connection_mode(self) -> str:
        return self._mode_switcher.current_mode()

    def set_firmware_version(
        self, main_version: Optional[str] = None, sub_version: Optional[str] = None
    ) -> None:
        if not main_version and not sub_version:
            self._fw_label.setText("FW: —")
        elif sub_version and main_version:
            self._fw_label.setText(f"FW: Main {main_version} / Sub {sub_version}")
        elif main_version:
            self._fw_label.setText(f"FW: {main_version}")
        else:
            self._fw_label.setText(f"FW: Sub {sub_version}")

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _on_combo_changed(self, _index: int) -> None:
        if self._populating:
            return
        device = self.current_device()
        if device is not None:
            logger.debug("HeaderBar device changed -> %s", device.label)
            self.deviceChanged.emit(device)

    def _set_status(self, state: str, text: str) -> None:
        self._status_light.set_state(state, text)
        self._status_label.setText(text)

    @staticmethod
    def _default_status_text(state: str) -> str:
        return {
            "red": "Scanner not detected",
            "yellow": "SD card mounted (not in serial mode)",
            "green": "Scanner connected (serial mode)",
            "unknown": "Status unknown",
        }.get(state, "Status unknown")
