"""Static RE pass: extract strings + diff + scan for command surface.

Walks every MAIN/SUB firmware image found in
``Metacache/Dev/RE/firmware/`` (auto-discovered from filename patterns; pass
``--image LABEL=PATH`` to add or override entries) and emits:

  - ``<label>.strings.txt``   : every ASCII run >= MIN_LEN, deduped
  - ``<old>_to_<new>.added.txt`` / ``.removed.txt`` for each
    consecutive version pair within MAIN and SUB.
  - ``command_surface_report.md``: 3-letter uppercase tokens that look
    like Remote Command Protocol mnemonics, with spec-coverage notes.

Read-only. No network, no scanner contact.

Usage::

    py Metacache/Dev/RE/tools/firmware/firmware_strings.py
    py Metacache/Dev/RE/tools/firmware/firmware_strings.py \\
        --image main_2.00.00=path/to/SDS-100_V2_00_00.bin
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _common as _c  # noqa: E402

RE_DIR = _c.RE_ROOT
FW_DIR = _c.FIRMWARE_DIR
OUT_DIR = _c.FIRMWARE_ANALYSIS_DIR
OUT_DIR.mkdir(parents=True, exist_ok=True)

MIN_LEN = 6
ASCII_RUN = re.compile(rb"[\x20-\x7e]{%d,}" % MIN_LEN)
CMD_TOKEN = re.compile(r"^[A-Z][A-Z0-9_]{1,5}$")

# Filename patterns we use to auto-discover firmware versions in
# Metacache/Dev/RE/firmware/. Add/override at runtime via --image LABEL=PATH.
_MAIN_RE = re.compile(r"SDS[-_]100_?V(\d+)_(\d+)_(\d+)\.bin$", re.IGNORECASE)
_SUB_RE = re.compile(r"SDS[-_]100[-_]SUB_?V(\d+)_(\d+)_(\d+)\.firm$", re.IGNORECASE)


def _autodiscover_images() -> dict[str, Path]:
    """Scan ``firmware/`` (and one-level subdirs) for firmware blobs."""
    images: dict[str, Path] = {}
    if not FW_DIR.exists():
        return images
    for p in list(FW_DIR.rglob("*.bin")) + list(FW_DIR.rglob("*.firm")):
        m = _MAIN_RE.search(p.name)
        if m:
            images[f"main_{m.group(1)}.{m.group(2).zfill(2)}.{m.group(3).zfill(2)}"] = p
            continue
        m = _SUB_RE.search(p.name)
        if m:
            images[f"sub_{m.group(1)}.{m.group(2).zfill(2)}.{m.group(3).zfill(2)}"] = p
    return images


# Default image dict, overridable via CLI.
IMAGES: dict[str, Path] = _autodiscover_images()

V102_SPEC_COMMANDS = {
    "MDL", "VER", "KEY", "QSH", "STS", "JNT", "NXT", "PRV", "FQK",
    "SQK", "DQK", "PSI", "GSI", "GLT", "HLD", "AVD", "SVC", "JPM",
    "DTM", "LCR", "AST", "APR", "URC", "MNU", "MSI", "MSV", "MSB",
    "GST", "PWF", "GWF",
}
V200_NEW = {"GW2", "KAL", "POF", "GCS", "VOL", "SQL"}
INHERITED_BCDX36HP = {"GLG", "PWR", "VOL", "SQL"}

ALL_KNOWN = V102_SPEC_COMMANDS | V200_NEW | INHERITED_BCDX36HP


def extract_strings(path: Path) -> list[str]:
    data = path.read_bytes()
    seen: set[str] = set()
    out: list[str] = []
    for m in ASCII_RUN.finditer(data):
        s = m.group().decode("ascii", errors="replace")
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def write_strings_files() -> dict[str, set[str]]:
    sets: dict[str, set[str]] = {}
    for label, path in IMAGES.items():
        if not path.exists():
            print(f"!! missing: {path}")
            continue
        strings = extract_strings(path)
        sets[label] = set(strings)
        out_path = OUT_DIR / f"{label}.strings.txt"
        out_path.write_text(
            "\n".join(strings) + "\n", encoding="utf-8", errors="replace"
        )
        print(f"{label}: {len(strings):,} unique strings -> {out_path.name}")
    return sets


def diff_set(old_label: str, new_label: str, sets: dict[str, set[str]]) -> None:
    if old_label not in sets or new_label not in sets:
        return
    added = sorted(sets[new_label] - sets[old_label])
    removed = sorted(sets[old_label] - sets[new_label])
    base = f"{old_label.split('_', 1)[0]}_{old_label.split('_', 1)[1]}_to_{new_label.split('_', 1)[1]}"
    (OUT_DIR / f"{base}.added.txt").write_text(
        "\n".join(added) + "\n", encoding="utf-8", errors="replace"
    )
    (OUT_DIR / f"{base}.removed.txt").write_text(
        "\n".join(removed) + "\n", encoding="utf-8", errors="replace"
    )
    print(f"  {old_label} -> {new_label}:  +{len(added):4d} added,  -{len(removed):4d} removed")


def scan_command_tokens(strings: set[str]) -> dict[str, list[str]]:
    """Find uppercase 3-letter tokens that appear as standalone words and
    look like protocol mnemonics. We collect surrounding context to score."""
    candidates: dict[str, list[str]] = {}
    for s in strings:
        for tok in re.findall(r"\b[A-Z][A-Z0-9_]{1,5}\b", s):
            if not CMD_TOKEN.match(tok):
                continue
            candidates.setdefault(tok, []).append(s)
    return candidates


def write_command_report(sets: dict[str, set[str]]) -> None:
    """Cross-reference all-caps tokens in firmware vs known spec commands."""
    main_new = sets.get("main_1.26.01", set())
    cands = scan_command_tokens(main_new)
    lines = [
        "# Firmware command-surface scan",
        "",
        "Tokens that look like Remote Command Protocol mnemonics, found",
        "in the **Main 1.26.01** firmware string table. Cross-referenced",
        "against V1.02 + V2.00 spec command lists. Tokens with many",
        "false-positive contexts are noise; tokens with few contexts are",
        "high-signal candidates for undocumented commands.",
        "",
        "## Known spec commands present in firmware strings",
        "",
        "| Token | V1.02 | V2.00 | BCDx36HP | First context |",
        "| --- | --- | --- | --- | --- |",
    ]
    known_seen: dict[str, str] = {}
    unknown: list[tuple[str, list[str]]] = []
    for tok in sorted(cands):
        ctxs = cands[tok]
        ctx0 = ctxs[0][:60].replace("|", "\\|")
        if tok in V102_SPEC_COMMANDS:
            v102 = "yes"
        else:
            v102 = ""
        if tok in V200_NEW:
            v200 = "yes"
        else:
            v200 = ""
        if tok in INHERITED_BCDX36HP:
            inh = "yes"
        else:
            inh = ""
        if tok in ALL_KNOWN:
            known_seen[tok] = ctx0
            lines.append(f"| `{tok}` | {v102} | {v200} | {inh} | `{ctx0}` |")
        else:
            unknown.append((tok, ctxs))
    lines.append("")
    lines.append("## Unknown 3-6 char uppercase tokens (raw firmware strings)")
    lines.append("")
    lines.append("Most are noise (variable names, bitmask labels, file-format")
    lines.append("type tags). The interesting ones are 3-letter standalone")
    lines.append("tokens that don't decode to anything obvious from English.")
    lines.append("")
    lines.append("| Token | hits | First 3 contexts |")
    lines.append("| --- | --- | --- |")
    for tok, ctxs in sorted(unknown, key=lambda kv: (-len(kv[1]), kv[0])):
        if len(tok) > 6:
            continue
        ctxs_str = " // ".join(c[:50].replace("|", "\\|") for c in ctxs[:3])
        lines.append(f"| `{tok}` | {len(ctxs)} | `{ctxs_str}` |")
    lines.append("")
    lines.append("## Known commands NOT seen as standalone tokens")
    lines.append("")
    missing = sorted(ALL_KNOWN - set(known_seen))
    for tok in missing:
        lines.append(f"- `{tok}` (no match)")
    (OUT_DIR / "command_surface_report.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8", errors="replace"
    )
    print(f"command_surface_report.md  ({len(cands):,} tokens scanned, "
          f"{len(known_seen)} known, {len(unknown)} unknown)")


def _consecutive_pairs(labels: list[str]) -> list[tuple[str, str]]:
    """Sort labels of the same family by version and return consecutive
    (older, newer) pairs."""
    pairs: list[tuple[str, str]] = []
    for fam in ("main_", "sub_"):
        members = sorted(label for label in labels if label.startswith(fam))
        for older, newer in zip(members, members[1:]):
            pairs.append((older, newer))
    return pairs


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--image", action="append", default=[], metavar="LABEL=PATH",
                   help="Add or override an image. May be repeated.")
    args = p.parse_args()

    for spec in args.image:
        if "=" not in spec:
            sys.exit(f"[X] --image expects LABEL=PATH, got {spec!r}")
        label, _, path = spec.partition("=")
        IMAGES[label.strip()] = Path(path.strip())

    if not IMAGES:
        sys.exit(
            f"[X] No firmware images found. Place SDS-100_V*.bin / "
            f"SDS-100-SUB_V*.firm in {FW_DIR}, or use --image."
        )

    print(f"=== Extracting strings from {len(IMAGES)} image(s) ===")
    sets = write_strings_files()
    print("\n=== Diffing consecutive versions ===")
    for older, newer in _consecutive_pairs(list(sets.keys())):
        diff_set(older, newer, sets)
    print("\n=== Command-surface scan ===")
    write_command_report(sets)
    print(f"\nDone. Outputs in {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
