#!/usr/bin/env python3
"""
Beartracker 885 Scanner Manager

Manage HPD frequency/talkgroup files for the Uniden Beartracker 885 scanner.
Load files from the SD card, browse the tree of counties/groups/frequencies,
edit service types, add new entries from RadioReference, and save back.
"""

import json
import os
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.parse
import urllib.request
import uuid
import webbrowser
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import core.app_updater as updater
import core.coverage_maps as coverage_maps
import core.sdcard as sdcard
import core.uniden_tools as uniden_tools
from core.metastore import (
    OP_ADD_ENTRY,
    OP_ADD_GROUP,
    OP_BULK_REVERT,
    OP_DELETE_ENTRY,
    OP_DELETE_GROUP,
    OP_DELETE_SYSTEM,
    OP_EDIT_ENTRY,
    OP_EDIT_GROUP,
    OP_EDIT_SYSTEM,
    OP_EXTERNAL_CHANGE,
    OP_IMPORT_APPLY,
    OP_LINK_RR,
    OP_REVERT,
    OP_SET_SERVICE,
    OP_UNLINK_RR,
    Event,
    GlobalMetaStore,
    MetaStore,
    entry_id_for,
    group_id_for,
    session_snapshot_path,
    system_id_for,
    write_session_snapshot,
)
from legacy_tk.coverage_ui import CoverageHeatmapDialog, CoverageMapDialog
from legacy_tk.geo_tables import (  # noqa: F401 — re-exported for tests / gui
    CityRecord,
    CustomLocationsStore,
    FirmwareCityTable,
    FirmwareZipTable,
    ScannerCityIndex,
    ZipCountyLookup,
    discover_alert_files,
    resolve_city_offline,
)
from legacy_tk.import_dialogs import (
    ConventionalImportSelectionDialog,
    TrunkedImportSelectionDialog,
)
from legacy_tk.literals import (
    _LIT_ALL_FILES,
    _LIT_AUTO_FROM_ZIP,
    _LIT_BULK_REMAP,
    _LIT_BUTTON_1,
    _LIT_COMBOBOX_SELECTED,
    _LIT_COVERAGE_HEATMAP,
    _LIT_COVERAGE_MAP,
    _LIT_EXE_GLOB,
    _LIT_FETCH_ERROR,
    _LIT_FREQ_MHZ_COLON,
    _LIT_LOAD_HPD_FIRST,
    _LIT_MODE_COLON,
    _LIT_NAME_COLON,
    _LIT_NO_FREQS_ON_PAGE,
    _LIT_NO_FREQUENCIES,
    _LIT_PROFILE_NOT_FOUND,
    _LIT_RESTORE_SESSION,
    _LIT_RESTORE_SNAPSHOT,
    _LIT_REVERT_TO_POINT,
    _LIT_RR_GROUP,
    _LIT_SELECT_TOOL_FIRST,
    _LIT_SWAP_PROFILE,
    _LIT_TREE_HEADINGS,
    _LIT_TREEVIEW_SELECT,
)
from legacy_tk.rr_parsing import (  # noqa: F401 — re-exported for tests / gui
    RR_SERVICE_MAP,
    _parse_rr_category_aid,
    _parse_rr_conventional_ctid,
    _parse_rr_fcc_callsign,
    _parse_rr_trs_sid,
    _rr_trs_mode_to_hpd,
    classify_rr_tg_import_action,
    diff_cfreq_with_rr,
    diff_tgid_with_rr,
    fetch_radioreference_data,
    is_rr_mode_encrypted,
)
from legacy_tk.sd_paths import filesystem_space_root, resolve_existing_folder, validated_sd_folder
from legacy_tk.sm_helpers import (  # noqa: F401 — many symbols re-exported for tests
    AddEntryValidation,
    MetastoreRevertOps,
    add_entry_from_snapshot,
    alerts_file_tree_rows,
    alerts_viewer_summary,
    append_fuzzy_licensee_rr_candidates,
    append_rr_candidate,
    apply_metastore_revert,
    apply_revert_import_payload,
    apply_sync_conflict_decision,
    audit_mode_issue_with_rr,
    audit_mode_issues,
    build_custom_city_records,
    card_identity_matches_profile,
    card_state_display,
    cfreq_diff_tree_rows,
    cfreq_import_service_type,
    collect_mode_audit_rows,
    compute_group_coverage_info,
    county_mismatch_reason,
    default_state_combo_index,
    discover_backups,
    entry_identity_display,
    entry_matches_bulk_filter,
    entry_passes_button_filter,
    events_newer_than_pivot,
    filter_meta_events,
    find_entry_after_update,
    find_group_after_update,
    find_hpdb_config,
    find_system_after_update,
    flatten_rr_cfreq_rows,
    flatten_rr_tg_rows,
    format_vsd_section,
    geo_distance_mismatch_reason,
    group_coverage_tree_tag,
    group_geo_strings,
    group_tower_members_by_system,
    group_tree_label,
    hpd_path_inside_workspace,
    iter_bulk_remap_candidates,
    local_cfreq_by_hz,
    local_tgid_by_id,
    location_scope_label,
    merge_reconcile_report_message,
    parse_rr_import_freq_hz,
    pipeline_health_color,
    pipeline_push_stage,
    pipeline_report_lines,
    pipeline_sync_pull_summary,
    pipeline_tool_abort_reason,
    pipeline_tools_info,
    qr_code_matrix,
    replay_entry_type_and_identity,
    replay_norm,
    resolve_script_dir,
    resolve_target_system,
    restore_import_deleted_entry,
    rr_callsign_urls,
    rr_diff_mode,
    rr_fetch_display_name,
    rr_pull_entry_row,
    rr_recent_url_candidates,
    run_updater_reconcile_sequence,
    select_installed_uniden_tool,
    service_choice_for_type,
    sort_rr_candidates,
    suggest_mode_for_freq,
    summarize_revert_import,
    sync_result_summary,
    system_matches_location,
    system_tree_label,
    tgid_diff_tree_rows,
    validate_add_entry,
    workspace_clone_result,
    zip_lookup_status_message,
)
from legacy_tk.sm_helpers import (
    crossref_hint_for_rr_row as lookup_crossref_hint_for_rr_row,
)
from scanner_profiles import (
    DEFAULT_PROFILE_ID,
    get_active_profile,
    set_active_profile,
)

# ---------------------------------------------------------------------------
# Project-level constants (single source of truth for version + URLs)
# ---------------------------------------------------------------------------

APP_NAME = "Scanner Manager"
APP_TAGLINE = "Uniden BearTracker 885 SD card companion"
APP_GITHUB_URL = "https://github.com/disturbedkh/scanner-manager"
APP_WIKI_URL = f"{APP_GITHUB_URL}/wiki"
APP_ISSUES_URL = f"{APP_GITHUB_URL}/issues"
APP_RELEASES_URL = f"{APP_GITHUB_URL}/releases"

DONATE_PAYPAL_URL = "https://paypal.me/gvillescanner"
DONATE_BTC_ADDR = "3FEgJ7y5qpagB2NqZaNhCurx8tA3cC8Gv3"
DONATE_ETH_ADDR = "0xC407c8f7b1f35182341AC914B5A51D867Ae986FA"
DONATE_USDT_ERC20_ADDR = "0xA34409BD5612FF23727fB6aEA0d584Bf0e841365"


def get_app_version() -> str:
    """Return the installed package version, or a dev fallback.

    Uses ``importlib.metadata`` so the EXE built by PyInstaller picks up
    the version from the pyproject-generated metadata just like a
    ``pip install -e .`` run does.
    """
    try:
        from importlib.metadata import PackageNotFoundError, version
        try:
            return version("beartracker-885-scanner-manager")
        except PackageNotFoundError:
            return "0.9.0b2-dev"
    except Exception:
        return "0.9.0b2-dev"


APP_VERSION = get_app_version()

IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")


def _repo_root() -> Path:
    """Repository root when running the legacy Tk app from a checkout."""
    return Path(__file__).resolve().parents[1]


def bundled_resources_dir() -> Path:
    """Return the dir that holds read-only assets (``data/...``) at runtime.

    When running from a PyInstaller one-file EXE, this is ``_MEIPASS``
    (the temp extraction dir). When running from source, it's the repo
    root (parent of ``legacy_tk/``).
    """
    mei = getattr(sys, "_MEIPASS", None)
    if mei:
        return Path(mei)
    return _repo_root()


def open_in_file_manager(path: str) -> None:
    """Open ``path`` in the host OS's file manager.

    Wraps the three platform idioms (``os.startfile`` on Windows,
    ``open`` on macOS, ``xdg-open`` on Linux/BSD) so the caller can
    just pass a path without a platform check. Raises the underlying
    exception on failure so callers can surface a meaningful error.
    """
    if IS_WINDOWS:
        os.startfile(path)  # type: ignore[attr-defined]
    elif IS_MACOS:
        import subprocess as _sp
        _sp.run(["open", path], check=False)
    else:
        import subprocess as _sp
        _sp.run(["xdg-open", path], check=False)


try:
    import core.rr_api as rr_api
except Exception:  # pragma: no cover - module always imports
    rr_api = None  # type: ignore

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Active scanner profile. The default is the BearTracker 885; the
# desktop app reassigns it (via ``scanner_profiles.set_active_profile``)
# whenever the user opens a new SD card or picks a different Device
# in the top selector. We expose it through a thin proxy so that
# every attribute access (``ACTIVE_PROFILE.scannable_service_types()``)
# resolves against the *current* registry value rather than a snapshot
# captured at import time.
set_active_profile(DEFAULT_PROFILE_ID)


class _ActiveProfileProxy:
    """Always-fresh view of ``scanner_profiles.get_active_profile()``.

    Behaves like a ``ScannerProfile`` for every attribute lookup; the
    indirection lets the rest of this module write
    ``ACTIVE_PROFILE.scannable_service_types()`` without caring that
    a Device swap could have replaced the profile under it.
    """

    __slots__ = ()

    def __getattr__(self, item: str):
        return getattr(get_active_profile(), item)

    def __repr__(self) -> str:
        return f"<ActiveProfile -> {get_active_profile()!r}>"


ACTIVE_PROFILE = _ActiveProfileProxy()

