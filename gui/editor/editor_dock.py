"""Phase 2 editor dock.

Layout (BT885)::

    +-------------------------------------------------------------+
    | [Save] [Save All] [Reload] [Audit Modes] | (status hint)     |
    +-------------------------------------------------------------+
    | LocationSimBar (ZIP / county / GPS)                           |
    +-------------------------------+-------------------------------+
    | HPDB tree                     | BT885 inspector (buttons +  |
    | (state -> system -> group ->  | details + include others)    |
    |   entry)                      |                               |
    +-------------------------------+-------------------------------+

Layout (SDS100/200) — LocationSimBar hidden, three columns::

    + tree | Details panel | Profile-side panel (Favorites + profile.cfg) +

Map / heatmap: View → Coverage / heatmap… popout only (MainWindow host).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from core.device_manager import Device
from scanner_profiles import ScannerProfile, detect_from_card, get_profile

from .bt885_inspector import Bt885InspectorPanel
from .details_panel import BaseDetailsPanel, details_panel_for
from .hpdb_tree import HpdbTreeWidget
from .location_filter import LocationFilterState
from .location_sim_bar import LocationSimBar
from .profile_panels import ProfileSidePanel

if TYPE_CHECKING:
    from gui.main_window import MainWindow

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
        self._workspace_name: Optional[str] = None

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

        # ---- Location simulation (BT885 only) ----
        self._location_sim = LocationSimBar()
        self._location_sim.setVisible(False)
        layout.addWidget(self._location_sim)

        # ---- Horizontal splitter: tree | profile-specific right stack ----
        self._splitter = QSplitter(Qt.Horizontal)
        self._splitter.setHandleWidth(6)

        self._tree = HpdbTreeWidget()
        self._splitter.addWidget(self._tree)

        self._details: BaseDetailsPanel = details_panel_for(
            get_profile("uniden_sds100")
        )
        self._side_panel = ProfileSidePanel()
        self._bt885_inspector = Bt885InspectorPanel()

        self._sds_splitter = QSplitter(Qt.Horizontal)
        self._sds_splitter.setHandleWidth(6)
        self._sds_splitter.addWidget(self._details)
        self._sds_splitter.addWidget(self._side_panel)
        self._sds_splitter.setStretchFactor(0, 1)
        self._sds_splitter.setStretchFactor(1, 1)

        self._right_stack = QStackedWidget()
        self._right_stack.addWidget(self._bt885_inspector)
        self._right_stack.addWidget(self._sds_splitter)

        self._splitter.addWidget(self._right_stack)
        self._splitter.setStretchFactor(0, 5)
        self._splitter.setStretchFactor(1, 4)

        layout.addWidget(self._splitter, stretch=1)

        # ---- Wiring ----
        self._location_sim.locationFilterChanged.connect(
            self._on_location_filter_changed
        )
        self._bt885_inspector.button_filter_panel().selectionChanged.connect(
            self._on_button_filter_changed
        )
        self._bt885_inspector.includeOthersChanged.connect(
            self._tree.set_include_others
        )
        self._bt885_inspector.details_panel().entryEdited.connect(
            self._on_after_edit
        )

    def _main_window(self) -> Optional["MainWindow"]:
        from gui.main_window import MainWindow

        w = self.window()
        return w if isinstance(w, MainWindow) else None

    def _connect_details_panel(self, panel: BaseDetailsPanel) -> None:
        self._disconnect_details_panel(panel)
        self._tree.entrySelected.connect(panel.show_entry)
        panel.entryEdited.connect(self._on_after_edit)

    def _disconnect_details_panel(self, panel: BaseDetailsPanel) -> None:
        try:
            self._tree.entrySelected.disconnect(panel.show_entry)
        except (RuntimeError, TypeError):
            pass
        try:
            panel.entryEdited.disconnect(self._on_after_edit)
        except (RuntimeError, TypeError):
            pass

    def _disconnect_bt885_inspector(self) -> None:
        try:
            self._tree.entrySelected.disconnect(
                self._bt885_inspector.details_panel().show_entry
            )
        except (RuntimeError, TypeError):
            pass

    def _apply_editor_layout(self, profile: ScannerProfile) -> None:
        """BT885: tree | inspector. SDS: tree | details | side panel."""
        is_bt885 = profile.uses_hardware_button_semantics
        self._location_sim.setVisible(is_bt885)

        if is_bt885:
            self._right_stack.setCurrentIndex(0)
            self._disconnect_details_panel(self._details)
            self._disconnect_bt885_inspector()
            self._tree.entrySelected.connect(
                self._bt885_inspector.details_panel().show_entry
            )
            self._splitter.setStretchFactor(0, 5)
            self._splitter.setStretchFactor(1, 4)
        else:
            self._right_stack.setCurrentIndex(1)
            self._disconnect_bt885_inspector()
            self._connect_details_panel(self._details)
            self._splitter.setStretchFactor(0, 4)
            self._splitter.setStretchFactor(1, 6)

    def _sync_hpdb_context(self) -> None:
        self._location_sim.set_hpdb_context(
            self._tree.hpd_config(), self._tree.sd_root()
        )

    def _on_location_filter_changed(self, state: LocationFilterState) -> None:
        self._tree.set_location_filter(state if state.enabled else None)
        mw = self._main_window()
        if mw is not None and state.coords is not None:
            lat, lon = state.coords
            mw.coverage_panel().set_sim_center(lat, lon)
        self._refresh_coverage()

    # ------------------------------------------------------------------
    # Public API called by MainWindow
    # ------------------------------------------------------------------

    def set_data_source_context(self, workspace_name: Optional[str] = None) -> None:
        """Prefix HPDB toolbar status when a named workspace is active."""
        self._workspace_name = workspace_name
        device = self._current_device
        profile = self._current_profile
        if device is not None and profile is not None:
            self._load_hpdb_for_device(device, profile)

    def _hpdb_status_text(self, message: str) -> str:
        if self._workspace_name:
            return f'Workspace "{self._workspace_name}" · {message}'
        return message

    def _apply_card_swap_coverage(
        self,
        prev_device: Optional[Device],
        device: Device,
        profile: ScannerProfile,
    ) -> None:
        if not profile.supports_coverage_simulation:
            return
        card_swapped = prev_device is not None and (
            prev_device.id != device.id
            or (prev_device.sd_card_path or "") != (device.sd_card_path or "")
        )
        if card_swapped:
            panel = self.coverage_panel()
            if panel is not None:
                panel.invalidate_map_shell()
        self._refresh_coverage()

    def _update_side_panel_for_device(
        self, device: Device, profile: ScannerProfile, *, load_hpdb: bool
    ) -> None:
        if load_hpdb:
            return
        if profile.uses_hardware_button_semantics:
            return
        sd_path = device.sd_card_path or ""
        self._side_panel.set_card_path(sd_path)
        if sd_path:
            self._update_profile_mismatch_banner(sd_path, profile)
        else:
            self._clear_profile_mismatch_banner()

    def set_active_device(
        self,
        device: Device,
        profile: ScannerProfile,
        *,
        load_hpdb: bool = True,
    ) -> None:
        if self.has_unsaved_changes() and not self._confirm_discard_unsaved():
            return

        prev_device = self._current_device
        self._current_device = device
        prev_profile = self._current_profile
        self._current_profile = profile

        self._apply_profile_widgets(profile, prev_profile)
        if load_hpdb:
            self._load_hpdb_for_device(device, profile)
        else:
            self._update_side_panel_for_device(device, profile, load_hpdb=load_hpdb)
        self._sync_hpdb_context()
        self._configure_bt885_filters(profile)
        self._tree.reemit_current_selection()
        self._apply_card_swap_coverage(prev_device, device, profile)

    def _confirm_discard_unsaved(self) -> bool:
        reply = QMessageBox.question(
            self,
            "Unsaved changes",
            "Switching devices will discard unsaved HPDB edits. Continue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        return reply == QMessageBox.Yes

    def _apply_profile_widgets(
        self, profile: ScannerProfile, prev_profile: Optional[ScannerProfile]
    ) -> None:
        is_bt885 = profile.uses_hardware_button_semantics
        if not is_bt885:
            self._details.set_profile(profile)
        self._apply_editor_layout(profile)
        self._tree.set_profile(profile)
        if is_bt885:
            self._bt885_inspector.set_profile(profile)
        else:
            self._side_panel.set_profile(profile)

    def _device_id(self) -> str:
        return self._current_device.id if self._current_device else ""

    def _invalidate_card_caches(self) -> None:
        device = self._current_device
        if device is None:
            self._tree.invalidate_cache()
            self._side_panel.invalidate_card_cache()
            return
        self._tree.invalidate_cache(device_id=device.id)
        self._side_panel.invalidate_card_cache(device.sd_card_path)

    def _load_hpdb_for_device(self, device: Device, profile: ScannerProfile) -> None:
        sd_path = device.sd_card_path or ""
        if sd_path:
            ok = self._tree.try_load_from_card(sd_path, device_id=device.id)
            if ok:
                files = self._tree.loaded_files()
                entry_count = sum(
                    len(g.entries)
                    for f in files
                    for s in f.systems
                    for g in s.groups
                )
                self._status_label.setText(
                    self._hpdb_status_text(
                        f"Loaded {len(files)} HPD files, {entry_count} entries from {sd_path}"
                    )
                )
            else:
                self._status_label.setText(
                    self._hpdb_status_text(f"No HPDB loaded from {sd_path}")
                )
            self._update_profile_mismatch_banner(sd_path, profile)
        else:
            self._tree.try_load_from_card("", device_id=device.id)
            self._status_label.setText(
                self._hpdb_status_text(
                    f"{profile.display_name} - no SD card path set. Use 'Manage devices…'."
                )
            )
            self._clear_profile_mismatch_banner()

    def _configure_bt885_filters(self, profile: ScannerProfile) -> None:
        if not profile.uses_hardware_button_semantics:
            self._side_panel.set_card_path(self._current_device.sd_card_path or "")
            return
        self._tree.set_button_filter(
            self._bt885_inspector.button_filter_panel().selected_buttons()
        )
        self._tree.set_include_others(
            self._bt885_inspector._include_others.isChecked()
        )
        self._on_location_filter_changed(self._location_sim.current_state())

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
        """Delegate to MainWindow's popout CoveragePanel host."""
        mw = self._main_window()
        if mw is not None:
            return mw.coverage_panel()
        return None

    def refresh_coverage(self) -> None:
        """Refresh heatmap/map via MainWindow's coverage panel."""
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
            self._invalidate_card_caches()

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
            self._invalidate_card_caches()
            self._tree.try_load_from_card(
                self._current_device.sd_card_path,
                device_id=self._device_id(),
            )
            self._sync_hpdb_context()
            panel = self.coverage_panel()
            if panel is not None:
                panel.invalidate_map_shell()
            self._refresh_coverage()
            self._status_label.setText("Reloaded from disk.")

    def _on_after_edit(self) -> None:
        if self._current_device:
            sd_path = self._current_device.sd_card_path or ""
            self._tree.try_load_from_card(sd_path, device_id=self._device_id())
            self._sync_hpdb_context()
            self._tree.reemit_current_selection()
        self._status_label.setText("Edit applied (not saved).")
        self._refresh_coverage()

    def _on_audit_modes(self) -> None:
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

    def _coverage_window_visible(self) -> bool:
        mw = self._main_window()
        if mw is None:
            return False
        window = getattr(mw, "_coverage_window", None)
        return window is not None and window.isVisible()

    def _refresh_coverage(self) -> None:
        try:
            panel = self.coverage_panel()
            if panel is None:
                return
            panel.set_refresh_enabled(self._coverage_window_visible())
            panel.refresh_from_hpdb()
        except Exception as exc:
            logger.warning("Coverage refresh failed: %s", exc)
