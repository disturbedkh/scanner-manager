"""BT885 location simulation bar for the editor dock.

ZIP / county / GPS controls that drive the HPDB tree location filter and
coverage map center. ZIP lookup mirrors legacy ``_on_zip_lookup`` in
:mod:`legacy_tk.scanner_manager`.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, List, Optional, Tuple

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QWidget,
)

from legacy_tk.scanner_manager import (
    FirmwareZipTable,
    bundled_resources_dir,
)

from .location_filter import LocationFilterState, ZipCountyLookup

_AUTO_COUNTY = "(Auto from ZIP)"


def _app_script_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


class LocationSimBar(QWidget):
    """ZIP / GPS simulation toolbar for BT885 editor layout."""

    locationFilterChanged = Signal(object)  # LocationFilterState

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self._config: Optional[Any] = None
        self._sd_root: Optional[Path] = None
        self._zip_lookup = ZipCountyLookup(
            _app_script_dir(),
            bundled_dir=bundled_resources_dir(),
        )
        self._firmware_zip_table = FirmwareZipTable()
        self._firmware_zip_loaded = False

        self._active_zip: Optional[str] = None
        self._active_county_id: Optional[int] = None
        self._active_coords: Optional[Tuple[float, float]] = None
        self._state_id: Optional[int] = None
        self._county_choices: List[Tuple[int, str]] = []
        self._updating = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(6)

        layout.addWidget(QLabel("ZIP:"))
        self._zip_field = QLineEdit()
        self._zip_field.setMaxLength(10)
        self._zip_field.setFixedWidth(72)
        layout.addWidget(self._zip_field)

        lookup_btn = QPushButton("Lookup")
        lookup_btn.clicked.connect(self._on_zip_lookup)
        layout.addWidget(lookup_btn)

        layout.addWidget(QLabel("County:"))
        self._county_combo = QComboBox()
        self._county_combo.setMinimumWidth(180)
        self._county_combo.addItem(_AUTO_COUNTY)
        self._county_combo.currentIndexChanged.connect(self._on_county_changed)
        layout.addWidget(self._county_combo)

        self._filter_enabled = QCheckBox("Apply location filter")
        self._filter_enabled.toggled.connect(self._on_controls_changed)
        layout.addWidget(self._filter_enabled)

        layout.addWidget(QLabel("Extra mi:"))
        self._tolerance_spin = QSpinBox()
        self._tolerance_spin.setRange(0, 200)
        self._tolerance_spin.setSingleStep(5)
        self._tolerance_spin.valueChanged.connect(self._on_controls_changed)
        layout.addWidget(self._tolerance_spin)

        layout.addWidget(QLabel("Lat:"))
        self._lat_spin = QDoubleSpinBox()
        self._lat_spin.setRange(-90.0, 90.0)
        self._lat_spin.setDecimals(6)
        self._lat_spin.setValue(34.0522)
        self._lat_spin.valueChanged.connect(self._on_lat_lon_changed)
        layout.addWidget(self._lat_spin)

        layout.addWidget(QLabel("Lon:"))
        self._lon_spin = QDoubleSpinBox()
        self._lon_spin.setRange(-180.0, 180.0)
        self._lon_spin.setDecimals(6)
        self._lon_spin.setValue(-118.2437)
        self._lon_spin.valueChanged.connect(self._on_lat_lon_changed)
        layout.addWidget(self._lon_spin)

        self._status_label = QLabel("")
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label, stretch=1)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_hpdb_context(self, config: Any, sd_root: Optional[Path]) -> None:
        """Attach HPDB config + SD root; refresh county list."""
        self._config = config
        self._sd_root = Path(sd_root) if sd_root is not None else None
        if self._sd_root is not None:
            self._load_firmware_zip_table(self._sd_root)
        self._refresh_county_options()

    def current_state(self) -> LocationFilterState:
        return LocationFilterState(
            enabled=self._filter_enabled.isChecked(),
            zip_code=self._active_zip or "",
            county_id=self._active_county_id,
            coords=self._active_coords,
            tolerance_mi=float(self._tolerance_spin.value()),
            state_id=self._state_id,
        )

    # ------------------------------------------------------------------
    # ZIP / county handlers (legacy parity)
    # ------------------------------------------------------------------

    def _on_zip_lookup(self) -> None:
        zip_code = self._zip_field.text().strip()
        normalized = self._zip_lookup.normalize_zip(zip_code)
        if len(normalized) != 5:
            QMessageBox.warning(self, "ZIP Code", "Enter a valid 5-digit ZIP code.")
            return
        if self._config is None:
            QMessageBox.warning(
                self,
                "ZIP Code",
                "Load HPDB first (hpdb.cfg + state files).",
            )
            return

        if self._sd_root is not None:
            self._load_firmware_zip_table(self._sd_root)

        preferred_state_id = self._state_id_from_firmware_zip(normalized)
        coords = self._firmware_zip_table.coords_for_zip(normalized)
        self._active_coords = coords

        match = self._zip_lookup.resolve(
            normalized,
            self._config,
            preferred_state_id=preferred_state_id,
        )
        self._active_zip = normalized
        if not match and preferred_state_id is not None:
            match = {
                "state_id": preferred_state_id,
                "county_id": None,
                "county_name": "",
                "source": "firmware-only",
            }
        if not match:
            self._active_county_id = None
            self._state_id = None
            self._status_label.setText(
                f"Could not resolve ZIP {normalized}. "
                "Verify internet access or provide zip_county_map.json."
            )
            self._emit_filter_changed(preserve_status=True)
            return

        state_id = match["state_id"]
        county_id = match["county_id"]
        self._state_id = state_id if isinstance(state_id, int) else None
        self._refresh_county_options()
        self._active_county_id = county_id if isinstance(county_id, int) else None
        if self._active_county_id is not None:
            self._set_county_combo_to_id(self._active_county_id)
        else:
            self._set_county_combo_auto()

        self._updating = True
        try:
            self._filter_enabled.setChecked(True)
            if coords is not None:
                self._lat_spin.setValue(coords[0])
                self._lon_spin.setValue(coords[1])
        finally:
            self._updating = False

        source = match.get("source", "local")
        county_name = match.get("county_name")
        coord_text = ""
        if coords:
            coord_text = f" @ ({coords[0]:.3f}, {coords[1]:.3f})"
        if self._active_county_id is not None:
            county_name = county_name or f"CountyId {self._active_county_id}"
            msg = (
                f"ZIP {normalized} resolved to {county_name} ({source})"
                f"{coord_text}; showing effective scan set."
            )
        else:
            msg = (
                f"ZIP {normalized} resolved state via {source}{coord_text}; "
                "showing effective scan set by coverage."
            )
        self._status_label.setText(msg)
        self._emit_filter_changed(preserve_status=True)

    def _on_county_changed(self, _index: int) -> None:
        if self._updating:
            return
        selected = self._county_combo.currentText()
        if selected == _AUTO_COUNTY:
            if self._active_zip and self._config is not None:
                match = self._zip_lookup.resolve(self._active_zip, self._config)
                self._active_county_id = match["county_id"] if match else None
            else:
                self._active_county_id = None
        else:
            for county_id, name in self._county_choices:
                if name == selected:
                    self._active_county_id = county_id
                    break
        self._emit_filter_changed()

    def _on_lat_lon_changed(self, _value: float) -> None:
        if self._updating:
            return
        self._active_coords = (self._lat_spin.value(), self._lon_spin.value())
        self._emit_filter_changed()

    def _on_controls_changed(self, *_args) -> None:
        if self._updating:
            return
        self._emit_filter_changed()

    def _emit_filter_changed(self, *, preserve_status: bool = False) -> None:
        if not preserve_status:
            self._update_filter_status()
        self.locationFilterChanged.emit(self.current_state())

    def _update_filter_status(self) -> None:
        if not self._filter_enabled.isChecked():
            return
        parts = ["Location filter enabled"]
        if self._active_zip:
            parts.append(f"ZIP {self._active_zip}")
        if self._active_county_id:
            county_name = next(
                (
                    name
                    for cid, name in self._county_choices
                    if cid == self._active_county_id
                ),
                f"CountyId {self._active_county_id}",
            )
            parts.append(county_name)
        self._status_label.setText(" | ".join(parts))

    def _refresh_county_options(self) -> None:
        self._updating = True
        try:
            current = self._county_combo.currentText()
            self._county_combo.clear()
            self._county_combo.addItem(_AUTO_COUNTY)
            self._county_choices = []
            sid = self._state_id
            if sid is not None and self._config is not None:
                self._county_choices = self._config.get_counties_for_state(sid)
                for _, name in self._county_choices:
                    self._county_combo.addItem(name)
            names = [
                self._county_combo.itemText(i)
                for i in range(self._county_combo.count())
            ]
            if current in names:
                self._county_combo.setCurrentText(current)
            else:
                self._county_combo.setCurrentIndex(0)
        finally:
            self._updating = False

    def _set_county_combo_to_id(self, county_id: int) -> None:
        for cid, name in self._county_choices:
            if cid == county_id:
                self._updating = True
                try:
                    self._county_combo.setCurrentText(name)
                finally:
                    self._updating = False
                return
        self._set_county_combo_auto()

    def _set_county_combo_auto(self) -> None:
        self._updating = True
        try:
            self._county_combo.setCurrentIndex(0)
        finally:
            self._updating = False

    def _load_firmware_zip_table(self, sd_root: Path) -> None:
        if self._firmware_zip_loaded:
            return
        self._firmware_zip_loaded = self._firmware_zip_table.load_from_sd(str(sd_root))

    def _state_id_from_firmware_zip(self, zip_code: str) -> Optional[int]:
        abbrev = self._firmware_zip_table.state_abbrev_for_zip(zip_code)
        if not abbrev or self._config is None:
            return None
        for sid, (_, state_abbrev) in self._config.states.items():
            if state_abbrev.upper() == abbrev.upper():
                return sid
        return None
