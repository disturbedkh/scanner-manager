"""Coverage panel: ZIP/GPS sim + heatmap + map.

Two visualisations:

- :class:`CoverageHeatmapWidget` - pyqtgraph-rendered density of
  scannable groups by lat/lon. Uses the existing ``coverage_maps``
  helpers to compute the matrix.
- :class:`CoverageMapView` - real tile-server map via QtWebEngine +
  Leaflet (the Tk app uses ``tkintermapview``). Falls back to a
  text label when QtWebEngine isn't installed.
"""

from __future__ import annotations

import json
import logging
from typing import Any, List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)

# Optional pyqtgraph for heatmap
try:
    import numpy as np  # noqa: F401
    import pyqtgraph as pg
    HAS_PYQTGRAPH = True
except Exception:  # pragma: no cover - optional dep
    HAS_PYQTGRAPH = False

# Optional QtWebEngine for the Leaflet map
try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
    HAS_WEBENGINE = True
except Exception:  # pragma: no cover - optional dep
    HAS_WEBENGINE = False


_LEAFLET_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8" />
    <title>Coverage</title>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <style>
        html, body, #map { height: 100%; margin: 0; padding: 0; }
        body { background: #1e1e1e; }
    </style>
</head>
<body>
<div id="map"></div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
    const map = L.map('map').setView([__LAT__, __LON__], __ZOOM__);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 18,
        attribution: '© OpenStreetMap'
    }).addTo(map);

    const data = __DATA_JSON__;
    const layer = L.layerGroup().addTo(map);

    function rebuild() {
        layer.clearLayers();
        for (const item of data) {
            if (item.kind === 'circle') {
                L.circle([item.lat, item.lon], {
                    radius: item.radius_m,
                    color: item.color || '#4dabf7',
                    weight: 1,
                    fillOpacity: 0.15
                }).bindTooltip(item.label || '').addTo(layer);
            } else if (item.kind === 'rectangle') {
                L.rectangle([
                    [item.lat1, item.lon1], [item.lat2, item.lon2]
                ], { color: '#a3e635', weight: 1, fillOpacity: 0.15 })
                .bindTooltip(item.label || '').addTo(layer);
            } else if (item.kind === 'marker') {
                L.marker([item.lat, item.lon])
                    .bindTooltip(item.label || '')
                    .addTo(layer);
            }
        }
        if (data.length > 0) {
            try {
                const bounds = layer.getBounds();
                if (bounds.isValid()) map.fitBounds(bounds, {padding: [20, 20]});
            } catch (e) { /* ignore */ }
        }
    }
    rebuild();
</script>
</body>
</html>
"""


class CoverageHeatmapWidget(QWidget):
    """pyqtgraph heatmap of group densities on a lat/lon grid."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        if not HAS_PYQTGRAPH:
            msg = QLabel(
                "Install pyqtgraph + numpy for the coverage heatmap:\n"
                "    pip install pyqtgraph numpy"
            )
            msg.setAlignment(Qt.AlignCenter)
            layout.addWidget(msg)
            self._plot = None
            self._image_item = None
            return

        self._plot = pg.PlotWidget()
        self._plot.setLabel("left", "Latitude")
        self._plot.setLabel("bottom", "Longitude")
        self._plot.setBackground(None)
        self._plot.invertY(False)
        self._image_item = pg.ImageItem()
        self._plot.addItem(self._image_item)
        layout.addWidget(self._plot)

    def set_groups(self, groups: List[Tuple[float, float, float]]) -> None:
        """Render groups as a 2-D density on a 64x64 grid.

        ``groups`` is a list of ``(lat, lon, weight)``. Empty list
        clears the plot.
        """
        if not HAS_PYQTGRAPH or self._image_item is None:
            return
        import numpy as np

        if not groups:
            self._image_item.clear()
            return

        lats = np.array([g[0] for g in groups])
        lons = np.array([g[1] for g in groups])
        weights = np.array([g[2] for g in groups])

        # Auto-bound the grid with a small pad
        lat_min, lat_max = float(lats.min()) - 0.25, float(lats.max()) + 0.25
        lon_min, lon_max = float(lons.min()) - 0.25, float(lons.max()) + 0.25
        if lat_max - lat_min < 0.01:
            lat_max = lat_min + 0.01
        if lon_max - lon_min < 0.01:
            lon_max = lon_min + 0.01

        bins = 64
        h, _, _ = np.histogram2d(
            lats, lons,
            bins=bins,
            range=[[lat_min, lat_max], [lon_min, lon_max]],
            weights=weights,
        )

        # Display: pyqtgraph treats the array as (x, y), so transpose
        self._image_item.setImage(h.T, autoLevels=True)
        # Map image pixel coords back to (lon, lat) display coords
        self._image_item.setRect(
            pg.QtCore.QRectF(
                lon_min,
                lat_min,
                lon_max - lon_min,
                lat_max - lat_min,
            )
        )
        self._plot.autoRange()


