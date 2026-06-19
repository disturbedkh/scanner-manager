"""Shared coverage-map helpers for the Scanner Manager.

This module intentionally contains **pure** geometry helpers and light
widget wrappers so both ``CoverageMapDialog`` and ``CoverageHeatmapDialog``
can share math and a single tile-provider selector.

Nothing in this module depends on Tk being present at import time; the
map-view helpers ``import tkintermapview`` lazily so headless tests can
still import and exercise ``heat_cells`` / ``miles_circle_polygon``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

MI_PER_DEG_LAT = 69.172


TileProvider = Tuple[str, str, int]  # (label, url_template, max_zoom)

TILE_PROVIDERS: List[TileProvider] = [
    (
        "OpenStreetMap",
        "https://a.tile.openstreetmap.org/{z}/{x}/{y}.png",
        19,
    ),
    (
        "Google (normal)",
        "https://mt0.google.com/vt/lyrs=m&hl=en&x={x}&y={y}&z={z}",
        22,
    ),
    (
        "Google (satellite)",
        "https://mt0.google.com/vt/lyrs=s&hl=en&x={x}&y={y}&z={z}",
        22,
    ),
]


def tile_provider_labels() -> List[str]:
    return [label for (label, _, _) in TILE_PROVIDERS]


def tile_provider_for(label: str) -> TileProvider:
    for item in TILE_PROVIDERS:
        if item[0] == label:
            return item
    return TILE_PROVIDERS[0]


def apply_tile_server(map_view, label: str) -> None:
    """Point ``map_view`` at the tile server named by ``label``.

    Falls back to OpenStreetMap for unknown labels. Safe to call with a
    freshly-constructed ``TkinterMapView`` whose default server hasn't
    been touched yet.
    """
    _, url, max_zoom = tile_provider_for(label)
    map_view.set_tile_server(url, max_zoom=max_zoom)


def mi_per_deg_lon(at_lat: float) -> float:
    """Miles per degree of longitude at a given latitude.

    Clamped to at least 1.0 so we never divide by zero near the poles.
    """
    return max(1.0, MI_PER_DEG_LAT * math.cos(math.radians(at_lat)))


def miles_circle_polygon(
    lat: float, lon: float, radius_mi: float, sides: int = 48
) -> List[Tuple[float, float]]:
    """Approximate a circle of ``radius_mi`` at (lat, lon) as lat/lon polygon.

    The conversion uses a flat-earth approximation that is accurate for
    the ~50-300 mile radii typical of scanner coverage; do not use for
    continent-scale polygons.
    """
    if sides < 3:
        sides = 3
    mi_lon = mi_per_deg_lon(lat)
    pts: List[Tuple[float, float]] = []
    for i in range(sides):
        theta = (i / sides) * 2.0 * math.pi
        dlat = (radius_mi * math.sin(theta)) / MI_PER_DEG_LAT
        dlon = (radius_mi * math.cos(theta)) / mi_lon
        pts.append((lat + dlat, lon + dlon))
    return pts


def cell_corner_offsets_mi(
    center_lat: float,
    center_lon: float,
    r: int,
    c: int,
    span_mi: float,
    grid: int,
) -> Tuple[Tuple[float, float], Tuple[float, float], Tuple[float, float], Tuple[float, float]]:
    """Return the four lat/lon corners of grid cell ``(r, c)``.

    ``r=0`` is the northmost row; ``c=0`` is the westmost column. The
    grid spans ``[-span_mi, +span_mi]`` in both axes from the center.
    """
    mi_per_cell = (span_mi * 2.0) / grid
    mi_lon = mi_per_deg_lon(center_lat)
    north_mi = span_mi - r * mi_per_cell
    south_mi = north_mi - mi_per_cell
    west_mi = -span_mi + c * mi_per_cell
    east_mi = west_mi + mi_per_cell

    def _to_ll(mi_n: float, mi_e: float) -> Tuple[float, float]:
        return (
            center_lat + mi_n / MI_PER_DEG_LAT,
            center_lon + mi_e / mi_lon,
        )

    return (
        _to_ll(north_mi, west_mi),
        _to_ll(north_mi, east_mi),
        _to_ll(south_mi, east_mi),
        _to_ll(south_mi, west_mi),
    )


@dataclass
class HeatResult:
    """Return value of :func:`heat_cells`."""

    counts: List[List[int]]
    max_count: int
    span_mi: float
    grid: int
    center_lat: float
    center_lon: float
    circles_considered: int


def _circle_offsets_mi(
    clat: float,
    clon: float,
    center_lat: float,
    center_lon: float,
    mi_lon: float,
) -> Tuple[float, float]:
    dlat_mi = (clat - center_lat) * MI_PER_DEG_LAT
    dlon_mi = (clon - center_lon) * mi_lon
    return dlat_mi, dlon_mi


def _circle_outside_span_box(
    dlat_mi: float, dlon_mi: float, crange: float, span_mi: float
) -> bool:
    return (
        abs(dlat_mi) - crange > span_mi or abs(dlon_mi) - crange > span_mi
    )


def _accumulate_circle_row_counts(
    counts: List[List[int]],
    r: int,
    grid: int,
    span_mi: float,
    mi_per_cell: float,
    dlat_mi: float,
    dlon_mi: float,
    crange: float,
    max_count: int,
) -> int:
    pixel_lat_mi = span_mi - (r + 0.5) * mi_per_cell
    lat_diff_mi = pixel_lat_mi - dlat_mi
    if abs(lat_diff_mi) > crange:
        return max_count
    dx_max_sq = crange * crange - lat_diff_mi * lat_diff_mi
    if dx_max_sq < 0:
        return max_count
    dx_max = dx_max_sq ** 0.5
    min_x_mi = dlon_mi - dx_max
    max_x_mi = dlon_mi + dx_max
    col_lo = max(0, int((min_x_mi + span_mi) / mi_per_cell))
    col_hi = min(grid - 1, int((max_x_mi + span_mi) / mi_per_cell))
    for c in range(col_lo, col_hi + 1):
        counts[r][c] += 1
        if counts[r][c] > max_count:
            max_count = counts[r][c]
    return max_count


def heat_cells(
    circles: Iterable[Tuple[float, float, float]],
    center_lat: float,
    center_lon: float,
    span_mi: float,
    grid: int = 60,
) -> HeatResult:
    """Count how many coverage circles overlap each grid cell.

    ``circles`` is an iterable of ``(lat, lon, range_miles)``. The grid
    is square, ``grid`` cells on a side, covering ``[-span_mi, +span_mi]``
    in both axes from ``(center_lat, center_lon)``. Runs in roughly
    ``O(circles * grid)`` thanks to a per-row bounding box.

    Pure function; no Tk, no I/O. Exposed for testing.
    """
    if grid < 1:
        grid = 1
    if span_mi <= 0:
        span_mi = 1.0
    mi_per_cell = (span_mi * 2.0) / grid
    mi_lon = mi_per_deg_lon(center_lat)

    counts = [[0] * grid for _ in range(grid)]
    max_count = 0
    considered = 0
    for (clat, clon, crange) in circles:
        if crange is None or crange <= 0:
            continue
        dlat_mi, dlon_mi = _circle_offsets_mi(
            clat, clon, center_lat, center_lon, mi_lon
        )
        if _circle_outside_span_box(dlat_mi, dlon_mi, crange, span_mi):
            continue
        considered += 1
        for r in range(grid):
            max_count = _accumulate_circle_row_counts(
                counts,
                r,
                grid,
                span_mi,
                mi_per_cell,
                dlat_mi,
                dlon_mi,
                crange,
                max_count,
            )

    return HeatResult(
        counts=counts,
        max_count=max_count,
        span_mi=span_mi,
        grid=grid,
        center_lat=center_lat,
        center_lon=center_lon,
        circles_considered=considered,
    )


def quantize_intensity(t: float, buckets: int = 6) -> int:
    """Snap an intensity ``t in [0, 1]`` to a discrete bucket index ``0..buckets``.

    Bucket 0 means "no heat" (skip). The higher buckets correspond to
    hotter cells. Quantizing lets us render adjacent cells with
    near-identical intensity as a single large polygon, which is what
    makes the heatmap survive zoom/pan without re-projecting thousands
    of vertices each frame.
    """
    if t <= 0 or buckets <= 0:
        return 0
    if t > 1:
        t = 1
    idx = int(t * buckets)
    if idx < 1:
        idx = 1
    if idx > buckets:
        idx = buckets
    return idx


@dataclass
class HeatRectangle:
    """A rectangle of constant-intensity cells in :func:`heat_rectangles` output."""

    r_start: int  # inclusive northmost row
    r_end: int    # inclusive southmost row
    c_start: int  # inclusive westmost column
    c_end: int    # inclusive eastmost column
    bucket: int
    color: str


def _heat_row_runs(
    result: HeatResult, r: int, grid: int, buckets: int
) -> List[Tuple[int, int, int]]:
    def bucket_for(c: int) -> int:
        n = result.counts[r][c]
        if n <= 0:
            return 0
        t = n / result.max_count
        return quantize_intensity(t, buckets=buckets)

    runs: List[Tuple[int, int, int]] = []
    c = 0
    while c < grid:
        b = bucket_for(c)
        if b == 0:
            c += 1
            continue
        c_start = c
        while c + 1 < grid and bucket_for(c + 1) == b:
            c += 1
        runs.append((c_start, c, b))
        c += 1
    return runs


def _merge_heat_row_runs(
    runs: List[Tuple[int, int, int]],
    active: Dict[Tuple[int, int, int], HeatRectangle],
    r: int,
    finished: List[HeatRectangle],
) -> Dict[Tuple[int, int, int], HeatRectangle]:
    keys_this_row: Dict[Tuple[int, int, int], HeatRectangle] = {}
    for (c_start, c_end, b) in runs:
        key = (c_start, c_end, b)
        carried = active.pop(key, None)
        if carried is not None and carried.r_end == r - 1:
            carried.r_end = r
            keys_this_row[key] = carried
        else:
            keys_this_row[key] = HeatRectangle(
                r_start=r,
                r_end=r,
                c_start=c_start,
                c_end=c_end,
                bucket=b,
                color="",
            )
    finished.extend(active.values())
    return keys_this_row


def heat_rectangles(
    result: "HeatResult", buckets: int = 6
) -> List[HeatRectangle]:
    """Compress a :class:`HeatResult` into a small list of rectangles.

    Adjacent cells whose intensity falls into the same quantization
    bucket are merged into a single rectangle. Produces dramatically
    fewer draw primitives than the naive "one polygon per cell" path
    - typically a 5-20x reduction - which is the difference between
    a heatmap that repaints smoothly on zoom and one that doesn't.

    The algorithm is two-pass:

    1. For each row, collapse adjacent same-bucket cells into
       ``(c_start, c_end, bucket)`` runs.
    2. Walk rows top-to-bottom; a run in the current row that exactly
       matches an active rectangle on the previous row (same span,
       same bucket, adjacent row) extends that rectangle downward.
       Anything else closes off any active rectangle and starts a new
       one.

    Pure function; no Tk, no I/O.
    """
    if result.max_count <= 0:
        return []
    grid = result.grid

    active: Dict[Tuple[int, int, int], HeatRectangle] = {}
    finished: List[HeatRectangle] = []

    for r in range(grid):
        runs = _heat_row_runs(result, r, grid, buckets)
        active = _merge_heat_row_runs(runs, active, r, finished)

    finished.extend(active.values())

    if buckets > 0:
        for rect in finished:
            centroid = (rect.bucket - 0.5) / buckets
            rect.color = heat_color(centroid)
    return finished


def rectangle_polygon(
    rect: HeatRectangle,
    center_lat: float,
    center_lon: float,
    span_mi: float,
    grid: int,
) -> List[Tuple[float, float]]:
    """Return the four lat/lon corners of a :class:`HeatRectangle`."""
    mi_per_cell = (span_mi * 2.0) / grid
    mi_lon = mi_per_deg_lon(center_lat)
    north_mi = span_mi - rect.r_start * mi_per_cell
    south_mi = span_mi - (rect.r_end + 1) * mi_per_cell
    west_mi = -span_mi + rect.c_start * mi_per_cell
    east_mi = -span_mi + (rect.c_end + 1) * mi_per_cell

    def _to_ll(mi_n: float, mi_e: float) -> Tuple[float, float]:
        return (
            center_lat + mi_n / MI_PER_DEG_LAT,
            center_lon + mi_e / mi_lon,
        )

    return [
        _to_ll(north_mi, west_mi),
        _to_ll(north_mi, east_mi),
        _to_ll(south_mi, east_mi),
        _to_ll(south_mi, west_mi),
    ]


def heat_color(t: float) -> str:
    """Map a normalised intensity ``t in [0, 1]`` to a cool->warm hex color.

    Blue -> green -> yellow -> red, matching the legacy canvas heatmap.
    """
    if t <= 0:
        return "#000040"
    if t > 1:
        t = 1
    if t < 0.5:
        g = int(t * 2 * 255)
        b = 255 - g
        return f"#00{g:02x}{b:02x}"
    u = (t - 0.5) * 2
    r = int(u * 255)
    g = 255 - int(u * 128)
    return f"#{r:02x}{g:02x}00"


def pick_default_center(
    active_coords: Optional[Tuple[float, float]],
    candidate_points: Sequence[Tuple[Optional[float], Optional[float]]],
    fallback: Tuple[float, float] = (38.9072, -77.0369),
) -> Tuple[float, float]:
    """Pick a map center: active coords, else first candidate with geo, else fallback."""
    if active_coords is not None:
        return active_coords
    for lat, lon in candidate_points:
        if lat is not None and lon is not None:
            return (lat, lon)
    return fallback


def have_map_support() -> bool:
    """Return True iff ``tkintermapview`` is importable in this env."""
    import importlib.util

    return importlib.util.find_spec("tkintermapview") is not None


def iter_coverage_circles(
    systems,
) -> Iterable[Tuple[float, float, float, str]]:
    """Yield (lat, lon, range_miles, label) for every group/site with geo.

    ``systems`` is the ``HpdFile.systems`` list. Kept here so both the
    heatmap and the map dialog can stay in sync on what "has geo" means.
    """
    for item in iter_coverage_items(systems):
        yield (item["lat"], item["lon"], item["range_mi"], item["label"])


def _coverage_site_item(sys_name: str, site) -> Optional[Dict[str, Any]]:
    if site.lat is None or site.lon is None or not site.range_miles:
        return None
    child = getattr(site, "name", "") or ""
    return {
        "lat": float(site.lat),
        "lon": float(site.lon),
        "range_mi": float(site.range_miles),
        "label": f"{sys_name} - {child}".strip(" -"),
        "system": sys_name,
        "kind": "site",
        "child": child,
        "service_types": set(),
        "deleted": False,
    }


def _service_types_from_group(group) -> Set[int]:
    svc_types: Set[int] = set()
    for entry in getattr(group, "entries", []) or []:
        st = getattr(entry, "service_type", None)
        if st is None:
            continue
        try:
            svc_types.add(int(st))
        except Exception:
            continue
    return svc_types


def _coverage_group_item(sys_name: str, group) -> Optional[Dict[str, Any]]:
    if group.lat is None or group.lon is None or not group.range_miles:
        return None
    child = getattr(group, "name", "") or ""
    return {
        "lat": float(group.lat),
        "lon": float(group.lon),
        "range_mi": float(group.range_miles),
        "label": f"{sys_name} - {child}".strip(" -"),
        "system": sys_name,
        "kind": "group",
        "child": child,
        "service_types": _service_types_from_group(group),
        "deleted": False,
    }


def iter_coverage_items(
    systems,
) -> Iterable[Dict[str, Any]]:
    """Richer version of :func:`iter_coverage_circles`.

    Yields a dict per geo-tagged site/group with keys:

    - ``lat``, ``lon``, ``range_mi`` - geometry
    - ``label`` - legacy "System - Child" string
    - ``system`` - owning ``SystemNode.name``
    - ``kind`` - ``"site"`` or ``"group"``
    - ``child`` - name of the site or group itself
    - ``service_types`` - set of ``int`` service types contributed by
      entries underneath this node (empty for sites; the site's parent
      system drives button filtering indirectly through its groups).
    - ``deleted`` - always ``False``; reserved so downstream code can
      stay symmetric with :func:`iter_deleted_tower_items`.

    Using a dict here (rather than a long positional tuple) keeps the
    call sites that need extra context - clustering, button filtering,
    deleted-tower overlays - readable.
    """
    for sys_node in systems:
        sys_name = getattr(sys_node, "name", "") or ""
        for site in getattr(sys_node, "sites", []):
            item = _coverage_site_item(sys_name, site)
            if item is not None:
                yield item
        for group in getattr(sys_node, "groups", []):
            item = _coverage_group_item(sys_name, group)
            if item is not None:
                yield item


def _yield_deleted_event_items(event) -> Iterable[Dict[str, Any]]:
    op = getattr(event, "op", "")
    payload = getattr(event, "payload", {}) or {}
    if op == "delete_group":
        snapshot = payload.get("snapshot") or {}
        item = _deleted_item_from_group_snapshot(snapshot, payload, event)
        if item is not None:
            yield item
    elif op == "delete_system":
        sys_name = (
            (payload.get("snapshot") or {}).get("name")
            or getattr(event, "target_name", "")
            or ""
        )
        blob = payload.get("system_blob") or {}
        yield from _items_from_system_blob(blob, sys_name)


def iter_deleted_tower_items(metastore) -> Iterable[Dict[str, Any]]:
    """Replay unreverted delete events into the same shape as
    :func:`iter_coverage_items`.

    Handles every delete op the app can log:

    - ``OP_DELETE_GROUP`` - payload has a structured group snapshot
      plus child entry snapshots (the cleanest case).
    - ``OP_DELETE_SYSTEM`` - payload's ``system_blob`` carries the
      raw HPD records that used to belong to the system. We walk
      them with a tiny state machine (identical to the live tree's
      parser) to reconstruct each group/site along with the service
      types of its entries.

    Tower records that never had lat/lon/range are skipped silently;
    there's nothing geographic to draw.
    """
    if metastore is None:
        return
    events = getattr(metastore, "events", None) or []
    for event in events:
        if getattr(event, "reverted", False):
            continue
        yield from _yield_deleted_event_items(event)


def _deleted_item_from_group_snapshot(
    snapshot: Dict[str, Any],
    payload: Dict[str, Any],
    event,
) -> Optional[Dict[str, Any]]:
    lat = snapshot.get("lat")
    lon = snapshot.get("lon")
    rng = snapshot.get("range_miles")
    if lat is None or lon is None or not rng:
        return None
    sys_name = snapshot.get("system_name") or ""
    child = snapshot.get("name") or getattr(event, "target_name", "") or ""
    service_types: Set[int] = set()
    for sub in payload.get("children") or []:
        sub_snap = sub.get("snapshot") or {}
        st = sub_snap.get("service_type")
        if st is None:
            continue
        try:
            service_types.add(int(st))
        except Exception:
            continue
    return {
        "lat": float(lat),
        "lon": float(lon),
        "range_mi": float(rng),
        "label": f"{sys_name} - {child}".strip(" -"),
        "system": sys_name,
        "kind": "group",
        "child": child,
        "service_types": service_types,
        "deleted": True,
    }


# HPD field positions we care about for synthesising deleted items.
# These match the live tree's ``_build_tree`` parser; the geo fields
# start at index 5 for C-Group / T-Group / Site rows.
_GEO_START = 5
_CFREQ_SVC_FIELD = 8
_TGID_SVC_FIELD = 7


def _parse_float_or_none(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_service_type(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None


@dataclass
class _RecordStreamState:
    default_system_name: str = ""
    current_system_name: str = ""
    current_kind: Optional[str] = None
    current_geo: Dict[str, Any] = field(default_factory=dict)
    current_service_types: Set[int] = field(default_factory=set)

    def __post_init__(self) -> None:
        if not self.current_system_name:
            self.current_system_name = self.default_system_name


def _flush_record_stream_state(
    state: _RecordStreamState,
) -> Iterable[Dict[str, Any]]:
    if not state.current_geo:
        return
    lat = _parse_float_or_none(state.current_geo.get("lat"))
    lon = _parse_float_or_none(state.current_geo.get("lon"))
    rng = _parse_float_or_none(state.current_geo.get("rng"))
    if lat is None or lon is None or not rng:
        return
    child = state.current_geo.get("name") or ""
    yield {
        "lat": lat,
        "lon": lon,
        "range_mi": float(rng),
        "label": f"{state.current_system_name} - {child}".strip(" -"),
        "system": state.current_system_name,
        "kind": state.current_kind or "group",
        "child": child,
        "service_types": set(state.current_service_types),
        "deleted": True,
    }


def _reset_record_stream_geo(state: _RecordStreamState) -> None:
    state.current_geo = {}
    state.current_service_types = set()
    state.current_kind = None


def _handle_system_record(
    state: _RecordStreamState, fields: List[str]
) -> Iterable[Dict[str, Any]]:
    yield from _flush_record_stream_state(state)
    _reset_record_stream_geo(state)
    state.current_system_name = (
        fields[3] if len(fields) > 3 else ""
    ) or state.default_system_name


def _handle_group_site_record(
    state: _RecordStreamState, rt: str, fields: List[str]
) -> Iterable[Dict[str, Any]]:
    yield from _flush_record_stream_state(state)

    def _field(idx: int, default: str = "") -> str:
        return fields[idx] if len(fields) > idx else default

    lat = _field(_GEO_START)
    lon = _field(_GEO_START + 1)
    rng = _field(_GEO_START + 2)
    state.current_kind = "site" if rt == "Site" else "group"
    state.current_geo = {
        "name": _field(3),
        "lat": lat,
        "lon": lon,
        "rng": rng,
    }
    state.current_service_types = set()


def _handle_service_type_record(
    state: _RecordStreamState, fields: List[str], field_idx: int
) -> None:
    st = _safe_service_type(
        fields[field_idx] if len(fields) > field_idx else None
    )
    if st is not None:
        state.current_service_types.add(st)


def _items_from_record_stream(
    records: Iterable[Dict[str, Any]],
    default_system_name: str = "",
) -> Iterable[Dict[str, Any]]:
    """Run a tiny state machine over raw HPD records.

    Mirrors ``HpdFile._build_tree`` just enough to yield a
    coverage-items dict per group/site. Accepts records shaped as
    ``{"record_type": str, "fields": List[str]}`` so it can be fed
    either the payload of an ``OP_DELETE_SYSTEM`` event or records
    parsed directly from a session-snapshot file.
    """
    state = _RecordStreamState(default_system_name=default_system_name)

    for rec in records:
        rt = rec.get("record_type") or ""
        fields = rec.get("fields") or []

        if rt in ("Conventional", "Trunk"):
            yield from _handle_system_record(state, fields)
        elif rt in ("C-Group", "T-Group", "Site"):
            yield from _handle_group_site_record(state, rt, fields)
        elif rt == "C-Freq":
            _handle_service_type_record(state, fields, _CFREQ_SVC_FIELD)
        elif rt == "TGID":
            _handle_service_type_record(state, fields, _TGID_SVC_FIELD)

    yield from _flush_record_stream_state(state)


def _items_from_system_blob(
    blob: Dict[str, Any], default_system_name: str
) -> Iterable[Dict[str, Any]]:
    """Expand a ``delete_system`` payload's ``system_blob`` into
    coverage-items dicts, one per group/site that had geo data."""
    records = blob.get("records") or []
    effective_sys = (
        blob.get("system_name") or default_system_name or ""
    )
    for item in _items_from_record_stream(records, effective_sys):
        yield item


def iter_hpd_session_snapshot_items(
    snapshot_path: "str | Any",
) -> Iterable[Dict[str, Any]]:
    """Parse a ``.session.bak`` HPD copy and yield live-tower items.

    Uses only a line-by-line tab split - intentionally zero dependency
    on the main ``HpdFile`` parser - so the heatmap can diff against
    "what was on the card when you started this session" without
    pulling the whole app into scope.

    Yielded dicts match :func:`iter_coverage_items` shape (with
    ``deleted=False`` because at snapshot time they were live).
    Callers that want to treat snapshot-only items as deleted can
    flip the flag themselves.
    """
    try:
        with open(str(snapshot_path), "r", encoding="utf-8", errors="replace") as fh:
            raw = fh.read()
    except Exception:
        return

    records: List[Dict[str, Any]] = []
    for line in raw.splitlines():
        if not line:
            continue
        fields = line.split("\t")
        record_type = fields[0] if fields else ""
        records.append({"record_type": record_type, "fields": fields})

    for item in _items_from_record_stream(records, ""):
        snap_item = dict(item)
        snap_item["deleted"] = False
        yield snap_item


def _tower_key(item: Dict[str, Any], precision: int = 3) -> Tuple[str, str, float, float]:
    """Identity key used to deduplicate towers across sources.

    Keys blend a normalised name with a coarse lat/lon bucket so
    "County PD - Dispatch" recorded twice at (29.6500, -82.3200) and
    (29.6501, -82.3200) still counts as one tower. The precision is
    deliberately looser (3 decimals, ~110 m) than the clustering
    precision because historical snapshots often differ in the last
    decimal place from what the user subsequently saved.
    """
    sys_name = (item.get("system") or "").strip().lower()
    child = (item.get("child") or "").strip().lower()
    lat = round(float(item.get("lat") or 0.0), precision)
    lon = round(float(item.get("lon") or 0.0), precision)
    return (sys_name, child, lat, lon)


def _merge_deleted_tower_item(
    seen: Dict[Tuple[str, str, float, float], Dict[str, Any]],
    item: Dict[str, Any],
) -> None:
    item["deleted"] = True
    key = _tower_key(item)
    existing = seen.get(key)
    if existing is None:
        seen[key] = item
        return
    existing["service_types"] = set(
        existing.get("service_types") or set()
    ) | set(item.get("service_types") or set())


def _live_tower_keys(live_systems: Any) -> Set[Tuple[str, str, float, float]]:
    live_keys: Set[Tuple[str, str, float, float]] = set()
    if live_systems is None:
        return live_keys
    for live_item in iter_coverage_items(live_systems):
        live_keys.add(_tower_key(live_item))
    return live_keys


def iter_deleted_tower_items_comprehensive(
    live_systems: Any,
    *,
    metastore: Any = None,
    session_snapshot_path: Any = None,
) -> Iterable[Dict[str, Any]]:
    """Comprehensive deleted-tower feed.

    Combines two complementary strategies so the heatmap never misses
    what the user actually removed:

    1. **Session-snapshot diff.** If the caller points us at a
       ``.session.bak`` copy of the HPD, we parse it line-by-line,
       collect every tower that existed at the start of the session,
       then subtract the towers still present in ``live_systems``.
       Anything left is a deletion - no matter whether it was removed
       via a single click, a bulk remap, or an external edit.
    2. **Event-log replay.** The event log picks up deletions that
       predate the current session snapshot (or edge cases where the
       snapshot is missing). We merge those in and dedupe by a coarse
       (system, child, lat, lon) key so nothing is double-counted.

    The resulting dicts are in :func:`iter_coverage_items` shape with
    ``deleted=True``.
    """
    seen: Dict[Tuple[str, str, float, float], Dict[str, Any]] = {}
    live_keys = _live_tower_keys(live_systems)

    if session_snapshot_path:
        for snap_item in iter_hpd_session_snapshot_items(
            session_snapshot_path
        ):
            if _tower_key(snap_item) in live_keys:
                continue
            _merge_deleted_tower_item(seen, snap_item)

    if metastore is not None:
        for ev_item in iter_deleted_tower_items(metastore):
            if _tower_key(ev_item) in live_keys:
                continue
            _merge_deleted_tower_item(seen, ev_item)

    for item in seen.values():
        yield item


@dataclass
class TowerClusterMember:
    """One (system, site|group) pair that shares a physical tower location."""

    system: str
    kind: str       # "site" or "group"
    child: str
    range_mi: float
    service_types: Set[int] = field(default_factory=set)
    deleted: bool = False


@dataclass
class TowerCluster:
    """A set of repeaters / talkgroup sites at the same rounded lat/lon.

    When several systems share one tower (very common for public-safety
    trunked systems), tkintermapview draws all their labels on top of
    each other. Cluster the members so the map can render one marker
    per physical tower and route a click through to a tree dialog.
    """

    lat: float
    lon: float
    members: List[TowerClusterMember] = field(default_factory=list)
    deleted: bool = False

    @property
    def size(self) -> int:
        return len(self.members)

    @property
    def max_range_mi(self) -> float:
        if not self.members:
            return 0.0
        return max(m.range_mi for m in self.members)

    @property
    def service_types(self) -> Set[int]:
        """Union of service types contributed by every cluster member."""
        combined: Set[int] = set()
        for m in self.members:
            combined |= m.service_types or set()
        return combined

    def short_label(self) -> str:
        prefix = "[deleted] " if self.deleted else ""
        if not self.members:
            return prefix.strip() or ""
        if len(self.members) == 1:
            m = self.members[0]
            return f"{prefix}{m.system} - {m.child}".strip(" -")
        systems: List[str] = []
        seen_systems: Set[str] = set()
        for m in self.members:
            key = m.system.lower()
            if key not in seen_systems:
                seen_systems.add(key)
                systems.append(m.system)
        if len(systems) == 1:
            return f"{prefix}{systems[0]} ({len(self.members)} groups)"
        return (
            f"{prefix}{len(systems)} systems / {len(self.members)} groups"
        )


def _add_items_to_clusters(
    items: Iterable[Dict[str, Any]],
    buckets: Dict[Tuple[float, float, bool], TowerCluster],
    precision: int,
) -> None:
    for item in items:
        key = (
            round(item["lat"], precision),
            round(item["lon"], precision),
            bool(item.get("deleted")),
        )
        cluster = buckets.get(key)
        if cluster is None:
            cluster = TowerCluster(
                lat=item["lat"],
                lon=item["lon"],
                deleted=bool(item.get("deleted")),
            )
            buckets[key] = cluster
        cluster.members.append(
            TowerClusterMember(
                system=item.get("system", ""),
                kind=item.get("kind", ""),
                child=item.get("child", ""),
                range_mi=float(item.get("range_mi", 0.0)),
                service_types=set(item.get("service_types") or set()),
                deleted=bool(item.get("deleted")),
            )
        )


def cluster_tower_points(
    systems,
    *,
    precision: int = 4,
    metastore=None,
    include_deleted: bool = False,
    session_snapshot_path: Any = None,
) -> List[TowerCluster]:
    """Group every geo-tagged site/group by rounded (lat, lon).

    ``precision`` is the number of decimal places used when bucketing;
    the default (4) tolerates ~11 meters of drift, which is plenty to
    collapse duplicate records written by different Uniden tools for
    the same physical repeater.

    When ``include_deleted`` is true, synthetic clusters are emitted
    for towers that the user has removed since this session began.
    Callers may supply either (or both) of:

    - ``metastore``: the per-HPD MetaStore. Unreverted ``delete_group``
      and ``delete_system`` events are replayed into deleted items.
    - ``session_snapshot_path``: path to the ``.session.bak`` HPD
      copy written on first load. The snapshot is diffed against
      ``systems`` and anything present then but missing now is treated
      as deleted.

    Using both together gives the most complete picture: the snapshot
    catches any mutation (including bulk-delete empties and external
    edits) while the event log fills in anything that predates the
    snapshot.

    Returns clusters sorted active-first, then by member count, then
    by latitude, so map marker draw order is deterministic across
    re-renders.
    """
    buckets: Dict[Tuple[float, float, bool], TowerCluster] = {}
    _add_items_to_clusters(iter_coverage_items(systems), buckets, precision)
    if include_deleted and (metastore is not None or session_snapshot_path):
        _add_items_to_clusters(
            iter_deleted_tower_items_comprehensive(
                systems,
                metastore=metastore,
                session_snapshot_path=session_snapshot_path,
            ),
            buckets,
            precision,
        )
    clusters = list(buckets.values())
    clusters.sort(key=lambda c: (c.deleted, -c.size, -c.lat, c.lon))
    return clusters


def cluster_passes_button_filter(
    cluster: TowerCluster,
    active_button_types: Set[int],
    include_others: bool,
    scannable_types: Set[int],
) -> bool:
    """Mirror of ``entry_passes_button_filter`` for clusters.

    A cluster is in-scope when:

    - any member has at least one service type in ``active_button_types``,
    - *or* ``include_others`` is true and any member carries a service
      type outside ``scannable_types``,
    - *or* the cluster has no service-type data at all (e.g. sites
      without entries) and one of the two flags above would let an
      "unknown" row through.

    This keeps the heatmap's button simulation symmetric with the main
    tree's filter so "Police on" means the same thing in both views.
    """
    types = cluster.service_types
    if not types:
        return bool(active_button_types) or include_others
    if types & active_button_types:
        return True
    if include_others:
        for t in types:
            if t not in scannable_types:
                return True
    return False


def clusters_within_span(
    clusters: Iterable[TowerCluster],
    center_lat: float,
    center_lon: float,
    span_mi: float,
) -> List[TowerCluster]:
    """Return only clusters whose center sits inside the +/- span_mi box.

    Uses the same flat-earth approximation that :func:`heat_cells` does
    (miles per degree at the center's latitude), so the span filter
    stays consistent with the heat grid the user sees.
    """
    if span_mi <= 0:
        return list(clusters)
    mi_lon = mi_per_deg_lon(center_lat)
    kept: List[TowerCluster] = []
    for cluster in clusters:
        dlat_mi = (cluster.lat - center_lat) * MI_PER_DEG_LAT
        dlon_mi = (cluster.lon - center_lon) * mi_lon
        if abs(dlat_mi) <= span_mi and abs(dlon_mi) <= span_mi:
            kept.append(cluster)
    return kept
