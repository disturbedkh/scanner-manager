"""Pure helpers extracted from legacy_tk/scanner_manager (Sonar S3776)."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Set, Tuple

if TYPE_CHECKING:
    from core.hpd import FreqEntry, GroupNode, SystemNode

# Tree tag names for group coverage status
_GROUP_COVERAGE_TAGS = {
    "in_range": "group_in_range",
    "nearby": "group_nearby",
    "out_range": "group_out_range",
    "no_geo": "group_no_geo",
}


def resolve_script_dir(repo_root_fn: Callable[[], Path]) -> Path:
    """Writable app state directory (EXE dir when frozen, else repo root)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return repo_root_fn()


def find_hpdb_config(folder: str) -> Optional[str]:
    """Return path to hpdb.cfg under ``folder``, or None if missing."""
    cfg = os.path.join(folder, "HPDB", "hpdb.cfg")
    if os.path.exists(cfg):
        return cfg
    cfg2 = os.path.join(folder, "hpdb.cfg")
    if os.path.exists(cfg2):
        return cfg2
    return None


def default_state_combo_index(state_id_list: List[int]) -> Optional[int]:
    """Prefer Florida (state id 12) when present."""
    for i, sid in enumerate(state_id_list):
        if sid == 12:
            return i
    return 0 if state_id_list else None


def apply_sync_conflict_decision(
    rel: str,
    decision: str,
    *,
    card_root: str,
    workspace_dir: str,
) -> Optional[str]:
    """Copy one conflict file per user decision. Returns error text or None."""
    if decision == "take_card":
        try:
            src = Path(card_root) / rel
            dst = Path(workspace_dir) / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        except Exception as exc:
            return f"Could not take card copy of {rel}: {exc}"
    elif decision == "take_workspace":
        try:
            src = Path(workspace_dir) / rel
            dst = Path(card_root) / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        except Exception as exc:
            return f"Could not push workspace copy of {rel}: {exc}"
    return None


def sync_result_summary(direction: str, report: Any) -> str:
    return (
        f"Sync {direction}: {len(report.copied)} copied, "
        f"{len(report.skipped_same)} unchanged, "
        f"{len(report.conflicts)} conflict(s), "
        f"{len(report.external_changes)} external change(s)."
    )


def group_coverage_tree_tag(status: str) -> str:
    return _GROUP_COVERAGE_TAGS.get(status, "group")


def system_tree_label(
    sys_node: "SystemNode",
    *,
    apply_location: bool,
    ranking_on: bool,
    rank: int,
    distance: Optional[float],
    scope_label_fn: Callable[["SystemNode"], str],
) -> str:
    sys_prefix = "CONV" if sys_node.system_type == "Conventional" else "TRUNK"
    rank_prefix = f"#{rank + 1} " if ranking_on else ""
    if apply_location:
        scope = scope_label_fn(sys_node)
        if distance is not None:
            return (
                f"{rank_prefix}[{scope}][{sys_prefix}] "
                f"{sys_node.name} ({distance:.1f} mi)"
            )
        return f"{rank_prefix}[{scope}][{sys_prefix}] {sys_node.name}"
    return f"[{sys_prefix}] {sys_node.name}"


def group_tree_label(
    group: "GroupNode",
    info: Dict[str, Any],
    *,
    apply_location: bool,
    has_active_coords: bool,
) -> str:
    if apply_location and has_active_coords and info.get("has_geo"):
        dist = info.get("distance")
        rng = info.get("range_miles")
        if dist is not None and rng is not None:
            return f"{group.name}  [{dist:.1f} mi / {rng:.1f} mi range]"
        if dist is not None:
            return f"{group.name}  [{dist:.1f} mi]"
    return group.name


