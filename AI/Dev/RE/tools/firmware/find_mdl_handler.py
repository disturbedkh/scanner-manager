"""Find the SUB function that handles MDL by locating literal-pool
references to the 'SDS100-SUB' identity string.

ARM Cortex-M Thumb code addresses string constants via
``LDR Rn, [PC, #imm]`` - the immediate value is a 32-bit constant in a
nearby literal pool. Look for those constants anywhere in the firmware
to find where the identity string is REFERENCED.

Usage::

    py AI/Dev/RE/tools/firmware/find_mdl_handler.py
    py AI/Dev/RE/tools/firmware/find_mdl_handler.py --firmware path/to/sub_X_inflated.bin
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

    if args.analysis_dump.exists():
        data = json.loads(args.analysis_dump.read_text(encoding="utf-8"))
        funcs = data.get("functions", [])
    else:
        print(f"# (no analysis dump at {args.analysis_dump} - function names suppressed)")
        funcs = []

    def addr_to_func(addr: int) -> str:
        for f in funcs:
            body_min = int(f.get("addr"), 16)
            body_max = body_min + f.get("size", 0)
            if body_min <= addr < body_max:
                return f"{f['addr']} {f['name']} (size={f['size']})"
        return f"<unknown> at 0x{addr:08X}"

    for tgt, label in DEFAULT_TARGETS.items():
        print(f"=== References to '{label}' (target 0x{tgt:08X}) ===")
        refs = find_word_refs(fw, tgt, only_aligned=False)
        if not refs:
            print("  (no references found)")
            continue
        for r in refs:
            ref_addr = BASE + r
            aligned = "aligned" if r % 4 == 0 else "UNALIGNED"
            print(f"  literal-pool entry at 0x{ref_addr:08X} ({aligned}) -> in {addr_to_func(ref_addr)}")
        print()

    start, end = args.scan_range
    print(f"=== Any 32-bit value in 0x{start:08X}..0x{end:08X} referenced from firmware ===")
    for v in range(start, end, 4):
        refs = find_word_refs(fw, v, only_aligned=True)
        if refs:
            for r in refs:
                print(f"  0x{v:08X} referenced at 0x{BASE + r:08X} in {addr_to_func(BASE + r)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