SERVICE_TYPES = {
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

SCANNABLE_TYPES = {1, 2, 3, 4, 14}

SERVICE_CHOICES = [
    (1, "1 - Multi Dispatch"),
    (2, "2 - Police Dispatch"),
    (3, "3 - Fire Dispatch"),
    (4, "4 - EMS Dispatch"),
    (6, "6 - Multi-Tac"),
    (7, "7 - Law Tac"),
    (8, "8 - Fire-Tac"),
    (9, "9 - EMS-Tac"),
    (14, "14 - Public Works"),
    (22, "22 - Multi-Talk"),
    (23, "23 - Law Talk"),
    (24, "24 - Fire-Talk"),
    (25, "25 - EMS-Talk"),
]

MODE_CHOICES_CONV = ["FM", "NFM", "AM", "AUTO"]
# BearTracker 885 HPD format (verified against real SD card):
#   TGID Mode column only ever contains ALL / ANALOG / DIGITAL.
#   There is NO separate TDMA token — TDMA (P25 Phase II) is decoded
#   automatically based on the Trunk record's system type (P25Standard).
#   So DIGITAL covers both P25 Phase I (FDMA) and Phase II (TDMA).
MODE_CHOICES_TGID = ["ALL", "ANALOG", "DIGITAL"]

# Friendly labels for UI. Canonical value (what we store in the HPD file)
# -> human label shown in the GUI. The label explains that DIGITAL covers
# (D) P25 Phase I FDMA *and* (T) P25 Phase II TDMA on this scanner.
TGID_MODE_UI_LABELS: Dict[str, str] = {
    "ALL": "ALL (auto D/T/A)",
    "ANALOG": "ANALOG (A)",
    "DIGITAL": "DIGITAL (D / T TDMA)",
}
TGID_MODE_LABEL_TO_CANONICAL: Dict[str, str] = {
    label: canonical for canonical, label in TGID_MODE_UI_LABELS.items()
}
MODE_CHOICES_TGID_LABELS: List[str] = [
    TGID_MODE_UI_LABELS[c] for c in MODE_CHOICES_TGID
]


def tgid_mode_label(canonical: str) -> str:
    """Render an HPD TGID mode value (ALL/ANALOG/DIGITAL/legacy) as a UI label."""
    if not canonical:
        return ""
    key = canonical.strip().upper()
    return TGID_MODE_UI_LABELS.get(key, canonical)


def tgid_mode_canonical(label: str) -> str:
    """Convert a UI label (or canonical/legacy value) back to an HPD-safe token."""
    if not label:
        return ""
    stripped = label.strip()
    if stripped in TGID_MODE_LABEL_TO_CANONICAL:
        return TGID_MODE_LABEL_TO_CANONICAL[stripped]
    upper = stripped.upper()
    if upper in ("D", "DMR"):
        return "DIGITAL"
    if upper in ("T", "TD", "TDMA"):
        return "DIGITAL"
    if upper == "DE":
        return "DIGITAL"  # scanner can't decode; flagged elsewhere
    if upper in ("A", "ANALOG"):
        return "ANALOG"
    if upper == "AE":
        return "ANALOG"
    if upper == "ALL":
        return "ALL"
    if upper in {"ALL", "ANALOG", "DIGITAL"}:
        return upper
    return upper or ""

SERVICE_TYPE_HELP_TEXT = (
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

# HPD data model, parser, and geo helpers (canonical implementation in core.hpd)
from core.hpd import (  # noqa: F401 — geo symbols re-exported for gui / tests
    EntryCustomization,
    FreqEntry,
    GroupNode,
    HpdConfig,
    HpdFile,
    SystemNode,
    haversine_miles,
    nearest_distance_miles,
    rectangle_contains_point,
    system_covers_point,
    system_has_geo,
)

# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def format_freq(freq_hz: int) -> str:
    """Convert Hz integer to readable MHz string."""
    if freq_hz == 0:
        return ""
    mhz = freq_hz / 1_000_000
    return f"{mhz:.4f} MHz"


def parse_freq_mhz(text: str) -> int:
    """Convert user-entered MHz string to Hz integer."""
    cleaned = text.strip().upper().replace("MHZ", "").replace(" ", "").replace(",", "")
    mhz = float(cleaned)
    return int(round(mhz * 1_000_000))


def service_label(stype: int) -> str:
    name = SERVICE_TYPES.get(stype, f"Type {stype}")
    return f"{stype} - {name}"


def is_scannable(stype: int) -> bool:
    return stype in SCANNABLE_TYPES


def list_backups_for(source_path: str) -> List[Path]:
    """Return backup files for source_path sorted oldest-first."""
    directory = Path(source_path).parent
    base_name = Path(source_path).name
    prefix = f"{base_name}.backup_"
    items: List[Path] = []
    if not directory.exists():
        return items
    for p in directory.iterdir():
        if p.is_file() and p.name.startswith(prefix):
            items.append(p)
    items.sort(key=lambda p: p.stat().st_mtime)
    return items


def prune_backups(source_path: str, max_backups: int) -> List[Path]:
    """Delete oldest backups for source_path so only the newest max_backups remain.

    Returns the list of successfully removed paths. Unlink failures are silenced.
    For a richer result (including failures), use :func:`prune_backups_detailed`.
    """
    result = prune_backups_detailed(source_path, max_backups)
    return result["removed"]


def prune_backups_detailed(source_path: str, max_backups: int) -> Dict[str, Any]:
    """Like :func:`prune_backups` but returns detailed results:
    {
        "candidates": [Path, ...] (files that should have been deleted),
        "removed": [Path, ...],
        "failed": [(Path, error_message), ...],
    }
    """
    info: Dict[str, Any] = {"candidates": [], "removed": [], "failed": []}
    if max_backups is None or max_backups < 0:
        return info
    backups = list_backups_for(source_path)
    if len(backups) <= max_backups:
        return info
    to_delete = backups[: len(backups) - max_backups]
    info["candidates"] = list(to_delete)
    for p in to_delete:
        try:
            p.unlink()
            info["removed"].append(p)
        except Exception as exc:
            info["failed"].append((p, str(exc)))
    return info


# Band/mode audit + bulk filter helpers live in legacy_tk.sm_helpers (re-exported above).


# ---------------------------------------------------------------------------
# Main GUI Application
# ---------------------------------------------------------------------------

class ScannerManagerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self._base_title = f"{APP_NAME} v{APP_VERSION}"
        self.root.title(self._base_title)
        self.root.geometry("1280x820")
        self.root.minsize(900, 600)
        self._build_menubar()
        self._init_core_models()
        self._init_filter_state()
        self._init_storage_and_meta()
        self._build_gui()
        self._finish_startup()

    def _init_core_models(self) -> None:
        self.hpd = HpdFile()
        self.config = HpdConfig()
        self.config_loaded = False
        self.zip_lookup = ZipCountyLookup(
            _repo_root(),
            bundled_dir=bundled_resources_dir(),
        )

    def _init_filter_state(self) -> None:
        self._selected_entry: Optional[FreqEntry] = None
        self._selected_group: Optional[GroupNode] = None
        self._selected_system: Optional[SystemNode] = None
        self._tree_id_map: Dict[str, object] = {}
        self._button_police = tk.BooleanVar(value=True)
        self._button_fire = tk.BooleanVar(value=True)
        self._button_ems = tk.BooleanVar(value=True)
        self._button_dot = tk.BooleanVar(value=True)
        self._button_multi = tk.BooleanVar(value=True)
        self._include_others = tk.BooleanVar(value=True)
        self._sd_space_var = tk.StringVar(value="")
        self._last_reconcile_audit: Optional[Path] = None
        self._state_id_list: List[int] = []
        self._location_filter_enabled = tk.BooleanVar(value=False)
        self._zip_var = tk.StringVar()
        self._county_var = tk.StringVar(value=_LIT_AUTO_FROM_ZIP)
        self._county_choices: List[Tuple[int, str]] = []
        self._active_zip: Optional[str] = None
        self._active_county_id: Optional[int] = None
        self._active_coords: Optional[Tuple[float, float]] = None
        self._coverage_tolerance_var = tk.IntVar(value=0)
        self._updater_path_var = tk.StringVar()
        self._merge_report: Optional[Dict[str, int]] = None
        self._firmware_zip_table = FirmwareZipTable()
        self._firmware_zip_loaded = False
        self._firmware_city_table = FirmwareCityTable()
        self._firmware_city_loaded = False

    def _init_storage_and_meta(self) -> None:
        self._script_dir = resolve_script_dir(_repo_root)
        self._custom_locations = CustomLocationsStore(self._script_dir)
        self._app_settings_path = self._script_dir / "app_settings.json"
        self._app_settings = self._load_app_settings()
        self._city_index = ScannerCityIndex()
        self._city_index_state_id: Optional[int] = None
        self._city_var = tk.StringVar()
        self._global_meta = GlobalMetaStore(
            self._script_dir / GlobalMetaStore.DEFAULT_FILENAME
        )
        self._meta: Optional[MetaStore] = None
        self._session_snapshot_paths: Set[str] = set()
        self._session_snapshot_enabled = tk.BooleanVar(
            value=bool(self._app_settings.get("session_snapshot_enabled", True))
        )

    def _finish_startup(self) -> None:
        saved_path = validated_sd_folder(self._app_settings.get("sd_path", ""))
        if saved_path:
            self._set_status(f"Ready. Last SD card path: {saved_path}. Click Load.")
        else:
            self._set_status("Ready. Browse to your SD card's BCDx36HP folder to begin.")
        self._refresh_sd_space()
        if not self._app_settings.get("first_run_seen"):
            self.root.after(250, self._show_first_run_notice)
        self.root.after(5000, lambda: self._run_update_check(manual=False))

    # ---- GUI Construction -------------------------------------------------

    def _build_menubar(self) -> None:
        """Top-level Help menu. We only add what's truly universally
        useful here; per-feature commands stay on the toolbars.
        """
        menubar = tk.Menu(self.root)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(
            label="Open Wiki", command=self._on_help_wiki,
        )
        help_menu.add_command(
            label="Check for Updates...", command=self._on_help_check_for_updates,
        )
        help_menu.add_command(
            label="Report an Issue...", command=self._on_help_report_issue,
        )
        help_menu.add_separator()
        help_menu.add_command(
            label="Donate / Support...", command=self._on_help_donate,
        )
        help_menu.add_separator()
        help_menu.add_command(
            label=f"About {APP_NAME}...", command=self._on_help_about,
        )
        menubar.add_cascade(label="Help", menu=help_menu)

        self.root.configure(menu=menubar)

    def _build_gui(self):
        style = ttk.Style()
        style.configure("Treeview", rowheight=22)

        self._build_toolbar()
        self._build_main_area()
        self._build_status_bar()

    def _build_toolbar(self):
        self._build_toolbar_row1()
        self._build_toolbar_row2()
        self._build_toolbar_row3()

    def _build_toolbar_row1(self):
        row1 = ttk.Frame(self.root, padding=(5, 5, 5, 2))
        row1.pack(fill=tk.X, side=tk.TOP)
        ttk.Label(row1, text="SD Card Folder:").pack(side=tk.LEFT)
        self._path_var = tk.StringVar(value=self._app_settings.get("sd_path", ""))
        ttk.Entry(row1, textvariable=self._path_var, width=50).pack(side=tk.LEFT, padx=(5, 2))
        ttk.Button(row1, text="Browse", command=self._on_browse).pack(side=tk.LEFT, padx=2)
        ttk.Button(row1, text="Load", command=self._on_load).pack(side=tk.LEFT, padx=2)
        ttk.Separator(row1, orient=tk.VERTICAL).pack(side=tk.LEFT, padx=8, fill=tk.Y)
        ttk.Label(row1, text="State:").pack(side=tk.LEFT)
        self._state_var = tk.StringVar()
        self._state_combo = ttk.Combobox(
            row1, textvariable=self._state_var, state="readonly", width=22,
        )
        self._state_combo.pack(side=tk.LEFT, padx=(5, 2))
        self._state_combo.bind(_LIT_COMBOBOX_SELECTED, self._on_state_selected)
        ttk.Separator(row1, orient=tk.VERTICAL).pack(side=tk.LEFT, padx=8, fill=tk.Y)
        ttk.Button(row1, text="Save", command=self._on_save).pack(side=tk.LEFT, padx=2)
        ttk.Button(
            row1, text="Run Update Pipeline",
            command=self._on_run_update_pipeline,
        ).pack(side=tk.LEFT, padx=2)
        ttk.Button(
            row1, text="Uniden Tools...",
            command=self._on_open_uniden_tools,
        ).pack(side=tk.LEFT, padx=2)
        ttk.Separator(row1, orient=tk.VERTICAL).pack(side=tk.LEFT, padx=8, fill=tk.Y)
        ttk.Button(
            row1, text="Workspace...",
            command=self._on_manage_workspaces,
        ).pack(side=tk.LEFT, padx=2)
        ttk.Button(
            row1, text="Sync from SD",
            command=self._on_sync_from_sd,
        ).pack(side=tk.LEFT, padx=2)
        ttk.Button(
            row1, text="Sync to SD",
            command=self._on_sync_to_sd,
        ).pack(side=tk.LEFT, padx=2)
        ttk.Button(
            row1, text="Swap Profile...",
            command=self._on_swap_profile,
        ).pack(side=tk.LEFT, padx=2)
        ttk.Separator(row1, orient=tk.VERTICAL).pack(side=tk.LEFT, padx=8, fill=tk.Y)
        ttk.Button(
            row1, text="RR API...",
            command=self._on_open_rr_settings,
        ).pack(side=tk.LEFT, padx=2)
        ttk.Button(
            row1, text="RR Pull...",
            command=self._on_open_rr_pull,
        ).pack(side=tk.LEFT, padx=2)

    def _build_toolbar_row2(self):
        row2 = ttk.Frame(self.root, padding=(5, 2, 5, 2))
        row2.pack(fill=tk.X, side=tk.TOP)
        ttk.Label(row2, text="ZIP:").pack(side=tk.LEFT)
        ttk.Entry(row2, textvariable=self._zip_var, width=8).pack(side=tk.LEFT, padx=(4, 2))
        ttk.Button(row2, text="Lookup", command=self._on_zip_lookup).pack(side=tk.LEFT, padx=2)
        ttk.Separator(row2, orient=tk.VERTICAL).pack(side=tk.LEFT, padx=8, fill=tk.Y)
        ttk.Label(row2, text="City:").pack(side=tk.LEFT)
        ttk.Entry(row2, textvariable=self._city_var, width=14).pack(side=tk.LEFT, padx=(4, 2))
        ttk.Button(row2, text="City Lookup", command=self._on_city_lookup).pack(side=tk.LEFT, padx=2)
        ttk.Button(row2, text="Cities...", command=self._on_manage_cities).pack(side=tk.LEFT, padx=2)
        ttk.Separator(row2, orient=tk.VERTICAL).pack(side=tk.LEFT, padx=8, fill=tk.Y)
        ttk.Label(row2, text="County:").pack(side=tk.LEFT)
        self._county_combo = ttk.Combobox(
            row2, textvariable=self._county_var, state="readonly", width=24
        )
        self._county_combo["values"] = [_LIT_AUTO_FROM_ZIP]
        self._county_combo.current(0)
        self._county_combo.bind(_LIT_COMBOBOX_SELECTED, self._on_county_override_changed)
        self._county_combo.pack(side=tk.LEFT, padx=(4, 2))
        ttk.Checkbutton(
            row2, text="Apply Location Filter",
            variable=self._location_filter_enabled,
            command=self._on_filter_changed,
        ).pack(side=tk.LEFT, padx=4)
        ttk.Label(row2, text="Extra mi:").pack(side=tk.LEFT, padx=(8, 0))
        ttk.Spinbox(
            row2, from_=0, to=200, increment=5, width=5,
            textvariable=self._coverage_tolerance_var,
            command=self._on_filter_changed,
        ).pack(side=tk.LEFT, padx=(2, 2))

    def _build_toolbar_row3(self):
        row3 = ttk.Frame(self.root, padding=(5, 2, 5, 4))
        row3.pack(fill=tk.X, side=tk.TOP)
        ttk.Label(row3, text="Scanner buttons:").pack(side=tk.LEFT)
        for label, var in (
            ("Police (2)", self._button_police),
            ("Fire (3)", self._button_fire),
            ("EMS (4)", self._button_ems),
            ("DOT (14)", self._button_dot),
            ("Multi (1)", self._button_multi),
        ):
            ttk.Checkbutton(
                row3, text=label, variable=var, command=self._on_filter_changed,
            ).pack(side=tk.LEFT, padx=3)
        ttk.Separator(row3, orient=tk.VERTICAL).pack(side=tk.LEFT, padx=8, fill=tk.Y)
        ttk.Checkbutton(
            row3, text="Include other types",
            variable=self._include_others,
            command=self._on_filter_changed,
        ).pack(side=tk.LEFT, padx=3)
        ttk.Button(
            row3, text="Export Effective Scan Set...",
            command=self._on_export_scan_set,
        ).pack(side=tk.RIGHT, padx=5)
        ttk.Button(
            row3, text="Alerts...",
            command=self._on_view_alerts,
        ).pack(side=tk.RIGHT, padx=2)
        ttk.Button(
            row3, text="Heatmap...",
            command=self._on_coverage_heatmap,
        ).pack(side=tk.RIGHT, padx=2)
        ttk.Button(
            row3, text="Map...",
            command=self._on_coverage_map,
        ).pack(side=tk.RIGHT, padx=2)
        ttk.Button(
            row3, text="Bulk Remap...",
            command=self._on_bulk_remap,
        ).pack(side=tk.RIGHT, padx=2)
        ttk.Button(
            row3, text="Audit Modes",
            command=self._on_mode_band_audit,
        ).pack(side=tk.RIGHT, padx=2)
        ttk.Button(
            row3, text="Changes...",
            command=self._on_show_changes,
        ).pack(side=tk.RIGHT, padx=2)
        ttk.Button(
            row3, text="Restore Session...",
            command=self._on_restore_session_snapshot,
        ).pack(side=tk.RIGHT, padx=2)
        ttk.Button(
            row3, text="Audit",
            command=self._on_show_last_audit,
        ).pack(side=tk.RIGHT, padx=2)

    def _build_main_area(self):
        paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        left = ttk.Frame(paned)
        paned.add(left, weight=3)

        right = ttk.Frame(paned)
        paned.add(right, weight=2)

        self._build_tree(left)
        self._build_right_panel(right)

    def _build_tree(self, parent: ttk.Frame):
        cols = ("freq_tgid", "mode", "service")
        self.tree = ttk.Treeview(
            parent, columns=cols, selectmode="browse", show=_LIT_TREE_HEADINGS,
        )
        self._configure_tree_headings()
        self._configure_tree_tags()
        self._layout_tree_with_scrollbars(parent)

    def _configure_tree_headings(self) -> None:
        self.tree.heading("#0", text="Name", anchor=tk.W)
        self.tree.heading("freq_tgid", text="Freq / TGID", anchor=tk.W)
        self.tree.heading("mode", text="Mode", anchor=tk.W)
        self.tree.heading("service", text="Service Type", anchor=tk.W)
        self.tree.column("#0", width=350, minwidth=200)
        self.tree.column("freq_tgid", width=130, minwidth=80)
        self.tree.column("mode", width=60, minwidth=50)
        self.tree.column("service", width=160, minwidth=100)

    def _configure_tree_tags(self) -> None:
        self.tree.tag_configure("scannable", foreground="#006400")
        self.tree.tag_configure("nonscannable", foreground="#888888")
        self.tree.tag_configure("system", font=("TkDefaultFont", 10, "bold"))
        self.tree.tag_configure("group", font=("TkDefaultFont", 9, "bold"))
        self.tree.tag_configure(
            "group_in_range", font=("TkDefaultFont", 9, "bold"), foreground="#006400"
        )
        self.tree.tag_configure(
            "group_nearby", font=("TkDefaultFont", 9, "bold"), foreground="#b8860b"
        )
        self.tree.tag_configure(
            "group_out_range", font=("TkDefaultFont", 9, "bold"), foreground="#b22222"
        )
        self.tree.tag_configure(
            "group_no_geo", font=("TkDefaultFont", 9, "bold"), foreground="#606060"
        )

    def _layout_tree_with_scrollbars(self, parent: ttk.Frame) -> None:
        vsb = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        hsb = ttk.Scrollbar(parent, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        parent.grid_rowconfigure(0, weight=1)
        parent.grid_columnconfigure(0, weight=1)
        self.tree.bind(_LIT_TREEVIEW_SELECT, self._on_tree_select)
        self.tree.bind("<Button-3>", self._on_tree_right_click)

    def _build_right_panel(self, parent: ttk.Frame):
        parent.grid_rowconfigure(0, weight=1)
        parent.grid_rowconfigure(1, weight=1)
        parent.grid_columnconfigure(0, weight=1)

        self._build_details_panel(parent)
        self._build_add_panel(parent)

    def _build_details_panel(self, parent: ttk.Frame):
        frame = ttk.LabelFrame(parent, text="Selected Entry Details", padding=10)
        frame.grid(row=0, column=0, sticky="nsew", pady=(0, 5))
        self._detail_labels: Dict[str, ttk.Label] = {}
        self._build_detail_field_rows(frame)
        self._build_detail_edit_controls(frame)

    def _build_detail_field_rows(self, frame: ttk.LabelFrame) -> None:
        detail_fields = [
            ("Type:", "type"),
            (_LIT_NAME_COLON, "name"),
            ("Frequency / TGID:", "freq"),
            (_LIT_MODE_COLON, "mode"),
            ("Tone / NAC:", "tone"),
            ("Service Type:", "service"),
            ("Group:", "group"),
        ]
        for i, (label_text, key) in enumerate(detail_fields):
            ttk.Label(frame, text=label_text, font=("TkDefaultFont", 9, "bold")).grid(
                row=i, column=0, sticky=tk.W, pady=2,
            )
            lbl = ttk.Label(frame, text="—")
            lbl.grid(row=i, column=1, sticky=tk.W, padx=(10, 0), pady=2)
            self._detail_labels[key] = lbl
        self._detail_sep_row = len(detail_fields)

    def _build_detail_edit_controls(self, frame: ttk.LabelFrame) -> None:
        sep_row = self._detail_sep_row
        ttk.Separator(frame, orient=tk.HORIZONTAL).grid(
            row=sep_row, column=0, columnspan=3, sticky="ew", pady=8,
        )
        edit_row = sep_row + 1
        ttk.Label(frame, text="Change Service Type:").grid(
            row=edit_row, column=0, sticky=tk.W, pady=2,
        )
        self._edit_stype_var = tk.StringVar()
        self._edit_stype_combo = ttk.Combobox(
            frame, textvariable=self._edit_stype_var, state="readonly", width=22,
            values=[s[1] for s in SERVICE_CHOICES],
        )
        self._edit_stype_combo.grid(row=edit_row, column=1, sticky=tk.W, padx=(10, 0))
        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=edit_row + 1, column=0, columnspan=2, pady=8)
        ttk.Button(btn_frame, text="Update Service Type", command=self._on_update_service).pack(
            side=tk.LEFT, padx=3,
        )
        ttk.Button(btn_frame, text="Edit...", command=self._on_edit_selected).pack(
            side=tk.LEFT, padx=3,
        )
        ttk.Button(btn_frame, text="Delete", command=self._on_delete_selected).pack(
            side=tk.LEFT, padx=3,
        )
        ttk.Separator(frame, orient=tk.HORIZONTAL).grid(
            row=edit_row + 2, column=0, columnspan=2, sticky="ew", pady=(6, 6)
        )
        ttk.Label(
            frame,
            text=SERVICE_TYPE_HELP_TEXT,
            foreground="#555555",
            justify=tk.LEFT,
            wraplength=360,
        ).grid(row=edit_row + 3, column=0, columnspan=2, sticky=tk.W)

    def _build_add_panel(self, parent: ttk.Frame):
        frame = ttk.LabelFrame(parent, text="Add New Entry (from RadioReference)", padding=10)
        frame.grid(row=1, column=0, sticky="nsew", pady=(5, 0))

        self._add_type_var = tk.StringVar(value="Conventional")
        type_frame = ttk.Frame(frame)
        type_frame.grid(row=0, column=0, columnspan=2, sticky=tk.W, pady=(0, 5))
        ttk.Radiobutton(
            type_frame, text="Conventional Frequency", variable=self._add_type_var,
            value="Conventional", command=self._on_add_type_changed,
        ).pack(side=tk.LEFT, padx=(0, 15))
        ttk.Radiobutton(
            type_frame, text="Trunked Talkgroup", variable=self._add_type_var,
            value="Trunked", command=self._on_add_type_changed,
        ).pack(side=tk.LEFT)

        url_row = 1
        ttk.Label(frame, text="RadioReference URL:").grid(row=url_row, column=0, sticky=tk.W, pady=2)
        url_frame = ttk.Frame(frame)
        url_frame.grid(row=url_row, column=1, sticky=tk.W, padx=(10, 0), pady=2)
        self._add_rr_url_var = tk.StringVar()
        ttk.Entry(url_frame, textvariable=self._add_rr_url_var, width=28).pack(side=tk.LEFT)
        ttk.Button(url_frame, text="Fetch", command=self._on_fetch_rr_url).pack(side=tk.LEFT, padx=(4, 0))

        row = url_row + 1
        ttk.Label(frame, text="Name / Description:").grid(row=row, column=0, sticky=tk.W, pady=2)
        self._add_name_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self._add_name_var, width=30).grid(
            row=row, column=1, sticky=tk.W, padx=(10, 0), pady=2,
        )

        row += 1
        self._add_freq_label = ttk.Label(frame, text=_LIT_FREQ_MHZ_COLON)
        self._add_freq_label.grid(row=row, column=0, sticky=tk.W, pady=2)
        self._add_freq_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self._add_freq_var, width=20).grid(
            row=row, column=1, sticky=tk.W, padx=(10, 0), pady=2,
        )

        row += 1
        ttk.Label(frame, text=_LIT_MODE_COLON).grid(row=row, column=0, sticky=tk.W, pady=2)
        self._add_mode_var = tk.StringVar(value="NFM")
        self._add_mode_combo = ttk.Combobox(
            frame, textvariable=self._add_mode_var, state="readonly", width=10,
            values=MODE_CHOICES_CONV,
        )
        self._add_mode_combo.grid(row=row, column=1, sticky=tk.W, padx=(10, 0), pady=2)

        row += 1
        self._add_tone_label = ttk.Label(frame, text="Tone (e.g. TONE=C156.7):")
        self._add_tone_label.grid(row=row, column=0, sticky=tk.W, pady=2)
        self._add_tone_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self._add_tone_var, width=20).grid(
            row=row, column=1, sticky=tk.W, padx=(10, 0), pady=2,
        )

        row += 1
        ttk.Label(frame, text="Service Type:").grid(row=row, column=0, sticky=tk.W, pady=2)
        self._add_stype_var = tk.StringVar()
        ttk.Combobox(
            frame, textvariable=self._add_stype_var, state="readonly", width=22,
            values=[s[1] for s in SERVICE_CHOICES],
        ).grid(row=row, column=1, sticky=tk.W, padx=(10, 0), pady=2)

        row += 1
        btn_row = ttk.Frame(frame)
        btn_row.grid(row=row, column=0, columnspan=2, pady=10)
        ttk.Button(btn_row, text="Add to Selected Group", command=self._on_add_entry).pack(
            side=tk.LEFT, padx=3
        )
        ttk.Button(btn_row, text="Create New Group...", command=self._on_create_group).pack(
            side=tk.LEFT, padx=3
        )

        row += 1
        self._add_hint = ttk.Label(
            frame,
            text=(
                "Tips: pick a group to add single entries, or a county/system to create "
                "a new sub-group. Paste a RadioReference URL to auto-fill or bulk-import."
            ),
            foreground="#666666",
            wraplength=360,
            justify=tk.LEFT,
        )
        self._add_hint.grid(row=row, column=0, columnspan=2, sticky=tk.W)

    def _build_status_bar(self):
        status_frame = ttk.Frame(self.root)
        status_frame.pack(fill=tk.X, side=tk.BOTTOM)
        self._status_var = tk.StringVar()
        ttk.Label(
            status_frame, textvariable=self._status_var, relief=tk.SUNKEN,
            anchor=tk.W, padding=(5, 2),
        ).pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._card_state_var = tk.StringVar(value="")
        self._card_state_label = ttk.Label(
            status_frame, textvariable=self._card_state_var, relief=tk.SUNKEN,
            anchor=tk.E, padding=(5, 2), foreground="#666666",
        )
        self._card_state_label.pack(side=tk.LEFT)
        # Pipeline-health pill: click to open the DataPipelineDialog.
        self._pipeline_health_var = tk.StringVar(value="Update pipeline: unknown")
        self._pipeline_health_label = tk.Label(
            status_frame, textvariable=self._pipeline_health_var,
            relief=tk.SUNKEN, anchor=tk.E, padx=6, pady=1,
            foreground="#fff", background="#888", cursor="hand2",
        )
        self._pipeline_health_label.pack(side=tk.LEFT, padx=(0, 2))
        self._pipeline_health_label.bind(
            _LIT_BUTTON_1, lambda _e: self._on_open_data_pipeline()
        )
        ttk.Label(
            status_frame, textvariable=self._sd_space_var, relief=tk.SUNKEN,
            anchor=tk.E, padding=(5, 2), foreground="#333333",
        ).pack(side=tk.LEFT)

    # ---- Event Handlers ---------------------------------------------------

    def _load_app_settings(self) -> Dict[str, Any]:
        if not self._app_settings_path.exists():
            return {}
        try:
            with self._app_settings_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        return {}

    def _save_app_settings(self):
        try:
            with self._app_settings_path.open("w", encoding="utf-8") as f:
                json.dump(self._app_settings, f, indent=2)
        except Exception:
            pass

    def _remember_sd_path(self, folder: str):
        if folder and os.path.isdir(folder):
            self._app_settings["sd_path"] = folder
            self._save_app_settings()
            self._refresh_sd_space()

    # ------------------------------------------------------------------
    # Virtual SD card / workspace lifecycle
    # ------------------------------------------------------------------

    def _active_profile(self) -> Optional[Dict[str, Any]]:
        pid = getattr(self._global_meta, "active_profile_id", None)
        if not pid:
            return None
        return self._global_meta.get_profile(pid)

    def _profile_baseline(
        self, profile: Dict[str, Any]
    ) -> Dict[str, "sdcard.FileState"]:
        return sdcard.file_states_from_json(profile.get("file_state") or {})

    def _update_profile_baseline(
        self, profile: Dict[str, Any], workspace_root: str
    ) -> None:
        states = sdcard.capture_file_state(workspace_root)
        profile["file_state"] = sdcard.file_states_to_json(states)
        profile["last_sync_at"] = datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )

    def _detect_card_identity(self) -> "sdcard.CardIdentity":
        folder = (self._path_var.get() or "").strip()
        return sdcard.probe_card_identity(folder)

    def _on_manage_workspaces(self):
        """Open the workspace picker: list profiles + clone/open/remove."""
        dlg = WorkspaceManagerDialog(self.root, self)
        if dlg.result is None:
            return
        action = dlg.result.get("action")
        if action == "open":
            self._open_profile(dlg.result["profile_id"])
        elif action == "clone":
            self._clone_current_card_as_new_profile(
                name=dlg.result["name"],
                workspace_dir=dlg.result["workspace_dir"],
            )
        elif action == "remove":
            self._global_meta.remove_profile(dlg.result["profile_id"])
            self._global_meta.save()
            self._set_status("Removed workspace profile.")
        elif action == "activate":
            self._activate_profile_on_card(dlg.result["profile_id"])
        elif action == "snapshots":
            self._open_profile_snapshots(dlg.result["profile_id"])

    def _on_swap_profile(self) -> None:
        """Toolbar shortcut: open the Workspaces dialog at the activate tab."""
        self._on_manage_workspaces()

    def _clone_current_card_as_new_profile(
        self,
        *,
        name: str,
        workspace_dir: str,
    ) -> None:
        card_root = (self._path_var.get() or "").strip()
        if not card_root or not os.path.isdir(card_root):
            messagebox.showerror(
                "Clone",
                "Point the SD card folder at a real, connected card before cloning.",
            )
            return
        workspace_dir = os.path.abspath(workspace_dir)
        os.makedirs(workspace_dir, exist_ok=True)
        self._set_status(f"Cloning SD card to {workspace_dir}...")
        self.root.update_idletasks()
        report = sdcard.clone_card_to_workspace(card_root, workspace_dir)
        if report.errors:
            messagebox.showerror(
                "Clone failed",
                "Some files could not be copied:\n\n"
                + "\n".join(f"{rel}: {msg}" for rel, msg in report.errors[:12]),
            )
            return
        ident = sdcard.probe_card_identity(card_root)
        pid = uuid.uuid4().hex
        profile = {
            "profile_id": pid,
            "name": name,
            "workspace_dir": workspace_dir,
            "card_volume_serial": ident.volume_serial,
            "content_fingerprint": ident.content_fingerprint,
            "target_model": ident.target_model,
            "last_synced_card_path": card_root,
        }
        self._update_profile_baseline(profile, workspace_dir)
        self._global_meta.upsert_profile(profile)
        self._global_meta.set_active_profile(pid)
        self._global_meta.save()
        self._set_status(
            f"Cloned {len(report.copied)} file(s) into workspace '{name}'."
        )
        self._open_profile(pid)

    def _open_profile(self, profile_id: str) -> None:
        profile = self._global_meta.get_profile(profile_id)
        if profile is None:
            messagebox.showerror("Workspace", _LIT_PROFILE_NOT_FOUND)
            return
        workspace_dir = profile.get("workspace_dir") or ""
        if not workspace_dir or not os.path.isdir(workspace_dir):
            messagebox.showerror(
                "Workspace",
                "The workspace folder for this profile is missing:\n"
                f"{workspace_dir}",
            )
            return
        self._global_meta.set_active_profile(profile_id)
        self._global_meta.save()
        self._path_var.set(workspace_dir)
        self._remember_sd_path(workspace_dir)
        self._try_load_config(workspace_dir)
        self._set_status(
            f"Opened workspace '{profile.get('name') or profile_id}'. "
            f"Pick a state + Load to browse."
        )
        self._refresh_sd_space()

    # --- Sync -----------------------------------------------------------

    def _on_sync_from_sd(self) -> None:
        profile = self._active_profile()
        if profile is None:
            messagebox.showinfo(
                "Sync",
                "Open a workspace first (Workspace... > Clone or Open).",
            )
            return
        card_root = self._prompt_card_for_sync(profile)
        if not card_root:
            return
        baseline = self._profile_baseline(profile)
        self._set_status("Pulling changes from SD card...")
        self.root.update_idletasks()
        report, diffs = sdcard.sync_pull(
            card_root=card_root,
            workspace_root=profile["workspace_dir"],
            baseline=baseline,
        )
        self._handle_sync_result(
            profile, report, diffs,
            card_root=card_root,
            direction="pull",
        )

    def _on_sync_to_sd(self) -> None:
        profile = self._active_profile()
        if profile is None:
            messagebox.showinfo(
                "Sync",
                "Open a workspace first (Workspace... > Clone or Open).",
            )
            return
        card_root = self._prompt_card_for_sync(profile)
        if not card_root:
            return
        baseline = self._profile_baseline(profile)
        self._set_status("Pushing workspace HPD files to SD card...")
        self.root.update_idletasks()
        report, diffs = sdcard.sync_push(
            card_root=card_root,
            workspace_root=profile["workspace_dir"],
            baseline=baseline,
        )
        self._handle_sync_result(
            profile, report, diffs,
            card_root=card_root,
            direction="push",
        )

    def _prompt_card_for_sync(
        self, profile: Dict[str, Any]
    ) -> Optional[str]:
        """Ask the user to point at an SD card root for syncing.

        Defaults to the last-seen card path; if that's stale we fall back
        to the app's top-level SD path so the user rarely has to type.
        """
        hint = (
            profile.get("last_synced_card_path")
            or (self._path_var.get() or "").strip()
        )
        if hint and os.path.isdir(hint) and hint != profile.get("workspace_dir"):
            # One-click path: if the hint is a card (not the workspace we
            # just opened) and it exists, use it directly.
            return hint
        folder = filedialog.askdirectory(
            title="Select the SD card root for sync",
            initialdir=hint if hint and os.path.isdir(hint) else None,
        )
        return folder or None

    def _handle_sync_result(
        self,
        profile: Dict[str, Any],
        report: "sdcard.SyncReport",
        diffs: List["sdcard.FileDiff"],
        *,
        card_root: str,
        direction: str,
    ) -> None:
        if report.errors:
            messagebox.showerror(
                "Sync errors",
                "\n".join(f"{rel}: {msg}" for rel, msg in report.errors[:12]),
            )
        self._log_sync_external_changes(report, direction)
        self._apply_sync_conflict_decisions(profile, report, diffs, direction, card_root)
        self._update_profile_baseline(profile, profile["workspace_dir"])
        profile["last_synced_card_path"] = card_root
        self._global_meta.upsert_profile(profile)
        self._global_meta.save()
        if direction == "push" and self._meta is not None:
            self._meta.mark_events_committed()
            self._meta.flush()
        self._set_status(sync_result_summary(direction, report))

    def _log_sync_external_changes(
        self, report: "sdcard.SyncReport", direction: str
    ) -> None:
        if self._meta is None:
            return
        for rel in report.external_changes:
            self._meta.record(
                op=OP_EXTERNAL_CHANGE,
                target_id=f"file:{rel}",
                payload={"direction": direction, "relpath": rel},
                target_name=rel,
                summary=f"Card-side change pulled into workspace ({rel})",
                source="sync_pull",
            )
            self._meta.flush()

    def _apply_sync_conflict_decisions(
        self,
        profile: Dict[str, Any],
        report: "sdcard.SyncReport",
        diffs: List["sdcard.FileDiff"],
        direction: str,
        card_root: str,
    ) -> None:
        if not report.conflicts:
            return
        dlg = SyncConflictDialog(
            self.root, report=report, diffs=diffs, direction=direction
        )
        decisions = (dlg.result or {}).get("decisions") or {}
        workspace = profile["workspace_dir"]
        for rel, decision in decisions.items():
            err = apply_sync_conflict_decision(
                rel, decision, card_root=card_root, workspace_dir=workspace
            )
            if err:
                messagebox.showerror("Sync", err)

    # --- Snapshots & profile swap --------------------------------------

    def _profile_snapshots(self, profile: Dict[str, Any]) -> List["sdcard.Snapshot"]:
        raw = profile.get("snapshots") or []
        return [sdcard.Snapshot.from_dict(s) for s in raw if isinstance(s, dict)]

    def _set_profile_snapshots(
        self,
        profile: Dict[str, Any],
        snapshots: List["sdcard.Snapshot"],
    ) -> None:
        profile["snapshots"] = [s.to_dict() for s in snapshots]

    def _profile_retention(self, profile: Dict[str, Any]) -> Dict[str, Any]:
        ret = profile.get("retention") or {}
        return {
            "max_snapshots": int(ret.get("max_snapshots") or sdcard.DEFAULT_MAX_SNAPSHOTS),
            "keep_manual": bool(ret.get("keep_manual", True)),
        }

    def _prune_and_persist_snapshots(
        self,
        profile: Dict[str, Any],
        snapshots: List["sdcard.Snapshot"],
    ) -> List["sdcard.Snapshot"]:
        ret = self._profile_retention(profile)
        kept, removed = sdcard.prune_snapshots(
            snapshots,
            max_snapshots=ret["max_snapshots"],
            keep_manual=ret["keep_manual"],
        )
        for s in removed:
            try:
                sdcard.delete_snapshot_payload(profile["workspace_dir"], s.id)
            except Exception:
                pass
        self._set_profile_snapshots(profile, kept)
        return kept

    def _take_profile_snapshot(
        self,
        profile: Dict[str, Any],
        *,
        reason: str,
        note: str = "",
        card_identity: Optional["sdcard.CardIdentity"] = None,
    ) -> Optional["sdcard.Snapshot"]:
        workspace = profile.get("workspace_dir") or ""
        if not workspace or not os.path.isdir(workspace):
            return None
        try:
            snap = sdcard.snapshot_workspace(
                workspace,
                reason=reason,
                note=note,
                card_identity=card_identity,
            )
        except Exception as exc:
            messagebox.showerror(
                "Snapshot",
                f"Could not create snapshot:\n{exc}",
            )
            return None
        snapshots = self._profile_snapshots(profile)
        snapshots.append(snap)
        snapshots = self._prune_and_persist_snapshots(profile, snapshots)
        self._global_meta.upsert_profile(profile)
        self._global_meta.save()
        return snap

    def _activate_profile_on_card(self, profile_id: str) -> None:
        """One-click swap: push profile ``profile_id`` onto the physical SD card."""
        target = self._global_meta.get_profile(profile_id)
        if not self._validate_swap_target(target):
            return
        card_hint = self._prompt_swap_card_path(target)
        if not card_hint:
            return
        if not self._confirm_profile_swap(target, profile_id, card_hint):
            return
        self._set_status("Preparing profile swap...")
        self.root.update_idletasks()
        card_identity = sdcard.probe_card_identity(card_hint)
        self._snapshot_active_profile_before_swap(profile_id, card_hint, card_identity)
        self._push_swap_profile_to_card(target, profile_id, card_hint)

    def _validate_swap_target(self, target: Optional[Dict[str, Any]]) -> bool:
        if target is None:
            messagebox.showerror(_LIT_SWAP_PROFILE, _LIT_PROFILE_NOT_FOUND)
            return False
        workspace = target.get("workspace_dir") or ""
        if workspace and os.path.isdir(workspace):
            return True
        messagebox.showerror(
            _LIT_SWAP_PROFILE,
            "The workspace folder for this profile is missing:\n"
            f"{workspace}",
        )
        return False

    def _prompt_swap_card_path(self, target: Dict[str, Any]) -> Optional[str]:
        card_hint = (
            target.get("last_synced_card_path")
            or (self._path_var.get() or "").strip()
        )
        workspace = target.get("workspace_dir") or ""
        if card_hint and os.path.isdir(card_hint) and card_hint != workspace:
            return card_hint
        card_hint = filedialog.askdirectory(
            title="Select the SD card root to receive this profile",
            initialdir=card_hint if card_hint and os.path.isdir(card_hint) else None,
        )
        return card_hint or None

    def _confirm_profile_swap(
        self, target: Dict[str, Any], profile_id: str, card_hint: str
    ) -> bool:
        return messagebox.askyesno(
            _LIT_SWAP_PROFILE,
            (
                f"Overwrite the SD card at\n  {card_hint}\n"
                f"with profile '{target.get('name') or profile_id}'?\n\n"
                "A snapshot of the card's current contents will be saved "
                "to the currently-active profile before anything is copied."
            ),
        )

    def _snapshot_active_profile_before_swap(
        self,
        profile_id: str,
        card_hint: str,
        card_identity: "sdcard.CardIdentity",
    ) -> None:
        active = self._active_profile()
        if active is None or active.get("profile_id") == profile_id:
            return
        try:
            sdcard.sync_pull(
                card_root=card_hint,
                workspace_root=active["workspace_dir"],
                baseline=self._profile_baseline(active),
            )
        except Exception:
            pass
        target = self._global_meta.get_profile(profile_id)
        name = (target or {}).get("name") or profile_id
        self._take_profile_snapshot(
            active,
            reason=sdcard.SNAP_REASON_PRE_SWAP,
            note=f"Card state before activating '{name}'",
            card_identity=card_identity,
        )

    def _push_swap_profile_to_card(
        self, target: Dict[str, Any], profile_id: str, card_hint: str
    ) -> None:
        workspace = target.get("workspace_dir") or ""
        self._set_status(
            f"Copying profile '{target.get('name') or profile_id}' onto SD card..."
        )
        self.root.update_idletasks()
        report, diffs = sdcard.sync_push(
            card_root=card_hint,
            workspace_root=workspace,
            baseline=self._profile_baseline(target),
            only_hpd=False,
            overwrite_changed_card=True,
        )
        if report.errors:
            messagebox.showerror(
                _LIT_SWAP_PROFILE,
                "Some files could not be copied:\n\n"
                + "\n".join(f"{rel}: {msg}" for rel, msg in report.errors[:12]),
            )
            return
        self._update_profile_baseline(target, workspace)
        target["last_synced_card_path"] = card_hint
        self._global_meta.upsert_profile(target)
        self._global_meta.set_active_profile(profile_id)
        self._global_meta.save()
        self._path_var.set(workspace)
        self._remember_sd_path(workspace)
        self._try_load_config(workspace)
        self._set_status(
            f"Activated '{target.get('name') or profile_id}' on SD card "
            f"({len(report.copied)} file(s) copied)."
        )
        _ = diffs

    def _open_profile_snapshots(self, profile_id: str) -> None:
        """Open the snapshots dialog for ``profile_id`` and act on the result."""
        profile = self._global_meta.get_profile(profile_id)
        if profile is None:
            messagebox.showerror("Snapshots", _LIT_PROFILE_NOT_FOUND)
            return
        dlg = ProfileSnapshotsDialog(self.root, self, profile_id)
        if dlg.result is None:
            return
        action = dlg.result.get("action")
        if action == "restore":
            self._restore_profile_snapshot(profile_id, dlg.result["snap_id"])
        elif action == "take_manual":
            self._take_profile_snapshot(
                profile,
                reason=sdcard.SNAP_REASON_MANUAL,
                note=dlg.result.get("note") or "",
            )
            self._set_status("Created manual snapshot.")

    def _restore_profile_snapshot(self, profile_id: str, snap_id: str) -> None:
        profile = self._global_meta.get_profile(profile_id)
        if profile is None:
            return
        workspace = profile.get("workspace_dir") or ""
        if not workspace or not os.path.isdir(workspace):
            messagebox.showerror(
                _LIT_RESTORE_SNAPSHOT,
                "Workspace folder for this profile is missing.",
            )
            return
        if not messagebox.askyesno(
            _LIT_RESTORE_SNAPSHOT,
            (
                "Restore this snapshot into the workspace? Any unsaved "
                "changes will be lost, and a 'pre-restore' snapshot will "
                "be created so you can undo this."
            ),
        ):
            return
        try:
            _marker, pre_restore = sdcard.restore_snapshot(workspace, snap_id)
        except Exception as exc:
            messagebox.showerror(
                _LIT_RESTORE_SNAPSHOT, f"Could not restore snapshot:\n{exc}"
            )
            return
        snapshots = self._profile_snapshots(profile)
        if pre_restore is not None:
            snapshots.append(pre_restore)
        snapshots = self._prune_and_persist_snapshots(profile, snapshots)
        self._update_profile_baseline(profile, workspace)
        self._global_meta.upsert_profile(profile)
        self._global_meta.save()
        if self.hpd.filepath:
            try:
                self.hpd.load(self.hpd.filepath)
                self._attach_meta_for_hpd(self.hpd.filepath, is_restore=True)
                self._populate_tree()
            except Exception:
                pass
        self._set_status(f"Restored snapshot {snap_id}.")

    def _on_browse(self):
        initial = self._path_var.get().strip() or self._app_settings.get("sd_path", "")
        folder = filedialog.askdirectory(
            title="Select BCDx36HP folder on SD card",
            initialdir=initial if initial and os.path.isdir(initial) else None,
        )
        if folder:
            self._path_var.set(folder)
            self._remember_sd_path(folder)
            self._try_load_config(folder)

    def _on_load(self):
        folder = self._path_var.get().strip()
        if not folder or not os.path.isdir(folder):
            messagebox.showerror("Error", "Please select a valid BCDx36HP folder.")
            return

        self._remember_sd_path(folder)
        self._try_load_config(folder)

        if not self.config_loaded:
            messagebox.showerror("Error", "Could not find hpdb.cfg in HPDB subfolder.")
            return

        sid = self._get_selected_state_id()
        if sid is None:
            messagebox.showinfo("Info", "Please select a state from the dropdown first.")
            return

        self._load_state_hpd(sid)

    def _try_load_config(self, folder: str):
        if self.config_loaded:
            return
        cfg = find_hpdb_config(folder)
        if cfg is None:
            return
        try:
            self.config.load(cfg)
            self.config_loaded = True
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load config:\n{e}")
            return
        self._populate_state_combo_from_config()

    def _populate_state_combo_from_config(self) -> None:
        state_items = []
        self._state_id_list = []
        for sid in sorted(self.config.state_files.keys()):
            state_items.append(self.config.get_state_name(sid))
            self._state_id_list.append(sid)
        self._state_combo["values"] = state_items
        idx = default_state_combo_index(self._state_id_list)
        if idx is not None:
            self._state_combo.current(idx)
        self._refresh_county_options()

    def _on_state_selected(self, event=None):
        self._refresh_county_options()
        if self._location_filter_enabled.get() and self.hpd.systems:
            self._populate_tree()

    def _get_selected_state_id(self) -> Optional[int]:
        idx = self._state_combo.current()
        if idx < 0 or idx >= len(self._state_id_list):
            return None
        return self._state_id_list[idx]

    def _on_tree_select(self, event=None):
        sel = self.tree.selection()
        if not sel:
            return

        item_id = sel[0]
        obj = self._tree_id_map.get(item_id)

        if isinstance(obj, FreqEntry):
            self._selected_entry = obj
            self._selected_system = None
            self._show_entry_details(obj)
            parent_id = self.tree.parent(item_id)
            parent_obj = self._tree_id_map.get(parent_id)
            if isinstance(parent_obj, GroupNode):
                self._selected_group = parent_obj
        elif isinstance(obj, GroupNode):
            self._selected_group = obj
            self._selected_entry = None
            self._selected_system = None
            self._show_group_details(obj)
        elif isinstance(obj, SystemNode):
            self._selected_group = None
            self._selected_entry = None
            self._selected_system = obj
            self._show_system_details(obj)

    def _on_tree_right_click(self, event):
        item_id = self.tree.identify_row(event.y)
        if not item_id:
            return
        self.tree.selection_set(item_id)
        self._on_tree_select()
        obj = self._tree_id_map.get(item_id)
        menu = tk.Menu(self.root, tearoff=0)
        if not self._populate_tree_context_menu(menu, obj):
            return
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _populate_tree_context_menu(self, menu: tk.Menu, obj: Any) -> bool:
        if isinstance(obj, FreqEntry):
            menu.add_command(label="Edit entry...", command=self._on_edit_selected)
            menu.add_separator()
            menu.add_command(label="Delete entry", command=self._on_delete_selected)
            return True
        if isinstance(obj, GroupNode):
            menu.add_command(label="Edit group...", command=self._on_edit_selected)
            menu.add_separator()
            menu.add_command(label="Bulk: update service type", command=self._on_update_service)
            menu.add_separator()
            self._append_group_rr_menu_items(menu, obj)
            menu.add_separator()
            menu.add_command(label="Delete group", command=self._on_delete_selected)
            return True
        if isinstance(obj, SystemNode):
            menu.add_command(label="Edit system...", command=self._on_edit_selected)
            menu.add_separator()
            menu.add_command(label="Bulk: update service type", command=self._on_update_service)
            menu.add_separator()
            menu.add_command(label="Delete system...", command=self._on_delete_selected)
            return True
        return False

    def _append_group_rr_menu_items(self, menu: tk.Menu, group: GroupNode) -> None:
        link_info = self._group_link_info(group)
        if link_info:
            menu.add_command(
                label=f"RadioReference: {link_info['rr_url']}",
                state="disabled",
            )
            menu.add_command(
                label="Refresh from RadioReference",
                command=self._on_refresh_group_from_rr,
            )
            menu.add_command(
                label="Diff against RadioReference...",
                command=self._on_diff_group_against_rr,
            )
            menu.add_command(
                label="Unlink from RadioReference",
                command=self._on_unlink_group_from_rr,
            )
        else:
            menu.add_command(
                label="Link to RadioReference...",
                command=self._on_link_group_to_rr,
            )

    def _on_edit_selected(self):
        if self._selected_entry is not None:
            dlg = EntryEditDialog(self.root, self._selected_entry)
            if dlg.result is None:
                return
            self._do_edit_entry(
                self._selected_entry,
                name=dlg.result["name"] or None,
                identity_value=dlg.result["identity_value"],
                mode=dlg.result["mode"] or None,
                tone=dlg.result.get("tone"),
            )
            self._refresh_entry_in_tree(self._selected_entry)
            self._show_entry_details(self._selected_entry)
            self._set_status(f"Updated entry: {self._selected_entry.name}")
            return
        if self._selected_group is not None:
            group = self._selected_group
            dlg = GroupEditDialog(self.root, group)
            if dlg.result is None:
                return
            self._do_edit_group(
                group,
                name=dlg.result["name"] or None,
                lat=dlg.result["lat"],
                lon=dlg.result["lon"],
                range_miles=dlg.result["range_miles"],
            )
            updated_name = group.name
            self._populate_tree()
            self._set_status(f"Updated group: {updated_name}")
            return
        if self._selected_system is not None:
            system = self._selected_system
            dlg = SystemEditDialog(self.root, system)
            if dlg.result is None:
                return
            self._do_edit_system(system, name=dlg.result["name"])
            updated_name = system.name
            self._populate_tree()
            self._set_status(f"Updated system: {updated_name}")
            return
        messagebox.showinfo("Edit", "Select an entry, group, or system to edit.")

    def _on_delete_selected(self):
        if self._selected_entry is not None:
            entry = self._selected_entry
            name = entry.name
            if not messagebox.askyesno(
                "Delete Entry",
                f"Delete entry '{name}' ({entry.entry_type})?\n"
                "This change is tracked in Changes... and can be reverted.",
            ):
                return
            self._do_delete_entry(entry)
            self._selected_entry = None
            self._populate_tree()
            self._set_status(f"Deleted entry: {name}")
            return
        if self._selected_group is not None:
            group = self._selected_group
            count = len(group.entries)
            name = group.name
            if not messagebox.askyesno(
                "Delete Group",
                f"Delete group '{name}' and all {count} entries under it?\n"
                "This change is tracked in Changes... and can be reverted.",
            ):
                return
            self._do_delete_group(group)
            self._selected_group = None
            self._populate_tree()
            self._set_status(f"Deleted group: {name}")
            return
        if self._selected_system is not None:
            system = self._selected_system
            name = system.name
            group_count = len(system.groups)
            entry_count = sum(len(g.entries) for g in system.groups)
            if not messagebox.askyesno(
                "Delete System",
                f"Delete system '{name}' and EVERYTHING beneath it?\n\n"
                f"\u2022 {group_count} group(s)\n"
                f"\u2022 {entry_count} entrie(s)\n"
                f"\u2022 all sites, area assignments, and rectangles\n\n"
                "This change is tracked in Changes... and can be reverted.",
            ):
                return
            self._do_delete_system(system)
            self._selected_system = None
            self._refresh_ui_after_mutation(
                status_msg=f"Deleted system: {name}"
            )
            return
        messagebox.showinfo("Delete", "Select an entry, group, or system to delete.")

    # ---- Group ↔ RadioReference linking (Phase C) -------------------------

    def _group_link_info(self, group: GroupNode) -> Optional[Dict[str, Any]]:
        if self._meta is None:
            return None
        key = self._group_key_for(group)
        return self._meta.group_link_for(key)

    @staticmethod
    def _rr_kind_from_url(url: str) -> str:
        u = (url or "").lower()
        if "/db/sid/" in u:
            return "trs"
        if "/db/aid/" in u:
            return "category"
        if "/db/browse/ctid/" in u or "/db/ctid/" in u:
            return "conventional_multi"
        if "/db/fcc/callsign/" in u:
            return "fcc_callsign"
        return "unknown"

    def _on_link_group_to_rr(self):
        group = self._selected_group
        if group is None:
            messagebox.showinfo("Link", "Select a group first.")
            return
        if self._meta is None:
            messagebox.showwarning(
                "Change History",
                "This action needs a loaded SD card with change tracking available.",
            )
            return

        existing = self._group_link_info(group)
        initial = existing.get("rr_url") if existing else ""
        candidates = self._guess_rr_urls_for_group(group)
        url: Optional[str] = None
        if candidates and not initial:
            picker = RadioReferenceAutoGuessDialog(self, group, candidates)
            url = picker.result
            if url is None:
                return  # user cancelled
            if url == "":
                url = self._prompt_rr_url(group, initial or "")
        else:
            url = self._prompt_rr_url(group, initial or "")
        if not url:
            return
        url = url.strip()
        kind = self._rr_kind_from_url(url)
        group_key = self._group_key_for(group)
        self._meta.set_group_link(group_key, rr_url=url, rr_kind=kind)
        self._log_event(
            op=OP_LINK_RR,
            target_id=group_key,
            target_name=group.name,
            payload={"link": {"rr_url": url, "rr_kind": kind}},
            summary=f"Linked '{group.name}' to {url}",
        )
        self._set_status(f"Linked group '{group.name}' to {url}")
        if messagebox.askyesno(
            "Refresh now?",
            "Fetch from RadioReference now and open the reconciler?",
        ):
            self._refresh_group_from_rr(group, url)

    def _prompt_rr_url(self, group: GroupNode, initial: str) -> Optional[str]:
        from tkinter import simpledialog
        return simpledialog.askstring(
            "Link to RadioReference",
            f"RadioReference URL for group '{group.name}':\n"
            "(paste a /db/sid/, /db/aid/, /db/ctid/ or /db/fcc/callsign/ URL)",
            initialvalue=initial,
            parent=self.root,
        )

    def _guess_rr_urls_for_group(self, group: GroupNode) -> List[Dict[str, Any]]:
        """Produce ranked candidate RR URLs for a group."""
        if self._meta is None:
            return []

        seen: Set[str] = set()
        candidates: List[Dict[str, Any]] = []
        callsigns: Set[str] = set()
        licensees: Set[str] = set()
        for entry in group.entries:
            eid = self._entry_id_for(entry)
            ref = self._meta.ref_for(eid) or {}
            for url in ref.get("source_urls") or []:
                append_rr_candidate(
                    candidates, seen, url, "entry-source", 0.95,
                    f"Imported from here ({entry.name})",
                )
            if ref.get("fcc_callsign"):
                callsigns.add(ref["fcc_callsign"].upper())
            if ref.get("licensee"):
                licensees.add(ref["licensee"])

        for url, source, confidence, detail in rr_callsign_urls(callsigns):
            append_rr_candidate(candidates, seen, url, source, confidence, detail)

        gm = self._global_meta
        if gm is not None:
            self._append_fuzzy_licensee_rr_candidates(
                candidates, seen, licensees, gm,
            )
            for url, source, confidence, detail in rr_recent_url_candidates(
                group.name or "", gm.recent_rr_urls, seen, GlobalMetaStore._tokens,
            ):
                append_rr_candidate(candidates, seen, url, source, confidence, detail)

        return sort_rr_candidates(candidates)

    def _append_fuzzy_licensee_rr_candidates(
        self,
        candidates: List[Dict[str, Any]],
        seen: Set[str],
        licensees: Set[str],
        gm: GlobalMetaStore,
    ) -> None:
        append_fuzzy_licensee_rr_candidates(
            candidates, seen, licensees, gm, self._meta, append_rr_candidate,
        )

    def _on_unlink_group_from_rr(self):
        group = self._selected_group
        if group is None or self._meta is None:
            return
        info = self._group_link_info(group)
        if not info:
            return
        if not messagebox.askyesno(
            "Unlink",
            f"Remove RadioReference link for '{group.name}'?",
        ):
            return
        group_key = self._group_key_for(group)
        removed = self._meta.clear_group_link(group_key)
        if removed is not None:
            self._log_event(
                op=OP_UNLINK_RR,
                target_id=group_key,
                target_name=group.name,
                payload={"link": removed},
                summary=f"Unlinked '{group.name}' from RadioReference",
            )
            self._set_status(f"Unlinked group '{group.name}' from RadioReference.")

    def _on_refresh_group_from_rr(self):
        group = self._selected_group
        if group is None:
            return
        info = self._group_link_info(group)
        if not info:
            messagebox.showinfo("Refresh", "This group isn't linked to RadioReference yet.")
            return
        self._refresh_group_from_rr(group, info["rr_url"])

    def _refresh_group_from_rr(self, group: GroupNode, url: str) -> None:
        self._set_status(f"Fetching {url} ...")
        self.root.update_idletasks()
        try:
            parsed = fetch_radioreference_data(url)
        except Exception as exc:
            messagebox.showerror(_LIT_FETCH_ERROR, f"Could not fetch URL:\n{exc}")
            self._set_status("RadioReference fetch failed.")
            return
        if not parsed:
            messagebox.showinfo(
                "No Data",
                "Could not extract usable fields from this page.",
            )
            return
        kind = parsed.get("kind")
        if kind == "category":
            self._handle_rr_category(parsed)
        elif kind == "conventional_multi":
            self._handle_rr_conventional_multi(parsed)
        elif kind == "trs":
            self._handle_rr_trs(parsed)
        elif kind == "fcc_callsign":
            self._handle_rr_category({
                "kind": "category",
                "group_name": parsed.get("licensee") or group.name,
                "frequencies": parsed.get("frequencies") or [],
            })
        else:
            messagebox.showinfo("Refresh", f"Unsupported RR page kind: {kind!r}")
            return
        if self._meta is not None:
            self._meta.set_group_link(
                self._group_key_for(group),
                rr_url=url,
                rr_kind=self._rr_kind_from_url(url),
            )

    def _on_diff_group_against_rr(self):
        group = self._selected_group
        if group is None:
            return
        info = self._group_link_info(group)
        if not info:
            messagebox.showinfo("Diff", "Link the group to RadioReference first.")
            return
        RadioReferenceDiffDialog(self, group, info["rr_url"])

    def _collect_entries_for_action(self) -> Tuple[str, List[FreqEntry]]:
        if self._selected_entry is not None:
            return ("entry", [self._selected_entry])
        if self._selected_group is not None:
            return ("group", list(self._selected_group.entries))
        sys_node = getattr(self, "_selected_system", None)
        if sys_node is not None:
            entries = [e for g in sys_node.groups for e in g.entries]
            return ("system", entries)
        return ("none", [])

    def _on_update_service(self):
        stype_str = self._edit_stype_var.get()
        if not stype_str:
            return
        new_type = int(stype_str.split(" - ")[0])
        scope, entries = self._collect_entries_for_action()
        if scope == "none" or not entries:
            messagebox.showinfo("Info", "Select an entry, group, or system first.")
            return
        if scope != "entry" and not messagebox.askyesno(
            "Bulk Update",
            f"Apply service type {service_label(new_type)} to {len(entries)} entries in this {scope}?",
        ):
            return
        txn = self._new_txn_id()
        source = "bulk" if scope != "entry" else "manual"
        changed = 0
        batch_ctx = self._meta.batch() if self._meta is not None else nullcontext()
        with batch_ctx:
            for entry in entries:
                if self._do_set_service(entry, new_type, source=source, txn_id=txn):
                    changed += 1
                self._refresh_entry_in_tree(entry)
        if self._selected_entry:
            self._show_entry_details(self._selected_entry)
        self._set_status(
            f"Updated service type to {service_label(new_type)} for {changed} entries ({scope})"
        )

    def _on_add_type_changed(self):
        if self._add_type_var.get() == "Conventional":
            self._add_freq_label.config(text=_LIT_FREQ_MHZ_COLON)
            self._add_mode_combo["values"] = MODE_CHOICES_CONV
            self._add_mode_var.set("NFM")
            self._add_tone_label.config(text="Tone (e.g. TONE=C156.7):")
        else:
            self._add_freq_label.config(text="Talkgroup ID:")
            self._add_mode_combo["values"] = MODE_CHOICES_TGID
            self._add_mode_var.set("ALL")
            self._add_tone_label.config(text="(Not used for TGID)")

    def _on_fetch_rr_url(self):
        url = self._add_rr_url_var.get().strip()
        if not url:
            messagebox.showinfo("Info", "Paste a RadioReference URL first.")
            return
        self._set_status(f"Fetching {url} ...")
        self.root.update_idletasks()
        try:
            parsed = fetch_radioreference_data(url)
        except Exception as exc:
            messagebox.showerror(_LIT_FETCH_ERROR, f"Could not fetch URL:\n{exc}")
            self._set_status("RadioReference fetch failed.")
            return
        if not parsed:
            messagebox.showinfo(
                "No Data",
                "Could not extract usable fields from this page. The page format may be unsupported.",
            )
            self._set_status("RadioReference fetch returned no usable data.")
            return
        if parsed.get("kind") == "category":
            self._handle_rr_category(parsed)
            return
        if parsed.get("kind") == "conventional_multi":
            self._handle_rr_conventional_multi(parsed)
            return
        if parsed.get("kind") == "trs":
            self._handle_rr_trs(parsed)
            return
        self._fill_add_form_from_rr_fetch(parsed)

    def _fill_add_form_from_rr_fetch(self, parsed: Dict[str, Any]) -> None:
        frequencies = parsed.get("frequencies") or []
        if not frequencies:
            messagebox.showinfo(_LIT_NO_FREQUENCIES, _LIT_NO_FREQS_ON_PAGE)
            return
        chosen = frequencies[0] if len(frequencies) == 1 else self._prompt_pick_frequency(frequencies)
        if chosen is None:
            return
        name = rr_fetch_display_name(parsed, chosen)
        self._add_name_var.set(name.strip())
        self._add_type_var.set("Conventional")
        self._on_add_type_changed()
        self._add_freq_var.set(f"{chosen['mhz']:.4f}")
        self._add_mode_var.set(chosen.get("mode") or "NFM")
        self._add_tone_var.set(chosen.get("tone") or "")
        stype_guess = parsed.get("suggested_service_type")
        if isinstance(stype_guess, int):
            label = service_choice_for_type(stype_guess, [s[1] for s in SERVICE_CHOICES])
            if label:
                self._add_stype_var.set(label)
        self._set_status(f"Fetched {name.strip() or self._add_rr_url_var.get().strip()}")

    def _location_mismatch_reason(
        self,
        system: Optional[SystemNode] = None,
        group: Optional[GroupNode] = None,
    ) -> Optional[str]:
        """Return a warning when system/group doesn't match the location filter."""
        if not self._location_filter_enabled.get():
            return None
        target_system = system or self._system_for_group(group)
        if target_system is None:
            return None
        county_reason = county_mismatch_reason(
            self._active_county_id, self._county_choices, target_system,
        )
        if county_reason:
            return county_reason
        if self._active_coords and group is not None:
            return geo_distance_mismatch_reason(
                self._active_coords, group, self._coverage_tolerance_miles(),
            )
        return None

    def _system_for_group(self, group: Optional[GroupNode]) -> Optional[SystemNode]:
        if group is None:
            return None
        for sys_node in self.hpd.systems:
            if group in sys_node.groups:
                return sys_node
        return None

    def _confirm_location_mismatch(
        self,
        system: Optional[SystemNode] = None,
        group: Optional[GroupNode] = None,
    ) -> bool:
        reason = self._location_mismatch_reason(system=system, group=group)
        if reason is None:
            return True
        return messagebox.askyesno("Location Mismatch", f"{reason}\n\nContinue anyway?")

    def _resolve_target_system(self) -> Optional[SystemNode]:
        return resolve_target_system(
            self.hpd.systems,
            self._selected_system,
            self._selected_group,
            self._selected_entry,
        )

    def _on_create_group(self):
        system = self._resolve_target_system()
        if system is None:
            messagebox.showinfo(
                "Info",
                "Select a county/system (or a group within it) before creating a new sub-group.",
            )
            return
        if system.system_type != "Conventional":
            messagebox.showwarning(
                "Unsupported",
                "Creating groups is currently supported for conventional (county) systems only.",
            )
            return
        from tkinter import simpledialog

        name = simpledialog.askstring(
            "Create Group",
            f"New group name under {system.name}:",
            parent=self.root,
        )
        if not name:
            return
        if not self._confirm_location_mismatch(system=system):
            return
        try:
            group = self._do_add_cgroup(system, name.strip())
        except Exception as exc:
            messagebox.showerror("Error", f"Could not create group:\n{exc}")
            return
        self._populate_tree()
        self._set_status(f"Created group '{group.name}' under {system.name}.")

    def _handle_rr_category(self, parsed: Dict[str, Any]):
        frequencies = parsed.get("frequencies") or []
        if not frequencies:
            messagebox.showinfo(_LIT_NO_FREQUENCIES, _LIT_NO_FREQS_ON_PAGE)
            return
        system = self._resolve_target_system()
        if system is None or system.system_type != "Conventional":
            messagebox.showinfo(
                "Select System",
                "Select a conventional county system first.",
            )
            return
        if not self._confirm_location_mismatch(system=system):
            return
        wrapped = {
            "title": parsed.get("group_name") or _LIT_RR_GROUP,
            "categories": [
                {
                    "name": parsed.get("group_name") or _LIT_RR_GROUP,
                    "frequencies": frequencies,
                }
            ],
        }
        dialog = ConventionalImportSelectionDialog(self, system, wrapped)
        if not dialog.result:
            return
        source_url = parsed.get("source_url") or self._add_rr_url_var.get().strip()
        source_kind = "rr_category" if "/aid/" in source_url else "rr_ctid"
        self._apply_cfreq_import(
            system, dialog.result, source=source_kind, source_url=source_url,
        )

    def _handle_rr_conventional_multi(self, parsed: Dict[str, Any]):
        categories = parsed.get("categories") or []
        if not categories:
            messagebox.showinfo(_LIT_NO_FREQUENCIES, _LIT_NO_FREQS_ON_PAGE)
            return
        system = self._resolve_target_system()
        if system is None or system.system_type != "Conventional":
            messagebox.showinfo(
                "Select System",
                "Select a conventional county system first.",
            )
            return
        if not self._confirm_location_mismatch(system=system):
            return
        dialog = ConventionalImportSelectionDialog(self, system, parsed)
        if not dialog.result:
            return
        source_url = parsed.get("source_url") or self._add_rr_url_var.get().strip()
        source_kind = "rr_ctid" if "/ctid/" in source_url else "rr_category"
        self._apply_cfreq_import(
            system, dialog.result, source=source_kind, source_url=source_url,
        )

    def _apply_cfreq_import(
        self,
        system: SystemNode,
        selection: List[Tuple[str, List[Dict[str, Any]]]],
        *,
        source: str = "rr_category",
        source_url: str = "",
    ):
        existing_names = {g.name.strip().lower(): g for g in system.groups}
        freq_added = 0
        freq_updated = 0
        freq_skipped = 0
        groups_created: List[str] = []

        default_group_lat, default_group_lon, default_group_range = (
            self._infer_tgroup_geo_defaults(system)
        )

        import_txn = self._new_txn_id()
        added_records: List[Dict[str, Any]] = []
        updated_records: List[Dict[str, Any]] = []

        batch_ctx = self._meta.batch() if self._meta is not None else nullcontext()
        with batch_ctx:
            for cat_name, freqs in selection:
                if not freqs:
                    continue
                key = cat_name.strip().lower()
                group = existing_names.get(key)
                new_freqs = [f for f in freqs if f.get("__action__") == "new"]
                group = self._cfreq_ensure_import_group(
                    system,
                    cat_name,
                    key,
                    group,
                    bool(new_freqs),
                    existing_names,
                    groups_created,
                    default_group_lat,
                    default_group_lon,
                    default_group_range,
                    source,
                    import_txn,
                )
                for freq in freqs:
                    result = self._cfreq_process_freq_row(
                        freq, group, source, import_txn, source_url,
                        added_records, updated_records,
                    )
                    freq_added += result["added"]
                    freq_updated += result["updated"]
                    freq_skipped += result["skipped"]

            if (added_records or updated_records) and self._meta is not None:
                self._log_event(
                    op=OP_IMPORT_APPLY,
                    target_id="",
                    target_name=source_url or "Conventional import",
                    summary=(
                        f"Conventional import: +{freq_added} added, "
                        f"~{freq_updated} updated, {len(groups_created)} new group(s)"
                    ),
                    source=source,
                    txn_id=import_txn,
                    payload={
                        "source_url": source_url,
                        "added": added_records,
                        "updated": updated_records,
                        "groups_created": groups_created,
                        "entry_type": "C-Freq",
                    },
                )

        if source_url and self._global_meta is not None:
            self._global_meta.push_recent_rr_url(source_url)
            self._global_meta.save()

        self._populate_tree()
        self._set_status(
            f"Conventional import: +{freq_added} new, ~{freq_updated} updated, "
            f"skipped {freq_skipped}."
        )
        messagebox.showinfo(
            "Conventional Import",
            f"Created {len(groups_created)} new group(s).\n"
            f"Added {freq_added} new frequencies.\n"
            f"Updated {freq_updated} existing frequencies.\n"
            f"Skipped {freq_skipped}.",
        )

    def _cfreq_ensure_import_group(
        self,
        system: SystemNode,
        cat_name: str,
        key: str,
        group: Optional[GroupNode],
        needs_new_group: bool,
        existing_names: Dict[str, GroupNode],
        groups_created: List[str],
        default_lat: Optional[float],
        default_lon: Optional[float],
        default_range: Optional[float],
        source: str,
        import_txn: Optional[str],
    ) -> Optional[GroupNode]:
        if group is not None or not needs_new_group:
            return group
        try:
            group = self._do_add_cgroup(
                system,
                cat_name.strip(),
                lat=default_lat,
                lon=default_lon,
                range_miles=default_range,
                source=source,
                txn_id=import_txn,
                log=False,
            )
            groups_created.append(self._group_key_for(group))
            existing_names[key] = group
            return group
        except Exception as exc:
            messagebox.showerror(
                "Error", f"Could not create group '{cat_name}':\n{exc}"
            )
            return None

    def _cfreq_process_freq_row(
        self,
        freq: Dict[str, Any],
        group: Optional[GroupNode],
        source: str,
        import_txn: Optional[str],
        source_url: str,
        added_records: List[Dict[str, Any]],
        updated_records: List[Dict[str, Any]],
    ) -> Dict[str, int]:
        result = {"added": 0, "updated": 0, "skipped": 0}
        action = freq.get("__action__")
        freq_hz = parse_rr_import_freq_hz(freq)
        if freq_hz is None:
            result["skipped"] = 1
            return result
        if action == "new":
            result["added"] = self._cfreq_import_new_freq(
                freq, group, freq_hz, source, import_txn, source_url, added_records,
            )
            if result["added"] == 0:
                result["skipped"] = 1
        elif action == "update":
            result["updated"] = self._cfreq_import_update_freq(
                freq, source_url, updated_records,
            )
            if result["updated"] == 0:
                result["skipped"] = 1
        else:
            result["skipped"] = 1
        return result

    def _cfreq_import_new_freq(
        self,
        freq: Dict[str, Any],
        group: Optional[GroupNode],
        freq_hz: int,
        source: str,
        import_txn: Optional[str],
        source_url: str,
        added_records: List[Dict[str, Any]],
    ) -> int:
        if group is None:
            return 0
        try:
            entry = self._do_add_cfreq(
                group=group,
                name=freq.get("name") or freq.get("alpha") or "",
                freq_hz=freq_hz,
                mode=freq.get("mode") or "NFM",
                tone=freq.get("tone") or "",
                service_type=cfreq_import_service_type(freq),
                source=source,
                txn_id=import_txn,
                log=False,
            )
            added_records.append({
                "id": self._entry_id_for(entry),
                "snapshot": self._entry_snapshot(entry),
                "record_fields": list(entry.record.fields),
                "group_key": self._group_key_for(group),
            })
            self._record_callsign_ref(freq, entry, source_url=source_url)
            return 1
        except Exception:
            return 0

    def _cfreq_import_update_freq(
        self,
        freq: Dict[str, Any],
        source_url: str,
        updated_records: List[Dict[str, Any]],
    ) -> int:
        existing = freq.get("__existing__")
        changes = freq.get("__changes__", {})
        if existing is None or not changes:
            return 0
        try:
            before = self._entry_snapshot(existing)
            if "name" in changes:
                new_name = changes["name"][1]
                existing.record.set_field(3, new_name)
                existing.name = new_name
            if "mode" in changes:
                existing.record.set_field(6, changes["mode"][1])
            if "tone" in changes:
                existing.record.set_field(7, changes["tone"][1])
            if "service_type" in changes:
                self.hpd.update_service_type(existing, changes["service_type"][1])
            else:
                self.hpd.has_changes = True
            updated_records.append({
                "id": self._entry_id_for(existing),
                "before": before,
                "after": self._entry_snapshot(existing),
            })
            self._record_callsign_ref(freq, existing, source_url=source_url)
            return 1
        except Exception:
            return 0

    def _handle_rr_trs(self, parsed: Dict[str, Any]):
        categories = parsed.get("categories") or []
        if not categories:
            messagebox.showinfo("No Talkgroups", "No talkgroup categories found on that page.")
            return
        system = self._resolve_target_system()
        if system is None or system.system_type != "Trunk":
            messagebox.showinfo(
                "Select Trunk System",
                "Select a trunked system in the tree first. New T-Groups will be added under it.",
            )
            return
        if not self._confirm_location_mismatch(system=system):
            return
        dialog = TrunkedImportSelectionDialog(self, system, parsed)
        if not dialog.result:
            return
        source_url = parsed.get("source_url") or self._add_rr_url_var.get().strip()
        self._apply_trs_import(
            system, dialog.result, source="rr_sid", source_url=source_url,
        )

    def _infer_tgroup_geo_defaults(
        self, system: SystemNode
    ) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        for site in system.sites:
            if site.lat is not None and site.lon is not None:
                return site.lat, site.lon, site.range_miles
        for group in system.groups:
            if group.lat is not None and group.lon is not None:
                return group.lat, group.lon, group.range_miles
        return None, None, None

    def _existing_tgids_by_group(self, system: SystemNode) -> Dict[str, Set[int]]:
        result: Dict[str, Set[int]] = {}
        for group in system.groups:
            key = group.name.strip().lower()
            tgids: Set[int] = set()
            for entry in group.entries:
                if entry.entry_type != "TGID":
                    continue
                try:
                    tgids.add(int(entry.record.get_field(5, "")))
                except ValueError:
                    continue
            result[key] = tgids
        return result

    def _existing_system_tgids(self, system: SystemNode) -> Set[int]:
        all_tgids: Set[int] = set()
        for group in system.groups:
            for entry in group.entries:
                if entry.entry_type != "TGID":
                    continue
                try:
                    all_tgids.add(int(entry.record.get_field(5, "")))
                except ValueError:
                    continue
        return all_tgids

    def _apply_trs_import(
        self, system: SystemNode, selection: List[Tuple[str, List[Dict[str, Any]]]],
        *,
        source: str = "rr_sid",
        source_url: str = "",
    ):
        existing_names = {g.name.strip().lower(): g for g in system.groups}
        groups_created: List[str] = []
        tgids_added = 0
        tgids_updated = 0
        tgids_skipped = 0

        default_lat, default_lon, default_range = self._infer_tgroup_geo_defaults(system)

        import_txn = self._new_txn_id()
        added_records: List[Dict[str, Any]] = []
        updated_records: List[Dict[str, Any]] = []
        deleted_records: List[Dict[str, Any]] = []

        tgids_deleted = 0
        batch_ctx = self._meta.batch() if self._meta is not None else nullcontext()
        with batch_ctx:
            for cat_name, talkgroups in selection:
                cat_counts = self._trs_process_category(
                    system, cat_name, talkgroups, existing_names, groups_created,
                    default_lat, default_lon, default_range, source, import_txn,
                    added_records, updated_records, deleted_records,
                )
                tgids_added += cat_counts["added"]
                tgids_updated += cat_counts["updated"]
                tgids_deleted += cat_counts["deleted"]
                tgids_skipped += cat_counts["skipped"]

            if (
                added_records
                or updated_records
                or deleted_records
            ) and self._meta is not None:
                self._log_event(
                    op=OP_IMPORT_APPLY,
                    target_id="",
                    target_name=source_url or "Trunked import",
                    summary=(
                        f"Trunked import: +{tgids_added} added, ~{tgids_updated} updated, "
                        f"{len(groups_created)} new group(s), "
                        f"{tgids_deleted} encrypted deleted"
                    ),
                    source=source,
                    txn_id=import_txn,
                    payload={
                        "source_url": source_url,
                        "added": added_records,
                        "updated": updated_records,
                        "deleted": deleted_records,
                        "groups_created": groups_created,
                        "entry_type": "TGID",
                    },
                )
        if source_url and self._global_meta is not None:
            self._global_meta.push_recent_rr_url(source_url)
            self._global_meta.save()

        self._populate_tree()
        self._set_status(
            f"Trunked import: +{tgids_added} new, ~{tgids_updated} updated, "
            f"deleted {tgids_deleted} encrypted, skipped {tgids_skipped}."
        )
        messagebox.showinfo(
            "Trunked Import",
            f"Created {groups_created} new group(s).\n"
            f"Added {tgids_added} new talkgroups.\n"
            f"Updated {tgids_updated} existing talkgroups.\n"
            f"Deleted {tgids_deleted} encrypted entries.\n"
            f"Skipped {tgids_skipped}.",
        )

    def _trs_process_category(
        self,
        system: SystemNode,
        cat_name: str,
        talkgroups: List[Dict[str, Any]],
        existing_names: Dict[str, GroupNode],
        groups_created: List[str],
        default_lat: Optional[float],
        default_lon: Optional[float],
        default_range: Optional[float],
        source: str,
        import_txn: Optional[str],
        added_records: List[Dict[str, Any]],
        updated_records: List[Dict[str, Any]],
        deleted_records: List[Dict[str, Any]],
    ) -> Dict[str, int]:
        counts = {"added": 0, "updated": 0, "deleted": 0, "skipped": 0}
        if not talkgroups:
            return counts
        key = cat_name.strip().lower()
        group = existing_names.get(key)
        needs_new_group = any(item.get("__action__") == "new" for item in talkgroups)
        group = self._trs_ensure_import_group(
            system,
            cat_name,
            key,
            group,
            needs_new_group,
            existing_names,
            groups_created,
            default_lat,
            default_lon,
            default_range,
            source,
            import_txn,
        )
        if group is None and needs_new_group:
            return counts
        self._trs_apply_group_geo_defaults(
            group, default_lat, default_lon, default_range
        )
        for tg in talkgroups:
            result = self._trs_apply_talkgroup_action(
                tg, group, source, import_txn,
                added_records, updated_records, deleted_records,
            )
            for key in counts:
                counts[key] += result[key]
        return counts

    def _trs_ensure_import_group(
        self,
        system: SystemNode,
        cat_name: str,
        key: str,
        group: Optional[GroupNode],
        needs_new_group: bool,
        existing_names: Dict[str, GroupNode],
        groups_created: List[str],
        default_lat: Optional[float],
        default_lon: Optional[float],
        default_range: Optional[float],
        source: str,
        import_txn: Optional[str],
    ) -> Optional[GroupNode]:
        if group is not None or not needs_new_group:
            return group
        try:
            group = self._do_add_tgroup(
                system,
                cat_name.strip(),
                lat=default_lat,
                lon=default_lon,
                range_miles=default_range,
                source=source,
                txn_id=import_txn,
                log=False,
            )
            groups_created.append(self._group_key_for(group))
            existing_names[key] = group
            return group
        except Exception as exc:
            messagebox.showerror(
                "Error", f"Could not create T-Group '{cat_name}':\n{exc}"
            )
            return None

    def _trs_apply_group_geo_defaults(
        self,
        group: Optional[GroupNode],
        default_lat: Optional[float],
        default_lon: Optional[float],
        default_range: Optional[float],
    ) -> None:
        if group is None:
            return
        if group.lat is not None or group.lon is not None:
            return
        if default_lat is None or default_lon is None:
            return
        try:
            self.hpd.edit_group(
                group,
                lat=default_lat,
                lon=default_lon,
                range_miles=default_range,
            )
        except Exception:
            pass

    def _trs_apply_talkgroup_action(
        self,
        tg: Dict[str, Any],
        group: Optional[GroupNode],
        source: str,
        import_txn: Optional[str],
        added_records: List[Dict[str, Any]],
        updated_records: List[Dict[str, Any]],
        deleted_records: List[Dict[str, Any]],
    ) -> Dict[str, int]:
        result = {"added": 0, "updated": 0, "deleted": 0, "skipped": 0}
        action = tg.get("__action__")
        try:
            tgid_val = int(tg["tgid"])
        except Exception:
            return result
        if action == "new":
            result["added"] = self._trs_import_new_tgid(
                tg, group, tgid_val, source, import_txn, added_records
            )
            if result["added"] == 0 and group is None:
                result["skipped"] = 1
        elif action == "update":
            result["updated"] = self._trs_import_update_tgid(
                tg, updated_records,
            )
            if result["updated"] == 0:
                result["skipped"] = 1
        elif action == "delete_encrypted":
            result["deleted"] = self._trs_import_delete_encrypted(
                tg, source, import_txn, deleted_records
            )
            if result["deleted"] == 0:
                result["skipped"] = 1
        else:
            result["skipped"] = 1
        return result

    def _trs_import_new_tgid(
        self,
        tg: Dict[str, Any],
        group: Optional[GroupNode],
        tgid_val: int,
        source: str,
        import_txn: Optional[str],
        added_records: List[Dict[str, Any]],
    ) -> int:
        if group is None:
            return 0
        try:
            stype = tg.get("suggested_service_type")
            if not isinstance(stype, int):
                stype = 1
            entry = self._do_add_tgid(
                group=group,
                name=tg.get("name") or tg.get("alpha") or f"TGID {tgid_val}",
                tgid=tgid_val,
                mode=tg.get("mode") or "ALL",
                service_type=stype,
                source=source,
                txn_id=import_txn,
                log=False,
            )
            added_records.append({
                "id": self._entry_id_for(entry),
                "snapshot": self._entry_snapshot(entry),
                "record_fields": list(entry.record.fields),
                "group_key": self._group_key_for(group),
            })
            return 1
        except Exception:
            return 0

    def _trs_import_update_tgid(
        self,
        tg: Dict[str, Any],
        updated_records: List[Dict[str, Any]],
    ) -> int:
        existing = tg.get("__existing__")
        changes = tg.get("__changes__", {})
        if existing is None or not changes:
            return 0
        try:
            before = self._entry_snapshot(existing)
            if "name" in changes:
                new_name = changes["name"][1]
                existing.record.set_field(3, new_name)
                existing.name = new_name
            if "mode" in changes:
                existing.record.set_field(6, changes["mode"][1])
            if "service_type" in changes:
                self.hpd.update_service_type(existing, changes["service_type"][1])
            else:
                self.hpd.has_changes = True
            updated_records.append({
                "id": self._entry_id_for(existing),
                "before": before,
                "after": self._entry_snapshot(existing),
            })
            return 1
        except Exception:
            return 0

    def _trs_import_delete_encrypted(
        self,
        tg: Dict[str, Any],
        source: str,
        import_txn: Optional[str],
        deleted_records: List[Dict[str, Any]],
    ) -> int:
        existing = tg.get("__existing__")
        if existing is None:
            return 0
        try:
            group_key = self._group_key_for_entry(existing)
            self._do_delete_entry(
                existing, source=source, txn_id=import_txn, log=False,
            )
            deleted_records.append({
                "id": self._entry_id_for(existing),
                "name": existing.name,
                "snapshot": self._entry_snapshot(existing),
                "record_fields": list(existing.record.fields),
                "group_key": group_key,
            })
            return 1
        except Exception:
            return 0

    def _group_key_for_entry(self, entry: FreqEntry) -> Optional[str]:
        for sys_node in self.hpd.systems:
            for group in sys_node.groups:
                if entry in group.entries:
                    return self._group_key_for(group)
        return None

    def _prompt_pick_frequency(self, frequencies: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        top = tk.Toplevel(self.root)
        top.title("Select Frequency")
        top.transient(self.root)
        top.grab_set()
        tk.Label(top, text="Multiple frequencies found. Pick one:").pack(padx=10, pady=(10, 4))
        listbox = tk.Listbox(top, width=60, height=min(12, len(frequencies)))
        for freq in frequencies:
            listbox.insert(
                tk.END,
                f"{freq['mhz']:.4f} MHz  {freq.get('mode', '')}  {freq.get('class', '')}  {freq.get('city', '')}",
            )
        listbox.pack(padx=10, pady=4, fill=tk.BOTH, expand=True)
        listbox.selection_set(0)
        result: List[Optional[Dict[str, Any]]] = [None]

        def on_ok():
            sel = listbox.curselection()
            if sel:
                result[0] = frequencies[sel[0]]
            top.destroy()

        def on_cancel():
            top.destroy()

        btns = ttk.Frame(top)
        btns.pack(pady=(4, 10))
        ttk.Button(btns, text="Use", command=on_ok).pack(side=tk.LEFT, padx=4)
        ttk.Button(btns, text="Cancel", command=on_cancel).pack(side=tk.LEFT, padx=4)
        self.root.wait_window(top)
        return result[0]

    def _on_add_entry(self):
        if not self._selected_group:
            messagebox.showinfo("Info", "Select a group (bold item) in the tree first.")
            return
        if not self._confirm_location_mismatch(group=self._selected_group):
            return

        group = self._selected_group
        validation = validate_add_entry(
            add_type=self._add_type_var.get(),
            group_type=group.group_type,
            name=self._add_name_var.get().strip(),
            stype_str=self._add_stype_var.get(),
            freq_text=self._add_freq_var.get().strip(),
            tgid_text=self._add_freq_var.get().strip(),
            parse_freq_mhz=parse_freq_mhz,
        )
        if not validation.ok:
            messagebox.showwarning(validation.error_title, validation.error_message)
            return

        name = self._add_name_var.get().strip()
        mode = self._add_mode_var.get()
        service_type = validation.service_type
        if self._add_type_var.get() == "Conventional":
            tone = self._add_tone_var.get().strip()
            entry = self._do_add_cfreq(
                group, name, validation.freq_hz, mode, tone, service_type,
            )
            self._add_entry_to_tree(group, entry)
            self._set_status(
                f"Added: {name} — {format_freq(validation.freq_hz)} "
                f"[{service_label(service_type)}]"
            )
        else:
            entry = self._do_add_tgid(
                group, name, validation.tgid, mode, service_type,
            )
            self._add_entry_to_tree(group, entry)
            self._set_status(
                f"Added: {name} — TGID {validation.tgid} "
                f"[{service_label(service_type)}]"
            )

        self._add_name_var.set("")
        self._add_freq_var.set("")
        self._add_tone_var.set("")

    def _on_save(self):
        if not self.hpd.filepath:
            messagebox.showinfo("Info", "No file loaded.")
            return

        if not self.hpd.has_changes:
            messagebox.showinfo("Info", "No changes to save.")
            return

        confirm = messagebox.askyesno(
            "Confirm Save",
            f"Save changes to:\n{self.hpd.filepath}\n\n"
            "Changes are tracked in Changes... and a session snapshot "
            "was captured when this file was first loaded.",
        )
        if not confirm:
            return

        try:
            self.hpd.save()
            committed_count = 0
            if self._meta is not None:
                committed_count = self._meta.mark_events_committed()
                self._meta.flush()
            extra = f" ({committed_count} change(s) committed)" if committed_count else ""
            self._set_status(
                f"Saved {os.path.basename(self.hpd.filepath)}{extra}"
            )
            self._refresh_sd_space()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save:\n{e}")

    def _on_filter_changed(self):
        if self.hpd.systems:
            self._populate_tree()
        self._update_filter_status()

    def _on_zip_lookup(self):
        zip_code = self._zip_var.get().strip()
        normalized = self.zip_lookup.normalize_zip(zip_code)
        if len(normalized) != 5:
            messagebox.showwarning("ZIP Code", "Enter a valid 5-digit ZIP code.")
            return
        folder = self._path_var.get().strip()
        if not self.config_loaded:
            if not folder or not os.path.isdir(folder):
                messagebox.showerror("Error", "Select your BCDx36HP folder first.")
                return
            self._try_load_config(folder)
            if not self.config_loaded:
                messagebox.showerror("Error", "Could not load hpdb.cfg from selected folder.")
                return

        self._load_firmware_zip_table(folder)
        preferred_state_id = self._state_id_from_firmware_zip(normalized)
        coords = self._firmware_zip_table.coords_for_zip(normalized)
        self._active_coords = coords
        match = self.zip_lookup.resolve(normalized, self.config, preferred_state_id=preferred_state_id)
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
            self._set_status(
                f"Could not resolve ZIP {normalized}. Verify internet access or provide zip_county_map.json."
            )
            return

        state_id = match["state_id"]
        county_id = match["county_id"]
        self._set_state_by_id(state_id)
        self._refresh_county_options()
        self._active_county_id = county_id if isinstance(county_id, int) else None
        if self._active_county_id is not None:
            self._set_county_combo_to_id(self._active_county_id)
        else:
            self._county_var.set(_LIT_AUTO_FROM_ZIP)
        self._location_filter_enabled.set(True)
        self._load_state_hpd(state_id, suppress_message=True)
        self._set_status(
            zip_lookup_status_message(
                normalized, match, coords, self._active_county_id,
            )
        )
        if self.hpd.systems:
            self._populate_tree()

    def _refresh_county_options(self):
        sid = self._get_selected_state_id()
        items = [_LIT_AUTO_FROM_ZIP]
        self._county_choices = []
        if sid is not None and self.config_loaded:
            self._county_choices = self.config.get_counties_for_state(sid)
            items.extend(name for _, name in self._county_choices)
        self._county_combo["values"] = items
        if self._county_var.get() not in items:
            self._county_var.set(_LIT_AUTO_FROM_ZIP)

    def _set_county_combo_to_id(self, county_id: int):
        for cid, name in self._county_choices:
            if cid == county_id:
                self._county_var.set(name)
                return
        self._county_var.set(_LIT_AUTO_FROM_ZIP)

    def _on_county_override_changed(self, event=None):
        selected = self._county_var.get()
        if selected == _LIT_AUTO_FROM_ZIP:
            if self._active_zip:
                match = self.zip_lookup.resolve(self._active_zip, self.config)
                self._active_county_id = match["county_id"] if match else None
            else:
                self._active_county_id = None
        else:
            for county_id, name in self._county_choices:
                if name == selected:
                    self._active_county_id = county_id
                    break
        if self._location_filter_enabled.get() and self.hpd.systems:
            self._populate_tree()
        self._update_filter_status()

    def _update_filter_status(self):
        if not self._location_filter_enabled.get():
            return
        parts = ["Location filter enabled"]
        if self._active_zip:
            parts.append(f"ZIP {self._active_zip}")
        if self._active_county_id:
            county_name = next(
                (name for cid, name in self._county_choices if cid == self._active_county_id),
                f"CountyId {self._active_county_id}",
            )
            parts.append(county_name)
        self._set_status(" | ".join(parts))

    def _load_state_hpd(self, sid: int, suppress_message: bool = False) -> bool:
        hpd_path = self.config.state_files.get(sid)
        if not hpd_path or not os.path.exists(hpd_path):
            if not suppress_message:
                messagebox.showerror(
                    "Error", f"No HPD file found for this state (expected s_{sid:06d}.hpd)"
                )
            return False
        if self.hpd.filepath == hpd_path and self.hpd.systems:
            return True
        try:
            self.hpd.load(hpd_path)
        except Exception as e:
            if not suppress_message:
                messagebox.showerror("Error", f"Failed to load HPD file:\n{e}")
            return False
        self._attach_meta_for_hpd(hpd_path)
        self._populate_tree()
        if not suppress_message:
            self._set_status(
                f"Loaded {os.path.basename(hpd_path)} — "
                f"{len(self.hpd.records)} lines, "
                f"{len(self.hpd.systems)} systems"
            )
            self._update_filter_status()
        return True

    def _set_state_by_id(self, state_id: int):
        for i, sid in enumerate(self._state_id_list):
            if sid == state_id:
                self._state_combo.current(i)
                return

    def _load_firmware_zip_table(self, folder: str):
        if self._firmware_zip_loaded:
            return
        self._firmware_zip_loaded = self._firmware_zip_table.load_from_sd(folder)

    def _load_firmware_city_table(self, folder: str):
        if self._firmware_city_loaded:
            return
        self._firmware_city_loaded = self._firmware_city_table.load_from_sd(folder)

    def _ensure_city_index(self, state_id: int):
        if self._city_index_state_id == state_id and self._city_index.by_state_name:
            return
        self._city_index = ScannerCityIndex()
        self._city_index.build(self.hpd, state_id)
        self._city_index_state_id = state_id

    def _state_id_from_firmware_zip(self, zip_code: str) -> Optional[int]:
        abbrev = self._firmware_zip_table.state_abbrev_for_zip(zip_code)
        if not abbrev:
            return None
        for sid, (_, state_abbrev) in self.config.states.items():
            if state_abbrev.upper() == abbrev.upper():
                return sid
        return None

    def _on_city_lookup(self):
        name = self._city_var.get().strip()
        if not name:
            messagebox.showwarning("City", "Enter a city name first.")
            return
        folder = self._path_var.get().strip()
        if not self.config_loaded:
            if not folder or not os.path.isdir(folder):
                messagebox.showerror("Error", "Select your BCDx36HP folder first.")
                return
            self._try_load_config(folder)
            if not self.config_loaded:
                messagebox.showerror("Error", "Could not load hpdb.cfg from selected folder.")
                return
        if folder:
            self._load_firmware_city_table(folder)
        state_id = self._get_selected_state_id()
        if state_id is None:
            messagebox.showinfo("City", "Pick a state from the State dropdown first.")
            return
        self._load_state_hpd(state_id, suppress_message=True)
        self._ensure_city_index(state_id)
        match = resolve_city_offline(
            name,
            self.config,
            self._custom_locations,
            self._firmware_city_table,
            self._city_index,
            state_id=state_id,
        )
        if not match:
            self._set_status(
                f"City '{name}' not in scanner database for this state. Add a custom location via Cities..."
            )
            return
        self._active_zip = None
        self._active_coords = (match["lat"], match["lon"])
        self._active_county_id = None
        self._location_filter_enabled.set(True)
        source = match.get("source", "offline")
        self._set_status(
            f"City '{name}' resolved via {source} @ ({match['lat']:.3f}, {match['lon']:.3f}); showing coverage scan set."
        )
        if self.hpd.systems:
            self._populate_tree()

    def _on_manage_cities(self):
        folder = self._path_var.get().strip()
        if folder:
            self._load_firmware_city_table(folder)
        CityManagerDialog(self)

    @staticmethod
    def _normalize_county_name(name: str) -> str:
        clean = " ".join(name.strip().lower().split())
        clean = clean.replace(" county", "")
        return clean

    def _on_select_updater_path(self):
        """Legacy single-override picker. Persists as an override in the
        Uniden tool registry (preferred tool = whichever this exe
        matches; we assume BT885 by default)."""
        path = filedialog.askopenfilename(
            title="Select Uniden updater executable",
            filetypes=[("Executable", _LIT_EXE_GLOB), (_LIT_ALL_FILES, "*.*")],
        )
        if not path:
            return
        self._updater_path_var.set(path)
        # Also stash in uniden_tools_overrides so the registry picks it up.
        overrides = dict(self._app_settings.get("uniden_tools_overrides") or {})
        lower = os.path.basename(path).lower()
        tool_id = (
            uniden_tools.TOOL_SENTINEL
            if "sentinel" in lower
            else uniden_tools.TOOL_BT885
        )
        overrides[tool_id] = path
        self._app_settings["uniden_tools_overrides"] = overrides
        self._save_app_settings()
        self._set_status(
            f"Updater path set: {os.path.basename(path)} ({tool_id})"
        )

    def _tool_overrides(self) -> Dict[str, str]:
        return dict(self._app_settings.get("uniden_tools_overrides") or {})

    def _detect_updater_path(self) -> Optional[str]:
        """Return the exe path of the preferred Uniden updater.

        Picks BT885 Update Manager when present (native for our scanner),
        falls back to Sentinel otherwise so existing installations keep
        working. Honors app_settings overrides.
        """
        tools = uniden_tools.detect_installed_tools(
            repo_root=self._script_dir,
            overrides=self._tool_overrides(),
        )
        preferred_order = tuple(ACTIVE_PROFILE.preferred_installer_ids())
        for preferred in preferred_order:
            for tool in tools:
                if tool.tool_id == preferred and tool.installed:
                    return tool.exe_path
        return None

    def _on_open_uniden_tools(self):
        """Open the Uniden Tools registry dialog."""
        UnidenToolsDialog(self.root, self)

    # ---- RadioReference API credentials ----------------------------------

    _RR_KEYRING_SERVICE = "scanner-manager:radioreference"

    def _rr_username(self) -> str:
        return str(self._app_settings.get("rr_username") or "").strip()

    def _rr_app_key(self) -> str:
        return str(self._app_settings.get("rr_app_key") or "").strip()

    def _rr_password(self) -> str:
        """Fetch the RR password.

        Prefers Windows Credential Manager via ``keyring``; falls back to
        an in-memory value set during this session (never persisted).
        Returns '' when nothing is available.
        """
        username = self._rr_username()
        if not username:
            return ""
        in_memory = getattr(self, "_rr_password_cache", "") or ""
        try:
            import keyring  # type: ignore
            value = keyring.get_password(self._RR_KEYRING_SERVICE, username)
            if value:
                return value
        except Exception:
            pass
        return in_memory

    def _set_rr_password(self, username: str, password: str) -> None:
        """Store the RR password in keyring; cache in-memory as fallback."""
        self._rr_password_cache = password
        try:
            import keyring  # type: ignore
            if password:
                keyring.set_password(
                    self._RR_KEYRING_SERVICE, username, password
                )
            else:
                try:
                    keyring.delete_password(
                        self._RR_KEYRING_SERVICE, username
                    )
                except Exception:
                    pass
        except Exception:
            # No keyring backend available; in-memory cache is all we have.
            pass

    def _rr_credentials(self) -> "Optional[rr_api.RRCredentials]":
        """Assemble a validated :class:`rr_api.RRCredentials` or return
        ``None`` when anything is missing. Never raises."""
        if rr_api is None:
            return None
        try:
            creds = rr_api.RRCredentials(
                app_key=self._rr_app_key(),
                username=self._rr_username(),
                password=self._rr_password(),
            )
            creds.validate()
            return creds
        except Exception:
            return None

    def _rr_client(self) -> "Optional[rr_api.RadioReferenceClient]":
        """Build a SOAP client when credentials + zeep are available.

        Returns ``None`` when we should fall back to the HTML scraper.
        """
        if rr_api is None:
            return None
        creds = self._rr_credentials()
        if creds is None:
            return None
        try:
            return rr_api.RadioReferenceClient(creds)
        except rr_api.RRUnavailableError:
            return None
        except Exception:
            return None

    def _on_open_rr_settings(self):
        """Open the RadioReference API credentials dialog."""
        RadioReferenceSettingsDialog(self.root, self)

    # ---- Data Pipeline control panel ------------------------------------

    def _pipeline_health_snapshot(self) -> Dict[str, Any]:
        """Compute health state for DataPipelineDialog and the status-bar pill."""
        tools = uniden_tools.detect_installed_tools(
            repo_root=self._script_dir,
            overrides=self._tool_overrides(),
        )
        tools_info = pipeline_tools_info(tools)
        rr_info = self._pipeline_rr_info()
        vsd_info = self._pipeline_vsd_info()
        return {
            "tools": tools_info,
            "rr": rr_info,
            "vsd": vsd_info,
            "health": pipeline_health_color(
                tools_any_installed=tools_info["any_installed"],
                rr_api_missing=rr_api is None,
                profile=vsd_info.get("profile"),
                card_connected=vsd_info["card"]["connected"],
                pending=vsd_info.get("pending_events"),
            ),
        }

    def _pipeline_rr_info(self) -> Dict[str, Any]:
        rr_info: Dict[str, Any] = {
            "zeep_missing": rr_api is None,
            "configured": bool(
                self._rr_app_key() and self._rr_username() and self._rr_password()
            ),
            "username": self._rr_username(),
            "premium": False,
            "expires": "",
        }
        if rr_api is None or not rr_info["configured"]:
            return rr_info
        client = self._rr_client()
        if client is None:
            return rr_info
        try:
            data = client.get_user_data()
            rr_info["premium"] = client.is_premium()
            rr_info["expires"] = data.get("expirationDate") or data.get("expires") or ""
        except Exception:
            pass
        return rr_info

    def _pipeline_vsd_info(self) -> Dict[str, Any]:
        profile = self._active_profile()
        folder = (self._path_var.get() or "").strip()
        card_connected = False
        card_target = ""
        if folder and os.path.isdir(folder):
            ident = sdcard.probe_card_identity(folder)
            card_connected, card_target = card_identity_matches_profile(ident, profile)
        pending = None
        if self._meta is not None:
            try:
                pending = len(self._meta.uncommitted_events())
            except Exception:
                pending = None
        return {
            "profile": profile,
            "pending_events": pending,
            "card": {"connected": card_connected, "target_model": card_target},
        }

    def _on_open_data_pipeline(self):
        DataPipelineDialog(self.root, self)

    def _on_open_rr_pull(self):
        """Open the bulk-pull dialog (API: pull a county or state)."""
        if rr_api is None:
            messagebox.showerror(
                "RR API",
                "The 'zeep' package is not installed; bulk pulls require "
                "the API path. Install via: pip install -r requirements.txt",
            )
            return
        client = self._rr_client()
        if client is None:
            messagebox.showerror(
                "RR API",
                "RadioReference credentials are not configured. "
                "Open 'RR API...' to set them up.",
            )
            return
        RadioReferencePullDialog(self.root, self, client)

    def _fetch_rr_url_preferred(self, url: str) -> Optional[Dict[str, Any]]:
        """Fetch a RadioReference URL, preferring the SOAP API when
        credentials are configured and ``zeep`` is installed. Falls
        through to the HTML scraper on any API failure so the legacy
        flow keeps working for free-tier users.

        Returns the scraper-shape dict the existing import pipeline
        expects (keys vary by kind; see ``fetch_radioreference_data``).
        On API hits, the returned dict additionally includes an
        ``"_api_import"`` key holding the raw :class:`HpdImport` dict,
        so callers that understand the API shape can use it directly.
        """
        client = self._rr_client()
        if client is not None:
            try:
                imp = rr_api.fetch_via_url(client, url)
                envelope = {
                    "kind": f"api_{imp.source}",
                    "title": imp.title,
                    "_api_import": imp.to_dict(),
                }
                return envelope
            except Exception as exc:
                # Fall through to scraper on any API failure so free-tier
                # users (and any RR outage) are never blocked.
                self._set_status(
                    f"RR API failed ({exc.__class__.__name__}); "
                    "falling back to HTML."
                )
        return fetch_radioreference_data(url)

    def _on_run_update_pipeline(self):
        """Toolbar handler: run the full push \u2192 run \u2192 pull \u2192 reconcile
        pipeline using whichever Uniden tool is preferred for this
        scanner family (BT885 first, Sentinel fallback)."""
        self._run_update_pipeline()

    def _on_run_updater_and_reconcile(self):
        if not self.hpd.filepath:
            messagebox.showinfo("Info", _LIT_LOAD_HPD_FIRST)
            return

        updater_path = self._detect_updater_path()
        if not updater_path:
            messagebox.showerror(
                "Updater Not Found",
                "Could not find the Uniden updater executable. Use 'Updater Path...' to set it.",
            )
            return

        snapshot = self.hpd.snapshot_customizations()
        target_hpd_path = self.hpd.filepath
        self._set_status("Launching official updater...")
        self.root.config(cursor="watch")

        def worker():
            try:
                err, self._merge_report = run_updater_reconcile_sequence(
                    updater_path,
                    target_hpd_path,
                    wait_for_updater=lambda path: subprocess.Popen(
                        [path], shell=False
                    ).wait(),
                    reconcile_after_reload=lambda: self._batch_reconcile_after_reload(
                        target_hpd_path,
                        snapshot,
                        source="updater",
                        target_id=f"updater::{int(time.time())}",
                        target_name=os.path.basename(updater_path),
                        payload_extra={"updater_path": updater_path},
                    ),
                )
                if err:
                    title, msg = err
                    self.root.after(
                        0,
                        lambda t=title, m=msg: messagebox.showerror(t, m),
                    )
                    return
                self.root.after(0, self._populate_tree)
                self.root.after(0, self._show_merge_report)
                self.root.after(0, self._refresh_sd_space)
                profile = self._active_profile()
                if profile and hpd_path_inside_workspace(
                    profile.get("workspace_dir") or "", target_hpd_path
                ):
                    self.root.after(0, self._post_updater_pull, profile)
            except Exception as exc:
                err_msg = f"Update/reconcile failed:\n{exc}"
                self.root.after(0, lambda: messagebox.showerror("Update Error", err_msg))
            finally:
                self.root.after(0, lambda: self.root.config(cursor=""))

        threading.Thread(target=worker, daemon=True).start()

    def _show_merge_report(self):
        self._set_status("Update and reconcile complete.")
        messagebox.showinfo(
            "Reconcile Report",
            merge_reconcile_report_message(self._merge_report),
        )

    def _batch_reconcile_after_reload(
        self,
        target_hpd_path: str,
        snapshot: List[EntryCustomization],
        *,
        source: str,
        target_id: str,
        target_name: str,
        payload_extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, int]:
        """Reload HPD, replay events, apply customization snapshot, log once."""
        self.hpd.load(target_hpd_path)
        self._attach_meta_for_hpd(target_hpd_path, is_restore=False)
        batch_ctx = (
            self._meta.batch() if self._meta is not None else nullcontext()
        )
        with batch_ctx:
            replay_report = self._replay_events_after_update()
            merge_report = self.hpd.apply_customizations(snapshot)
            merge_report.update(replay_report)
            if self.hpd.has_changes:
                self.hpd.save()
            payload: Dict[str, Any] = {
                "hpd_path": target_hpd_path,
                "replay": replay_report,
                "safety_net": {
                    k: merge_report.get(k, 0)
                    for k in ("reapplied", "inserted", "unresolved")
                },
            }
            if payload_extra:
                payload.update(payload_extra)
            try:
                self._log_event(
                    op=OP_EXTERNAL_CHANGE,
                    target_id=target_id,
                    target_name=target_name,
                    summary=(
                        f"{source}: "
                        f"replayed={replay_report.get('replayed', 0)}, "
                        f"missed={replay_report.get('missed', 0)}, "
                        f"safety_reapplied={merge_report.get('reapplied', 0)}, "
                        f"inserted={merge_report.get('inserted', 0)}"
                    ),
                    source=source,
                    payload=payload,
                )
            except Exception:
                pass
        audit_path = self._write_reconcile_audit(
            target_hpd_path, snapshot, merge_report
        )
        self._last_reconcile_audit = audit_path
        return merge_report

    # ---- Full pipeline (push -> run -> pull -> reconcile) ---------------

    def _run_update_pipeline(self, *, tool_id: Optional[str] = None) -> None:
        """Full four-stage data pipeline:

        1. If a workspace is active, push workspace HPDs to the card (only
           HPD files; conflicts block the push).
        2. Launch the selected Uniden tool, wait for it to exit.
        3. Sync-pull any ancillary card-side changes back into the
           workspace (logs ``OP_EXTERNAL_CHANGE`` events).
        4. Re-apply MetaStore customizations via ``apply_customizations``
           and surface one merged report.
        """
        if not self.hpd.filepath:
            messagebox.showinfo(
                "Pipeline", _LIT_LOAD_HPD_FIRST
            )
            return

        tools = uniden_tools.detect_installed_tools(
            repo_root=self._script_dir,
            overrides=self._tool_overrides(),
        )
        selected = select_installed_uniden_tool(tools, tool_id)
        if selected is None:
            messagebox.showerror(
                "Pipeline",
                "No Uniden tool is installed. Open 'Uniden Tools...' and "
                "install one first.",
            )
            return

        profile = self._active_profile()
        push_report: Optional["sdcard.SyncReport"] = None
        card_root: Optional[str] = None
        if profile:
            card_root, push_report, abort = pipeline_push_stage(
                profile,
                prompt_card=self._prompt_card_for_sync,
                get_baseline=self._profile_baseline,
                sync_push=sdcard.sync_push,
                ask_continue_on_conflicts=lambda n: messagebox.askyesno(
                    "Pipeline — conflicts on card",
                    (
                        f"{n} file(s) on the card diverged from the last sync. "
                        "Continue launching the Uniden tool anyway? "
                        "(Your changes will not be pushed until resolved.)"
                    ),
                ),
                update_baseline=self._update_profile_baseline,
                save_global=self._global_meta.save,
            )
            if abort:
                return

        snapshot = self.hpd.snapshot_customizations()
        target_hpd_path = self.hpd.filepath
        self._set_status(
            f"Pipeline: launching {selected.display_name}..."
        )
        self.root.config(cursor="watch")

        def worker():
            stage = "launch"
            try:
                exit_code = uniden_tools.run_tool(selected, wait=True)
                abort = pipeline_tool_abort_reason(
                    exit_code, selected.display_name, target_hpd_path
                )
                if abort:
                    self.root.after(
                        0,
                        lambda msg=abort: messagebox.showerror("Pipeline", msg),
                    )
                    return
                stage = "reconcile"
                self._merge_report = self._batch_reconcile_after_reload(
                    target_hpd_path,
                    snapshot,
                    source="pipeline",
                    target_id=f"pipeline::{int(time.time())}",
                    target_name=selected.display_name,
                    payload_extra={
                        "tool_id": selected.tool_id,
                        "tool_version": selected.version or "",
                    },
                )
                self.root.after(0, self._populate_tree)
                self.root.after(0, self._refresh_sd_space)
                stage = "pull"
                pull_summary, pull_report, pull_diffs = pipeline_sync_pull_summary(
                    profile,
                    card_root,
                    get_baseline=self._profile_baseline,
                    sync_pull=sdcard.sync_pull,
                )
                if pull_report is not None:
                    self.root.after(
                        0,
                        lambda: self._handle_sync_result(
                            profile, pull_report, pull_diffs,
                            card_root=card_root,
                            direction="pull",
                        ),
                    )
                self.root.after(
                    0,
                    lambda: self._show_pipeline_report(
                        selected, push_report, self._merge_report, pull_summary
                    ),
                )
            except Exception as exc:
                err_msg = f"Pipeline failed during {stage}:\n{exc}"
                self.root.after(
                    0, lambda: messagebox.showerror("Pipeline", err_msg)
                )
            finally:
                self.root.after(0, lambda: self.root.config(cursor=""))

        threading.Thread(target=worker, daemon=True).start()

    def _show_pipeline_report(
        self,
        tool: "uniden_tools.UnidenTool",
        push_report: Optional["sdcard.SyncReport"],
        merge_report: Optional[Dict[str, int]],
        pull_summary: Dict[str, Any],
    ) -> None:
        self._set_status("Pipeline complete.")
        messagebox.showinfo(
            "Pipeline report",
            "\n".join(pipeline_report_lines(tool, push_report, merge_report, pull_summary)),
        )

    def _post_updater_pull(self, profile: Dict[str, Any]) -> None:
        """After the Uniden updater writes a new HPD on the workspace,
        pull any card-side ancillary changes (firmware, CityTable, etc.)
        back into the workspace so the virtual SD stays a faithful mirror.

        Safe to call even when no physical card is attached; it just
        no-ops in that case.
        """
        card_root = (
            profile.get("last_synced_card_path")
            or (self._path_var.get() or "").strip()
        )
        if not card_root or not os.path.isdir(card_root):
            return
        if os.path.abspath(card_root) == os.path.abspath(
            profile.get("workspace_dir") or ""
        ):
            return  # updater ran against the workspace directly, nothing to pull
        baseline = self._profile_baseline(profile)
        report, diffs = sdcard.sync_pull(
            card_root=card_root,
            workspace_root=profile["workspace_dir"],
            baseline=baseline,
        )
        if report.copied or report.conflicts:
            self._handle_sync_result(
                profile, report, diffs,
                card_root=card_root,
                direction="pull",
            )

    # ---- MetaStore integration --------------------------------------------

    def _attach_meta_for_hpd(self, hpd_path: str, is_restore: bool = False) -> None:
        """Attach (or reload) the MetaStore sidecar for an HPD file.

        Called once per HPD load. Writes a session snapshot on first load
        of this path in this session, then captures baselines for all
        currently-present entries/groups.
        """
        self._meta = MetaStore()
        self._meta.bind(hpd_path)
        self._backfill_committed_from_hpd_mtime(hpd_path)
        if self._session_snapshot_enabled.get():
            key = os.path.normcase(os.path.abspath(hpd_path))
            if is_restore or key not in self._session_snapshot_paths:
                try:
                    write_session_snapshot(hpd_path)
                    self._session_snapshot_paths.add(key)
                except Exception:
                    pass
        self._capture_baselines()
        self._meta.flush()

    def _backfill_committed_from_hpd_mtime(self, hpd_path: str) -> None:
        """Stamp legacy events (no committed_at) as committed at the HPD's
        mtime. Rationale: we are loading an HPD from disk that already
        reflects every event persisted to the sidecar; treating them as
        committed keeps the Changes panel honest for files last touched by
        an older build of the app.
        """
        if self._meta is None or not self._meta.events:
            return
        if not any(e.committed_at is None for e in self._meta.events):
            return
        try:
            mtime = os.path.getmtime(hpd_path)
            stamp = datetime.fromtimestamp(mtime, tz=timezone.utc).replace(tzinfo=None).replace(
                microsecond=0
            ).isoformat() + "Z"
        except Exception:
            stamp = None
        self._meta.mark_events_committed(stamp)

    def _capture_baselines(self) -> None:
        """On first attachment, ensure every system/entry/group has a baseline row."""
        if self._meta is None:
            return
        new_baselines = 0
        for sys_node in self.hpd.systems:
            new_baselines += self._ensure_system_baseline(sys_node)
            for group in sys_node.groups:
                new_baselines += self._ensure_group_baseline(sys_node, group)
                for entry in group.entries:
                    new_baselines += self._ensure_entry_baseline(sys_node, group, entry)
        if new_baselines:
            self._meta.mark_dirty()

    def _ensure_system_baseline(self, sys_node: SystemNode) -> int:
        sid = self._system_key_for(sys_node)
        if self._meta.has_baseline(sid):
            return 0
        self._meta.ensure_baseline(
            sid,
            origin="first_load",
            snapshot=self._system_snapshot(sys_node),
            record_fields=list(sys_node.record.fields),
            group_ref={
                "system_id": sys_node.system_id,
                "system_type": sys_node.system_type,
            },
        )
        return 1

    def _ensure_group_baseline(self, sys_node: SystemNode, group: GroupNode) -> int:
        gid = self._group_key_for(group)
        if self._meta.has_baseline(gid):
            return 0
        self._meta.ensure_baseline(
            gid,
            origin="first_load",
            snapshot=self._group_snapshot(group),
            record_fields=list(group.record.fields),
            group_ref={
                "system_id": sys_node.system_id,
                "system_name": sys_node.name,
                "group_type": group.group_type,
            },
        )
        return 1

    def _ensure_entry_baseline(
        self, _sys_node: SystemNode, _group: GroupNode, entry: FreqEntry
    ) -> int:
        eid = self._entry_id_for(entry)
        if self._meta.has_baseline(eid):
            return 0
        self._meta.ensure_baseline(
            eid,
            origin="first_load",
            snapshot=self._entry_snapshot(entry),
            record_fields=list(entry.record.fields),
            group_ref={
                "system_id": entry.system_id,
                "group_id": entry.group_id,
                "group_name": entry.group_name,
                "system_name": entry.system_name,
                "group_type": entry.group_type,
                "entry_type": entry.entry_type,
            },
        )
        return 1

    # --- id / snapshot helpers ---

    def _entry_id_for(self, entry: FreqEntry) -> str:
        return entry_id_for(
            entry.entry_type,
            entry.system_id or "",
            entry.group_id or "",
            entry.record.get_field(5, ""),
        )

    def _group_key_for(self, group: GroupNode) -> str:
        return group_id_for(group.system_id or "", group.group_id or "")

    def _system_key_for(self, sys_node: SystemNode) -> str:
        return system_id_for(sys_node.system_id or "")

    def _entry_snapshot(self, entry: FreqEntry) -> Dict[str, Any]:
        rec = entry.record
        snap: Dict[str, Any] = {
            "entry_type": entry.entry_type,
            "name": entry.name,
            "service_type": entry.service_type,
            "identity_value": rec.get_field(5, ""),
            "mode": rec.get_field(6, ""),
            "group_id": entry.group_id,
            "group_name": entry.group_name,
            "system_id": entry.system_id,
            "system_name": entry.system_name,
        }
        if entry.entry_type == "C-Freq":
            snap["tone"] = rec.get_field(7, "")
        return snap

    def _group_snapshot(self, group: GroupNode) -> Dict[str, Any]:
        return {
            "group_type": group.group_type,
            "name": group.name,
            "lat": group.lat,
            "lon": group.lon,
            "range_miles": group.range_miles,
            "system_id": group.system_id,
            "system_name": group.system_name,
        }

    def _system_snapshot(self, sys_node: SystemNode) -> Dict[str, Any]:
        return {
            "system_type": sys_node.system_type,
            "system_id": sys_node.system_id,
            "name": sys_node.name,
            "group_count": len(sys_node.groups),
            "entry_count": sum(len(g.entries) for g in sys_node.groups),
        }

    # --- lookup helpers ---

    def _find_entry_by_id(self, entry_id: str) -> Optional[FreqEntry]:
        if not entry_id:
            return None
        for sys_node in self.hpd.systems:
            for group in sys_node.groups:
                for entry in group.entries:
                    if self._entry_id_for(entry) == entry_id:
                        return entry
        return None

    def _find_group_by_key(self, group_key: str) -> Optional[GroupNode]:
        if not group_key:
            return None
        for sys_node in self.hpd.systems:
            for group in sys_node.groups:
                if self._group_key_for(group) == group_key:
                    return group
        return None

    def _find_system_by_key(self, sys_key: str) -> Optional[SystemNode]:
        if not sys_key:
            return None
        for sys_node in self.hpd.systems:
            if self._system_key_for(sys_node) == sys_key:
                return sys_node
        return None

    # --- post-update event replay ---
    #
    # The Uniden updater rewrites HPDs from scratch and wipes every user
    # customization (deletions, service types, renames, adds).
    # After the file reloads, we walk the MetaStore event log and
    # re-execute every non-reverted reversible event against the fresh
    # tree. Raw `self.hpd.*` mutations are used so we don't double-log.

    @staticmethod
    def _replay_norm(text: str) -> str:
        return replay_norm(text)

    def _event_baseline(self, target_id: str) -> Any:
        if self._meta is None:
            return None
        return self._meta.get_baseline(target_id)

    def _find_entry_after_update(
        self, event: "Event"
    ) -> Optional[FreqEntry]:
        return find_entry_after_update(
            self.hpd.systems,
            event,
            find_by_id=self._find_entry_by_id,
            baseline_for=self._event_baseline,
            norm=self._replay_norm,
        )

    def _find_group_after_update(
        self, event: "Event"
    ) -> Optional[GroupNode]:
        return find_group_after_update(
            self.hpd.systems,
            event,
            find_by_key=self._find_group_by_key,
            baseline_for=self._event_baseline,
            norm=self._replay_norm,
        )

    def _find_system_after_update(
        self, event: "Event"
    ) -> Optional[SystemNode]:
        return find_system_after_update(
            self.hpd.systems,
            event,
            find_by_key=self._find_system_by_key,
            baseline_for=self._event_baseline,
            norm=self._replay_norm,
        )

    def _find_group_for_reinsert(
        self, event: "Event"
    ) -> Optional[GroupNode]:
        """Locate the containing group when re-inserting an add_entry or
        re-creating a deleted entry/group child."""
        payload = event.payload or {}
        group_key = payload.get("group_key") or ""
        hit = self._find_group_by_key(group_key)
        if hit is not None:
            return hit
        snap = payload.get("snapshot") or {}
        sys_name = self._replay_norm(snap.get("system_name", ""))
        grp_name = self._replay_norm(snap.get("group_name", ""))
        if not (sys_name and grp_name):
            return None
        for sys_node in self.hpd.systems:
            if self._replay_norm(sys_node.name) != sys_name:
                continue
            for group in sys_node.groups:
                if self._replay_norm(group.name) == grp_name:
                    return group
        return None

    def _replay_events_after_update(self) -> Dict[str, int]:
        """Re-execute every non-reverted reversible event from the
        MetaStore against the freshly reloaded HPD tree.

        Uses raw ``self.hpd.*`` operations so no new events are written;
        we're re-enacting the existing change log, not appending to it.
        """
        report = {
            "replayed": 0,
            "missed": 0,
            "deletions": 0,
            "services": 0,
            "edits": 0,
            "additions": 0,
        }
        if self._meta is None or not self._meta.events:
            return report

        events = sorted(self._meta.events, key=lambda e: e.ts or "")

        for evt in events:
            if evt.reverted:
                continue
            try:
                ok = self._replay_single_event(evt, report)
            except Exception:
                ok = False
            if ok:
                report["replayed"] += 1
            else:
                report["missed"] += 1
        return report

    def _replay_single_event(
        self, evt: "Event", report: Dict[str, int]
    ) -> bool:
        op = evt.op
        payload = evt.payload or {}
        after = payload.get("after") or {}

        if op == "set_avoid":
            return True

        handlers = {
            OP_DELETE_ENTRY: self._replay_delete_entry,
            OP_DELETE_GROUP: self._replay_delete_group,
            OP_DELETE_SYSTEM: self._replay_delete_system,
            OP_SET_SERVICE: self._replay_set_service,
            OP_EDIT_ENTRY: self._replay_edit_entry,
            OP_EDIT_GROUP: self._replay_edit_group,
            OP_EDIT_SYSTEM: self._replay_edit_system,
            OP_ADD_ENTRY: self._replay_add_entry,
        }
        handler = handlers.get(op)
        if handler is None:
            return False
        if op in (OP_DELETE_ENTRY, OP_DELETE_GROUP, OP_DELETE_SYSTEM):
            handler(evt, report, after)
            return True
        return handler(evt, report, after)

    def _replay_delete(
        self,
        evt: "Event",
        report: Dict[str, int],
        find_fn: Callable[["Event"], Any],
        delete_fn: Callable[[Any], None],
    ) -> None:
        target = find_fn(evt)
        if target is not None:
            delete_fn(target)
            report["deletions"] += 1

    def _replay_delete_entry(self, evt: "Event", report: Dict[str, int], _after: Any) -> None:
        self._replay_delete(evt, report, self._find_entry_after_update, self.hpd.delete_entry)

    def _replay_delete_group(self, evt: "Event", report: Dict[str, int], _after: Any) -> None:
        self._replay_delete(evt, report, self._find_group_after_update, self.hpd.delete_group)

    def _replay_delete_system(self, evt: "Event", report: Dict[str, int], _after: Any) -> None:
        self._replay_delete(evt, report, self._find_system_after_update, self.hpd.delete_system)

    def _replay_set_service(self, evt: "Event", report: Dict[str, int], after: Any) -> bool:
        entry = self._find_entry_after_update(evt)
        if entry is None:
            return False
        try:
            svc = int(after.get("service_type"))
        except (TypeError, ValueError):
            return False
        if entry.service_type != svc:
            self.hpd.update_service_type(entry, svc)
        report["services"] += 1
        return True

    def _replay_edit_entry(self, evt: "Event", report: Dict[str, int], after: Any) -> bool:
        entry = self._find_entry_after_update(evt)
        if entry is None:
            return False
        self.hpd.edit_entry(
            entry,
            name=after.get("name"),
            identity_value=(
                str(after.get("identity_value"))
                if after.get("identity_value") is not None else None
            ),
            mode=after.get("mode"),
            tone=after.get("tone"),
        )
        if "service_type" in after:
            try:
                svc = int(after.get("service_type"))
                if entry.service_type != svc:
                    self.hpd.update_service_type(entry, svc)
            except (TypeError, ValueError):
                pass
        report["edits"] += 1
        return True

    def _replay_edit_group(self, evt: "Event", report: Dict[str, int], after: Any) -> bool:
        group = self._find_group_after_update(evt)
        if group is None:
            return False
        self.hpd.edit_group(
            group,
            name=after.get("name"),
            lat=after.get("lat"),
            lon=after.get("lon"),
            range_miles=after.get("range_miles"),
        )
        report["edits"] += 1
        return True

    def _replay_edit_system(self, evt: "Event", report: Dict[str, int], after: Any) -> bool:
        system = self._find_system_after_update(evt)
        if system is None:
            return False
        self.hpd.edit_system(system, name=after.get("name"))
        report["edits"] += 1
        return True

    def _replay_add_entry(self, evt: "Event", report: Dict[str, int], _after: Any) -> bool:
        payload = evt.payload or {}
        snap = payload.get("snapshot") or {}
        et, identity = replay_entry_type_and_identity(snap)
        if not (et and identity):
            return False
        if self._find_entry_after_update(evt) is not None:
            return True
        group = self._find_group_for_reinsert(evt)
        if group is None:
            return False
        if not self._replay_insert_entry(group, et, identity, snap):
            return False
        report["additions"] += 1
        return True

    def _replay_insert_entry(
        self, group: GroupNode, et: str, identity: str, snap: Dict[str, Any]
    ) -> bool:
        try:
            if et == "C-FREQ":
                self.hpd.add_cfreq(
                    group=group,
                    name=snap.get("name") or "",
                    freq_hz=int(identity),
                    mode=snap.get("mode") or "NFM",
                    tone=snap.get("tone") or "",
                    service_type=int(snap.get("service_type") or 0),
                )
            else:
                self.hpd.add_tgid(
                    group=group,
                    name=snap.get("name") or "",
                    tgid=int(identity),
                    mode=snap.get("mode") or "ALL",
                    service_type=int(snap.get("service_type") or 0),
                )
        except Exception:
            return False
        return True

    # --- event log recording ---

    def _log_event(
        self,
        *,
        op: str,
        target_id: str,
        target_name: str = "",
        payload: Optional[Dict[str, Any]] = None,
        summary: str = "",
        source: str = "manual",
        txn_id: Optional[str] = None,
    ) -> Optional[Event]:
        if self._meta is None:
            return None
        event = self._meta.record(
            op=op,
            target_id=target_id,
            target_name=target_name,
            payload=payload or {},
            summary=summary,
            source=source,
            txn_id=txn_id,
        )
        self._meta.flush()
        return event

    def _new_txn_id(self) -> Optional[str]:
        if self._meta is None:
            return None
        return self._meta.new_txn_id()

    # --- mutation wrappers ---

    def _do_edit_entry(
        self,
        entry: FreqEntry,
        *,
        name: Optional[str] = None,
        identity_value: Optional[str] = None,
        mode: Optional[str] = None,
        tone: Optional[str] = None,
        source: str = "manual",
        txn_id: Optional[str] = None,
        log: bool = True,
    ) -> None:
        before = self._entry_snapshot(entry)
        target_id = self._entry_id_for(entry)
        self.hpd.edit_entry(
            entry, name=name, identity_value=identity_value, mode=mode, tone=tone
        )
        after = self._entry_snapshot(entry)
        # Entry id may have changed if identity_value was edited; use the new id.
        new_target_id = self._entry_id_for(entry)
        if not log:
            return
        summary = self._diff_summary(before, after)
        self._log_event(
            op=OP_EDIT_ENTRY,
            target_id=new_target_id,
            target_name=entry.name,
            summary=summary or "Edited entry",
            source=source,
            txn_id=txn_id,
            payload={
                "before": before,
                "after": after,
                "prev_target_id": target_id if target_id != new_target_id else None,
            },
        )

    def _do_edit_group(
        self,
        group: GroupNode,
        *,
        name: Optional[str] = None,
        lat: Optional[float] = None,
        lon: Optional[float] = None,
        range_miles: Optional[float] = None,
        source: str = "manual",
        txn_id: Optional[str] = None,
        log: bool = True,
    ) -> None:
        before = self._group_snapshot(group)
        self.hpd.edit_group(
            group, name=name, lat=lat, lon=lon, range_miles=range_miles
        )
        after = self._group_snapshot(group)
        if not log:
            return
        self._log_event(
            op=OP_EDIT_GROUP,
            target_id=self._group_key_for(group),
            target_name=group.name,
            summary=self._diff_summary(before, after) or "Edited group",
            source=source,
            txn_id=txn_id,
            payload={"before": before, "after": after},
        )

    def _do_set_service(
        self,
        entry: FreqEntry,
        new_type: int,
        *,
        source: str = "manual",
        txn_id: Optional[str] = None,
        log: bool = True,
    ) -> bool:
        if entry.service_type == new_type:
            return False
        before_stype = entry.service_type
        self.hpd.update_service_type(entry, new_type)
        if not log:
            return True
        self._log_event(
            op=OP_SET_SERVICE,
            target_id=self._entry_id_for(entry),
            target_name=entry.name,
            summary=f"Service type {before_stype} -> {new_type}",
            source=source,
            txn_id=txn_id,
            payload={
                "before": {"service_type": before_stype},
                "after": {"service_type": new_type},
            },
        )
        return True

    def _do_add_cfreq(
        self,
        group: GroupNode,
        name: str,
        freq_hz: int,
        mode: str,
        tone: str,
        service_type: int,
        *,
        source: str = "manual",
        txn_id: Optional[str] = None,
        log: bool = True,
    ) -> FreqEntry:
        entry = self.hpd.add_cfreq(group, name, freq_hz, mode, tone, service_type)
        self._log_add_entry(entry, group, source=source, txn_id=txn_id, log=log)
        return entry

    def _do_add_tgid(
        self,
        group: GroupNode,
        name: str,
        tgid: int,
        mode: str,
        service_type: int,
        *,
        source: str = "manual",
        txn_id: Optional[str] = None,
        log: bool = True,
    ) -> FreqEntry:
        entry = self.hpd.add_tgid(group, name, tgid, mode, service_type)
        self._log_add_entry(entry, group, source=source, txn_id=txn_id, log=log)
        return entry

    def _log_add_entry(
        self,
        entry: FreqEntry,
        group: GroupNode,
        *,
        source: str = "manual",
        txn_id: Optional[str] = None,
        log: bool = True,
    ) -> None:
        target_id = self._entry_id_for(entry)
        if self._meta is not None:
            # Baseline ensures revert of a later edit finds the starting
            # shape; we keep this even when `log=False` (composite-import
            # flow) so per-entry reverts still work after a future edit.
            if not self._meta.has_baseline(target_id):
                self._meta.ensure_baseline(
                    target_id,
                    origin="manual_add",
                    snapshot=self._entry_snapshot(entry),
                    record_fields=list(entry.record.fields),
                    group_ref={
                        "system_id": entry.system_id,
                        "group_id": entry.group_id,
                        "group_name": entry.group_name,
                        "system_name": entry.system_name,
                        "group_type": entry.group_type,
                        "entry_type": entry.entry_type,
                    },
                )
        if not log:
            return
        self._log_event(
            op=OP_ADD_ENTRY,
            target_id=target_id,
            target_name=entry.name,
            summary=f"Added {entry.entry_type} {entry.name}",
            source=source,
            txn_id=txn_id,
            payload={
                "snapshot": self._entry_snapshot(entry),
                "record_fields": list(entry.record.fields),
                "group_key": self._group_key_for(group),
            },
        )

    def _do_add_cgroup(
        self,
        system: SystemNode,
        name: str,
        lat: Optional[float] = None,
        lon: Optional[float] = None,
        range_miles: Optional[float] = None,
        *,
        source: str = "manual",
        txn_id: Optional[str] = None,
        log: bool = True,
    ) -> GroupNode:
        group = self.hpd.add_cgroup(system, name, lat=lat, lon=lon, range_miles=range_miles)
        self._log_add_group(group, system, source=source, txn_id=txn_id, log=log)
        return group

    def _do_add_tgroup(
        self,
        system: SystemNode,
        name: str,
        lat: Optional[float] = None,
        lon: Optional[float] = None,
        range_miles: Optional[float] = None,
        *,
        source: str = "manual",
        txn_id: Optional[str] = None,
        log: bool = True,
    ) -> GroupNode:
        group = self.hpd.add_tgroup(system, name, lat=lat, lon=lon, range_miles=range_miles)
        self._log_add_group(group, system, source=source, txn_id=txn_id, log=log)
        return group

    def _log_add_group(
        self,
        group: GroupNode,
        system: SystemNode,
        *,
        source: str = "manual",
        txn_id: Optional[str] = None,
        log: bool = True,
    ) -> None:
        gid = self._group_key_for(group)
        if self._meta is not None and not self._meta.has_baseline(gid):
            self._meta.ensure_baseline(
                gid,
                origin="manual_add",
                snapshot=self._group_snapshot(group),
                record_fields=list(group.record.fields),
                group_ref={
                    "system_id": system.system_id,
                    "system_name": system.name,
                    "group_type": group.group_type,
                },
            )
        if not log:
            return
        self._log_event(
            op=OP_ADD_GROUP,
            target_id=gid,
            target_name=group.name,
            summary=f"Added {group.group_type} {group.name}",
            source=source,
            txn_id=txn_id,
            payload={
                "snapshot": self._group_snapshot(group),
                "record_fields": list(group.record.fields),
                "system_key": self._system_key_for(system),
            },
        )

    def _do_delete_entry(
        self,
        entry: FreqEntry,
        *,
        source: str = "manual",
        txn_id: Optional[str] = None,
        log: bool = True,
    ) -> None:
        eid = self._entry_id_for(entry)
        name = entry.name
        record_fields = list(entry.record.fields)
        snapshot = self._entry_snapshot(entry)
        group_key = None
        for sys_node in self.hpd.systems:
            for group in sys_node.groups:
                if entry in group.entries:
                    group_key = self._group_key_for(group)
                    break
            if group_key:
                break
        self.hpd.delete_entry(entry)
        if not log:
            return
        self._log_event(
            op=OP_DELETE_ENTRY,
            target_id=eid,
            target_name=name,
            summary=f"Deleted entry {name}",
            source=source,
            txn_id=txn_id,
            payload={
                "snapshot": snapshot,
                "record_fields": record_fields,
                "group_key": group_key,
            },
        )

    def _do_edit_system(
        self,
        system: SystemNode,
        *,
        name: Optional[str] = None,
        source: str = "manual",
        txn_id: Optional[str] = None,
        log: bool = True,
    ) -> None:
        before = self._system_snapshot(system)
        self.hpd.edit_system(system, name=name)
        after = self._system_snapshot(system)
        if not log:
            return
        summary = self._diff_summary(before, after) or "Edited system"
        self._log_event(
            op=OP_EDIT_SYSTEM,
            target_id=self._system_key_for(system),
            target_name=system.name,
            summary=summary,
            source=source,
            txn_id=txn_id,
            payload={"before": before, "after": after},
        )

    def _do_delete_system(
        self,
        system: SystemNode,
        *,
        source: str = "manual",
        txn_id: Optional[str] = None,
        log: bool = True,
    ) -> None:
        """Cascading delete of a system with full revert payload."""
        sys_key = self._system_key_for(system)
        name = system.name
        group_count = len(system.groups)
        entry_count = sum(len(g.entries) for g in system.groups)
        snapshot = self._system_snapshot(system)
        raw_payload = self.hpd.delete_system(system)
        if not log:
            return
        self._log_event(
            op=OP_DELETE_SYSTEM,
            target_id=sys_key,
            target_name=name,
            summary=(
                f"Deleted system {name} "
                f"({group_count} group(s), {entry_count} entries)"
            ),
            source=source,
            txn_id=txn_id,
            payload={
                "snapshot": snapshot,
                "group_count": group_count,
                "entry_count": entry_count,
                "system_blob": raw_payload,
            },
        )

    def _do_delete_group(
        self,
        group: GroupNode,
        *,
        source: str = "manual",
        txn_id: Optional[str] = None,
        log: bool = True,
    ) -> None:
        gid = self._group_key_for(group)
        name = group.name
        system_key = None
        for sys_node in self.hpd.systems:
            if group in sys_node.groups:
                system_key = self._system_key_for(sys_node)
                break
        group_record_fields = list(group.record.fields)
        child_payloads = [
            {
                "target_id": self._entry_id_for(e),
                "record_fields": list(e.record.fields),
                "snapshot": self._entry_snapshot(e),
                "entry_type": e.entry_type,
                "name": e.name,
            }
            for e in group.entries
        ]
        snapshot = self._group_snapshot(group)
        self.hpd.delete_group(group)
        if not log:
            return
        self._log_event(
            op=OP_DELETE_GROUP,
            target_id=gid,
            target_name=name,
            summary=f"Deleted group {name} with {len(child_payloads)} entries",
            source=source,
            txn_id=txn_id,
            payload={
                "snapshot": snapshot,
                "record_fields": group_record_fields,
                "system_key": system_key,
                "children": child_payloads,
            },
        )

    def _record_callsign_ref(
        self,
        freq: Dict[str, Any],
        entry: FreqEntry,
        *,
        source_url: str = "",
    ) -> None:
        """Persist FCC callsign/licensee metadata for an imported entry."""
        if self._meta is None:
            return
        callsign = (freq.get("fcc_callsign") or "").strip().upper()
        licensee = (freq.get("licensee") or freq.get("licensee_text") or "").strip()
        if not callsign and not licensee and not source_url:
            return
        eid = self._entry_id_for(entry)
        self._meta.set_ref(
            eid,
            fcc_callsign=callsign or None,
            licensee=licensee or None,
            source_url=source_url or None,
            name=entry.name,
        )
        if callsign:
            self._global_meta.index_callsign(callsign, eid)
        if licensee:
            self._global_meta.index_licensee(licensee, eid)

    @staticmethod
    def _diff_summary(before: Dict[str, Any], after: Dict[str, Any]) -> str:
        parts: List[str] = []
        for key in before:
            if key in after and before[key] != after[key]:
                b = before[key]
                a = after[key]
                parts.append(f"{key}: {b!r} -> {a!r}")
        return "; ".join(parts)

    # ---- Cross-reference lookup (Phase B) ---------------------------------

    def _entry_for_id(self, entry_id: str) -> Tuple[Optional[FreqEntry], str]:
        """Return (entry, group_name) for a stored entry_id, or (None, "")."""
        entry = self._find_entry_by_id(entry_id)
        if entry is None:
            return (None, "")
        for sys_node in self.hpd.systems:
            for group in sys_node.groups:
                if entry in group.entries:
                    return (entry, group.name)
        return (entry, "")

    def crossref_hint_for_rr_row(
        self,
        rr_row: Dict[str, Any],
        *,
        fallback_name: str = "",
        fuzzy_threshold: float = 0.85,
    ) -> Optional[Dict[str, Any]]:
        return lookup_crossref_hint_for_rr_row(
            getattr(self, "_global_meta", None),
            rr_row,
            self._entry_for_id,
            fallback_name=fallback_name,
            fuzzy_threshold=fuzzy_threshold,
        )

    # ---- Revert engine ----------------------------------------------------

    def _apply_entry_snapshot(self, entry: FreqEntry, snap: Dict[str, Any]) -> None:
        rec = entry.record
        if "name" in snap:
            rec.set_field(3, str(snap["name"] or ""))
            entry.name = str(snap["name"] or "")
        if "identity_value" in snap:
            rec.set_field(5, str(snap["identity_value"] or ""))
        if "mode" in snap:
            rec.set_field(6, str(snap["mode"] or ""))
        if entry.entry_type == "C-Freq" and "tone" in snap:
            rec.set_field(7, str(snap.get("tone") or ""))
        if "service_type" in snap:
            try:
                self.hpd.update_service_type(entry, int(snap["service_type"]))
            except (ValueError, TypeError):
                pass
        self.hpd.has_changes = True

    def _apply_group_snapshot(self, group: GroupNode, snap: Dict[str, Any]) -> None:
        changes: Dict[str, Any] = {}
        if "name" in snap:
            changes["name"] = snap["name"]
        if "lat" in snap:
            changes["lat"] = snap["lat"]
        if "lon" in snap:
            changes["lon"] = snap["lon"]
        if "range_miles" in snap:
            changes["range_miles"] = snap["range_miles"]
        self.hpd.edit_group(
            group,
            name=changes.get("name"),
            lat=changes.get("lat"),
            lon=changes.get("lon"),
            range_miles=changes.get("range_miles"),
        )

    def _reinsert_entry_from_payload(self, payload: Dict[str, Any]) -> bool:
        group = self._find_group_by_key(payload.get("group_key") or "")
        if group is None:
            return False
        return add_entry_from_snapshot(self.hpd, group, payload.get("snapshot") or {})

    def _reinsert_group_from_payload(self, payload: Dict[str, Any]) -> Optional[GroupNode]:
        system = self._find_system_by_key(payload.get("system_key") or "")
        if system is None:
            return None
        snap = payload.get("snapshot") or {}
        try:
            if snap.get("group_type") == "C-Group":
                group = self.hpd.add_cgroup(
                    system,
                    name=str(snap.get("name") or ""),
                    lat=snap.get("lat"),
                    lon=snap.get("lon"),
                    range_miles=snap.get("range_miles"),
                )
            else:
                group = self.hpd.add_tgroup(
                    system,
                    name=str(snap.get("name") or ""),
                    lat=snap.get("lat"),
                    lon=snap.get("lon"),
                    range_miles=snap.get("range_miles"),
                )
        except Exception:
            return None
        for child in payload.get("children") or []:
            child_group_key = self._group_key_for(group)
            child_payload = dict(child)
            child_payload["group_key"] = child_group_key
            # Ensure child snapshot has updated group_id since the new group has id=0.
            snap_child = dict(child.get("snapshot") or {})
            snap_child["group_id"] = group.group_id
            child_payload["snapshot"] = snap_child
            self._reinsert_entry_from_payload(child_payload)
        return group

    def revert_event(
        self,
        event: Event,
        *,
        force: bool = False,
        cascade_txn: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """Apply the inverse of `event`.

        Returns (success, message). When `force=False`, bails out if later
        active events touch the same target and the caller hasn't chosen
        a resolution.
        """
        if self._meta is None:
            return False, "No metastore attached."
        if event.reverted:
            return False, "This change has already been reverted."
        if event.op == OP_REVERT or event.op == OP_BULK_REVERT:
            return False, "Cannot revert a revert event. Find the original change instead."
        if not force:
            later = self._meta.later_active_events_on(event.event_id)
            if later:
                summary = ", ".join(f"#{e.event_id}" for e in later[:5])
                return False, f"Later changes touch this target ({summary}). Use cascade or force."

        op = event.op
        payload = event.payload or {}
        try:
            ok, msg = apply_metastore_revert(
                op, event, payload, self._metastore_revert_ops(),
            )
        except Exception as exc:
            ok, msg = False, f"Revert failed: {exc}"

        if ok:
            self._meta.mark_reverted(event.event_id)
            # Record a revert event so the revert itself is revertable.
            revert_txn = cascade_txn or self._new_txn_id()
            self._meta.record(
                op=OP_REVERT,
                target_id=event.target_id,
                target_name=event.target_name,
                summary=f"Reverted #{event.event_id}",
                source="manual",
                txn_id=revert_txn,
                payload={"target_event_id": event.event_id},
            )
            self._meta.flush()
        return ok, msg

    def _metastore_revert_ops(self) -> MetastoreRevertOps:
        def _restore_group_link(target_id: str, link: Dict[str, Any]) -> None:
            assert self._meta is not None
            self._meta.group_links[target_id] = link
            self._meta.mark_dirty()

        return MetastoreRevertOps(
            find_entry_by_id=self._find_entry_by_id,
            find_group_by_key=self._find_group_by_key,
            find_system_by_key=self._find_system_by_key,
            apply_entry_snapshot=self._apply_entry_snapshot,
            apply_group_snapshot=self._apply_group_snapshot,
            edit_system_name=lambda sys_node, name: self.hpd.edit_system(sys_node, name=name),
            delete_entry=self.hpd.delete_entry,
            delete_group=self.hpd.delete_group,
            update_service_type=self.hpd.update_service_type,
            reinsert_system=self.hpd.reinsert_system_from_payload,
            reinsert_entry=self._reinsert_entry_from_payload,
            reinsert_group=self._reinsert_group_from_payload,
            revert_import=self._revert_import_apply,
            clear_group_link=self._meta.clear_group_link,
            restore_group_link=_restore_group_link,
        )

    def _revert_import_apply(
        self, payload: Dict[str, Any]
    ) -> Tuple[bool, str]:
        removed, reverted, restored, group_removed, failed = apply_revert_import_payload(
            payload,
            find_entry=self._find_entry_by_id,
            find_group=self._find_group_by_key,
            delete_entry=self.hpd.delete_entry,
            apply_snapshot=self._apply_entry_snapshot,
            restore_deleted=lambda group, dl: restore_import_deleted_entry(
                self.hpd, group, dl
            ),
            delete_group=self.hpd.delete_group,
        )
        return True, summarize_revert_import(
            removed, reverted, restored, group_removed, failed
        )

    def revert_cascade(self, event: Event) -> Tuple[bool, str]:
        """Revert this event + all later active events touching the same target.

        Reverts in reverse chronological order under one shared revert txn.
        """
        if self._meta is None:
            return False, "No metastore."
        later = self._meta.later_active_events_on(event.event_id)
        chain = list(reversed(later)) + [event]
        txn = self._new_txn_id()
        ok_count = 0
        fails: List[str] = []
        for ev in chain:
            ok, msg = self.revert_event(ev, force=True, cascade_txn=txn)
            if ok:
                ok_count += 1
            else:
                fails.append(f"#{ev.event_id}: {msg}")
        status = f"Reverted {ok_count}/{len(chain)} change(s)."
        if fails:
            status += " Issues: " + "; ".join(fails[:5])
        return ok_count > 0, status

    def revert_to_point(self, pivot_event_id: str) -> Tuple[bool, str]:
        """Revert every active event strictly after pivot_event_id, newest-first."""
        if self._meta is None:
            return False, "No metastore."
        newer = events_newer_than_pivot(
            self._meta.events,
            pivot_event_id,
            {OP_REVERT, OP_BULK_REVERT},
        )
        if not newer:
            return False, "No later changes to revert."
        txn = self._new_txn_id()
        ok_count = 0
        fails: List[str] = []
        for ev in reversed(newer):
            ok, msg = self.revert_event(ev, force=True, cascade_txn=txn)
            if ok:
                ok_count += 1
            else:
                fails.append(f"#{ev.event_id}: {msg}")
        # Record the bulk revert marker
        self._meta.record(
            op=OP_BULK_REVERT,
            target_id="",
            target_name=_LIT_REVERT_TO_POINT,
            summary=f"Reverted {ok_count} events after #{pivot_event_id}",
            source="manual",
            txn_id=txn,
            payload={"pivot_event_id": pivot_event_id, "reverted_count": ok_count},
        )
        self._meta.flush()
        status = f"Reverted {ok_count}/{len(newer)} change(s) after #{pivot_event_id}."
        if fails:
            status += " Issues: " + "; ".join(fails[:5])
        return ok_count > 0, status

    # ---- Tree Population --------------------------------------------------

    def _populate_tree(self):
        self.tree.delete(*self.tree.get_children())
        self._tree_id_map.clear()
        self._selected_entry = None
        self._selected_group = None

        apply_location = self._location_filter_enabled.get() and (
            self._active_county_id is not None or self._active_coords is not None
        )
        ordered_systems = self._ordered_systems_for_tree(apply_location)
        ranking_on = apply_location and self._active_coords is not None
        tolerance = self._coverage_tolerance_miles()

        for idx, (sys_node, distance) in enumerate(ordered_systems):
            self._insert_system_tree_branch(
                sys_node, distance, apply_location, ranking_on, idx, tolerance
            )

    def _ordered_systems_for_tree(
        self, apply_location: bool
    ) -> List[Tuple[SystemNode, Optional[float]]]:
        ordered: List[Tuple[SystemNode, Optional[float]]] = []
        for sys_node in self.hpd.systems:
            if apply_location and not self._system_matches_location(sys_node):
                continue
            distance = None
            if self._active_coords is not None:
                distance = nearest_distance_miles(
                    sys_node, self._active_coords[0], self._active_coords[1]
                )
            ordered.append((sys_node, distance))
        if apply_location and self._active_coords is not None:
            ordered.sort(
                key=lambda item: item[1] if item[1] is not None else float("inf")
            )
        return ordered

    def _visible_groups_for_system(
        self,
        sys_node: SystemNode,
        tolerance: float,
        apply_location: bool,
    ) -> List[Tuple[GroupNode, List[FreqEntry], Dict[str, Any]]]:
        visible: List[Tuple[GroupNode, List[FreqEntry], Dict[str, Any]]] = []
        for group in sys_node.groups:
            entries = [e for e in group.entries if self._entry_passes_button_filter(e)]
            if not entries:
                continue
            info = self._group_coverage_info(group, tolerance)
            if (
                apply_location
                and self._active_coords is not None
                and info["status"] == "out_range"
            ):
                continue
            visible.append((group, entries, info))
        return visible

    def _insert_system_tree_branch(
        self,
        sys_node: SystemNode,
        distance: Optional[float],
        apply_location: bool,
        ranking_on: bool,
        rank: int,
        tolerance: float,
    ) -> None:
        visible_groups = self._visible_groups_for_system(
            sys_node, tolerance, apply_location
        )
        if not visible_groups:
            return
        if ranking_on:
            visible_groups.sort(
                key=lambda item: (
                    item[2]["distance"]
                    if item[2].get("distance") is not None
                    else float("inf")
                )
            )
        sys_text = system_tree_label(
            sys_node,
            apply_location=apply_location,
            ranking_on=ranking_on,
            rank=rank,
            distance=distance,
            scope_label_fn=self._system_scope_label,
        )
        sys_id = self.tree.insert(
            "", tk.END, text=sys_text, tags=("system",), open=False,
        )
        self._tree_id_map[sys_id] = sys_node
        has_coords = self._active_coords is not None
        for group, entries_to_show, info in visible_groups:
            grp_text = group_tree_label(
                group, info, apply_location=apply_location, has_active_coords=has_coords
            )
            tag_name = "group"
            if apply_location and has_coords:
                tag_name = group_coverage_tree_tag(info["status"])
            grp_id = self.tree.insert(
                sys_id, tk.END, text=grp_text, tags=(tag_name,), open=False,
            )
            self._tree_id_map[grp_id] = group
            for entry in entries_to_show:
                self._insert_entry_item(grp_id, entry)

    def _group_coverage_info(self, group: GroupNode, tolerance: float) -> Dict[str, Any]:
        return compute_group_coverage_info(group, self._active_coords, tolerance)

    def _system_matches_location(self, sys_node: SystemNode) -> bool:
        return system_matches_location(
            sys_node,
            active_coords=self._active_coords,
            active_county_id=self._active_county_id,
            selected_state_id=self._get_selected_state_id(),
            tolerance=self._coverage_tolerance_miles(),
        )

    def _system_scope_label(self, sys_node: SystemNode) -> str:
        return location_scope_label(
            sys_node,
            active_coords=self._active_coords,
            active_county_id=self._active_county_id,
            tolerance=self._coverage_tolerance_miles(),
        )

    def _coverage_tolerance_miles(self) -> float:
        try:
            return max(0, int(self._coverage_tolerance_var.get()))
        except Exception:
            return 0

    def _active_button_types(self) -> Set[int]:
        active: Set[int] = set()
        if self._button_police.get():
            active.add(2)
        if self._button_fire.get():
            active.add(3)
        if self._button_ems.get():
            active.add(4)
        if self._button_dot.get():
            active.add(14)
        if self._button_multi.get():
            active.add(1)
        return active

    def _entry_passes_button_filter(self, entry: FreqEntry) -> bool:
        if not entry_passes_button_filter(
            entry.service_type,
            self._active_button_types(),
            bool(self._include_others.get()),
        ):
            return False
        return True

    def _on_export_scan_set(self):
        if not self.hpd.systems:
            messagebox.showinfo("Export", _LIT_LOAD_HPD_FIRST)
            return
        target = filedialog.asksaveasfilename(
            title="Export Effective Scan Set",
            defaultextension=".csv",
            filetypes=[("CSV file", "*.csv"), ("Text file", "*.txt"), (_LIT_ALL_FILES, "*.*")],
        )
        if not target:
            return
        rows = list(self._iter_effective_scan_rows())
        columns = [
            "Scope", "System", "System Type", "Group", "Entry Type",
            "Name", "Identity Value", "Mode", "Tone", "Service Type",
            "Service Name", "Lat", "Lon", "Range (mi)",
            "Distance (mi)",
        ]
        fmt = "csv" if target.lower().endswith(".csv") else "txt"
        try:
            if fmt == "csv":
                import csv
                with open(target, "w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow(columns)
                    for row in rows:
                        writer.writerow(row)
            else:
                with open(target, "w", encoding="utf-8") as f:
                    f.write("\t".join(columns) + "\n")
                    for row in rows:
                        f.write("\t".join(str(v) for v in row) + "\n")
        except Exception as exc:
            messagebox.showerror("Export", f"Could not write file:\n{exc}")
            return
        self._set_status(f"Exported {len(rows)} entries to {os.path.basename(target)}")

    def _iter_effective_scan_rows(self):
        apply_location = self._location_filter_enabled.get() and (
            self._active_county_id is not None or self._active_coords is not None
        )
        for sys_node in self.hpd.systems:
            if apply_location and not self._system_matches_location(sys_node):
                continue
            yield from self._scan_rows_for_system(sys_node, apply_location)

    def _scan_rows_for_system(self, sys_node: SystemNode, apply_location: bool):
        scope = self._system_scope_label(sys_node) if apply_location else ""
        sys_distance = self._system_distance_label(sys_node)
        tolerance = self._coverage_tolerance_miles()
        for group in sys_node.groups:
            info = self._group_coverage_info(group, tolerance)
            if apply_location and self._active_coords is not None and info["status"] == "out_range":
                continue
            lat_s, lon_s, range_s = group_geo_strings(group)
            distance_mi = sys_distance
            if info.get("distance") is not None:
                distance_mi = f"{info['distance']:.2f}"
            for entry in group.entries:
                if not self._entry_passes_button_filter(entry):
                    continue
                yield self._scan_row_for_entry(
                    entry, sys_node, group, scope, lat_s, lon_s, range_s, distance_mi
                )

    def _system_distance_label(self, sys_node: SystemNode) -> str:
        if self._active_coords is None:
            return ""
        d = nearest_distance_miles(sys_node, self._active_coords[0], self._active_coords[1])
        return f"{d:.2f}" if d is not None else ""

    def _scan_row_for_entry(
        self,
        entry: FreqEntry,
        sys_node: SystemNode,
        group: GroupNode,
        scope: str,
        lat_s: str,
        lon_s: str,
        range_s: str,
        distance_mi: str,
    ):
        identity, mode, tone = entry_identity_display(entry, HpdFile._parse_int)
        service_name = SERVICE_TYPES.get(
            entry.service_type, f"Type {entry.service_type}"
        )
        return (
            scope,
            sys_node.name,
            sys_node.system_type,
            group.name,
            entry.entry_type,
            entry.name,
            identity,
            mode,
            tone,
            entry.service_type,
            service_name,
            lat_s,
            lon_s,
            range_s,
            distance_mi,
        )

    def _insert_entry_item(self, parent_id: str, entry: FreqEntry) -> str:
        rec = entry.record
        tag = "scannable" if is_scannable(entry.service_type) else "nonscannable"

        if entry.entry_type == "C-Freq":
            freq_hz = HpdFile._parse_int(rec.get_field(5, "0"))
            freq_display = format_freq(freq_hz)
            mode = rec.get_field(6, "")
        elif entry.entry_type == "TGID":
            tgid_val = rec.get_field(5, "")
            freq_display = f"TGID {tgid_val}"
            mode = tgid_mode_label(rec.get_field(6, ""))
        else:
            freq_display = ""
            mode = ""

        svc = service_label(entry.service_type)

        item_id = self.tree.insert(
            parent_id, tk.END, text=entry.name,
            values=(freq_display, mode, svc),
            tags=(tag,),
        )
        self._tree_id_map[item_id] = entry
        return item_id

    def _add_entry_to_tree(self, group: GroupNode, entry: FreqEntry):
        for tree_id, obj in self._tree_id_map.items():
            if obj is group:
                item_id = self._insert_entry_item(tree_id, entry)
                self.tree.see(item_id)
                self.tree.selection_set(item_id)
                break

    def _refresh_entry_in_tree(self, entry: FreqEntry):
        for tree_id, obj in self._tree_id_map.items():
            if obj is entry:
                rec = entry.record
                tag = "scannable" if is_scannable(entry.service_type) else "nonscannable"

                if entry.entry_type == "C-Freq":
                    freq_hz = HpdFile._parse_int(rec.get_field(5, "0"))
                    freq_display = format_freq(freq_hz)
                    mode = rec.get_field(6, "")
                elif entry.entry_type == "TGID":
                    freq_display = f"TGID {rec.get_field(5, '')}"
                    mode = tgid_mode_label(rec.get_field(6, ""))
                else:
                    freq_display = ""
                    mode = ""

                svc = service_label(entry.service_type)
                self.tree.item(tree_id, values=(freq_display, mode, svc), tags=(tag,))
                break

    # ---- Details Display --------------------------------------------------

    def _show_entry_details(self, entry: FreqEntry):
        rec = entry.record
        self._detail_labels["type"].config(text=entry.entry_type)
        self._detail_labels["name"].config(text=entry.name)

        if entry.entry_type == "C-Freq":
            freq_hz = HpdFile._parse_int(rec.get_field(5, "0"))
            self._detail_labels["freq"].config(text=format_freq(freq_hz))
            self._detail_labels["mode"].config(text=rec.get_field(6, "—"))
            self._detail_labels["tone"].config(text=rec.get_field(7, "—") or "—")
        elif entry.entry_type == "TGID":
            self._detail_labels["freq"].config(text=f"TGID {rec.get_field(5, '')}")
            raw_mode = rec.get_field(6, "")
            self._detail_labels["mode"].config(text=tgid_mode_label(raw_mode) if raw_mode else "—")
            self._detail_labels["tone"].config(text="—")

        self._detail_labels["service"].config(text=service_label(entry.service_type))

        group_name = "—"
        for sys_node in self.hpd.systems:
            for grp in sys_node.groups:
                if entry in grp.entries:
                    group_name = grp.name
                    break
        self._detail_labels["group"].config(text=group_name)

        for i, (code, _label) in enumerate(SERVICE_CHOICES):
            if code == entry.service_type:
                self._edit_stype_combo.current(i)
                break

    def _show_group_details(self, group: GroupNode):
        self._detail_labels["type"].config(text=group.group_type)
        self._detail_labels["name"].config(text=group.name)
        self._detail_labels["freq"].config(text=f"{len(group.entries)} entries")
        self._detail_labels["mode"].config(text="—")
        self._detail_labels["tone"].config(text="—")
        self._detail_labels["service"].config(text="—")
        self._detail_labels["group"].config(text="—")

    def _show_system_details(self, sys_node: SystemNode):
        total = sum(len(g.entries) for g in sys_node.groups)
        self._detail_labels["type"].config(text=sys_node.system_type)
        self._detail_labels["name"].config(text=sys_node.name)
        self._detail_labels["freq"].config(text=f"{len(sys_node.groups)} groups, {total} entries")
        self._detail_labels["mode"].config(text="—")
        self._detail_labels["tone"].config(text="—")
        self._detail_labels["service"].config(text="—")
        self._detail_labels["group"].config(text="—")

    def _clear_details_panel(self) -> None:
        """Blank the detail labels. Used after reverts that may delete the
        currently-selected row."""
        for key in ("type", "name", "freq", "mode", "tone", "service", "group"):
            lbl = self._detail_labels.get(key)
            if lbl is not None:
                lbl.config(text="—")

    def _refresh_ui_after_mutation(self, status_msg: Optional[str] = None) -> None:
        """Rebuild the main tree + detail panel after an operation that may
        have added/removed rows (revert, bulk import, restore). The previous
        selection references may now be stale, so we drop them."""
        self._selected_entry = None
        self._selected_group = None
        self._populate_tree()
        self._clear_details_panel()
        if status_msg is not None:
            self._set_status(status_msg)

    # ---- Helpers ----------------------------------------------------------

    def _set_status(self, msg: str):
        self._status_var.set(msg)

    def _sd_space_root(self) -> Optional[Path]:
        folder = (self._path_var.get() or "").strip()
        if not folder:
            folder = self._app_settings.get("sd_path", "") or ""
        resolved = resolve_existing_folder(folder)
        if resolved is None:
            return None
        return filesystem_space_root(resolved)

    def _refresh_sd_space(self):
        root = self._sd_space_root()
        if root is None:
            self._sd_space_var.set("")
            self._refresh_card_state()
            return
        try:
            usage = shutil.disk_usage(str(root))
        except Exception:
            self._sd_space_var.set("")
            self._refresh_card_state()
            return
        free_gb = usage.free / (1024 ** 3)
        total_gb = usage.total / (1024 ** 3)
        used_pct = (1.0 - usage.free / usage.total) * 100 if usage.total else 0
        self._sd_space_var.set(
            f"SD {root}: {free_gb:.1f} / {total_gb:.1f} GB free ({used_pct:.0f}% used)"
        )
        self._refresh_card_state()

    def _refresh_card_state(self) -> None:
        """Update the card-state label to reflect workspace vs physical
        card status."""
        profile = self._active_profile()
        folder = (self._path_var.get() or "").strip()
        pending = (
            len(self._meta.uncommitted_events()) if self._meta is not None else 0
        )
        ident = (
            sdcard.probe_card_identity(folder)
            if folder and os.path.isdir(folder)
            else sdcard.CardIdentity()
        )
        self._card_state_var.set(
            card_state_display(profile, folder, ident, pending)
        )
        self._refresh_pipeline_health()

    def _refresh_pipeline_health(self) -> None:
        """Recompute the pipeline-health pill from the snapshot helper."""
        try:
            snap = self._pipeline_health_snapshot()
        except Exception:
            return
        health = snap.get("health", "amber")
        label = getattr(self, "_pipeline_health_label", None)
        if label is None:
            return
        color = {"green": "#2a6", "amber": "#b80", "red": "#b33"}.get(
            health, "#666"
        )
        display = {
            "green": "Ready",
            "amber": "Needs attention",
            "red": "Blocked",
        }.get(health, "Unknown")
        self._pipeline_health_var.set(f"Update pipeline: {display}")
        try:
            label.configure(background=color)
        except Exception:
            pass

    def _write_reconcile_audit(
        self,
        hpd_path: str,
        snapshot: List[EntryCustomization],
        report: Dict[str, int],
    ) -> Path:
        audit_dir = Path(hpd_path).parent
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        audit_path = audit_dir / f"{Path(hpd_path).name}.reconcile_{ts}.log"
        lines: List[str] = []
        lines.append(f"Reconcile audit for {hpd_path}")
        lines.append(f"Timestamp: {datetime.now().isoformat(timespec='seconds')}")
        lines.append(f"Report: reapplied={report.get('reapplied', 0)} "
                     f"inserted={report.get('inserted', 0)} "
                     f"unresolved={report.get('unresolved', 0)}")
        lines.append(f"Customizations considered: {len(snapshot)}")
        lines.append("")
        lines.append("Customization details (entry_type, system, group, identity, service, user_added):")
        for c in snapshot:
            lines.append(
                f"- {c.entry_type}\t{c.system_name}\t{c.group_name}\t{c.identity_value}\t"
                f"svc={c.service_type}\tuser_added={c.is_user_added}"
            )
        try:
            audit_path.write_text("\n".join(lines), encoding="utf-8")
        except Exception:
            pass
        return audit_path

    def _on_show_last_audit(self):
        if not self._last_reconcile_audit or not self._last_reconcile_audit.exists():
            messagebox.showinfo("Audit", "No reconcile audit available. Run a reconcile first.")
            return
        try:
            content = self._last_reconcile_audit.read_text(encoding="utf-8")
        except Exception as e:
            messagebox.showerror("Audit", f"Could not read audit log:\n{e}")
            return
        self._show_text_dialog(f"Reconcile Audit - {self._last_reconcile_audit.name}", content)

    def _show_text_dialog(self, title: str, content: str):
        top = tk.Toplevel(self.root)
        top.title(title)
        top.geometry("720x500")
        text = tk.Text(top, wrap="none")
        text.insert("1.0", content)
        text.configure(state="disabled")
        text.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        ttk.Button(top, text="Close", command=top.destroy).pack(pady=(0, 8))

    def _on_show_changes(self):
        """Open the event-sourced Changes panel."""
        if self._meta is None or self.hpd.filepath is None:
            messagebox.showinfo(
                "Changes",
                "Load an HPD file first. Changes are tracked per file.",
            )
            return
        ChangesPanelDialog(self)

    def _on_restore_session_snapshot(self):
        """Restore the single .session.bak safety snapshot for the active HPD.

        When a workspace profile is active, also offers the user the
        option to pick from the per-profile snapshot history instead.
        """
        active = self._active_profile()
        has_profile_snaps = bool(
            active is not None and self._profile_snapshots(active)
        )
        if has_profile_snaps:
            choice = messagebox.askyesnocancel(
                "Restore",
                (
                    "Restore from a per-profile snapshot?\n\n"
                    "Yes = pick a snapshot from this workspace's history.\n"
                    "No = restore just this HPD file from the session snapshot.\n"
                    "Cancel = do nothing."
                ),
            )
            if choice is None:
                return
            if choice:
                self._open_profile_snapshots(active["profile_id"])
                return
        if not self.hpd.filepath:
            messagebox.showinfo(_LIT_RESTORE_SESSION, "No HPD file loaded.")
            return
        snap = session_snapshot_path(self.hpd.filepath)
        if not snap.exists():
            messagebox.showinfo(
                _LIT_RESTORE_SESSION,
                "No session snapshot exists for this file. "
                "A session snapshot is created automatically when a file is loaded.",
            )
            return
        if not messagebox.askyesno(
            "Restore Session Snapshot",
            f"Replace the current file with the session snapshot from:\n"
            f"{snap}\n\n"
            "Unsaved changes in memory will also be lost.\n"
            "A new session snapshot will be created on next load.",
        ):
            return
        try:
            import shutil as _sh
            _sh.copy2(str(snap), self.hpd.filepath)
            self.hpd.load(self.hpd.filepath)
            self._attach_meta_for_hpd(self.hpd.filepath, is_restore=True)
            self._populate_tree()
            self._set_status(
                f"Restored {os.path.basename(self.hpd.filepath)} from session snapshot."
            )
            self._refresh_sd_space()
        except Exception as exc:
            messagebox.showerror(_LIT_RESTORE_SESSION, f"Restore failed:\n{exc}")

    def _on_view_alerts(self):
        AlertsViewerDialog(self)

    def _on_coverage_heatmap(self):
        if not self.hpd.systems:
            messagebox.showinfo(_LIT_COVERAGE_HEATMAP, _LIT_LOAD_HPD_FIRST)
            return
        CoverageHeatmapDialog(self)

    def _on_coverage_map(self):
        if not self.hpd.systems:
            messagebox.showinfo(_LIT_COVERAGE_MAP, _LIT_LOAD_HPD_FIRST)
            return
        CoverageMapDialog(self)

    # -- Help menu handlers --------------------------------------------------

    def _on_help_wiki(self) -> None:
        webbrowser.open(APP_WIKI_URL)

    def _on_help_report_issue(self) -> None:
        title = urllib.parse.quote(f"[{APP_VERSION}] ")
        body = urllib.parse.quote(
            "### What happened?\n\n"
            "### Steps to reproduce\n\n"
            "### Expected behavior\n\n"
            "### Environment\n"
            f"- Scanner Manager: v{APP_VERSION}\n"
            f"- OS: {sys.platform}\n"
            f"- Python: {sys.version.split()[0]}\n"
        )
        webbrowser.open(
            f"{APP_ISSUES_URL}/new?title={title}&body={body}"
        )

    def _on_help_donate(self) -> None:
        DonateDialog(self)

    def _on_help_check_for_updates(self) -> None:
        """Run a fresh check (ignoring the 24h-debounce and skip-version
        tracks) and always show a dialog, even when up-to-date.
        """
        self._run_update_check(manual=True)

    def _run_update_check(self, *, manual: bool) -> None:
        """Kick off a background update check.

        ``manual=True`` bypasses the 24h debounce and shows a dialog even
        if we're up to date (or offline). ``manual=False`` is the silent
        startup path and only surfaces a dialog when a *newer* release is
        available that the user hasn't already skipped.
        """
        if not manual:
            if not self._app_settings.get("updater_check_on_startup", True):
                return
            last = self._app_settings.get("updater_last_check_at") or 0
            try:
                last_ts = float(last)
            except (TypeError, ValueError):
                last_ts = 0.0
            import time as _time
            if _time.time() - last_ts < 24 * 3600:
                return

        def worker() -> None:
            import time as _time
            try:
                info = updater.check_for_update(APP_VERSION)
            except Exception:
                info = None
            self._app_settings["updater_last_check_at"] = _time.time()
            try:
                self._save_app_settings()
            except Exception:
                pass
            self.root.after(0, self._on_update_check_done, info, manual)

        threading.Thread(target=worker, daemon=True).start()

    def _on_update_check_done(
        self,
        info: Optional["updater.UpdateInfo"],
        manual: bool,
    ) -> None:
        if info is None:
            if manual:
                UpdateAvailableDialog(self, info=None, mode="offline")
            return
        skipped = self._app_settings.get("updater_skipped_version") or ""
        if not manual and skipped == info.version:
            return
        if not manual:
            UpdateAvailableDialog(self, info=info, mode="available")
            return
        # Manual path: even if the GitHub tag == current, surface the
        # "you're current" dialog so the user gets feedback.
        try:
            is_newer = updater.Version(info.version) > updater.Version(APP_VERSION)
        except Exception:
            is_newer = False
        mode = "available" if is_newer else "current"
        UpdateAvailableDialog(self, info=info if is_newer else None, mode=mode)

    def _on_help_about(self) -> None:
        AboutDialog(self)

    def _show_first_run_notice(self) -> None:
        """One-shot alpha welcome modal. Persists a flag in app_settings.json
        so it's shown exactly once per install.
        """
        top = tk.Toplevel(self.root)
        top.title(f"Welcome to {APP_NAME} (Alpha)")
        top.transient(self.root)
        top.grab_set()
        top.resizable(False, False)

        frm = ttk.Frame(top, padding=16)
        frm.pack(fill=tk.BOTH, expand=True)
        ttk.Label(
            frm, text=f"{APP_NAME} v{APP_VERSION} - beta release",
            font=("TkDefaultFont", 12, "bold"),
        ).pack(anchor=tk.W, pady=(0, 6))
        ttk.Label(
            frm,
            text=(
                "Thanks for helping test the alpha! A few quick notes before "
                "you start:\n\n"
                "  - This tool writes to your scanner's SD card. Please make "
                "a full file-copy backup of the card before using it.\n"
                "  - Every edit is logged and individually revertable from "
                "the Changes... dialog; a per-session .session.bak snapshot "
                "is also written so you can roll back the HPD file.\n"
                "  - The 'Workspaces / Virtual SD card' feature lets you "
                "experiment without touching the physical card at all until "
                "you're happy.\n"
                "  - Please report bugs, regressions, and suggestions on "
                "GitHub. Include the scanner model and a description of "
                "what you were doing when things broke."
            ),
            wraplength=520, justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(0, 10))

        btns = ttk.Frame(frm)
        btns.pack(fill=tk.X, pady=(6, 0))
        ttk.Button(
            btns, text="Open Wiki",
            command=lambda: webbrowser.open(APP_WIKI_URL),
        ).pack(side=tk.LEFT)
        ttk.Button(
            btns, text="Report an Issue",
            command=self._on_help_report_issue,
        ).pack(side=tk.LEFT, padx=4)

        def _dismiss() -> None:
            self._app_settings["first_run_seen"] = True
            try:
                self._save_app_settings()
            except Exception:
                pass
            top.destroy()

        ttk.Button(btns, text="Got it", command=_dismiss).pack(
            side=tk.RIGHT
        )
        top.protocol("WM_DELETE_WINDOW", _dismiss)

    def _on_bulk_remap(self):
        if not self.hpd.systems:
            messagebox.showinfo(_LIT_BULK_REMAP, _LIT_LOAD_HPD_FIRST)
            return
        BulkRemapDialog(self)

    def _on_mode_band_audit(self):
        if not self.hpd.systems:
            messagebox.showinfo("Audit", _LIT_LOAD_HPD_FIRST)
            return
        ModeBandAuditorDialog(self)


class RadioReferenceAutoGuessDialog:
    """Present ranked RadioReference URL candidates for a group.

    ``result`` is one of:
      * ``None`` - user cancelled
      * ``""`` - user chose to enter a URL manually
      * a non-empty URL string - user picked a candidate
    """

    def __init__(
        self,
        app: "ScannerManagerApp",
        group: GroupNode,
        candidates: List[Dict[str, Any]],
    ):
        self.app = app
        self.group = group
        self.candidates = candidates
        self.result: Optional[str] = None

        self.top = tk.Toplevel(app.root)
        self.top.title(f"Suggest RadioReference Link - {group.name}")
        self.top.transient(app.root)
        self.top.geometry("860x420")
        self.top.grab_set()

        header = ttk.Frame(self.top, padding=8)
        header.pack(fill=tk.X)
        ttk.Label(
            header,
            text=(
                f"Candidate RadioReference URLs for group '{group.name}'. "
                "Higher confidence = derived from a past import or callsign."
            ),
            wraplength=820, justify=tk.LEFT,
        ).pack(anchor=tk.W)

        tree_frame = ttk.Frame(self.top, padding=8)
        tree_frame.pack(fill=tk.BOTH, expand=True)
        columns = ("confidence", "source", "url", "detail")
        self.tree = ttk.Treeview(
            tree_frame, columns=columns, show="headings", selectmode="browse"
        )
        for col, label, width, anchor in (
            ("confidence", "Confidence", 90, tk.CENTER),
            ("source", "Source", 120, tk.W),
            ("url", "URL", 380, tk.W),
            ("detail", "Detail", 240, tk.W),
        ):
            self.tree.heading(col, text=label)
            self.tree.column(col, width=width, anchor=anchor)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        sb.pack(side=tk.LEFT, fill=tk.Y)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.bind("<Double-1>", lambda _e: self._on_accept())

        for c in self.candidates:
            self.tree.insert(
                "", tk.END,
                values=(
                    f"{int(round(c['confidence'] * 100))}%",
                    c["source"],
                    c["url"],
                    c.get("detail", ""),
                ),
            )
        if self.candidates:
            first = self.tree.get_children("")[0]
            self.tree.selection_set(first)

        footer = ttk.Frame(self.top, padding=8)
        footer.pack(fill=tk.X)
        ttk.Button(footer, text="Use Selected", command=self._on_accept).pack(side=tk.LEFT)
        ttk.Button(
            footer, text="Enter URL Manually...", command=self._on_manual,
        ).pack(side=tk.LEFT, padx=4)
        ttk.Button(footer, text="Cancel", command=self._on_cancel).pack(side=tk.RIGHT)

        app.root.wait_window(self.top)

    def _on_accept(self) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        url = self.tree.set(sel[0], "url")
        self.result = url
        self.top.destroy()

    def _on_manual(self) -> None:
        self.result = ""
        self.top.destroy()

    def _on_cancel(self) -> None:
        self.result = None
        self.top.destroy()


class RadioReferenceDiffDialog:
    """Read-only diff between a local group and its linked RadioReference page."""

    STATUS_ADDED = "ADDED"
    STATUS_REMOVED = "REMOVED"
    STATUS_CHANGED = "CHANGED"
    STATUS_SAME = "SAME"

    def __init__(self, app: "ScannerManagerApp", group: GroupNode, url: str):
        self.app = app
        self.group = group
        self.url = url
        self.system = next(
            (s for s in app.hpd.systems if group in s.groups), None
        )
        self.parsed: Optional[Dict[str, Any]] = None

        self.top = tk.Toplevel(app.root)
        self.top.title(f"RadioReference Diff - {group.name}")
        self.top.transient(app.root)
        self.top.geometry("980x620")
        self.top.grab_set()

        header = ttk.Frame(self.top, padding=8)
        header.pack(fill=tk.X)
        ttk.Label(
            header,
            text=f"Group: {group.name}    URL: {url}",
            wraplength=940, justify=tk.LEFT,
        ).pack(anchor=tk.W)
        self.summary_var = tk.StringVar(value="Fetching RadioReference page...")
        ttk.Label(
            header, textvariable=self.summary_var, foreground="#333333",
        ).pack(anchor=tk.W, pady=(4, 0))

        tree_frame = ttk.Frame(self.top, padding=8)
        tree_frame.pack(fill=tk.BOTH, expand=True)
        columns = ("status", "ident", "local", "rr", "detail")
        self.tree = ttk.Treeview(
            tree_frame, columns=columns, show="headings", selectmode="browse"
        )
        for col, label, width, anchor in (
            ("status", "Status", 100, tk.W),
            ("ident", "Freq/TGID", 110, tk.W),
            ("local", "Local", 220, tk.W),
            ("rr", "RadioReference", 220, tk.W),
            ("detail", "Details", 260, tk.W),
        ):
            self.tree.heading(col, text=label)
            self.tree.column(col, width=width, anchor=anchor)
        self.tree.tag_configure("added", foreground="#1a7f37")
        self.tree.tag_configure("removed", foreground="#b22222")
        self.tree.tag_configure("changed", foreground="#b8860b")
        self.tree.tag_configure("same", foreground="#808080")
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        sb.pack(side=tk.LEFT, fill=tk.Y)
        self.tree.configure(yscrollcommand=sb.set)

        footer = ttk.Frame(self.top, padding=8)
        footer.pack(fill=tk.X)
        ttk.Button(footer, text="Refresh", command=self._on_refresh).pack(side=tk.LEFT)
        ttk.Button(
            footer, text="Open Reconciler...", command=self._on_open_reconciler,
        ).pack(side=tk.LEFT, padx=4)
        ttk.Button(footer, text="Close", command=self.top.destroy).pack(side=tk.RIGHT)

        self.top.after(50, self._fetch_and_populate)
        app.root.wait_window(self.top)

    def _fetch_and_populate(self) -> None:
        try:
            parsed = fetch_radioreference_data(self.url)
        except Exception as exc:
            messagebox.showerror(
                _LIT_FETCH_ERROR, f"Could not fetch RadioReference page:\n{exc}",
                parent=self.top,
            )
            self.summary_var.set("Fetch failed.")
            return
        if not parsed:
            self.summary_var.set("No usable data from the RadioReference page.")
            return
        self.parsed = parsed
        self._populate()

    def _on_refresh(self) -> None:
        for iid in self.tree.get_children(""):
            self.tree.delete(iid)
        self.summary_var.set("Refreshing...")
        self.top.update_idletasks()
        self._fetch_and_populate()

    def _on_open_reconciler(self) -> None:
        if not self.parsed:
            return
        self.top.destroy()
        self.app._refresh_group_from_rr(self.group, self.url)

    def _flatten_cfreq_rows(self) -> List[Dict[str, Any]]:
        return flatten_rr_cfreq_rows(self.parsed)

    def _flatten_tg_rows(self) -> List[Dict[str, Any]]:
        return flatten_rr_tg_rows(self.parsed)

    def _populate(self) -> None:
        rr_mode = rr_diff_mode(self.group, self.parsed)
        if rr_mode == "cfreq":
            counts = self._populate_cfreq_diff()
        else:
            counts = self._populate_tgid_diff()
        self.summary_var.set(
            f"Diff: {counts['added']} added, {counts['removed']} removed, "
            f"{counts['changed']} changed, {counts['same']} same"
        )

    def _populate_cfreq_diff(self) -> Dict[str, int]:
        diff_rows, counts = cfreq_diff_tree_rows(
            local_cfreq_by_hz(self.group),
            self._flatten_cfreq_rows(),
            diff_fn=diff_cfreq_with_rr,
            status_added=self.STATUS_ADDED,
            status_removed=self.STATUS_REMOVED,
            status_changed=self.STATUS_CHANGED,
            status_same=self.STATUS_SAME,
        )
        for row in diff_rows:
            self.tree.insert("", tk.END, values=row["values"], tags=row["tags"])
        return counts

    def _populate_tgid_diff(self) -> Dict[str, int]:
        diff_rows, counts = tgid_diff_tree_rows(
            local_tgid_by_id(self.group),
            self._flatten_tg_rows(),
            diff_fn=diff_tgid_with_rr,
            mode_label_fn=tgid_mode_label,
            status_added=self.STATUS_ADDED,
            status_removed=self.STATUS_REMOVED,
            status_changed=self.STATUS_CHANGED,
            status_same=self.STATUS_SAME,
        )
        for row in diff_rows:
            self.tree.insert("", tk.END, values=row["values"], tags=row["tags"])
        return counts


class ModeBandAuditorDialog:
    """Flag entries whose mode doesn't match the frequency band and offer quick-fix."""

    def __init__(self, app: "ScannerManagerApp"):
        self.app = app
        self.top = tk.Toplevel(app.root)
        self.top.title("Mode / Band Audit")
        self.top.transient(app.root)
        self.top.geometry("1020x560")

        self._rr_reference: Dict[int, Dict[str, Any]] = {}
        self._rr_sources: List[str] = []

        header = ttk.Frame(self.top, padding=8)
        header.pack(fill=tk.X)
        self.summary_var = tk.StringVar()
        ttk.Label(header, textvariable=self.summary_var).pack(side=tk.LEFT)
        ttk.Button(header, text="Refresh", command=self._refresh).pack(side=tk.RIGHT)

        ref_row = ttk.Frame(self.top, padding=(8, 0, 8, 0))
        ref_row.pack(fill=tk.X)
        self.rr_status_var = tk.StringVar(value="RR reference: none loaded")
        ttk.Label(ref_row, textvariable=self.rr_status_var, foreground="#555555").pack(side=tk.LEFT)
        ttk.Button(ref_row, text="Add RR Reference URL...", command=self._on_add_rr_reference).pack(
            side=tk.RIGHT, padx=2
        )
        ttk.Button(ref_row, text="Clear RR Reference", command=self._on_clear_rr_reference).pack(
            side=tk.RIGHT, padx=2
        )

        tree_frame = ttk.Frame(self.top)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)
        columns = ("system", "group", "name", "freq", "mode", "suggested", "source", "issue")
        self.tree = ttk.Treeview(
            tree_frame, columns=columns, show="headings", selectmode="extended",
        )
        for col, label, width in (
            ("system", "System", 150),
            ("group", "Group", 160),
            ("name", "Name", 140),
            ("freq", "Freq (MHz)", 90),
            ("mode", "Mode", 60),
            ("suggested", "Suggested", 80),
            ("source", "Source", 70),
            ("issue", "Issue", 240),
        ):
            self.tree.heading(col, text=label)
            self.tree.column(col, width=width, anchor=tk.W)
        self.tree.tag_configure("source_rr", foreground="#8b0000")
        self.tree.tag_configure("source_band", foreground="#606060")
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        sb.pack(side=tk.LEFT, fill=tk.Y)
        self.tree.configure(yscrollcommand=sb.set)

        footer = ttk.Frame(self.top, padding=8)
        footer.pack(fill=tk.X)
        ttk.Button(footer, text="Apply Suggested to Selected", command=self._on_fix_selected).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(footer, text="Apply Suggested to All", command=self._on_fix_all).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(footer, text="Close", command=self.top.destroy).pack(side=tk.RIGHT)

        self._issues: List[Tuple[FreqEntry, str, str]] = []
        self._refresh()

    def _refresh(self):
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        audit_rows, total, rr_flags, band_flags = collect_mode_audit_rows(
            self.app.hpd.systems,
            self._rr_reference,
            audit_mode_issue_with_rr,
        )
        self._issues = [(row["entry"], row["issue"], row["suggested"]) for row in audit_rows]
        for row in audit_rows:
            self.tree.insert("", tk.END, values=row["values"], tags=row["tags"])
        self.summary_var.set(
            f"Reviewed {total} conventional entries; "
            f"flagged {len(self._issues)} ({rr_flags} RR, {band_flags} band)."
        )
        if self._rr_sources:
            summary = (
                f"RR reference: {len(self._rr_reference)} frequencies from "
                f"{len(self._rr_sources)} URL(s)"
            )
        else:
            summary = "RR reference: none loaded"
        self.rr_status_var.set(summary)

    def _on_add_rr_reference(self):
        from tkinter import simpledialog

        url = simpledialog.askstring(
            "Add RR Reference URL",
            "Paste a RadioReference category URL (e.g. .../db/aid/3161):",
            parent=self.top,
        )
        if not url:
            return
        try:
            parsed = fetch_radioreference_data(url)
        except Exception as exc:
            messagebox.showerror("Fetch", f"Could not fetch URL:\n{exc}", parent=self.top)
            return
        if not parsed or parsed.get("kind") != "category":
            messagebox.showinfo(
                "Fetch",
                "Only RadioReference category (aid/cid) URLs are supported for audit reference.",
                parent=self.top,
            )
            return
        added = 0
        for freq in parsed.get("frequencies") or []:
            try:
                freq_hz = int(round(float(freq["mhz"]) * 1_000_000))
            except Exception:
                continue
            self._rr_reference[freq_hz] = {
                "mode": freq.get("mode") or "",
                "name": freq.get("name") or freq.get("alpha") or "",
                "tone": freq.get("tone") or "",
                "tag": freq.get("tag", ""),
            }
            added += 1
        self._rr_sources.append(url)
        self._refresh()
        messagebox.showinfo(
            "RR Reference",
            f"Loaded {added} frequencies from {parsed.get('group_name', 'URL')}.",
            parent=self.top,
        )

    def _on_clear_rr_reference(self):
        self._rr_reference.clear()
        self._rr_sources.clear()
        self._refresh()

    def _entries_for_iids(self, iids) -> List[Tuple[FreqEntry, str]]:
        result: List[Tuple[FreqEntry, str]] = []
        id_map = {str(id(ent)): (ent, suggested) for ent, _, suggested in self._issues}
        for iid in iids:
            tags = self.tree.item(iid, "tags")
            if not tags:
                continue
            key = tags[0]
            if key in id_map:
                result.append(id_map[key])
        return result

    def _apply_fix(self, pairs: List[Tuple[FreqEntry, str]]):
        if not pairs:
            return 0
        if not messagebox.askyesno(
            "Apply Mode Fix",
            f"Apply suggested mode to {len(pairs)} entries?",
            parent=self.top,
        ):
            return 0
        applied = 0
        for entry, suggested in pairs:
            entry.record.set_field(6, suggested)
            self.app.hpd.has_changes = True
            applied += 1
        self.app._populate_tree()
        self.app._set_status(f"Mode audit: applied suggested mode to {applied} entries.")
        self._refresh()
        return applied

    def _on_fix_selected(self):
        pairs = self._entries_for_iids(self.tree.selection())
        if not pairs:
            messagebox.showinfo("Audit", "Select one or more flagged entries first.", parent=self.top)
            return
        self._apply_fix(pairs)

    def _on_fix_all(self):
        pairs = [(ent, suggested) for ent, _, suggested in self._issues]
        self._apply_fix(pairs)


class BulkRemapDialog:
    """Filter entries by type/service/scope and apply a remap action in bulk."""

    def __init__(self, app: "ScannerManagerApp"):
        self.app = app
        self.top = tk.Toplevel(app.root)
        self.top.title(_LIT_BULK_REMAP)
        self.top.transient(app.root)
        self.top.geometry("680x520")

        frm = ttk.Frame(self.top, padding=8)
        frm.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frm, text="Entry types:").grid(row=0, column=0, sticky=tk.W, pady=4)
        type_frame = ttk.Frame(frm)
        type_frame.grid(row=0, column=1, columnspan=3, sticky=tk.W)
        self.include_cfreq = tk.BooleanVar(value=True)
        self.include_tgid = tk.BooleanVar(value=True)
        ttk.Checkbutton(type_frame, text="C-Freq", variable=self.include_cfreq).pack(side=tk.LEFT, padx=4)
        ttk.Checkbutton(type_frame, text="TGID", variable=self.include_tgid).pack(side=tk.LEFT, padx=4)

        ttk.Label(frm, text="Service types (comma-separated, blank=all):").grid(
            row=1, column=0, sticky=tk.W, pady=4
        )
        self.service_filter = tk.StringVar(value="")
        ttk.Entry(frm, textvariable=self.service_filter, width=30).grid(
            row=1, column=1, columnspan=3, sticky=tk.W
        )

        ttk.Label(frm, text="System scope:").grid(row=2, column=0, sticky=tk.W, pady=4)
        self.scope_var = tk.StringVar(value="all")
        ttk.Radiobutton(frm, text="All systems", variable=self.scope_var, value="all").grid(
            row=2, column=1, sticky=tk.W
        )
        ttk.Radiobutton(
            frm, text="Current location filter only",
            variable=self.scope_var, value="location",
        ).grid(row=2, column=2, sticky=tk.W)
        ttk.Radiobutton(
            frm, text="Selected system only",
            variable=self.scope_var, value="selected",
        ).grid(row=2, column=3, sticky=tk.W)

        ttk.Separator(frm, orient=tk.HORIZONTAL).grid(
            row=3, column=0, columnspan=4, sticky="ew", pady=6
        )

        ttk.Label(frm, text="Action:").grid(row=4, column=0, sticky=tk.W, pady=4)
        self.action_var = tk.StringVar(value="remap")
        ttk.Radiobutton(
            frm, text="Remap service type to", variable=self.action_var, value="remap",
        ).grid(row=4, column=1, sticky=tk.W)
        self.new_service_var = tk.StringVar()
        ttk.Combobox(
            frm, textvariable=self.new_service_var, state="readonly", width=22,
            values=[s[1] for s in SERVICE_CHOICES],
        ).grid(row=4, column=2, columnspan=2, sticky=tk.W)

        ttk.Separator(frm, orient=tk.HORIZONTAL).grid(
            row=5, column=0, columnspan=4, sticky="ew", pady=6
        )

        self.preview_var = tk.StringVar(value="Preview: (click Preview to count)")
        ttk.Label(frm, textvariable=self.preview_var, foreground="#333333").grid(
            row=6, column=0, columnspan=4, sticky=tk.W, pady=4
        )

        btns = ttk.Frame(frm)
        btns.grid(row=7, column=0, columnspan=4, pady=8)
        ttk.Button(btns, text="Preview", command=self._on_preview).pack(side=tk.LEFT, padx=4)
        ttk.Button(btns, text="Apply", command=self._on_apply).pack(side=tk.LEFT, padx=4)
        ttk.Button(btns, text="Close", command=self.top.destroy).pack(side=tk.LEFT, padx=4)

    def _collect_filter(self) -> Dict[str, Any]:
        types: Set[str] = set()
        if self.include_cfreq.get():
            types.add("C-Freq")
        if self.include_tgid.get():
            types.add("TGID")
        svc_text = (self.service_filter.get() or "").strip()
        service_types: Optional[Set[int]] = None
        if svc_text:
            try:
                service_types = {int(x.strip()) for x in svc_text.split(",") if x.strip()}
            except ValueError:
                service_types = None
        return {
            "entry_types": types,
            "service_types": service_types,
        }

    def _iter_candidates(self) -> List[FreqEntry]:
        flt = self._collect_filter()
        scope = self.scope_var.get()
        selected_system_id = None
        if scope == "selected" and self.app._selected_system is not None:
            selected_system_id = self.app._selected_system.system_id
        elif scope == "selected" and self.app._selected_group is not None:
            selected_system_id = self.app._selected_group.system_id
        elif scope == "selected" and self.app._selected_entry is not None:
            selected_system_id = self.app._selected_entry.system_id
        return iter_bulk_remap_candidates(
            self.app.hpd.systems,
            entry_types=flt["entry_types"],
            service_types=flt["service_types"],
            scope=scope,
            location_match_fn=self.app._system_matches_location,
            selected_system_id=selected_system_id,
        )

    def _on_preview(self):
        candidates = self._iter_candidates()
        self.preview_var.set(f"Preview: {len(candidates)} entries match the filter")

    def _on_apply(self):
        candidates = self._iter_candidates()
        if not candidates:
            messagebox.showinfo(_LIT_BULK_REMAP, "No entries match the filter.", parent=self.top)
            return
        action = self.action_var.get()
        if action == "remap":
            stype_str = self.new_service_var.get()
            if not stype_str:
                messagebox.showwarning(_LIT_BULK_REMAP, "Pick a service type first.", parent=self.top)
                return
            new_type = int(stype_str.split(" - ")[0])
            desc = f"remap service type to {service_label(new_type)}"
        else:
            return

        if not messagebox.askyesno(
            _LIT_BULK_REMAP,
            f"Apply '{desc}' to {len(candidates)} entries?",
            parent=self.top,
        ):
            return

        # Route through the event log so bulk remaps are revertable and
        # auditable. Wrap in a single MetaStore batch so the whole
        # operation emits one sidecar write regardless of candidate count.
        txn = self.app._new_txn_id()
        changed = 0
        batch_ctx = (
            self.app._meta.batch() if self.app._meta is not None else nullcontext()
        )
        with batch_ctx:
            if action == "remap":
                for entry in candidates:
                    if self.app._do_set_service(
                        entry, new_type, source="bulk_remap", txn_id=txn,
                    ):
                        changed += 1

        self.app._populate_tree()
        self.app._set_status(
            f"Bulk remap applied to {changed} of {len(candidates)} entries."
        )
        self.preview_var.set(f"Applied to {changed} entries.")


class AlertsViewerDialog:
    """Viewer for the SD card ``alert/`` folder.

    A file list on the left, file contents on the right, using the
    flat-folder layout of the ``alert/`` payloads.
    """

    MAX_PREVIEW_BYTES = 8192

    def __init__(self, app: "ScannerManagerApp"):
        self.app = app
        self.top = tk.Toplevel(app.root)
        self.top.title("Alerts")
        self.top.transient(app.root)
        self.top.geometry("900x600")

        sd_folder = (app._path_var.get() or "").strip()
        self.alert_root = Path(sd_folder) / "alert" if sd_folder else None
        self.files = (
            discover_alert_files(self.alert_root)
            if self.alert_root and self.alert_root.exists()
            else []
        )

        header_frame = ttk.Frame(self.top, padding=(8, 8, 8, 0))
        header_frame.pack(fill=tk.X)
        summary = alerts_viewer_summary(self.alert_root, self.files)
        ttk.Label(
            header_frame, text=summary, wraplength=860, justify=tk.LEFT
        ).pack(side=tk.LEFT)

        paned = ttk.PanedWindow(self.top, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        left = ttk.Frame(paned)
        paned.add(left, weight=1)
        self.file_tree = ttk.Treeview(
            left,
            columns=("name", "size", "modified"),
            show=_LIT_TREE_HEADINGS,
            selectmode="browse",
        )
        self.file_tree.heading("name", text="File")
        self.file_tree.heading("size", text="Size")
        self.file_tree.heading("modified", text="Modified")
        self.file_tree.column("#0", width=140, stretch=False)
        self.file_tree.column("name", width=220)
        self.file_tree.column("size", width=80, anchor=tk.E)
        self.file_tree.column("modified", width=160)
        self.file_tree.pack(fill=tk.BOTH, expand=True)
        self.file_tree.bind(_LIT_TREEVIEW_SELECT, self._on_select)

        right = ttk.Frame(paned)
        paned.add(right, weight=2)
        self.preview = tk.Text(right, wrap="none")
        self.preview.configure(state="disabled")
        self.preview.pack(fill=tk.BOTH, expand=True)

        folders: Dict[str, str] = {}
        if self.alert_root and self.files:
            for row in alerts_file_tree_rows(self.alert_root, self.files):
                key = row["folder_key"]
                if key not in folders:
                    folders[key] = self.file_tree.insert(
                        "", tk.END, text=row["folder_label"], open=True
                    )
                self.file_tree.insert(
                    folders[key],
                    tk.END,
                    text="",
                    values=(row["name"], row["size_kb"], row["modified"]),
                    tags=(str(row["path"]),),
                )

        footer = ttk.Frame(self.top, padding=8)
        footer.pack(fill=tk.X)
        ttk.Button(
            footer, text="Export Selected...", command=self._on_export
        ).pack(side=tk.LEFT)
        ttk.Button(footer, text="Close", command=self.top.destroy).pack(
            side=tk.RIGHT
        )

    def _selected_path(self) -> Optional[Path]:
        sel = self.file_tree.selection()
        if not sel:
            return None
        tags = self.file_tree.item(sel[0], "tags")
        if not tags:
            return None
        return Path(tags[0])

    def _render_preview(self, path: Path) -> str:
        try:
            stat = path.stat()
        except Exception:
            return f"File: {path}\n(could not stat)"
        lines: List[str] = [
            f"File: {path}",
            f"Size: {stat.st_size} bytes",
            f"Modified: {datetime.fromtimestamp(stat.st_mtime).isoformat(timespec='seconds')}",
            "",
        ]
        try:
            data = path.read_bytes()
        except Exception as exc:
            lines.append(f"(could not read: {exc})")
            return "\n".join(lines)
        chunk = data[: self.MAX_PREVIEW_BYTES]
        try:
            text = chunk.decode("utf-8")
            lines.append(text)
        except UnicodeDecodeError:
            try:
                text = chunk.decode("latin-1", errors="replace")
                lines.append("(shown as Latin-1 — file is not UTF-8)")
                lines.append(text)
            except Exception:
                lines.append("(binary - cannot preview)")
        if len(data) > self.MAX_PREVIEW_BYTES:
            lines.append("")
            lines.append(
                f"... ({len(data) - self.MAX_PREVIEW_BYTES} more bytes)"
            )
        return "\n".join(lines)

    def _on_select(self, event=None):
        path = self._selected_path()
        if not path or not path.exists():
            return
        self.preview.configure(state="normal")
        self.preview.delete("1.0", tk.END)
        self.preview.insert("1.0", self._render_preview(path))
        self.preview.configure(state="disabled")

    def _on_export(self):
        path = self._selected_path()
        if not path or not path.exists():
            messagebox.showinfo(
                "Export", "Select an alert file first.", parent=self.top
            )
            return
        target = filedialog.asksaveasfilename(
            title="Export Alert File",
            initialfile=path.name,
            filetypes=[(_LIT_ALL_FILES, "*.*")],
        )
        if not target:
            return
        try:
            shutil.copy2(path, target)
            self.app._set_status(f"Exported alert file to {target}")
        except Exception as exc:
            messagebox.showerror(
                "Export", f"Failed to export:\n{exc}", parent=self.top
            )


class TowerClusterDialog:
    """Popup that breaks down every system/group sharing a tower location.

    The coverage map and heatmap collapse co-located repeaters into a
    single marker so labels don't stack on top of each other. When the
    user clicks the marker, this dialog expands the cluster as a tree:
    one node per system, children are the individual groups or sites
    with their advertised coverage range.
    """

    def __init__(
        self,
        parent: tk.Misc,
        cluster: "coverage_maps.TowerCluster",
    ):
        self.cluster = cluster
        self.top = tk.Toplevel(parent)
        self.top.title("Tower site")
        self.top.transient(parent)
        self.top.geometry("480x360")
        try:
            self.top.grab_set()
        except Exception:
            pass

        header = ttk.Frame(self.top, padding=(10, 8, 10, 4))
        header.pack(fill=tk.X)
        ttk.Label(
            header,
            text=(
                f"{cluster.lat:.4f}, {cluster.lon:.4f}    "
                f"{cluster.size} channel group"
                + ("s" if cluster.size != 1 else "")
            ),
        ).pack(side=tk.LEFT)
        ttk.Button(header, text="Close", command=self.top.destroy).pack(
            side=tk.RIGHT
        )

        body = ttk.Frame(self.top, padding=(10, 0, 10, 10))
        body.pack(fill=tk.BOTH, expand=True)
        tree = ttk.Treeview(
            body,
            columns=("detail",),
            show=_LIT_TREE_HEADINGS,
            selectmode="browse",
        )
        tree.heading("#0", text="System / group")
        tree.heading("detail", text="Coverage")
        tree.column("#0", width=260, anchor=tk.W)
        tree.column("detail", width=160, anchor=tk.W)
        tree.pack(fill=tk.BOTH, expand=True)

        by_system = group_tower_members_by_system(cluster.members)
        for system_name, members in by_system:
            max_r = max((m.range_mi for m in members), default=0.0)
            parent_id = tree.insert(
                "",
                tk.END,
                text=system_name or "(unnamed system)",
                values=(f"~{max_r:.0f} mi" if max_r else "",),
                open=True,
            )
            for m in members:
                kind_label = "site" if m.kind == "site" else "group"
                tree.insert(
                    parent_id,
                    tk.END,
                    text=m.child or f"(unnamed {kind_label})",
                    values=(
                        f"{m.range_mi:.0f} mi {kind_label}"
                        if m.range_mi
                        else kind_label,
                    ),
                )


class EntryEditDialog:
    """Edit name, freq/tgid, mode, tone for a FreqEntry."""

    def __init__(self, parent: tk.Misc, entry: FreqEntry):
        self.entry = entry
        self.result: Optional[Dict[str, Any]] = None
        self.top = tk.Toplevel(parent)
        self.top.title(f"Edit {entry.entry_type}")
        self.top.transient(parent)
        self.top.grab_set()

        rec = entry.record
        frame = ttk.Frame(self.top, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)

        self.name_var = tk.StringVar(value=entry.name)
        ttk.Label(frame, text=_LIT_NAME_COLON).grid(row=0, column=0, sticky=tk.W, pady=2)
        ttk.Entry(frame, textvariable=self.name_var, width=32).grid(row=0, column=1, sticky=tk.EW, padx=4)

        row = 1
        self.identity_var = tk.StringVar(value=rec.get_field(5, ""))
        if entry.entry_type == "C-Freq":
            ttk.Label(frame, text=_LIT_FREQ_MHZ_COLON).grid(row=row, column=0, sticky=tk.W, pady=2)
            try:
                freq_hz = int(self.identity_var.get())
                self.identity_var.set(f"{freq_hz / 1_000_000:.4f}")
            except Exception:
                pass
        else:
            ttk.Label(frame, text="TGID:").grid(row=row, column=0, sticky=tk.W, pady=2)
        ttk.Entry(frame, textvariable=self.identity_var, width=18).grid(row=row, column=1, sticky=tk.W, padx=4)

        row += 1
        raw_mode = rec.get_field(6, "")
        if entry.entry_type == "C-Freq":
            mode_values = MODE_CHOICES_CONV
            self._mode_is_labeled = False
            self.mode_var = tk.StringVar(value=raw_mode)
        else:
            mode_values = MODE_CHOICES_TGID_LABELS
            self._mode_is_labeled = True
            self.mode_var = tk.StringVar(value=tgid_mode_label(raw_mode) if raw_mode else "")
        ttk.Label(frame, text=_LIT_MODE_COLON).grid(row=row, column=0, sticky=tk.W, pady=2)
        combo_width = 22 if entry.entry_type == "TGID" else 10
        ttk.Combobox(
            frame, textvariable=self.mode_var, values=mode_values, state="readonly",
            width=combo_width,
        ).grid(row=row, column=1, sticky=tk.W, padx=4)
        if entry.entry_type == "TGID":
            ttk.Label(
                frame,
                text=(
                    "Pick DIGITAL for any P25 talkgroup - the BearTracker\n"
                    "handles the two P25 flavors automatically.\n"
                    "Pick ANALOG for conventional analog voice.\n"
                    "Pick ALL when you aren't sure, and let the scanner\n"
                    "figure it out at play time."
                ),
                foreground="#555555", justify=tk.LEFT,
            ).grid(row=row, column=2, sticky=tk.W, padx=8)

        self.tone_var = tk.StringVar(value=rec.get_field(7, "") if entry.entry_type == "C-Freq" else "")
        if entry.entry_type == "C-Freq":
            row += 1
            ttk.Label(frame, text="Tone:").grid(row=row, column=0, sticky=tk.W, pady=2)
            ttk.Entry(frame, textvariable=self.tone_var, width=18).grid(row=row, column=1, sticky=tk.W, padx=4)

        row += 1
        btns = ttk.Frame(frame)
        btns.grid(row=row, column=0, columnspan=2, pady=(10, 0))
        ttk.Button(btns, text="OK", command=self._on_ok).pack(side=tk.LEFT, padx=4)
        ttk.Button(btns, text="Cancel", command=self.top.destroy).pack(side=tk.LEFT, padx=4)

        frame.columnconfigure(1, weight=1)
        parent.wait_window(self.top)

    def _on_ok(self):
        identity_text = self.identity_var.get().strip()
        if self.entry.entry_type == "C-Freq":
            try:
                identity_value = str(parse_freq_mhz(identity_text))
            except Exception:
                messagebox.showerror("Invalid", "Frequency must be a number in MHz.", parent=self.top)
                return
        else:
            if not identity_text.isdigit():
                messagebox.showerror("Invalid", "TGID must be an integer.", parent=self.top)
                return
            identity_value = identity_text
        raw_mode = self.mode_var.get()
        stored_mode = tgid_mode_canonical(raw_mode) if getattr(self, "_mode_is_labeled", False) else raw_mode
        self.result = {
            "name": self.name_var.get().strip(),
            "identity_value": identity_value,
            "mode": stored_mode,
            "tone": self.tone_var.get().strip() if self.entry.entry_type == "C-Freq" else None,
        }
        self.top.destroy()


class GroupEditDialog:
    """Edit name / lat / lon / range_miles for a GroupNode."""

    def __init__(self, parent: tk.Misc, group: GroupNode):
        self.group = group
        self.result: Optional[Dict[str, Any]] = None
        self.top = tk.Toplevel(parent)
        self.top.title(f"Edit {group.group_type}")
        self.top.transient(parent)
        self.top.grab_set()

        frame = ttk.Frame(self.top, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)

        self.name_var = tk.StringVar(value=group.name)
        self.lat_var = tk.StringVar(value="" if group.lat is None else f"{group.lat:.6f}")
        self.lon_var = tk.StringVar(value="" if group.lon is None else f"{group.lon:.6f}")
        self.range_var = tk.StringVar(
            value="" if group.range_miles is None else f"{group.range_miles:.1f}"
        )

        for i, (label, var) in enumerate(
            ((_LIT_NAME_COLON, self.name_var), ("Lat:", self.lat_var), ("Lon:", self.lon_var), ("Range (mi):", self.range_var))
        ):
            ttk.Label(frame, text=label).grid(row=i, column=0, sticky=tk.W, pady=2)
            ttk.Entry(frame, textvariable=var, width=26).grid(row=i, column=1, sticky=tk.EW, padx=4)

        btns = ttk.Frame(frame)
        btns.grid(row=4, column=0, columnspan=2, pady=(10, 0))
        ttk.Button(btns, text="OK", command=self._on_ok).pack(side=tk.LEFT, padx=4)
        ttk.Button(btns, text="Cancel", command=self.top.destroy).pack(side=tk.LEFT, padx=4)

        frame.columnconfigure(1, weight=1)
        parent.wait_window(self.top)

    def _on_ok(self):
        def _opt_float(text: str, label: str, lo: float, hi: float) -> Optional[float]:
            s = text.strip()
            if not s:
                return None
            try:
                v = float(s)
            except ValueError as exc:
                raise ValueError(f"{label} must be numeric.") from exc
            if not (lo <= v <= hi):
                raise ValueError(f"{label} out of range.")
            return v

        try:
            lat = _opt_float(self.lat_var.get(), "Lat", -90.0, 90.0)
            lon = _opt_float(self.lon_var.get(), "Lon", -180.0, 180.0)
            range_miles = _opt_float(self.range_var.get(), "Range", 0.0, 5000.0)
        except ValueError as exc:
            messagebox.showerror("Invalid", str(exc), parent=self.top)
            return

        self.result = {
            "name": self.name_var.get().strip(),
            "lat": lat,
            "lon": lon,
            "range_miles": range_miles,
        }
        self.top.destroy()


class SystemEditDialog:
    """Edit a SystemNode's top-level fields (currently just name)."""

    def __init__(self, parent: tk.Misc, system: SystemNode):
        self.system = system
        self.result: Optional[Dict[str, Any]] = None
        self.top = tk.Toplevel(parent)
        self.top.title(f"Edit {system.system_type} system")
        self.top.transient(parent)
        self.top.grab_set()

        frame = ttk.Frame(self.top, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)

        self.name_var = tk.StringVar(value=system.name)
        ttk.Label(frame, text=_LIT_NAME_COLON).grid(row=0, column=0, sticky=tk.W, pady=2)
        ttk.Entry(frame, textvariable=self.name_var, width=36).grid(
            row=0, column=1, sticky=tk.EW, padx=4
        )

        info_lines = [
            f"Type: {system.system_type}",
            f"System ID: {system.system_id}",
            f"Groups: {len(system.groups)}",
            f"Entries: {sum(len(g.entries) for g in system.groups)}",
        ]
        ttk.Label(
            frame, text="\n".join(info_lines), justify=tk.LEFT,
            foreground="#555555",
        ).grid(row=1, column=0, columnspan=2, sticky=tk.W, pady=(8, 0))

        btns = ttk.Frame(frame)
        btns.grid(row=2, column=0, columnspan=2, pady=(10, 0))
        ttk.Button(btns, text="OK", command=self._on_ok).pack(side=tk.LEFT, padx=4)
        ttk.Button(btns, text="Cancel", command=self.top.destroy).pack(side=tk.LEFT, padx=4)

        frame.columnconfigure(1, weight=1)
        parent.wait_window(self.top)

    def _on_ok(self):
        new_name = self.name_var.get().strip()
        if not new_name:
            messagebox.showerror("Invalid", "Name cannot be empty.", parent=self.top)
            return
        self.result = {"name": new_name}
        self.top.destroy()


class RadioReferenceSettingsDialog:
    """Configure the RadioReference SOAP API credentials.

    App key is stored plain in ``app_settings.json``; username + password
    are stored via ``keyring`` (Windows Credential Manager). When
    ``keyring`` is not installed we fall back to an in-memory cache that
    lives only for the current session.
    """

    def __init__(self, parent: tk.Misc, app: "ScannerManagerApp"):
        self.app = app
        self.top = tk.Toplevel(parent)
        self.top.title("RadioReference API")
        self.top.transient(parent)
        self.top.grab_set()
        self.top.geometry("540x340")

        frame = ttk.Frame(self.top, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            frame,
            text=(
                "Premium RadioReference accounts can query the SOAP API "
                "directly. When configured, imports hit the API; otherwise "
                "the app falls through to HTML scraping.\n\n"
                "The app key is stored in app_settings.json; your password "
                "is stored in the Windows Credential Manager (never in our "
                "JSON)."
            ),
            wraplength=500,
            justify=tk.LEFT,
            foreground="#444",
        ).pack(fill=tk.X, pady=(0, 8))

        self._app_key_var = tk.StringVar(value=self.app._rr_app_key())
        self._username_var = tk.StringVar(value=self.app._rr_username())
        self._password_var = tk.StringVar(value=self.app._rr_password())
        self._status_var = tk.StringVar()

        grid = ttk.Frame(frame)
        grid.pack(fill=tk.X)
        ttk.Label(grid, text="App Key").grid(row=0, column=0, sticky=tk.W, pady=3)
        ttk.Entry(grid, textvariable=self._app_key_var, width=44).grid(
            row=0, column=1, sticky=tk.EW, pady=3, padx=(8, 0)
        )
        ttk.Label(grid, text="Username").grid(row=1, column=0, sticky=tk.W, pady=3)
        ttk.Entry(grid, textvariable=self._username_var, width=44).grid(
            row=1, column=1, sticky=tk.EW, pady=3, padx=(8, 0)
        )
        ttk.Label(grid, text="Password").grid(row=2, column=0, sticky=tk.W, pady=3)
        ttk.Entry(
            grid, textvariable=self._password_var, show="*", width=44,
        ).grid(row=2, column=1, sticky=tk.EW, pady=3, padx=(8, 0))
        grid.columnconfigure(1, weight=1)

        status = ttk.Label(
            frame, textvariable=self._status_var,
            foreground="#2a6", wraplength=500,
        )
        status.pack(fill=tk.X, pady=(8, 0))

        btns = ttk.Frame(frame)
        btns.pack(fill=tk.X, pady=(10, 0))
        ttk.Button(btns, text="Test", command=self._on_test).pack(
            side=tk.LEFT, padx=3
        )
        ttk.Button(btns, text="Save", command=self._on_save).pack(
            side=tk.LEFT, padx=3
        )
        ttk.Button(btns, text="Clear", command=self._on_clear).pack(
            side=tk.LEFT, padx=3
        )
        ttk.Button(btns, text="Close", command=self.top.destroy).pack(
            side=tk.RIGHT, padx=3
        )
        parent.wait_window(self.top)

    def _apply_to_settings(self) -> None:
        self.app._app_settings["rr_app_key"] = self._app_key_var.get().strip()
        self.app._app_settings["rr_username"] = self._username_var.get().strip()
        self.app._save_app_settings()
        self.app._set_rr_password(
            self._username_var.get().strip(),
            self._password_var.get(),
        )

    def _on_save(self) -> None:
        self._apply_to_settings()
        self._status_var.set("Saved.")

    def _on_clear(self) -> None:
        self._app_key_var.set("")
        self._username_var.set("")
        self._password_var.set("")
        self._apply_to_settings()
        self._status_var.set("Cleared.")

    def _on_test(self) -> None:
        if rr_api is None:
            self._status_var.set(
                "rr_api module unavailable (install zeep: "
                "pip install -r requirements.txt)."
            )
            return
        self._apply_to_settings()
        client = self.app._rr_client()
        if client is None:
            self._status_var.set(
                "Cannot build client — check credentials and that 'zeep' "
                "is installed."
            )
            return
        try:
            premium = client.is_premium()
            data = client.get_user_data()
            expires = data.get("expirationDate") or data.get("expires") or ""
            if premium:
                self._status_var.set(
                    f"Authenticated. Premium: yes. Expires: {expires or 'n/a'}"
                )
            else:
                self._status_var.set(
                    "Authenticated but account is not Premium — API will "
                    "be disabled."
                )
        except Exception as exc:
            self._status_var.set(f"Test failed: {exc}")


class DataPipelineDialog:
    """Single-pane view of the full data pipeline health: installed
    Uniden tools, RadioReference API authentication state, the active
    Virtual-SD workspace, and a one-click 'Refresh everything' that
    chains RR pull \u2192 Uniden updater \u2192 workspace sync."""

    def __init__(self, parent: tk.Misc, app: "ScannerManagerApp"):
        self.app = app
        self.top = tk.Toplevel(parent)
        self.top.title("Data Pipeline")
        self.top.transient(parent)
        self.top.grab_set()
        self.top.geometry("720x520")

        outer = ttk.Frame(self.top, padding=10)
        outer.pack(fill=tk.BOTH, expand=True)

        self._summary_var = tk.StringVar()
        ttk.Label(
            outer, textvariable=self._summary_var,
            font=("TkDefaultFont", 11, "bold"),
        ).pack(fill=tk.X, pady=(0, 6))

        sections = ttk.Frame(outer)
        sections.pack(fill=tk.BOTH, expand=True)

        tools_lf = ttk.LabelFrame(
            sections, text="Uniden desktop apps", padding=8
        )
        tools_lf.pack(fill=tk.X, pady=3)
        self._tools_text = tk.Text(
            tools_lf, height=4, wrap="word", relief="flat",
            background=self.top.cget("background"),
        )
        self._tools_text.pack(fill=tk.X)
        self._tools_text.configure(state="disabled")

        rr_lf = ttk.LabelFrame(
            sections, text="RadioReference API", padding=8
        )
        rr_lf.pack(fill=tk.X, pady=3)
        self._rr_text = tk.Text(
            rr_lf, height=3, wrap="word", relief="flat",
            background=self.top.cget("background"),
        )
        self._rr_text.pack(fill=tk.X)
        self._rr_text.configure(state="disabled")

        vsd_lf = ttk.LabelFrame(
            sections, text="Virtual SD card / workspaces", padding=8
        )
        vsd_lf.pack(fill=tk.BOTH, expand=True, pady=3)
        self._vsd_text = tk.Text(
            vsd_lf, height=6, wrap="word", relief="flat",
            background=self.top.cget("background"),
        )
        self._vsd_text.pack(fill=tk.BOTH, expand=True)
        self._vsd_text.configure(state="disabled")

        btns = ttk.Frame(outer)
        btns.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(
            btns, text="Refresh everything",
            command=self._on_refresh_everything,
        ).pack(side=tk.LEFT, padx=3)
        ttk.Button(
            btns, text="Uniden Tools...",
            command=self._on_open_tools,
        ).pack(side=tk.LEFT, padx=3)
        ttk.Button(
            btns, text="RR API...",
            command=self._on_open_rr,
        ).pack(side=tk.LEFT, padx=3)
        ttk.Button(
            btns, text="Workspace...",
            command=self._on_open_workspaces,
        ).pack(side=tk.LEFT, padx=3)
        ttk.Button(
            btns, text="Recheck",
            command=self._refresh,
        ).pack(side=tk.LEFT, padx=3)
        ttk.Button(btns, text="Close", command=self.top.destroy).pack(
            side=tk.RIGHT, padx=3
        )

        self._refresh()
        parent.wait_window(self.top)

    # -- health snapshot ----------------------------------------------------

    def _snapshot(self) -> Dict[str, Any]:
        return self.app._pipeline_health_snapshot()

    def _refresh(self) -> None:
        snap = self._snapshot()
        health = snap["health"]
        self._summary_var.set(f"Pipeline health: {health.upper()}")
        # (tkinter Label foreground isn't dynamic on StringVar; set directly)
        self._set_text(
            self._tools_text,
            _format_tools_section(snap["tools"]),
        )
        self._set_text(
            self._rr_text,
            _format_rr_section(snap["rr"]),
        )
        self._set_text(
            self._vsd_text,
            _format_vsd_section(snap["vsd"]),
        )

    def _set_text(self, widget: tk.Text, content: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", tk.END)
        widget.insert("1.0", content)
        widget.configure(state="disabled")

    # -- button handlers ----------------------------------------------------

    def _on_refresh_everything(self) -> None:
        # Currently this just kicks off the push\u2192run\u2192pull pipeline with
        # the default tool. When Phase 3 wiring for RR bulk-refresh is
        # fully in-app we'll prepend that step here.
        self.top.destroy()
        self.app._run_update_pipeline()

    def _on_open_tools(self) -> None:
        self.top.destroy()
        self.app._on_open_uniden_tools()

    def _on_open_rr(self) -> None:
        self.top.destroy()
        self.app._on_open_rr_settings()

    def _on_open_workspaces(self) -> None:
        self.top.destroy()
        self.app._on_manage_workspaces()


def _format_tools_section(info: Dict[str, Any]) -> str:
    rows = info.get("rows") or []
    if not rows:
        return "No Uniden tools detected. Click 'Uniden Tools...' to install one."
    lines: List[str] = []
    for row in rows:
        marker = "\u2713" if row["installed"] else "\u2717"
        ver = row.get("version") or ("" if row["installed"] else "not installed")
        lines.append(f"  {marker} {row['display_name']}  {ver}")
    return "\n".join(lines)


def _format_rr_section(info: Dict[str, Any]) -> str:
    if info.get("zeep_missing"):
        return (
            "zeep package not installed \u2014 API disabled. Install via: "
            "pip install -r requirements.txt"
        )
    if not info.get("configured"):
        return "Not configured. Open 'RR API...' to enter credentials."
    if info.get("premium"):
        return (
            f"Authenticated as {info['username']}. "
            f"Premium expires: {info.get('expires') or 'unknown'}"
        )
    return (
        f"Authenticated as {info['username']}, but account is not Premium. "
        "Falling back to HTML scraping."
    )


def _format_vsd_section(info: Dict[str, Any]) -> str:
    return format_vsd_section(info)


class RadioReferencePullDialog:
    """Bulk-pull helper for RR Premium subscribers.

    The scraper can't usefully fetch "every system in a county" or
    "every county in a state" as a single URL — those pages are
    navigation hubs. With an authenticated API client we can list
    them and let the user copy the matching RR URLs back into the
    regular import flow.
    """

    def __init__(
        self,
        parent: tk.Misc,
        app: "ScannerManagerApp",
        client: "rr_api.RadioReferenceClient",
    ):
        self.app = app
        self.client = client
        self.top = tk.Toplevel(parent)
        self.top.title("RadioReference — Bulk Pull")
        self.top.transient(parent)
        self.top.grab_set()
        self.top.geometry("720x480")

        outer = ttk.Frame(self.top, padding=10)
        outer.pack(fill=tk.BOTH, expand=True)

        form = ttk.Frame(outer)
        form.pack(fill=tk.X)
        self._mode_var = tk.StringVar(value="county")
        ttk.Radiobutton(
            form, text="County", value="county",
            variable=self._mode_var,
        ).pack(side=tk.LEFT)
        ttk.Radiobutton(
            form, text="State", value="state",
            variable=self._mode_var,
        ).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Label(form, text="ID:").pack(side=tk.LEFT, padx=(14, 4))
        self._id_var = tk.StringVar()
        ttk.Entry(form, textvariable=self._id_var, width=10).pack(
            side=tk.LEFT
        )
        ttk.Button(form, text="Fetch", command=self._on_fetch).pack(
            side=tk.LEFT, padx=8
        )
        ttk.Label(
            outer,
            text=(
                "You can also paste the full RadioReference page URL for a "
                "county, state, or trunked system - the app will read the "
                "numeric ID out of it for you."
            ),
            foreground="#666",
        ).pack(fill=tk.X, pady=(2, 6))

        columns = ("title", "kind", "id", "url")
        self.tree = ttk.Treeview(
            outer, columns=columns, show="headings", selectmode="browse",
        )
        for col, w, lbl in (
            ("title", 260, "Title"),
            ("kind", 90, "Kind"),
            ("id", 80, "ID"),
            ("url", 260, "URL"),
        ):
            self.tree.heading(col, text=lbl)
            self.tree.column(col, width=w, anchor=tk.W, stretch=True)
        self.tree.pack(fill=tk.BOTH, expand=True, pady=(6, 0))

        btns = ttk.Frame(outer)
        btns.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(btns, text="Copy URL", command=self._on_copy_url).pack(
            side=tk.LEFT, padx=3
        )
        ttk.Button(btns, text="Close", command=self.top.destroy).pack(
            side=tk.RIGHT, padx=3
        )
        parent.wait_window(self.top)

    def _on_fetch(self) -> None:
        ident = (self._id_var.get() or "").strip()
        if not ident:
            return
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        mode = self._mode_var.get()
        try:
            if mode == "county":
                raw = self.client.get_county_systems(ident)
                imp = self.client.to_hpd_import(
                    raw, source="county", source_id=ident
                )
            else:
                raw = self.client.get_state_systems(ident)
                imp = self.client.to_hpd_import(
                    raw, source="state", source_id=ident
                )
        except Exception as exc:
            messagebox.showerror("RR Pull", str(exc), parent=self.top)
            return
        for entry in imp.entries:
            title, kind, ident_field, url = rr_pull_entry_row(entry, mode)
            self.tree.insert(
                "", "end",
                values=(title, kind, ident_field, url),
            )

    def _on_copy_url(self) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        url = self.tree.item(sel[0], "values")[3]
        if not url:
            return
        self.top.clipboard_clear()
        self.top.clipboard_append(url)
        self.app._set_status(f"Copied: {url}")


class AboutDialog:
    """Small modal showing app name, version, tagline, and a Donate button."""

    def __init__(self, app: "ScannerManagerApp"):
        self.app = app
        self.top = tk.Toplevel(app.root)
        self.top.title(f"About {APP_NAME}")
        self.top.transient(app.root)
        self.top.grab_set()
        self.top.resizable(False, False)

        frm = ttk.Frame(self.top, padding=16)
        frm.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            frm, text=APP_NAME,
            font=("TkDefaultFont", 14, "bold"),
        ).pack(anchor=tk.W)
        ttk.Label(
            frm, text=f"Version {APP_VERSION}",
            foreground="#555",
        ).pack(anchor=tk.W, pady=(2, 8))
        ttk.Label(
            frm, text=APP_TAGLINE, wraplength=420,
        ).pack(anchor=tk.W)
        ttk.Label(
            frm,
            text=(
                "Unofficial, community-built. Not affiliated with or endorsed "
                "by Uniden America Corporation. See DISCLAIMER.md for details."
            ),
            wraplength=420, foreground="#666",
        ).pack(anchor=tk.W, pady=(10, 8))

        links = ttk.Frame(frm)
        links.pack(anchor=tk.W, pady=(2, 8))
        ttk.Button(
            links, text="GitHub",
            command=lambda: webbrowser.open(APP_GITHUB_URL),
        ).pack(side=tk.LEFT, padx=2)
        ttk.Button(
            links, text="Wiki",
            command=lambda: webbrowser.open(APP_WIKI_URL),
        ).pack(side=tk.LEFT, padx=2)
        ttk.Button(
            links, text="Report an Issue",
            command=app._on_help_report_issue,
        ).pack(side=tk.LEFT, padx=2)

        btns = ttk.Frame(frm)
        btns.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(
            btns, text="Donate / Support...",
            command=self._on_donate,
        ).pack(side=tk.LEFT)
        ttk.Button(btns, text="Close", command=self.top.destroy).pack(
            side=tk.RIGHT
        )

    def _on_donate(self) -> None:
        self.top.destroy()
        DonateDialog(self.app)


class DonateDialog:
    """Modal listing PayPal + crypto donation targets with Copy buttons.

    If the optional ``qrcode`` dependency is installed, each crypto row
    also shows a QR code rendered on a Tk canvas. Without ``qrcode`` the
    dialog still works - it just omits the QR art.
    """

    _CRYPTO_ROWS: List[Tuple[str, str, str]] = [
        (
            "Bitcoin (BTC)",
            DONATE_BTC_ADDR,
            f"bitcoin:{DONATE_BTC_ADDR}",
        ),
        (
            "Ethereum (ETH)",
            DONATE_ETH_ADDR,
            f"ethereum:{DONATE_ETH_ADDR}",
        ),
        (
            "Tether (USDT, ERC-20)",
            DONATE_USDT_ERC20_ADDR,
            f"ethereum:{DONATE_USDT_ERC20_ADDR}",
        ),
    ]

    def __init__(self, app: "ScannerManagerApp"):
        self.app = app
        self.top = tk.Toplevel(app.root)
        self.top.title("Support the Project")
        self.top.transient(app.root)
        self.top.grab_set()
        self.top.resizable(False, False)

        frm = ttk.Frame(self.top, padding=16)
        frm.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            frm, text="Caffeinate the developer",
            font=("TkDefaultFont", 13, "bold"),
        ).pack(anchor=tk.W)
        ttk.Label(
            frm,
            text=(
                "If this project saved you time, please consider supporting "
                "my caffeine habit. PayPal is easiest; crypto is also "
                "appreciated. Any amount is genuinely appreciated."
            ),
            wraplength=500, foreground="#555",
        ).pack(anchor=tk.W, pady=(4, 10))

        paypal_row = ttk.Frame(frm)
        paypal_row.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(
            paypal_row, text="PayPal:", width=22, anchor=tk.W,
        ).pack(side=tk.LEFT)
        ttk.Button(
            paypal_row, text=DONATE_PAYPAL_URL,
            command=lambda: webbrowser.open(DONATE_PAYPAL_URL),
        ).pack(side=tk.LEFT)
        ttk.Button(
            paypal_row, text="Copy link",
            command=lambda: self._copy(DONATE_PAYPAL_URL, "PayPal link"),
        ).pack(side=tk.LEFT, padx=4)

        ttk.Separator(frm, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=4)

        self._qr_images: List[Any] = []  # keep GC refs for tk.PhotoImage
        qr_cls = self._load_qr()

        for label, addr, qr_data in self._CRYPTO_ROWS:
            row = ttk.Frame(frm)
            row.pack(fill=tk.X, pady=4)
            ttk.Label(row, text=label, width=22, anchor=tk.W).pack(
                side=tk.LEFT, anchor=tk.N
            )
            right = ttk.Frame(row)
            right.pack(side=tk.LEFT, fill=tk.X, expand=True)

            addr_entry = ttk.Entry(right, width=56)
            addr_entry.insert(0, addr)
            addr_entry.configure(state="readonly")
            addr_entry.pack(side=tk.TOP, anchor=tk.W)

            btns = ttk.Frame(right)
            btns.pack(side=tk.TOP, anchor=tk.W, pady=(2, 0))
            ttk.Button(
                btns, text="Copy address",
                command=lambda a=addr, lbl=label: self._copy(a, lbl),
            ).pack(side=tk.LEFT)
            if qr_cls is not None and (
                canvas := self._render_qr(right, qr_cls, qr_data)
            ) is not None:
                canvas.pack(side=tk.RIGHT, padx=8)

        if qr_cls is None:
            ttk.Label(
                frm,
                text=(
                    "(Install the optional 'qrcode' package for scannable "
                    "QR codes next to each address.)"
                ),
                foreground="#888",
            ).pack(anchor=tk.W, pady=(8, 0))

        ttk.Separator(frm, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=(10, 6))
        ttk.Button(
            frm, text="Close", command=self.top.destroy,
        ).pack(side=tk.RIGHT)

    @staticmethod
    def _load_qr():
        try:
            import qrcode  # type: ignore
            return qrcode
        except Exception:
            return None

    def _render_qr(self, parent: tk.Misc, qrcode_mod: Any, data: str):
        """Render ``data`` as a QR code on a Tk canvas. Returns the
        canvas widget or ``None`` on failure.
        """
        matrix = qr_code_matrix(qrcode_mod, data)
        if not matrix:
            return None
        rows = len(matrix)
        cols = len(matrix[0])
        pixel = 3
        size_px = cols * pixel
        canvas = tk.Canvas(
            parent, width=size_px, height=size_px,
            background="white", highlightthickness=0,
        )
        img = tk.PhotoImage(width=size_px, height=size_px)
        self._qr_images.append(img)
        for y in range(rows):
            row_colors = []
            for x in range(cols):
                cell = "#000000" if matrix[y][x] else "#ffffff"
                row_colors.extend([cell] * pixel)
            row_str = "{" + " ".join(row_colors) + "}"
            for py in range(y * pixel, (y + 1) * pixel):
                img.put(row_str, to=(0, py))
        canvas.create_image(0, 0, image=img, anchor=tk.NW)
        return canvas

    def _copy(self, value: str, label: str) -> None:
        self.top.clipboard_clear()
        self.top.clipboard_append(value)
        self.app._set_status(f"Copied {label} to clipboard.")


class UpdateAvailableDialog:
    """Shown when a newer Scanner Manager release is available on GitHub.

    The dialog can be driven in three modes:

    - **available**: newer version found — offers Update Now, Skip, Later,
      and Open Release Page.
    - **current**: user triggered the check manually and we're up to date.
    - **offline**: the background check couldn't reach GitHub; surfaced
      only for manual checks so startup remains silent on flaky networks.
    """

    def __init__(
        self,
        app: "ScannerManagerApp",
        *,
        info: Optional["updater.UpdateInfo"],
        mode: str = "available",
    ) -> None:
        self.app = app
        self.info = info
        self.mode = mode
        self.top = tk.Toplevel(app.root)
        self.top.title("Scanner Manager update")
        self.top.transient(app.root)
        self.top.geometry("560x440")
        self.top.resizable(True, True)

        frm = ttk.Frame(self.top, padding=12)
        frm.pack(fill=tk.BOTH, expand=True)

        if mode == "current":
            headline = f"You're on the latest version, v{APP_VERSION}."
        elif mode == "offline":
            headline = "Couldn't reach GitHub to check for updates."
        else:
            assert info is not None
            headline = f"Update available: v{APP_VERSION} → v{info.version}"
        ttk.Label(
            frm, text=headline, font=("TkDefaultFont", 11, "bold"),
        ).pack(anchor=tk.W, pady=(0, 6))

        body_text = tk.Text(frm, wrap="word", height=12)
        body_text.pack(fill=tk.BOTH, expand=True)
        if mode == "available" and info is not None:
            body_text.insert(
                "1.0",
                (info.body or "Release notes unavailable.").strip() + "\n",
            )
        elif mode == "current":
            body_text.insert(
                "1.0",
                "No newer release is published on GitHub.\n\n"
                "You can always grab the source or a fresh build from\n"
                f"{APP_RELEASES_URL}\n",
            )
        else:
            body_text.insert(
                "1.0",
                "Scanner Manager couldn't contact GitHub. Your network "
                "may be offline, proxied, or the service may be "
                "temporarily unavailable.\n\n"
                "You can download updates manually from\n"
                f"{APP_RELEASES_URL}\n",
            )
        body_text.configure(state="disabled")

        btns = ttk.Frame(frm)
        btns.pack(fill=tk.X, pady=(8, 0))

        if mode == "available" and info is not None:
            ttk.Button(
                btns, text="Update Now",
                command=self._on_update_now,
            ).pack(side=tk.LEFT)
            ttk.Button(
                btns, text="Open Release Page",
                command=self._on_open_release,
            ).pack(side=tk.LEFT, padx=6)
            ttk.Button(
                btns, text="Skip This Version",
                command=self._on_skip,
            ).pack(side=tk.LEFT, padx=6)
            ttk.Button(
                btns, text="Remind Me Later",
                command=self.top.destroy,
            ).pack(side=tk.RIGHT)
        else:
            ttk.Button(
                btns, text="Open Release Page",
                command=self._on_open_release,
            ).pack(side=tk.LEFT)
            ttk.Button(
                btns, text="Close", command=self.top.destroy,
            ).pack(side=tk.RIGHT)

    def _on_update_now(self) -> None:
        if self.info is None:
            self.top.destroy()
            return
        # On mac/linux we simply route the user to the release page; the
        # in-place swap implementation targets Windows frozen EXEs.
        if sys.platform != "win32" or not getattr(sys, "frozen", False):
            self._on_open_release()
            return
        webbrowser.open(self.info.html_url or APP_RELEASES_URL)
        messagebox.showinfo(
            "Manual update",
            "In-place updates for this build aren't wired up yet. "
            "Download the new EXE from the release page and replace "
            "this one.",
            parent=self.top,
        )
        self.top.destroy()

    def _on_open_release(self) -> None:
        target = (self.info.html_url if self.info else "") or APP_RELEASES_URL
        webbrowser.open(target)

    def _on_skip(self) -> None:
        if self.info is not None:
            self.app._app_settings["updater_skipped_version"] = self.info.version
            self.app._save_app_settings()
        self.top.destroy()


class UnidenInstallerDownloadDialog:
    """Downloads a Uniden installer from the pinned manifest URL, verifies
    its SHA-256, and returns the cached path ready for ``install_tool``.

    Presents a progress bar, a Cancel button, and a secondary
    "Browse for installer..." button so users on corporate networks
    (or those who already have a local copy) can side-load without
    going through the download.
    """

    @classmethod
    def run(
        cls,
        parent: tk.Misc,
        descriptor: Dict[str, Any],
        app: "ScannerManagerApp",
    ) -> Optional[str]:
        dlg = cls(parent, descriptor, app)
        parent.wait_window(dlg.top)
        return dlg.result

    def __init__(
        self,
        parent: tk.Misc,
        descriptor: Dict[str, Any],
        app: "ScannerManagerApp",
    ):
        self.parent = parent
        self.descriptor = descriptor
        self.app = app
        self.result: Optional[str] = None
        self._cancel = False
        self._worker: Optional[threading.Thread] = None

        self.top = tk.Toplevel(parent)
        self.top.title("Download Uniden Installer")
        self.top.transient(parent)
        self.top.grab_set()
        self.top.geometry("520x260")

        frm = ttk.Frame(self.top, padding=12)
        frm.pack(fill=tk.BOTH, expand=True)

        display_name = descriptor.get("display_name") or descriptor.get("tool_id")
        version = descriptor.get("version") or ""
        header = f"{display_name}"
        if version:
            header += f"  (v{version})"
        ttk.Label(frm, text=header, font=("TkDefaultFont", 11, "bold")).pack(
            anchor=tk.W, pady=(0, 4)
        )
        ttk.Label(
            frm,
            text=(
                "Scanner Manager does not redistribute Uniden's installers. "
                "With your permission it can download the installer directly "
                "from Uniden's CDN, verify the file against a pinned SHA-256 "
                "hash, and cache it for future use."
            ),
            wraplength=480, justify=tk.LEFT, foreground="#555",
        ).pack(anchor=tk.W, pady=(0, 6))

        url = descriptor.get("download_url") or ""
        url_row = ttk.Frame(frm)
        url_row.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(url_row, text="Source:", width=10).pack(side=tk.LEFT)
        url_entry = ttk.Entry(url_row)
        url_entry.insert(0, url)
        url_entry.configure(state="readonly")
        url_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.status_var = tk.StringVar(value="Ready.")
        ttk.Label(
            frm, textvariable=self.status_var, foreground="#333",
        ).pack(anchor=tk.W, pady=(4, 2))

        self.progress = ttk.Progressbar(
            frm, mode="determinate", length=480, maximum=100
        )
        self.progress.pack(fill=tk.X, pady=(0, 6))

        btns = ttk.Frame(frm)
        btns.pack(fill=tk.X, pady=(6, 0))
        self.download_btn = ttk.Button(
            btns, text="Download & Verify",
            command=self._start_download,
        )
        self.download_btn.pack(side=tk.LEFT)
        ttk.Button(
            btns, text="Browse for installer...",
            command=self._on_browse,
        ).pack(side=tk.LEFT, padx=6)
        ttk.Button(
            btns, text="Open vendor page",
            command=self._on_open_vendor,
        ).pack(side=tk.LEFT, padx=6)
        self.close_btn = ttk.Button(
            btns, text="Cancel", command=self._on_close,
        )
        self.close_btn.pack(side=tk.RIGHT)
        self.top.protocol("WM_DELETE_WINDOW", self._on_close)

    def _start_download(self) -> None:
        if self._worker and self._worker.is_alive():
            return
        self.download_btn.configure(state=tk.DISABLED)
        self.status_var.set("Starting download...")
        self._cancel = False

        def progress_cb(fetched: int, total: int) -> bool:
            if self._cancel:
                return False
            pct = 0.0
            if total > 0:
                pct = min(100.0, fetched * 100.0 / total)
            self.top.after(0, self._update_progress, fetched, total, pct)
            return True

        def worker() -> None:
            try:
                path = uniden_tools.download_installer(
                    self.descriptor, progress_cb=progress_cb,
                )
                self.top.after(0, self._on_download_ok, str(path))
            except KeyboardInterrupt:
                self.top.after(0, self._on_cancelled)
            except uniden_tools.InstallerHashMismatch as exc:
                self.top.after(0, self._on_hash_mismatch, exc)
            except Exception as exc:
                self.top.after(0, self._on_download_failed, str(exc))

        self._worker = threading.Thread(target=worker, daemon=True)
        self._worker.start()

    def _update_progress(self, fetched: int, total: int, pct: float) -> None:
        self.progress["value"] = pct
        if total > 0:
            self.status_var.set(
                f"Downloading... {fetched/1024/1024:.1f} / "
                f"{total/1024/1024:.1f} MB ({pct:.1f}%)"
            )
        else:
            self.status_var.set(
                f"Downloading... {fetched/1024/1024:.1f} MB"
            )

    def _on_download_ok(self, path: str) -> None:
        self.progress["value"] = 100.0
        self.status_var.set(
            f"Verified and cached: {path}"
        )
        self.result = path
        self.close_btn.configure(text="Close")
        self.app._set_status(
            f"Installer cached and verified at {path}"
        )
        # Close automatically so the Install flow can continue.
        self.top.after(600, self.top.destroy)

    def _on_download_failed(self, message: str) -> None:
        self.download_btn.configure(state=tk.NORMAL)
        self.status_var.set("Download failed.")
        messagebox.showerror(
            "Download failed", message, parent=self.top
        )

    def _on_hash_mismatch(self, exc: "uniden_tools.InstallerHashMismatch") -> None:
        """Surface a hash-verification failure with both hashes visible
        so the user (or a forum reporter) can file an actionable bug.
        """
        self.download_btn.configure(state=tk.NORMAL)
        self.status_var.set("Hash verification failed.")
        self.progress["value"] = 0
        body = (
            "Hash verification failed for this installer. This usually "
            "means Uniden has rotated the installer on their side and "
            "Scanner Manager's pinned hash is stale.\n\n"
            f"Tool: {exc.tool_id or self.descriptor.get('display_name', '?')}\n"
            f"URL: {exc.url}\n\n"
            f"Expected SHA-256:\n  {exc.expected or '(not pinned)'}\n\n"
            f"Got SHA-256:\n  {exc.got or '(could not compute)'}\n\n"
            "Please file an issue with these values so the manifest can "
            "be re-pinned:\n"
            "https://github.com/disturbedkh/scanner-manager/issues"
        )
        messagebox.showerror(
            "Installer hash mismatch", body, parent=self.top
        )

    def _on_cancelled(self) -> None:
        self.download_btn.configure(state=tk.NORMAL)
        self.status_var.set("Cancelled.")
        self.progress["value"] = 0

    def _on_browse(self) -> None:
        path = filedialog.askopenfilename(
            title="Select installer (setup.exe or .zip)",
            filetypes=[
                ("Installer", _LIT_EXE_GLOB),
                ("Zip archive", "*.zip"),
                (_LIT_ALL_FILES, "*.*"),
            ],
            parent=self.top,
        )
        if not path:
            return
        p = Path(path)
        expected = (self.descriptor.get("sha256") or "").strip().lower()
        if (
            expected
            and not uniden_tools.verify_installer(p, expected)
            and not messagebox.askyesno(
                "Hash mismatch",
                (
                    "The selected file's SHA-256 does not match the value "
                    "pinned for this tool. Run it anyway?\n\n"
                    "Only say Yes if you trust the source."
                ),
                parent=self.top,
            )
        ):
            return
        self.result = str(p)
        self.top.destroy()

    def _on_open_vendor(self) -> None:
        url = self.descriptor.get("vendor_page") or self.descriptor.get(
            "download_url"
        )
        if url:
            webbrowser.open(url)

    def _on_close(self) -> None:
        if self._worker and self._worker.is_alive():
            self._cancel = True
            self.status_var.set("Cancelling...")
            return
        self.top.destroy()


class UnidenToolsDialog:
    """Registry of installed / installable Uniden desktop apps.

    Rows show: display name, scanner family, installed path + version, and
    action buttons for Launch / Launch + Auto-Sync / Install / Open data
    folder. Overrides get persisted into ``app_settings.json`` under
    ``uniden_tools_overrides``.
    """

    def __init__(self, parent: tk.Misc, app: "ScannerManagerApp"):
        self.app = app
        self.top = tk.Toplevel(parent)
        self.top.title("Uniden Tools")
        self.top.transient(parent)
        self.top.grab_set()
        self.top.geometry("820x360")

        frame = ttk.Frame(self.top, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            frame,
            text=(
                "Uniden ships two scanner companion apps that both read from "
                "RadioReference. Scanner Manager detects their installs and "
                "orchestrates the push \u2192 update \u2192 pull cycle for you."
            ),
            wraplength=780,
            justify=tk.LEFT,
            foreground="#444",
        ).pack(fill=tk.X, pady=(0, 6))

        if not IS_WINDOWS:
            ttk.Label(
                frame,
                text=(
                    "\u26a0  Uniden Sentinel and the BT885 Update Manager are "
                    "Windows-only applications. This panel cannot launch or "
                    "install them on "
                    f"{'macOS' if IS_MACOS else 'this platform'}. Everything "
                    "else in Scanner Manager (HPD editing, RadioReference "
                    "import, ZIP/GPS simulation, workspaces) works here; you "
                    "just won't be able to drive Uniden's vendor tools from "
                    "this host. Run Scanner Manager on Windows to use them."
                ),
                wraplength=780,
                justify=tk.LEFT,
                foreground="#a33",
            ).pack(fill=tk.X, pady=(0, 6))

        columns = ("name", "family", "version", "path")
        self.tree = ttk.Treeview(
            frame, columns=columns, show="headings",
            height=6, selectmode="browse",
        )
        headings = {
            "name": "Tool",
            "family": "Scanner Family",
            "version": "Version",
            "path": "Install Path",
        }
        widths = {"name": 180, "family": 220, "version": 90, "path": 300}
        for col in columns:
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, width=widths[col], anchor=tk.W, stretch=True)
        self.tree.pack(fill=tk.BOTH, expand=True)
        self.tree.tag_configure("missing", foreground="#a33")

        self._tools: List["uniden_tools.UnidenTool"] = []
        self._refresh()

        btns = ttk.Frame(frame)
        btns.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(btns, text="Launch", command=self._on_launch).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(
            btns, text="Launch + Auto-Sync",
            command=self._on_launch_and_sync,
        ).pack(side=tk.LEFT, padx=4)
        ttk.Button(
            btns, text="Install...", command=self._on_install
        ).pack(side=tk.LEFT, padx=4)
        ttk.Button(
            btns, text="Override Path...", command=self._on_override
        ).pack(side=tk.LEFT, padx=4)
        ttk.Button(
            btns, text="Open Data Folder",
            command=self._on_open_data_dir,
        ).pack(side=tk.LEFT, padx=4)
        ttk.Button(btns, text="Refresh", command=self._refresh).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(btns, text="Close", command=self.top.destroy).pack(
            side=tk.RIGHT, padx=4
        )
        parent.wait_window(self.top)

    def _refresh(self) -> None:
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        self._tools = uniden_tools.detect_installed_tools(
            repo_root=self.app._script_dir,
            overrides=self.app._tool_overrides(),
        )
        for tool in self._tools:
            tags = () if tool.installed else ("missing",)
            version = tool.version or ("installed" if tool.installed else "not installed")
            self.tree.insert(
                "", "end", iid=tool.tool_id,
                values=(
                    tool.display_name,
                    tool.scanner_family,
                    version,
                    tool.exe_path or "\u2014",
                ),
                tags=tags,
            )

    def _selected_tool(self) -> Optional["uniden_tools.UnidenTool"]:
        sel = self.tree.selection()
        if not sel:
            return None
        tid = sel[0]
        for tool in self._tools:
            if tool.tool_id == tid:
                return tool
        return None

    def _on_launch(self) -> None:
        tool = self._selected_tool()
        if tool is None:
            messagebox.showinfo("Launch", _LIT_SELECT_TOOL_FIRST, parent=self.top)
            return
        if not tool.installed:
            messagebox.showinfo(
                "Not installed",
                "This tool is not installed yet. Use Install... to run the "
                "bundled installer.",
                parent=self.top,
            )
            return
        try:
            uniden_tools.run_tool(tool, wait=False)
            self.app._set_status(f"Launched {tool.display_name}.")
        except Exception as exc:
            messagebox.showerror("Launch failed", str(exc), parent=self.top)

    def _on_launch_and_sync(self) -> None:
        tool = self._selected_tool()
        if tool is None:
            messagebox.showinfo("Launch", _LIT_SELECT_TOOL_FIRST, parent=self.top)
            return
        if not tool.installed:
            messagebox.showinfo(
                "Not installed",
                "Install the tool first.",
                parent=self.top,
            )
            return
        self.top.destroy()
        self.app._run_update_pipeline(tool_id=tool.tool_id)

    def _on_install(self) -> None:
        tool = self._selected_tool()
        if tool is None:
            messagebox.showinfo("Install", _LIT_SELECT_TOOL_FIRST, parent=self.top)
            return
        # Prefer a cached / local copy if we already have one; otherwise
        # route the user through the download dialog which will fetch,
        # verify, and hand back a runnable path.
        if not tool.bundled_installer:
            resolution = uniden_tools.resolve_installer(tool.tool_id)
            if resolution.descriptor is None:
                messagebox.showerror(
                    "No installer",
                    "No installer manifest entry was found for this tool "
                    "and no local copy is available. Drop the setup files "
                    "into the scanner-manager folder and try again.",
                    parent=self.top,
                )
                return
            installer_path = UnidenInstallerDownloadDialog.run(
                self.top, resolution.descriptor, self.app,
            )
            if installer_path is None:
                return
            tool.bundled_installer = installer_path
        if not messagebox.askyesno(
            "Install",
            (
                f"Launch the installer for {tool.display_name}?\n\n"
                f"{tool.bundled_installer}\n\n"
                "Windows will prompt for elevation."
            ),
            parent=self.top,
        ):
            return
        try:
            uniden_tools.install_tool(tool, wait=True)
        except Exception as exc:
            messagebox.showerror("Install failed", str(exc), parent=self.top)
            return
        self._refresh()

    def _on_override(self) -> None:
        tool = self._selected_tool()
        if tool is None:
            messagebox.showinfo(
                "Override", _LIT_SELECT_TOOL_FIRST, parent=self.top
            )
            return
        path = filedialog.askopenfilename(
            title=f"Select {tool.display_name} executable",
            filetypes=[("Executable", _LIT_EXE_GLOB), (_LIT_ALL_FILES, "*.*")],
            parent=self.top,
        )
        if not path:
            return
        overrides = self.app._tool_overrides()
        overrides[tool.tool_id] = path
        self.app._app_settings["uniden_tools_overrides"] = overrides
        self.app._save_app_settings()
        self._refresh()

    def _on_open_data_dir(self) -> None:
        tool = self._selected_tool()
        if tool is None:
            messagebox.showinfo(
                "Open", _LIT_SELECT_TOOL_FIRST, parent=self.top
            )
            return
        target = tool.data_dir or (
            os.path.dirname(tool.exe_path) if tool.exe_path else None
        )
        if not target or not os.path.isdir(target):
            messagebox.showinfo(
                "Open", "No data folder discovered yet.", parent=self.top
            )
            return
        try:
            open_in_file_manager(target)
        except Exception as exc:
            messagebox.showerror("Open", str(exc), parent=self.top)