def entry_identity_display(entry: "FreqEntry", parse_int_fn: Callable[[str, str], int]) -> Tuple[str, str, str]:
    """Return (identity, mode, tone) strings for scan-set export."""
    rec = entry.record
    if entry.entry_type == "C-Freq":
        freq_hz = parse_int_fn(rec.get_field(5, "0"))
        identity = f"{freq_hz / 1_000_000:.4f} MHz" if freq_hz else ""
        return identity, rec.get_field(6, ""), rec.get_field(7, "")
    if entry.entry_type == "TGID":
        return f"TGID {rec.get_field(5, '')}", rec.get_field(6, ""), ""
    return "", "", ""


def format_vsd_profile_lines(profile: Optional[Dict[str, Any]]) -> List[str]:
    if profile is None:
        return ["No workspace profile is active."]
    return [
        f"Active profile: {profile.get('name') or profile.get('profile_id')}",
        f"Workspace: {profile.get('workspace_dir') or ''}",
        f"Last sync: {profile.get('last_sync_at') or 'never'}",
    ]


def format_vsd_card_line(card: Dict[str, Any]) -> str:
    if card.get("connected"):
        model = card.get("target_model") or "unknown"
        return f"connected ({model})"
    return "detached"


def format_vsd_section(info: Dict[str, Any]) -> str:
    lines = format_vsd_profile_lines(info.get("profile"))
    pending = info.get("pending_events")
    if pending is not None:
        lines.append(f"Pending (uncommitted) events: {pending}")
    card = info.get("card") or {}
    lines.append(f"Card: {format_vsd_card_line(card)}")
    return "\n".join(lines)


def rr_diff_mode(group: "GroupNode", parsed: Optional[Dict[str, Any]]) -> str:
    is_trunked = any(e.entry_type == "TGID" for e in group.entries)
    if is_trunked or (parsed and parsed.get("kind") == "trs"):
        return "tgid"
    return "cfreq"


def local_cfreq_by_hz(group: "GroupNode") -> Dict[int, "FreqEntry"]:
    out: Dict[int, FreqEntry] = {}
    for entry in group.entries:
        if entry.entry_type != "C-Freq":
            continue
        try:
            out[int(entry.record.get_field(5, ""))] = entry
        except ValueError:
            continue
    return out


def local_tgid_by_id(group: "GroupNode") -> Dict[int, "FreqEntry"]:
    out: Dict[int, FreqEntry] = {}
    for entry in group.entries:
        if entry.entry_type != "TGID":
            continue
        try:
            out[int(entry.record.get_field(5, ""))] = entry
        except ValueError:
            continue
    return out


