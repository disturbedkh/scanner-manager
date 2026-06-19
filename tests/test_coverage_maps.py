"""Tests for the pure helpers in :mod:`coverage_maps`.

These tests intentionally avoid Tk. They validate the math that both
``CoverageHeatmapDialog`` and ``CoverageMapDialog`` rely on.
"""

from __future__ import annotations

import math

import core.coverage_maps as coverage_maps


def test_heat_cells_empty_returns_zero_max():
    result = coverage_maps.heat_cells([], 0.0, 0.0, 50.0, grid=20)
    assert result.max_count == 0
    assert result.grid == 20
    assert len(result.counts) == 20
    assert all(len(row) == 20 for row in result.counts)
    assert all(v == 0 for row in result.counts for v in row)
    assert result.circles_considered == 0


def test_heat_cells_single_circle_hits_center():
    center_lat, center_lon = 29.65, -82.32
    circles = [(center_lat, center_lon, 10.0)]
    result = coverage_maps.heat_cells(
        circles, center_lat, center_lon, 50.0, grid=60
    )
    assert result.max_count >= 1
    assert result.circles_considered == 1
    mid = 30
    assert result.counts[mid][mid] >= 1


def test_heat_cells_overlapping_circles_stack():
    center_lat, center_lon = 29.65, -82.32
    circles = [
        (center_lat, center_lon, 30.0),
        (center_lat, center_lon, 30.0),
        (center_lat, center_lon, 30.0),
    ]
    result = coverage_maps.heat_cells(
        circles, center_lat, center_lon, 50.0, grid=40
    )
    assert result.max_count == 3


def test_heat_cells_skips_far_away_circle():
    center_lat, center_lon = 29.65, -82.32
    circles = [(40.0, -110.0, 5.0)]
    result = coverage_maps.heat_cells(
        circles, center_lat, center_lon, 50.0, grid=40
    )
    assert result.max_count == 0
    assert result.circles_considered == 0


def test_miles_circle_polygon_point_count_and_closure():
    pts = coverage_maps.miles_circle_polygon(29.65, -82.32, 25.0, sides=48)
    assert len(pts) == 48
    for (lat, lon) in pts:
        d_lat_mi = (lat - 29.65) * coverage_maps.MI_PER_DEG_LAT
        d_lon_mi = (
            (lon + 82.32)
            * coverage_maps.mi_per_deg_lon(29.65)
        )
        r = math.hypot(d_lat_mi, d_lon_mi)
        assert abs(r - 25.0) < 0.5


def test_miles_circle_polygon_defends_min_sides():
    pts = coverage_maps.miles_circle_polygon(0.0, 0.0, 10.0, sides=1)
    assert len(pts) == 3


def test_heat_color_gradient_endpoints():
    cold = coverage_maps.heat_color(0.0)
    warm = coverage_maps.heat_color(1.0)
    assert cold.startswith("#")
    assert warm.startswith("#")
    assert warm != cold
    assert warm[1:3] == "ff"
    assert cold[5:7] != "00" or cold == "#000040"


def test_tile_providers_match_ui_labels():
    labels = coverage_maps.tile_provider_labels()
    assert labels[0] == "OpenStreetMap"
    assert "Google (normal)" in labels
    assert "Google (satellite)" in labels


def test_apply_tile_server_routes_to_chosen_provider():
    captured = {}

    class _FakeMap:
        def set_tile_server(self, url, max_zoom):
            captured["url"] = url
            captured["max_zoom"] = max_zoom

    coverage_maps.apply_tile_server(_FakeMap(), "Google (satellite)")
    assert "google" in captured["url"].lower()
    assert captured["max_zoom"] >= 20

    coverage_maps.apply_tile_server(_FakeMap(), "unknown-provider")
    assert "openstreetmap.org" in captured["url"]


def test_pick_default_center_prefers_active_coords():
    assert coverage_maps.pick_default_center((1.0, 2.0), []) == (1.0, 2.0)


