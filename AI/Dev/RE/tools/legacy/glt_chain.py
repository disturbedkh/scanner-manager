"""One-shot GLT chain probe.

Sends a fixed set of GLT subcommands using indices we already know
(from a prior GSI + GLT,FL response on the same scanner state).
All commands are read-only structured queries documented in the
Uniden SDS100/SDS200 Remote Command Spec V1.02 (GLT command page).

This file is throwaway tooling - delete after Session 3 documentation
is captured. Reuses helpers from serial_probe.py so the read-loop
behaviour stays identical.
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from serial_probe import (
    FORBIDDEN_FOR_READ_ONLY,
    _safe_decode,
    _send_and_read,
)

import serial  # noqa: E402

# Indices from prior GSI + GLT,FL responses on this same scanner state:
#   FL Home    : Index=2
#   System     : Index=6 (Gainesville Regional Utilities (GRUCom), P25 Trunk)
#   Site       : Index=9 (Simulcast)
CHAIN = [
    ("glt_sys_in_home",      "GLT,SYS,2"),
    ("glt_dept_in_grucom",   "GLT,DEPT,6"),
    ("glt_site_in_grucom",   "GLT,SITE,6"),
    ("glt_sfreq_in_simul",   "GLT,SFREQ,9"),
    ("glt_atgid_in_grucom",  "GLT,ATGID,6"),
]


def main() -> int:
    ser = serial.Serial(port="COM4", baudrate=115200,
                        timeout=0.05, write_timeout=0.5)
    try:
        print(f"# GLT chain probe @ {datetime.datetime.now().isoformat(timespec='seconds')}")
        print("# Port: COM4, host: MAINGAMINGPC")
        print()
        for label, cmd in CHAIN:
            head = cmd.split(",", 1)[0].upper()
            if head in FORBIDDEN_FOR_READ_ONLY:
                print(f"[skip] {label}: {cmd!r}")
                continue
            resp, ms = _send_and_read(ser, cmd)
            print(f">>> {label:<24} cmd={cmd!r}")
            print(f"<<< {len(resp)} bytes in {ms:.0f} ms")
            print(f"    raw  : {resp!r}")
            print(f"    show : {_safe_decode(resp)}")
            print()
    finally:
        ser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