def flatten_rr_cfreq_rows(parsed: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not parsed:
        return []
    rows: List[Dict[str, Any]] = []
    if parsed.get("frequencies"):
        rows.extend(parsed["frequencies"])
    for cat in parsed.get("categories") or []:
        for freq in cat.get("frequencies") or []:
            rows.append(freq)
    return rows


def flatten_rr_tg_rows(parsed: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not parsed:
        return []
    rows: List[Dict[str, Any]] = []
    for cat in parsed.get("categories") or []:
        for tg in cat.get("talkgroups") or []:
            rows.append(tg)
    return rows


def changes_detail(changes: Dict[str, Tuple[Any, Any]]) -> str:
    return ", ".join(
        f"{k}: {changes[k][0]!r}->{changes[k][1]!r}" for k in sorted(changes)
    )


BAND_MODE_RULES: List[Tuple[float, float, str, Set[str]]] = [
    (25_000_000, 54_000_000, "FM", {"FM", "NFM"}),
    (108_000_000, 137_000_000, "AM", {"AM"}),
    (137_000_000, 174_000_000, "NFM", {"FM", "NFM"}),
    (216_000_000, 225_000_000, "NFM", {"FM", "NFM"}),
    (406_000_000, 420_000_000, "NFM", {"FM", "NFM"}),
    (450_000_000, 470_000_000, "NFM", {"FM", "NFM"}),
    (470_000_000, 512_000_000, "NFM", {"FM", "NFM"}),
    (758_000_000, 824_000_000, "NFM", {"FM", "NFM"}),
    (849_000_000, 869_000_000, "NFM", {"FM", "NFM"}),
    (894_000_000, 960_000_000, "NFM", {"FM", "NFM"}),
]


def suggest_mode_for_freq(freq_hz: int) -> Optional[str]:
    for lo, hi, suggested, _ in BAND_MODE_RULES:
        if lo <= freq_hz <= hi:
            return suggested
    return None


def audit_mode_issues(entry: "FreqEntry") -> Optional[Tuple[str, str]]:
    """Return (issue, suggested_mode) when the entry has a mode/band problem."""
    if entry.entry_type != "C-Freq":
        return None
    rec = entry.record
    try:
        freq_hz = int(rec.get_field(5, "0"))
    except ValueError:
        return None
    if freq_hz <= 0:
        return None
    mode = rec.get_field(6, "").upper()
    suggested = suggest_mode_for_freq(freq_hz)
    if suggested is None:
        return None
    if mode == "AUTO":
        return ("AUTO mode where explicit mode is preferred", suggested)
    allowed = next(
        (allowed for lo, hi, _, allowed in BAND_MODE_RULES if lo <= freq_hz <= hi),
        set(),
    )
    if mode and allowed and mode not in allowed:
        return (f"Mode '{mode}' invalid for {freq_hz / 1_000_000:.4f} MHz", suggested)
    return None


def _rr_mode_audit(
    freq_hz: int,
    mode: str,
    rr: Dict[str, Any],
) -> Optional[Tuple[str, str, str]]:
    rr_mode = (rr.get("mode") or "").upper()
    if not rr_mode:
        return None
    if rr_mode == mode:
        return None
    if rr_mode not in {"FM", "NFM", "AM", "AUTO"}:
        return None
    rr_desc = rr.get("name") or f"{freq_hz / 1_000_000:.4f} MHz"
    return (
        f"RR lists mode '{rr_mode}' for {rr_desc}; HPD has '{mode or 'blank'}'",
        rr_mode,
        "rr",
    )


def audit_mode_issue_with_rr(
    entry: "FreqEntry",
    rr_ref: Dict[int, Dict[str, Any]],
) -> Optional[Tuple[str, str, str]]:
    """Flag mode issues using RR reference data and band rules."""
    if entry.entry_type != "C-Freq":
        return None
    rec = entry.record
    try:
        freq_hz = int(rec.get_field(5, "0"))
    except ValueError:
        return None
    if freq_hz <= 0:
        return None
    mode = rec.get_field(6, "").upper()
    rr = rr_ref.get(freq_hz)
    if rr is not None:
        rr_issue = _rr_mode_audit(freq_hz, mode, rr)
        if rr_issue is not None:
            return rr_issue
    band_issue = audit_mode_issues(entry)
    if band_issue is not None:
        issue, suggested = band_issue
        return (issue, suggested, "band")
    return None


def entry_matches_bulk_filter(
    entry: "FreqEntry",
    entry_types: Set[str],
    service_types: Optional[Set[int]],
    county_id: Optional[int],
    system_id: Optional[str],
) -> bool:
    """Generic predicate for bulk operations."""
    if entry_types and entry.entry_type not in entry_types:
        return False
    if service_types is not None and entry.service_type not in service_types:
        return False
    if system_id is not None and entry.system_id != system_id:
        return False
    if county_id is None:
        return True
    system_county = entry.system_id if entry.system_id and entry.system_type == "Conventional" else None
    return system_county == str(county_id)


def entry_passes_button_filter(
    service_type: int,
    active_button_types: Set[int],
    include_others: bool,
) -> bool:
    """Return True if an entry with this service type matches button filters."""
    if service_type in active_button_types:
        return True
    from scanner_profiles import get_active_profile

    scannable = get_active_profile().scannable_service_types()
    if service_type in scannable and service_type not in active_button_types:
        return False
    return bool(include_others)
