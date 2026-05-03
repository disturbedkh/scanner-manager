"""Characterise firmware binary structure.

Findings discovered while running this:
- Main .bin is opaque (3000+ random ASCII runs == random byte distribution)
- Sub .firm contains real plaintext strings

This script confirms format hypotheses with:
  - Entropy per 4 KiB chunk (high == encrypted/compressed; low == code/data)
  - First/last 256 bytes hex dump (looking for headers/footers, magic numbers,
    length fields, hash signatures)
  - Common magic-byte signature scan (LZMA, ZIP, ZLIB, ARM CM vector table, etc.)
  - Byte-level diff between consecutive versions of each MCU

Usage::

    py AI/Dev/RE/tools/firmware/firmware_structure.py
    py AI/Dev/RE/tools/firmware/firmware_structure.py --image main_2.00.00=path/to/V2_00_00.bin
"""
from __future__ import annotations

import argparse
import math
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _common as _c  # noqa: E402

RE_DIR = _c.RE_ROOT
FW_DIR = _c.FIRMWARE_DIR
OUT_DIR = _c.FIRMWARE_ANALYSIS_DIR
OUT_DIR.mkdir(parents=True, exist_ok=True)

_MAIN_RE = re.compile(r"SDS[-_]100_?V(\d+)_(\d+)_(\d+)\.bin$", re.IGNORECASE)
_SUB_RE = re.compile(r"SDS[-_]100[-_]SUB_?V(\d+)_(\d+)_(\d+)\.firm$", re.IGNORECASE)


def _autodiscover_images() -> dict[str, Path]:
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


IMAGES: dict[str, Path] = _autodiscover_images()

CHUNK = 4096


def shannon(buf: bytes) -> float:
    if not buf:
        return 0.0
    cnt = Counter(buf)
    n = len(buf)
    return -sum((c / n) * math.log2(c / n) for c in cnt.values())


def entropy_profile(path: Path) -> tuple[list[float], float]:
    data = path.read_bytes()
    chunks = [data[i:i + CHUNK] for i in range(0, len(data), CHUNK)]
    return [shannon(c) for c in chunks], shannon(data)


def hex_dump(buf: bytes, base: int = 0, width: int = 16) -> list[str]:
    out = []
    for off in range(0, len(buf), width):
        row = buf[off:off + width]
        h = " ".join(f"{b:02x}" for b in row)
        a = "".join(chr(b) if 32 <= b < 127 else "." for b in row)
        out.append(f"  {base + off:08x}  {h:<{width * 3}}  |{a}|")
    return out


def signature_scan(data: bytes) -> list[tuple[int, str]]:
    sigs = {
        b"\x5d\x00\x00":          "LZMA1 (literal context bits)",
        b"\x1f\x8b":              "gzip",
        b"\x78\x9c":              "zlib (default)",
        b"\x78\x01":              "zlib (low compression)",
        b"\x78\xda":              "zlib (best compression)",
        b"PK\x03\x04":            "ZIP local-file header",
        b"\x42\x5a\x68":          "bzip2",
        b"\xfd7zXZ":              "XZ",
        b"UBI#":                  "UBIFS",
        b"\xd0\xcf\x11\xe0":      "OLE2 / .doc",
        b"\x7fELF":               "ELF binary",
        b"MZ":                    "DOS / PE",
        b"UNIDEN":                "Uniden plaintext header",
        b"SDS100":                "SDS100 plaintext",
        b"BCDx36HP":              "BCDx36HP plaintext",
        b"\x00\x10\x00\x20":      "ARM Cortex-M reset vector candidate (initial SP at 0x20001000)",
        b"\x00\x00\x00\x20":      "ARM Cortex-M reset vector candidate (SP at 0x20000000)",
    }
    hits: list[tuple[int, str]] = []
    for sig, label in sigs.items():
        idx = -1
        while True:
            idx = data.find(sig, idx + 1)
            if idx < 0:
                break
            hits.append((idx, label))
            if len(hits) > 64:
                break
        if len(hits) > 64:
            break
    return sorted(hits)[:64]


