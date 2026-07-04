"""HPDB tree widget - QTreeView wrapping the parsed Hpd model.

Loads ``BCDx36HP/HPDB/hpdb.cfg`` + every ``s_*.hpd`` file underneath
it via the existing ``HpdConfig`` / ``HpdFile`` classes from
:mod:`scanner_manager`. The same parser the legacy Tk app uses, so
edits + saves stay byte-for-byte compatible with both apps in the
same release.

Tree shape::

    state (s_000012.hpd)            -- counted system count + entry count
      county / Trunk system          -- icon by system_type
        group                        -- groups inside the system
          frequency / TGID           -- leaf with freq/tgid + service-type column

Selection emits :attr:`HpdbTreeWidget.entrySelected` carrying a
typed dict the details panel can render. The dict references the
underlying ``HpdFile`` + node objects so edits write back into
the in-memory model directly.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QHeaderView,
    QLineEdit,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from scanner_profiles import ScannerProfile

from .display_helpers import entry_passes_button_filter, entry_row_color
from .hpdb_cache import CachedHpdb, get_hpdb_session_cache
from .location_filter import (
    LocationFilterState,
    group_coverage_info,
    nearest_distance_miles,
    system_matches_location,
)

logger = logging.getLogger(__name__)


# Tree chrome colors (non-entry rows).
_COLOR_GROUP = QColor("#1f3864")
_COLOR_SYSTEM = QColor("#000000")
_COLOR_FILE = QColor("#0b3866")


class HpdbTreeWidget(QWidget):
    """Tree view of one or more HPD state files."""

    entrySelected = Signal(object)  # dict{kind, payload, hpd_file, ...}

    COLUMNS = ("Name", "Freq / TGID", "Mode", "Service Type")

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._profile: Optional[ScannerProfile] = None
        self._hpd_files: Dict[int, Any] = {}  # state_id -> HpdFile instance
        self._hpd_config: Optional[Any] = None
        self._sd_root: Optional[Path] = None
        self._search_text: str = ""
        self._active_buttons: Optional[Set[str]] = None
        self._include_others: bool = True
        self._location_filter: Optional[LocationFilterState] = None

        self._model = QStandardItemModel()
        self._model.setHorizontalHeaderLabels(list(self.COLUMNS))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Filter by name / freq / TGID…")
        self._search.textChanged.connect(self._on_search_changed)
        layout.addWidget(self._search)

        self._view = QTreeView()
        self._view.setModel(self._model)
        self._view.setUniformRowHeights(True)
        self._view.setAlternatingRowColors(True)
        self._view.setHeaderHidden(False)
        self._view.setSelectionBehavior(QTreeView.SelectRows)
        self._view.header().setSectionResizeMode(QHeaderView.Interactive)
        self._view.header().setStretchLastSection(False)
        self._view.setColumnWidth(0, 320)
        self._view.setColumnWidth(1, 130)
        self._view.setColumnWidth(2, 80)
        self._view.setColumnWidth(3, 160)
        self._view.selectionModel().currentChanged.connect(self._on_current_changed)
        layout.addWidget(self._view)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_profile(self, profile: ScannerProfile) -> None:
        self._profile = profile
        if profile is None or not profile.uses_hardware_button_semantics:
            self._active_buttons = None
        self._apply_visibility_filters()

    def set_button_filter(self, selected_buttons: Set[str]) -> None:
        """Hide entries that would not play with the given BT885 buttons."""
        if self._profile is None or not self._profile.uses_hardware_button_semantics:
            return
        self._active_buttons = set(selected_buttons)
        self._apply_visibility_filters()

    def set_include_others(self, include: bool) -> None:
        """Toggle whether non-button service types remain visible."""
        self._include_others = include
        self._apply_visibility_filters()

    def set_location_filter(self, state: Optional[LocationFilterState]) -> None:
        """Apply ZIP/GPS location filter (systems, groups, distance labels)."""
        self._location_filter = state
        self._update_location_labels()
        self._apply_visibility_filters()

    def hpd_config(self) -> Optional[Any]:
        return self._hpd_config

    def sd_root(self) -> Optional[Path]:
        return self._sd_root

    def reemit_current_selection(self) -> None:
        """Re-fire :attr:`entrySelected` for the current row (profile swap)."""
        idx = self._view.currentIndex()
        if idx.isValid():
            self._on_current_changed(idx, None)

    def loaded_files(self) -> List[Any]:
        """Return every loaded HpdFile (caller iterates for save-all)."""
        return list(self._hpd_files.values())

    def has_unsaved_changes(self) -> bool:
        return any(getattr(f, "has_changes", False) for f in self._hpd_files.values())

    def try_load_from_card(self, sd_path: str, device_id: str = "") -> bool:
        """Load every state HPD under ``sd_path`` into the tree.

        Uses :class:`scanner_manager.HpdConfig` to enumerate state
        files via hpdb.cfg, then loads each ``s_*.hpd`` via
        :class:`scanner_manager.HpdFile`. Returns True if at least
        one file loaded.

        When ``device_id`` is supplied, a session cache keyed by
        ``(device_id, hpdb_dir, mtime fingerprint)`` can skip disk
        parse and Qt model rebuild on repeat loads.
        """
        from legacy_tk.scanner_manager import HpdConfig, HpdFile

        self._reset_load_state(sd_path)

        if not sd_path:
            return False

        hpdb_dir = self._resolve_hpdb_dir(Path(sd_path))
        if hpdb_dir is None:
            self._show_message_row(
                f"No HPDB folder found under {sd_path!r}. Point the device at the SD card root."
            )
            return False

        cached = get_hpdb_session_cache().get(device_id, hpdb_dir)
        if cached is not None:
            return self._restore_from_cache(cached)

        cfg = self._load_hpdb_config(hpdb_dir, HpdConfig)
        sources = self._enumerate_hpd_sources(hpdb_dir, cfg)
        if not sources:
            self._show_message_row(f"No s_*.hpd files in {hpdb_dir}")
            return False

        loaded = self._load_hpd_sources(sources, HpdFile)
        if loaded == 0:
            self._show_message_row(f"No HPDs could be parsed under {hpdb_dir}")
            return False

        get_hpdb_session_cache().put(
            device_id,
            hpdb_dir,
            self._hpd_files,
            self._hpd_config,
            self._model,
        )
        self._view.collapseAll()
        self._apply_visibility_filters()
        return True

    def invalidate_cache(
        self,
        device_id: Optional[str] = None,
        hpdb_dir: Optional[Path] = None,
    ) -> None:
        """Drop cached HPDB data (Wave 2: after save/reload)."""
        get_hpdb_session_cache().invalidate(device_id=device_id, hpdb_dir=hpdb_dir)

    def _reset_load_state(self, sd_path: str) -> None:
        self._hpd_files.clear()
        self._hpd_config = None
        self._sd_root = Path(sd_path) if sd_path else None
        self._model.removeRows(0, self._model.rowCount())

    def _restore_from_cache(self, cached: CachedHpdb) -> bool:
        self._hpd_files = cached.hpd_files
        self._hpd_config = cached.hpd_config
        self._model = cached.model
        self._view.setModel(self._model)
        self._view.collapseAll()
        self._apply_visibility_filters()
        return True

    def _resolve_hpdb_dir(self, root: Path) -> Optional[Path]:
        candidates = (
            root / "BCDx36HP" / "HPDB",
            root / "HPDB",
            root,
        )
        return next((c for c in candidates if c.exists() and c.is_dir()), None)

    def _load_hpdb_config(self, hpdb_dir: Path, hpd_config_cls) -> Optional[Any]:
        cfg_path = hpdb_dir / "hpdb.cfg"
        if not cfg_path.exists():
            return None
        cfg = hpd_config_cls()
        try:
            cfg.load(str(cfg_path))
            self._hpd_config = cfg
            return cfg
        except Exception as exc:
            logger.warning("Failed to parse hpdb.cfg: %s", exc)
            return None

    def _enumerate_hpd_sources(
        self, hpdb_dir: Path, cfg: Optional[Any]
    ) -> List[tuple]:
        if cfg and cfg.state_files:
            ordered_state_ids = sorted(
                cfg.state_files.keys(),
                key=lambda sid: cfg.get_state_name(sid).lower(),
            )
            return [(sid, cfg.state_files[sid]) for sid in ordered_state_ids]
        return [(i, str(p)) for i, p in enumerate(sorted(hpdb_dir.glob("s_*.hpd")))]

    def _load_hpd_sources(self, sources: List[tuple], hpd_file_cls) -> int:
        loaded = 0
        for state_id, hpd_path in sources:
            try:
                hpd = hpd_file_cls()
                hpd.load(hpd_path)
            except Exception as exc:
                logger.warning("Failed to parse %s: %s", hpd_path, exc)
                continue
            self._hpd_files[state_id] = hpd
            label = self._state_label(state_id, Path(hpd_path).name)
            self._append_state_row(state_id, label, hpd_path, hpd)
            loaded += 1
        return loaded

    # ------------------------------------------------------------------
    # Build the tree
    # ------------------------------------------------------------------

    def _state_label(self, state_id: int, fallback: str) -> str:
        if self._hpd_config and state_id in self._hpd_config.states:
            return self._hpd_config.get_state_name(state_id)
        return fallback

    def _append_state_row(
        self, state_id: int, label: str, hpd_path: str, hpd
    ) -> None:
        sys_count = len(hpd.systems)
        entry_count = sum(
            len(g.entries) for s in hpd.systems for g in s.groups
        )
        sub_label = f"{label}  ({sys_count} systems, {entry_count} entries)"

        items = self._make_row(sub_label, "", "", "", color=_COLOR_FILE, bold=True)
        items[0].setData(
            {
                "kind": "file",
                "state_id": state_id,
                "path": hpd_path,
                "hpd_file": hpd,
            },
            Qt.UserRole,
        )

        for sys_node in hpd.systems:
            items[0].appendRow(self._build_system_row(hpd, sys_node))

        self._model.appendRow(items)

    def _build_system_row(self, hpd, sys_node) -> List[QStandardItem]:
        kind_label = sys_node.system_type or "?"
        sys_prefix = "CONV" if sys_node.system_type == "Conventional" else "TRUNK"
        base_text = f"[{kind_label}] {sys_node.name}"
        sys_items = self._make_row(
            base_text,
            "",
            "",
            "",
            color=_COLOR_SYSTEM,
            bold=True,
        )
        sys_items[0].setData(
            {
                "kind": "system",
                "system": sys_node,
                "hpd_file": hpd,
                "base_label": base_text,
                "sys_prefix": sys_prefix,
            },
            Qt.UserRole,
        )

        for group in sys_node.groups:
            sys_items[0].appendRow(self._build_group_row(hpd, sys_node, group))

        # Sites for trunk systems
        for site in sys_node.sites:
            sys_items[0].appendRow(self._build_site_row(hpd, sys_node, site))

        return sys_items

    def _build_group_row(self, hpd, sys_node, group) -> List[QStandardItem]:
        base_text = group.name or "(unnamed group)"
        items = self._make_row(
            base_text,
            "",
            "",
            "",
            color=_COLOR_GROUP,
        )
        items[0].setData(
            {
                "kind": "group",
                "system": sys_node,
                "group": group,
                "hpd_file": hpd,
                "base_label": base_text,
            },
            Qt.UserRole,
        )
        for entry in group.entries:
            items[0].appendRow(self._build_entry_row(hpd, sys_node, group, entry))
        return items

    def _build_site_row(self, hpd, sys_node, site) -> List[QStandardItem]:
        items = self._make_row(
            f"Site: {site.name}",
            "",
            "",
            "",
            color=_COLOR_GROUP,
        )
        items[0].setData(
            {
                "kind": "site",
                "system": sys_node,
                "site": site,
                "hpd_file": hpd,
            },
            Qt.UserRole,
        )
        return items

    def _build_entry_row(self, hpd, sys_node, group, entry) -> List[QStandardItem]:
        # Frequency / TGID column
        if entry.entry_type == "C-Freq":
            freq_field = entry.record.get_field(5, "")
            try:
                freq_hz = int(freq_field)
                identity = f"{freq_hz / 1e6:.5f} MHz".rstrip("0").rstrip(".")
            except (TypeError, ValueError):
                identity = freq_field
            mode = entry.record.get_field(6, "")
        else:  # TGID
            identity = entry.record.get_field(5, "")
            mode = entry.record.get_field(6, "")

        service_label = ""
        if self._profile is not None:
            service_label = self._profile.service_label(entry.service_type) or ""
        if not service_label and entry.service_type is not None:
            service_label = str(entry.service_type)

        color = entry_row_color(self._profile, entry.service_type, mode)

        items = self._make_row(
            entry.name or "(unnamed entry)",
            identity,
            mode,
            service_label,
            color=color,
        )
        items[0].setData(
            {
                "kind": "entry",
                "system": sys_node,
                "group": group,
                "entry": entry,
                "hpd_file": hpd,
            },
            Qt.UserRole,
        )
        return items

    def _make_row(
        self,
        name: str,
        identity: str,
        mode: str,
        service: str,
        color: Optional[QColor] = None,
        bold: bool = False,
    ) -> List[QStandardItem]:
        items: List[QStandardItem] = []
        for value in (name, identity, mode, service):
            item = QStandardItem(value)
            item.setEditable(False)
            if color is not None:
                item.setForeground(QBrush(color))
            if bold:
                font = item.font()
                font.setBold(True)
                item.setFont(font)
            items.append(item)
        return items

    def _show_message_row(self, message: str) -> None:
        item = QStandardItem(message)
        item.setEditable(False)
        item.setForeground(QBrush(QColor("#666")))
        self._model.appendRow(
            [item, QStandardItem(""), QStandardItem(""), QStandardItem("")]
        )

    # ------------------------------------------------------------------
    # Selection + filtering
    # ------------------------------------------------------------------

    def _on_current_changed(self, current, _previous) -> None:
        if not current.isValid():
            return
        idx = current.siblingAtColumn(0)
        item = self._model.itemFromIndex(idx)
        if item is None:
            return
        payload = item.data(Qt.UserRole)
        if payload:
            self.entrySelected.emit(payload)

    def _on_search_changed(self, text: str) -> None:
        self._search_text = (text or "").strip().lower()
        # Rebuild the tree from in-memory hpd files - cheap; the
        # cardinality in HPDB is comfortably small (<5k entries even
        # for a fully-loaded SDS card).
        if not self._hpd_files:
            return
        self._refilter()

    def _refilter(self) -> None:
        self._apply_visibility_filters()

    def _apply_visibility_filters(self) -> None:
        root_idx = self._model.invisibleRootItem().index()
        for state_row in range(self._model.rowCount()):
            state_item = self._model.item(state_row)
            if state_item is not None:
                visible = self._apply_visibility_row(state_item)
                self._view.setRowHidden(state_row, root_idx, not visible)

    def _apply_visibility_row(self, item: QStandardItem) -> bool:
        payload = item.data(Qt.UserRole)
        kind = payload.get("kind") if isinstance(payload, dict) else None
        apply_location = self._location_filter_active()

        entry_result = self._visibility_entry_item(item, kind, payload)
        if entry_result is not None:
            return entry_result

        file_result = self._visibility_file_item(kind, payload, apply_location)
        if file_result is False:
            return False

        if self._visibility_leaf_blocked(kind, payload, apply_location):
            return False

        any_child_visible = self._apply_visibility_children(item)

        if kind == "system" and apply_location and not self._system_has_visible_group(
            item
        ):
            return False

        if not self._search_text:
            return any_child_visible or not item.hasChildren()

        return self._row_matches_search(item, any_child_visible)

    def _visibility_entry_item(
        self, item: QStandardItem, kind: Optional[str], payload: Any
    ) -> Optional[bool]:
        if kind != "entry" or not isinstance(payload, dict):
            return None
        entry = payload["entry"]
        mode = entry.record.get_field(6, "")
        visible = self._entry_visible(entry, mode)
        parent = item.parent() or self._model.invisibleRootItem()
        self._view.setRowHidden(item.row(), parent.index(), not visible)
        return visible

    def _visibility_file_item(
        self, kind: Optional[str], payload: Any, apply_location: bool
    ) -> Optional[bool]:
        if kind != "file" or not apply_location or self._location_filter is None:
            return None
        filter_state_id = self._location_filter.state_id
        if filter_state_id is not None and payload.get("state_id") != filter_state_id:
            return False
        return None

    def _visibility_leaf_blocked(
        self, kind: Optional[str], payload: Any, apply_location: bool
    ) -> bool:
        if kind == "system" and self._location_filter_blocks_system(payload):
            return True
        if kind == "group" and self._location_filter_blocks_group(payload):
            return True
        return kind == "site" and apply_location

    def _apply_visibility_children(self, item: QStandardItem) -> bool:
        any_child_visible = False
        for child_row in range(item.rowCount()):
            child = item.child(child_row, 0)
            if child is None:
                continue
            child_visible = self._apply_visibility_row(child)
            self._view.setRowHidden(child_row, item.index(), not child_visible)
            if child_visible:
                any_child_visible = True
        return any_child_visible

    def _row_matches_search(self, item: QStandardItem, any_child_visible: bool) -> bool:
        text = (item.text() or "").lower()
        ident_item = self._model.itemFromIndex(item.index().siblingAtColumn(1))
        if ident_item is not None:
            text = text + " " + (ident_item.text() or "").lower()
        return self._search_text in text or any_child_visible

    def _system_has_visible_group(self, system_item: QStandardItem) -> bool:
        for child_row in range(system_item.rowCount()):
            child = system_item.child(child_row, 0)
            if child is None:
                continue
            child_payload = child.data(Qt.UserRole)
            if not isinstance(child_payload, dict) or child_payload.get("kind") != "group":
                continue
            if not self._view.isRowHidden(child_row, system_item.index()):
                return True
        return False

    def _location_filter_active(self) -> bool:
        state = self._location_filter
        if state is None or not state.enabled:
            return False
        return state.county_id is not None or state.coords is not None

    def _location_filter_blocks_system(self, payload: dict) -> bool:
        if not self._location_filter_active():
            return False
        sys_node = payload.get("system")
        if sys_node is None or self._location_filter is None:
            return False
        return not system_matches_location(sys_node, self._location_filter)

    def _location_filter_blocks_group(self, payload: dict) -> bool:
        if not self._location_filter_active():
            return False
        state = self._location_filter
        if state is None or state.coords is None:
            return False
        group = payload.get("group")
        if group is None:
            return False
        tolerance = max(0.0, state.tolerance_mi)
        info = group_coverage_info(group, state.coords, tolerance)
        return info["status"] == "out_range"

    @staticmethod
    def _child_at(parent, row: int, col: int = 0) -> Optional[QStandardItem]:
        if isinstance(parent, QStandardItemModel):
            return parent.item(row, col)
        return parent.child(row, col)

    def _iter_child_items(self, parent, *, col: int = 0):
        for row in range(parent.rowCount()):
            item = self._child_at(parent, row, col)
            if item is not None:
                yield item

    def _iter_group_items(self):
        """Yield (sys_item, grp_item, grp_payload) for every group row."""
        for file_item in self._iter_child_items(self._model):
            for sys_item in self._iter_child_items(file_item):
                for grp_item in self._iter_child_items(sys_item):
                    grp_payload = grp_item.data(Qt.UserRole)
                    if not isinstance(grp_payload, dict) or grp_payload.get("kind") != "group":
                        continue
                    yield sys_item, grp_item, grp_payload

    def _update_location_labels(self) -> None:
        state = self._location_filter
        active = self._location_filter_active()
        for state_row in range(self._model.rowCount()):
            file_item = self._model.item(state_row, 0)
            if file_item is None:
                continue
            for sys_row in range(file_item.rowCount()):
                sys_item = file_item.child(sys_row, 0)
                if sys_item is None:
                    continue
                self._refresh_system_label(sys_item, state, active)
        for _sys_item, grp_item, grp_payload in self._iter_group_items():
            self._refresh_group_label(grp_item, grp_payload, state, active)

    def _refresh_system_label(
        self,
        sys_item: QStandardItem,
        state: Optional[LocationFilterState],
        active: bool,
    ) -> None:
        payload = sys_item.data(Qt.UserRole)
        if not isinstance(payload, dict):
            return
        base = payload.get("base_label") or sys_item.text()
        if not active or state is None or state.coords is None:
            sys_item.setText(base)
            return
        sys_node = payload.get("system")
        if sys_node is None:
            sys_item.setText(base)
            return
        distance = nearest_distance_miles(sys_node, state.coords[0], state.coords[1])
        if distance is not None:
            sys_item.setText(f"{base} ({distance:.1f} mi)")
        else:
            sys_item.setText(base)

    def _refresh_group_label(
        self,
        grp_item: QStandardItem,
        payload: dict,
        state: Optional[LocationFilterState],
        active: bool,
    ) -> None:
        base = payload.get("base_label") or grp_item.text()
        if not active or state is None or state.coords is None:
            grp_item.setText(base)
            return
        group = payload.get("group")
        if group is None:
            grp_item.setText(base)
            return
        tolerance = max(0.0, state.tolerance_mi)
        info = group_coverage_info(group, state.coords, tolerance)
        if info["has_geo"] and info.get("distance") is not None:
            if info["range_miles"] is not None:
                grp_item.setText(
                    f"{base}  "
                    f"[{info['distance']:.1f} mi / {info['range_miles']:.1f} mi range]"
                )
            else:
                grp_item.setText(f"{base}  [{info['distance']:.1f} mi]")
        else:
            grp_item.setText(base)

    def _entry_visible(self, entry, mode: str) -> bool:
        if self._search_text and not self._entry_matches_search(entry, mode):
            return False
        if (
            self._active_buttons is not None
            and self._profile is not None
            and self._profile.uses_hardware_button_semantics
        ):
            return entry_passes_button_filter(
                entry.service_type,
                self._active_buttons,
                self._profile,
                include_others=self._include_others,
            )
        return True

    def _entry_matches_search(self, entry, mode: str) -> bool:
        blob = " ".join(
            [
                entry.name or "",
                entry.record.get_field(5, "") or "",
                mode or "",
                str(entry.service_type or ""),
            ]
        ).lower()
        if self._search_text in blob:
            return True
        if self._profile is None:
            return False
        label = self._profile.service_label(entry.service_type) or ""
        return self._search_text in label.lower()

    def _restore_all(self) -> None:
        self._apply_visibility_filters()
