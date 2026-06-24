"""Profile-aware HPDB editor display helpers.

Centralizes service-type wording and tree row colors so the details
panel and tree stay consistent across BT885 and SDS profiles.
"""

from __future__ import annotations

from typing import Optional, Set

from PySide6.QtGui import QColor

from scanner_profiles import ScannerProfile

_COLOR_SCANNABLE = QColor("#196f3d")
_COLOR_NONSCAN = QColor("#a04000")
_COLOR_ENCRYPTED = QColor("#922b21")

# Maps BT885 hardware button keys to the dispatch service type each
# button activates (mirrors legacy Tk ``_active_button_types``).
_BUTTON_ACTIVE_TYPES = {
    "POLICE": 2,
    "FIRE": 3,
    "EMS": 4,
    "DOT": 14,
    "MULTI": 1,
}


def entry_is_encrypted(mode: str) -> bool:
    return (mode or "").upper() in {"DE", "TE", "AE"}


def format_service_type_details(profile: ScannerProfile, service_type: int) -> str:
    """Human-readable service type for the details panel."""
    label = profile.service_label(service_type) or str(service_type)
    if not profile.uses_hardware_button_semantics:
        return label
    if service_type in profile.scannable_service_types():
        return f"{label} — plays on a scanner button"
    return f"{label} — stored only (no button)"


def entry_row_color(
    profile: Optional[ScannerProfile],
    service_type: Optional[int],
    mode: str,
) -> Optional[QColor]:
    """Foreground color for an entry row, or None for default text."""
    if profile is None:
        return None
    if entry_is_encrypted(mode):
        return _COLOR_ENCRYPTED
    if profile.uses_hardware_button_semantics:
        if service_type in profile.scannable_service_types():
            return _COLOR_SCANNABLE
        return _COLOR_NONSCAN
    return None


def bulk_action_label(profile: ScannerProfile) -> str:
    if profile.uses_hardware_button_semantics:
        return "Apply service type to all…"
    return "Set category for all…"


def active_button_service_types(selected_buttons: Set[str]) -> Set[int]:
    """Convert checked BT885 button keys to active service-type IDs."""
    return {
        _BUTTON_ACTIVE_TYPES[key]
        for key in selected_buttons
        if key in _BUTTON_ACTIVE_TYPES
    }


def entry_passes_button_filter(
    service_type: int,
    selected_buttons: Set[str],
    profile: ScannerProfile,
    *,
    include_others: bool = True,
) -> bool:
    """Return True if an entry should appear for the current button row."""
    active_types = active_button_service_types(selected_buttons)
    if service_type in active_types:
        return True
    if (
        service_type in profile.scannable_service_types()
        and service_type not in active_types
    ):
        return False
    return include_others
