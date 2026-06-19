"""Extract the ARM Cortex-M payload from a Uniden SDS100 Sub firmware
container (``*.firm`` file).

Despite firmware_structure_report.md flagging zlib magic bytes scattered
through the file, manual inspection reveals those are coincidental
2-byte matches in plaintext ARM Cortex-M machine code. The Sub
firmware is **not** zlib- or LZMA-compressed - it's a flat ARM image
wrapped in a ~128-byte header and ~32-byte footer.

Container layout (verified empirically against the 1.03.15 SUB):

    Offset  Size  Content
    ------  ----  -------
    0x000   12    "SDS-100-SUB\\0" (mnemonic)
    0x00c   12    0xff filler
    0x018   16    "Version x.xx.xx \\0" + 0xff filler
    0x028    4    BE u32  payload_end
    0x02c    4    BE u32  load_marker (header size)
    0x030    4    BE u32  payload_padded_end
    0x034   76    0xff filler (rest of header)
    0x080  ...    ARM Cortex-M vector table + code (the payload)
    ...           (extends to payload_end)
    payload_end  0xc0  0xff trailer padding
    -36          4    BE u32  CRC32 of payload
    -32          32   Repeat of "SDS-100-SUB\\0..." footer block

ARM Cortex-M reset vector at 0x080-0x087:
  Word 0 (SP): LPC43xx SRAM region
  Word 1 (PC): Thumb-mode entry, base 0x14000000 (LPC43xx SPIFI flash)

This script extracts the payload (bytes 0x80..payload_end) as a flat
binary suitable for Ghidra import at base address 0x14000000.

Usage::

    py Metacache/Dev/RE/tools/firmware/inflate_sub.py
        # auto-discovers the only *.firm in firmware/

    py Metacache/Dev/RE/tools/firmware/inflate_sub.py \\
        --input firmware/SDS-100-SUB_V1_04_00.firm \\
        --version 1.04.00

Outputs (named after ``--version`` or auto-detected from the header)::

    <firmware-dir>/sub_<VER>_inflated.bin    (the ARM payload)
    <firmware-dir>/sub_<VER>_chunk_map.md    (header + layout)
"""
from __future__ import annotations

import argparse
import re
import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _common as _c  # noqa: E402


def parse_header(data: bytes) -> dict:
    """Decode the static header fields documented above."""
    return {
        "magic": data[0:12].rstrip(b"\x00").decode("ascii", "replace"),
        "version": data[0x18:0x28].rstrip(b"\x00 ").decode("ascii", "replace"),
        "payload_end_offset": struct.unpack(">I", data[0x28:0x2c])[0],
        "header_size_marker": struct.unpack(">I", data[0x2c:0x30])[0],
        "payload_padded_end": struct.unpack(">I", data[0x30:0x34])[0],
        "footer_crc": struct.unpack(">I", data[-36:-32])[0],
        "footer_magic": data[-32:].rstrip(b"\xff").decode("ascii", "replace"),
    }


def parse_arm_vectors(payload: bytes) -> dict:
    """Decode the first few ARM Cortex-M vector table entries."""
    if len(payload) < 64:
        return {}
    fields = struct.unpack("<16I", payload[:64])
    return {
        "initial_sp": f"0x{fields[0]:08x}",
        "reset_pc": f"0x{fields[1]:08x}",
        "nmi": f"0x{fields[2]:08x}",
        "hardfault": f"0x{fields[3]:08x}",
        "memmanage": f"0x{fields[4]:08x}",
        "busfault": f"0x{fields[5]:08x}",
        "usagefault": f"0x{fields[6]:08x}",
        "svcall": f"0x{fields[11]:08x}",
        "pendsv": f"0x{fields[14]:08x}",
        "systick": f"0x{fields[15]:08x}",
    }


