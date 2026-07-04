"""Passive listen-only test on COM6 (Uniden VID 1965, PID 001A).

WRITE-NOTHING. Just opens the port, listens for 5 seconds, prints
whatever bytes arrive. Used to determine whether COM6 is:

  (a) the GPS NMEA stream (will see $GPGGA / $GPRMC every ~1 sec), or
  (b) silent (might be the MAIN processor command port - we'd then
      probe it with the read-only whitelist), or
  (c) something else entirely.

Usage:  py Metacache/Dev/RE/com6_listen.py [--port COM6] [--seconds 5]
"""

from __future__ import annotations

import argparse
import datetime as _dt
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _common as _c  # noqa: E402

try:
    import serial
except ImportError:
    sys.stderr.write("pyserial required.\n")
    sys.exit(2)


def _safe(buf: bytes) -> str:
    out = []
    for b in buf:
        if b == 0x0D:
            out.append("\\r")
        elif b == 0x0A:
            out.append("\\n\n")  # also break visual line on LF
        elif b == 0x09:
            out.append("\\t")
        elif 32 <= b < 127:
            out.append(chr(b))
        else:
            out.append(f"<\\x{b:02X}>")
    return "".join(out)


def _listen_at_baud(args, emit, baud: int) -> tuple[bool, bool]:
    """Return (saw_data, saw_nmea)."""
    emit(f"--- attempt @ baud={baud} ---")
    try:
        ser = serial.Serial(
            port=args.port, baudrate=baud,
            bytesize=serial.EIGHTBITS, parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE, timeout=0.1,
            rtscts=False, dsrdtr=False, xonxoff=False,
        )
    except Exception as exc:
        emit(f"open failed: {exc}")
        return False, False

    try:
        time.sleep(0.1)
        t_end = time.perf_counter() + args.seconds
        buf = bytearray()
        while time.perf_counter() < t_end:
            n = ser.in_waiting
            if n:
                buf.extend(ser.read(n))
            else:
                time.sleep(0.02)
        if not buf:
            emit("(silent)")
            return False, False
        emit(f"received {len(buf)} bytes:")
        emit(f"raw : {bytes(buf)!r}")
        emit("show:")
        emit(_safe(bytes(buf)))
        emit("")
        return True, b"$GP" in buf or b"$GN" in buf
    finally:
        ser.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="COM6")
    ap.add_argument("--baud", type=int, default=4800)  # NMEA default; GPS is usually 4800 or 9600
    ap.add_argument("--seconds", type=float, default=5.0)
    args = ap.parse_args()

    sessions = _c.SESSIONS_DIR
    sessions.mkdir(parents=True, exist_ok=True)
    ts = _dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    out_path = sessions / f"com6_listen_{ts}.txt"

    log = out_path.open("w", encoding="utf-8", newline="\n")

    def emit(s: str = "") -> None:
        print(s)
        log.write(s + "\n")
        log.flush()

    emit(f"# COM6 listen-only probe @ {_dt.datetime.now().isoformat(timespec='seconds')}")
    emit(f"# Port={args.port} Baud={args.baud} Seconds={args.seconds}")
    emit(f"# Output: {out_path}")
    emit("")

    # Try a few baud rates if the first yields nothing.
    candidates = [args.baud] + [b for b in (4800, 9600, 38400, 115200) if b != args.baud]
    seen_anything = False

    for baud in candidates:
        saw_data, saw_nmea = _listen_at_baud(args, emit, baud)
        seen_anything = seen_anything or saw_data
        if saw_nmea:
            emit("# NMEA sentences detected; stopping.")
            break
        emit("")

    emit(f"# done; saw_data={seen_anything}")
    log.close()
    print(f"\nLog: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
