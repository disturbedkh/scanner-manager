"""Add / manage devices wizard.

Two dialogs live in this module:

- :class:`AddDeviceDialog` - new-device wizard. Asks the user to pick
  a scanner type, name the device, and optionally bind it to an SD
  card folder (with auto-detection of the scanner family from the
  card if the user picks one).
- :class:`ManageDevicesDialog` - simple table editor for renaming,
  rebinding, or removing existing devices.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from device_manager import Device, DeviceManager
from scanner_profiles import detect_from_card, list_profiles

logger = logging.getLogger(__name__)


class AddDeviceDialog(QDialog):
    """Wizard: pick scanner type + name + optional SD card path."""

    def __init__(
        self,
        device_manager: DeviceManager,
        parent: Optional[QWidget] = None,
        prefill_path: Optional[str] = None,
    ) -> None:
        super().__init__(parent)
        self._dm = device_manager
        self._created_device: Optional[Device] = None

        self.setWindowTitle("Add Scanner Device")
        self.setMinimumWidth(480)

        layout = QVBoxLayout(self)
        intro = QLabel(
            "A scanner device pairs a model (SDS100/200, BearTracker 885) with\n"
            "an optional SD card path. You can register the same scanner under\n"
            "multiple device entries (e.g. 'Home' vs 'Roadtrip')."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #555;")
        layout.addWidget(intro)

        form = QFormLayout()

        self._profile_combo = QComboBox()
        for p in list_profiles():
            self._profile_combo.addItem(p.display_name, userData=p.id)
        form.addRow("Scanner model:", self._profile_combo)

        self._label_edit = QLineEdit()
        self._label_edit.setPlaceholderText("e.g. Truck, Home, Roadtrip")
        form.addRow("Friendly name:", self._label_edit)

        path_row = QHBoxLayout()
        self._path_edit = QLineEdit()
        self._path_edit.setPlaceholderText("Optional - SD card folder (BCDx36HP/...)")
        if prefill_path:
            self._path_edit.setText(prefill_path)
        path_row.addWidget(self._path_edit, stretch=1)
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._on_browse)
        path_row.addWidget(browse_btn)
        path_widget = QWidget()
        path_widget.setLayout(path_row)
        form.addRow("SD card folder:", path_widget)

        layout.addLayout(form)

        self._detect_label = QLabel("")
        self._detect_label.setStyleSheet("color: #2c662d; font-style: italic;")
        layout.addWidget(self._detect_label)

        self._path_edit.textChanged.connect(self._maybe_autodetect)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        if prefill_path:
            self._maybe_autodetect(prefill_path)

    @property
    def created_device(self) -> Optional[Device]:
        return self._created_device

    def _on_browse(self) -> None:
        start = self._path_edit.text() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(
            self,
            "Select scanner SD card folder (root, or BCDx36HP/...)",
            start,
        )
        if chosen:
            self._path_edit.setText(chosen)

    def _maybe_autodetect(self, path: str) -> None:
        path = path.strip()
        if not path:
            self._detect_label.setText("")
            return
        try:
            profile = detect_from_card(path)
        except Exception as exc:
            logger.warning("detect_from_card failed: %s", exc)
            profile = None
        if profile is None:
            self._detect_label.setText("(card not recognized — pick the model manually)")
            self._detect_label.setStyleSheet("color: #b22222; font-style: italic;")
            return
        # Update combo to the detected profile + show success
        for i in range(self._profile_combo.count()):
            if self._profile_combo.itemData(i) == profile.id:
                self._profile_combo.setCurrentIndex(i)
                break
        self._detect_label.setText(f"Detected: {profile.display_name}")
        self._detect_label.setStyleSheet("color: #2c662d; font-style: italic;")

    def _on_accept(self) -> None:
        profile_id = self._profile_combo.currentData()
        label = self._label_edit.text().strip()
        path = self._path_edit.text().strip() or None

        if not profile_id:
            QMessageBox.warning(self, "Add Device", "Pick a scanner model.")
            return
        if not label:
            QMessageBox.warning(self, "Add Device", "Give this device a friendly name.")
            return

        device = Device.make(
            scanner_profile_id=profile_id,
            label=label,
            sd_card_path=path,
        )
        if path:
            device.update_seen()
        self._dm.add_device(device)
        self._created_device = device
        self.accept()


class ManageDevicesDialog(QDialog):
    """Table editor: rename, rebind, remove devices."""

    devicesChanged = Signal()

    def __init__(self, device_manager: DeviceManager, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._dm = device_manager

        self.setWindowTitle("Manage Devices")
        self.setMinimumSize(640, 320)

        layout = QVBoxLayout(self)

        self._table = QTableWidget()
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels(["Name", "Model", "SD card", "Last seen"])
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self._table)

        btn_row = QHBoxLayout()
        rename_btn = QPushButton("Rename…")
        rename_btn.clicked.connect(self._on_rename)
        btn_row.addWidget(rename_btn)

        rebind_btn = QPushButton("Set SD card folder…")
        rebind_btn.clicked.connect(self._on_rebind)
        btn_row.addWidget(rebind_btn)

        remove_btn = QPushButton("Remove")
        remove_btn.clicked.connect(self._on_remove)
        btn_row.addWidget(remove_btn)

        btn_row.addStretch(1)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)

        layout.addLayout(btn_row)

        self._refresh()

    def _refresh(self) -> None:
        devices = self._dm.list_devices()
        self._table.setRowCount(len(devices))
        for row, d in enumerate(devices):
            profile = d.resolve_profile()
            for col, value in enumerate(
                (d.label, profile.display_name, d.sd_card_path or "—", d.last_seen or "—")
            ):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, d.id)
                self._table.setItem(row, col, item)
        self._table.resizeColumnsToContents()

    def _selected_device(self) -> Optional[Device]:
        items = self._table.selectedItems()
        if not items:
            return None
        device_id = items[0].data(Qt.UserRole)
        return self._dm.get_device(device_id)

    def _on_rename(self) -> None:
        device = self._selected_device()
        if not device:
            return
        from PySide6.QtWidgets import QInputDialog
        new_name, ok = QInputDialog.getText(
            self, "Rename device", "New friendly name:", text=device.label
        )
        if not ok or not new_name.strip():
            return
        device.label = new_name.strip()
        self._dm.update_device(device)
        self._refresh()
        self.devicesChanged.emit()

    def _on_rebind(self) -> None:
        device = self._selected_device()
        if not device:
            return
        start = device.sd_card_path or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(
            self, f"Set SD card folder for {device.label}", start
        )
        if not chosen:
            return
        device.sd_card_path = chosen
        device.update_seen()
        self._dm.update_device(device)
        self._refresh()
        self.devicesChanged.emit()

    def _on_remove(self) -> None:
        device = self._selected_device()
        if not device:
            return
        confirm = QMessageBox.question(
            self,
            "Remove device",
            f"Remove '{device.label}' from the device list?\n\n"
            "This does not delete any SD card files - only the manager entry.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        self._dm.remove_device(device.id)
        self._refresh()
        self.devicesChanged.emit()