class WorkspaceManagerDialog:
    """Pick an existing workspace profile, clone a new one, or remove."""

    def __init__(self, parent: tk.Misc, app: "ScannerManagerApp"):
        self.app = app
        self.result: Optional[Dict[str, Any]] = None
        self.top = tk.Toplevel(parent)
        self.top.title("Scanner Workspaces")
        self.top.transient(parent)
        self.top.grab_set()
        self.top.geometry("760x420")

        frame = ttk.Frame(self.top, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)

        info = ttk.Label(
            frame,
            text=(
                "Workspaces let you clone the SD card into a local folder so "
                "you can keep editing while the card is out. Each profile "
                "remembers the card that created it so sync can find its way home."
            ),
            wraplength=720,
            justify=tk.LEFT,
            foreground="#444",
        )
        info.pack(fill=tk.X, pady=(0, 8))

        columns = ("name", "target", "workspace", "last_sync", "card")
        self.tree = ttk.Treeview(
            frame, columns=columns, show="headings", height=10, selectmode="browse"
        )
        headings = {
            "name": "Profile",
            "target": "Target Model",
            "workspace": "Workspace",
            "last_sync": "Last Sync",
            "card": "Card Connected?",
        }
        widths = {
            "name": 160, "target": 120,
            "workspace": 260, "last_sync": 120, "card": 90,
        }
        for col in columns:
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, width=widths[col], anchor=tk.W, stretch=True)
        self.tree.pack(fill=tk.BOTH, expand=True)

        self._populate()

        btns = ttk.Frame(frame)
        btns.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(btns, text="Open Selected", command=self._on_open).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(
            btns, text="Activate on SD card...", command=self._on_activate
        ).pack(side=tk.LEFT, padx=4)
        ttk.Button(btns, text="Snapshots...", command=self._on_snapshots).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(btns, text="Clone from current SD...",
                   command=self._on_clone).pack(side=tk.LEFT, padx=4)
        ttk.Button(btns, text="Remove Selected", command=self._on_remove).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(btns, text="Close", command=self.top.destroy).pack(
            side=tk.RIGHT, padx=4
        )
        parent.wait_window(self.top)

    def _populate(self) -> None:
        for item_id in self.tree.get_children():
            self.tree.delete(item_id)
        ident = self.app._detect_card_identity()
        for profile in self.app._global_meta.list_profiles():
            matches_card = bool(
                ident.has_any_id()
                and (
                    (ident.volume_serial and ident.volume_serial == profile.get("card_volume_serial"))
                    or (ident.content_fingerprint and ident.content_fingerprint == profile.get("content_fingerprint"))
                )
            )
            self.tree.insert(
                "", "end",
                iid=profile["profile_id"],
                values=(
                    profile.get("name") or "(unnamed)",
                    profile.get("target_model") or "—",
                    profile.get("workspace_dir") or "—",
                    profile.get("last_sync_at") or "never",
                    "yes" if matches_card else "no",
                ),
            )

    def _selected_profile_id(self) -> Optional[str]:
        sel = self.tree.selection()
        return sel[0] if sel else None

    def _on_open(self) -> None:
        pid = self._selected_profile_id()
        if not pid:
            messagebox.showinfo("Open", "Select a profile first.", parent=self.top)
            return
        self.result = {"action": "open", "profile_id": pid}
        self.top.destroy()

    def _on_activate(self) -> None:
        pid = self._selected_profile_id()
        if not pid:
            messagebox.showinfo(
                "Activate",
                "Select a profile to copy onto the SD card.",
                parent=self.top,
            )
            return
        self.result = {"action": "activate", "profile_id": pid}
        self.top.destroy()

    def _on_snapshots(self) -> None:
        pid = self._selected_profile_id()
        if not pid:
            messagebox.showinfo(
                "Snapshots",
                "Select a profile to see its snapshots.",
                parent=self.top,
            )
            return
        self.result = {"action": "snapshots", "profile_id": pid}
        self.top.destroy()

    def _on_remove(self) -> None:
        pid = self._selected_profile_id()
        if not pid:
            messagebox.showinfo(
                "Remove", "Select a profile to remove.", parent=self.top
            )
            return
        profile = self.app._global_meta.get_profile(pid)
        if not messagebox.askyesno(
            "Remove profile",
            f"Remove profile '{(profile or {}).get('name') or pid}' from the "
            "registry?\n\nThe workspace folder is NOT deleted from disk.",
            parent=self.top,
        ):
            return
        self.result = {"action": "remove", "profile_id": pid}
        self.top.destroy()

    def _on_clone(self) -> None:
        card_root = (self.app._path_var.get() or "").strip()
        if not card_root or not os.path.isdir(card_root):
            messagebox.showerror(
                "Clone",
                "Point the SD Card Folder at a real card first.",
                parent=self.top,
            )
            return
        default_name = (
            sdcard.probe_card_identity(card_root).target_model
            or "Beartracker Workspace"
        )
        from tkinter import simpledialog
        name = simpledialog.askstring(
            "Clone SD",
            "Name for this scanner profile:",
            initialvalue=default_name,
            parent=self.top,
        )
        if not name:
            return
        initial_dir = os.path.join(
            os.path.dirname(card_root) or os.path.expanduser("~"),
            "scanner-workspaces",
        )
        os.makedirs(initial_dir, exist_ok=True)
        ws_dir = filedialog.askdirectory(
            title="Choose a folder to hold the workspace (a new subfolder will be created)",
            initialdir=initial_dir,
            parent=self.top,
        )
        if not ws_dir:
            return
        clone = workspace_clone_result(name, ws_dir)
        if clone is None:
            return
        if clone.get("needs_nonempty_confirm") and not messagebox.askyesno(
                "Clone",
                f"{clone['workspace_dir']} already exists and is not empty. "
                "Cloning may overwrite files. Continue?",
                parent=self.top,
            ):
            return
        self.result = {
            "action": clone["action"],
            "name": clone["name"],
            "workspace_dir": clone["workspace_dir"],
        }
        self.top.destroy()


