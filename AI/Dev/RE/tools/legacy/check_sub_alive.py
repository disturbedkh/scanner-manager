"""Quick test: drain COM3 buffer, then send MDL.

Used after sub_probe.py runs that may have left the SUB port mid-stream
(e.g. the lowercase 'h' command triggers a continuous H/h dump that
doesn't self-terminate). If MDL still returns the expected SDS100-SUB
identity after a drain, the SUB is recoverable without a power cycle.
"""
from __future__ import annotations

import sys
import time

import serial


def main() -> int:
    port = sys.argv[1] if len(sys.argv) > 1 else "COM3"
    p = serial.Serial(port, 115200, timeout=0.05)
    try:
        # Drain anything stale.
        deadline = time.monotonic() + 1.5
        drained = bytearray()
        while time.monotonic() < deadline:
            n = p.in_waiting
            if n:
                drained.extend(p.read(n))
                deadline = time.monotonic() + 0.3
            else:
                time.sleep(0.02)
        print(f"# drained {len(drained)} bytes from stale stream")
        if drained:
            print(f"# drained-tail: {drained[-200:]!r}")

        # Now try MDL.
        p.reset_input_buffer()
        p.write(b"MDL\r")
        time.sleep(0.5)
        n = p.in_waiting
        resp = p.read(n) if n else b""
        print(f"# MDL response ({len(resp)} bytes): {resp!r}")

        # Try a benign Phase-3 command on MAIN-equivalent: VER.
        p.reset_input_buffer()
        p.write(b"VER\r")
        time.sleep(0.5)
        n = p.in_waiting
        resp2 = p.read(n) if n else b""
        print(f"# VER response ({len(resp2)} bytes): {resp2!r}")

        return 0 if resp.startswith(b"SDS100-SUB") else 1
    finally:
        p.close()


if __name__ == "__main__":
    raise SystemExit(main())