class CoverageMapView(QWidget):
    """Leaflet-backed map view (or a text fallback)."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._stack = QStackedWidget()
        layout.addWidget(self._stack)

        if HAS_WEBENGINE:
            self._view = QWebEngineView()
            self._stack.addWidget(self._view)
        else:
            placeholder = QLabel(
                "Install PySide6-Addons for the QtWebEngine map view, or use the\n"
                "heatmap tab. The coverage map renders OpenStreetMap tiles via\n"
                "Leaflet inside QWebEngineView."
            )
            placeholder.setAlignment(Qt.AlignCenter)
            placeholder.setWordWrap(True)
            self._stack.addWidget(placeholder)
            self._view = None

        self.set_view(34.0, -118.0, zoom=4, items=[])

    def set_view(
        self,
        lat: float,
        lon: float,
        zoom: int = 6,
        items: Optional[List[dict]] = None,
    ) -> None:
        """Render a fresh map centered on (lat, lon).

        ``items`` is a list of dicts. Each item is one of:
        - ``{"kind": "circle", "lat": ..., "lon": ..., "radius_m": ...,
            "label": ..., "color": ...}``
        - ``{"kind": "rectangle", "lat1": ..., "lon1": ..., "lat2": ...,
            "lon2": ..., "label": ...}``
        - ``{"kind": "marker", "lat": ..., "lon": ..., "label": ...}``
        """
        if self._view is None:
            return
        items = items or []
        html = (
            _LEAFLET_HTML
            .replace("__LAT__", str(lat))
            .replace("__LON__", str(lon))
            .replace("__ZOOM__", str(zoom))
            .replace("__DATA_JSON__", json.dumps(items))
        )
        self._view.setHtml(html)


class CoveragePanel(QWidget):
    """ZIP / GPS sim toolbar + heatmap tab + map tab."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._tree_provider = None  # set via set_data_source

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        controls = QGroupBox("ZIP / GPS simulation")
        form = QFormLayout(controls)

        self._lat_spin = QDoubleSpinBox()
        self._lat_spin.setRange(-90.0, 90.0)
        self._lat_spin.setDecimals(6)
        self._lat_spin.setValue(34.0522)
        form.addRow("Latitude:", self._lat_spin)

        self._lon_spin = QDoubleSpinBox()
        self._lon_spin.setRange(-180.0, 180.0)
        self._lon_spin.setDecimals(6)
        self._lon_spin.setValue(-118.2437)
        form.addRow("Longitude:", self._lon_spin)

        btn_row = QHBoxLayout()
        center_btn = QPushButton("Center map here")
        center_btn.clicked.connect(self._center_map)
        btn_row.addWidget(center_btn)
        refresh_btn = QPushButton("Refresh from HPDB")
        refresh_btn.clicked.connect(self.refresh_from_hpdb)
        btn_row.addWidget(refresh_btn)
        btn_row.addStretch(1)
        form.addRow(btn_row)

        layout.addWidget(controls)

        self._tabs = QTabWidget()
        self._heatmap = CoverageHeatmapWidget()
        self._map = CoverageMapView()
        self._tabs.addTab(self._heatmap, "Heatmap")
        self._tabs.addTab(self._map, "Map")
        layout.addWidget(self._tabs, stretch=1)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_data_source(self, hpd_files_provider) -> None:
        """``hpd_files_provider`` is a 0-arg callable returning the
        list of currently-loaded ``HpdFile`` instances. We re-call it
        on every refresh so swaps are picked up automatically."""
        self._tree_provider = hpd_files_provider

    def refresh_from_hpdb(self) -> None:
        if self._tree_provider is None:
            return
        try:
            files = self._tree_provider() or []
        except Exception:
            files = []
        groups: List[Tuple[float, float, float]] = []
        items: List[dict] = []
        for hpd in files:
            for system in hpd.systems:
                for group in system.groups:
                    if group.lat is None or group.lon is None:
                        continue
                    weight = max(1.0, float(len(group.entries)))
                    groups.append((float(group.lat), float(group.lon), weight))
                    radius_miles = (
                        float(group.range_miles) if group.range_miles else 5.0
                    )
                    items.append(
                        {
                            "kind": "circle",
                            "lat": float(group.lat),
                            "lon": float(group.lon),
                            "radius_m": radius_miles * 1609.344,
                            "label": group.name or "",
                            "color": "#4dabf7" if weight > 1 else "#999",
                        }
                    )
                    for rect in group.rectangles:
                        if len(rect) >= 4:
                            items.append(
                                {
                                    "kind": "rectangle",
                                    "lat1": float(rect[0]),
                                    "lon1": float(rect[1]),
                                    "lat2": float(rect[2]),
                                    "lon2": float(rect[3]),
                                    "label": group.name or "",
                                }
                            )
                for site in system.sites:
                    if site.lat is None or site.lon is None:
                        continue
                    items.append(
                        {
                            "kind": "marker",
                            "lat": float(site.lat),
                            "lon": float(site.lon),
                            "label": f"Site: {site.name}",
                        }
                    )
        self._heatmap.set_groups(groups)
        # Center map near the data centroid if possible, else on the
        # user's lat/lon spinner
        if items:
            lat_sum = sum(
                i.get("lat", i.get("lat1", 0.0)) for i in items if i.get("kind") != "rectangle"
            )
            lon_sum = sum(
                i.get("lon", i.get("lon1", 0.0)) for i in items if i.get("kind") != "rectangle"
            )
            n = sum(1 for i in items if i.get("kind") != "rectangle")
            if n > 0:
                self._map.set_view(lat_sum / n, lon_sum / n, zoom=7, items=items)
                return
        self._map.set_view(self._lat_spin.value(), self._lon_spin.value(), zoom=4, items=items)

    def _center_map(self) -> None:
        self._map.set_view(self._lat_spin.value(), self._lon_spin.value(), zoom=8)