class ProfileSnapshotsDialog:
    """Browse, take, restore, and delete snapshots for one workspace profile.

    Snapshots are per-profile content backups stored under
    ``<workspace>/.snapshots/<id>/``. Each row shows the created time,
    why the snapshot was taken, a short note, the file count, and the
    disk usage. Manual snapshots are pinned - the retention pruner
    never removes them.
    """

    def __init__(
        self,
        parent: tk.Misc,
        app: "ScannerManagerApp",
        profile_id: str,
    ):
        self.app = app
        self.profile_id = profile_id
        self.result: Optional[Dict[str, Any]] = None
        profile = app._global_meta.get_profile(profile_id) or {}
        name = profile.get("name") or profile_id
        self.top = tk.Toplevel(parent)
        self.top.title(f"Snapshots - {name}")
        self.top.transient(parent)
        self.top.grab_set()
        self.top.geometry("820x440")

        frame = ttk.Frame(self.top, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            frame,
            text=(
                "Each snapshot is a full copy of the workspace at a "
                "point in time. Manual snapshots are kept forever; "
                "pre-swap and auto snapshots are pruned by the profile's "
                "retention rule."
            ),
            wraplength=760,
            justify=tk.LEFT,
            foreground="#444",
        ).pack(fill=tk.X, pady=(0, 8))

        columns = ("created", "reason", "note", "files", "size", "kept")
        self.tree = ttk.Treeview(
            frame, columns=columns, show="headings", height=12, selectmode="browse"
        )
        headings = {
            "created": "Created",
            "reason": "Reason",
            "note": "Note",
            "files": "Files",
            "size": "Size",
            "kept": "Kept",
        }
        widths = {
            "created": 170, "reason": 100, "note": 260,
            "files": 60, "size": 90, "kept": 60,
        }
        for col in columns:
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, width=widths[col], anchor=tk.W, stretch=True)
        self.tree.pack(fill=tk.BOTH, expand=True)

        self.usage_var = tk.StringVar(value="")
        ttk.Label(
            frame, textvariable=self.usage_var, foreground="#555"
        ).pack(anchor=tk.W, pady=(6, 0))

        btns = ttk.Frame(frame)
        btns.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(
            btns, text="Take Snapshot Now...", command=self._on_take
        ).pack(side=tk.LEFT, padx=4)
        ttk.Button(btns, text="Restore", command=self._on_restore).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(btns, text="Edit Note...", command=self._on_edit_note).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(btns, text="Pin / Unpin", command=self._on_toggle_keep).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(btns, text="Delete", command=self._on_delete).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(btns, text="Close", command=self.top.destroy).pack(
            side=tk.RIGHT, padx=4
        )

        self._populate()
        parent.wait_window(self.top)

    def _snapshots(self) -> List["sdcard.Snapshot"]:
        profile = self.app._global_meta.get_profile(self.profile_id) or {}
        return self.app._profile_snapshots(profile)

    def _format_size(self, n: int) -> str:
        if n <= 0:
            return "0 B"
        units = ["B", "KB", "MB", "GB", "TB"]
        val = float(n)
        i = 0
        while val >= 1024 and i < len(units) - 1:
            val /= 1024
            i += 1
        return f"{val:.1f} {units[i]}" if i else f"{int(val)} {units[i]}"

    def _populate(self) -> None:
        for item_id in self.tree.get_children():
            self.tree.delete(item_id)
        snapshots = self._snapshots()
        snapshots_sorted = sorted(
            snapshots, key=lambda s: s.created_at or "", reverse=True
        )
        for snap in snapshots_sorted:
            kept = "yes" if (snap.keep or snap.reason == sdcard.SNAP_REASON_MANUAL) else ""
            self.tree.insert(
                "", "end",
                iid=snap.id,
                values=(
                    snap.created_at,
                    snap.reason,
                    snap.note,
                    snap.file_count,
                    self._format_size(snap.size_bytes),
                    kept,
                ),
            )
        profile = self.app._global_meta.get_profile(self.profile_id) or {}
        ws = profile.get("workspace_dir") or ""
        on_disk = sdcard.snapshot_disk_usage(ws) if ws else 0
        self.usage_var.set(
            f"Snapshots on disk: {self._format_size(on_disk)}  "
            f"({len(snapshots)} total)"
        )

    def _selected_id(self) -> Optional[str]:
        sel = self.tree.selection()
        return sel[0] if sel else None

    def _on_take(self) -> None:
        from tkinter import simpledialog
        note = simpledialog.askstring(
            "Take Snapshot",
            "Optional note for this snapshot:",
            parent=self.top,
        )
        if note is None:
            return
        self.result = {"action": "take_manual", "note": note.strip()}
        self.top.destroy()

    def _on_restore(self) -> None:
        sid = self._selected_id()
        if not sid:
            messagebox.showinfo(
                "Restore", "Select a snapshot to restore.", parent=self.top
            )
            return
        self.result = {"action": "restore", "snap_id": sid}
        self.top.destroy()

    def _on_edit_note(self) -> None:
        sid = self._selected_id()
        if not sid:
            return
        profile = self.app._global_meta.get_profile(self.profile_id)
        if not profile:
            return
        snaps = self.app._profile_snapshots(profile)
        target = next((s for s in snaps if s.id == sid), None)
        if target is None:
            return
        from tkinter import simpledialog
        new_note = simpledialog.askstring(
            "Edit Note",
            "Note for this snapshot:",
            initialvalue=target.note,
            parent=self.top,
        )
        if new_note is None:
            return
        target.note = new_note.strip()
        self.app._set_profile_snapshots(profile, snaps)
        self.app._global_meta.upsert_profile(profile)
        self.app._global_meta.save()
        self._populate()

    def _on_toggle_keep(self) -> None:
        sid = self._selected_id()
        if not sid:
            return
        profile = self.app._global_meta.get_profile(self.profile_id)
        if not profile:
            return
        snaps = self.app._profile_snapshots(profile)
        target = next((s for s in snaps if s.id == sid), None)
        if target is None:
            return
        target.keep = not target.keep
        self.app._set_profile_snapshots(profile, snaps)
        self.app._global_meta.upsert_profile(profile)
        self.app._global_meta.save()
        self._populate()

    def _on_delete(self) -> None:
        sid = self._selected_id()
        if not sid:
            return
        if not messagebox.askyesno(
            "Delete Snapshot",
            "Delete this snapshot? The payload files will be removed from disk.",
            parent=self.top,
        ):
            return
        profile = self.app._global_meta.get_profile(self.profile_id)
        if not profile:
            return
        snaps = [s for s in self.app._profile_snapshots(profile) if s.id != sid]
        self.app._set_profile_snapshots(profile, snaps)
        self.app._global_meta.upsert_profile(profile)
        self.app._global_meta.save()
        ws = profile.get("workspace_dir") or ""
        if ws:
            sdcard.delete_snapshot_payload(ws, sid)
        self._populate()


