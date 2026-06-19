"""Entry / group / system edit dialogs.

Each dialog exposes the same fields the legacy Tk app's
``EntryEditDialog`` / ``GroupEditDialog`` / ``SystemEditDialog`` did,
but as PySide6 widgets. They write back through the existing
``HpdFile.edit_entry`` / ``edit_group`` API so the persistence path
is unchanged - both the new Qt app and the legacy Tk app produce
identical files on disk.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from scanner_profiles import ScannerProfile


class EntryEditDialog(QDialog):
    """Edit a single C-Freq or TGID entry in place.

    The dialog is built dynamically off the entry type so the
    frequency-vs-TGID + tone field switch happens automatically.
    """

    def __init__(
        self,
        entry,
        hpd_file,
        profile: ScannerProfile,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._entry = entry
        self._hpd_file = hpd_file
        self._profile = profile

        self.setWindowTitle(f"Edit entry — {entry.name or '(unnamed)'}")
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)

        info = QLabel(
            f"<b>System:</b> {entry.system_name}<br>"
            f"<b>Group:</b> {entry.group_name}<br>"
            f"<b>Type:</b> {entry.entry_type}"
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        form = QFormLayout()

        self._name_edit = QLineEdit(entry.name or "")
        form.addRow("Name:", self._name_edit)

        if entry.entry_type == "C-Freq":
            self._freq_spin = QDoubleSpinBox()
            self._freq_spin.setRange(0.0, 9999.99999)
            self._freq_spin.setDecimals(5)
            self._freq_spin.setSuffix(" MHz")
            current_hz_str = entry.record.get_field(5, "")
            try:
                self._freq_spin.setValue(int(current_hz_str) / 1e6)
            except (TypeError, ValueError):
                self._freq_spin.setValue(0.0)
            form.addRow("Frequency:", self._freq_spin)

            self._mode_combo = QComboBox()
            self._mode_combo.addItems(["FM", "NFM", "AM", "AUTO"])
            current_mode = entry.record.get_field(6, "AUTO")
            idx = self._mode_combo.findText(current_mode)
            if idx >= 0:
                self._mode_combo.setCurrentIndex(idx)
            form.addRow("Mode:", self._mode_combo)

            self._tone_edit = QLineEdit(entry.record.get_field(7, ""))
            self._tone_edit.setPlaceholderText("CTCSS / DCS, e.g. 100.0 or D023N (blank = none)")
            form.addRow("Tone / NAC:", self._tone_edit)
        else:
            self._tgid_spin = QSpinBox()
            self._tgid_spin.setRange(0, 0xFFFFFF)
            try:
                self._tgid_spin.setValue(int(entry.record.get_field(5, "0")))
            except (TypeError, ValueError):
                self._tgid_spin.setValue(0)
            form.addRow("TGID:", self._tgid_spin)

            self._mode_combo = QComboBox()
            self._mode_combo.addItems(["ALL", "ANALOG", "DIGITAL"])
            current_mode = (entry.record.get_field(6, "ALL") or "ALL").upper()
            idx = self._mode_combo.findText(current_mode)
            if idx >= 0:
                self._mode_combo.setCurrentIndex(idx)
            form.addRow("Mode:", self._mode_combo)

        # Service-type dropdown driven by the active profile
        self._service_combo = QComboBox()
        for sid, label in sorted(profile.service_types.items()):
            self._service_combo.addItem(f"{sid} — {label}", userData=sid)
        # Pick the current value
        for i in range(self._service_combo.count()):
            if self._service_combo.itemData(i) == entry.service_type:
                self._service_combo.setCurrentIndex(i)
                break
        form.addRow("Service type:", self._service_combo)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_save(self) -> None:
        try:
            name = self._name_edit.text().strip()
            if not name:
                QMessageBox.warning(self, "Edit entry", "Name can't be blank.")
                return

            if self._entry.entry_type == "C-Freq":
                freq_hz = int(round(self._freq_spin.value() * 1e6))
                if freq_hz <= 0:
                    QMessageBox.warning(self, "Edit entry", "Frequency must be > 0.")
                    return
                self._hpd_file.edit_entry(
                    self._entry,
                    name=name,
                    identity_value=str(freq_hz),
                    mode=self._mode_combo.currentText(),
                    tone=self._tone_edit.text().strip(),
                )
            else:
                self._hpd_file.edit_entry(
                    self._entry,
                    name=name,
                    identity_value=str(self._tgid_spin.value()),
                    mode=self._mode_combo.currentText(),
                )

            new_service = self._service_combo.currentData()
            if new_service is not None and new_service != self._entry.service_type:
                self._hpd_file.update_service_type(self._entry, int(new_service))

            self.accept()
        except Exception as exc:
            QMessageBox.critical(self, "Edit entry failed", str(exc))


class GroupEditDialog(QDialog):
    """Edit a single C-Group or T-Group's name + geo metadata."""

    def __init__(
        self,
        group,
        hpd_file,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._group = group
        self._hpd_file = hpd_file

        self.setWindowTitle(f"Edit group — {group.name or '(unnamed)'}")
        self.setMinimumWidth(380)

        layout = QVBoxLayout(self)

        form = QFormLayout()

        self._name_edit = QLineEdit(group.name or "")
        form.addRow("Name:", self._name_edit)

        self._lat_spin = QDoubleSpinBox()
        self._lat_spin.setRange(-90.0, 90.0)
        self._lat_spin.setDecimals(6)
        self._lat_spin.setSuffix("°")
        if group.lat is not None:
            self._lat_spin.setValue(group.lat)
        form.addRow("Latitude:", self._lat_spin)

        self._lon_spin = QDoubleSpinBox()
        self._lon_spin.setRange(-180.0, 180.0)
        self._lon_spin.setDecimals(6)
        self._lon_spin.setSuffix("°")
        if group.lon is not None:
            self._lon_spin.setValue(group.lon)
        form.addRow("Longitude:", self._lon_spin)

        self._range_spin = QDoubleSpinBox()
        self._range_spin.setRange(0.0, 9999.0)
        self._range_spin.setDecimals(1)
        self._range_spin.setSuffix(" mi")
        if group.range_miles is not None:
            self._range_spin.setValue(group.range_miles)
        form.addRow("Range:", self._range_spin)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_save(self) -> None:
        try:
            self._hpd_file.edit_group(
                self._group,
                name=self._name_edit.text().strip() or None,
                lat=self._lat_spin.value() or None,
                lon=self._lon_spin.value() or None,
                range_miles=self._range_spin.value() or None,
            )
            self.accept()
        except Exception as exc:
            QMessageBox.critical(self, "Edit group failed", str(exc))


class BulkServiceTypeDialog(QDialog):
    """Apply a single service-type to every entry under a group / system.

    Mirrors the right-click "Apply service type to all entries" context
    menu in the legacy Tk app.
    """

    def __init__(
        self,
        target_label: str,
        profile: ScannerProfile,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._profile = profile
        self.setWindowTitle("Apply service type")
        self.setMinimumWidth(320)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Apply service type to:\n{target_label}"))

        self._service_combo = QComboBox()
        for sid, label in sorted(profile.service_types.items()):
            self._service_combo.addItem(f"{sid} — {label}", userData=sid)
        layout.addWidget(self._service_combo)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Apply | QDialogButtonBox.Cancel
        )
        apply_btn = buttons.button(QDialogButtonBox.Apply)
        apply_btn.clicked.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_service_type(self) -> Optional[int]:
        return self._service_combo.currentData()
