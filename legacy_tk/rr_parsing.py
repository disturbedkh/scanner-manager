"""RadioReference HTML fetch and parse helpers for legacy Tk."""

from __future__ import annotations

import re
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Set, Tuple

from legacy_tk.literals import _LIT_RE_TR_ROW, _LIT_RR_GROUP

RR_SERVICE_MAP = {
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


def fetch_radioreference_data(url: str) -> Optional[Dict[str, Any]]:
    if not re.match(r"^https?://(www\.)?radioreference\.com/", url):
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
    lower_url = url.lower()
    parsed: Optional[Dict[str, Any]] = None
    if "/fcc/callsign/" in lower_url:
        parsed = _parse_rr_fcc_callsign(html)
        if parsed is not None:
            parsed["kind"] = "fcc_callsign"
            # Enrich with the callsign from the URL itself, which survives
            # even when the page body doesn't repeat it verbatim.
            cs_match = re.search(r"/fcc/callsign/([A-Za-z0-9]+)", url)
            if cs_match:
                parsed["fcc_callsign"] = cs_match.group(1).upper()
                for freq in parsed.get("frequencies") or []:
                    freq.setdefault("fcc_callsign", cs_match.group(1).upper())
                    if parsed.get("licensee"):
                        freq.setdefault("licensee", parsed["licensee"])
    elif "/db/aid/" in lower_url or "/db/cid/" in lower_url:
        parsed = _parse_rr_category_aid(html)
        if parsed is not None:
            parsed["kind"] = "category"
    elif "/db/ctid/" in lower_url or "/db/browse/" in lower_url:
        parsed = _parse_rr_conventional_ctid(html)
        if parsed is not None:
            parsed["kind"] = "conventional_multi"
    elif "/db/sid/" in lower_url or "/db/tid/" in lower_url:
        parsed = _parse_rr_trs_sid(html)
        if parsed is not None:
            parsed["kind"] = "trs"
    if parsed is not None:
        parsed.setdefault("source_url", url)
    return parsed


def _strip_tags(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html)


def _collapse_ws(text: str) -> str:
    return " ".join(text.replace("&nbsp;", " ").split())


def _parse_rr_fcc_callsign(html: str) -> Optional[Dict[str, Any]]:
    licensee = _extract_labeled_value(html, "Licensee")
    radio_service = _extract_labeled_value(html, "Radio Service")
    notes = _extract_labeled_value(html, "Notes")
    county = _extract_labeled_value(html, "County")
    state = _extract_labeled_value(html, "State")

    frequencies: List[Dict[str, Any]] = []
    classes_wanted = {"FB", "FB2", "FB8", "FXO", "MO"}
    classes_secondary = {"FX1"}
    seen: Set[Tuple[str, str]] = set()
    for row_match in re.finditer(_LIT_RE_TR_ROW, html, re.DOTALL | re.IGNORECASE):
        row = row_match.group(1)
        cells = [
            _collapse_ws(_strip_tags(cell))
            for cell in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.DOTALL | re.IGNORECASE)
        ]
        if len(cells) < 5:
            continue
        freq_match = re.search(r"^(\d{2,4}\.\d+)$", cells[1].replace(",", "")) if len(cells) > 1 else None
        if not freq_match:
            continue
        try:
            mhz = float(freq_match.group(1))
        except ValueError:
            continue
        if not (25.0 <= mhz <= 1300.0):
            continue
        emission = cells[2] if len(cells) > 2 else ""
        fclass = cells[3] if len(cells) > 3 else ""
        lat = cells[6] if len(cells) > 6 else ""
        lon = cells[7] if len(cells) > 7 else ""
        city = cells[8] if len(cells) > 8 else ""
        key = (freq_match.group(1), fclass)
        if key in seen:
            continue
        seen.add(key)
        frequencies.append(
            {
                "mhz": mhz,
                "emission": emission,
                "class": fclass,
                "lat": lat,
                "lon": lon,
                "city": city,
                "mode": _emission_to_mode(emission),
                "tone": "",
                "name": licensee or "",
            }
        )

    if frequencies:
        def priority(item: Dict[str, Any]) -> Tuple[int, float]:
            fclass = item.get("class", "")
            tier = 0 if fclass in classes_wanted else (1 if fclass in classes_secondary else 2)
            return (tier, item.get("mhz", 0.0))

        frequencies.sort(key=priority)

    suggested = _guess_service_type(f"{radio_service} {notes} {licensee}")

    # Propagate licensee onto every row so downstream imports get the cross-ref.
    for freq in frequencies:
        if licensee:
            freq["licensee"] = licensee
        if county:
            freq["county"] = county

    return {
        "name": licensee or "",
        "licensee": licensee or "",
        "frequencies": frequencies,
        "county": county,
        "state": state,
        "suggested_service_type": suggested,
    }


