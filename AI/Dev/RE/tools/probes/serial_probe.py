"""Passive RE probe for the Uniden SDS100 (and SDS200) over serial / USB CDC.

READ-ONLY by design. This script is for reverse-engineering the live
scanner's command surface without touching its state. Every command in
the WHITELIST below is a documented or strongly-suspected query-only
command. The script:

- enumerates COM ports, picks the new one introduced by the scanner
  switching into serial mode (or honors --port);
- opens it at 115200 8N1 (USB CDC virtual COM port - baud is nominal,
  the scanner ignores it but pyserial wants a value);
- sends each whitelisted command, waits up to ~600 ms for a response;
- captures every byte verbatim into a timestamped session log under
  ``AI/Dev/RE/sessions/``;
- never sends anything that simulates a key press, enters programming
  mode, writes config, or otherwise changes scanner state.

To extend the probe with a new query command, add it to ``QUERIES``
ONLY after confirming it is read-only in the official Uniden Remote
Command Reference. NEVER add KEY, PRG, EPG, CLR, JNT, JPM, or any
command that takes a "set" form.

Usage::

    py AI/Dev/RE/serial_probe.py
    py AI/Dev/RE/serial_probe.py --port COM7
    py AI/Dev/RE/serial_probe.py --port COM7 --baud 115200
    py AI/Dev/RE/serial_probe.py --list

Outputs are written into ``AI/Dev/RE/sessions/<timestamp>.txt`` and
also streamed to stdout for live monitoring.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import os
import sys
import time
from pathlib import Path
from typing import List, Optional

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    sys.stderr.write(
        "pyserial is required. Install with:  py -m pip install --user pyserial\n"
    )
    sys.exit(2)


# ---------------------------------------------------------------------------
# READ-ONLY command whitelist
# ---------------------------------------------------------------------------
# Each entry is a command line WITHOUT terminator. The probe appends "\r"
# automatically. We try a "bare" form first; if the scanner answers ERR
# we don't try a "set" form - that would by definition be mutating.
#
# Sources for command names: the Uniden BCDx36HP / SDS100 Operation
# Specification. Cited inline. If a command isn't here, don't add it
# unless you have read the spec and confirmed it's a pure query.
# ---------------------------------------------------------------------------

QUERIES: List[tuple[str, str]] = [
    # (label, command)
    ("model", "MDL"),                    # model name, e.g. SDS100
    ("firmware", "VER"),                 # firmware version
    ("rsi", "RSI"),                      # RSSI / radio status info (some FW)
    ("status_display", "STS"),           # current display + alert/dim state
    ("glcd_info", "GLG"),                # current LCD reception info
    ("power_freq", "PWR"),               # signal level + frequency
    ("volume", "VOL"),                   # current volume (0..15)
    ("squelch", "SQL"),                  # current squelch (0..15)
    ("battery", "BAV"),                  # battery voltage (some FW)
    ("backlight", "BLT"),                # backlight setting (some FW)
    ("contrast", "CNT"),                 # display contrast (some FW)
    ("display_mode", "DMA"),             # display mode (some FW)
    ("scan_state", "SCN"),               # generic scan state query (best-effort)
    ("close_call_band", "CBP"),          # close call band plan (read form)
    ("custom_search_status", "CSP"),     # custom search params (read form)
    ("location_get", "LOC"),             # current scanner location (lat/lon)
    ("gps_get", "GIN,GPS"),              # GPS info (some FW)
    ("clock", "CLK"),                    # clock format / timezone (read form)
    ("owner_info", "OMS"),               # owner-info / opening message (read)
    ("backlight_info", "BLI"),           # backlight info (some FW)
    ("memory_info", "MEM"),              # memory usage (some FW)
    ("recording_state", "RST"),          # recording state (best-effort)
    ("priority_state", "PRI"),           # priority mode state (read)
    ("alert_status", "ALT"),             # alert status (read)
    ("get_remote_id", "GID"),            # current talkgroup ID
    ("number_tag", "NTG"),               # current number tag (read)
    ("waterfall_setting", "WFL"),        # waterfall settings (read)
    ("favorite_list", "FAV"),            # favorites list info (read)
    ("scanner_settings", "GST"),         # global settings (read; suspected)
    ("rangelist_get", "RLG"),            # range list (read; suspected)
    # Generic "?" form fallbacks for the most likely commands. Some
    # Uniden FWs accept both "MDL" and "MDL,?".
    ("model_query", "MDL,?"),
    ("firmware_query", "VER,?"),
    ("status_query", "STS,?"),
    ("glcd_query", "GLG,?"),
    ("volume_query", "VOL,?"),
    ("squelch_query", "SQL,?"),
]


# Commands that look query-ish but are CONFIRMED mutating; never send.
FORBIDDEN_FOR_READ_ONLY = {
    "KEY", "JNT", "JPM", "PRG", "EPG", "CLR", "DLA", "MEMSET",
    "TGW", "VLO", "SLO", "WPL", "WPS", "WIPE", "RST,SET", "GLT",
}


# ---------------------------------------------------------------------------


def list_ports() -> List[str]:
    return [p.device for p in serial.tools.list_ports.comports()]


def describe_ports() -> str:
    out = []
    for p in serial.tools.list_ports.comports():
        out.append(f"  {p.device}  {p.description}  [HWID {p.hwid}]")
    return "\n".join(out) if out else "  (no COM ports found)"


def auto_pick_port(known_baseline: List[str]) -> Optional[str]:
    """Return the first COM port not in known_baseline, or None."""
    for p in serial.tools.list_ports.comports():
        if p.device not in known_baseline:
            return p.device
    return None


def _safe_decode(buf: bytes) -> str:
    """Decode bytes for logging. Show non-printable as <\\xHH>."""
    out = []
    for b in buf:
        c = chr(b)
        if c == "\r":
            out.append("\\r")
        elif c == "\n":
            out.append("\\n")
        elif c == "\t":
            out.append("\\t")
        elif 32 <= b < 127:
            out.append(c)
        else:
            out.append(f"<\\x{b:02X}>")
    return "".join(out)


def probe_one(port: serial.Serial, label: str, command: str, log) -> None:
    """Send one query, capture response, log everything."""
    head = command.split(",", 1)[0].upper()
    if head in FORBIDDEN_FOR_READ_ONLY:
        log(f"[skip] {label:<24}  cmd={command!r}  (head {head!r} is on FORBIDDEN list)")
        return

    payload = (command + "\r").encode("ascii", errors="replace")
    log("")
    log(f">>> {label:<24}  cmd={command!r}  bytes_out={payload!r}")

    port.reset_input_buffer()
    t0 = time.perf_counter()
    try:
        port.write(payload)
        port.flush()
    except Exception as exc:
        log(f"[error] write failed: {exc}")
        return

    deadline = t0 + 0.6  # 600 ms read window
    response = bytearray()
    while time.perf_counter() < deadline:
        n = port.in_waiting
        if n:
            chunk = port.read(n)
            response.extend(chunk)
            # Heuristic: if we've seen a CR and nothing arrived for ~50 ms,
            # the scanner is done.
            if response.endswith(b"\r") or response.endswith(b"\n"):
                quiet_until = time.perf_counter() + 0.05
                while time.perf_counter() < quiet_until:
                    n2 = port.in_waiting
                    if n2:
                        response.extend(port.read(n2))
                        quiet_until = time.perf_counter() + 0.05
                break
        else:
            time.sleep(0.005)

    elapsed_ms = (time.perf_counter() - t0) * 1000
    if response:
        log(f"<<< {len(response)} bytes in {elapsed_ms:.0f} ms")
        log(f"    raw  : {bytes(response)!r}")
        log(f"    show : {_safe_decode(bytes(response))}")
    else:
        log(f"<<< (no response, {elapsed_ms:.0f} ms timeout)")


def main() -> int:
    parser = argparse.ArgumentParser(description="Passive SDS100 serial probe (READ-ONLY).")
    parser.add_argument("--port", help="COM port (e.g. COM7). Default: auto-detect new port.")
    parser.add_argument("--baud", type=int, default=115200,
                        help="Baud rate. Nominal for USB CDC; default 115200.")
    parser.add_argument("--list", action="store_true",
                        help="List COM ports and exit.")
    parser.add_argument("--baseline", default="",
                        help="Comma-separated baseline COM ports to ignore in auto-detect "
                             "(e.g. 'COM3,COM4').")
    parser.add_argument("--out", default="",
                        help="Output log path. Default: AI/Dev/RE/sessions/<timestamp>.txt.")
    args = parser.parse_args()

    if args.list:
        print("Available COM ports:")
        print(describe_ports())
        return 0

    baseline = [p.strip() for p in args.baseline.split(",") if p.strip()]
    port_name = args.port or auto_pick_port(baseline)
    if not port_name:
        sys.stderr.write(
            "No new COM port detected. Pass --port, or list with --list.\n"
            "Current ports:\n" + describe_ports() + "\n"
        )
        return 3

    repo_root = Path(__file__).resolve().parent.parent.parent.parent  # AI/Dev/RE/.. -> repo root
    if args.out:
        out_path = Path(args.out)
    else:
        sessions_dir = repo_root / "AI" / "Dev" / "RE" / "sessions"
        sessions_dir.mkdir(parents=True, exist_ok=True)
        ts = _dt.datetime.now().strftime("%Y%m%dT%H%M%S")
        out_path = sessions_dir / f"sds100_serial_{ts}.txt"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = out_path.open("w", encoding="utf-8", newline="\n")

    def log(msg: str = "") -> None:
        print(msg)
        log_file.write(msg + "\n")
        log_file.flush()

    log(f"# SDS100 passive serial probe")
    log(f"# When     : {_dt.datetime.now().isoformat(timespec='seconds')}")
    log(f"# Host     : {os.environ.get('COMPUTERNAME', '?')}")
    log(f"# Port     : {port_name}  (baud={args.baud}, 8N1)")
    log(f"# Output   : {out_path}")
    log(f"# Probe ID : {_dt.datetime.now().strftime('%Y%m%dT%H%M%S')}")
    log(f"#")
    log(f"# Forbidden (never sent): {sorted(FORBIDDEN_FOR_READ_ONLY)}")
    log(f"# Whitelist size        : {len(QUERIES)}")
    log(f"#")
    log(f"# Available ports at start:")
    for line in describe_ports().splitlines():
        log(f"# {line}")
    log("")

    try:
        ser = serial.Serial(
            port=port_name,
            baudrate=args.baud,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.05,
            write_timeout=0.5,
            rtscts=False,
            dsrdtr=False,
            xonxoff=False,
        )
    except Exception as exc:
        log(f"[fatal] could not open {port_name}: {exc}")
        log_file.close()
        return 4

    try:
        time.sleep(0.1)
        # Drain anything the scanner emitted on connect.
        n = ser.in_waiting
        if n:
            preamble = ser.read(n)
            log(f"# preamble on open: {preamble!r}  show={_safe_decode(preamble)}")

        for label, cmd in QUERIES:
            probe_one(ser, label, cmd, log)

        # Final drain.
        time.sleep(0.2)
        if ser.in_waiting:
            tail = ser.read(ser.in_waiting)
            log("")
            log(f"# trailing async bytes: {tail!r}  show={_safe_decode(tail)}")
    finally:
        try:
            ser.close()
        except Exception:
            pass
        log("")
        log("# probe complete.")
        log_file.close()

    print(f"\nLog saved to: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