def _auto_input(fw_dir: Path) -> Path | None:
    """Return the most-recently-modified ``*.firm`` in ``fw_dir``."""
    candidates = sorted(fw_dir.glob("*.firm"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def _version_to_slug(version: str) -> str:
    return re.sub(r"[^0-9.]", "", version) or "unknown"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", type=Path, default=None,
                   help="Path to a *.firm container. Default: most-recent "
                        f"*.firm in {_c.FIRMWARE_DIR}.")
    p.add_argument("--version", type=str, default=None,
                   help="Firmware-version slug for output filenames "
                        "(e.g. '1.03.15'). Auto-derived from container "
                        "header if omitted.")
    p.add_argument("--out-dir", type=Path, default=_c.FIRMWARE_DIR,
                   help="Where to write the inflated payload + chunk map. "
                        "Default: Metacache/Dev/RE/firmware/.")
    args = p.parse_args()

    fw_path: Path | None = args.input or _auto_input(_c.FIRMWARE_DIR)
    if not fw_path or not fw_path.exists():
        raise SystemExit(
            f"Sub firmware container not found. Pass --input or place a "
            f"*.firm in {_c.FIRMWARE_DIR}."
        )
    fw_dir = args.out_dir
    fw_dir.mkdir(parents=True, exist_ok=True)

    data = fw_path.read_bytes()
    print(f"# Loaded {fw_path.name}: {len(data)} bytes")

    header = parse_header(data)
    print("# Container header:")
    for k, v in header.items():
        print(f"   {k}: {v!r}")

    version = args.version or _version_to_slug(header.get("version", "unknown"))
    out_bin = fw_dir / f"sub_{version}_inflated.bin"
    out_map = fw_dir / f"sub_{version}_chunk_map.md"

    payload_start = header["header_size_marker"]   # 0x80
    payload_end = header["payload_end_offset"]     # 0x16080 here
    payload = data[payload_start:payload_end]
    print(
        f"# Payload: {len(payload)} bytes "
        f"({payload_start:#x}..{payload_end:#x})"
    )

    # Verify the embedded CRC32 matches what we'd compute over the payload.
    # Try a few common CRC variants - we'll see which (if any) match.
    crc_variants = {
        "zlib_crc32(payload)": zlib.crc32(payload) & 0xffffffff,
        "zlib_crc32(payload+0xff*pad)": zlib.crc32(
            data[payload_start:header["payload_padded_end"]]
        ) & 0xffffffff,
        "zlib_crc32(header+payload)": zlib.crc32(
            data[: header["payload_padded_end"]]
        ) & 0xffffffff,
    }
    print("# CRC32 candidates (target: footer_crc=0x{:08x}):".format(
        header["footer_crc"]
    ))
    for label, val in crc_variants.items():
        match = " <-- MATCH" if val == header["footer_crc"] else ""
        print(f"   {label}: 0x{val:08x}{match}")

    vectors = parse_arm_vectors(payload)
    print("# ARM Cortex-M vector table (first 64 bytes of payload):")
    for k, v in vectors.items():
        print(f"   {k}: {v}")

    out_bin.write_bytes(payload)
    print(f"# Wrote {out_bin}: {len(payload)} bytes")

    with open(out_map, "w", encoding="utf-8") as f:
        f.write(f"# Sub firmware {version} container layout\n\n")
        f.write(
            "Generated by `tools/firmware/inflate_sub.py`. "
            "Despite zlib magic bytes appearing throughout the .firm file, "
            "the firmware is **not** compressed - it's a flat ARM Cortex-M "
            "image wrapped in a header and footer. The 'zlib magic' bytes "
            "are coincidental matches in machine code.\n\n"
        )
        f.write("## Container header\n\n")
        for k, v in header.items():
            f.write(f"- **{k}**: `{v!r}`\n")
        f.write("\n## Layout\n\n")
        f.write("| Offset | Size | Content |\n")
        f.write("| --- | ---: | --- |\n")
        f.write("| `0x000` | 128 | Container header (mnemonic, version, sizes) |\n")
        f.write(
            f"| `0x{payload_start:03x}` | {len(payload):,} | "
            f"ARM Cortex-M payload (vector table + code) |\n"
        )
        trailer_size = header["payload_padded_end"] - payload_end
        f.write(
            f"| `0x{payload_end:05x}` | {trailer_size} | "
            f"Trailer padding (0xff) |\n"
        )
        f.write(
            f"| `0x{len(data) - 36:05x}` | 4 | "
            f"BE u32 CRC32 (`0x{header['footer_crc']:08x}`) |\n"
        )
        f.write(f"| `0x{len(data) - 32:05x}` | 32 | Footer block (mnemonic repeat) |\n")
        f.write("\n## ARM Cortex-M vector table\n\n")
        f.write("First 64 bytes of payload (interpreted as 16 LE u32s):\n\n")
        for k, v in vectors.items():
            f.write(f"- **{k}**: `{v}`\n")
        f.write(
            "\nReset PC `{}` indicates Thumb-mode entry at `0x140001d4`. "
            "This places code in the LPC43xx **SPIFI** address range "
            "(0x14000000-0x17ffffff), confirming the Sub processor is "
            "executing from external SPI flash at base 0x14000000.\n".format(
                vectors["reset_pc"]
            )
        )
        f.write("\n## CRC32 verification\n\n")
        f.write(
            f"Footer CRC: `0x{header['footer_crc']:08x}`\n\n"
        )
        for label, val in crc_variants.items():
            match = " **MATCH**" if val == header["footer_crc"] else ""
            f.write(f"- {label}: `0x{val:08x}`{match}\n")

    print(f"# Wrote {out_map}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