class SyncConflictDialog:
    """3-way conflict resolution dialog for Sync pull/push.

    For each conflicting file the user picks ``take_card``,
    ``take_workspace``, or ``skip``. Non-conflicting files are shown as
    context so the user understands what just happened.
    """

    def __init__(
        self,
        parent: tk.Misc,
        *,
        report: "sdcard.SyncReport",
        diffs: List["sdcard.FileDiff"],
        direction: str,
    ):
        self.report = report
        self.diffs = diffs
        self.direction = direction
        self.result: Optional[Dict[str, Any]] = None
        self.top = tk.Toplevel(parent)
        self.top.title(f"Sync {direction} — resolve conflicts")
        self.top.transient(parent)
        self.top.grab_set()
        self.top.geometry("820x520")

        frame = ttk.Frame(self.top, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            frame,
            text=(
                "These files were modified on both sides since the last sync. "
                "Choose which version wins for each, or skip to leave the file alone."
            ),
            wraplength=780,
            justify=tk.LEFT,
        ).pack(fill=tk.X, pady=(0, 6))

        self.tree = ttk.Treeview(
            frame, columns=("file", "decision"), show="headings",
            height=14, selectmode="extended",
        )
        self.tree.heading("file", text="File")
        self.tree.heading("decision", text="Decision")
        self.tree.column("file", width=540, anchor=tk.W)
        self.tree.column("decision", width=220, anchor=tk.W)
        self.tree.pack(fill=tk.BOTH, expand=True)

        self._decisions: Dict[str, str] = {}
        for rel in report.conflicts:
            self._decisions[rel] = "skip"
            self.tree.insert("", "end", iid=rel, values=(rel, "skip"))

        btns = ttk.Frame(frame)
        btns.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(
            btns, text="Take CARD version",
            command=lambda: self._apply_to_selection("take_card"),
        ).pack(side=tk.LEFT, padx=4)
        ttk.Button(
            btns, text="Take WORKSPACE version",
            command=lambda: self._apply_to_selection("take_workspace"),
        ).pack(side=tk.LEFT, padx=4)
        ttk.Button(
            btns, text="Skip",
            command=lambda: self._apply_to_selection("skip"),
        ).pack(side=tk.LEFT, padx=4)
        ttk.Button(btns, text="Apply & Close", command=self._on_ok).pack(
            side=tk.RIGHT, padx=4
        )
        ttk.Button(btns, text="Cancel", command=self.top.destroy).pack(
            side=tk.RIGHT, padx=4
        )
        parent.wait_window(self.top)

    def _apply_to_selection(self, decision: str) -> None:
        sel = self.tree.selection() or tuple(self.tree.get_children())
        for iid in sel:
            self._decisions[iid] = decision
            current = list(self.tree.item(iid, "values"))
            current[1] = decision
            self.tree.item(iid, values=current)

    def _on_ok(self) -> None:
        self.result = {"decisions": dict(self._decisions)}
        self.top.destroy()