def _emission_to_mode(emission: str) -> str:
    if not emission:
        return "NFM"
    digital_hints = ("F1D", "F1E", "D7W", "GXE", "G1D")
    if any(hint in emission for hint in digital_hints):
        return "NFM"
    if "F3E" in emission or "F2E" in emission:
        if emission.startswith("20K") or emission.startswith("25K"):
            return "FM"
        return "NFM"
    return "NFM"


def _guess_service_type(text: str) -> Optional[int]:
    if not text:
        return None
    lowered = text.lower()
    for keyword, service_id in RR_SERVICE_MAP.items():
        if keyword in lowered:
            return service_id
    return None


def _extract_cfreq_rows_from_html(html_segment: str) -> List[Dict[str, Any]]:
    """Extract conventional-frequency rows from a RadioReference HTML fragment.

    Also captures the FCC callsign and licensee/tag anchor text from the
    License cell (index 1) so later cross-referencing can identify
    operators by callsign and licensee name.
    """
    frequencies: List[Dict[str, Any]] = []
    for row_match in re.finditer(_LIT_RE_TR_ROW, html_segment, re.DOTALL | re.IGNORECASE):
        row = row_match.group(1)
        raw_cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.DOTALL | re.IGNORECASE)
        cells = [_collapse_ws(_strip_tags(c)) for c in raw_cells]
        if len(cells) < 7:
            continue
        freq_text = cells[0].replace(",", "")
        m = re.match(r"^(\d{2,4}\.\d+)$", freq_text)
        if not m:
            continue
        try:
            mhz = float(m.group(1))
        except ValueError:
            continue
        if not (25.0 <= mhz <= 1300.0):
            continue

        callsign = ""
        licensee_text = ""
        if len(raw_cells) > 1:
            cs_match = re.search(
                r"/db/fcc/callsign/([A-Za-z0-9]+)", raw_cells[1], re.IGNORECASE,
            )
            if cs_match:
                callsign = cs_match.group(1).upper()
            lic_match = re.search(
                r"<a[^>]*/db/fcc/callsign/[^>]*>([^<]+)</a>",
                raw_cells[1],
                re.IGNORECASE,
            )
            if lic_match:
                licensee_text = _collapse_ws(_strip_tags(lic_match.group(1)))
            elif cells[1]:
                licensee_text = cells[1]

        tone_text = cells[3] if len(cells) > 3 else ""
        alpha = cells[4] if len(cells) > 4 else ""
        desc = cells[5] if len(cells) > 5 else ""
        mode_text = cells[6] if len(cells) > 6 else ""
        tag = cells[7] if len(cells) > 7 else ""
        name = desc or alpha or ""
        frequencies.append(
            {
                "mhz": mhz,
                "mode": _rr_mode_to_hpd(mode_text),
                "tone": _rr_tone_to_hpd(tone_text),
                "name": name,
                "alpha": alpha,
                "tag": tag,
                "fcc_callsign": callsign,
                "licensee": licensee_text,
                "licensee_text": licensee_text,
                "suggested_service_type": _guess_service_type(f"{tag} {desc}") or 14,
            }
        )
    return frequencies


def _parse_rr_category_aid(html: str) -> Optional[Dict[str, Any]]:
    title = _extract_category_title(html)
    frequencies = _extract_cfreq_rows_from_html(html)
    if not frequencies:
        return None
    return {
        "group_name": title or _LIT_RR_GROUP,
        "frequencies": frequencies,
    }


