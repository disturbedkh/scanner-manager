"""Static analysis of an inflated SUB firmware payload.

Without a full Ghidra import (which is the multi-week side quest in
the firmware-RE plan), we do best-effort static RE on the raw ARM
Cortex-M payload produced by ``inflate_sub.py``.

Goals:
- Enumerate command-mnemonic candidates (ASCII clusters that look
  like command tokens followed by NUL or comma).
- Find LPC43xx peripheral register accesses (32-bit immediate loads
  of known peripheral base addresses).
- Map RF/DSP format-string xrefs to surrounding code.

Usage::

    py Metacache/Dev/RE/tools/firmware/sub_static_analysis.py
    py Metacache/Dev/RE/tools/firmware/sub_static_analysis.py \\
        --firmware path/to/sub_X_inflated.bin \\
        --output Metacache/Dev/RE/docs/sub_static_analysis.md
"""
from __future__ import annotations

import argparse
import re
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _common as _c  # noqa: E402

# Code is loaded at virtual base 0x14000000 (LPC43xx SPIFI region).
CODE_BASE = 0x14000000

# LPC43xx peripheral memory map (subset of interest).
# Source: NXP LPC43xx user manual UM10503.
LPC43XX_PERIPHS = [
    (0x40000000, 0x40010000, "AHB peripherals"),
    (0x40050000, 0x40051000, "SCT (State Configurable Timer)"),
    (0x40051000, 0x40052000, "GPDMA"),
    (0x40080000, 0x40081000, "USART0"),
    (0x40081000, 0x40082000, "UART1"),
    (0x40082000, 0x40083000, "SSP0 (SPI)"),
    (0x40083000, 0x40084000, "Timer0"),
    (0x40084000, 0x40085000, "Timer1"),
    (0x40085000, 0x40086000, "SCU (System Control Unit)"),
    (0x40086000, 0x40087000, "GPIO interrupts"),
    (0x400a0000, 0x400a1000, "ADC0"),
    (0x400a1000, 0x400a2000, "ADC1"),
    (0x400a2000, 0x400a3000, "DAC"),
    (0x40080000, 0x40081000, "USART2"),
    (0x40090000, 0x40091000, "I2C0"),
    (0x40091000, 0x40092000, "I2C1"),
    (0x400a4000, 0x400a5000, "I2S0"),
    (0x400a8000, 0x400a9000, "I2S1"),
    (0x400a6000, 0x400a7000, "SPIFI (flash interface)"),
    (0x40010000, 0x40011000, "RGU (Reset Generator)"),
    (0x40050000, 0x40051000, "CGU (Clock Generator)"),
    (0x400f0000, 0x400f1000, "USB0"),
    (0x40006000, 0x40007000, "GPDMA"),
    (0x40090000, 0x40091000, "GPIO ports"),
    (0x42000000, 0x44000000, "AHB bit-banding alias"),
    (0x10000000, 0x10020000, "SRAM Bank0 (LOC SRAM)"),
    (0x10080000, 0x100a0000, "SRAM Bank1 (LOC SRAM)"),
    (0x20000000, 0x20010000, "SRAM AHB"),
    (0xe0000000, 0xe0100000, "Cortex-M4 system control"),
    (0x14000000, 0x18000000, "SPIFI flash (code)"),
]


def classify_addr(addr: int) -> str:
    for lo, hi, name in LPC43XX_PERIPHS:
        if lo <= addr < hi:
            return name
    return "unknown"


def find_command_mnemonics(payload: bytes) -> list[tuple[int, str]]:
    """Find 2-5 char ASCII A-Z[A-Z0-9]* sequences followed by NUL or comma."""
    pat = re.compile(rb"[A-Z][A-Z0-9_]{1,5}[\x00,]")
    out: list[tuple[int, str]] = []
    for m in pat.finditer(payload):
        s = m.group()[:-1].decode("ascii")
        # Filter out common non-command junk: short variable-name-like
        # patterns and tokens that appear in plaintext format strings.
        if len(s) < 2 or len(s) > 5:
            continue
        out.append((m.start(), s))
    return out


def cluster_mnemonics(items: list[tuple[int, str]], max_gap: int = 32) -> list[list]:
    """Group mnemonics that are within max_gap bytes of each other - a
    typical command-dispatch table puts them all in a single contiguous
    region of the binary."""
    if not items:
        return []
    items_sorted = sorted(items)
    clusters: list[list] = [[items_sorted[0]]]
    for off, mn in items_sorted[1:]:
        last_off = clusters[-1][-1][0]
        if off - last_off <= max_gap:
            clusters[-1].append((off, mn))
        else:
            clusters.append([(off, mn)])
    return clusters


