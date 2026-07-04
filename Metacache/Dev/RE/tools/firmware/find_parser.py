"""Hunt for the SUB-port command parser.

Searches an inflated SUB firmware blob for known command mnemonics
(MDL, VER, STS, U, h, GLT) and Ghidra string-table candidates.

Usage::

    py Metacache/Dev/RE/tools/firmware/find_parser.py
    py Metacache/Dev/RE/tools/firmware/find_parser.py --firmware path/to/sub_X_inflated.bin
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _common as _c  # noqa: E402

BASE = 0x14000000


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    _c.add_firmware_arg(p)
    p.add_argument(
        "--analysis-dump",
        type=Path,
        default=_c.FIRMWARE_DIR / "analysis_dump.json",
        help="Ghidra analysis dump JSON. Default: firmware/analysis_dump.json.",
    )
    args = p.parse_args()

    fw_path = _c.resolve_firmware(args)
    fw = fw_path.read_bytes()
    if args.analysis_dump.exists():
        data = json.loads(args.analysis_dump.read_text(encoding="utf-8"))
    else:
        print(f"# (no analysis dump at {args.analysis_dump} - skipping function/string sections)")
        data = {}
    return _do_scan(fw, data)


def _find_all(fw: bytes, needle: bytes) -> list[int]:
    out: list[int] = []
    i = 0
    while True:
        idx = fw.find(needle, i)
        if idx < 0:
            break
        out.append(idx)
        i = idx + 1
    return out


def _print_mnemonic_search(fw: bytes) -> None:
    print("=== Mnemonic byte-pattern search (raw firmware bytes) ===")
    for needle, label in [
        (b"MDL\0",   "MDL\\0 (null-terminated)"),
        (b"MDL,",    "MDL, (CSV-leading)"),
        (b"MDL\r",   "MDL\\r"),
        (b"MDL ",    "MDL (space)"),
        (b"VER\0",   "VER\\0"),
        (b"VER,",    "VER,"),
        (b"VER\r",   "VER\\r"),
        (b"STS\0",   "STS\\0"),
        (b"STS,",    "STS,"),
        (b"GLT,SYS", "GLT,SYS"),
        (b"GLT",     "GLT (any)"),
        (b"BCDx36HP", "BCDx36HP (model)"),
        (b"SDS100",  "SDS100"),
        (b"\0M\0D\0L\0", "MDL UTF-16"),
        (b"M\0D\0L",     "MDL UTF-16-no-null"),
    ]:
        hits = _find_all(fw, needle)
        print(f"  {label:30s} -> {len(hits)} hit(s)" + (f" at {[hex(BASE+h) for h in hits[:6]]}" if hits else ""))

    print()
    print("=== Context around 'MDL' bytes (any) ===")
    for idx in _find_all(fw, b"MDL"):
        ctx = fw[max(0, idx - 8):idx + 16]
        print(f"  +0x{idx:06X} (0x{BASE + idx:08X}): {ctx!r}")


def _print_short_mnemonics(data: dict) -> None:
    print()
    print("=== Short ASCII-mnemonic strings (3-6 chars, all uppercase A-Z) ===")
    mnem_strings = []
    for s in data.get("strings", []):
        v = s.get("value", "") or ""
        if 3 <= len(v) <= 6 and all('A' <= c <= 'Z' for c in v):
            mnem_strings.append((s.get("addr"), v, len(s.get("xrefs", []))))
    mnem_strings.sort()
    for addr, v, nx in mnem_strings[:80]:
        print(f"  {addr}  {v:6s}  xrefs={nx}")
    print(f"  total {len(mnem_strings)} short ASCII-mnemonic strings")


def _print_zero_caller_candidates(data: dict) -> None:
    print()
    print("=== Functions with 0 callers, sorted by size (parser candidates) ===")
    zc = [f for f in data.get("functions", []) if not f.get("callers")]
    zc.sort(key=lambda x: -x.get("size", 0))
    for f in zc[:15]:
        print(
            f"  {f['addr']}  {f['name']:25s}  size={f['size']:>5}  "
            f"callees={len(f.get('callees', []))}  periph={','.join(f.get('peripheral_accesses', [])) or '-'}"
        )


def _do_scan(fw: bytes, data: dict) -> int:
    _print_mnemonic_search(fw)
    _print_short_mnemonics(data)
    _print_zero_caller_candidates(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
