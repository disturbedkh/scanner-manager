"""Qt port of the CityManagerDialog.

Manages user-supplied ZIP/county overrides used by the coverage
heatmap when the bundled ``zip_county_map.json`` is missing an entry.
The on-disk format mirrors the legacy Tk dialog so both shells can
share the same overrides file during the transition.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Dict, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

logger = logging.getLogger(__name__)


def _city_overrides_path() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    return base / "scanner-manager" / "city_overrides.json"


def load_overrides(path: Optional[Path] = None) -> Dict[str, Dict]:
    target = Path(path) if path else _city_overrides_path()
    if not target.exists():
        return {}
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    return {k: v for k, v in raw.items() if isinstance(v, dict)}


def save_overrides(overrides: Dict[str, Dict], path: Optional[Path] = None) -> None:
    target = Path(path) if path else _city_overrides_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(overrides, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, target)


class CityManagerDialog(QDialog):
    """Edit user ZIP -> {city, state, lat, lon, county} overrides."""

    def __init__(self, parent=None, path: Optional[Path] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("City overrides")
        self.resize(720, 500)
        self._path = Path(path) if path else _city_overrides_path()
        self._overrides = load_overrides(self._path)
        self._build_ui()
        self._refresh_table()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<b>ZIP / city / county overrides</b>"))
        layout.addWidget(QLabel(
            "Add custom ZIP entries the bundled lookup table doesn't know "
            "about, or correct existing ones."
        ))

        # Add row form
        form = QFormLayout()
        self._zip_field = QLineEdit()
        form.addRow("ZIP:", self._zip_field)
        self._city_field = QLineEdit()
        form.addRow("City:", self._city_field)
        self._state_field = QLineEdit()
        form.addRow("State:", self._state_field)
        self._county_field = QLineEdit()
        form.addRow("County:", self._county_field)
        self._lat_field = QDoubleSpinBox()
        self._lat_field.setRange(-90.0, 90.0)
        self._lat_field.setDecimals(5)
        form.addRow("Latitude:", self._lat_field)
        self._lon_field = QDoubleSpinBox()
        self._lon_field.setRange(-180.0, 180.0)
        self._lon_field.setDecimals(5)
        form.addRow("Longitude:", self._lon_field)
        layout.addLayout(form)

        button_row = QHBoxLayout()
        add_btn = QPushButton("Add / update")
        add_btn.clicked.connect(self._on_add)
        button_row.addWidget(add_btn)

        delete_btn = QPushButton("Delete selected")
        delete_btn.clicked.connect(self._on_delete)
        button_row.addWidget(delete_btn)

        button_row.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        button_row.addWidget(close_btn)
        layout.addLayout(button_row)

        self._table = QTableWidget(0, 6, self)
        self._table.setHorizontalHeaderLabels(
            ["ZIP", "City", "State", "County", "Lat", "Lon"]
        )
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.itemSelectionChanged.connect(self._on_selection)
        layout.addWidget(self._table, 1)

    def _refresh_table(self) -> None:
        self._table.setRowCount(0)
        for zip_code in sorted(self._overrides.keys()):
            entry = self._overrides[zip_code]
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, QTableWidgetItem(zip_code))
            self._table.setItem(row, 1, QTableWidgetItem(str(entry.get("city", ""))))
            self._table.setItem(row, 2, QTableWidgetItem(str(entry.get("state", ""))))
            self._table.setItem(row, 3, QTableWidgetItem(str(entry.get("county", ""))))
            self._table.setItem(row, 4, QTableWidgetItem(f"{entry.get('lat', '')}"))
            self._table.setItem(row, 5, QTableWidgetItem(f"{entry.get('lon', '')}"))

    def _on_add(self) -> None:
        zip_code = self._zip_field.text().strip()
        if not zip_code:
            QMessageBox.warning(self, "Missing ZIP", "Enter a ZIP code first.")
            return
        self._overrides[zip_code] = {
            "city": self._city_field.text().strip(),
            "state": self._state_field.text().strip(),
            "county": self._county_field.text().strip(),
            "lat": float(self._lat_field.value()),
            "lon": float(self._lon_field.value()),
        }
        try:
            save_overrides(self._overrides, self._path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Save failed", str(exc))
            return
        self._refresh_table()

    def _on_delete(self) -> None:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return
        zip_code = self._table.item(rows[0].row(), 0).text()
        if zip_code in self._overrides:
            del self._overrides[zip_code]
            try:
                save_overrides(self._overrides, self._path)
            except Exception as exc:  # noqa: BLE001
                QMessageBox.critical(self, "Save failed", str(exc))
                return
        self._refresh_table()

    def _on_selection(self) -> None:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return
        row = rows[0].row()
        self._zip_field.setText(self._table.item(row, 0).text())
        self._city_field.setText(self._table.item(row, 1).text())
        self._state_field.setText(self._table.item(row, 2).text())
        self._county_field.setText(self._table.item(row, 3).text())
        try:
            self._lat_field.setValue(float(self._table.item(row, 4).text() or 0))
        except ValueError:
            self._lat_field.setValue(0.0)
        try:
            self._lon_field.setValue(float(self._table.item(row, 5).text() or 0))
        except ValueError:
            self._lon_field.setValue(0.0)