def find_addr_constants(payload: bytes) -> dict[str, list[int]]:
    """Find 32-bit LE values that look like peripheral base addresses.
    Returns dict keyed by peripheral name, with list of code offsets."""
    out: dict[str, list[int]] = {}
    if len(payload) < 4:
        return out
    for i in range(0, len(payload) - 4, 4):
        val = struct.unpack_from("<I", payload, i)[0]
        # Filter to "interesting" 32-bit values: peripheral / SRAM / code regions.
        if val == 0 or val == 0xffffffff:
            continue
        if not (0x10000000 <= val <= 0x18000000 or 0x20000000 <= val <= 0x20020000
                or 0x40000000 <= val <= 0x44000000 or 0xe0000000 <= val <= 0xe0100000):
            continue
        name = classify_addr(val)
        out.setdefault(name, []).append(i)
    return out


def find_string_xrefs(payload: bytes, marker: bytes) -> list[int]:
    """Find offsets where the marker bytes appear in the payload."""
    out: list[int] = []
    i = 0
    while True:
        j = payload.find(marker, i)
        if j < 0:
            break
        out.append(j)
        i = j + 1
    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    _c.add_firmware_arg(p)
    p.add_argument("--output", "-o", type=Path,
                   default=_c.DOCS_DIR / "sub_static_analysis.md",
                   help="Where to write the markdown report. Default: "
                        "Metacache/Dev/RE/docs/sub_static_analysis.md.")
    args = p.parse_args()

    fw_path = _c.resolve_firmware(args)
    payload = fw_path.read_bytes()
    OUT = args.output
    OUT.parent.mkdir(parents=True, exist_ok=True)
    print(f"# Loaded {fw_path.relative_to(_c.REPO_ROOT)}: {len(payload)} bytes")

    mnemonics = find_command_mnemonics(payload)
    print(f"# Found {len(mnemonics)} ASCII command-mnemonic candidates")

    clusters = cluster_mnemonics(mnemonics, max_gap=32)
    print(f"# Grouped into {len(clusters)} clusters")

    biggest = sorted(clusters, key=len, reverse=True)[:10]
    print("# Top 10 clusters by size:")
    for cl in biggest:
        print(f"   @{cl[0][0]:#08x}: {len(cl)} mnemonics: "
              f"{[m for _, m in cl[:8]]}{'...' if len(cl) > 8 else ''}")

    addrs = find_addr_constants(payload)
    print("# Peripheral / memory-region 32-bit constants found:")
    for name in sorted(addrs.keys(), key=lambda k: -len(addrs[k])):
        print(f"   {name}: {len(addrs[name])} occurrences")

    # RF/DSP format-string xrefs: find the ASCII "S%02X..." status format
    # in the payload as a NUL-terminated string. Then list code offsets
    # that contain a 32-bit literal pointing AT it.
    # Common SUB-firmware identity / format-string anchors. The first
    # block below tracks ones we've seen across multiple SUB firmware
    # versions; the last two are version-specific anchors that may need
    # updating for a future SUB build.
    target_strings = [
        b"S%02X%04X%04X%04X%04X%01X%04X\x00",
        b"R840_FM\x00",
        b"R840_DVB_T2_1_7M\x00",
        b"Noise Squelch,%6d\x00",
        b"FFT_PEAK,%ddB\x00",
        b"SDS100-SUB\x00",
    ]
    # Try to anchor on the version string from the firmware itself.
    ver_match = re.search(rb"Version [0-9]+\.[0-9]+\.[0-9]+ \x00", payload)
    if ver_match:
        target_strings.append(ver_match.group(0))
    string_xrefs: list[tuple[bytes, int, list[int]]] = []
    for s in target_strings:
        offsets = find_string_xrefs(payload, s)
        # For each offset, find code positions that load CODE_BASE + offset
        # as a 32-bit literal.
        code_refs = []
        for soff in offsets:
            target = CODE_BASE + soff
            target_bytes = struct.pack("<I", target)
            for cm in re.finditer(re.escape(target_bytes), payload):
                code_refs.append(cm.start())
        string_xrefs.append((s, offsets[0] if offsets else -1, code_refs))

    with open(OUT, "w", encoding="utf-8") as f:
        f.write("# Sub firmware static analysis (best-effort)\n\n")
        f.write(
            f"Generated by `tools/firmware/sub_static_analysis.py` from "
            f"`{fw_path.name}` ({len(payload):,} bytes), "
            f"loaded at base `0x14000000`.\n\n"
        )

        f.write("## Phase 6.3: Command-mnemonic candidates\n\n")
        f.write(
            f"Found {len(mnemonics)} ASCII A-Z[A-Z0-9_]{{1,4}} sequences "
            f"terminated by NUL or comma. These are byte patterns that look "
            f"like command tokens. Many are false positives (random ASCII "
            f"in machine code), but real dispatch tables tend to cluster.\n\n"
        )

        f.write("### Top 20 mnemonic clusters\n\n")
        f.write("| # | Offset | Count | Mnemonics |\n")
        f.write("| ---: | --- | ---: | --- |\n")
        for i, cl in enumerate(sorted(clusters, key=len, reverse=True)[:20]):
            mns = ", ".join(f"`{m}`" for _, m in cl[:10])
            if len(cl) > 10:
                mns += f" (+{len(cl) - 10})"
            f.write(f"| {i + 1} | `0x{cl[0][0]:08x}` | {len(cl)} | {mns} |\n")

        # Highlight clusters containing known SUB commands.
        known_sub = {"MDL", "VER", "SDS100", "SUB"}
        f.write("\n### Clusters containing known SUB tokens\n\n")
        for cl in clusters:
            if any(mn in known_sub for _, mn in cl):
                mns = ", ".join(f"`{m}`" for _, m in cl)
                f.write(f"- `0x{cl[0][0]:08x}` ({len(cl)} entries): {mns}\n")

        f.write("\n## Phase 6.4: Inter-MCU bus and peripheral register usage\n\n")
        f.write(
            "Static scan for 32-bit LE constants matching LPC43xx peripheral "
            "base addresses. These appear in literal pools that ARM Cortex-M "
            "code uses to load peripheral pointers.\n\n"
        )
        f.write("| Peripheral | Constant occurrences |\n")
        f.write("| --- | ---: |\n")
        for name in sorted(addrs.keys(), key=lambda k: -len(addrs[k])):
            f.write(f"| {name} | {len(addrs[name])} |\n")

        f.write(
            "\nKey finding: the relative occurrence count of I2C, USART, "
            "I2S, and SPI/SSP peripherals lets us infer which bus "
            "implements the inter-MCU communication channel between SUB "
            "and MAIN. The most-used data-path peripheral is the "
            "best candidate for the audio/FFT pipe, while a less-used "
            "but always-present peripheral like I2C is the likely "
            "control-message channel.\n"
        )

        f.write("\n## Phase 6.5: Format-string xrefs\n\n")
        f.write(
            "For each high-value format string in the firmware, locate "
            "32-bit code references to its address (`code_base + string_offset`). "
            "These mark the call sites of `printf`-style functions that "
            "produce the response we observe.\n\n"
        )
        f.write("| Format string | String offset | Code xrefs (code-base relative) |\n")
        f.write("| --- | --- | --- |\n")
        for s, soff, refs in string_xrefs:
            sname = s.rstrip(b"\x00").decode("ascii", "replace")
            if len(sname) > 50:
                sname = sname[:47] + "..."
            ref_str = ", ".join(f"`0x{r:05x}`" for r in refs[:8])
            if not refs:
                ref_str = "_none found_"
            elif len(refs) > 8:
                ref_str += f" (+{len(refs) - 8})"
            soff_str = f"`0x{soff:05x}`" if soff >= 0 else "_not present_"
            f.write(f"| `{sname}` | {soff_str} | {ref_str} |\n")

        f.write(
            "\n### Interpretation\n\n"
            "Code references found via 32-bit address constants tell us "
            "the printf call site - but not the *trigger*. To find the "
            "trigger (the command mnemonic that causes printf to fire), "
            "the next step would be a Ghidra import (Phase 6.2) where we "
            "can backtrack from the printf call to the command-dispatch "
            "table identified above.\n\n"
            "Without Ghidra, the **string offsets** themselves are still "
            "useful - they map onto the `mnemonic_offsets` column of "
            "`sub_command_response_map.md`, letting us correlate live "
            "responses with their format-string source.\n"
        )

    print(f"# Wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
