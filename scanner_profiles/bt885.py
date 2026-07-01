"""Uniden BearTracker 885 scanner profile.

This is the first (and currently only) concrete :class:`ScannerProfile`
implementation. The module is intentionally self-contained - all the
constants it needs are defined here, not imported from
:mod:`scanner_manager`, so :mod:`scanner_manager` can import this
profile without creating a circular dependency.

A parity test (``tests/test_bt885_parity.py``) verifies that the
constants here stay in lock-step with the module-level constants
still used throughout :mod:`scanner_manager`.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Sequence, Set

from .base import ScannerProfile

_SERVICE_TYPES: Dict[int, str] = {
    1: "Multi Dispatch",
    2: "Police Dispatch",
    3: "Fire Dispatch",
    4: "EMS Dispatch",
    6: "Multi-Tac",
    7: "Law Tac",
    8: "Fire-Tac",
    9: "EMS-Tac",
    14: "Public Works",
    22: "Multi-Talk",
    23: "Law Talk",
    24: "Fire-Talk",
    25: "EMS-Talk",
    209: "Auto/BTW",
}

_SCANNABLE_TYPES: Set[int] = {1, 2, 3, 4, 14}

_BUTTON_FILTERS: Dict[str, Set[int]] = {
    "POLICE": {1, 2, 14},
    "EMS": {1, 4, 14},
    "FIRE": {1, 3, 14},
    "DOT": {1, 14},
}

_SERVICE_TYPE_HELP_TEXT = (
    "Which scanner button plays which kind of channel:\n"
    "  Police button   - plays Police Dispatch channels\n"
    "  Fire button     - plays Fire Dispatch channels\n"
    "  EMS button      - plays EMS Dispatch channels\n"
    "  DOT button      - plays Public Works channels\n"
    "\n"
    "Channels tagged 'Multi Dispatch' play whenever any of the four\n"
    "buttons is active. Channels tagged for a different kind (tac,\n"
    "talk, etc.) are ignored - the scanner has no button for them.\n"
    "\n"
    "Advanced: the numeric service type IDs the HPD file uses are\n"
    "  2 Police Dispatch, 3 Fire Dispatch, 4 EMS Dispatch,\n"
    "  14 Public Works, 1 Multi Dispatch.\n"
    "Everything else (Tac, Talk, Auto/BTW) is stored but not played."
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
    "security": 14,
    "industrial": 14,
    "business": 14,
}

_RR_TAG_SERVICE_MAP: Dict[str, int] = {
    "law dispatch": 2,
    "police dispatch": 2,
    "law tac": 7,
    "law talk": 23,
    "fire dispatch": 3,
    "fire-tac": 8,
    "fire-talk": 24,
    "ems dispatch": 4,
    "ems-tac": 9,
    "ems-talk": 25,
    "public works": 14,
    "multi-tac": 6,
    "multi-talk": 22,
    "multi dispatch": 1,
    "transportation": 14,
    "security": 14,
    "business": 14,
    "utilities": 14,
    "hospital": 4,
    "emergency ops": 14,
}

_ENCRYPTED_RR_MODES: Set[str] = {"DE", "TE", "AE"}

_PREFERRED_INSTALLERS: List[str] = [
    "bt885_update_manager",
    "bcdx36hp_sentinel",
]

_TARGET_MODEL_ALIASES: Sequence[str] = (
    # Historical aliases kept for backwards-compatibility with old
    # workspace sidecars + tests; real BT885 firmware writes
    # `BCDx36HP` here (verified 2026-04-27 against a real card -
    # see Metacache/Dev/RE/docs/BT885.md). The BCDx36HP family alias is
    # what we'll match on going forward; identity is disambiguated
    # via `scanner.inf` Scanner field 1 (`BT885-SCN`).
    "Beartracker885",
    "BearTracker885",
    "BT885",
    "BCDx36HP",
)

_SCANNER_INF_ALIASES: Sequence[str] = ("BT885-SCN",)

_PRODUCT_NAME_ALIASES: Sequence[str] = ("BT885", "BT885-SCN")

_EDITABLE_CARD_FILE_SUFFIXES = (".hpd", ".cfg", ".HPD", ".CFG")


class Bt885Profile(ScannerProfile):
    """Profile for the Uniden BearTracker 885 scanner."""

    # ---- Identity ----------------------------------------------------

    @property
    def id(self) -> str:
        return "uniden_bt885"

    @property
    def display_name(self) -> str:
        return "Uniden BearTracker 885"

    @property
    def family(self) -> str:
        return "uniden_beartracker"

    @property
    def supports_hpd(self) -> bool:
        return True

    @property
    def supports_tgid(self) -> bool:
        return True

    @property
    def supported_file_extensions(self) -> Sequence[str]:
        return (".hpd", ".cfg")

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
        if not button_name:
            return set()
        return set(_BUTTON_FILTERS.get(button_name.strip().upper(), set()))

    def service_label(self, service_type: int) -> str:
        return _SERVICE_TYPES.get(int(service_type), "") if service_type is not None else ""

    def service_type_help_text(self) -> str:
        return _SERVICE_TYPE_HELP_TEXT

    # ---- RadioReference import mapping -------------------------------

    def rr_mode_to_hpd_mode(self, rr_mode: str) -> str:
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
        try:
            import core.sdcard as sdcard
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
            import core.sdcard as sdcard
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
        # Real BT885 cards keep HPDB at BCDx36HP/HPDB/hpdb.cfg, plus a
        # scanner.inf fingerprint at BCDx36HP/scanner.inf. The legacy
        # bare "hpdb.cfg" entry stays so older fingerprints keep
        # matching.
        return [
            "BCDx36HP/HPDB/hpdb.cfg",
            "BCDx36HP/scanner.inf",
            "hpdb.cfg",
        ]

    def is_editable_config_file(self, relpath: str) -> bool:
        if not relpath:
            return False
        return relpath.endswith(_EDITABLE_CARD_FILE_SUFFIXES)

    # ---- Live-mode capability flags (BT885 has no serial mode) ------

    @property
    def uses_hardware_button_semantics(self) -> bool:
        return True

    @property
    def supports_serial_mode(self) -> bool:
        return False

    @property
    def supports_waterfall(self) -> bool:
        return False

    @property
    def supports_favorites_lists(self) -> bool:
        return False

    @property
    def supports_profile_cfg(self) -> bool:
        return False

    @property
    def scanner_inf_aliases(self) -> Sequence[str]:
        return _SCANNER_INF_ALIASES

    @property
    def product_name_aliases(self) -> Sequence[str]:
        return _PRODUCT_NAME_ALIASES


from .registry import register_profile

register_profile(Bt885Profile())
