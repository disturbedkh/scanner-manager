"""Uniden SDS100 and SDS200 scanner profile.

The SDS100 (handheld) and SDS200 (mobile) share ~99% of their
firmware and SD card layout per the lab notebook in
``AI/Dev/RE/docs/SDS100.md``. The only practical differences are
form factor and antenna connector. One profile covers both via
the ``scanner_inf_aliases`` list ``("SDS100", "SDS200")``.

This profile is **largely a superset of BT885**: same HPD record
schema, same TGID modes, same RR mode mapping, same FW data
tables (CityTable / ZipTable). What's different:

- 36-slot ``ServiceType`` mask in ``profile.cfg`` instead of the
  BT885's hard-coded 14-ID enum.
- No fixed scanner buttons - the SDS picks systems via Quick Keys
  + Favorites Lists, so ``button_filter`` returns an empty set.
- All service types are scannable (no button restriction).
- Live serial mode is supported (Uniden Remote Command Protocol on
  USB CDC PIDs ``0x001A`` MAIN + ``0x0019`` SUB).
- Waterfall via SUB-port ``m`` debug command (FFT magnitude) is
  available; the GUI's live dock surfaces it.
- Favorites Lists feature: per-list HPDs under
  ``BCDx36HP/favorites_lists/f_*.hpd`` with manifest
  ``f_list.cfg``.
- ``BCDx36HP/profile.cfg`` carries every SDS-specific setting
  (waterfall, GPS, weather, display layout, paging tones, etc.).

References:
- ``AI/Dev/RE/docs/SDS100.md``
- ``AI/Dev/RE/docs/SD_CARD_COMPARISON.md``
- ``wiki/RE-Serial-Protocol.md``
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Sequence, Set, Tuple

from .base import ScannerProfile

# ---------------------------------------------------------------------------
# Service-type table
#
# The SDS100/200 supports 36 service types in its profile.cfg
# ``ServiceType`` mask. The numeric IDs below are the same IDs the
# scanner writes into the 8th column of TGID records and the 9th column
# of C-Freq records (verified against real SDS100 cards).
#
# IDs 1-14 overlap exactly with the BT885 (so RR imports stay
# consistent across both scanners). IDs 22-25, 26-36 add the wider
# "Tac" / "Talk" / agency-class breakdowns the SDS exposes.
#
# The SDS does **not** restrict service-type playback by hardware
# button - the user picks which TGIDs/freqs they want via Favorites
# Lists + Quick Keys. So every defined service type is scannable.
# ---------------------------------------------------------------------------

_SERVICE_TYPES: Dict[int, str] = {
    1: "Multi Dispatch",
    2: "Police Dispatch",
    3: "Fire Dispatch",
    4: "EMS Dispatch",
    5: "Multi-Tac Dispatch",
    6: "Multi-Tac",
    7: "Law Tac",
    8: "Fire-Tac",
    9: "EMS-Tac",
    10: "Multi-Talk",
    11: "Law Talk",
    12: "Fire-Talk",
    13: "EMS-Talk",
    14: "Public Works",
    15: "Federal",
    16: "Aircraft",
    17: "Coast Guard",
    18: "Marine",
    19: "Military",
    20: "Railroad",
    21: "Utilities",
    22: "Multi-Talk",
    23: "Law Talk",
    24: "Fire-Talk",
    25: "EMS-Talk",
    26: "Schools",
    27: "Security",
    28: "Hospital",
    29: "News Media",
    30: "Business",
    31: "Transportation",
    32: "Emergency Ops",
    33: "Federal",
    34: "Custom 1",
    35: "Custom 2",
    36: "Custom 3",
    209: "Auto/BTW",
}

# Every defined service type is scannable on the SDS - no per-button
# filter. We expose the full ID set so the GUI's "scannable" badge
# colors all entries correctly.
_SCANNABLE_TYPES: Set[int] = set(_SERVICE_TYPES.keys())

# The SDS has no fixed scanner buttons. The GUI's button-filter row
# is hidden for SDS profiles and ``button_filter`` returns the empty
# set for any name (no button selection narrows the playback list).
_BUTTON_FILTERS: Dict[str, Set[int]] = {}

_SERVICE_TYPE_HELP_TEXT = (
    "The SDS100/200 plays every service type by default - selection\n"
    "is done through Favorites Lists + Quick Keys, not hardware\n"
    "buttons. The 36 slot ``ServiceType`` mask in profile.cfg lets\n"
    "you mute whole categories.\n"
    "\n"
    "RadioReference imports map agency tags to these IDs the same\n"
    "way they do on the BearTracker, so the BT885 -> SDS migration\n"
    "is a straight copy.\n"
    "\n"
    "Tip: Quick Keys 1-115 are the SDS equivalent of the BT885's\n"
    "Police/Fire/EMS/DOT buttons. Assign a Favorites List to a\n"
    "Quick Key in the Favorites editor; the per-FL Quick Key\n"
    "checkbox toggles the whole list on/off."
)

_RR_SERVICE_MAP: Dict[str, int] = {
    "police": 2,
    "law enforcement": 2,
    "sheriff": 2,
    "fire": 3,
    "ems": 4,
    "emergency medical": 4,
    "public works": 14,
    "highway": 14,
    "transportation": 14,
    "property management": 14,
    "security": 27,
    "industrial": 30,
    "business": 30,
    "federal": 15,
    "aircraft": 16,
    "coast guard": 17,
    "marine": 18,
    "military": 19,
    "railroad": 20,
    "utilities": 21,
    "schools": 26,
    "hospital": 28,
    "news": 29,
    "media": 29,
    "emergency ops": 32,
}

_RR_TAG_SERVICE_MAP: Dict[str, int] = {
    "law dispatch": 2,
    "police dispatch": 2,
    "law tac": 7,
    "law talk": 11,
    "fire dispatch": 3,
    "fire-tac": 8,
    "fire-talk": 12,
    "ems dispatch": 4,
    "ems-tac": 9,
    "ems-talk": 13,
    "public works": 14,
    "multi-tac": 6,
    "multi-talk": 10,
    "multi dispatch": 1,
    "transportation": 31,
    "security": 27,
    "business": 30,
    "utilities": 21,
    "hospital": 28,
    "emergency ops": 32,
    "federal": 15,
    "aircraft": 16,
    "marine": 18,
    "railroad": 20,
}

_ENCRYPTED_RR_MODES: Set[str] = {"DE", "TE", "AE"}

_PREFERRED_INSTALLERS: List[str] = [
    "bcdx36hp_sentinel",  # Sentinel for SDS100/200
]

# TargetModel writes "BCDx36HP" on real SDS cards - that's the
# firmware-family value, not the model. Disambiguation happens via
# scanner.inf's Scanner field 1 ("SDS100" or "SDS200"). Keep the
# family alias so old workspace sidecars still match.
_TARGET_MODEL_ALIASES: Sequence[str] = ("BCDx36HP",)

_SCANNER_INF_ALIASES: Sequence[str] = ("SDS100", "SDS200")

_PRODUCT_NAME_ALIASES: Sequence[str] = ("SDS100", "SDS200")

_EDITABLE_CARD_FILE_SUFFIXES = (".hpd", ".cfg", ".HPD", ".CFG", ".inf", ".INF")

# Uniden assigns a single VID to its scanner family.
_UNIDEN_USB_VID = 0x1965
_SDS_USB_PID_MAIN = 0x001A
_SDS_USB_PID_SUB = 0x0019


class Sds100Profile(ScannerProfile):
    """Profile for the Uniden SDS100 and SDS200 scanners (one driver
    covers both, distinguished only by ``scanner.inf`` field 1)."""

    # ---- Identity ----------------------------------------------------

    @property
    def id(self) -> str:
        return "uniden_sds100"

    @property
    def display_name(self) -> str:
        return "Uniden SDS100 / SDS200"

    @property
    def family(self) -> str:
        return "uniden_bcdx36hp"

    @property
    def supports_hpd(self) -> bool:
        return True

    @property
    def supports_tgid(self) -> bool:
        return True

    @property
    def supported_file_extensions(self) -> Sequence[str]:
        return (".hpd", ".cfg", ".inf")

    @property
    def target_model_aliases(self) -> Sequence[str]:
        return _TARGET_MODEL_ALIASES

    # ---- Service types + buttons ------------------------------------

    @property
    def service_types(self) -> Dict[int, str]:
        return dict(_SERVICE_TYPES)

    def scannable_service_types(self) -> Set[int]:
        return set(_SCANNABLE_TYPES)

    def button_filter(self, button_name: str) -> Set[int]:
        # SDS has no fixed buttons; selection is via Quick Keys +
        # Favorites Lists. Return empty for every name.
        return set()

    def service_label(self, service_type: int) -> str:
        if service_type is None:
            return ""
        return _SERVICE_TYPES.get(int(service_type), "")

    def service_type_help_text(self) -> str:
        return _SERVICE_TYPE_HELP_TEXT

    # ---- RadioReference import mapping -------------------------------

    def rr_mode_to_hpd_mode(self, rr_mode: str) -> str:
        # Same logic as BT885 - the on-disk TGID Mode column is
        # ALL/ANALOG/DIGITAL on both scanners.
        if not rr_mode:
            return "ALL"
        upper = rr_mode.strip().upper()
        compact = re.sub(r"[\s\-_/]+", "", upper)

        if upper == "ALL":
            return "ALL"
        if upper == "AE":
            return "ANALOG"
        if upper in ("A", "ANALOG"):
            return "ANALOG"
        if upper in ("TE", "DE") or upper.startswith("DE/") or upper.startswith("DE "):
            return "DIGITAL"
        if upper in ("T", "TD", "D", "DMR") or "TDMA" in upper or "TDMA" in compact:
            return "DIGITAL"
        if "PHASE2" in compact or "PHASE 2" in upper:
            return "DIGITAL"
        if upper.startswith("P25"):
            return "DIGITAL"
        return "ALL"

    def is_rr_mode_encrypted(self, rr_mode: str) -> bool:
        if not rr_mode:
            return False
        return rr_mode.strip().upper() in _ENCRYPTED_RR_MODES

    def guess_service_type_from_tag(self, tag: str) -> Optional[int]:
        if not tag:
            return None
        lowered = tag.strip().lower()
        if lowered in _RR_TAG_SERVICE_MAP:
            return _RR_TAG_SERVICE_MAP[lowered]
        for keyword, service_id in _RR_SERVICE_MAP.items():
            if keyword in lowered:
                return service_id
        return None

    # ---- Firmware tables --------------------------------------------

    def read_zip_table(self, sd_root: str):
        # Same parser as BT885 - the FW tables are bit-identical
        # across the BCDx36HP family.
        try:
            import sdcard
        except Exception:
            return None
        reader = getattr(sdcard, "read_zip_table", None)
        if reader is None:
            return None
        try:
            return reader(sd_root)
        except Exception:
            return None

    def read_city_table(self, sd_root: str):
        try:
            import sdcard
        except Exception:
            return None
        reader = getattr(sdcard, "read_city_table", None)
        if reader is None:
            return None
        try:
            return reader(sd_root)
        except Exception:
            return None

    # ---- Tools -------------------------------------------------------

    def preferred_installer_ids(self) -> List[str]:
        return list(_PREFERRED_INSTALLERS)

    # ---- Card layout -------------------------------------------------

    def card_identity_files(self) -> List[str]:
        return [
            "BCDx36HP/scanner.inf",
            "BCDx36HP/HPDB/hpdb.cfg",
            "BCDx36HP/profile.cfg",
        ]

    def is_editable_config_file(self, relpath: str) -> bool:
        if not relpath:
            return False
        return relpath.endswith(_EDITABLE_CARD_FILE_SUFFIXES)

    # ---- Live-mode capability flags ---------------------------------

    @property
    def supports_serial_mode(self) -> bool:
        return True

    @property
    def supports_waterfall(self) -> bool:
        return True

    @property
    def supports_favorites_lists(self) -> bool:
        return True

    @property
    def supports_profile_cfg(self) -> bool:
        return True

    @property
    def usb_vid_pid_main(self) -> Optional[Tuple[int, int]]:
        return (_UNIDEN_USB_VID, _SDS_USB_PID_MAIN)

    @property
    def usb_vid_pid_sub(self) -> Optional[Tuple[int, int]]:
        return (_UNIDEN_USB_VID, _SDS_USB_PID_SUB)

    @property
    def scanner_inf_aliases(self) -> Sequence[str]:
        return _SCANNER_INF_ALIASES

    @property
    def product_name_aliases(self) -> Sequence[str]:
        return _PRODUCT_NAME_ALIASES

    @property
    def supports_coverage_simulation(self) -> bool:
        # SDS100/200 has on-device GPS + Favorites Lists; the live
        # mirror + scanner control panel are the primary UX. Coverage
        # heatmap stays available as an opt-in Tools menu window for
        # users who specifically want to plot their RX areas.
        return False


from .registry import register_profile

register_profile(Sds100Profile())
