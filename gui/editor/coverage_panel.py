"""Coverage panel: heatmap + map (popout-only).

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
from typing import List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QLabel,
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


_LEAFLET_SHELL_HTML = """
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
    const map = L.map('map').setView([34.0, -118.0], 4);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 18,
        attribution: 'Â© OpenStreetMap'
    }).addTo(map);

    const layer = L.layerGroup().addTo(map);

    window.updateCoverageData = function(lat, lon, zoom, data) {
        layer.clearLayers();
        data = data || [];
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
        } else if (lat != null && lon != null) {
            map.setView([lat, lon], zoom != null ? zoom : map.getZoom());
        }
    };
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

        self._shell_loaded = False
        self._loading_shell = False
        self._pending_view: Optional[Tuple[float, float, int, List[dict]]] = None

        if HAS_WEBENGINE:
            self._view = QWebEngineView()
            self._view.loadFinished.connect(self._on_shell_loaded)
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

    def invalidate_shell(self) -> None:
        """Drop the one-time Leaflet shell so the next update reloads HTML."""
        self._shell_loaded = False
        self._loading_shell = False
        self._pending_view = None

    def set_view(
        self,
        lat: float,
        lon: float,
        zoom: int = 6,
        items: Optional[List[dict]] = None,
    ) -> None:
        """Update map center and overlay items.

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
        if not self._shell_loaded:
            self._pending_view = (lat, lon, zoom, items)
            if not self._loading_shell:
                self._loading_shell = True
                self._view.setHtml(_LEAFLET_SHELL_HTML)
            return
        self._update_via_javascript(lat, lon, zoom, items)

    def _on_shell_loaded(self, ok: bool) -> None:
        if not ok or self._shell_loaded:
            self._loading_shell = False
            return
        self._shell_loaded = True
        self._loading_shell = False
        pending = self._pending_view
        if pending is None:
            return
        lat, lon, zoom, items = pending
        self._pending_view = None
        self._update_via_javascript(lat, lon, zoom, items)

    def _update_via_javascript(
        self,
        lat: float,
        lon: float,
        zoom: int,
        items: List[dict],
    ) -> None:
        payload = json.dumps(items)
        js = (
            f"if (window.updateCoverageData) {{"
            f"window.updateCoverageData({lat}, {lon}, {zoom}, {payload});"
            f"}}"
        )
        self._view.page().runJavaScript(js)


def _rectangle_items_for_group(group) -> List[dict]:
    items: List[dict] = []
    for rect in group.rectangles:
        if len(rect) < 4:
            continue
        items.append({
            "kind": "rectangle",
            "lat1": float(rect[0]),
            "lon1": float(rect[1]),
            "lat2": float(rect[2]),
            "lon2": float(rect[3]),
            "label": group.name or "",
        })
    return items


def _group_coverage_from_group(
    group,
) -> Tuple[Optional[Tuple[float, float, float]], List[dict]]:
    if group.lat is None or group.lon is None:
        return None, []
    weight = max(1.0, float(len(group.entries)))
    radius_miles = float(group.range_miles) if group.range_miles else 5.0
    circle = {
        "kind": "circle",
        "lat": float(group.lat),
        "lon": float(group.lon),
        "radius_m": radius_miles * 1609.344,
        "label": group.name or "",
        "color": "#4dabf7" if weight > 1 else "#999",
    }
    return (
        (float(group.lat), float(group.lon), weight),
        [circle, *_rectangle_items_for_group(group)],
    )


def _site_marker_item(site) -> Optional[dict]:
    if site.lat is None or site.lon is None:
        return None
    return {
        "kind": "marker",
        "lat": float(site.lat),
        "lon": float(site.lon),
        "label": f"Site: {site.name}",
    }


def _coverage_items_from_system(
    system,
) -> Tuple[List[Tuple[float, float, float]], List[dict]]:
    groups: List[Tuple[float, float, float]] = []
    items: List[dict] = []
    for group in system.groups:
        group_pt, group_items = _group_coverage_from_group(group)
        if group_pt is not None:
            groups.append(group_pt)
            items.extend(group_items)
    for site in system.sites:
        marker = _site_marker_item(site)
        if marker is not None:
            items.append(marker)
    return groups, items


def _coverage_items_from_hpd_files(
    files,
) -> Tuple[List[Tuple[float, float, float]], List[dict]]:
    groups: List[Tuple[float, float, float]] = []
    items: List[dict] = []
    for hpd in files:
        for system in hpd.systems:
            sys_groups, sys_items = _coverage_items_from_system(system)
            groups.extend(sys_groups)
            items.extend(sys_items)
    return groups, items


def _map_center_from_items(items: List[dict]) -> Optional[Tuple[float, float]]:
    lat_sum = sum(
        item.get("lat", item.get("lat1", 0.0))
        for item in items
        if item.get("kind") != "rectangle"
    )
    lon_sum = sum(
        item.get("lon", item.get("lon1", 0.0))
        for item in items
        if item.get("kind") != "rectangle"
    )
    n = sum(1 for item in items if item.get("kind") != "rectangle")
    if n <= 0:
        return None
    return lat_sum / n, lon_sum / n


class CoveragePanel(QWidget):
    """Heatmap + map tabs for the View-menu coverage popout."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._tree_provider = None  # set via set_data_source
        self._sim_lat = 34.0522
        self._sim_lon = -118.2437
        self._refresh_enabled = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

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

    def set_sim_center(self, lat: float, lon: float) -> None:
        """Update the map fallback center (driven by LocationSimBar)."""
        self._sim_lat = lat
        self._sim_lon = lon

    def set_refresh_enabled(self, enabled: bool) -> None:
        """Enable or disable automatic coverage refresh (heatmap + map).

        When disabled, :meth:`refresh_from_hpdb` is a no-op unless
        ``force=True``. Wave 2 wires this to coverage-window visibility.
        """
        self._refresh_enabled = enabled

    def invalidate_map_shell(self) -> None:
        """Force the Leaflet shell to reload on the next map update."""
        self._map.invalidate_shell()

    def refresh_from_hpdb(self, *, force: bool = False) -> bool:
        """Recompute heatmap and map from the current HPDB tree data.

        Returns ``True`` when a refresh ran, ``False`` when skipped or
        when no data source is configured.
        """
        if not force and not self._refresh_enabled:
            return False
        if self._tree_provider is None:
            return False
        try:
            files = self._tree_provider() or []
        except Exception:
            files = []
        groups, items = _coverage_items_from_hpd_files(files)
        self._heatmap.set_groups(groups)
        center = _map_center_from_items(items)
        if center is not None:
            self._map.set_view(center[0], center[1], zoom=7, items=items)
        else:
            self._map.set_view(self._sim_lat, self._sim_lon, zoom=4, items=items)
        return True