class ChangesPanelDialog:
    """Reverse-chronological Changes panel backed by the MetaStore event log.

    Supports filters, per-row Revert, multi-select Revert, Revert to this
    point, and a details drawer showing before/after.
    """

    _OP_LABELS = {
        OP_EDIT_ENTRY: "Edit entry",
        OP_EDIT_GROUP: "Edit group",
        OP_EDIT_SYSTEM: "Edit system",
        OP_ADD_ENTRY: "Add entry",
        OP_ADD_GROUP: "Add group",
        OP_DELETE_ENTRY: "Delete entry",
        OP_DELETE_GROUP: "Delete group",
        OP_DELETE_SYSTEM: "Delete system",
        OP_SET_SERVICE: "Service type",
        OP_IMPORT_APPLY: "Import",
        OP_LINK_RR: "Link RR",
        OP_UNLINK_RR: "Unlink RR",
        OP_EXTERNAL_CHANGE: "External change",
        OP_REVERT: "Revert",
        OP_BULK_REVERT: "Bulk revert",
    }

    def __init__(self, app: "ScannerManagerApp"):
        self.app = app
        self.top = tk.Toplevel(app.root)
        self.top.title(
            f"Changes - {os.path.basename(app.hpd.filepath)}"
            if app.hpd.filepath
            else "Changes"
        )
        self.top.transient(app.root)
        self.top.geometry("1000x620")

        # -- filter bar --
        filters = ttk.Frame(self.top, padding=8)
        filters.pack(fill=tk.X)
        ttk.Label(filters, text="Filter:").pack(side=tk.LEFT)
        self.op_filter_var = tk.StringVar(value="All")
        op_vals = ["All"] + list(self._OP_LABELS.values())
        ttk.Combobox(
            filters, textvariable=self.op_filter_var, values=op_vals,
            state="readonly", width=16,
        ).pack(side=tk.LEFT, padx=4)
        self.source_filter_var = tk.StringVar(value="All")
        ttk.Combobox(
            filters, textvariable=self.source_filter_var,
            values=["All", "manual", "bulk", "rr_category", "rr_ctid", "rr_sid", "rr_callsign"],
            state="readonly", width=14,
        ).pack(side=tk.LEFT, padx=4)
        self.status_filter_var = tk.StringVar(value="Active")
        ttk.Combobox(
            filters, textvariable=self.status_filter_var,
            values=["Active", "Reverted", "All"],
            state="readonly", width=10,
        ).pack(side=tk.LEFT, padx=4)
        self.committed_filter_var = tk.StringVar(value="All")
        ttk.Combobox(
            filters, textvariable=self.committed_filter_var,
            values=["All", "Saved", "Pending"],
            state="readonly", width=10,
        ).pack(side=tk.LEFT, padx=4)
        self.search_var = tk.StringVar()
        ttk.Label(filters, text="Search:").pack(side=tk.LEFT, padx=(12, 2))
        search_entry = ttk.Entry(filters, textvariable=self.search_var, width=22)
        search_entry.pack(side=tk.LEFT, padx=2)
        search_entry.bind("<Return>", lambda e: self._refresh())
        ttk.Button(filters, text="Apply", command=self._refresh).pack(side=tk.LEFT, padx=4)
        for var in (
            self.op_filter_var,
            self.source_filter_var,
            self.status_filter_var,
            self.committed_filter_var,
        ):
            var.trace_add("write", lambda *args: self._refresh())

        # -- main treeview --
        frame = ttk.Frame(self.top)
        frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)
        cols = ("ts", "op", "target", "source", "status", "saved", "summary")
        self.tree = ttk.Treeview(
            frame, columns=cols, show="headings", selectmode="extended"
        )
        self.tree.heading("ts", text="Time")
        self.tree.heading("op", text="Op")
        self.tree.heading("target", text="Target")
        self.tree.heading("source", text="Source")
        self.tree.heading("status", text="Status")
        self.tree.heading("saved", text="Saved")
        self.tree.heading("summary", text="Summary")
        self.tree.column("ts", width=140)
        self.tree.column("op", width=90)
        self.tree.column("target", width=180)
        self.tree.column("source", width=90)
        self.tree.column("status", width=70)
        self.tree.column("saved", width=70, anchor=tk.CENTER)
        self.tree.column("summary", width=320)
        self.tree.tag_configure("pending", background="#fff7d6")
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.tree.yview)
        sb.pack(side=tk.LEFT, fill=tk.Y)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.bind(_LIT_TREEVIEW_SELECT, lambda e: self._refresh_details())

        # -- details drawer --
        details_frame = ttk.LabelFrame(self.top, text="Details", padding=6)
        details_frame.pack(fill=tk.BOTH, expand=False, padx=8, pady=(0, 4))
        self.details_text = tk.Text(details_frame, height=8, wrap="word")
        self.details_text.pack(fill=tk.BOTH, expand=True)
        self.details_text.configure(state="disabled")

        # -- bottom buttons --
        bottom = ttk.Frame(self.top, padding=8)
        bottom.pack(fill=tk.X)
        ttk.Button(bottom, text="Revert selected", command=self._on_revert_selected).pack(side=tk.LEFT, padx=4)
        ttk.Button(bottom, text="Revert to this point", command=self._on_revert_to_point).pack(side=tk.LEFT, padx=4)
        ttk.Button(bottom, text="Refresh", command=self._refresh).pack(side=tk.LEFT, padx=4)
        ttk.Button(
            bottom, text="Open Data Pipeline...",
            command=self._on_open_pipeline_for_selected,
        ).pack(side=tk.LEFT, padx=4)
        ttk.Button(bottom, text="Close", command=self.top.destroy).pack(side=tk.RIGHT, padx=4)

        self._refresh()

    def _refresh(self):
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        if self.app._meta is None:
            return
        rows, pending_count, saved_count = filter_meta_events(
            list(self.app._meta.events_reverse()),
            op_labels=self._OP_LABELS,
            op_filter=self.op_filter_var.get(),
            src_filter=self.source_filter_var.get(),
            status_filter=self.status_filter_var.get(),
            committed_filter=self.committed_filter_var.get(),
            search=self.search_var.get(),
        )
        for row in rows:
            self.tree.insert(
                "", tk.END,
                iid=row["iid"],
                values=row["values"],
                tags=row["tags"],
            )
        dirty = getattr(self.app.hpd, "has_changes", False)
        self.top.title(
            (
                f"Changes - {os.path.basename(self.app.hpd.filepath)}"
                if self.app.hpd.filepath
                else "Changes"
            )
            + (
                f"  [{pending_count} pending, {saved_count} saved"
                + (" * unsaved" if dirty else "")
                + "]"
            )
        )
        self._refresh_details()

    def _refresh_details(self):
        self.details_text.configure(state="normal")
        self.details_text.delete("1.0", tk.END)
        sel = self.tree.selection()
        if not sel or self.app._meta is None:
            self.details_text.configure(state="disabled")
            return
        event = self.app._meta.get_event(sel[0])
        if event is None:
            self.details_text.configure(state="disabled")
            return
        import json as _json
        commit_line = (
            f"Saved:  yes (at {event.committed_at})"
            if event.committed
            else "Saved:  pending (not yet written to HPD)"
        )
        txt = (
            f"Event: {event.event_id}  (txn {event.txn_id})\n"
            f"Op:    {event.op}\n"
            f"Target: {event.target_name or event.target_id}\n"
            f"Time:   {event.ts}\n"
            f"Source: {event.source}\n"
            f"Status: {'reverted' if event.reverted else 'active'}\n"
            f"{commit_line}\n"
            f"Summary: {event.summary}\n"
            f"----\n"
            f"{_json.dumps(event.payload, indent=2, default=str)}"
        )
        self.details_text.insert("1.0", txt)
        self.details_text.configure(state="disabled")

    def _selected_events(self) -> List[Event]:
        if self.app._meta is None:
            return []
        result: List[Event] = []
        for iid in self.tree.selection():
            ev = self.app._meta.get_event(iid)
            if ev is not None:
                result.append(ev)
        return result

    def _on_open_pipeline_for_selected(self) -> None:
        """Deep-link into the Data Pipeline dialog for the selected
        event. Primarily useful for ``OP_EXTERNAL_CHANGE`` rows (the
        card-side changes introduced by Uniden's tools), where the user
        wants to see which tool ran and when the workspace last synced."""
        self.app._on_open_data_pipeline()

    def _on_revert_selected(self):
        events = self._selected_events()
        if not events:
            messagebox.showinfo("Revert", "Select one or more changes.", parent=self.top)
            return
        events.sort(key=lambda e: e.ts, reverse=True)
        messages: List[str] = []
        for event in events:
            ok, msg = self.app.revert_event(event)
            if not ok and "cascade" in msg.lower():
                choice = messagebox.askyesnocancel(
                    "Later changes exist",
                    f"#{event.event_id} ({event.op}) has later changes on the same target.\n\n"
                    f"{msg}\n\n"
                    "Yes = Revert the whole chain (cascade)\n"
                    "No = Force revert this one only (may leave inconsistent state)\n"
                    "Cancel = Skip",
                    parent=self.top,
                )
                if choice is None:
                    messages.append(f"#{event.event_id}: skipped")
                    continue
                if choice:
                    ok, msg = self.app.revert_cascade(event)
                else:
                    ok, msg = self.app.revert_event(event, force=True)
            messages.append(f"#{event.event_id}: {msg}")
        self.app._refresh_ui_after_mutation(
            status_msg="Reverted change(s); save to write to SD card."
        )
        self._refresh()
        messagebox.showinfo(
            "Revert Result",
            "\n".join(messages[:20]) + (
                f"\n... ({len(messages) - 20} more)" if len(messages) > 20 else ""
            ),
            parent=self.top,
        )

    def _on_revert_to_point(self):
        events = self._selected_events()
        if len(events) != 1:
            messagebox.showinfo(
                _LIT_REVERT_TO_POINT,
                "Select exactly one change. Everything AFTER it will be reverted.",
                parent=self.top,
            )
            return
        pivot = events[0]
        if not messagebox.askyesno(
            "Revert to this point",
            f"Revert every change made AFTER #{pivot.event_id} "
            f"({pivot.ts} - {pivot.summary})?\n\n"
            "Changes will be reverted newest-first as one batch.",
            parent=self.top,
        ):
            return
        _, msg = self.app.revert_to_point(pivot.event_id)
        self.app._refresh_ui_after_mutation(
            status_msg="Reverted to point; save to write to SD card."
        )
        self._refresh()
        messagebox.showinfo(_LIT_REVERT_TO_POINT, msg, parent=self.top)


