"""Coverage heatmap and map dialogs for legacy Tk."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple

import core.coverage_maps as coverage_maps
from core.metastore import session_snapshot_path
from legacy_tk.literals import (
    _LIT_COMBOBOX_SELECTED,
    _LIT_COVERAGE_HEATMAP,
    _LIT_COVERAGE_MAP,
)
from scanner_profiles import get_active_profile

if TYPE_CHECKING:
    from legacy_tk.scanner_manager import ScannerManagerApp

class CoverageHeatmapDialog:
    """Coverage heatmap overlaid on real-world map tiles.

    Each group/site with ``lat``/``lon``/``range_miles`` contributes a
    coverage circle; overlapping circles raise the intensity of the
    underlying grid cell. The grid is then drawn as a stack of small
    filled polygons on top of an OSM / Google tile layer so the user can
    see *where* the hotspots sit relative to real geography.

    If ``tkintermapview`` is not installed, the dialog falls back to the
    legacy pure-Tk canvas renderer so headless installs still work.
    """

    DEFAULT_SPAN_MI = 50.0
    DEFAULT_GRID = 36
    HEAT_BUCKETS = 6
    LEGACY_GRID = 200

    def __init__(self, app: "ScannerManagerApp"):
        self.app = app
        if app._active_coords is None:
            messagebox.showinfo(
                _LIT_COVERAGE_HEATMAP,
                "Apply a ZIP or City location filter first so the heatmap "
                "has a center point.",
            )
            return
        self.center_lat, self.center_lon = app._active_coords
        self._tile_mode = coverage_maps.have_map_support()
        self._map_module = None
        if self._tile_mode:
            try:
                import tkintermapview  # type: ignore

                self._map_module = tkintermapview
            except Exception:
                self._tile_mode = False

        self.top = tk.Toplevel(app.root)
        self.top.title(_LIT_COVERAGE_HEATMAP)
        self.top.transient(app.root)
        if self._tile_mode:
            self.top.geometry("900x700")

        header = ttk.Frame(self.top, padding=(8, 8, 8, 4))
        header.pack(fill=tk.X)
        ttk.Label(
            header,
            text=(
                f"Center: {self.center_lat:.4f}, {self.center_lon:.4f}    "
                "Span (mi):"
            ),
        ).pack(side=tk.LEFT)
        self.span_var = tk.StringVar(value=str(int(self.DEFAULT_SPAN_MI)))
        entry = ttk.Entry(header, textvariable=self.span_var, width=6)
        entry.pack(side=tk.LEFT, padx=4)
        entry.bind("<Return>", lambda _e: self._render())
        entry.bind("<FocusOut>", lambda _e: self._render())

        if self._tile_mode:
            ttk.Label(header, text="Tile server:").pack(side=tk.LEFT, padx=(10, 2))
            self.tile_var = tk.StringVar(value="OpenStreetMap")
            tile_cb = ttk.Combobox(
                header,
                textvariable=self.tile_var,
                width=22,
                state="readonly",
                values=tuple(coverage_maps.tile_provider_labels()),
            )
            tile_cb.pack(side=tk.LEFT)
            tile_cb.bind(
                _LIT_COMBOBOX_SELECTED,
                lambda _e: coverage_maps.apply_tile_server(
                    self.map, self.tile_var.get()
                ),
            )

            self.markers_var = tk.BooleanVar(value=True)
            ttk.Checkbutton(
                header,
                text="Show tower markers",
                variable=self.markers_var,
                command=self._render,
            ).pack(side=tk.LEFT, padx=8)

            self.circles_var = tk.BooleanVar(value=False)
            ttk.Checkbutton(
                header,
                text="Show coverage circles",
                variable=self.circles_var,
                command=self._render,
            ).pack(side=tk.LEFT, padx=8)

        ttk.Button(header, text="Render", command=self._render).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(header, text="Close", command=self.top.destroy).pack(
            side=tk.RIGHT
        )

        if self._tile_mode:
            # Second row: scanner button simulation + deleted-tower toggle.
            # Defaults mirror whatever the main app currently has selected,
            # so the heatmap opens showing "what the scanner sees" rather
            # than dumping every raw tower on the user.
            filters = ttk.Frame(self.top, padding=(8, 0, 8, 4))
            filters.pack(fill=tk.X)
            ttk.Label(filters, text="Scanner buttons:").pack(side=tk.LEFT)
            self.btn_police = tk.BooleanVar(
                value=bool(app._button_police.get())
            )
            self.btn_fire = tk.BooleanVar(value=bool(app._button_fire.get()))
            self.btn_ems = tk.BooleanVar(value=bool(app._button_ems.get()))
            self.btn_dot = tk.BooleanVar(value=bool(app._button_dot.get()))
            self.btn_multi = tk.BooleanVar(
                value=bool(app._button_multi.get())
            )
            self.btn_others = tk.BooleanVar(
                value=bool(app._include_others.get())
            )
            for label, var in (
                ("Police", self.btn_police),
                ("Fire", self.btn_fire),
                ("EMS", self.btn_ems),
                ("DOT", self.btn_dot),
                ("Multi (1/14)", self.btn_multi),
                ("Other types", self.btn_others),
            ):
                ttk.Checkbutton(
                    filters, text=label, variable=var, command=self._render
                ).pack(side=tk.LEFT, padx=2)

            # Deleted-tower visibility: off by default so the heatmap
            # matches the live SD card. Turn on to see grayed-out ghosts
            # of towers the user removed since the last baseline.
            self.show_deleted_var = tk.BooleanVar(value=False)
            ttk.Checkbutton(
                filters,
                text="Show removed towers (grayed)",
                variable=self.show_deleted_var,
                command=self._render,
            ).pack(side=tk.LEFT, padx=(12, 2))

        body = ttk.Frame(self.top)
        body.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        if self._tile_mode:
            self.map = self._map_module.TkinterMapView(
                body, width=880, height=600, corner_radius=0
            )
            self.map.pack(fill=tk.BOTH, expand=True)
            coverage_maps.apply_tile_server(self.map, "OpenStreetMap")
            self.map.set_position(self.center_lat, self.center_lon)
            self.map.set_zoom(9)
            self._heat_polygons: List[Any] = []
            self._coverage_polygons: List[Any] = []
            self._markers: List[Any] = []
        else:
            ttk.Label(
                body,
                text=(
                    "Install the optional 'tkintermapview' package to see the "
                    "heatmap on real map tiles (pip install tkintermapview)."
                ),
                foreground="#888888",
                wraplength=520,
            ).pack(anchor=tk.W, pady=(0, 4))
            self.canvas = tk.Canvas(
                body,
                width=self.LEGACY_GRID,
                height=self.LEGACY_GRID,
                background="#101010",
                highlightthickness=0,
            )
            self.canvas.pack()

        self.legend = ttk.Label(self.top, text="", padding=(8, 0, 8, 8))
        self.legend.pack(fill=tk.X)

        self._render()

    def _iter_coverage_circles(self):
        for (lat, lon, rng, _label) in coverage_maps.iter_coverage_circles(
            self.app.hpd.systems
        ):
            yield lat, lon, rng

    def _render(self):
        try:
            span = float(self.span_var.get())
        except ValueError:
            span = self.DEFAULT_SPAN_MI
        span = max(5.0, min(span, 500.0))

        circles = list(coverage_maps.iter_coverage_circles(self.app.hpd.systems))
        if not circles:
            self.legend.configure(text="No group/site has lat/lon + range.")
            if self._tile_mode:
                self._clear_overlays()
            else:
                self.canvas.delete("all")
                self.canvas.create_text(
                    self.LEGACY_GRID / 2,
                    self.LEGACY_GRID / 2,
                    text="No geo data",
                    fill="#888888",
                )
            return

        if self._tile_mode:
            self._render_tiles(circles, span)
        else:
            self._render_canvas(circles, span)

    def _clear_overlays(self) -> None:
        for poly in getattr(self, "_heat_polygons", []):
            try:
                poly.delete()
            except Exception:
                pass
        self._heat_polygons = []
        for poly in getattr(self, "_coverage_polygons", []):
            try:
                poly.delete()
            except Exception:
                pass
        self._coverage_polygons = []
        for marker in getattr(self, "_markers", []):
            try:
                marker.delete()
            except Exception:
                pass
        self._markers = []

    def _session_snapshot_path(self) -> Optional[str]:
        """Path to the session-snapshot copy of the currently-loaded HPD,
        if one exists on disk. Used by the comprehensive deleted-tower
        diff so the heatmap can tell the difference between "was there
        at load time and removed since" vs "never existed"."""
        hpd_path = getattr(self.app.hpd, "filepath", None)
        if not hpd_path:
            return None
        try:
            snap = session_snapshot_path(hpd_path)
        except Exception:
            return None
        try:
            if not snap.exists():
                return None
        except Exception:
            return None
        return str(snap)

    def _active_button_types(self) -> Set[int]:
        active: Set[int] = set()
        if getattr(self, "btn_police", None) and self.btn_police.get():
            active.add(2)
        if getattr(self, "btn_fire", None) and self.btn_fire.get():
            active.add(3)
        if getattr(self, "btn_ems", None) and self.btn_ems.get():
            active.add(4)
        if getattr(self, "btn_dot", None) and self.btn_dot.get():
            active.add(14)
        if getattr(self, "btn_multi", None) and self.btn_multi.get():
            active.add(1)
        return active

    def _render_tiles(self, circles, span: float) -> None:
        self._clear_overlays()

        # Build the full cluster list first, so both the heat grid and
        # the marker/circle overlays use the exact same "in-scope" set.
        # This is what lets the Span box actually reduce the number of
        # tower icons the user sees (previously it only affected the
        # heat grid).
        include_deleted = bool(
            getattr(self, "show_deleted_var", tk.BooleanVar(value=False)).get()
        )
        all_clusters = coverage_maps.cluster_tower_points(
            self.app.hpd.systems,
            metastore=getattr(self.app, "_meta", None),
            include_deleted=include_deleted,
            session_snapshot_path=self._session_snapshot_path(),
        )
        active_buttons = self._active_button_types()
        include_others = bool(
            getattr(self, "btn_others", tk.BooleanVar(value=True)).get()
        )
        scannable = set(get_active_profile().scannable_service_types())
        filtered_clusters = [
            c
            for c in all_clusters
            if coverage_maps.cluster_passes_button_filter(
                c, active_buttons, include_others, scannable
            )
        ]
        span_clusters = coverage_maps.clusters_within_span(
            filtered_clusters, self.center_lat, self.center_lon, span
        )

        live_clusters = [c for c in span_clusters if not c.deleted]
        deleted_clusters = [c for c in span_clusters if c.deleted]

        # The heat grid only ever reflects *live* coverage; deleted
        # towers are annotations, not part of what the scanner will
        # actually scan tonight.
        heat_source = []
        for c in live_clusters:
            for m in c.members:
                heat_source.append((c.lat, c.lon, m.range_mi))

        result = coverage_maps.heat_cells(
            heat_source,
            self.center_lat,
            self.center_lon,
            span,
            grid=self.DEFAULT_GRID,
        )
        rectangles: List[coverage_maps.HeatRectangle] = []
        if result.max_count > 0:
            rectangles = coverage_maps.heat_rectangles(
                result, buckets=self.HEAT_BUCKETS
            )
            for rect in rectangles:
                pts = coverage_maps.rectangle_polygon(
                    rect,
                    self.center_lat,
                    self.center_lon,
                    span,
                    result.grid,
                )
                try:
                    poly = self.map.set_polygon(
                        pts,
                        outline_color=rect.color,
                        fill_color=rect.color,
                        border_width=0,
                    )
                    self._heat_polygons.append(poly)
                except Exception:
                    pass

        # Per-tower coverage circles (optional - off by default since
        # they clutter the view when there are many towers).
        if (
            getattr(self, "circles_var", None)
            and self.circles_var.get()
        ):
            self._draw_coverage_circles(live_clusters, deleted=False)
            if include_deleted:
                self._draw_coverage_circles(deleted_clusters, deleted=True)

        try:
            you_marker = self.map.set_marker(
                self.center_lat,
                self.center_lon,
                text="(you)",
                marker_color_circle="red",
            )
            self._markers.append(you_marker)
        except Exception:
            pass
        if getattr(self, "markers_var", None) and self.markers_var.get():
            self._add_cluster_markers(live_clusters, deleted=False)
            if include_deleted:
                self._add_cluster_markers(deleted_clusters, deleted=True)

        live_member_count = sum(c.size for c in live_clusters)
        deleted_note = ""
        if include_deleted:
            deleted_note = (
                f"    {len(deleted_clusters)} removed tower"
                f"{'s' if len(deleted_clusters) != 1 else ''} shown in gray"
            )
        if result.max_count == 0:
            self.legend.configure(
                text=(
                    "No coverage circles intersect this span. "
                    f"{len(live_clusters)} tower(s) within +/-{span:.0f} mi."
                    + deleted_note
                )
            )
            return
        self.legend.configure(
            text=(
                f"{result.circles_considered} coverage circles across "
                f"{len(live_clusters)} tower site(s) "
                f"({live_member_count} groups), "
                f"{len(rectangles)} heat rectangles. "
                f"Brightest = {result.max_count} overlapping systems. "
                f"Span = {span:.0f} mi."
                + deleted_note
            )
        )

    def _draw_coverage_circles(
        self,
        clusters: List["coverage_maps.TowerCluster"],
        *,
        deleted: bool,
    ) -> None:
        """Outline each cluster's advertised coverage radius.

        Deleted towers render in a muted gray so the user can see what
        they've removed against the active footprint without the two
        sets visually fighting each other.
        """
        if deleted:
            outline = "#888888"
            fill = "#cccccc"
        else:
            outline = "#0a84ff"
            fill = "#0a84ff"
        for cluster in clusters:
            radius = cluster.max_range_mi
            if not radius or radius <= 0:
                continue
            try:
                pts = coverage_maps.miles_circle_polygon(
                    cluster.lat, cluster.lon, float(radius), sides=48
                )
                poly = self.map.set_polygon(
                    pts,
                    outline_color=outline,
                    fill_color=fill,
                    border_width=1,
                )
                self._coverage_polygons.append(poly)
            except Exception:
                pass

    def _add_cluster_markers(
        self,
        clusters: List["coverage_maps.TowerCluster"],
        *,
        deleted: bool = False,
    ) -> None:
        """Drop one map marker per unique tower location.

        Co-located repeaters collapse into a single marker; the user
        clicks through to :class:`TowerClusterDialog` to see the full
        list of systems / groups at that site. Removed towers use a
        gray marker circle so they read as "ghosts" on top of the live
        heat.
        """
        for cluster in clusters:
            label = cluster.short_label()
            try:
                kwargs: Dict[str, Any] = dict(
                    text=label,
                    command=self._make_cluster_click_handler(cluster),
                )
                if deleted:
                    kwargs["marker_color_circle"] = "#888888"
                    kwargs["marker_color_outside"] = "#bdbdbd"
                    kwargs["text_color"] = "#707070"
                marker = self.map.set_marker(
                    cluster.lat, cluster.lon, **kwargs
                )
                self._markers.append(marker)
            except Exception:
                pass

    def _make_cluster_click_handler(
        self, cluster: "coverage_maps.TowerCluster"
    ):
        def _open(_marker=None, _cluster=cluster):
            from legacy_tk.scanner_manager import TowerClusterDialog

            TowerClusterDialog(self.top, _cluster)
        return _open

    def _render_canvas(self, circles, span: float) -> None:
        grid = self.LEGACY_GRID
        result = coverage_maps.heat_cells(
            ((lat, lon, rng) for (lat, lon, rng, _l) in circles),
            self.center_lat,
            self.center_lon,
            span,
            grid=grid,
        )
        self.canvas.delete("all")
        if result.max_count == 0:
            self.canvas.create_text(
                grid / 2,
                grid / 2,
                text="(no coverage overlaps this span)",
                fill="#888888",
            )
            self.legend.configure(
                text="No coverage circles intersect this span."
            )
            return
        img = tk.PhotoImage(width=grid, height=grid)
        self._img = img
        for r in range(grid):
            row_colors: List[str] = []
            for c in range(grid):
                n = result.counts[r][c]
                if n == 0:
                    row_colors.append("#101010")
                else:
                    row_colors.append(
                        coverage_maps.heat_color(n / result.max_count)
                    )
            img.put("{" + " ".join(row_colors) + "}", to=(0, r))
        self.canvas.create_image(0, 0, anchor=tk.NW, image=img)
        half_px = grid // 2
        self.canvas.create_line(
            half_px - 6, half_px, half_px + 6, half_px, fill="#ffffff"
        )
        self.canvas.create_line(
            half_px, half_px - 6, half_px, half_px + 6, fill="#ffffff"
        )
        self.legend.configure(
            text=(
                f"{result.circles_considered} coverage circles — "
                f"darkest = no overlap, brightest = {result.max_count} "
                f"overlapping systems. Span = {span:.0f} mi on each axis."
            )
        )


