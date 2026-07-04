"""RadioReference HTML table parsers (pure, no Tk)."""

from __future__ import annotations

import re
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

_RE_TR_ROW = re.compile(_LIT_RE_TR_ROW, re.DOTALL | re.IGNORECASE)
_RE_TABLE_CELL = re.compile(
    r"<t[dh][^>]*>(.*?)</t[dh]>", re.DOTALL | re.IGNORECASE
)
_RE_MATCHING_CELL = re.compile(
    r"<(t[dh])[^>]*>(.*?)</\1>", re.DOTALL | re.IGNORECASE
)
_RE_STRIP_TAGS = re.compile(r"<[^>]+>")
_RE_FCC_FREQ = re.compile(r"^(\d{2,4}\.\d+)$")
_RE_FCC_CALLSIGN = re.compile(r"/fcc/callsign/([A-Z0-9]+)", re.IGNORECASE)
_RE_LICENSEE_ANCHOR = re.compile(
    r'<a\b[^>]{0,200}/db/fcc/callsign/[^>]{0,200}>([^<]{1,200})</a>',
    re.IGNORECASE,
)
_RE_PAGE_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.DOTALL | re.IGNORECASE)
_RE_H12 = re.compile(r"<h[12][^>]*>(.*?)</h[12]>", re.DOTALL | re.IGNORECASE)
_RE_H5_OPEN = re.compile(r"<h5\b[^>]*>", re.IGNORECASE)
_RE_H5_CLOSE = re.compile(r"</h5>", re.IGNORECASE)
_RE_H5_BOUNDARY = re.compile(r"<(?:h5\b|footer\b)", re.IGNORECASE)
_RE_STRIP_ANCHORS = re.compile(r"<a\b[^>]*>.*?</a>", re.DOTALL | re.IGNORECASE)
_RE_HEADING = re.compile(
    r"<(?P<tag>h[1-3])[^>]*>(?P<body>[^<]*)</(?P=tag)>", re.IGNORECASE
)
_RE_PL_TONE = re.compile(r"^(\d+(?:\.\d+)?)\s+PL$", re.IGNORECASE)
_RE_DPL_TONE = re.compile(r"^(\d+)\s+DPL$", re.IGNORECASE)
_RE_RR_URL_CALLSIGN = re.compile(r"/fcc/callsign/([A-Z0-9]+)", re.IGNORECASE)

_FCC_CLASSES_WANTED = frozenset({"FB", "FB2", "FB8", "FXO", "MO"})
_FCC_CLASSES_SECONDARY = frozenset({"FX1"})

_RR_MODE_TOKENS = frozenset({
    "A", "AE", "D", "DE", "T", "TE", "TD", "TDMA", "DMR",
    "ALL", "ANALOG", "DIGITAL", "P25", "P-25",
})

RR_CATEGORY_TITLE_TRAIL_PATTERNS = (
    "view talkgroup category details",
    "view subcategory details",
    "view details",
)


def _strip_tags(html: str) -> str:
    return _RE_STRIP_TAGS.sub("", html)


def _collapse_ws(text: str) -> str:
    return " ".join(text.replace("&nbsp;", " ").split())


def _guess_service_type(text: str) -> Optional[int]:
    if not text:
        return None
    lowered = text.lower()
    for keyword, service_id in RR_SERVICE_MAP.items():
        if keyword in lowered:
            return service_id
    return None


def _emission_to_mode(emission: str) -> str:
    if not emission:
        return "NFM"
    digital_hints = ("F1D", "F1E", "D7W", "GXE", "G1D")
    if any(hint in emission for hint in digital_hints):
        return "NFM"
    if "F3E" in emission or "F2E" in emission:
        if emission.startswith(("20K", "25K")):
            return "FM"
        return "NFM"
    return "NFM"


def _fcc_class_tier(fclass: str) -> int:
    if fclass in _FCC_CLASSES_WANTED:
        return 0
    if fclass in _FCC_CLASSES_SECONDARY:
        return 1
    return 2


def _parse_mhz(freq_text: str) -> Optional[float]:
    m = _RE_FCC_FREQ.match(freq_text.replace(",", ""))
    if not m:
        return None
    try:
        mhz = float(m.group(1))
    except ValueError:
        return None
    if not (25.0 <= mhz <= 1300.0):
        return None
    return mhz


def _extract_labeled_value(html: str, label: str) -> str:
    pattern = re.compile(
        rf"{re.escape(label)}\s*:?\s*</[^>]+>\s*<[^>]+>([^<]*)</",
        re.IGNORECASE,
    )
    match = pattern.search(html)
    if not match:
        return ""
    return _collapse_ws(_strip_tags(match.group(1)))


