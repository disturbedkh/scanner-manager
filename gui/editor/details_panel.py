"""Right-side details panels for the editor dock.

Profile-specific surfaces:

- :class:`Bt885DetailsPanel` — legacy Tk parity (inline service-type
  change, button help text, hardware-button wording).
- :class:`HpdbDetailsPanel` — SDS / general HPDB editing (plain
  category labels, no button semantics).
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from scanner_profiles import ScannerProfile

from .display_helpers import bulk_action_label, format_service_type_details
from .entry_dialog import (
    Bt885BulkServiceTypeDialog,
    Bt885EntryEditDialog,
    GroupEditDialog,
    HpdbBulkCategoryDialog,
    HpdbEntryEditDialog,
)


class BaseDetailsPanel(QWidget):
    """Shared chrome for profile-specific details panels."""

    entryEdited = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._profile: Optional[ScannerProfile] = None
        self._payload: Optional[dict] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self._title = QLabel("Select a node in the tree")
        font = self._title.font()
        font.setPointSize(font.pointSize() + 1)
        font.setBold(True)
        self._title.setFont(font)
        layout.addWidget(self._title)

        self._info_box = QGroupBox("Details")
        self._info_form = QFormLayout(self._info_box)
        layout.addWidget(self._info_box)

        self._actions_widget = QWidget()
        actions_layout = QHBoxLayout(self._actions_widget)
        actions_layout.setContentsMargins(0, 0, 0, 0)

        self._edit_button = QPushButton("Edit…")
        self._edit_button.clicked.connect(self._on_edit_clicked)
        actions_layout.addWidget(self._edit_button)

        self._bulk_button = QPushButton("Apply service type to all…")
        self._bulk_button.clicked.connect(self._on_bulk_service_clicked)
        actions_layout.addWidget(self._bulk_button)

        self._delete_button = QPushButton("Delete")
        self._delete_button.setStyleSheet("color: #b22222;")
        self._delete_button.clicked.connect(self._on_delete_clicked)
        actions_layout.addWidget(self._delete_button)

        actions_layout.addStretch(1)
        layout.addWidget(self._actions_widget)

        self._help_label = QLabel("")
        self._help_label.setWordWrap(True)
        self._help_label.setStyleSheet("color: #555555;")
        self._help_label.setVisible(False)
        layout.addWidget(self._help_label)

        layout.addStretch(1)

        self._actions_widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self._reset()

    def set_profile(self, profile: ScannerProfile) -> None:
        self._profile = profile
        self._bulk_button.setText(bulk_action_label(profile))
        if profile is not None:
            help_text = profile.service_type_help_text().strip()
            self._help_label.setText(help_text)
            self._help_label.setVisible(bool(help_text))
        else:
            self._help_label.clear()
            self._help_label.setVisible(False)
        if self._payload:
            self.show_entry(self._payload)

    def show_entry(self, payload: Optional[dict]) -> None:
        self._payload = payload
        self._reset()
        if not isinstance(payload, dict):
            return

        kind = payload.get("kind")
        if kind == "entry":
            self._show_entry(payload)
        elif kind == "group":
            self._show_group(payload)
        elif kind == "system":
            self._show_system(payload)
        elif kind == "site":
            self._show_site(payload)
        elif kind == "file":
            self._show_file(payload)

    def _show_entry(self, payload: dict) -> None:
        raise NotImplementedError

    def _show_group(self, payload: dict) -> None:
        group = payload["group"]
        self._title.setText(group.name or "(unnamed group)")
        self._info_form.addRow("Type:", QLabel(group.group_type or "—"))
        self._info_form.addRow("System:", QLabel(group.system_name or "—"))
        self._info_form.addRow(
            "Latitude:",
            QLabel(f"{group.lat:.6f}°" if group.lat is not None else "—"),
        )
        self._info_form.addRow(
            "Longitude:",
            QLabel(f"{group.lon:.6f}°" if group.lon is not None else "—"),
        )
        self._info_form.addRow(
            "Range:",
            QLabel(
                f"{group.range_miles:.1f} mi"
                if group.range_miles is not None
                else "—"
            ),
        )
        self._info_form.addRow("Entries:", QLabel(str(len(group.entries))))

        self._edit_button.setEnabled(True)
        self._bulk_button.setEnabled(True)
        self._delete_button.setEnabled(False)

    def _show_system(self, payload: dict) -> None:
        system = payload["system"]
        self._title.setText(system.name or "(unnamed system)")
        self._info_form.addRow("Type:", QLabel(system.system_type or "—"))
        self._info_form.addRow("Area records:", QLabel(str(len(system.area_records))))
        self._info_form.addRow(
            "States:",
            QLabel(", ".join(map(str, sorted(system.state_ids))) or "—"),
        )
        self._info_form.addRow(
            "Counties:",
            QLabel(", ".join(map(str, sorted(system.county_ids))) or "—"),
        )
        self._info_form.addRow("Groups:", QLabel(str(len(system.groups))))
        self._info_form.addRow("Sites:", QLabel(str(len(system.sites))))

        self._edit_button.setEnabled(False)
        self._bulk_button.setEnabled(True)
        self._delete_button.setEnabled(False)

    def _show_site(self, payload: dict) -> None:
        site = payload["site"]
        self._title.setText(f"Site: {site.name}")
        self._info_form.addRow("Site ID:", QLabel(site.site_id or "—"))
        self._info_form.addRow(
            "Latitude:", QLabel(f"{site.lat:.6f}°" if site.lat is not None else "—")
        )
        self._info_form.addRow(
            "Longitude:", QLabel(f"{site.lon:.6f}°" if site.lon is not None else "—")
        )
        self._info_form.addRow(
            "Range:",
            QLabel(
                f"{site.range_miles:.1f} mi"
                if site.range_miles is not None
                else "—"
            ),
        )
        self._info_form.addRow("Frequencies:", QLabel(str(len(site.freqs))))

        self._edit_button.setEnabled(False)
        self._bulk_button.setEnabled(False)
        self._delete_button.setEnabled(False)

    def _show_file(self, payload: dict) -> None:
        hpd_file = payload["hpd_file"]
        path = payload.get("path", "")
        sys_count = len(hpd_file.systems)
        entry_count = sum(
            len(g.entries) for s in hpd_file.systems for g in s.groups
        )

        self._title.setText("HPDB state file")
        self._info_form.addRow("Path:", QLabel(path or "—"))
        self._info_form.addRow("Systems:", QLabel(str(sys_count)))
        self._info_form.addRow("Entries:", QLabel(str(entry_count)))

        self._edit_button.setEnabled(False)
        self._bulk_button.setEnabled(False)
        self._delete_button.setEnabled(False)

    def _on_edit_clicked(self) -> None:
        raise NotImplementedError

    def _on_bulk_service_clicked(self) -> None:
        if not self._payload or self._profile is None:
            return
        kind = self._payload.get("kind")
        hpd_file = self._payload.get("hpd_file")

        if kind == "group":
            group = self._payload["group"]
            label = f"all {len(group.entries)} entries in '{group.name}'"
            entries = list(group.entries)
        elif kind == "system":
            system = self._payload["system"]
            entries = [e for g in system.groups for e in g.entries]
            label = f"all {len(entries)} entries in system '{system.name}'"
        else:
            return

        if not entries:
            return

        dlg = self._make_bulk_dialog(label)
        if dlg.exec() != dlg.Accepted:
            return
        new_type = dlg.selected_service_type()
        if new_type is None:
            return
        for entry in entries:
            hpd_file.update_service_type(entry, int(new_type))
        self.entryEdited.emit()

    def _make_bulk_dialog(self, target_label: str):
        raise NotImplementedError

    def _on_delete_clicked(self) -> None:
        if not self._payload:
            return
        if self._payload.get("kind") != "entry":
            return
        from PySide6.QtWidgets import QMessageBox

        entry = self._payload["entry"]
        confirm = QMessageBox.question(
            self,
            "Delete entry",
            f"Delete entry '{entry.name}'? This change isn't saved until you "
            "click Save in the toolbar.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        hpd_file = self._payload["hpd_file"]
        hpd_file.delete_entry(entry)
        self._payload = None
        self._reset()
        self.entryEdited.emit()

    def _reset(self) -> None:
        while self._info_form.rowCount() > 0:
            self._info_form.removeRow(0)
        self._title.setText("Select a node in the tree")
        for btn in (self._edit_button, self._bulk_button, self._delete_button):
            btn.setEnabled(False)


class Bt885DetailsPanel(BaseDetailsPanel):
    """BearTracker 885 editor — inline service-type change + button help."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._service_combo: Optional[QComboBox] = None
        self._update_service_button: Optional[QPushButton] = None

    def _show_entry(self, payload: dict) -> None:
        entry = payload["entry"]
        profile = self._profile
        if profile is None:
            return

        self._title.setText(entry.name or "(unnamed entry)")
        if entry.entry_type == "C-Freq":
            freq_field = entry.record.get_field(5, "")
            try:
                identity = f"{int(freq_field) / 1e6:.5f} MHz".rstrip("0").rstrip(".")
            except (TypeError, ValueError):
                identity = freq_field or "—"
            self._info_form.addRow("Frequency:", QLabel(identity))
            self._info_form.addRow("Mode:", QLabel(entry.record.get_field(6, "—")))
            self._info_form.addRow("Tone:", QLabel(entry.record.get_field(7, "—") or "—"))
        else:
            self._info_form.addRow("TGID:", QLabel(entry.record.get_field(5, "—")))
            self._info_form.addRow("Mode:", QLabel(entry.record.get_field(6, "—")))

        service_text = format_service_type_details(profile, entry.service_type)
        self._info_form.addRow("Service type:", QLabel(service_text))

        self._info_form.addRow("System:", QLabel(entry.system_name or "—"))
        self._info_form.addRow("Group:", QLabel(entry.group_name or "—"))

        self._service_combo = QComboBox()
        for sid, label in sorted(profile.service_types.items()):
            self._service_combo.addItem(f"{sid} — {label}", userData=sid)
        for i in range(self._service_combo.count()):
            if self._service_combo.itemData(i) == entry.service_type:
                self._service_combo.setCurrentIndex(i)
                break
        self._update_service_button = QPushButton("Update service type")
        self._update_service_button.clicked.connect(self._on_update_service_type)
        change_row = QWidget()
        change_layout = QHBoxLayout(change_row)
        change_layout.setContentsMargins(0, 0, 0, 0)
        change_layout.addWidget(self._service_combo, stretch=1)
        change_layout.addWidget(self._update_service_button)
        self._info_form.addRow("Change service type:", change_row)

        self._edit_button.setEnabled(True)
        self._bulk_button.setEnabled(False)
        self._delete_button.setEnabled(True)

    def _on_update_service_type(self) -> None:
        if not self._payload or self._service_combo is None:
            return
        if self._payload.get("kind") != "entry":
            return
        new_type = self._service_combo.currentData()
        if new_type is None:
            return
        entry = self._payload["entry"]
        if new_type == entry.service_type:
            return
        hpd_file = self._payload["hpd_file"]
        hpd_file.update_service_type(entry, int(new_type))
        self.entryEdited.emit()

    def _on_edit_clicked(self) -> None:
        if not self._payload or self._profile is None:
            return
        kind = self._payload.get("kind")
        hpd_file = self._payload.get("hpd_file")
        if kind == "entry":
            entry = self._payload["entry"]
            dlg = Bt885EntryEditDialog(entry, hpd_file, self._profile, parent=self)
            if dlg.exec() == Bt885EntryEditDialog.Accepted:
                self.entryEdited.emit()
        elif kind == "group":
            group = self._payload["group"]
            dlg = GroupEditDialog(group, hpd_file, parent=self)
            if dlg.exec() == GroupEditDialog.Accepted:
                self.entryEdited.emit()

    def _make_bulk_dialog(self, target_label: str):
        return Bt885BulkServiceTypeDialog(target_label, self._profile, parent=self)


