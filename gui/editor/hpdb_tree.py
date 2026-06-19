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
from typing import Any, Dict, List, Optional

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

logger = logging.getLogger(__name__)


# Color tokens shared with the legacy Tk app so users see the same
# visual cues (scannable green, non-scannable orange, encrypted red).
_COLOR_SCANNABLE = QColor("#196f3d")
_COLOR_NONSCAN = QColor("#a04000")
_COLOR_ENCRYPTED = QColor("#922b21")
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

    def loaded_files(self) -> List[Any]:
        """Return every loaded HpdFile (caller iterates for save-all)."""
        return list(self._hpd_files.values())

    def has_unsaved_changes(self) -> bool:
        return any(getattr(f, "has_changes", False) for f in self._hpd_files.values())

    def try_load_from_card(self, sd_path: str) -> bool:
        """Load every state HPD under ``sd_path`` into the tree.

        Uses :class:`scanner_manager.HpdConfig` to enumerate state
        files via hpdb.cfg, then loads each ``s_*.hpd`` via
        :class:`scanner_manager.HpdFile`. Returns True if at least
        one file loaded.
        """
        from scanner_manager import HpdConfig, HpdFile

        self._hpd_files.clear()
        self._hpd_config = None
        self._sd_root = Path(sd_path) if sd_path else None
        self._model.removeRows(0, self._model.rowCount())

        if not sd_path:
            return False

        root = Path(sd_path)
        candidates = (
            root / "BCDx36HP" / "HPDB",
            root / "HPDB",
            root,
        )
        hpdb_dir = next((c for c in candidates if c.exists() and c.is_dir()), None)
        if hpdb_dir is None:
            self._show_message_row(
                f"No HPDB folder found under {sd_path!r}. Point the device at the SD card root."
            )
            return False

        cfg_path = hpdb_dir / "hpdb.cfg"
        if cfg_path.exists():
            cfg = HpdConfig()
            try:
                cfg.load(str(cfg_path))
                self._hpd_config = cfg
            except Exception as exc:
                logger.warning("Failed to parse hpdb.cfg: %s", exc)

        # Enumerate state HPDs the same way the Tk app does.
        if self._hpd_config and self._hpd_config.state_files:
            ordered_state_ids = sorted(
                self._hpd_config.state_files.keys(),
                key=lambda sid: self._hpd_config.get_state_name(sid).lower(),
            )
            sources = [
                (sid, self._hpd_config.state_files[sid]) for sid in ordered_state_ids
            ]
        else:
            sources = [
                (i, str(p))
                for i, p in enumerate(sorted(hpdb_dir.glob("s_*.hpd")))
            ]

        if not sources:
            self._show_message_row(f"No s_*.hpd files in {hpdb_dir}")
            return False

        for state_id, hpd_path in sources:
            try:
                hpd = HpdFile()
                hpd.load(hpd_path)
            except Exception as exc:
                logger.warning("Failed to parse %s: %s", hpd_path, exc)
                continue
            self._hpd_files[state_id] = hpd
            label = self._state_label(state_id, Path(hpd_path).name)
            self._append_state_row(state_id, label, hpd_path, hpd)

        if not self._hpd_files:
            self._show_message_row(f"No HPDs could be parsed under {hpdb_dir}")
            return False

        self._view.expandToDepth(0)
        return True

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
        sys_items = self._make_row(
            f"[{kind_label}] {sys_node.name}",
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
        items = self._make_row(
            group.name or "(unnamed group)",
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

        scannable = (
            self._profile is not None
            and entry.service_type in self._profile.scannable_service_types()
        )
        encrypted_mode = (mode or "").upper() in {"DE", "TE", "AE"}

        if encrypted_mode:
            color = _COLOR_ENCRYPTED
        elif scannable:
            color = _COLOR_SCANNABLE
        else:
            color = _COLOR_NONSCAN

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
        # We re-walk the QStandardItemModel and hide rows whose
        # cumulative children don't contain the search text. This is
        # bog-standard tree filtering.
        if not self._search_text:
            self._restore_all()
            return
        for state_row in range(self._model.rowCount()):
            state_item = self._model.item(state_row)
            self._filter_row(state_item)

    def _filter_row(self, item: QStandardItem) -> bool:
        text = (item.text() or "").lower()
        sibling_index = item.index()
        # Pull the identity column too
        ident_item = self._model.itemFromIndex(sibling_index.siblingAtColumn(1))
        if ident_item is not None:
            text = text + " " + (ident_item.text() or "").lower()

        any_child_matches = False
        for child_row in range(item.rowCount()):
            child = item.child(child_row, 0)
            child_match = self._filter_row(child) if child else False
            self._view.setRowHidden(child_row, item.index(), not child_match)
            if child_match:
                any_child_matches = True

        self_match = self._search_text in text
        return self_match or any_child_matches

    def _restore_all(self) -> None:
        for state_row in range(self._model.rowCount()):
            state_item = self._model.item(state_row)
            self._restore_subtree(state_item)

    def _restore_subtree(self, item: QStandardItem) -> None:
        for child_row in range(item.rowCount()):
            self._view.setRowHidden(child_row, item.index(), False)
            child = item.child(child_row, 0)
            if child is not None:
                self._restore_subtree(child)
