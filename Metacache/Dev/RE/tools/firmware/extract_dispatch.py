"""Extract the SDS100 SUB MCU's uppercase-command dispatch table.

In SUB firmware 1.03.15, ``FUN_14008340`` looks up the first byte of
an incoming command in a 77-entry table at ``DAT_14008428``. Each
entry is 8 bytes:

    +0x0  byte    matching char
    +0x4  uint32  handler function pointer (Thumb, LSB=1)

This script:
1. Reads ``DAT_14008428`` from the firmware (or whichever address you
   pass via ``--table-ptr``).
2. Decodes the table.
3. Reports (mnemonic_byte, handler_addr, ascii_repr).

For new firmware versions, the literal-pool address may shift; pass
``--table-ptr 0x...`` to override the default.

Usage::

    py Metacache/Dev/RE/tools/firmware/extract_dispatch.py
    py Metacache/Dev/RE/tools/firmware/extract_dispatch.py --firmware path/to/sub_X_inflated.bin
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _common as _c  # noqa: E402

DEFAULT_TABLE_PTR_ADDR = 0x14008428
DEFAULT_LITPOOL_RANGE = (0x14008418, 0x14008448)
BASE = 0x14000000
SRAM_BASE = 0x10000000
SRAM_TO_FLASH = BASE - SRAM_BASE  # +0x04000000


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    _c.add_firmware_arg(p)
    p.add_argument("--table-ptr", type=lambda s: int(s, 0),
                   default=DEFAULT_TABLE_PTR_ADDR,
                   help="Address of the literal-pool word holding the "
                        "dispatch-table base pointer. Default: "
                        f"0x{DEFAULT_TABLE_PTR_ADDR:08X} (1.03.15 SUB).")
    p.add_argument("--litpool-range", nargs=2, type=lambda s: int(s, 0),
                   default=list(DEFAULT_LITPOOL_RANGE),
                   metavar=("START", "END"),
                   help="Literal-pool word range to dump for context.")
    p.add_argument("--max-entries", type=int, default=80,
                   help="How many table entries to scan before stopping.")
    args = p.parse_args()

    fw_path = _c.resolve_firmware(args)
    fw = fw_path.read_bytes()
    size = len(fw)
    print(f"# Firmware: {fw_path.relative_to(_c.REPO_ROOT)}  ({size:,} bytes)")

    def normalize(addr: int) -> int:
        if SRAM_BASE <= addr < SRAM_BASE + size:
            return addr + SRAM_TO_FLASH
        return addr

    def in_fw(addr: int) -> bool:
        a = normalize(addr & ~1)
        return BASE <= a < BASE + size

    def fw_word(addr: int) -> int:
        a = normalize(addr)
        return struct.unpack_from("<I", fw, a - BASE)[0]

    def fw_byte(addr: int) -> int:
        a = normalize(addr)
        return fw[a - BASE]

    lp_start, lp_end = args.litpool_range
    print(f"=== Literal pool (0x{lp_start:08X}..0x{lp_end:08X}) ===")
    for addr in range(lp_start, lp_end, 4):
        if BASE <= addr < BASE + size:
            print(f"  *0x{addr:08X} = 0x{fw_word(addr):08X}")

    table_ptr_addr: int = args.table_ptr
    table_base = fw_word(table_ptr_addr)
    print(f"\n=== Dispatch table (loaded from *0x{table_ptr_addr:08X} = 0x{table_base:08X}) ===")
    if not in_fw(table_base):
        print(f"  [!] Table address 0x{table_base:08X} is outside firmware range")
        return 1
    print(f"  Table base (flash equivalent): 0x{normalize(table_base):08X}")

    print(f"  {'idx':>3}  {'addr':<10}  {'byte':<5}  {'char':<6}  {'handler':<10}  notes")
    entries: list = []
    for i in range(args.max_entries):
        entry_addr = table_base + i * 8
        if not in_fw(entry_addr):
            break
        b0 = fw_byte(entry_addr)
        handler = fw_word(entry_addr + 4)
        char_repr = repr(chr(b0)) if 0x20 <= b0 < 0x7F else f"\\x{b0:02X}"
        h_norm = normalize(handler & ~1)
        if BASE <= h_norm < BASE + size:
            note = f"fn @ 0x{h_norm:08X}"
        else:
            note = f"out-of-fw (0x{handler:08X})"
        entries.append((i, entry_addr, b0, char_repr, handler, note))
        print(f"  {i:>3}  0x{entry_addr:08X}  0x{b0:02X}   {char_repr:<6}  0x{handler:08X}  {note}")

    print("\n=== Likely-real entries (handler is Thumb in firmware, byte is printable ASCII) ===")
    valid: list = []
    for i, _ea, b, ch, h, _note in entries:
        h_norm = normalize(h & ~1)
        if not (BASE <= h_norm < BASE + size):
            continue
        if (h & 1) != 1:
            continue
        if not (0x20 <= b < 0x7F):
            continue
        valid.append((i, b, ch, h_norm))
        print(f"  [{i:>2}] '{ch}' (0x{b:02X}) -> FUN_{h_norm:08x}")
    print(f"  Total: {len(valid)} valid entries")

    out = _c.SESSIONS_DIR / "dispatch_table_raw.md"
    _c.ensure_dir(out.parent)
    lines = ["# SUB-port dispatch table (extracted)", ""]
    lines.append(f"- Firmware: `{fw_path.relative_to(_c.REPO_ROOT)}`")
    lines.append(f"- Table base: 0x{table_base:08X}")
    lines.append(f"- Pointer literal: *0x{table_ptr_addr:08X}")
    lines.append(f"- Total entries scanned: {len(entries)}")
    lines.append(f"- Valid entries: {len(valid)}")
    lines.append("")
    lines.append("| idx | byte | char | handler addr |")
    lines.append("|---:|---:|---|---|")
    for i, b, ch, h in valid:
        lines.append(f"| {i} | 0x{b:02X} | `{ch}` | `FUN_{h:08x}` |")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n[+] Saved table to {out.relative_to(_c.REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
