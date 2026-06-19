"""Cross-correlate live probe responses with SUB firmware strings.

For each probe response captured during a sub_probe / serial_probe
session, search the SUB firmware string-table and the raw payload for
matching format strings, command mnemonics, and response shape
patterns.

Usage::

    py Metacache/Dev/RE/tools/firmware/correlate_responses.py
    py Metacache/Dev/RE/tools/firmware/correlate_responses.py \\
        --firmware path/to/sub_X_inflated.bin \\
        --strings  path/to/sub_X.strings.txt
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _common as _c  # noqa: E402

RE_DIR = _c.RE_ROOT
SESSIONS_DIR = _c.SESSIONS_DIR
FW_DIR = _c.FIRMWARE_DIR

# Regex to extract HIT entries from sub_probe session logs.
# Format: "[%5d/%5d]  HIT      %-8s  %4dB in %6.1f ms  | <show>"
SUB_HIT_RE = re.compile(
    r"HIT\s+(\S+)\s+\d+B\s+in\s+[\d.]+\s+ms\s+\|\s+(.+)",
    re.MULTILINE,
)

# Regex to extract HIT entries from serial_probe session logs (MAIN port).
# Format varies; we look for "<<< name=cmd  bytes=N  raw=...".
MAIN_RESPONSE_RE = re.compile(
    r"^>>>\s+(\w+)\s*=?\s*(\S+).*?\n.*?<<<.*?\|\s*(.+?)$",
    re.MULTILINE | re.DOTALL,
)


def collect_sub_hits() -> list[tuple[str, str]]:
    """Return list of (command, response_show) pairs from sub_probe logs."""
    hits: list[tuple[str, str]] = []
    seen: set[str] = set()
    for log in sorted(SESSIONS_DIR.glob("sub_probe_*.txt")):
        if "summary" in log.name or "stdout" in log.name:
            continue
        text = log.read_text(encoding="utf-8", errors="replace")
        for cmd, resp in SUB_HIT_RE.findall(text):
            key = f"{cmd}|{resp}"
            if key in seen:
                continue
            seen.add(key)
            hits.append((cmd, resp))
    return hits


def load_strings(strings_file: Path) -> list[str]:
    """Return non-empty lines from the Sub strings dump."""
    if not strings_file.exists():
        return []
    return [
        line.strip()
        for line in strings_file.read_text(encoding="utf-8", errors="replace").splitlines()
        if line.strip()
    ]


def fmt_to_regex(fmt: str) -> re.Pattern | None:
    """Convert a printf-style format string to a regex matching its
    expected output. Returns None if the format has no specifiers."""
    # Tokenize into literals and conversion specs.
    parts: list[str] = []
    i = 0
    has_spec = False
    while i < len(fmt):
        c = fmt[i]
        if c == "%":
            if i + 1 < len(fmt) and fmt[i + 1] == "%":
                parts.append("%")
                i += 2
                continue
            # match %[flags][width][.precision][length]conv
            m = re.match(r"%([-+ #0]*)(\d+)?(\.\d+)?([hljztL]*)([diouxXeEfgGsc])", fmt[i:])
            if not m:
                parts.append(re.escape(c))
                i += 1
                continue
            has_spec = True
            _flags, _width, _prec, _length, conv = m.groups()
            if conv in ("d", "i"):
                parts.append(r"-?\s*\d+")
            elif conv in ("u", "o"):
                parts.append(r"\d+")
            elif conv in ("x", "X"):
                parts.append(r"[0-9a-fA-F]+")
            elif conv in ("e", "E", "f", "g", "G"):
                parts.append(r"-?\d+(?:\.\d+)?(?:[eE]-?\d+)?")
            elif conv == "c":
                parts.append(r".")
            elif conv == "s":
                parts.append(r"\S+")
            else:
                parts.append(r"\S+")
            i += m.end()
        else:
            parts.append(re.escape(c))
            i += 1
    if not has_spec:
        return None
    pattern = "".join(parts)
    try:
        return re.compile(pattern)
    except re.error:
        return None


def find_mnemonic_in_payload(mnemonic: str, payload: bytes) -> list[int]:
    """Return offsets where the mnemonic appears as a NUL-terminated
    ASCII string in the firmware payload. Looks for `<MNEMONIC>\\0`."""
    needle = mnemonic.encode("ascii") + b"\x00"
    out: list[int] = []
    i = 0
    while True:
        j = payload.find(needle, i)
        if j < 0:
            break
        out.append(j)
        i = j + 1
    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    _c.add_firmware_arg(p)
    p.add_argument("--strings", type=Path, default=None,
                   help="SUB strings dump (.strings.txt). Default: latest "
                        "sub_*.strings.txt in firmware_analysis/.")
    p.add_argument("--output", "-o", type=Path,
                   default=_c.DOCS_DIR / "sub_command_response_map.md",
                   help="Markdown output path. Default: "
                        "Metacache/Dev/RE/docs/sub_command_response_map.md.")
    args = p.parse_args()

    fw_path = _c.resolve_firmware(args)
    payload = fw_path.read_bytes()
    strings_file = args.strings or _c.find_latest_sub_strings()
    if not strings_file:
        sys.exit("[X] No SUB strings dump found. Generate with "
                 "tools/firmware/firmware_strings.py first.")
    OUT_MAP = args.output
    OUT_MAP.parent.mkdir(parents=True, exist_ok=True)
    sub_hits = collect_sub_hits()
    strings = load_strings(strings_file)

    print(f"# Loaded {len(sub_hits)} unique SUB-probe hits")
    print(f"# Loaded {len(strings)} Sub firmware strings")
    print(f"# Loaded {len(payload)} byte Sub payload")

    # Pre-compile all format-string regexes from firmware strings.
    fmt_patterns: list[tuple[str, re.Pattern]] = []
    for s in strings:
        pat = fmt_to_regex(s)
        if pat is not None:
            fmt_patterns.append((s, pat))
    print(f"# {len(fmt_patterns)} firmware strings have printf specifiers")

    # For each SUB hit, try every format pattern.
    matches: list[dict] = []
    for cmd, resp in sub_hits:
        # The "show" representation has \r escaped. Convert back so the
        # printf regexes can match raw \r-terminated content.
        cleaned = resp.replace("\\r", "\r").replace("\\n", "\n").replace("\\t", "\t")
        # Drop the <\xHH> escapes for matching purposes.
        cleaned = re.sub(r"<\\x[0-9A-Fa-f]{2}>", "?", cleaned)

        per_cmd_matches: list[str] = []
        for fmt, pat in fmt_patterns:
            if pat.search(cleaned):
                per_cmd_matches.append(fmt)

        # Look up the mnemonic itself in the firmware payload.
        head = cmd.split(",", 1)[0]
        offsets = find_mnemonic_in_payload(head, payload)

        matches.append({
            "cmd": cmd,
            "response": resp,
            "matched_strings": per_cmd_matches,
            "mnemonic_offsets": offsets,
        })

    # Print a quick on-screen summary.
    n_with_match = sum(1 for m in matches if m["matched_strings"])
    n_with_xref = sum(1 for m in matches if m["mnemonic_offsets"])
    print(f"# {n_with_match} commands matched a firmware format string")
    print(f"# {n_with_xref} commands have their mnemonic in the firmware payload")

    # Write output map.
    with open(OUT_MAP, "w", encoding="utf-8") as f:
        f.write("# Sub command -> firmware string correlation map\n\n")
        f.write(
            "Generated by `_correlate_responses.py` from Phase 1-3 session "
            "logs and the Sub firmware strings table.\n\n"
        )
        f.write(f"- SUB-probe unique hits: {len(sub_hits)}\n")
        f.write(f"- Sub firmware strings: {len(strings)}\n")
        f.write(f"- Format strings (with %specifiers): {len(fmt_patterns)}\n")
        f.write(f"- Hits with response matching a format string: {n_with_match}\n")
        f.write(f"- Hits with mnemonic xref in payload: {n_with_xref}\n\n")

        f.write("## Per-command join\n\n")
        f.write("| Cmd | Response | Format-string matches | Payload offsets |\n")
        f.write("| --- | --- | --- | --- |\n")
        for m in matches:
            cmd = f"`{m['cmd']}`"
            resp = m["response"][:60].replace("|", "\\|")
            fs = "; ".join(f"`{s}`" for s in m["matched_strings"][:3])
            if len(m["matched_strings"]) > 3:
                fs += f" (+{len(m['matched_strings']) - 3} more)"
            offs = ", ".join(f"`0x{o:05x}`" for o in m["mnemonic_offsets"][:5])
            if len(m["mnemonic_offsets"]) > 5:
                offs += f" (+{len(m['mnemonic_offsets']) - 5})"
            f.write(f"| {cmd} | `{resp}` | {fs or '-'} | {offs or '-'} |\n")

        f.write("\n## Unmatched format strings (hypothesis targets)\n\n")
        f.write(
            "Format strings present in the Sub firmware that are NOT yet "
            "triggered by a known command. These are high-value probe "
            "targets - the existence of a printf format implies code "
            "somewhere prints it; finding the trigger gives us a new "
            "command.\n\n"
        )
        triggered_fmts = set()
        for m in matches:
            triggered_fmts.update(m["matched_strings"])
        untriggered = [
            (fmt, pat) for fmt, pat in fmt_patterns if fmt not in triggered_fmts
        ]
        f.write(f"- Total format strings: {len(fmt_patterns)}\n")
        f.write(f"- Triggered: {len(fmt_patterns) - len(untriggered)}\n")
        f.write(f"- Untriggered: {len(untriggered)}\n\n")
        f.write("| Format string |\n")
        f.write("| --- |\n")
        for fmt, _pat in untriggered:
            short = fmt.replace("|", "\\|")[:120]
            f.write(f"| `{short}` |\n")

    print(f"# Wrote {OUT_MAP}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