def test_pick_default_center_uses_first_non_null_candidate():
    center = coverage_maps.pick_default_center(
        None, [(None, None), (10.0, 20.0), (30.0, 40.0)]
    )
    assert center == (10.0, 20.0)


def test_pick_default_center_falls_back_to_dc():
    center = coverage_maps.pick_default_center(None, [(None, None)])
    assert center == (38.9072, -77.0369)


def test_cell_corner_offsets_span_the_grid():
    nw, ne, se, sw = coverage_maps.cell_corner_offsets_mi(
        center_lat=0.0,
        center_lon=0.0,
        r=0,
        c=0,
        span_mi=50.0,
        grid=50,
    )
    assert nw[0] > se[0]
    assert ne[1] > nw[1]
    assert abs(ne[1] - nw[1]) > 0


def test_iter_coverage_circles_handles_missing_geo():
    class _FakeSite:
        def __init__(self, lat, lon, rng, name="s"):
            self.lat = lat
            self.lon = lon
            self.range_miles = rng
            self.name = name

    class _FakeSys:
        def __init__(self):
            self.name = "sys"
            self.sites = [
                _FakeSite(1.0, 2.0, 5.0, "good"),
                _FakeSite(None, 2.0, 5.0, "no-lat"),
                _FakeSite(1.0, 2.0, 0.0, "no-range"),
            ]
            self.groups = []

    results = list(coverage_maps.iter_coverage_circles([_FakeSys()]))
    assert len(results) == 1
    assert results[0][0] == 1.0
    assert results[0][3] == "sys - good"


def test_module_imports_without_tk():
    import importlib

    mod = importlib.reload(coverage_maps)
    assert hasattr(mod, "heat_cells")


def test_quantize_intensity_buckets_and_clamps():
    assert coverage_maps.quantize_intensity(0.0) == 0
    assert coverage_maps.quantize_intensity(-0.5) == 0
    assert coverage_maps.quantize_intensity(0.001, buckets=6) == 1
    assert coverage_maps.quantize_intensity(1.0, buckets=6) == 6
    assert coverage_maps.quantize_intensity(2.0, buckets=6) == 6
    assert coverage_maps.quantize_intensity(0.5, buckets=10) == 5


def test_heat_rectangles_empty_when_no_heat():
    result = coverage_maps.heat_cells([], 0.0, 0.0, 50.0, grid=20)
    assert coverage_maps.heat_rectangles(result) == []


def test_heat_rectangles_merge_reduces_polygon_count():
    """Rectangles must be at least an order of magnitude fewer than the
    raw non-zero cell count on realistic input - that's the whole point
    of this optimization."""
    center_lat, center_lon = 29.65, -82.32
    circles = [
        (center_lat, center_lon, 30.0),
        (center_lat + 0.05, center_lon + 0.05, 20.0),
        (center_lat - 0.1, center_lon + 0.1, 50.0),
    ]
    result = coverage_maps.heat_cells(
        circles, center_lat, center_lon, 60.0, grid=36
    )
    nonzero = sum(
        1 for row in result.counts for v in row if v > 0
    )
    rectangles = coverage_maps.heat_rectangles(result)
    assert rectangles, "should produce at least one rectangle"
    assert len(rectangles) < nonzero
    assert len(rectangles) * 3 < nonzero
    for rect in rectangles:
        assert rect.r_start <= rect.r_end
        assert rect.c_start <= rect.c_end
        assert rect.bucket >= 1
        assert rect.color.startswith("#")


