"""Phase 2 editor dock.

Layout::

    +-------------------------------------------------------------+
    | [Save] [Save All] [Reload] [Audit Modes] | (status hint)     |
    +-------------------------------+---------------+---------------+
    | HPDB tree                     | Details panel | Profile-side  |
    | (state -> system -> group ->  | (entry/group  | panel (BT885  |
    |   entry)                      | edit)         | buttons or    |
    |                               |               | SDS Favorites |
    |                               |               | + profile.cfg)|
    +-------------------------------+---------------+---------------+
    | Coverage panel (heatmap + Leaflet map + ZIP/GPS sim controls) |
    +-------------------------------------------------------------+
"""

from __future__ import annotations

import logging
from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from core.device_manager import Device
from scanner_profiles import ScannerProfile, detect_from_card, get_profile

from .coverage_panel import CoveragePanel
from .details_panel import BaseDetailsPanel, details_panel_for
from .hpdb_tree import HpdbTreeWidget
from .profile_panels import ProfileSidePanel

logger = logging.getLogger(__name__)


def _entry_has_encrypted_mode(entry) -> bool:
    mode = (entry.record.get_field(6, "") or "").upper()
    return mode in {"DE", "TE", "AE"}


def _count_encrypted_entries(files) -> int:
    return sum(
        1
        for hpd in files
        for sys_node in hpd.systems
        for group in sys_node.groups
        for entry in group.entries
        if _entry_has_encrypted_mode(entry)
    )


