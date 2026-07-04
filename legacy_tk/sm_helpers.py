"""Pure helpers extracted from legacy_tk/scanner_manager (Sonar S3776)."""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
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


def filter_rr_import_changes(
    raw: Dict[str, Tuple[Any, Any]],
    *,
    update_mode: bool,
    update_name: bool,
    update_tone: bool = False,
    update_service: bool,
) -> Dict[str, Tuple[Any, Any]]:
    result: Dict[str, Tuple[Any, Any]] = {}
    if update_mode and "mode" in raw:
        result["mode"] = raw["mode"]
    if update_tone and "tone" in raw:
        result["tone"] = raw["tone"]
    if update_name and "name" in raw:
        result["name"] = raw["name"]
    if update_service and "service_type" in raw:
        result["service_type"] = raw["service_type"]
    return result


def cfreq_import_row_display(
    action: str,
    changes: Dict[str, Tuple[Any, Any]],
) -> Tuple[str, bool, Tuple[str, ...]]:
    if action == "new":
        return "New", True, ()
    if action == "update":
        change_text = changes_detail(changes)
        return f"Update ({change_text})", True, ("update_available",)
    return "Same (skip)", False, ("same",)


def tg_import_row_display(
    action: str,
    changes: Dict[str, Tuple[Any, Any]],
) -> Tuple[str, bool, Tuple[str, ...]]:
    if action == "new":
        return "New", True, ()
    if action == "update":
        return f"Update ({changes_detail(changes)})", True, ("update_available",)
    if action == "same":
        return "Same (skip)", False, ("same",)
    if action == "delete_encrypted":
        return "Encrypted - DELETE", True, ("encrypted_action",)
    if action == "same_encrypted":
        return "Encrypted (skip, leave as-is)", False, ("encrypted",)
    return "Encrypted (skip)", False, ("encrypted",)


def apply_rr_crossref_tags(
    row_tags: Tuple[str, ...],
    hint: Optional[Dict[str, Any]],
    counts: Dict[str, int],
) -> Tuple[str, ...]:
    if hint is None:
        return row_tags
    kind = hint.get("kind")
    if kind == "callsign":
        counts["callsign"] = counts.get("callsign", 0) + 1
        return row_tags + ("crossref_callsign",)
    if kind == "fuzzy":
        counts["fuzzy"] = counts.get("fuzzy", 0) + 1
        return row_tags + ("crossref_fuzzy",)
    return row_tags