def test_heat_rectangles_cover_every_hot_cell():
    center_lat, center_lon = 29.65, -82.32
    circles = [
        (center_lat, center_lon, 20.0),
        (center_lat + 0.1, center_lon, 15.0),
    ]
    result = coverage_maps.heat_cells(
        circles, center_lat, center_lon, 40.0, grid=24
    )
    rectangles = coverage_maps.heat_rectangles(result)
    covered = set()
    for rect in rectangles:
        for r in range(rect.r_start, rect.r_end + 1):
            for c in range(rect.c_start, rect.c_end + 1):
                covered.add((r, c))
    hot_cells = {
        (r, c)
        for r, row in enumerate(result.counts)
        for c, v in enumerate(row)
        if v > 0
    }
    assert hot_cells.issubset(covered)


def test_rectangle_polygon_has_four_corners_inside_span():
    result = coverage_maps.heat_cells(
        [(0.0, 0.0, 30.0)], 0.0, 0.0, 40.0, grid=16
    )
    rects = coverage_maps.heat_rectangles(result)
    assert rects
    pts = coverage_maps.rectangle_polygon(
        rects[0], 0.0, 0.0, 40.0, result.grid
    )
    assert len(pts) == 4
    for lat, lon in pts:
        assert abs(lat) < 1.0
        assert abs(lon) < 1.0


def _make_fake_system(name, entries):
    class _Geo:
        def __init__(self, lat, lon, rng, n):
            self.lat = lat
            self.lon = lon
            self.range_miles = rng
            self.name = n

    class _Sys:
        pass

    s = _Sys()
    s.name = name
    s.sites = []
    s.groups = []
    for kind, lat, lon, rng, n in entries:
        geo = _Geo(lat, lon, rng, n)
        if kind == "site":
            s.sites.append(geo)
        else:
            s.groups.append(geo)
    return s


def _make_fake_system_with_entries(name, lat, lon, rng, child_name, service_types):
    class _Entry:
        def __init__(self, st):
            self.service_type = st

    class _Group:
        def __init__(self):
            self.lat = lat
            self.lon = lon
            self.range_miles = rng
            self.name = child_name
            self.entries = [_Entry(st) for st in service_types]

    class _Sys:
        pass

    s = _Sys()
    s.name = name
    s.sites = []
    s.groups = [_Group()]
    return s


def test_iter_coverage_items_collects_group_service_types():
    sys_a = _make_fake_system_with_entries(
        "Alachua Police", 29.65, -82.32, 25.0, "Dispatch", [2, 2, 3]
    )
    items = list(coverage_maps.iter_coverage_items([sys_a]))
    assert len(items) == 1
    assert items[0]["service_types"] == {2, 3}
    assert items[0]["deleted"] is False
    assert items[0]["kind"] == "group"


def test_cluster_passes_button_filter_honors_active_buttons():
    sys_a = _make_fake_system_with_entries(
        "Police", 29.65, -82.32, 25.0, "D", [2]
    )
    cluster = coverage_maps.cluster_tower_points([sys_a])[0]
    scannable = {2, 3, 4, 14, 1}
    assert coverage_maps.cluster_passes_button_filter(
        cluster, {2}, include_others=False, scannable_types=scannable
    )
    # Police-only cluster should be rejected when only Fire is picked
    # and "other types" is off.
    assert not coverage_maps.cluster_passes_button_filter(
        cluster, {3}, include_others=False, scannable_types=scannable
    )
    # Unknown-type clusters (no service types) only pass when one of
    # the toggles would allow them.
    empty = coverage_maps.TowerCluster(lat=0, lon=0)
    assert coverage_maps.cluster_passes_button_filter(
        empty, set(), include_others=True, scannable_types=scannable
    )
    assert not coverage_maps.cluster_passes_button_filter(
        empty, set(), include_others=False, scannable_types=scannable
    )


def test_cluster_passes_button_filter_other_types_route():
    # A security/industrial entry has a non-standard service type (42)
    # and should only surface when the "other types" toggle is on.
    sys_a = _make_fake_system_with_entries(
        "Utility", 29.65, -82.32, 25.0, "D", [42]
    )
    cluster = coverage_maps.cluster_tower_points([sys_a])[0]
    scannable = {2, 3, 4, 14, 1}
    assert not coverage_maps.cluster_passes_button_filter(
        cluster, {2}, include_others=False, scannable_types=scannable
    )
    assert coverage_maps.cluster_passes_button_filter(
        cluster, {2}, include_others=True, scannable_types=scannable
    )


