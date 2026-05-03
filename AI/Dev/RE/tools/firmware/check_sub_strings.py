"""Search a SUB firmware blob for known identity strings.

Usage::

    py AI/Dev/RE/tools/firmware/check_sub_strings.py
    py AI/Dev/RE/tools/firmware/check_sub_strings.py --firmware path/to/sub_X_inflated.bin
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _common as _c  # noqa: E402

BASE = 0x14000000


def find_all(buf: bytes, needle: bytes) -> list[int]:
    out: list[int] = []
    i = 0
    while True:
        idx = buf.find(needle, i)
        if idx < 0:
            break
        out.append(idx)
        i = idx + 1
    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    _c.add_firmware_arg(p)
    args = p.parse_args()

    fw_path = _c.resolve_firmware(args)
    fw = fw_path.read_bytes()
    print(f"# Scanning {fw_path.relative_to(_c.REPO_ROOT)}  ({len(fw):,} bytes)")

    needles: list[bytes] = [
        b"SDS100",
        b"SDS100-SUB",
        b"Version",
        b"Version ",
        b"BCDx36HP",
        b"MDL",
        b"M\0D\0L\0",
        b"VER",
        b"\rERR",
    ]
    for needle in needles:
        hits = find_all(fw, needle)
        if hits:
            print(f"  {needle!r}: {len(hits)} hit(s)")
            for h in hits[:6]:
                ctx = fw[max(0, h - 6):h + len(needle) + 18]
                print(f"    +0x{h:06X} (0x{BASE + h:08X}): {ctx!r}")
        else:
            print(f"  {needle!r}: 0 hits")
    return 0


if __name__ == "__main__":
    sys.exit(main())