class EditorDock(QWidget):
    """Main editor surface for the active scanner."""

    manageDevicesRequested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._current_device: Optional[Device] = None
        self._current_profile: Optional[ScannerProfile] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # ---- Toolbar ----
        self._toolbar = QToolBar()
        self._save_action = self._toolbar.addAction("Save current", self.save_current)
        self._save_all_action = self._toolbar.addAction("Save all", self.save_all)
        self._toolbar.addAction("Reload", self._on_reload)
        self._toolbar.addSeparator()
        self._toolbar.addAction("Audit modes…", self._on_audit_modes)
        self._toolbar.addAction("Refresh coverage", self._refresh_coverage)
        self._toolbar.addSeparator()
        self._status_label = QLabel("No HPDB loaded")
        self._status_label.setStyleSheet("color: #666;")
        self._toolbar.addWidget(self._status_label)
        layout.addWidget(self._toolbar)

        # Card vs device profile mismatch (hidden by default).
        self._mismatch_banner = QLabel("")
        self._mismatch_banner.setVisible(False)
        self._mismatch_banner.setWordWrap(True)
        self._mismatch_banner.setStyleSheet(
            "background: #4a3728; color: #ffe8cc; padding: 8px; "
            "border: 1px solid #a08060; border-radius: 4px;"
        )
        mismatch_row = QWidget()
        mismatch_layout = QVBoxLayout(mismatch_row)
        mismatch_layout.setContentsMargins(0, 0, 0, 0)
        mismatch_layout.addWidget(self._mismatch_banner)
        self._manage_devices_link = QPushButton("Manage devices…")
        self._manage_devices_link.setFlat(True)
        self._manage_devices_link.setStyleSheet(
            "color: #ffe8cc; text-align: left; padding: 0 8px 8px 8px;"
        )
        self._manage_devices_link.clicked.connect(self.manageDevicesRequested.emit)
        self._manage_devices_link.setVisible(False)
        mismatch_layout.addWidget(self._manage_devices_link)
        layout.addWidget(mismatch_row)

        # ---- Top splitter (tree | details | side panel) ----
        self._top_splitter = QSplitter(Qt.Horizontal)

        self._tree = HpdbTreeWidget()
        self._top_splitter.addWidget(self._tree)

        self._details: BaseDetailsPanel = details_panel_for(
            get_profile("uniden_bt885")
        )
        self._top_splitter.addWidget(self._details)

        self._side_panel = ProfileSidePanel()
        self._top_splitter.addWidget(self._side_panel)

        self._top_splitter.setStretchFactor(0, 4)
        self._top_splitter.setStretchFactor(1, 3)
        self._top_splitter.setStretchFactor(2, 3)

        # ---- Bottom: coverage panel (gated by profile) ----
        # The coverage panel is created up front so signals can wire
        # against it; visibility is toggled by ``set_active_device``
        # based on profile.supports_coverage_simulation. The same
        # widget can also be reparented into a standalone window via
        # the Tools > Coverage window… menu.
        self._coverage = CoveragePanel()
        self._coverage.set_data_source(self._tree.loaded_files)

        self._main_splitter = QSplitter(Qt.Vertical)
        self._main_splitter.addWidget(self._top_splitter)
        self._main_splitter.addWidget(self._coverage)
        self._main_splitter.setStretchFactor(0, 3)
        self._main_splitter.setStretchFactor(1, 2)
        self._main_splitter.setHandleWidth(6)
        self._top_splitter.setHandleWidth(6)

        layout.addWidget(self._main_splitter, stretch=1)

        # ---- Wiring ----
        self._connect_details_panel(self._details)
        self._side_panel.button_filter_panel().selectionChanged.connect(
            self._on_button_filter_changed
        )

    def _connect_details_panel(self, panel: BaseDetailsPanel) -> None:
        self._tree.entrySelected.connect(panel.show_entry)
        panel.entryEdited.connect(self._on_after_edit)

    def _swap_details_panel(
        self, profile: ScannerProfile, prev_profile: Optional[ScannerProfile]
    ) -> None:
        need_swap = (
            prev_profile is None
            or profile.uses_hardware_button_semantics
            != prev_profile.uses_hardware_button_semantics
        )
        if not need_swap:
            self._details.set_profile(profile)
            return

        try:
            self._tree.entrySelected.disconnect(self._details.show_entry)
        except (RuntimeError, TypeError):
            pass
        try:
            self._details.entryEdited.disconnect(self._on_after_edit)
        except (RuntimeError, TypeError):
            pass

        old = self._details
        self._details = details_panel_for(profile)
        self._details.set_profile(profile)
        idx = self._top_splitter.indexOf(old)
        if idx >= 0:
            self._top_splitter.replaceWidget(idx, self._details)
        else:
            self._top_splitter.addWidget(self._details)
        old.setParent(None)
        old.deleteLater()
        self._connect_details_panel(self._details)

    # ------------------------------------------------------------------
    # Public API called by MainWindow
    # ------------------------------------------------------------------

    def set_active_device(self, device: Device, profile: ScannerProfile) -> None:
        if self.has_unsaved_changes():
            reply = QMessageBox.question(
                self,
                "Unsaved changes",
                "Switching devices will discard unsaved HPDB edits. Continue?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                # Tell the header to revert, but in Phase 1+ we don't
                # have a clean revert path - just continue and accept
                # the discard.
                pass

        self._current_device = device
        prev_profile = self._current_profile
        self._current_profile = profile

        self._swap_details_panel(profile, prev_profile)
        self._tree.set_profile(profile)
        self._side_panel.set_profile(profile)

        sd_path = device.sd_card_path or ""
        if sd_path:
            ok = self._tree.try_load_from_card(sd_path)
            if ok:
                files = self._tree.loaded_files()
                entry_count = sum(
                    len(g.entries)
                    for f in files
                    for s in f.systems
                    for g in s.groups
                )
                self._status_label.setText(
                    f"Loaded {len(files)} HPD files, {entry_count} entries from {sd_path}"
                )
            else:
                self._status_label.setText(f"No HPDB loaded from {sd_path}")
            self._update_profile_mismatch_banner(sd_path, profile)
        else:
            self._tree.try_load_from_card("")
            self._status_label.setText(
                f"{profile.display_name} - no SD card path set. Use 'Manage devices…'."
            )
            self._clear_profile_mismatch_banner()

        self._side_panel.set_card_path(sd_path)
        if profile.uses_hardware_button_semantics:
            self._tree.set_button_filter(
                self._side_panel.button_filter_panel().selected_buttons()
            )
        self._tree.reemit_current_selection()
        # Hide the embedded coverage panel for profiles that don't use
        # ZIP/GPS simulation (e.g. SDS100/200). The user can still
        # open it as a separate window via Tools > Coverage window.
        self._coverage.setVisible(profile.supports_coverage_simulation)
        # Hide the "Refresh coverage" toolbar action too, to keep the
        # toolbar tidy on SDS profiles.
        for action in self._toolbar.actions():
            if action.text() == "Refresh coverage":
                action.setVisible(profile.supports_coverage_simulation)
        if profile.supports_coverage_simulation:
            self._refresh_coverage()

    def _on_button_filter_changed(self, selected: set) -> None:
        if self._current_profile and self._current_profile.uses_hardware_button_semantics:
            self._tree.set_button_filter(selected)

    def _update_profile_mismatch_banner(
        self, sd_path: str, configured: ScannerProfile
    ) -> None:
        detected = detect_from_card(sd_path)
        if detected is None or detected.id == configured.id:
            self._clear_profile_mismatch_banner()
            return
        self._mismatch_banner.setText(
            f"This SD card looks like a {detected.display_name}, but this device "
            f"is configured as {configured.display_name}. Service-type labels may "
            "be wrong until you fix the device profile."
        )
        self._mismatch_banner.setVisible(True)
        self._manage_devices_link.setVisible(True)

    def _clear_profile_mismatch_banner(self) -> None:
        self._mismatch_banner.clear()
        self._mismatch_banner.setVisible(False)
        self._manage_devices_link.setVisible(False)

    def save_current(self) -> None:
        """Save whichever HPD file is currently the focus.

        Phase 2 falls through to save_all() since the tree doesn't
        track a "current file" notion separately from selection.
        """
        self.save_all()

    def current_hpd_path(self) -> str:
        """Return the path of the most-recently-loaded HPD file (if any).

        Used by Tools > Recent changes to pick which sidecar to inspect.
        """
        files = self._tree.loaded_files()
        if not files:
            return ""
        last = files[-1]
        return getattr(last, "filepath", "") or ""

    def coverage_panel(self):
        """Expose the CoveragePanel widget so MainWindow can host it
        in a standalone Tools > Coverage window when the embedded panel
        is hidden (SDS100/200 profile).
        """
        return self._coverage

    def refresh_coverage(self) -> None:
        """Public re-export of the internal _refresh_coverage hook,
        used by the standalone Coverage window's Refresh button.
        """
        self._refresh_coverage()

    def save_all(self) -> None:
        files = [f for f in self._tree.loaded_files() if getattr(f, "has_changes", False)]
        if not files:
            self._status_label.setText("Nothing to save (no in-memory changes).")
            return
        errors: List[str] = []
        saved: List[str] = []
        for hpd in files:
            try:
                hpd.save()
                saved.append(hpd.filepath or "")
            except Exception as exc:
                errors.append(f"{hpd.filepath}: {exc}")
        if errors:
            QMessageBox.critical(
                self,
                "Save failed",
                "Some files could not be saved:\n\n" + "\n".join(errors),
            )
        else:
            self._status_label.setText(
                f"Saved {len(saved)} HPD file(s)."
            )

    def has_unsaved_changes(self) -> bool:
        return self._tree.has_unsaved_changes()

    def request_close(self) -> bool:
        if not self.has_unsaved_changes():
            return True
        reply = QMessageBox.question(
            self,
            "Unsaved changes",
            "There are unsaved HPDB edits. Save before quitting?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Save,
        )
        if reply == QMessageBox.Cancel:
            return False
        if reply == QMessageBox.Save:
            self.save_all()
        return True

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _on_reload(self) -> None:
        if self._current_device and self._current_device.sd_card_path:
            self._tree.try_load_from_card(self._current_device.sd_card_path)
            self._refresh_coverage()
            self._status_label.setText("Reloaded from disk.")

    def _on_after_edit(self) -> None:
        # Reload the tree from in-memory state so the new service
        # type / name / freq etc. show up.
        if self._current_device:
            sd_path = self._current_device.sd_card_path or ""
            self._tree.try_load_from_card(sd_path)
            self._tree.reemit_current_selection()
        self._status_label.setText("Edit applied (not saved).")
        self._refresh_coverage()

    def _on_audit_modes(self) -> None:
        # Simple Phase 2 audit: count entries flagged as encrypted-mode
        # but where the scanner can't decode them. The legacy Tk app
        # has a much richer audit dialog; the cutover phase will port it.
        files = self._tree.loaded_files()
        if not files:
            QMessageBox.information(self, "Audit modes", "No HPDB loaded.")
            return
        encrypted_total = _count_encrypted_entries(files)
        QMessageBox.information(
            self,
            "Audit modes",
            f"Found {encrypted_total} entries flagged as encrypted "
            f"(mode in {{DE, TE, AE}}). The scanner cannot decode "
            "these - consider muting them via service-type changes.",
        )

    def _refresh_coverage(self) -> None:
        try:
            self._coverage.refresh_from_hpdb()
        except Exception as exc:
            logger.warning("Coverage refresh failed: %s", exc)
