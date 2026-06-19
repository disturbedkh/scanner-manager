"""Qt port of the ChangesPanelDialog.

Surfaces the metastore event log for the active HPD file in a sortable
table. Lets the user filter by op + revert individual events.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

import core.metastore as metastore

logger = logging.getLogger(__name__)


class ChangesPanelDialog(QDialog):
    """Show + filter the metastore event log for one HPD file."""

    eventReverted = Signal(str)  # event_id

    OP_FILTER_OPTIONS = (
        "All",
        "edit_entry",
        "delete_entry",
        "create_entry",
        "edit_group",
        "create_group",
        "delete_group",
        "rr_import",
    )

    def __init__(self, hpd_path: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Changes - {Path(hpd_path).name}")
        self.resize(820, 540)
        self._hpd_path = hpd_path
        self._store: Optional[metastore.MetaStore] = None
        try:
            self._store = metastore.MetaStore.load_for(hpd_path)
        except Exception:
            try:
                self._store = metastore.MetaStore(hpd_path)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not open metastore for %s: %s", hpd_path, exc)
                self._store = None
        self._build_ui()
        self._refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        header = QHBoxLayout()
        header.addWidget(QLabel("Filter:"))
        self._filter = QComboBox()
        self._filter.addItems(self.OP_FILTER_OPTIONS)
        self._filter.currentIndexChanged.connect(self._refresh)
        header.addWidget(self._filter)
        header.addStretch(1)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._refresh)
        header.addWidget(refresh_btn)
        layout.addLayout(header)

        self._table = QTableWidget(0, 5, self)
        self._table.setHorizontalHeaderLabels(
            ["Timestamp", "Op", "Target", "Summary", "Reverted"]
        )
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self._table, 1)

        button_row = QHBoxLayout()
        revert_btn = QPushButton("Mark selected reverted")
        revert_btn.clicked.connect(self._on_revert)
        button_row.addWidget(revert_btn)
        button_row.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        button_row.addWidget(close_btn)
        layout.addLayout(button_row)

    def _refresh(self) -> None:
        self._table.setRowCount(0)
        if self._store is None:
            self._table.setRowCount(1)
            for col, txt in enumerate(["(no metastore loaded)", "", "", "", ""]):
                self._table.setItem(0, col, QTableWidgetItem(txt))
            return
        op_filter = self._filter.currentText()
        events = list(self._iter_events())
        if op_filter and op_filter != "All":
            events = [e for e in events if getattr(e, "op", "") == op_filter]
        events.sort(key=lambda e: getattr(e, "ts", ""), reverse=True)
        self._table.setRowCount(len(events))
        for row, e in enumerate(events):
            self._table.setItem(row, 0, QTableWidgetItem(getattr(e, "ts", "")))
            self._table.setItem(row, 1, QTableWidgetItem(getattr(e, "op", "")))
            self._table.setItem(row, 2, QTableWidgetItem(str(getattr(e, "target_id", ""))))
            self._table.setItem(row, 3, QTableWidgetItem(getattr(e, "summary", "")))
            reverted = getattr(e, "reverted", False)
            self._table.setItem(row, 4, QTableWidgetItem("yes" if reverted else ""))
            # Stash the event_id for revert
            self._table.item(row, 0).setData(Qt.UserRole, getattr(e, "event_id", ""))

    def _iter_events(self):
        store = self._store
        if store is None:
            return []
        # MetaStore exposes events as a list-like attribute or via a method.
        events = getattr(store, "events", None)
        if events is None:
            events = getattr(store, "all_events", lambda: [])()
        return events

    def _on_revert(self) -> None:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return
        event_id = self._table.item(rows[0].row(), 0).data(Qt.UserRole)
        if not event_id or self._store is None:
            return
        confirm = QMessageBox.question(
            self, "Mark reverted",
            f"Mark event {event_id} as reverted in the change log?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            mark = getattr(self._store, "mark_reverted", None)
            if callable(mark):
                mark(event_id)
                save = getattr(self._store, "save", None)
                if callable(save):
                    save()
            self.eventReverted.emit(event_id)
            self._refresh()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Revert failed", str(exc))
