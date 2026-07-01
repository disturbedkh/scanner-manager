"""Location filter state and geo helpers for the BT885 editor tree.

Wraps legacy :mod:`legacy_tk.scanner_manager` geo utilities — do not
duplicate haversine / coverage math here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from legacy_tk.scanner_manager import (
    ZipCountyLookup,
    haversine_miles,
    rectangle_contains_point,
    system_covers_point,
    system_has_geo,
)

__all__ = [
    "LocationFilterState",
    "ZipCountyLookup",
    "group_coverage_info",
    "haversine_miles",
    "nearest_distance_miles",
    "rectangle_contains_point",
    "system_covers_point",
    "system_matches_location",
]

_STATUS_NO_GEO = "no_geo"
_STATUS_IN_RANGE = "in_range"
_STATUS_NEARBY = "nearby"
_STATUS_OUT_RANGE = "out_range"


def nearest_distance_miles(sys_node, lat: float, lon: float) -> Optional[float]:
    """Re-export for callers that decorate the tree with distance labels."""
    from legacy_tk.scanner_manager import nearest_distance_miles as _nearest

    return _nearest(sys_node, lat, lon)


@dataclass
class LocationFilterState:
    enabled: bool
    zip_code: str = ""
    county_id: Optional[int] = None
    coords: Optional[Tuple[float, float]] = None
    tolerance_mi: float = 0.0
    state_id: Optional[int] = None


def _status_from_distance(d: float, range_miles: float, tolerance_mi: float) -> str:
    rng = range_miles or 0.0
    if rng > 0 and d <= rng:
        return _STATUS_IN_RANGE
    if rng > 0 and d <= rng + tolerance_mi:
        return _STATUS_NEARBY
    if rng <= 0 and d <= tolerance_mi:
        return _STATUS_NEARBY
    return _STATUS_OUT_RANGE


def _info_from_rectangles(
    group, lat: float, lon: float, info: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    if not group.rectangles:
        return None
    if not any(rectangle_contains_point(r, lat, lon) for r in group.rectangles):
        return None
    info["has_geo"] = True
    info["status"] = _STATUS_IN_RANGE
    if group.lat is not None and group.lon is not None:
        info["distance"] = haversine_miles(lat, lon, group.lat, group.lon)
    else:
        info["distance"] = 0.0
    return info


def group_coverage_info(
    group, coords: Optional[Tuple[float, float]], tolerance_mi: float
) -> Dict[str, Any]:
    """Coverage status for one group relative to simulated coordinates."""
    info: Dict[str, Any] = {
        "has_geo": False,
        "distance": None,
        "range_miles": group.range_miles,
        "status": _STATUS_NO_GEO,
    }
    if coords is None:
        return info
    lat, lon = coords
    rect_info = _info_from_rectangles(group, lat, lon, info)
    if rect_info is not None:
        return rect_info
    if group.lat is None or group.lon is None:
        return info
    info["has_geo"] = True
    d = haversine_miles(lat, lon, group.lat, group.lon)
    info["distance"] = d
    info["status"] = _status_from_distance(d, group.range_miles or 0.0, tolerance_mi)
    return info


def _matches_with_coords(sys_node, state: LocationFilterState) -> bool:
    assert state.coords is not None
    lat, lon = state.coords
    tolerance = max(0.0, float(state.tolerance_mi))
    covered, delta = system_covers_point(sys_node, lat, lon)
    if covered:
        return True
    if system_has_geo(sys_node):
        if delta != float("inf") and delta <= tolerance:
            return True
        return False
    if state.county_id and state.county_id in sys_node.county_ids:
        return True
    return not sys_node.county_ids and not sys_node.state_ids


def _matches_with_county_only(sys_node, state: LocationFilterState) -> bool:
    if state.county_id is None:
        return True
    if sys_node.county_ids:
        return state.county_id in sys_node.county_ids
    sid = state.state_id
    if sys_node.state_ids and sid is not None:
        return sid in sys_node.state_ids
    return True


def system_matches_location(sys_node, state: LocationFilterState) -> bool:
    """Whether a system should appear when the location filter is active."""
    if state.coords is not None:
        return _matches_with_coords(sys_node, state)
    return _matches_with_county_only(sys_node, state)