class CityManagerDialog:
    """Dialog for listing/editing firmware and custom city locations."""

    def __init__(self, app: "ScannerManagerApp"):
        self.app = app
        self.top = tk.Toplevel(app.root)
        self.top.title("Cities")
        self.top.transient(app.root)
        self.top.geometry("620x480")

        state_id = app._get_selected_state_id()
        default_abbrev = ""
        if state_id is not None:
            _, default_abbrev = app.config.states.get(state_id, ("", ""))

        filter_frame = ttk.Frame(self.top, padding=8)
        filter_frame.pack(fill=tk.X)
        ttk.Label(filter_frame, text="State:").pack(side=tk.LEFT)
        self.state_var = tk.StringVar(value=default_abbrev)
        ttk.Entry(filter_frame, textvariable=self.state_var, width=6).pack(side=tk.LEFT, padx=(4, 8))
        ttk.Button(filter_frame, text="Refresh", command=self._refresh).pack(side=tk.LEFT)
        firmware_state = "loaded" if app._firmware_city_table.is_loaded() else "not loaded"
        ttk.Label(filter_frame, text=f"Firmware CityTable: {firmware_state}").pack(side=tk.LEFT, padx=(12, 0))

        list_frame = ttk.Frame(self.top)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)
        columns = ("source", "state", "name", "lat", "lon")
        self.tree = ttk.Treeview(list_frame, columns=columns, show="headings", selectmode="browse")
        self.tree.heading("source", text="Source")
        self.tree.heading("state", text="ST")
        self.tree.heading("name", text="Name / City ID")
        self.tree.heading("lat", text="Lat")
        self.tree.heading("lon", text="Lon")
        self.tree.column("source", width=80)
        self.tree.column("state", width=40)
        self.tree.column("name", width=240)
        self.tree.column("lat", width=80)
        self.tree.column("lon", width=80)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.tree.yview)
        sb.pack(side=tk.LEFT, fill=tk.Y)
        self.tree.configure(yscrollcommand=sb.set)

        add_frame = ttk.LabelFrame(self.top, text="Add Custom Location", padding=8)
        add_frame.pack(fill=tk.X, padx=8, pady=4)
        self.new_name = tk.StringVar()
        self.new_lat = tk.StringVar()
        self.new_lon = tk.StringVar()
        ttk.Label(add_frame, text=_LIT_NAME_COLON).grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(add_frame, textvariable=self.new_name, width=24).grid(row=0, column=1, padx=4)
        ttk.Label(add_frame, text="Lat:").grid(row=0, column=2, sticky=tk.W)
        ttk.Entry(add_frame, textvariable=self.new_lat, width=10).grid(row=0, column=3, padx=4)
        ttk.Label(add_frame, text="Lon:").grid(row=0, column=4, sticky=tk.W)
        ttk.Entry(add_frame, textvariable=self.new_lon, width=10).grid(row=0, column=5, padx=4)
        ttk.Button(add_frame, text="Add", command=self._on_add).grid(row=0, column=6, padx=4)
        ttk.Button(add_frame, text="Delete Selected", command=self._on_delete).grid(row=0, column=7, padx=4)

        export_frame = ttk.Frame(self.top, padding=8)
        export_frame.pack(fill=tk.X)
        ttk.Button(
            export_frame, text="Export patched CityTable.dat",
            command=self._on_export_city_table,
        ).pack(side=tk.LEFT)
        ttk.Label(
            export_frame,
            text=(
                "Export writes to CityTable_V1_00_00.custom.dat by default. "
                "Uniden updater may overwrite edits."
            ),
            foreground="#666666",
        ).pack(side=tk.LEFT, padx=(8, 0))

        close_frame = ttk.Frame(self.top)
        close_frame.pack(fill=tk.X, pady=(4, 8))
        ttk.Button(close_frame, text="Close", command=self.top.destroy).pack(side=tk.RIGHT, padx=8)

        self._refresh()

    def _current_state_abbrev(self) -> str:
        return (self.state_var.get() or "").strip().upper()

    def _current_state_id(self) -> Optional[int]:
        abbrev = self._current_state_abbrev()
        if not abbrev:
            return None
        for sid, (_, sabbrev) in self.app.config.states.items():
            if sabbrev.upper() == abbrev:
                return sid
        return None

    def _refresh(self):
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        abbrev = self._current_state_abbrev()
        state_id = self._current_state_id()
        firmware_records = self.app._firmware_city_table.by_state.get(abbrev, []) if abbrev else []
        for rec in firmware_records[:2000]:
            self.tree.insert(
                "", tk.END,
                values=("firmware", rec.state_abbrev, f"city_id={rec.city_id}", f"{rec.lat:.4f}", f"{rec.lon:.4f}"),
            )
        for loc in self.app._custom_locations.locations:
            if state_id is None or loc["state_id"] == state_id:
                self.tree.insert(
                    "", tk.END,
                    values=("custom", self._abbrev_for_state_id(loc["state_id"]), loc["name"], f"{loc['lat']:.4f}", f"{loc['lon']:.4f}"),
                )

    def _abbrev_for_state_id(self, state_id: int) -> str:
        _, abbrev = self.app.config.states.get(state_id, ("", ""))
        return abbrev

    def _on_add(self):
        name = self.new_name.get().strip()
        if not name:
            messagebox.showwarning("Add", "Enter a name.")
            return
        state_id = self._current_state_id()
        if state_id is None:
            messagebox.showwarning("Add", "Set a valid state abbreviation first.")
            return
        try:
            lat = float(self.new_lat.get())
            lon = float(self.new_lon.get())
        except ValueError:
            messagebox.showwarning("Add", "Lat/Lon must be numeric.")
            return
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            messagebox.showwarning("Add", "Lat/Lon out of range.")
            return
        self.app._custom_locations.add(name, state_id, lat, lon)
        self.new_name.set("")
        self.new_lat.set("")
        self.new_lon.set("")
        self._refresh()

    def _on_delete(self):
        sel = self.tree.selection()
        if not sel:
            return
        values = self.tree.item(sel[0], "values")
        if not values or values[0] != "custom":
            messagebox.showinfo("Delete", "Only custom locations can be deleted here.")
            return
        name = values[2]
        state_abbrev = values[1]
        state_id = None
        for sid, (_, sabbrev) in self.app.config.states.items():
            if sabbrev.upper() == state_abbrev:
                state_id = sid
                break
        if state_id is None:
            return
        self.app._custom_locations.remove(name, state_id)
        self._refresh()

    def _on_export_city_table(self):
        if not self.app._firmware_city_table.is_loaded():
            messagebox.showerror("Export", "Firmware CityTable not loaded.")
            return
        if not messagebox.askyesno(
            "Export CityTable",
            "This will write a patched CityTable.dat that includes your custom locations. "
            "A backup of the original will be created. "
            "Uniden's updater may overwrite edits on next refresh. Continue?",
        ):
            return
        original_path = self.app._firmware_city_table.source_path
        if original_path is None:
            messagebox.showerror("Export", "Cannot determine source path.")
            return
        default_target = original_path.with_name(original_path.stem + ".custom.dat")
        overwrite = messagebox.askyesno(
            "Export CityTable",
            f"Overwrite original CityTable at:\n{original_path}\n\n"
            f"Click Yes to overwrite (backup will be created).\n"
            f"Click No to write to:\n{default_target}",
        )
        target_path = original_path if overwrite else default_target
        extras = build_custom_city_records(
            self.app._custom_locations.locations,
            self._abbrev_for_state_id,
        )
        try:
            written = self.app._firmware_city_table.export_patched(
                target_path, extras, make_backup=overwrite
            )
        except Exception as exc:
            messagebox.showerror("Export", f"Could not export CityTable:\n{exc}")
            return
        messagebox.showinfo("Export", f"Wrote patched CityTable to:\n{written}")


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