def _parse_rr_conventional_ctid(html: str) -> Optional[Dict[str, Any]]:
    """Parse a RR county/browse page into multiple categories of conventional frequencies.

    Tries subsection heading tags (h3, h4, h2) in order and groups frequency rows
    under each subsection. Falls back to a single category when no subsections
    produce usable rows.
    """
    title = _extract_category_title(html)
    categories: List[Dict[str, Any]] = []
    seen_total_rows = 0
    for heading_tag in ("h3", "h4", "h5", "h2"):
        cat_pattern = re.compile(
            rf"<{heading_tag}[^>]*>(?P<title>.*?)</{heading_tag}>"
            rf"(?P<after>.*?)(?=<{heading_tag}[^>]*>|<footer|$)",
            re.DOTALL | re.IGNORECASE,
        )
        tmp: List[Dict[str, Any]] = []
        for m in cat_pattern.finditer(html):
            cat_title = _clean_rr_category_title(m.group("title"))
            if not cat_title or cat_title.lower().startswith("premium subscription"):
                continue
            freqs = _extract_cfreq_rows_from_html(m.group("after"))
            if not freqs:
                continue
            tmp.append({"name": cat_title, "frequencies": freqs})
            seen_total_rows += len(freqs)
        if tmp:
            categories = tmp
            break
    if not categories:
        freqs = _extract_cfreq_rows_from_html(html)
        if freqs:
            categories = [
                {"name": title or "RadioReference Frequencies", "frequencies": freqs}
            ]
    if not categories:
        return None
    return {"title": title, "categories": categories}


def _parse_rr_trs_sid(html: str) -> Optional[Dict[str, Any]]:
    """Parse a RadioReference trunked system (sid) page into categories + talkgroups."""
    system_name = ""
    page_title_match = re.search(
        r"<title[^>]*>(.*?)</title>", html, re.DOTALL | re.IGNORECASE
    )
    if page_title_match:
        raw_title = _collapse_ws(_strip_tags(page_title_match.group(1)))
        primary = raw_title.split(",", 1)[0].strip()
        if primary:
            system_name = primary
    if not system_name:
        heading_match = re.search(
            r"<h[12][^>]*>(.*?)</h[12]>", html, re.DOTALL | re.IGNORECASE
        )
        if heading_match:
            system_name = _collapse_ws(_strip_tags(heading_match.group(1)))
    categories: List[Dict[str, Any]] = []
    category_pattern = re.compile(
        r"<h5[^>]*>(?P<title>.*?)</h5>(?P<after>.*?)(?=<h5[^>]*>|<footer|$)",
        re.DOTALL | re.IGNORECASE,
    )
    for m in category_pattern.finditer(html):
        title = _clean_rr_category_title(m.group("title"))
        if not title or title.lower() in ("premium subscription required",):
            continue
        segment = m.group("after")
        talkgroups = _extract_rr_trs_talkgroups(segment)
        if not talkgroups:
            continue
        categories.append({"name": title, "talkgroups": talkgroups})
    if not categories:
        return None
    return {"system_name": system_name or "RadioReference Trunk System", "categories": categories}


RR_CATEGORY_TITLE_TRAIL_PATTERNS = (
    "view talkgroup category details",
    "view subcategory details",
    "view details",
)


def _clean_rr_category_title(title_html: str) -> str:
    """Strip inline <a> link text and known trailing UI phrases from a category title."""
    without_anchors = re.sub(
        r"<a[^>]*>.*?</a>", "", title_html, flags=re.DOTALL | re.IGNORECASE
    )
    text = _collapse_ws(_strip_tags(without_anchors))
    lowered = text.lower()
    for phrase in RR_CATEGORY_TITLE_TRAIL_PATTERNS:
        if lowered.endswith(phrase):
            text = text[: len(text) - len(phrase)].rstrip()
            break
    return text.strip()


