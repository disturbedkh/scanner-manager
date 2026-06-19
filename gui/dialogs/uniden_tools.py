"""Qt port of the UnidenToolsDialog.

Lists detected Uniden ecosystem apps (BT885 Update Manager, BCDx36HP
Sentinel) so the user can launch them directly or install the bundled
copies. All detection / install logic delegates to the existing
:mod:`uniden_tools` module, so this is a UI-only wrapper.
"""

from __future__ import annotations

import logging
from typing import List

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
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

import core.uniden_tools as uniden_tools

logger = logging.getLogger(__name__)


class UnidenToolsDialog(QDialog):
    """Detect, install, and launch the Uniden desktop ecosystem apps."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Uniden tools")
        self.resize(720, 420)
        self._tools: List[uniden_tools.UnidenTool] = []
        self._build_ui()
        self._refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<b>Uniden ecosystem apps</b>"))
        layout.addWidget(QLabel(
            "We auto-detect installed Sentinel + BT885 Update Manager. "
            "Use the bundled installers if you don't have them yet."
        ))

        self._table = QTableWidget(0, 4, self)
        self._table.setHorizontalHeaderLabels(["Tool", "Family", "Installed", "Version"])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self._table, 1)

        button_row = QHBoxLayout()
        run_btn = QPushButton("Launch selected")
        run_btn.clicked.connect(self._on_launch)
        button_row.addWidget(run_btn)

        install_btn = QPushButton("Install bundled…")
        install_btn.clicked.connect(self._on_install)
        button_row.addWidget(install_btn)

        refresh_btn = QPushButton("Re-detect")
        refresh_btn.clicked.connect(self._refresh)
        button_row.addWidget(refresh_btn)

        button_row.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        button_row.addWidget(close_btn)
        layout.addLayout(button_row)

    def _refresh(self) -> None:
        try:
            self._tools = uniden_tools.detect_installed_tools()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Tool detection failed: %s", exc)
            self._tools = []
        self._table.setRowCount(0)
        for t in self._tools:
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, QTableWidgetItem(t.display_name))
            self._table.setItem(row, 1, QTableWidgetItem(t.scanner_family))
            self._table.setItem(row, 2, QTableWidgetItem("yes" if t.installed else "no"))
            self._table.setItem(row, 3, QTableWidgetItem(t.version or ""))
            self._table.item(row, 0).setData(Qt.UserRole, t)

    def _selected(self):
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return None
        return self._table.item(rows[0].row(), 0).data(Qt.UserRole)

    def _on_launch(self) -> None:
        tool = self._selected()
        if tool is None:
            return
        if not tool.installed or not tool.exe_path:
            QMessageBox.information(
                self, "Not installed",
                f"{tool.display_name} isn't installed on this machine."
            )
            return
        try:
            uniden_tools.run_tool(tool)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Launch failed", str(exc))

    def _on_install(self) -> None:
        tool = self._selected()
        if tool is None:
            return
        if not tool.bundled_installer:
            QMessageBox.information(
                self, "No bundled installer",
                f"No bundled installer for {tool.display_name}."
            )
            return
        confirm = QMessageBox.question(
            self, "Install",
            f"Run the bundled installer for {tool.display_name}?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            uniden_tools.install_tool(tool, wait=False)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Install failed", str(exc))
            return
        self._refresh()