def test_clusters_within_span_prunes_far_towers():
    near = _make_fake_system_with_entries(
        "Near", 29.65, -82.32, 25.0, "D", [2]
    )
    far = _make_fake_system_with_entries(
        "Far", 40.0, -100.0, 25.0, "D", [2]
    )
    clusters = coverage_maps.cluster_tower_points([near, far])
    kept_wide = coverage_maps.clusters_within_span(
        clusters, 29.65, -82.32, 2000.0
    )
    kept_narrow = coverage_maps.clusters_within_span(
        clusters, 29.65, -82.32, 5.0
    )
    assert {c.lat for c in kept_wide} == {29.65, 40.0}
    assert {c.lat for c in kept_narrow} == {29.65}


class _FakeEvent:
    def __init__(self, op, payload, reverted=False, target_name=""):
        self.op = op
        self.payload = payload
        self.reverted = reverted
        self.target_name = target_name


class _FakeMeta:
    def __init__(self, events):
        self.events = events


def test_iter_deleted_tower_items_expands_delete_system_records():
    """OP_DELETE_SYSTEM stores raw HPD records rather than a pre-parsed
    groups list, so the replay has to run the same state machine the
    live tree uses. A missing "groups" key here was exactly the bug
    the comprehensive deleted-tower fix addresses."""
    events = [
        _FakeEvent(
            "delete_system",
            {
                "snapshot": {"name": "Statewide LE EDACS"},
                "system_blob": {
                    "system_name": "Statewide LE EDACS",
                    "records": [
                        {
                            "record_type": "Trunk",
                            "fields": [
                                "Trunk", "1", "-1", "Statewide LE EDACS",
                                "EDACS",
                            ],
                        },
                        {
                            "record_type": "T-Group",
                            "fields": [
                                "T-Group", "10", "1", "North Tower",
                                "0",
                                "30.00", "-82.50", "45.0",
                            ],
                        },
                        {
                            "record_type": "TGID",
                            "fields": [
                                "TGID", "20", "10", "Law Dispatch",
                                "0", "100", "DIGITAL", "2",
                            ],
                        },
                        {
                            "record_type": "TGID",
                            "fields": [
                                "TGID", "21", "10", "Tactical",
                                "0", "101", "DIGITAL", "2",
                            ],
                        },
                        {
                            "record_type": "T-Group",
                            "fields": [
                                "T-Group", "11", "1", "South Tower",
                                "0",
                                "29.00", "-82.00", "35.0",
                            ],
                        },
                        {
                            "record_type": "TGID",
                            "fields": [
                                "TGID", "30", "11", "Fire",
                                "0", "200", "DIGITAL", "3",
                            ],
                        },
                    ],
                },
            },
        )
    ]
    items = list(coverage_maps.iter_deleted_tower_items(_FakeMeta(events)))
    assert len(items) == 2
    by_name = {i["child"]: i for i in items}
    assert "North Tower" in by_name
    assert "South Tower" in by_name
    north = by_name["North Tower"]
    assert north["system"] == "Statewide LE EDACS"
    assert north["service_types"] == {2}
    assert abs(north["lat"] - 30.0) < 1e-6
    assert abs(north["range_mi"] - 45.0) < 1e-6
    south = by_name["South Tower"]
    assert south["service_types"] == {3}