def _parse_fcc_freq_row(
    cells: List[str],
    seen: Set[Tuple[str, str]],
    licensee: str,
) -> Optional[Dict[str, Any]]:
    if len(cells) < 5:
        return None
    freq_match = _RE_FCC_FREQ.match(cells[1].replace(",", "")) if len(cells) > 1 else None
    if not freq_match:
        return None
    try:
        mhz = float(freq_match.group(1))
    except ValueError:
        return None
    if not (25.0 <= mhz <= 1300.0):
        return None
    emission = cells[2] if len(cells) > 2 else ""
    fclass = cells[3] if len(cells) > 3 else ""
    key = (freq_match.group(1), fclass)
    if key in seen:
        return None
    seen.add(key)
    lat = cells[6] if len(cells) > 6 else ""
    lon = cells[7] if len(cells) > 7 else ""
    city = cells[8] if len(cells) > 8 else ""
    return {
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


def parse_rr_fcc_callsign(html: str) -> Optional[Dict[str, Any]]:
    licensee = _extract_labeled_value(html, "Licensee")
    radio_service = _extract_labeled_value(html, "Radio Service")
    notes = _extract_labeled_value(html, "Notes")
    county = _extract_labeled_value(html, "County")
    state = _extract_labeled_value(html, "State")

    frequencies: List[Dict[str, Any]] = []
    seen: Set[Tuple[str, str]] = set()
    for row_match in _RE_TR_ROW.finditer(html):
        row = row_match.group(1)
        cells = [
            _collapse_ws(_strip_tags(cell))
            for cell in _RE_TABLE_CELL.findall(row)
        ]
        parsed_row = _parse_fcc_freq_row(cells, seen, licensee)
        if parsed_row is not None:
            frequencies.append(parsed_row)

    if frequencies:
        frequencies.sort(key=lambda item: (_fcc_class_tier(item.get("class", "")), item.get("mhz", 0.0)))

    suggested = _guess_service_type(f"{radio_service} {notes} {licensee}")

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


def _licensee_from_cell(raw_cells: List[str], cells: List[str]) -> Tuple[str, str]:
    callsign = ""
    licensee_text = ""
    if len(raw_cells) <= 1:
        return callsign, licensee_text
    cs_match = _RE_FCC_CALLSIGN.search(raw_cells[1])
    if cs_match:
        callsign = cs_match.group(1).upper()
    lic_match = _RE_LICENSEE_ANCHOR.search(raw_cells[1])
    if lic_match:
        licensee_text = _collapse_ws(_strip_tags(lic_match.group(1)))
    elif len(cells) > 1 and cells[1]:
        licensee_text = cells[1]
    return callsign, licensee_text


def _build_cfreq_row(
    cells: List[str],
    raw_cells: List[str],
    mhz: float,
) -> Dict[str, Any]:
    callsign, licensee_text = _licensee_from_cell(raw_cells, cells)
    tone_text = cells[3] if len(cells) > 3 else ""
    alpha = cells[4] if len(cells) > 4 else ""
    desc = cells[5] if len(cells) > 5 else ""
    mode_text = cells[6] if len(cells) > 6 else ""
    tag = cells[7] if len(cells) > 7 else ""
    name = desc or alpha or ""
    return {
        "mhz": mhz,
        "mode": rr_mode_to_hpd(mode_text),
        "tone": rr_tone_to_hpd(tone_text),
        "name": name,
        "alpha": alpha,
        "tag": tag,
        "fcc_callsign": callsign,
        "licensee": licensee_text,
        "licensee_text": licensee_text,
        "suggested_service_type": _guess_service_type(f"{tag} {desc}") or 14,
    }


def extract_cfreq_rows_from_html(html_segment: str) -> List[Dict[str, Any]]:
    """Extract conventional-frequency rows from a RadioReference HTML fragment."""
    frequencies: List[Dict[str, Any]] = []
    for row_match in _RE_TR_ROW.finditer(html_segment):
        row = row_match.group(1)
        raw_cells = _RE_TABLE_CELL.findall(row)
        cells = [_collapse_ws(_strip_tags(c)) for c in raw_cells]
        if len(cells) < 7:
            continue
        mhz = _parse_mhz(cells[0])
        if mhz is None:
            continue
        frequencies.append(_build_cfreq_row(cells, raw_cells, mhz))
    return frequencies


def _extract_category_title(html: str) -> str:
    for match in _RE_HEADING.finditer(html):
        text = _collapse_ws(_strip_tags(match.group("body")))
        if text:
            return text
    return ""


def parse_rr_category_aid(html: str) -> Optional[Dict[str, Any]]:
    title = _extract_category_title(html)
    frequencies = extract_cfreq_rows_from_html(html)
    if not frequencies:
        return None
    return {
        "group_name": title or _LIT_RR_GROUP,
        "frequencies": frequencies,
    }


def _heading_category_pattern(heading_tag: str) -> re.Pattern[str]:
    return re.compile(
        rf"<{heading_tag}[^>]*>(?P<title>[^<]*)</{heading_tag}>"
        rf"(?P<after>.+?)(?=<{heading_tag}\b|<footer|$)",
        re.DOTALL | re.IGNORECASE,
    )


def _categories_from_headings(html: str, heading_tag: str) -> List[Dict[str, Any]]:
    pattern = _heading_category_pattern(heading_tag)
    categories: List[Dict[str, Any]] = []
    for match in pattern.finditer(html):
        cat_title = clean_rr_category_title(match.group("title"))
        if not cat_title or cat_title.lower().startswith("premium subscription"):
            continue
        freqs = extract_cfreq_rows_from_html(match.group("after"))
        if not freqs:
            continue
        categories.append({"name": cat_title, "frequencies": freqs})
    return categories


def parse_rr_conventional_ctid(html: str) -> Optional[Dict[str, Any]]:
    """Parse a RR county/browse page into multiple conventional categories."""
    title = _extract_category_title(html)
    categories: List[Dict[str, Any]] = []
    for heading_tag in ("h3", "h4", "h5", "h2"):
        tmp = _categories_from_headings(html, heading_tag)
        if tmp:
            categories = tmp
            break
    if not categories:
        freqs = extract_cfreq_rows_from_html(html)
        if freqs:
            categories = [
                {"name": title or "RadioReference Frequencies", "frequencies": freqs}
            ]
    if not categories:
        return None
    return {"title": title, "categories": categories}


def _system_name_from_html(html: str) -> str:
    page_title_match = _RE_PAGE_TITLE.search(html)
    if page_title_match:
        raw_title = _collapse_ws(_strip_tags(page_title_match.group(1)))
        primary = raw_title.split(",", 1)[0].strip()
        if primary:
            return primary
    heading_match = _RE_H12.search(html)
    if heading_match:
        return _collapse_ws(_strip_tags(heading_match.group(1)))
    return ""


def clean_rr_category_title(title_html: str) -> str:
    """Strip inline anchors and known trailing UI phrases from a category title."""
    without_anchors = _RE_STRIP_ANCHORS.sub("", title_html)
    text = _collapse_ws(_strip_tags(without_anchors))
    lowered = text.lower()
    for phrase in RR_CATEGORY_TITLE_TRAIL_PATTERNS:
        if lowered.endswith(phrase):
            text = text[: len(text) - len(phrase)].rstrip()
            break
    return text.strip()


def _is_rr_mode_encrypted(rr_mode: str) -> bool:
    if not rr_mode:
        return False
    return rr_mode.strip().upper() in {"DE", "TE", "AE"}


def _cell_looks_like_hex_id(cell: str) -> bool:
    s = (cell or "").strip().upper()
    if not s or s in _RR_MODE_TOKENS:
        return False
    if not all(ch in "0123456789ABCDEF" for ch in s):
        return False
    if any(ch.isdigit() for ch in s):
        return True
    return len(s) > 2


def _resolve_mode_column(mode_col: Optional[int], cells: List[str]) -> int:
    if mode_col is not None and mode_col < len(cells):
        return mode_col
    return 2 if _cell_looks_like_hex_id(cells[1]) else 1


def _parse_trs_talkgroup_row(
    cells: List[str],
    mode_col: Optional[int],
) -> Optional[Dict[str, Any]]:
    if len(cells) < 5:
        return None
    dec_text = cells[0].replace(",", "").strip()
    if not dec_text.isdigit():
        return None
    try:
        tgid = int(dec_text)
    except ValueError:
        return None
    if tgid <= 0:
        return None

    resolved_mode_col = _resolve_mode_column(mode_col, cells)
    raw_mode = cells[resolved_mode_col].strip() if resolved_mode_col < len(cells) else ""
    alpha_idx = resolved_mode_col + 1
    desc_idx = resolved_mode_col + 2
    tag_idx = resolved_mode_col + 3
    alpha = cells[alpha_idx] if alpha_idx < len(cells) else ""
    desc = cells[desc_idx] if desc_idx < len(cells) else ""
    tag = cells[tag_idx] if tag_idx < len(cells) else ""
    name = desc or alpha or ""
    return {
        "tgid": tgid,
        "name": name,
        "alpha": alpha,
        "mode": rr_trs_mode_to_hpd(raw_mode),
        "mode_raw": raw_mode,
        "tag": tag,
        "encrypted": _is_rr_mode_encrypted(raw_mode),
        "suggested_service_type": tag_to_service_type(tag),
    }


def extract_rr_trs_talkgroups(html_segment: str) -> List[Dict[str, Any]]:
    """Pull talkgroup rows from a category segment of a RR trunk page."""
    talkgroups: List[Dict[str, Any]] = []
    mode_col: Optional[int] = None
    for row_match in _RE_TR_ROW.finditer(html_segment):
        row = row_match.group(1)
        cell_matches = list(_RE_MATCHING_CELL.finditer(row))
        if not cell_matches:
            continue
        is_header_row = any(m.group(1).lower() == "th" for m in cell_matches)
        cells = [_collapse_ws(_strip_tags(m.group(2))) for m in cell_matches]
        if is_header_row:
            headers = [c.strip().lower() for c in cells]
            for idx, h in enumerate(headers):
                if h == "mode":
                    mode_col = idx
                    break
            continue
        parsed = _parse_trs_talkgroup_row(cells, mode_col)
        if parsed is not None:
            talkgroups.append(parsed)
    return talkgroups


def _iter_h5_category_sections(html: str):
    """Yield ``(title_html, section_html)`` for each ``<h5>`` block (no lazy backtracking)."""
    pos = 0
    while True:
        open_match = _RE_H5_OPEN.search(html, pos)
        if open_match is None:
            break
        inner_start = open_match.end()
        close_match = _RE_H5_CLOSE.search(html, inner_start)
        if close_match is None:
            break
        title_raw = html[inner_start : close_match.start()]
        section_start = close_match.end()
        boundary = _RE_H5_BOUNDARY.search(html, section_start)
        section_end = boundary.start() if boundary else len(html)
        yield title_raw, html[section_start:section_end]
        pos = section_end


def parse_rr_trs_sid(html: str) -> Optional[Dict[str, Any]]:
    """Parse a RadioReference trunk system (sid) page into categories + talkgroups."""
    system_name = _system_name_from_html(html)
    categories: List[Dict[str, Any]] = []
    for title_raw, section_html in _iter_h5_category_sections(html):
        title = clean_rr_category_title(title_raw)
        if not title or title.lower() in ("premium subscription required",):
            continue
        talkgroups = extract_rr_trs_talkgroups(section_html)
        if not talkgroups:
            continue
        categories.append({"name": title, "talkgroups": talkgroups})
    if not categories:
        return None
    return {"system_name": system_name or "RadioReference Trunk System", "categories": categories}


def rr_mode_to_hpd(mode_text: str) -> str:
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


def rr_tone_to_hpd(tone_text: str) -> str:
    if not tone_text:
        return ""
    cleaned = tone_text.strip()
    pl_match = _RE_PL_TONE.match(cleaned)
    if pl_match:
        return f"TONE=C{pl_match.group(1)}"
    dpl_match = _RE_DPL_TONE.match(cleaned)
    if dpl_match:
        return f"TONE=D{dpl_match.group(1)}"
    return ""


def rr_trs_mode_to_hpd(mode_text: str) -> str:
    from scanner_profiles import get_active_profile

    return get_active_profile().rr_mode_to_hpd_mode(mode_text)


def tag_to_service_type(tag: str) -> Optional[int]:
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


def enrich_fcc_callsign_from_url(parsed: Dict[str, Any], url: str) -> None:
    cs_match = _RE_RR_URL_CALLSIGN.search(url)
    if not cs_match:
        return
    callsign = cs_match.group(1).upper()
    parsed["fcc_callsign"] = callsign
    for freq in parsed.get("frequencies") or []:
        freq.setdefault("fcc_callsign", callsign)
        if parsed.get("licensee"):
            freq.setdefault("licensee", parsed["licensee"])


def parse_rr_html_by_url(html: str, lower_url: str) -> Optional[Dict[str, Any]]:
    """Dispatch HTML to the appropriate RR page parser based on URL path."""
    if "/fcc/callsign/" in lower_url:
        parsed = parse_rr_fcc_callsign(html)
        if parsed is not None:
            parsed["kind"] = "fcc_callsign"
            enrich_fcc_callsign_from_url(parsed, lower_url)
        return parsed
    if "/db/aid/" in lower_url or "/db/cid/" in lower_url:
        parsed = parse_rr_category_aid(html)
        if parsed is not None:
            parsed["kind"] = "category"
        return parsed
    if "/db/ctid/" in lower_url or "/db/browse/" in lower_url:
        parsed = parse_rr_conventional_ctid(html)
        if parsed is not None:
            parsed["kind"] = "conventional_multi"
        return parsed
    if "/db/sid/" in lower_url or "/db/tid/" in lower_url:
        parsed = parse_rr_trs_sid(html)
        if parsed is not None:
            parsed["kind"] = "trs"
        return parsed
    return None