def byte_diff_summary(a: bytes, b: bytes) -> tuple[int, int, list[tuple[int, int]]]:
    """Return (total_changed_bytes, total_runs, top_runs_by_size)."""
    if len(a) != len(b):
        return -1, -1, []
    changed = 0
    runs: list[tuple[int, int]] = []
    in_run = False
    run_start = 0
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            changed += 1
            if not in_run:
                in_run = True
                run_start = i
        else:
            if in_run:
                in_run = False
                runs.append((run_start, i - run_start))
    if in_run:
        runs.append((run_start, len(a) - run_start))
    runs.sort(key=lambda r: -r[1])
    return changed, len(runs), runs[:20]


def report() -> None:
    out = ["# Firmware structural analysis", ""]

    for label, path in IMAGES.items():
        if not path.exists():
            out.append(f"## {label}: MISSING ({path})")
            continue
        data = path.read_bytes()
        chunks_ent, full_ent = entropy_profile(path)
        out.append(f"## {label}")
        out.append("")
        out.append(f"- File: `{path.name}`")
        out.append(f"- Size: **{len(data):,}** bytes")
        out.append(f"- Whole-file Shannon entropy: **{full_ent:.4f}** bits/byte (max 8)")
        # entropy buckets
        high = sum(1 for e in chunks_ent if e >= 7.5)
        mid = sum(1 for e in chunks_ent if 4.0 <= e < 7.5)
        low = sum(1 for e in chunks_ent if e < 4.0)
        out.append(f"- 4 KiB chunk entropy: {high} high(>=7.5), {mid} mid, {low} low(<4) "
                   f"of {len(chunks_ent)} total")
        out.append("")
        out.append("### First 64 bytes")
        out.append("```")
        out.extend(hex_dump(data[:64]))
        out.append("```")
        out.append("")
        out.append("### Last 64 bytes")
        out.append("```")
        out.extend(hex_dump(data[-64:], base=len(data) - 64))
        out.append("```")
        out.append("")
        out.append("### Magic-byte signature hits (first 32)")
        sigs = signature_scan(data)[:32]
        if not sigs:
            out.append("- (none)")
        else:
            out.append("```")
            for off, label_s in sigs[:32]:
                out.append(f"  0x{off:08x}  {label_s}")
            out.append("```")
        out.append("")

    # Byte diffs - all consecutive version pairs within each family.
    pairs: list[tuple[str, str]] = []
    for fam in ("main_", "sub_"):
        members = sorted(label for label in IMAGES if label.startswith(fam))
        pairs.extend(zip(members, members[1:]))
    for a_label, b_label in pairs:
        a_path = IMAGES.get(a_label)
        b_path = IMAGES.get(b_label)
        if not a_path or not b_path or not a_path.exists() or not b_path.exists():
            continue
        a = a_path.read_bytes()
        b = b_path.read_bytes()
        out.append(f"## Byte-level diff: {a_label} -> {b_label}")
        out.append("")
        if len(a) != len(b):
            out.append(f"- Different sizes: {len(a):,} -> {len(b):,} bytes "
                       f"(delta {len(b) - len(a):+,})")
            out.append("- Cannot do byte-aligned diff directly. Skipping.")
            continue
        changed, runs, top = byte_diff_summary(a, b)
        pct = 100.0 * changed / len(a)
        out.append(f"- Same size: {len(a):,} bytes")
        out.append(f"- Bytes changed: **{changed:,}** "
                   f"({pct:.2f}% of file)")
        out.append(f"- Number of changed runs: **{runs}**")
        out.append("- Top 20 longest changed runs (offset, length):")
        out.append("")
        out.append("| Offset | Length | Pct of file |")
        out.append("| --- | --- | --- |")
        for off, length in top:
            out.append(f"| `0x{off:08x}` | {length:,} | {100.0 * length / len(a):.2f}% |")
        out.append("")

    rep_path = OUT_DIR / "firmware_structure_report.md"
    rep_path.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"Wrote {rep_path}")


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
    report()
    return 0


if __name__ == "__main__":
    sys.exit(main())
