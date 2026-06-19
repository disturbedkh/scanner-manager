"""Resume the Phase 1b retry from where the previous run left off.

The previous full ``--only-targeted2`` run at 18:31 hit lowercase ``h``,
``h0``, ``h1``, ``hh``, ``hQ`` and U,0 then was killed before finishing
the remaining ~30 candidates. Rather than re-running the whole 154 (and
re-triggering the noisy ``h`` stream), this script tests just the
remainder using the same anchor-and-compare logic.
"""
from __future__ import annotations

import sys
import time
from datetime import datetime
from pathlib import Path

import serial

HERE = Path(__file__).resolve().parent
SESSIONS = HERE / "sessions"
SESSIONS.mkdir(exist_ok=True)

REMAINDER = [
    # U register read with numeric arg
    "U,1", "U,2", "U,3",
    "U0", "U1", "U2", "U3",
    "U?",
    # Status with numeric
    "S,0", "S,1", "S,2",
    # Common short-RPC mnemonics
    "GET", "READ", "RD0", "RD1", "PEEK",
    "DBG0", "DBG1", "DBG2", "DBGM",
    "QRY", "PING", "ECHO", "ID", "WHO",
    "SYS", "SYSI", "SI", "SYSQ", "STAT0",
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


def send_and_read(p: serial.Serial, command: str, deadline_s: float = 0.6) -> bytes:
    p.reset_input_buffer()
    p.write((command + "\r").encode("ascii"))
    p.flush()
    deadline = time.monotonic() + deadline_s
    buf = bytearray()
    saw_cr = False
    last = time.monotonic()
    while time.monotonic() < deadline:
        chunk = p.read(4096)
        if chunk:
            buf.extend(chunk)
            last = time.monotonic()
            if b"\r" in chunk:
                saw_cr = True
        else:
            if saw_cr and time.monotonic() - last > 0.08:
                break
            time.sleep(0.005)
    return bytes(buf)


def is_binary(buf: bytes) -> bool:
    return any(b > 0x7E or b < 0x09 for b in buf)


def drain_briefly(p: serial.Serial, ms: int = 200) -> None:
    deadline = time.monotonic() + ms / 1000.0
    while time.monotonic() < deadline:
        chunk = p.read(4096)
        if chunk:
            deadline = time.monotonic() + 0.05
        else:
            time.sleep(0.005)


def main() -> int:
    port = sys.argv[1] if len(sys.argv) > 1 else "COM3"
    p = serial.Serial(port, 115200, timeout=0.05)
    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    log_path = SESSIONS / f"sub_probe_t2_remainder_{ts}.txt"
    log = open(log_path, "w", encoding="utf-8", buffering=1)
    try:
        anchor = send_and_read(p, "MDL")
        log.write(f"# remainder run @ {datetime.now().isoformat()} on {port}\n")
        log.write(f"# anchor MDL -> {len(anchor)}B  {show(anchor)}\n\n")
        print(f"# anchor: {len(anchor)}B  {show(anchor)[:80]}")

        for i, cmd in enumerate(REMAINDER, 1):
            resp = send_and_read(p, cmd)
            different = resp and resp != anchor and not resp.startswith(b"ERR")
            tag = "HIT" if different else ("ERR" if resp.startswith(b"ERR") else ("TO " if not resp else "fb "))
            line = f"[{i:3d}/{len(REMAINDER)}] {tag} {cmd:8s} {len(resp):4d}B | {show(resp)[:200]}"
            print(line, flush=True)
            log.write(line + "\n")
            # If binary, pause + drain and skip re-anchor (matching
            # sub_probe.py's defensive logic for binary responses).
            if is_binary(resp):
                drain_briefly(p, 200)
                continue
            if different or resp.startswith(b"ERR"):
                a2 = send_and_read(p, "MDL")
                if a2.startswith(b"SDS100-SUB"):
                    anchor = a2
        return 0
    finally:
        p.close()
        log.close()
        print(f"\n# log: {log_path}")


if __name__ == "__main__":
    raise SystemExit(main())