def _extract_rr_trs_talkgroups(html_segment: str) -> List[Dict[str, Any]]:
    """Pull talkgroup rows from a category segment of a RR trunk page.

    Handles two column layouts:
      * P25 / Motorola / LTR (6 cols): DEC | HEX | Mode | Alpha Tag | Description | Tag
      * EDACS / EDACS-Ext. Addr. (5 cols): DEC | Mode | Alpha Tag | Description | Tag

    The Mode column index is auto-detected per-table from the header row, with a
    per-row fallback that checks whether cell[1] looks like a hex id or a mode
    token — so parsing still works if a particular table is missing <th>s.
    """
    talkgroups: List[Dict[str, Any]] = []
    mode_col: Optional[int] = None  # resolved from header when available
    for row_match in re.finditer(_LIT_RE_TR_ROW, html_segment, re.DOTALL | re.IGNORECASE):
        row = row_match.group(1)
        cell_matches = list(
            re.finditer(r"<(t[dh])[^>]*>(.*?)</\1>", row, re.DOTALL | re.IGNORECASE)
        )
        if not cell_matches:
            continue
        is_header_row = any(
            m.group(1).lower() == "th" for m in cell_matches
        )
        cells = [_collapse_ws(_strip_tags(m.group(2))) for m in cell_matches]

        if is_header_row:
            headers = [c.strip().lower() for c in cells]
            for idx, h in enumerate(headers):
                if h == "mode":
                    mode_col = idx
                    break
            continue

        if len(cells) < 5:
            continue

        dec_text = cells[0].replace(",", "").strip()
        if not dec_text.isdigit():
            continue
        try:
            tgid = int(dec_text)
        except ValueError:
            continue
        if tgid <= 0:
            continue

        if mode_col is not None and mode_col < len(cells):
            resolved_mode_col = mode_col
        else:
            resolved_mode_col = 2 if _cell_looks_like_hex_id(cells[1]) else 1

        raw_mode = cells[resolved_mode_col].strip() if resolved_mode_col < len(cells) else ""
        alpha_idx = resolved_mode_col + 1
        desc_idx = resolved_mode_col + 2
        tag_idx = resolved_mode_col + 3
        alpha = cells[alpha_idx] if alpha_idx < len(cells) else ""
        desc = cells[desc_idx] if desc_idx < len(cells) else ""
        tag = cells[tag_idx] if tag_idx < len(cells) else ""
        name = desc or alpha or ""
        mode = _rr_trs_mode_to_hpd(raw_mode)
        talkgroups.append(
            {
                "tgid": tgid,
                "name": name,
                "alpha": alpha,
                "mode": mode,
                "mode_raw": raw_mode,
                "tag": tag,
                "encrypted": is_rr_mode_encrypted(raw_mode),
                "suggested_service_type": _tag_to_service_type(tag),
            }
        )
    return talkgroups


_RR_MODE_TOKENS = {
    "A", "AE", "D", "DE", "T", "TE", "TD", "TDMA", "DMR",
    "ALL", "ANALOG", "DIGITAL", "P25", "P-25",
}


def _cell_looks_like_hex_id(cell: str) -> bool:
    """Heuristic: does this cell look like the HEX id column (P25/Moto) rather than Mode?

    RR HEX cells are compact hex numbers (e.g. '0A1', '12F4', '1000'). Mode cells are
    short alphabetic tokens (e.g. 'D', 'DE', 'T', 'TDMA', 'A'). Hex cells can contain
    the letters A-F, which overlap with Mode ('A','D'), so we require either a digit
    or a length > 2 to classify as hex.
    """
    s = (cell or "").strip().upper()
    if not s:
        return False
    if s in _RR_MODE_TOKENS:
        return False
    if not all(ch in "0123456789ABCDEF" for ch in s):
        return False
    if any(ch.isdigit() for ch in s):
        return True
    return len(s) > 2


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
    """Decide what to do with a TG row in the RR-import dialog.

    Centralizes the encrypted-policy branching so the rules (skip new
    encrypted by default; delete existing encrypted by default; respect
    a per-system "include encrypted" override) are unit-testable without
    spinning up a Tk window. Returns one of:

    - ``"new"``: add this unseen talkgroup.
    - ``"update"``: overwrite changed fields on an existing entry.
    - ``"same"``: identical to existing, nothing to do.
    - ``"delete_encrypted"``: existing entry now marked encrypted on RR, remove.
    - ``"same_encrypted"``: existing encrypted entry but user chose to skip.
    - ``"encrypted"``: new encrypted TG the user hasn't opted into (skip).
    """
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
    """Normalize TGID mode strings so legacy/short values compare equal to what
    actually lives on the SD card (ALL / ANALOG / DIGITAL).

    The BearTracker 885 HPD TGID Mode column uses the long names exclusively;
    short forms like D / T / TD / DE only ever come from RadioReference or
    older half-baked imports, and should be considered equivalent to DIGITAL
    (or ANALOG for A/AE) for comparison purposes.
    """
    m = (mode or "").strip().upper()
    if not m:
        return ""
    if m in ("D", "TD", "T", "TDMA", "DE", "DMR"):
        return "DIGITAL"
    if m in ("A", "AE"):
        return "ANALOG"
    return m


