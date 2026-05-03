"""Single-command SUB probe with full port reopen between each command.

Used to characterize commands that may leave the SUB in a streaming
state. Reopening the port between commands forces a clean state.

Usage:  py AI/Dev/RE/_sub_one_shot.py COM3 "U,0" "U,1" "U,2" ...
"""
from __future__ import annotations

import sys
import time
from datetime import datetime
from pathlib import Path

import serial


HERE = Path(__file__).resolve().parent
SESSIONS = HERE / "sessions"


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


def shoot_one(port_dev: str, command: str, deadline_s: float = 1.0) -> bytes:
    p = serial.Serial(port_dev, 115200, timeout=0.05)
    try:
        # Drain any leftover from prior session.
        d_deadline = time.monotonic() + 0.3
        while time.monotonic() < d_deadline:
            chunk = p.read(4096)
            if chunk:
                d_deadline = time.monotonic() + 0.1
            else:
                time.sleep(0.01)
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
    finally:
        p.close()


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: _sub_one_shot.py PORT CMD [CMD...]")
        return 2
    port = sys.argv[1]
    cmds = sys.argv[2:]
    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    out = SESSIONS / f"sub_one_shot_{ts}.txt"
    with open(out, "w", encoding="utf-8", buffering=1) as log:
        log.write(f"# SUB one-shot probe @ {datetime.now().isoformat()} on {port}\n\n")
        for cmd in cmds:
            try:
                resp = shoot_one(port, cmd)
            except Exception as exc:
                line = f"!! {cmd!r}: {exc!r}"
                print(line, flush=True)
                log.write(line + "\n")
                continue
            line = f"{cmd:12s}  {len(resp):4d}B  {show(resp)[:300]}"
            print(line, flush=True)
            log.write(line + "\n")
            # Brief settle between commands.
            time.sleep(0.2)
    print(f"\n# log: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