class HpdbDetailsPanel(BaseDetailsPanel):
    """SDS / general HPDB editor — plain category labels."""

    def _show_entry(self, payload: dict) -> None:
        entry = payload["entry"]
        profile = self._profile
        if profile is None:
            return

        self._title.setText(entry.name or "(unnamed entry)")
        if entry.entry_type == "C-Freq":
            freq_field = entry.record.get_field(5, "")
            try:
                identity = f"{int(freq_field) / 1e6:.5f} MHz".rstrip("0").rstrip(".")
            except (TypeError, ValueError):
                identity = freq_field or "—"
            self._info_form.addRow("Frequency:", QLabel(identity))
            self._info_form.addRow("Mode:", QLabel(entry.record.get_field(6, "—")))
            self._info_form.addRow("Tone:", QLabel(entry.record.get_field(7, "—") or "—"))
        else:
            self._info_form.addRow("TGID:", QLabel(entry.record.get_field(5, "—")))
            self._info_form.addRow("Mode:", QLabel(entry.record.get_field(6, "—")))

        category = format_service_type_details(profile, entry.service_type)
        self._info_form.addRow("Category:", QLabel(category))

        self._info_form.addRow("System:", QLabel(entry.system_name or "—"))
        self._info_form.addRow("Group:", QLabel(entry.group_name or "—"))

        self._edit_button.setEnabled(True)
        self._bulk_button.setEnabled(False)
        self._delete_button.setEnabled(True)

    def _on_edit_clicked(self) -> None:
        if not self._payload or self._profile is None:
            return
        kind = self._payload.get("kind")
        hpd_file = self._payload.get("hpd_file")
        if kind == "entry":
            entry = self._payload["entry"]
            dlg = HpdbEntryEditDialog(entry, hpd_file, self._profile, parent=self)
            if dlg.exec() == HpdbEntryEditDialog.Accepted:
                self.entryEdited.emit()
        elif kind == "group":
            group = self._payload["group"]
            dlg = GroupEditDialog(group, hpd_file, parent=self)
            if dlg.exec() == GroupEditDialog.Accepted:
                self.entryEdited.emit()

    def _make_bulk_dialog(self, target_label: str):
        return HpdbBulkCategoryDialog(target_label, self._profile, parent=self)


def details_panel_for(
    profile: ScannerProfile, parent: Optional[QWidget] = None
) -> BaseDetailsPanel:
    """Build the details panel appropriate for the active scanner profile."""
    if profile.uses_hardware_button_semantics:
        return Bt885DetailsPanel(parent)
    return HpdbDetailsPanel(parent)


# Backward-compatible alias for imports that still reference DetailsPanel.
DetailsPanel = BaseDetailsPanel