def test_iter_hpd_session_snapshot_items(tmp_path):
    """Session-snapshot parsing must recognise the same record layout
    as the live tree so the diff uses identical identity keys."""
    snap_text = (
        "Trunk\t1\t-1\tGainesville PD\tEDACS\n"
        "T-Group\t5\t1\tCentral Dispatch\t0\t29.65\t-82.32\t25.0\n"
        "TGID\t101\t5\tLaw\t0\t100\tDIGITAL\t2\n"
        "Conventional\t2\t-1\tCounty Fire Ops\t\n"
        "C-Group\t9\t2\tEngine 1\t0\t29.65\t-82.33\t15.0\n"
        "C-Freq\t201\t9\tTac 1\t0\t154000000\tFM\t\t3\n"
    )
    path = tmp_path / "test.hpd.session.bak"
    path.write_text(snap_text, encoding="utf-8")

    items = list(coverage_maps.iter_hpd_session_snapshot_items(path))
    by_child = {i["child"]: i for i in items}
    assert "Central Dispatch" in by_child
    assert "Engine 1" in by_child
    assert by_child["Central Dispatch"]["system"] == "Gainesville PD"
    assert by_child["Central Dispatch"]["service_types"] == {2}
    assert by_child["Engine 1"]["system"] == "County Fire Ops"
    assert by_child["Engine 1"]["service_types"] == {3}
    assert all(item["deleted"] is False for item in items)


def test_iter_deleted_tower_items_comprehensive_diffs_against_snapshot(tmp_path):
    """Diffing the session snapshot against the live tree must catch
    any tower that's no longer present - even when the event log is
    empty, which is the whole point of the comprehensive path."""
    snap_text = (
        "Trunk\t1\t-1\tGainesville PD\tEDACS\n"
        "T-Group\t5\t1\tCentral Dispatch\t0\t29.65\t-82.32\t25.0\n"
        "TGID\t101\t5\tLaw\t0\t100\tDIGITAL\t2\n"
        "T-Group\t6\t1\tWest Tower\t0\t29.70\t-82.45\t20.0\n"
        "TGID\t102\t6\tFire\t0\t200\tDIGITAL\t3\n"
    )
    snap_path = tmp_path / "card.hpd.session.bak"
    snap_path.write_text(snap_text, encoding="utf-8")

    live_sys = _make_fake_system_with_entries(
        "Gainesville PD", 29.65, -82.32, 25.0, "Central Dispatch", [2]
    )

    deleted = list(
        coverage_maps.iter_deleted_tower_items_comprehensive(
            [live_sys], session_snapshot_path=str(snap_path)
        )
    )
    assert len(deleted) == 1
    assert deleted[0]["child"] == "West Tower"
    assert deleted[0]["deleted"] is True
    assert deleted[0]["service_types"] == {3}


def test_cluster_tower_points_surfaces_deleted_system_via_snapshot(tmp_path):
    """End-to-end sanity: when a whole system is wiped from the live
    tree but still exists in the session snapshot, the clusterer must
    return it as a deleted cluster, not silently drop it (the bug the
    user hit with "statewide law enforcement EDACS")."""
    snap_text = (
        "Trunk\t1\t-1\tStatewide LE EDACS\tEDACS\n"
        "T-Group\t10\t1\tNorth Tower\t0\t30.00\t-82.50\t45.0\n"
        "TGID\t101\t10\tDispatch\t0\t100\tDIGITAL\t2\n"
        "T-Group\t11\t1\tSouth Tower\t0\t29.00\t-82.00\t35.0\n"
        "TGID\t102\t11\tFire Backup\t0\t200\tDIGITAL\t3\n"
    )
    snap_path = tmp_path / "wiped.hpd.session.bak"
    snap_path.write_text(snap_text, encoding="utf-8")

    clusters = coverage_maps.cluster_tower_points(
        [],
        include_deleted=True,
        session_snapshot_path=str(snap_path),
    )
    deleted = [c for c in clusters if c.deleted]
    live = [c for c in clusters if not c.deleted]
    assert len(live) == 0
    assert len(deleted) == 2
    names = {m.child for c in deleted for m in c.members}
    assert names == {"North Tower", "South Tower"}


