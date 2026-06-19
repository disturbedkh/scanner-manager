"""Throwaway: test the SUB-processor hypothesis on COM3 (PID 0x0019).

If COM3 is the SUB processor command port (not a bootloader), it
should answer at least MDL/VER and possibly the V2.00 SUB-targeted
commands GCS (Get Charge Status) and KAL (Keep Alive).

READ-ONLY only. We send only the V1.02/V2.00 read-only mnemonics that
are safe by construction.
"""
from __future__ import annotations

import sys
import time

import serial

PORT = "COM3"
BAUD = 115200

PROBES = [
    ("MDL", "Get Model Info (V1.02 #1)"),
    ("VER", "Get Firmware Version (V1.02 #2)"),
    ("STS", "Get Current Status (V1.02 #5)"),
    ("GSI", "Get Scanner Info (V1.02 #13)"),
    ("GCS", "Get Charge Status (V2.00 #32, SUB-targeted?)"),
    ("KAL", "Keep Alive (V2.00, no response expected)"),
    ("VOL", "Volume (BCDx36HP inherited)"),
    ("SQL", "Squelch (BCDx36HP inherited)"),
    ("PWR", "Power/RSSI (BCDx36HP inherited)"),
    ("GLG", "Reception info (BCDx36HP inherited)"),
]


def show(buf: bytes) -> str:
    out = []
    for b in buf:
        c = chr(b)
        if c == "\r":
            out.append("\\r")
        elif c == "\n":
            out.append("\\n")
        elif 32 <= b < 127:
            out.append(c)
        else:
            out.append(f"<\\x{b:02X}>")
    return "".join(out)


def main() -> None:
    try:
        port = serial.Serial(PORT, BAUD, timeout=0.05)
    except serial.SerialException as e:
        print(f"FAILED to open {PORT}: {e}")
        sys.exit(1)
    print(f"# Opened {PORT} @ {BAUD} 8N1")
    try:
        for cmd, doc in PROBES:
            port.reset_input_buffer()
            port.write((cmd + "\r").encode("ascii"))
            t0 = time.monotonic()
            deadline = t0 + 1.5
            quiet_after_cr = 0.10
            buf = bytearray()
            last_byte_t = t0
            saw_cr = False
            while time.monotonic() < deadline:
                chunk = port.read(4096)
                if chunk:
                    buf.extend(chunk)
                    last_byte_t = time.monotonic()
                    if b"\r" in chunk or b"\n" in chunk:
                        saw_cr = True
                else:
                    if saw_cr and (time.monotonic() - last_byte_t) > quiet_after_cr:
                        break
                    time.sleep(0.005)
            elapsed_ms = (time.monotonic() - t0) * 1000.0
            print(
                f">>> {cmd:8s} ({doc})\n"
                f"    {len(buf):4d}B in {elapsed_ms:6.1f} ms  | {show(bytes(buf))}"
            )
    finally:
        port.close()


if __name__ == "__main__":
    main()