def _rr_trs_mode_to_hpd(mode_text: str) -> str:
    """Map RadioReference trunk 'Mode' cell to the HPD TGID mode for the active scanner.

    Delegates to :meth:`ScannerProfile.rr_mode_to_hpd_mode` so the exact
    mapping is owned by the scanner profile. Kept as a free function for
    back-compat with existing call sites.
    """
    from scanner_profiles import get_active_profile

    return get_active_profile().rr_mode_to_hpd_mode(mode_text)


def _tag_to_service_type(tag: str) -> Optional[int]:
    if not tag:
        return None
    lowered = tag.strip().lower()
    mapping = {
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
    if lowered in mapping:
        return mapping[lowered]
    return _guess_service_type(tag)


def _extract_category_title(html: str) -> str:
    for heading_tag in ("h1", "h2", "h3"):
        match = re.search(rf"<{heading_tag}[^>]*>(.*?)</{heading_tag}>", html, re.DOTALL | re.IGNORECASE)
        if match:
            text = _collapse_ws(_strip_tags(match.group(1)))
            if text:
                return text
    return ""


def _rr_mode_to_hpd(mode_text: str) -> str:
    if not mode_text:
        return "NFM"
    upper = mode_text.strip().upper()
    if upper == "FM":
        return "FM"
    if upper in ("FMN", "NFM"):
        return "NFM"
    if upper in ("AM",):
        return "AM"
    if upper in ("DMR", "NXDN", "P25", "MOTOTRBO"):
        return "AUTO"
    return "NFM"


def _rr_tone_to_hpd(tone_text: str) -> str:
    if not tone_text:
        return ""
    cleaned = tone_text.strip()
    pl_match = re.match(r"^(\d+\.?\d*)\s*PL$", cleaned, re.IGNORECASE)
    if pl_match:
        return f"TONE=C{pl_match.group(1)}"
    dpl_match = re.match(r"^(\d+)\s*DPL$", cleaned, re.IGNORECASE)
    if dpl_match:
        return f"TONE=D{dpl_match.group(1)}"
    return ""


def _extract_labeled_value(html: str, label: str) -> str:
    pattern = re.compile(
        rf"{re.escape(label)}\s*:?\s*</[^>]+>\s*<[^>]+>(.*?)</",
        re.IGNORECASE | re.DOTALL,
    )
    match = pattern.search(html)
    if not match:
        return ""
    return _collapse_ws(_strip_tags(match.group(1)))


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
    """Detect meaningful differences between existing C-Freq and RR data.

    - name: update if RR differs (non-empty)
    - mode: update if differs; prefer RR value
    - tone: update if RR provides a different non-empty tone
    - service_type: update if RR suggests a different integer type
    """
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


def diff_tgid_with_rr(
    entry_name: str,
    entry_mode: str,
    entry_service_type: int,
    rr_name: str,
    rr_mode: str,
    rr_service_type: Optional[int],
) -> Dict[str, Tuple[Any, Any]]:
    """Return map of field -> (old, new) for fields that should be updated from RR.

    Rules:
    - name: update if RR name differs (non-empty)
    - mode: update if existing is 'ALL' (generic) and RR is specific (D/T/DE/ANALOG), or if concrete modes mismatch
    - service_type: update if RR suggests a different concrete value
    """
    changes: Dict[str, Tuple[Any, Any]] = {}
    if rr_name and rr_name.strip() and rr_name.strip() != (entry_name or "").strip():
        changes["name"] = (entry_name, rr_name.strip())
    if rr_mode:
        rr_raw = rr_mode.strip()
        rr_n = _normalize_tgid_mode_for_diff(rr_raw)
        ex_n = _normalize_tgid_mode_for_diff(entry_mode)
        if not ex_n:
            ex_n = "ALL"
        if rr_n and rr_n != ex_n:
            concrete = frozenset({"DIGITAL", "ANALOG"})
            # Always write the canonical HPD token (DIGITAL/ANALOG/ALL), not
            # the RR short code, so the scanner parses it correctly.
            new_value = rr_n if rr_n in concrete or rr_n == "ALL" else rr_raw
            if ex_n == "ALL" and rr_n in concrete:
                changes["mode"] = (entry_mode, new_value)
            elif ex_n in concrete and rr_n in concrete:
                changes["mode"] = (entry_mode, new_value)
    if isinstance(rr_service_type, int) and rr_service_type > 0:
        if rr_service_type != entry_service_type:
            changes["service_type"] = (entry_service_type, rr_service_type)
    return changes