def _crash_log_dir() -> Path:
    """Directory where the global exception hook writes crash logs.

    Honors ``%LOCALAPPDATA%`` on Windows and falls back to the user's
    home directory on other platforms. A ``SCANNER_MANAGER_LOG_DIR``
    environment override is honored by tests.
    """
    override = os.environ.get("SCANNER_MANAGER_LOG_DIR")
    if override:
        return Path(override)
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "scanner-manager" / "logs"
    return Path.home() / ".scanner-manager" / "logs"


def _write_crash_log(exc_type, exc_value, exc_tb) -> Path:
    """Serialize an uncaught traceback + context to a timestamped log
    file and return its path. Never raises - a crash reporter that
    crashes its reporting path is worse than useless.
    """
    import traceback
    log_dir = _crash_log_dir()
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        log_dir = Path.home()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = log_dir / f"crash-{stamp}.log"
    try:
        with log_path.open("w", encoding="utf-8") as f:
            f.write(f"# {APP_NAME} v{APP_VERSION} crash log\n")
            f.write(f"# Timestamp: {datetime.now().isoformat()}\n")
            f.write(f"# Platform : {sys.platform}\n")
            f.write(f"# Python   : {sys.version.split()[0]}\n")
            f.write("\n")
            traceback.print_exception(
                exc_type, exc_value, exc_tb, file=f,
            )
    except OSError:
        pass
    return log_path


def _install_crash_hook(root: tk.Tk, _app: "ScannerManagerApp") -> None:
    """Route Tk callback exceptions through our crash-log writer and
    give the user a one-click path to file the bug report.
    """

    def handler(exc_type, exc_value, exc_tb):
        log_path = _write_crash_log(exc_type, exc_value, exc_tb)
        try:
            if not messagebox.askyesno(
                "Unexpected error",
                (
                    f"{APP_NAME} hit an unexpected error and saved a crash "
                    f"log to:\n\n{log_path}\n\n"
                    "Open the GitHub issue form with these details "
                    "pre-filled? (You can attach the log file.)"
                ),
                parent=root,
            ):
                return
        except Exception:
            return
        import traceback
        tb_text = "".join(
            traceback.format_exception(exc_type, exc_value, exc_tb)
        )[-1200:]
        title = urllib.parse.quote(
            f"[{APP_VERSION}] {exc_type.__name__}: {exc_value}"
        )
        body = urllib.parse.quote(
            "### What happened?\n(please describe what you were doing)\n\n"
            "### Environment\n"
            f"- {APP_NAME}: v{APP_VERSION}\n"
            f"- OS: {sys.platform}\n"
            f"- Python: {sys.version.split()[0]}\n"
            f"- Log file: `{log_path}`\n\n"
            "### Traceback\n"
            f"```\n{tb_text}\n```\n"
        )
        webbrowser.open(f"{APP_ISSUES_URL}/new?title={title}&body={body}")

    root.report_callback_exception = handler


def main():
    root = tk.Tk()
    app = ScannerManagerApp(root)
    _install_crash_hook(root, app)

    def on_close():
        if app.hpd.has_changes and not messagebox.askyesno(
            "Unsaved Changes", "You have unsaved changes. Quit anyway?"
        ):
            return
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
