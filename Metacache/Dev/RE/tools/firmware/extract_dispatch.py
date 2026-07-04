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


def _normalize_addr(addr: int, fw_size: int) -> int:
    if SRAM_BASE <= addr < SRAM_BASE + fw_size:
        return addr + SRAM_TO_FLASH
    return addr


def _in_fw(addr: int, fw_size: int) -> bool:
    normalized = _normalize_addr(addr & ~1, fw_size)
    return BASE <= normalized < BASE + fw_size


def _fw_word(fw: bytes, addr: int, fw_size: int) -> int:
    normalized = _normalize_addr(addr, fw_size)
    return struct.unpack_from("<I", fw, normalized - BASE)[0]


def _fw_byte(fw: bytes, addr: int, fw_size: int) -> int:
    normalized = _normalize_addr(addr, fw_size)
    return fw[normalized - BASE]


def _dump_literal_pool(
    fw_word,
    *,
    lp_start: int,
    lp_end: int,
    size: int,
) -> None:
    print(f"=== Literal pool (0x{lp_start:08X}..0x{lp_end:08X}) ===")
    for addr in range(lp_start, lp_end, 4):
        if BASE <= addr < BASE + size:
            print(f"  *0x{addr:08X} = 0x{fw_word(addr):08X}")


def _dispatch_entry_note(handler: int, h_norm: int, fw_size: int) -> str:
    if BASE <= h_norm < BASE + fw_size:
        return f"fn @ 0x{h_norm:08X}"
    return f"out-of-fw (0x{handler:08X})"


def _char_repr(b0: int) -> str:
    return repr(chr(b0)) if 0x20 <= b0 < 0x7F else f"\\x{b0:02X}"


def _scan_dispatch_entries(
    *,
    table_base: int,
    max_entries: int,
    fw_size: int,
    in_fw,
    fw_byte,
    fw_word,
    normalize,
) -> tuple[list, list]:
    print(f"  {'idx':>3}  {'addr':<10}  {'byte':<5}  {'char':<6}  {'handler':<10}  notes")
    entries: list = []
    for i in range(max_entries):
        entry_addr = table_base + i * 8
        if not in_fw(entry_addr):
            break
        b0 = fw_byte(entry_addr)
        handler = fw_word(entry_addr + 4)
        char_repr = _char_repr(b0)
        h_norm = normalize(handler & ~1)
        note = _dispatch_entry_note(handler, h_norm, fw_size)
        entries.append((i, entry_addr, b0, char_repr, handler, note))
        print(f"  {i:>3}  0x{entry_addr:08X}  0x{b0:02X}   {char_repr:<6}  0x{handler:08X}  {note}")
    return entries, _valid_dispatch_entries(entries, fw_size, normalize)


def _valid_dispatch_entries(entries: list, fw_size: int, normalize) -> list:
    valid: list = []
    print("\n=== Likely-real entries (handler is Thumb in firmware, byte is printable ASCII) ===")
    for i, _ea, b, ch, h, _note in entries:
        h_norm = normalize(h & ~1)
        if not (BASE <= h_norm < BASE + fw_size):
            continue
        if (h & 1) != 1:
            continue
        if not (0x20 <= b < 0x7F):
            continue
        valid.append((i, b, ch, h_norm))
        print(f"  [{i:>2}] '{ch}' (0x{b:02X}) -> FUN_{h_norm:08x}")
    print(f"  Total: {len(valid)} valid entries")
    return valid


def _write_dispatch_report(
    *,
    out: Path,
    fw_path: Path,
    table_base: int,
    table_ptr_addr: int,
    entries: list,
    valid: list,
) -> None:
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
        return _normalize_addr(addr, size)

    def in_fw(addr: int) -> bool:
        return _in_fw(addr, size)

    def fw_word(addr: int) -> int:
        return _fw_word(fw, addr, size)

    def fw_byte(addr: int) -> int:
        return _fw_byte(fw, addr, size)

    lp_start, lp_end = args.litpool_range
    _dump_literal_pool(fw_word, lp_start=lp_start, lp_end=lp_end, size=size)

    table_ptr_addr: int = args.table_ptr
    table_base = fw_word(table_ptr_addr)
    print(f"\n=== Dispatch table (loaded from *0x{table_ptr_addr:08X} = 0x{table_base:08X}) ===")
    if not in_fw(table_base):
        print(f"  [!] Table address 0x{table_base:08X} is outside firmware range")
        return 1
    print(f"  Table base (flash equivalent): 0x{normalize(table_base):08X}")

    entries, valid = _scan_dispatch_entries(
        table_base=table_base,
        max_entries=args.max_entries,
        fw_size=size,
        in_fw=in_fw,
        fw_byte=fw_byte,
        fw_word=fw_word,
        normalize=normalize,
    )

    out = _c.SESSIONS_DIR / "dispatch_table_raw.md"
    _write_dispatch_report(
        out=out,
        fw_path=fw_path,
        table_base=table_base,
        table_ptr_addr=table_ptr_addr,
        entries=entries,
        valid=valid,
    )
    print(f"\n[+] Saved table to {out.relative_to(_c.REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