def compute_cfreq_import_row(
    freq: Dict[str, Any],
    freq_hz: int,
    existing: Optional["FreqEntry"],
    cat_name: str,
    *,
    filter_changes: Callable[[Dict[str, Tuple[Any, Any]]], Dict[str, Tuple[Any, Any]]],
    diff_fn: Callable[..., Dict[str, Tuple[Any, Any]]],
    target_group_fn: Callable[["FreqEntry"], str],
    crossref_hint: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    service = freq.get("suggested_service_type")
    raw_changes: Dict[str, Tuple[Any, Any]] = {}
    changes: Dict[str, Tuple[Any, Any]] = {}
    action = "new"
    if existing is not None:
        raw_changes = diff_fn(
            existing.name,
            existing.record.get_field(6, ""),
            existing.record.get_field(7, ""),
            existing.service_type,
            freq.get("name") or freq.get("alpha") or "",
            freq.get("mode") or "",
            freq.get("tone") or "",
            service if isinstance(service, int) else None,
        )
        changes = filter_changes(raw_changes)
        action = "update" if changes else "same"
    action_text, checked, row_tags = cfreq_import_row_display(action, changes)
    target_group = target_group_fn(existing) if existing is not None else cat_name
    crossref_text = hint["label"] if (hint := crossref_hint) else ""
    return {
        "action": action,
        "action_text": action_text,
        "checked": checked,
        "row_tags": row_tags,
        "raw_changes": raw_changes,
        "changes": changes,
        "target_group": target_group,
        "crossref_text": crossref_text,
        "crossref": hint,
        "service": service,
    }


def compute_tg_import_row(
    tg: Dict[str, Any],
    existing: Optional["FreqEntry"],
    *,
    filter_changes: Callable[[Dict[str, Tuple[Any, Any]]], Dict[str, Tuple[Any, Any]]],
    diff_fn: Callable[..., Dict[str, Tuple[Any, Any]]],
    classify_fn: Callable[..., str],
    encrypted_policy: str,
    include_encrypted: bool,
    crossref_hint: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    service = tg.get("suggested_service_type")
    raw_changes: Dict[str, Tuple[Any, Any]] = {}
    changes: Dict[str, Tuple[Any, Any]] = {}
    if existing is not None:
        raw_changes = diff_fn(
            existing.name,
            existing.record.get_field(6, ""),
            existing.service_type,
            tg.get("name") or tg.get("alpha") or "",
            tg.get("mode") or "",
            service if isinstance(service, int) else None,
        )
        changes = filter_changes(raw_changes)
    action = classify_fn(
        is_encrypted=bool(tg.get("encrypted")),
        has_existing=existing is not None,
        has_update_diff=bool(changes),
        encrypted_policy=encrypted_policy,
        include_encrypted=include_encrypted,
    )
    action_text, checked, row_tags = tg_import_row_display(action, changes)
    crossref_text = hint["label"] if (hint := crossref_hint) else ""
    return {
        "action": action,
        "action_text": action_text,
        "checked": checked,
        "row_tags": row_tags,
        "raw_changes": raw_changes,
        "changes": changes,
        "crossref_text": crossref_text,
        "crossref": hint,
        "service": service,
    }


def summarize_cfreq_import_rows(
    item_meta: Dict[str, Dict[str, Any]],
    crossref_counts: Dict[str, int],
) -> str:
    total = 0
    new_sel = 0
    update_sel = 0
    updates_available = 0
    for meta in item_meta.values():
        if meta.get("type") != "cfreq":
            continue
        total += 1
        if meta.get("action") == "update":
            updates_available += 1
        if meta.get("checked"):
            if meta.get("action") == "new":
                new_sel += 1
            elif meta.get("action") == "update":
                update_sel += 1
    extra = ""
    if crossref_counts.get("callsign") or crossref_counts.get("fuzzy"):
        extra = (
            f"   |  xref: {crossref_counts.get('callsign', 0)} callsign, "
            f"{crossref_counts.get('fuzzy', 0)} fuzzy"
        )
    return (
        f"{total} frequencies; {new_sel} new, {update_sel}/{updates_available} updates"
        + extra
    )


def summarize_tg_import_rows(
    item_meta: Dict[str, Dict[str, Any]],
    crossref_counts: Dict[str, int],
) -> str:
    total = 0
    new_sel = 0
    update_sel = 0
    delete_sel = 0
    encrypted = 0
    updates_available = 0
    for meta in item_meta.values():
        if meta.get("type") != "tg":
            continue
        total += 1
        if meta["data"].get("encrypted"):
            encrypted += 1
        if meta.get("action") == "update":
            updates_available += 1
        if meta.get("checked"):
            action = meta.get("action")
            if action == "new":
                new_sel += 1
            elif action == "update":
                update_sel += 1
            elif action == "delete_encrypted":
                delete_sel += 1
    extra = ""
    if crossref_counts.get("callsign") or crossref_counts.get("fuzzy"):
        extra = (
            f"   |  xref: {crossref_counts.get('callsign', 0)} callsign, "
            f"{crossref_counts.get('fuzzy', 0)} fuzzy"
        )
    return (
        f"{total} talkgroups; {new_sel} new, {update_sel}/{updates_available} updates, "
        f"{delete_sel} delete-encrypted, "
        f"{encrypted} total encrypted"
        + extra
    )


def gather_cfreq_import_selection(
    item_meta: Dict[str, Dict[str, Any]],
    cat_ids: List[str],
    cat_name_fn: Callable[[str], str],
) -> Tuple[List[Tuple[str, List[Dict[str, Any]]]], int, int]:
    selection: List[Tuple[str, List[Dict[str, Any]]]] = []
    new_count = 0
    update_count = 0
    for cat_id in cat_ids:
        cat_name = cat_name_fn(cat_id)
        items: List[Dict[str, Any]] = []
        for _iid, meta in item_meta.items():
            if meta.get("type") != "cfreq" or meta.get("parent") != cat_id:
                continue
            if not meta.get("checked"):
                continue
            action = meta.get("action")
            if action not in ("new", "update"):
                continue
            payload = dict(meta["data"])
            payload["__action__"] = action
            payload["__changes__"] = meta.get("changes", {})
            payload["__existing__"] = meta.get("existing")
            payload["__freq_hz__"] = meta.get("freq_hz")
            items.append(payload)
            if action == "new":
                new_count += 1
            elif action == "update":
                update_count += 1
        if items:
            selection.append((cat_name, items))
    return selection, new_count, update_count


def gather_tg_import_selection(
    item_meta: Dict[str, Dict[str, Any]],
    cat_ids: List[str],
    cat_name_fn: Callable[[str], str],
) -> Tuple[List[Tuple[str, List[Dict[str, Any]]]], int, int, int]:
    selection: List[Tuple[str, List[Dict[str, Any]]]] = []
    new_count = 0
    update_count = 0
    delete_count = 0
    for cat_id in cat_ids:
        cat_name = cat_name_fn(cat_id)
        items: List[Dict[str, Any]] = []
        for _iid, meta in item_meta.items():
            if meta.get("type") != "tg" or meta.get("parent") != cat_id:
                continue
            if not meta.get("checked"):
                continue
            action = meta.get("action")
            if action not in ("new", "update", "delete_encrypted"):
                continue
            payload = dict(meta["data"])
            payload["__action__"] = action
            payload["__changes__"] = meta.get("changes", {})
            payload["__existing__"] = meta.get("existing")
            items.append(payload)
            if action == "new":
                new_count += 1
            elif action == "update":
                update_count += 1
            elif action == "delete_encrypted":
                delete_count += 1
        if items:
            selection.append((cat_name, items))
    return selection, new_count, update_count, delete_count


def tg_import_confirm_prompt(
    new_count: int,
    update_count: int,
    delete_count: int,
    system_name: str,
) -> str:
    summary_parts = []
    if new_count:
        summary_parts.append(f"{new_count} new")
    if update_count:
        summary_parts.append(f"{update_count} updates")
    if delete_count:
        summary_parts.append(f"{delete_count} DELETE encrypted")
    prompt = (
        "Proceed with:\n  " + "\n  ".join(summary_parts)
        + f"\nunder '{system_name}'?"
    )
    if delete_count:
        prompt += "\n\nDeletion is permanent once you Save."
    return prompt


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


def append_rr_candidate(
    candidates: List[Dict[str, Any]],
    seen: Set[str],
    url: str,
    source: str,
    confidence: float,
    detail: str,
) -> None:
    if not url or url in seen:
        return
    seen.add(url)
    candidates.append(
        {"url": url, "source": source, "confidence": confidence, "detail": detail}
    )


def rr_callsign_urls(callsigns: Set[str]) -> List[Tuple[str, str, float, str]]:
    rows: List[Tuple[str, str, float, str]] = []
    for cs in callsigns:
        rows.append(
            (
                f"https://www.radioreference.com/db/fcc/callsign/{cs}",
                "callsign",
                0.9,
                f"Derived from FCC callsign {cs}",
            )
        )
    return rows


def rr_recent_url_candidates(
    probe_name: str,
    recent_urls: List[str],
    seen: Set[str],
    tokenize: Callable[[str], List[str]],
) -> List[Tuple[str, str, float, str]]:
    if not probe_name:
        return []
    probe_tokens = set(tokenize(probe_name))
    if not probe_tokens:
        return []
    rows: List[Tuple[str, str, float, str]] = []
    for url in recent_urls[-50:]:
        if not url or url in seen:
            continue
        url_tokens = set(tokenize(url))
        if not url_tokens:
            continue
        inter = len(probe_tokens & url_tokens)
        if inter == 0:
            continue
        score = inter / len(probe_tokens | url_tokens)
        if score >= 0.25:
            rows.append(
                (url, "recent-url", 0.4 + 0.3 * score, f"Recent URL match (tok score {score:.2f})")
            )
    return rows


def sort_rr_candidates(
    candidates: List[Dict[str, Any]], *, limit: int = 25
) -> List[Dict[str, Any]]:
    candidates.sort(key=lambda c: c["confidence"], reverse=True)
    return candidates[:limit]


def parse_rr_import_freq_hz(freq: Dict[str, Any]) -> Optional[int]:
    try:
        return int(freq["__freq_hz__"])
    except Exception:
        try:
            return int(round(float(freq["mhz"]) * 1_000_000))
        except Exception:
            return None


def cfreq_import_service_type(freq: Dict[str, Any]) -> int:
    stype = freq.get("suggested_service_type")
    return stype if isinstance(stype, int) else 14


def rr_fetch_display_name(parsed: Dict[str, Any], chosen: Dict[str, Any]) -> str:
    name = parsed.get("name") or chosen.get("name") or ""
    city = chosen.get("city")
    if city and name and city.lower() not in name.lower():
        return f"{name} ({city})"
    return name


def service_choice_for_type(
    stype_guess: int, service_labels: List[str]
) -> Optional[str]:
    prefix = f"{stype_guess} "
    for label in service_labels:
        if label.startswith(prefix):
            return label
    return None


def county_mismatch_reason(
    active_county: Optional[int],
    county_choices: List[Tuple[int, str]],
    system: "SystemNode",
) -> Optional[str]:
    if not active_county or not system.county_ids:
        return None
    if active_county in system.county_ids:
        return None
    county_name = next(
        (name for cid, name in county_choices if cid == active_county),
        f"CountyId {active_county}",
    )
    return (
        f"Active county is {county_name}, but the target system '{system.name}' "
        "belongs to a different county."
    )


def geo_distance_mismatch_reason(
    active_coords: Tuple[float, float],
    group: "GroupNode",
    tolerance_miles: float,
) -> Optional[str]:
    if group.lat is None or group.lon is None:
        return None
    from legacy_tk.geo_tables import haversine_miles

    distance = haversine_miles(
        active_coords[0], active_coords[1], group.lat, group.lon
    )
    tolerance = max(tolerance_miles, group.range_miles or 0.0)
    if distance <= tolerance + 50:
        return None
    return (
        f"Group '{group.name}' is {distance:.0f} miles from the active ZIP/City. "
        "It will not likely be heard from this location."
    )


def pipeline_tools_info(tools: List[Any]) -> Dict[str, Any]:
    return {
        "rows": [
            {
                "tool_id": t.tool_id,
                "display_name": t.display_name,
                "installed": t.installed,
                "version": t.version,
            }
            for t in tools
        ],
        "any_installed": any(t.installed for t in tools),
    }


def card_identity_matches_profile(
    ident: Any, profile: Optional[Dict[str, Any]]
) -> Tuple[bool, str]:
    if profile is not None:
        connected = bool(
            (ident.volume_serial and ident.volume_serial == profile.get("card_volume_serial"))
            or (
                ident.content_fingerprint
                and ident.content_fingerprint == profile.get("content_fingerprint")
            )
        )
    else:
        connected = ident.has_any_id()
    return connected, ident.target_model or ""


def pipeline_health_color(
    *,
    tools_any_installed: bool,
    rr_api_missing: bool,
    profile: Optional[Dict[str, Any]],
    card_connected: bool,
    pending: Optional[int],
) -> str:
    if not tools_any_installed and rr_api_missing:
        return "red"
    if not tools_any_installed:
        return "amber"
    if profile is None or card_connected or pending == 0:
        return "green"
    return "amber"


def zip_lookup_status_message(
    normalized: str,
    match: Dict[str, Any],
    coords: Optional[Tuple[float, float]],
    active_county_id: Optional[int],
) -> str:
    source = match.get("source", "local")
    county_name = match.get("county_name")
    coord_text = f" @ ({coords[0]:.3f}, {coords[1]:.3f})" if coords else ""
    if active_county_id is not None:
        county_name = county_name or f"CountyId {active_county_id}"
        return (
            f"ZIP {normalized} resolved to {county_name} ({source}){coord_text}; "
            "showing effective scan set."
        )
    return (
        f"ZIP {normalized} resolved state via {source}{coord_text}; "
        "showing effective scan set by coverage."
    )


def replay_entry_type_and_identity(snap: Dict[str, Any]) -> Tuple[str, str]:
    et = (snap.get("entry_type") or "").upper()
    identity = str(snap.get("identity_value") or "").strip()
    return et, identity


# ---- Coverage / location filter (R3+R4) ------------------------------------


def compute_group_coverage_info(
    group: "GroupNode",
    active_coords: Optional[Tuple[float, float]],
    tolerance: float,
) -> Dict[str, Any]:
    from core.hpd import haversine_miles, rectangle_contains_point

    info: Dict[str, Any] = {
        "has_geo": False,
        "distance": None,
        "range_miles": group.range_miles,
        "status": "no_geo",
    }
    if active_coords is None:
        return info
    lat, lon = active_coords
    if group.rectangles and any(
        rectangle_contains_point(r, lat, lon) for r in group.rectangles
    ):
        info["has_geo"] = True
        info["status"] = "in_range"
        if group.lat is not None and group.lon is not None:
            info["distance"] = haversine_miles(lat, lon, group.lat, group.lon)
        else:
            info["distance"] = 0.0
        return info
    if group.lat is None or group.lon is None:
        return info
    info["has_geo"] = True
    d = haversine_miles(lat, lon, group.lat, group.lon)
    info["distance"] = d
    rng = group.range_miles or 0.0
    if rng > 0 and d <= rng:
        info["status"] = "in_range"
    elif rng > 0 and d <= rng + tolerance:
        info["status"] = "nearby"
    elif rng <= 0 and d <= tolerance:
        info["status"] = "nearby"
    else:
        info["status"] = "out_range"
    return info


def system_matches_location(
    sys_node: "SystemNode",
    *,
    active_coords: Optional[Tuple[float, float]],
    active_county_id: Optional[int],
    selected_state_id: Optional[int],
    tolerance: float,
) -> bool:
    from core.hpd import system_covers_point, system_has_geo

    if active_coords is not None:
        covered, delta = system_covers_point(
            sys_node, active_coords[0], active_coords[1]
        )
        if covered:
            return True
        if system_has_geo(sys_node):
            if delta != float("inf") and delta <= tolerance:
                return True
            return False
        if active_county_id and active_county_id in sys_node.county_ids:
            return True
        return not sys_node.county_ids and not sys_node.state_ids
    if active_county_id is None:
        return True
    if sys_node.county_ids:
        return active_county_id in sys_node.county_ids
    if sys_node.state_ids and selected_state_id is not None:
        return selected_state_id in sys_node.state_ids
    return True


def location_scope_label(
    sys_node: "SystemNode",
    *,
    active_coords: Optional[Tuple[float, float]],
    active_county_id: Optional[int],
    tolerance: float,
) -> str:
    from core.hpd import system_covers_point, system_has_geo

    if active_coords is not None:
        covered, delta = system_covers_point(
            sys_node, active_coords[0], active_coords[1]
        )
        if covered:
            return "COVERAGE"
        if system_has_geo(sys_node) and delta != float("inf") and delta <= tolerance:
            return "NEARBY"
    if active_county_id and active_county_id in sys_node.county_ids:
        return "LOCAL"
    if not sys_node.county_ids and sys_node.state_ids:
        return "STATEWIDE"
    if not sys_node.county_ids and not sys_node.state_ids:
        return "WIDE"
    return "OTHER"


def group_geo_strings(group: "GroupNode") -> Tuple[str, str, str]:
    lat_s = "" if group.lat is None else f"{group.lat:.6f}"
    lon_s = "" if group.lon is None else f"{group.lon:.6f}"
    range_s = "" if not group.range_miles else f"{group.range_miles:.2f}"
    return lat_s, lon_s, range_s


# ---- Metastore revert (R3) -------------------------------------------------


@dataclass
class MetastoreRevertOps:
    find_entry_by_id: Callable[[str], Optional["FreqEntry"]]
    find_group_by_key: Callable[[str], Optional["GroupNode"]]
    find_system_by_key: Callable[[str], Optional["SystemNode"]]
    apply_entry_snapshot: Callable[["FreqEntry", Dict[str, Any]], None]
    apply_group_snapshot: Callable[["GroupNode", Dict[str, Any]], None]
    edit_system_name: Callable[["SystemNode", str], None]
    delete_entry: Callable[["FreqEntry"], None]
    delete_group: Callable[["GroupNode"], None]
    update_service_type: Callable[["FreqEntry", int], None]
    reinsert_system: Callable[[Dict[str, Any]], Optional["SystemNode"]]
    reinsert_entry: Callable[[Dict[str, Any]], bool]
    reinsert_group: Callable[[Dict[str, Any]], Optional["GroupNode"]]
    revert_import: Callable[[Dict[str, Any]], Tuple[bool, str]]
    clear_group_link: Callable[[str], None]
    restore_group_link: Callable[[str, Dict[str, Any]], None]


def apply_metastore_revert(
    op: str,
    event: Any,
    payload: Dict[str, Any],
    ops: MetastoreRevertOps,
) -> Tuple[bool, str]:
    from core.metastore import (
        OP_ADD_ENTRY,
        OP_ADD_GROUP,
        OP_DELETE_ENTRY,
        OP_DELETE_GROUP,
        OP_DELETE_SYSTEM,
        OP_EDIT_ENTRY,
        OP_EDIT_GROUP,
        OP_EDIT_SYSTEM,
        OP_IMPORT_APPLY,
        OP_LINK_RR,
        OP_SET_SERVICE,
        OP_UNLINK_RR,
    )

    target_name = event.target_name
    if op == OP_EDIT_ENTRY:
        target = ops.find_entry_by_id(event.target_id)
        if target is None:
            prev = payload.get("prev_target_id")
            if prev:
                target = ops.find_entry_by_id(prev)
        if target is None:
            return False, "Could not find the entry to revert."
        ops.apply_entry_snapshot(target, payload.get("before") or {})
        return True, f"Reverted edit on {target.name}"
    if op == OP_EDIT_GROUP:
        target = ops.find_group_by_key(event.target_id)
        if target is None:
            return False, "Could not find the group to revert."
        ops.apply_group_snapshot(target, payload.get("before") or {})
        return True, f"Reverted edit on group {target.name}"
    if op == OP_EDIT_SYSTEM:
        target = ops.find_system_by_key(event.target_id)
        if target is None:
            return False, "Could not find the system to revert."
        before = payload.get("before") or {}
        prev_name = before.get("name")
        if prev_name is not None:
            ops.edit_system_name(target, str(prev_name))
        return True, f"Reverted edit on system {target.name}"
    if op == OP_DELETE_SYSTEM:
        restored = ops.reinsert_system(payload.get("system_blob") or {})
        if restored is None:
            return False, "Could not restore deleted system."
        entry_count = sum(len(g.entries) for g in restored.groups)
        return True, (
            f"Restored system {restored.name} with "
            f"{len(restored.groups)} group(s) and {entry_count} entries"
        )
    if op == OP_SET_SERVICE:
        target = ops.find_entry_by_id(event.target_id)
        if target is None:
            return False, "Could not find the entry."
        before = (payload.get("before") or {}).get("service_type")
        if before is None:
            return False, "Could not find the entry."
        ops.update_service_type(target, int(before))
        return True, f"Service type reverted on {target.name}"
    if op == OP_ADD_ENTRY:
        target = ops.find_entry_by_id(event.target_id)
        if target is None:
            return False, "Entry no longer present (already deleted)."
        ops.delete_entry(target)
        return True, f"Removed added entry {target_name}"
    if op == OP_ADD_GROUP:
        target = ops.find_group_by_key(event.target_id)
        if target is None:
            return False, "Group no longer present."
        if target.entries:
            return False, (
                f"Group {target.name} now contains {len(target.entries)} entries; "
                "refusing to auto-delete."
            )
        ops.delete_group(target)
        return True, f"Removed added group {target_name}"
    if op == OP_DELETE_ENTRY:
        if ops.reinsert_entry(payload):
            return True, f"Restored deleted entry {target_name}"
        return False, "Could not restore entry (group missing?)"
    if op == OP_DELETE_GROUP:
        grp = ops.reinsert_group(payload)
        if grp is not None:
            return True, (
                f"Restored deleted group {target_name} with {len(grp.entries)} entries"
            )
        return False, "Could not restore group (system missing?)"
    if op == OP_IMPORT_APPLY:
        return ops.revert_import(payload)
    if op == OP_LINK_RR:
        ops.clear_group_link(event.target_id)
        return True, f"Unlinked {target_name}"
    if op == OP_UNLINK_RR:
        link = payload.get("link") or {}
        if not link.get("rr_url"):
            return False, "Original link info missing."
        ops.restore_group_link(event.target_id, dict(link))
        return True, f"Restored RR link on {target_name}"
    return False, f"Don't know how to revert {op}."


def add_entry_from_snapshot(hpd: Any, group: "GroupNode", snap: Dict[str, Any]) -> bool:
    try:
        if snap.get("entry_type") == "C-Freq":
            freq_hz = int(str(snap.get("identity_value") or "0"))
            hpd.add_cfreq(
                group,
                name=str(snap.get("name") or ""),
                freq_hz=freq_hz,
                mode=str(snap.get("mode") or "NFM"),
                tone=str(snap.get("tone") or ""),
                service_type=int(snap.get("service_type") or 14),
            )
        else:
            tgid_val = int(str(snap.get("identity_value") or "0"))
            hpd.add_tgid(
                group,
                name=str(snap.get("name") or ""),
                tgid=tgid_val,
                mode=str(snap.get("mode") or "ALL"),
                service_type=int(snap.get("service_type") or 1),
            )
        hpd.has_changes = True
    except Exception:
        return False
    return True


def restore_import_deleted_entry(
    hpd: Any,
    group: "GroupNode",
    dl: Dict[str, Any],
) -> bool:
    snap = dl.get("snapshot") or {}
    if not dl.get("record_fields"):
        return False
    entry_type = snap.get("entry_type") or "TGID"
    name = snap.get("name") or dl.get("name") or ""
    if entry_type == "TGID":
        try:
            tgid_val = int(snap.get("identity_value") or 0)
        except Exception:
            tgid_val = 0
        hpd.add_tgid(
            group, name, tgid_val,
            snap.get("mode") or "ALL",
            int(snap.get("service_type") or 1),
        )
    else:
        try:
            freq_hz = int(snap.get("identity_value") or 0)
        except Exception:
            freq_hz = 0
        hpd.add_cfreq(
            group, name, freq_hz,
            snap.get("mode") or "NFM",
            snap.get("tone") or "",
            int(snap.get("service_type") or 14),
        )
    return True


def summarize_revert_import(
    removed: int,
    reverted: int,
    restored: int,
    group_removed: int,
    failed: int,
) -> str:
    return (
        f"Reverted import: removed {removed} added, "
        f"reverted {reverted} updated, restored {restored} deleted, "
        f"removed {group_removed} empty groups "
        f"(failures: {failed})"
    )


# ---- RR diff rows (R3) -----------------------------------------------------


def cfreq_diff_tree_rows(
    local_by_hz: Dict[int, "FreqEntry"],
    rr_rows: List[Dict[str, Any]],
    *,
    diff_fn: Callable[..., Dict[str, Tuple[Any, Any]]],
    status_added: str,
    status_removed: str,
    status_changed: str,
    status_same: str,
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    counts = {"added": 0, "removed": 0, "changed": 0, "same": 0}
    rows: List[Dict[str, Any]] = []
    seen: Set[int] = set()
    for rr in rr_rows:
        try:
            hz = int(round(float(rr.get("mhz") or 0) * 1_000_000))
        except Exception:
            continue
        if hz <= 0:
            continue
        seen.add(hz)
        existing = local_by_hz.get(hz)
        rr_name = rr.get("name") or rr.get("alpha") or ""
        rr_mode_str = rr.get("mode") or ""
        ident = f"{hz / 1_000_000:.4f} MHz"
        if existing is None:
            rows.append({
                "values": (status_added, ident, "", f"{rr_name} / {rr_mode_str}", "New on RR"),
                "tags": ("added",),
            })
            counts["added"] += 1
            continue
        svc = rr.get("suggested_service_type")
        changes = diff_fn(
            existing.name,
            existing.record.get_field(6, ""),
            existing.record.get_field(7, ""),
            existing.service_type,
            rr_name,
            rr_mode_str,
            rr.get("tone") or "",
            svc if isinstance(svc, int) else None,
        )
        if changes:
            rows.append({
                "values": (
                    status_changed, ident,
                    f"{existing.name} / {existing.record.get_field(6, '')}",
                    f"{rr_name} / {rr_mode_str}",
                    changes_detail(changes),
                ),
                "tags": ("changed",),
            })
            counts["changed"] += 1
        else:
            rows.append({
                "values": (status_same, ident, existing.name, rr_name, ""),
                "tags": ("same",),
            })
            counts["same"] += 1
    for hz, entry in local_by_hz.items():
        if hz in seen:
            continue
        rows.append({
            "values": (
                status_removed, f"{hz / 1_000_000:.4f} MHz",
                entry.name, "", "Missing on RR",
            ),
            "tags": ("removed",),
        })
        counts["removed"] += 1
    return rows, counts


def tgid_diff_tree_rows(
    local_by_tgid: Dict[int, "FreqEntry"],
    rr_rows: List[Dict[str, Any]],
    *,
    diff_fn: Callable[..., Dict[str, Tuple[Any, Any]]],
    mode_label_fn: Callable[[str], str],
    status_added: str,
    status_removed: str,
    status_changed: str,
    status_same: str,
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    counts = {"added": 0, "removed": 0, "changed": 0, "same": 0}
    rows: List[Dict[str, Any]] = []
    seen_tgids: Set[int] = set()
    for rr in rr_rows:
        try:
            tgid = int(rr.get("tgid") or 0)
        except Exception:
            continue
        if tgid <= 0:
            continue
        seen_tgids.add(tgid)
        existing = local_by_tgid.get(tgid)
        rr_name = rr.get("name") or rr.get("alpha") or ""
        rr_mode_str = rr.get("mode") or ""
        ident = f"TGID {tgid}"
        if existing is None:
            detail = "Encrypted" if rr.get("encrypted") else "New on RR"
            mode_disp = mode_label_fn(rr_mode_str) or rr_mode_str
            rows.append({
                "values": (status_added, ident, "", f"{rr_name} / {mode_disp}", detail),
                "tags": ("added",),
            })
            counts["added"] += 1
            continue
        svc = rr.get("suggested_service_type")
        changes = diff_fn(
            existing.name,
            existing.record.get_field(6, ""),
            existing.service_type,
            rr_name,
            rr_mode_str,
            svc if isinstance(svc, int) else None,
        )
        if changes:
            detail = changes_detail(changes)
            if rr.get("encrypted"):
                detail = f"[enc] {detail}"
            ex_mode = mode_label_fn(existing.record.get_field(6, "")) or ""
            rr_mode_disp = mode_label_fn(rr_mode_str) or rr_mode_str
            rows.append({
                "values": (
                    status_changed, ident,
                    f"{existing.name} / {ex_mode}",
                    f"{rr_name} / {rr_mode_disp}",
                    detail,
                ),
                "tags": ("changed",),
            })
            counts["changed"] += 1
        else:
            rows.append({
                "values": (status_same, ident, existing.name, rr_name, ""),
                "tags": ("same",),
            })
            counts["same"] += 1
    for tgid, entry in local_by_tgid.items():
        if tgid in seen_tgids:
            continue
        rows.append({
            "values": (status_removed, f"TGID {tgid}", entry.name, "", "Missing on RR"),
            "tags": ("removed",),
        })
        counts["removed"] += 1
    return rows, counts


def collect_mode_audit_rows(
    systems: List["SystemNode"],
    rr_reference: Dict[int, Dict[str, Any]],
    audit_fn: Callable[["FreqEntry", Dict[int, Dict[str, Any]]], Optional[Tuple[str, str, str]]],
) -> Tuple[List[Dict[str, Any]], int, int, int]:
    rows: List[Dict[str, Any]] = []
    total = rr_flags = band_flags = 0
    for sys_node in systems:
        for group in sys_node.groups:
            for entry in group.entries:
                if entry.entry_type != "C-Freq":
                    continue
                total += 1
                result = audit_fn(entry, rr_reference)
                if result is None:
                    continue
                issue, suggested, source = result
                rec = entry.record
                try:
                    freq_mhz = int(rec.get_field(5, "0")) / 1_000_000
                except ValueError:
                    freq_mhz = 0
                if source == "rr":
                    rr_flags += 1
                    row_tag = "source_rr"
                else:
                    band_flags += 1
                    row_tag = "source_band"
                rows.append({
                    "entry": entry,
                    "issue": issue,
                    "suggested": suggested,
                    "values": (
                        sys_node.name,
                        group.name,
                        entry.name,
                        f"{freq_mhz:.4f}",
                        rec.get_field(6, ""),
                        suggested,
                        source.upper(),
                        issue,
                    ),
                    "tags": (str(id(entry)), row_tag),
                })
    return rows, total, rr_flags, band_flags


def iter_bulk_remap_candidates(
    systems: List["SystemNode"],
    *,
    entry_types: Set[str],
    service_types: Optional[Set[int]],
    scope: str,
    location_match_fn: Callable[["SystemNode"], bool],
    selected_system_id: Optional[str],
) -> List["FreqEntry"]:
    location_indices: Optional[Set[int]] = None
    if scope == "location":
        location_indices = {
            i for i, sys_node in enumerate(systems) if location_match_fn(sys_node)
        }
    candidates: List[FreqEntry] = []
    for i, sys_node in enumerate(systems):
        if scope == "location" and location_indices is not None and i not in location_indices:
            continue
        if scope == "selected" and selected_system_id is not None and sys_node.system_id != selected_system_id:
            continue
        for group in sys_node.groups:
            for entry in group.entries:
                if entry_matches_bulk_filter(
                    entry, entry_types, service_types, county_id=None, system_id=None,
                ):
                    candidates.append(entry)
    return candidates


def rr_pull_entry_row(entry: Dict[str, Any], mode: str) -> Tuple[str, str, str, str]:
    kind = entry.get("system_kind") or entry.get("type") or mode
    if kind in ("trs", "trs_ref"):
        ident_field = entry.get("sid") or ""
        url = f"https://www.radioreference.com/db/sid/{ident_field}" if ident_field else ""
    elif kind == "ctid":
        ident_field = entry.get("ctid") or ""
        url = f"https://www.radioreference.com/db/ctid/{ident_field}" if ident_field else ""
    elif kind == "county_ref":
        ident_field = entry.get("cid") or ""
        url = f"https://www.radioreference.com/db/county/{ident_field}" if ident_field else ""
    else:
        ident_field = entry.get("id") or ""
        url = ""
    title = entry.get("title") or entry.get("group") or ""
    return title, kind, ident_field, url


def filter_meta_events(
    events: List[Any],
    *,
    op_labels: Dict[str, str],
    op_filter: str,
    src_filter: str,
    status_filter: str,
    committed_filter: str,
    search: str,
) -> Tuple[List[Dict[str, Any]], int, int]:
    pending_count = saved_count = 0
    rows: List[Dict[str, Any]] = []
    search_lower = search.strip().lower()
    for event in events:
        op_label = op_labels.get(event.op, event.op)
        if op_filter != "All" and op_filter != op_label:
            continue
        if src_filter != "All" and src_filter != event.source:
            continue
        if status_filter == "Active" and event.reverted:
            continue
        if status_filter == "Reverted" and not event.reverted:
            continue
        if committed_filter == "Saved" and not event.committed:
            continue
        if committed_filter == "Pending" and event.committed:
            continue
        haystack = " ".join([
            event.target_name or "",
            event.summary or "",
            event.target_id or "",
        ]).lower()
        if search_lower and search_lower not in haystack:
            continue
        status = "reverted" if event.reverted else "active"
        saved_label = "yes" if event.committed else "pending"
        tags: Tuple[str, ...] = () if event.committed else ("pending",)
        if event.committed:
            saved_count += 1
        else:
            pending_count += 1
        rows.append({
            "iid": event.event_id,
            "values": (
                event.ts, op_label,
                event.target_name or event.target_id,
                event.source, status, saved_label, event.summary,
            ),
            "tags": tags,
        })
    return rows, pending_count, saved_count


def group_tower_members_by_system(
    members: List[Any],
) -> List[Tuple[str, List[Any]]]:
    by_system: Dict[str, List[Any]] = {}
    order: List[str] = []
    for member in members:
        if member.system not in by_system:
            by_system[member.system] = []
            order.append(member.system)
        by_system[member.system].append(member)
    return [(name, by_system[name]) for name in order]


def qr_code_matrix(qrcode_mod: Any, data: str) -> Optional[List[List[bool]]]:
    try:
        qr = qrcode_mod.QRCode(
            border=1, box_size=1,
            error_correction=qrcode_mod.constants.ERROR_CORRECT_M,
        )
        qr.add_data(data)
        qr.make(fit=True)
        return qr.get_matrix()
    except Exception:
        return None


def build_custom_city_records(
    custom_locations: List[Dict[str, Any]],
    abbrev_fn: Callable[[int], Optional[str]],
    base_id: int = 60000,
) -> List[Any]:
    from legacy_tk.geo_tables import CityRecord

    extras: List[CityRecord] = []
    next_id = base_id
    for loc in custom_locations:
        abbrev = abbrev_fn(loc["state_id"]) or "XX"
        if len(abbrev) != 2:
            continue
        extras.append(
            CityRecord(
                state_abbrev=abbrev,
                city_id=next_id,
                lat=float(loc["lat"]),
                lon=float(loc["lon"]),
            )
        )
        next_id += 1
    return extras


def workspace_clone_result(
    name: str,
    card_root: str,
    ws_dir: str,
) -> Optional[Dict[str, str]]:
    import re

    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_") or "workspace"
    workspace_dir = os.path.join(ws_dir, safe_name)
    return {
        "action": "clone",
        "name": name,
        "workspace_dir": workspace_dir,
        "needs_nonempty_confirm": (
            os.path.exists(workspace_dir) and bool(os.listdir(workspace_dir))
        ),
    }