class CoverageMapDialog:
    """Real-tile coverage map built on tkintermapview.

    Optional: requires ``tkintermapview`` to be installed. The host will
    pull tiles from OpenStreetMap by default; each group/site with
    ``lat``/``lon``/``range_miles`` data is drawn as a circle (polygon
    approximation) plus a labeled marker.
    """

    def __init__(self, app: "ScannerManagerApp"):
        self.app = app
        try:
            import tkintermapview  # type: ignore
        except Exception:
            messagebox.showinfo(
                _LIT_COVERAGE_MAP,
                "Install the optional 'tkintermapview' package to use this "
                "view (pip install tkintermapview). The pure-Python "
                "'Heatmap...' dialog works without any extra dependency.",
            )
            return

        self.top = tk.Toplevel(app.root)
        self.top.title(_LIT_COVERAGE_MAP)
        self.top.transient(app.root)
        self.top.geometry("900x650")

        header = ttk.Frame(self.top, padding=6)
        header.pack(fill=tk.X)
        ttk.Label(header, text="Tile server:").pack(side=tk.LEFT)
        self.tile_var = tk.StringVar(value="OpenStreetMap")
        tile_cb = ttk.Combobox(
            header, textvariable=self.tile_var, width=24, state="readonly",
            values=tuple(coverage_maps.tile_provider_labels()),
        )
        tile_cb.pack(side=tk.LEFT, padx=4)
        tile_cb.bind(_LIT_COMBOBOX_SELECTED, lambda _e: self._apply_tile())
        ttk.Button(header, text="Refresh", command=self._redraw).pack(
            side=tk.LEFT, padx=6
        )
        ttk.Button(header, text="Close", command=self.top.destroy).pack(
            side=tk.RIGHT
        )

        self._map_module = tkintermapview
        self.map = tkintermapview.TkinterMapView(
            self.top, width=880, height=580, corner_radius=0
        )
        self.map.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        # The widget's constructor picks an uncustomised default tile URL;
        # explicitly apply our chosen provider so what the combobox says
        # matches what the user actually sees.
        self._apply_tile()

        center = self._pick_center()
        self.map.set_position(center[0], center[1])
        self.map.set_zoom(8)

        self._polygons: List = []
        self._markers: List = []
        self._redraw()

    def _pick_center(self) -> Tuple[float, float]:
        candidates: List[Tuple[Optional[float], Optional[float]]] = []
        for sys_node in self.app.hpd.systems:
            for site in sys_node.sites:
                candidates.append((site.lat, site.lon))
            for group in sys_node.groups:
                candidates.append((group.lat, group.lon))
        return coverage_maps.pick_default_center(
            self.app._active_coords, candidates
        )

    def _apply_tile(self):
        coverage_maps.apply_tile_server(self.map, self.tile_var.get())

    @staticmethod
    def _circle_points(
        lat: float, lon: float, range_miles: float, sides: int = 48
    ) -> List[Tuple[float, float]]:
        return coverage_maps.miles_circle_polygon(
            lat, lon, float(range_miles), sides=sides
        )

    def _redraw(self):
        for p in self._polygons:
            try:
                p.delete()
            except Exception:
                pass
        for m in self._markers:
            try:
                m.delete()
            except Exception:
                pass
        self._polygons.clear()
        self._markers.clear()

        clusters = coverage_maps.cluster_tower_points(self.app.hpd.systems)
        drawn = 0
        for cluster in clusters:
            radius = cluster.max_range_mi
            if radius and radius > 0:
                pts = self._circle_points(cluster.lat, cluster.lon, float(radius))
                poly = self.map.set_polygon(
                    pts,
                    outline_color="#0a84ff",
                    fill_color="#0a84ff",
                    border_width=1,
                )
                # tkintermapview polygons default to ~40% opacity fill.
                self._polygons.append(poly)
            try:
                marker = self.map.set_marker(
                    cluster.lat,
                    cluster.lon,
                    text=cluster.short_label(),
                    command=self._make_cluster_click_handler(cluster),
                )
                self._markers.append(marker)
            except Exception:
                pass
            drawn += cluster.size

        if self.app._active_coords is not None:
            clat, clon = self.app._active_coords
            self._markers.append(
                self.map.set_marker(clat, clon, text="(you)", marker_color_circle="red")
            )

        self.top.title(
            f"Coverage Map - {drawn} coverage circles across "
            f"{len(clusters)} unique towers"
        )

    def _make_cluster_click_handler(
        self, cluster: "coverage_maps.TowerCluster"
    ):
        def _open(_marker=None, _cluster=cluster):
            from legacy_tk.scanner_manager import TowerClusterDialog

            TowerClusterDialog(self.top, _cluster)
        return _open


