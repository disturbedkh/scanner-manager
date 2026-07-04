"""RadioReference HTML fetch and parse helpers for legacy Tk."""

from __future__ import annotations

import re
import urllib.request
from typing import Any, Dict, Optional, Tuple

from legacy_tk import rr_html_parsers as _html

# Re-export parsers for tests and scanner_manager back-compat.
_parse_rr_fcc_callsign = _html.parse_rr_fcc_callsign
_parse_rr_category_aid = _html.parse_rr_category_aid
_parse_rr_conventional_ctid = _html.parse_rr_conventional_ctid
_parse_rr_trs_sid = _html.parse_rr_trs_sid
_extract_cfreq_rows_from_html = _html.extract_cfreq_rows_from_html
_extract_rr_trs_talkgroups = _html.extract_rr_trs_talkgroups
_clean_rr_category_title = _html.clean_rr_category_title
_rr_mode_to_hpd = _html.rr_mode_to_hpd
_rr_tone_to_hpd = _html.rr_tone_to_hpd
_rr_trs_mode_to_hpd = _html.rr_trs_mode_to_hpd
_tag_to_service_type = _html.tag_to_service_type
RR_SERVICE_MAP = _html.RR_SERVICE_MAP
RR_CATEGORY_TITLE_TRAIL_PATTERNS = _html.RR_CATEGORY_TITLE_TRAIL_PATTERNS

_RE_RR_URL = re.compile(r"^https?://(www\.)?radioreference\.com/")


def fetch_radioreference_data(url: str) -> Optional[Dict[str, Any]]:
    if not _RE_RR_URL.match(url):
        raise ValueError("URL must be a radioreference.com link.")
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "scanner-manager/0.1 (+python urllib)",
            "Accept": "text/html",
        },
    )
    with urllib.request.urlopen(req, timeout=12) as resp:
        html = resp.read().decode("utf-8", errors="replace")
    parsed = _html.parse_rr_html_by_url(html, url.lower())
    if parsed is not None:
        parsed.setdefault("source_url", url)
    return parsed


def is_rr_mode_encrypted(rr_mode: str) -> bool:
    """True when RadioReference Mode indicates encrypted audio (BT885 can't decode)."""
    if not rr_mode:
        return False
    upper = rr_mode.strip().upper()
    return upper in {"DE", "TE", "AE"}


def classify_rr_tg_import_action(
    *,
    is_encrypted: bool,
    has_existing: bool,
    has_update_diff: bool,
    encrypted_policy: str,
    include_encrypted: bool,
) -> str:
    """Decide what to do with a TG row in the RR-import dialog."""
    if is_encrypted:
        if has_existing:
            if encrypted_policy == "delete":
                return "delete_encrypted"
            return "same_encrypted"
        if include_encrypted:
            return "new"
        return "encrypted"
    if has_existing:
        return "update" if has_update_diff else "same"
    return "new"


def _normalize_tgid_mode_for_diff(mode: str) -> str:
    m = (mode or "").strip().upper()
    if not m:
        return ""
    if m in ("D", "TD", "T", "TDMA", "DE", "DMR"):
        return "DIGITAL"
    if m in ("A", "AE"):
        return "ANALOG"
    return m


def diff_cfreq_with_rr(
    entry_name: str,
    entry_mode: str,
    entry_tone: str,
    entry_service_type: int,
    rr_name: str,
    rr_mode: str,
    rr_tone: str,
    rr_service_type: Optional[int],
) -> Dict[str, Tuple[Any, Any]]:
    """Detect meaningful differences between existing C-Freq and RR data."""
    changes: Dict[str, Tuple[Any, Any]] = {}
    if rr_name and rr_name.strip() and rr_name.strip() != (entry_name or "").strip():
        changes["name"] = (entry_name, rr_name.strip())
    rr_mode_norm = (rr_mode or "").strip().upper()
    existing_mode_norm = (entry_mode or "").strip().upper()
    if rr_mode_norm and rr_mode_norm != existing_mode_norm:
        changes["mode"] = (entry_mode, rr_mode_norm)
    rr_tone_norm = (rr_tone or "").strip()
    existing_tone_norm = (entry_tone or "").strip()
    if rr_tone_norm and rr_tone_norm != existing_tone_norm:
        changes["tone"] = (entry_tone, rr_tone_norm)
    if isinstance(rr_service_type, int) and rr_service_type > 0:
        if rr_service_type != entry_service_type:
            changes["service_type"] = (entry_service_type, rr_service_type)
    return changes


def _apply_tgid_mode_diff(
    changes: Dict[str, Tuple[Any, Any]],
    entry_mode: str,
    rr_mode: str,
) -> None:
    rr_raw = rr_mode.strip()
    rr_n = _normalize_tgid_mode_for_diff(rr_raw)
    ex_n = _normalize_tgid_mode_for_diff(entry_mode) or "ALL"
    if not rr_n or rr_n == ex_n:
        return
    concrete = frozenset({"DIGITAL", "ANALOG"})
    new_value = rr_n if rr_n in concrete or rr_n == "ALL" else rr_raw
    if rr_n in concrete and (ex_n == "ALL" or ex_n in concrete):
        changes["mode"] = (entry_mode, new_value)


def diff_tgid_with_rr(
    entry_name: str,
    entry_mode: str,
    entry_service_type: int,
    rr_name: str,
    rr_mode: str,
    rr_service_type: Optional[int],
) -> Dict[str, Tuple[Any, Any]]:
    """Return map of field -> (old, new) for fields that should be updated from RR."""
    changes: Dict[str, Tuple[Any, Any]] = {}
    if rr_name and rr_name.strip() and rr_name.strip() != (entry_name or "").strip():
        changes["name"] = (entry_name, rr_name.strip())
    if rr_mode:
        _apply_tgid_mode_diff(changes, entry_mode, rr_mode)
    if isinstance(rr_service_type, int) and rr_service_type > 0:
        if rr_service_type != entry_service_type:
            changes["service_type"] = (entry_service_type, rr_service_type)
    return changes
