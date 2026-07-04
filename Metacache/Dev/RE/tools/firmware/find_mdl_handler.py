"""Find the SUB function that handles MDL by locating literal-pool
references to the 'SDS100-SUB' identity string.

ARM Cortex-M Thumb code addresses string constants via
``LDR Rn, [PC, #imm]`` - the immediate value is a 32-bit constant in a
nearby literal pool. Look for those constants anywhere in the firmware
to find where the identity string is REFERENCED.

Usage::

    py Metacache/Dev/RE/tools/firmware/find_mdl_handler.py
    py Metacache/Dev/RE/tools/firmware/find_mdl_handler.py --firmware path/to/sub_X_inflated.bin
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _common as _c  # noqa: E402

BASE = 0x14000000
SRAM_TO_FLASH = 0x04000000

# These constants come from manually identifying the strings in the
# 1.03.15 SUB firmware. They will need updating for newer firmware
# versions; pass --targets to override.
DEFAULT_TARGETS: dict[int, str] = {
    0x10013290: "SDS100-SUB",
    0x10013234: "Version 1.03.15",
    0x1001322C: "Version 1.03.15 (incl prefix)",
}


def find_word_refs(fw: bytes, target_addr: int, *, only_aligned: bool = False) -> list[int]:
    target_le = struct.pack("<I", target_addr)
    out: list[int] = []
    i = 0
    while True:
        idx = fw.find(target_le, i)
        if idx < 0:
            break
        if only_aligned and idx % 4 != 0:
            i = idx + 1
            continue
        out.append(idx)
        i = idx + 1
    return out


def _load_analysis_funcs(dump_path: Path) -> list:
    if not dump_path.exists():
        print(f"# (no analysis dump at {dump_path} - function names suppressed)")
        return []
    data = json.loads(dump_path.read_text(encoding="utf-8"))
    return data.get("functions", [])


def _addr_to_func(funcs: list, addr: int) -> str:
    for f in funcs:
        body_min = int(f.get("addr"), 16)
        body_max = body_min + f.get("size", 0)
        if body_min <= addr < body_max:
            return f"{f['addr']} {f['name']} (size={f['size']})"
    return f"<unknown> at 0x{addr:08X}"


def _print_target_refs(fw: bytes, funcs: list, tgt: int, label: str) -> None:
    print(f"=== References to '{label}' (target 0x{tgt:08X}) ===")
    refs = find_word_refs(fw, tgt, only_aligned=False)
    if not refs:
        print("  (no references found)")
        return
    for r in refs:
        ref_addr = BASE + r
        aligned = "aligned" if r % 4 == 0 else "UNALIGNED"
        print(f"  literal-pool entry at 0x{ref_addr:08X} ({aligned}) -> in {_addr_to_func(funcs, ref_addr)}")
    print()


def _print_value_refs(fw: bytes, funcs: list, value: int) -> None:
    for r in find_word_refs(fw, value, only_aligned=True):
        ref_addr = BASE + r
        print(f"  0x{value:08X} referenced at 0x{ref_addr:08X} in {_addr_to_func(funcs, ref_addr)}")


def _print_scan_range_refs(fw: bytes, funcs: list, start: int, end: int) -> None:
    print(f"=== Any 32-bit value in 0x{start:08X}..0x{end:08X} referenced from firmware ===")
    for v in range(start, end, 4):
        _print_value_refs(fw, funcs, v)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    _c.add_firmware_arg(p)
    p.add_argument(
        "--analysis-dump",
        type=Path,
        default=_c.FIRMWARE_DIR / "analysis_dump.json",
        help="Ghidra analysis dump JSON. Default: firmware/analysis_dump.json.",
    )
    p.add_argument(
        "--scan-range",
        nargs=2,
        type=lambda s: int(s, 0),
        default=(0x1001321C, 0x100132A0),
        metavar=("START", "END"),
        help="Inclusive 4-byte-aligned word range to also scan for any "
             "string references in (defaults to literal-pool window "
             "around the SDS100-SUB identity strings).",
    )
    args = p.parse_args()

    fw_path = _c.resolve_firmware(args)
    fw = fw_path.read_bytes()
    print(f"# Scanning {fw_path.relative_to(_c.REPO_ROOT)}  ({len(fw):,} bytes)")

    funcs = _load_analysis_funcs(args.analysis_dump)

    for tgt, label in DEFAULT_TARGETS.items():
        _print_target_refs(fw, funcs, tgt, label)

    start, end = args.scan_range
    _print_scan_range_refs(fw, funcs, start, end)
    return 0


if __name__ == "__main__":
    sys.exit(main())