def test_iter_deleted_tower_items_picks_up_unreverted_group_deletes():
    events = [
        _FakeEvent(
            "delete_group",
            {
                "snapshot": {
                    "name": "Old Dispatch",
                    "system_name": "County PD",
                    "lat": 29.65,
                    "lon": -82.32,
                    "range_miles": 25.0,
                },
                "children": [
                    {"snapshot": {"service_type": 2}},
                    {"snapshot": {"service_type": 2}},
                ],
            },
        ),
        # Reverted delete must not surface.
        _FakeEvent(
            "delete_group",
            {
                "snapshot": {
                    "name": "Restored",
                    "system_name": "County PD",
                    "lat": 29.0,
                    "lon": -82.0,
                    "range_miles": 25.0,
                },
                "children": [],
            },
            reverted=True,
        ),
        # Geo-less delete must not surface.
        _FakeEvent(
            "delete_group",
            {
                "snapshot": {
                    "name": "No geo",
                    "system_name": "County PD",
                    "lat": None,
                    "lon": None,
                    "range_miles": 0,
                },
                "children": [],
            },
        ),
    ]
    items = list(coverage_maps.iter_deleted_tower_items(_FakeMeta(events)))
    assert len(items) == 1
    assert items[0]["deleted"] is True
    assert items[0]["service_types"] == {2}
    assert items[0]["child"] == "Old Dispatch"


def test_cluster_tower_points_include_deleted_merges_live_and_deleted():
    live = _make_fake_system_with_entries(
        "Alive", 29.65, -82.32, 25.0, "Dispatch", [2]
    )
    events = [
        _FakeEvent(
            "delete_group",
            {
                "snapshot": {
                    "name": "Old Fire",
                    "system_name": "Ghost Fire",
                    "lat": 29.65,
                    "lon": -82.32,
                    "range_miles": 25.0,
                },
                "children": [{"snapshot": {"service_type": 3}}],
            },
        )
    ]
    meta = _FakeMeta(events)

    # Default: only live.
    clusters = coverage_maps.cluster_tower_points([live], metastore=meta)
    assert len(clusters) == 1
    assert not clusters[0].deleted

    # include_deleted=True keeps them as separate clusters (one live,
    # one deleted) even though they share the same lat/lon - the UI
    # renders them with different styling so users can tell them apart.
    clusters = coverage_maps.cluster_tower_points(
        [live], metastore=meta, include_deleted=True
    )
    assert len(clusters) == 2
    live_c = [c for c in clusters if not c.deleted][0]
    dead_c = [c for c in clusters if c.deleted][0]
    assert live_c.service_types == {2}
    assert dead_c.service_types == {3}
    assert dead_c.short_label().startswith("[deleted]")


def test_cluster_tower_points_collapses_colocated_entries():
    sys_a = _make_fake_system(
        "County Police",
        [("group", 29.6500, -82.3200, 25.0, "Dispatch")],
    )
    sys_b = _make_fake_system(
        "County Fire",
        [("group", 29.6500, -82.3200, 25.0, "Dispatch")],
    )
    sys_c = _make_fake_system(
        "City Public Works",
        [("site", 29.65001, -82.32002, 15.0, "Tower North")],
    )
    sys_d = _make_fake_system(
        "Remote System",
        [("group", 35.0, -100.0, 10.0, "Group")],
    )
    clusters = coverage_maps.cluster_tower_points(
        [sys_a, sys_b, sys_c, sys_d]
    )
    assert len(clusters) == 2
    big = clusters[0]
    assert big.size == 3
    assert big.max_range_mi == 25.0
    systems = {m.system for m in big.members}
    assert systems == {
        "County Police",
        "County Fire",
        "City Public Works",
    }
    label = big.short_label()
    assert "3" in label
    small = clusters[1]
    assert small.size == 1
    assert small.short_label() == "Remote System - Group"

