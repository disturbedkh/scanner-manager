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

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QLabel,
    QMessageBox,
    QSplitter,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from core.device_manager import Device
from scanner_profiles import ScannerProfile

from .coverage_panel import CoveragePanel
from .details_panel import DetailsPanel
from .hpdb_tree import HpdbTreeWidget
from .profile_panels import ProfileSidePanel

logger = logging.getLogger(__name__)


class EditorDock(QWidget):
    """Main editor surface for the active scanner."""

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

        # ---- Top splitter (tree | details | side panel) ----
        top_splitter = QSplitter(Qt.Horizontal)

        self._tree = HpdbTreeWidget()
        top_splitter.addWidget(self._tree)

        self._details = DetailsPanel()
        top_splitter.addWidget(self._details)

        self._side_panel = ProfileSidePanel()
        top_splitter.addWidget(self._side_panel)

        top_splitter.setStretchFactor(0, 4)
        top_splitter.setStretchFactor(1, 3)
        top_splitter.setStretchFactor(2, 3)

        # ---- Bottom: coverage panel (gated by profile) ----
        # The coverage panel is created up front so signals can wire
        # against it; visibility is toggled by ``set_active_device``
        # based on profile.supports_coverage_simulation. The same
        # widget can also be reparented into a standalone window via
        # the Tools > Coverage window… menu.
        self._coverage = CoveragePanel()
        self._coverage.set_data_source(self._tree.loaded_files)

        self._main_splitter = QSplitter(Qt.Vertical)
        self._main_splitter.addWidget(top_splitter)
        self._main_splitter.addWidget(self._coverage)
        self._main_splitter.setStretchFactor(0, 3)
        self._main_splitter.setStretchFactor(1, 2)
        # All splitter handles get a visible grip so users see they're
        # draggable.
        self._main_splitter.setHandleWidth(6)
        top_splitter.setHandleWidth(6)

        layout.addWidget(self._main_splitter, stretch=1)

        # Mode-hint banner shown when MainWindow puts us into "disabled
        # for Live mode" state. Hidden by default.
        self._mode_hint = QLabel("")
        self._mode_hint.setVisible(False)
        self._mode_hint.setWordWrap(True)
        self._mode_hint.setStyleSheet(
            "background: #443; color: #ffd; padding: 8px; "
            "border: 1px solid #886; border-radius: 4px;"
        )
        layout.addWidget(self._mode_hint)

        # ---- Wiring ----
        self._tree.entrySelected.connect(self._details.show_entry)
        self._details.entryEdited.connect(self._on_after_edit)

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
        self._current_profile = profile

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
        else:
            self._tree.try_load_from_card("")
            self._status_label.setText(
                f"{profile.display_name} - no SD card path set. Use 'Manage devices…'."
            )

        self._side_panel.set_card_path(sd_path)
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

    def set_mode_hint(self, message: str) -> None:
        """Show / hide a banner explaining why the editor is disabled.

        MainWindow drives this when the operator is in Live (Serial)
        mode - the SD card isn't accessible while the scanner is in
        Serial Mode, so editing HPDB / firmware is impossible.
        Empty string clears the banner.
        """
        if message:
            self._mode_hint.setText(message)
            self._mode_hint.setVisible(True)
        else:
            self._mode_hint.setVisible(False)
            self._mode_hint.setText("")

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
            # Cheap rebuild: rebuild the model in place.
            # The HpdFile instances are shared, so we just rebuild the
            # tree's view - any calls to try_load_from_card with the
            # same SD path are idempotent.
            sd_path = self._current_device.sd_card_path or ""
            self._tree.try_load_from_card(sd_path)
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
        encrypted_total = 0
        for hpd in files:
            for sys_node in hpd.systems:
                for group in sys_node.groups:
                    for entry in group.entries:
                        mode = (entry.record.get_field(6, "") or "").upper()
                        if mode in {"DE", "TE", "AE"}:
                            encrypted_total += 1
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
