"""Decode Sentinel USB CDC captures into command/response JSONL.

Phase 4 decoder for [`sentinel_capture.md`](sentinel_capture.md).
Reads one or more `.pcapng` files captured via USBPcap and emits, per
input file:

- ``<basename>.commands.jsonl`` -- one JSON object per recovered
  (command, response) pair on a given USB device.
- ``<basename>.summary.md`` -- human-readable per-file summary with
  mnemonic frequency, source-port classification, and any commands
  not present in the known-spec / probe-discovered union.

Strategy
--------
1. Use the ``tshark`` CLI (bundled with Wireshark) to dump the
   packets as JSON. We don't depend on the ``pyshark`` Python
   package because it's flaky on Windows.
2. Filter to USB Bulk transfers on the SDS100 device addresses
   (VID 1965, PID 0019 / 001A).
3. Reassemble the OUT-direction (host -> scanner) byte stream per
   device into ASCII, split on ``\\r``. Each line is a candidate
   command line.
4. Reassemble the IN-direction (scanner -> host) byte stream per
   device, split on ``\\r``.
5. Pair each command line on a device with the next response line
   on the same device that arrives within ``--pair-window-ms``
   milliseconds. Unpaired lines are emitted with ``response=null``
   for further inspection.

Limitations
-----------
- USB ZLP and split-bulk reassembly is approximated; a single
  command may end up with its response chunked across multiple
  Bulk-IN packets, which we glue together using the ``\\r``
  terminator.
- We don't try to decode SETUP/CONTROL transfers - this script is
  ASCII-CDC focused.
- Devices on the same VID:PID but different bus/address are kept
  separate (so a captures with two scanners would still be
  unambiguous).

Usage
-----
::

    py Metacache/Dev/RE/_decode_pcap.py Metacache/Dev/RE/sentinel_pcaps/*.pcapng

Or to point at a specific tshark binary::

    py Metacache/Dev/RE/_decode_pcap.py --tshark "C:\\Program Files\\Wireshark\\tshark.exe" \\
        Metacache/Dev/RE/sentinel_pcaps/01_read_from_scanner.pcapng

Outputs land alongside the inputs.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _common as _c  # noqa: E402

# --- Known-command universe used to flag novel mnemonics -----------------

# Every command head we've already seen (case-sensitive). Anything
# Sentinel sends that isn't in this set is a "novel" candidate.
KNOWN_HEADS: set[str] = {
    # SDS V1.02 spec
    "MDL", "VER", "STS", "FQK", "GSI", "SVC", "DTM", "LCR", "MSI",
    "GST", "GLT", "SQK", "DQK", "PSI",
    # SDS V2.00 additions
    "GCS", "KAL",
    # BCDx36HP-inherited (working on FW 1.26.01)
    "GLG", "PWR", "VOL", "SQL",
    # SUB-port unofficial discoveries (Phase 1 + 1b)
    "U", "h",
    # Mutating commands the spec defines (not expected in passive reads
    # but Sentinel's Write/Restore will hit them):
    "KEY", "QSH", "JNT", "NXT", "PRV", "HLD", "AVD", "JPM",
    "AST", "APR", "URC", "MNU", "MSV", "MSB", "PWF", "GWF", "GW2",
    "BFH",
}


@dataclass
class TransferLine:
    timestamp: float        # seconds since capture start
    device_key: str         # "<bus>.<addr>:<vid:pid>"
    direction: str          # "OUT" (host->dev) or "IN" (dev->host)
    payload: bytes          # decoded ASCII line WITHOUT trailing \r


@dataclass
class CommandResponse:
    timestamp: float
    device_key: str
    command: str            # the OUT line
    head: str               # uppercased portion before first comma
    response: str | None    # the next IN line on the same device
    response_delay_ms: float | None


@dataclass
class DeviceState:
    out_buf: bytearray = field(default_factory=bytearray)
    in_buf: bytearray = field(default_factory=bytearray)
    out_lines: list[tuple[float, str]] = field(default_factory=list)
    in_lines: list[tuple[float, str]] = field(default_factory=list)


# --- tshark invocation ---------------------------------------------------


def _find_tshark(explicit: str | None) -> str:
    if explicit:
        return str(_c.validate_executable(explicit, label="tshark"))
    which = shutil.which("tshark")
    if which:
        return which
    candidates = [
        r"C:\Program Files\Wireshark\tshark.exe",
        r"C:\Program Files (x86)\Wireshark\tshark.exe",
    ]
    for c in candidates:
        if Path(c).is_file():
            return c
    raise FileNotFoundError(
        "tshark.exe not found. Install Wireshark, or pass --tshark "
        "PATH explicitly."
    )


_TSHARK_FIELDS = [
    "frame.time_relative",
    "usb.bus_id",
    "usb.device_address",
    "usb.idVendor",
    "usb.idProduct",
    "usb.transfer_type",
    "usb.endpoint_address.direction",
    "usb.capdata",
]


def _parse_tshark_line(line: str) -> dict | None:
    parts = line.split("|")
    if len(parts) != len(_TSHARK_FIELDS):
        return None
    ts, bus, addr, vid, pid, xtype, ep_dir, capdata = parts
    if xtype != "0x03" or not capdata:
        return None
    return {
        "ts": float(ts) if ts else 0.0,
        "bus": bus or "",
        "addr": addr or "",
        "vid": vid or "",
        "pid": pid or "",
        "ep_dir": ep_dir or "",
        "data": capdata.replace(":", ""),
    }


def _run_tshark(tshark: str, pcap: Path) -> list[dict]:
    """Return list of {timestamp, src, dst, vid, pid, ep_dir, payload} dicts."""
    tshark_path = _c.validate_executable(tshark, label="tshark")
    cmd = [str(tshark_path), "-r", str(pcap), "-T", "fields"]
    for f in _TSHARK_FIELDS:
        cmd.extend(["-e", f])
    cmd.extend(["-E", "separator=|", "-E", "occurrence=f"])

    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if res.returncode != 0:
        raise RuntimeError(
            f"tshark failed for {pcap}: {res.stderr.strip()}"
        )
    out: list[dict] = []
    for line in res.stdout.splitlines():
        rec = _parse_tshark_line(line)
        if rec is not None:
            out.append(rec)
    return out


# --- Stream reassembly ---------------------------------------------------


def _device_key(rec: dict) -> str:
    return f"{rec['bus']}.{rec['addr']}:{rec['vid']}:{rec['pid']}"


def _is_sds100(rec: dict) -> bool:
    return rec["vid"].lower() in ("0x1965", "1965") and rec["pid"].lower() in (
        "0x0019", "0x001a", "1965", "001a", "0019",
    )


def _append_stream_lines(st: DeviceState, ts: float, payload: bytes, *, outbound: bool) -> None:
    buf = st.out_buf if outbound else st.in_buf
    lines = st.out_lines if outbound else st.in_lines
    buf.extend(payload)
    while b"\r" in buf:
        line, _, rest = buf.partition(b"\r")
        if outbound:
            st.out_buf = bytearray(rest)
        else:
            st.in_buf = bytearray(rest)
        lines.append((ts, line.decode("ascii", "replace")))


def reassemble(records: list[dict]) -> dict[str, DeviceState]:
    states: dict[str, DeviceState] = defaultdict(DeviceState)
    for rec in records:
        if not _is_sds100(rec):
            continue
        try:
            payload = bytes.fromhex(rec["data"])
        except ValueError:
            continue
        st = states[_device_key(rec)]
        outbound = rec["ep_dir"] == "0"
        _append_stream_lines(st, rec["ts"], payload, outbound=outbound)
    return states


def _match_response(
    ins: list[tuple[float, str]],
    cts: float,
    pair_window_s: float,
) -> tuple[int | None, str | None, float | None]:
    for i, (its, iline) in enumerate(ins):
        if its < cts:
            continue
        if its - cts > pair_window_s:
            break
        return i, iline, (its - cts) * 1000.0
    return None, None, None


def pair_lines(
    states: dict[str, DeviceState],
    pair_window_s: float,
) -> list[CommandResponse]:
    pairs: list[CommandResponse] = []
    for dkey, st in states.items():
        ins = list(st.in_lines)   # mutable copy; pop fronts as consumed
        for cts, cline in st.out_lines:
            if not cline.strip():
                continue
            head = cline.split(",", 1)[0].upper().strip()
            idx, response, response_delay_ms = _match_response(ins, cts, pair_window_s)
            if idx is not None:
                ins.pop(idx)
            pairs.append(CommandResponse(
                timestamp=cts,
                device_key=dkey,
                command=cline,
                head=head,
                response=response,
                response_delay_ms=response_delay_ms,
            ))
    pairs.sort(key=lambda p: p.timestamp)
    return pairs


# --- Reporting -----------------------------------------------------------


def write_jsonl(pairs: list[CommandResponse], path: Path) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for p in pairs:
            f.write(json.dumps({
                "ts": round(p.timestamp, 6),
                "device": p.device_key,
                "command": p.command,
                "head": p.head,
                "response": p.response,
                "response_delay_ms": (
                    round(p.response_delay_ms, 3)
                    if p.response_delay_ms is not None else None
                ),
            }) + "\n")


def _write_device_breakdown(f, by_dev: dict[str, list[CommandResponse]]) -> None:
    f.write("## Per-device breakdown\n\n")
    for dkey, plist in by_dev.items():
        heads = Counter(p.head for p in plist)
        f.write(f"### `{dkey}`\n\n")
        f.write(f"- Total commands: {len(plist)}\n")
        f.write("- Top mnemonics:\n")
        for h, n in heads.most_common(20):
            marker = "" if h in KNOWN_HEADS else " **(novel)**"
            f.write(f"  - `{h or '<empty>'}` x {n}{marker}\n")
        f.write("\n")


def _write_novel_mnemonics(f, pairs: list[CommandResponse], head_counts: Counter[str]) -> None:
    novel = sorted(h for h in head_counts if h and h not in KNOWN_HEADS)
    f.write("## Novel mnemonics (not in any known spec or probe)\n\n")
    if not novel:
        f.write("_None._\n")
        return
    for h in novel:
        samples = [p for p in pairs if p.head == h][:3]
        f.write(f"- `{h}` ({head_counts[h]} occurrences)\n")
        for s in samples:
            f.write(
                f"    - cmd=`{s.command}`  "
                f"resp=`{(s.response or '<none>')[:120]}`\n"
            )


def write_summary(
    pairs: list[CommandResponse],
    src_pcap: Path,
    path: Path,
) -> None:
    by_dev: dict[str, list[CommandResponse]] = defaultdict(list)
    for p in pairs:
        by_dev[p.device_key].append(p)

    head_counts: Counter[str] = Counter(p.head for p in pairs)

    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# Decoded summary - {src_pcap.name}\n\n")
        f.write(f"- Source: `{src_pcap}`\n")
        f.write(f"- Pairs decoded: {len(pairs)}\n")
        f.write(f"- Devices observed: {len(by_dev)}\n\n")

        _write_device_breakdown(f, by_dev)
        _write_novel_mnemonics(f, pairs, head_counts)

        f.write("\n## Slowest responses\n\n")
        slow = [p for p in pairs if p.response_delay_ms is not None]
        slow.sort(key=lambda p: p.response_delay_ms or 0, reverse=True)
        for p in slow[:10]:
            f.write(
                f"- {p.response_delay_ms:8.1f} ms  "
                f"`{p.command[:60]}`  -> `{(p.response or '')[:60]}`\n"
            )


# --- Driver --------------------------------------------------------------


def decode_one(
    pcap: Path,
    tshark: str,
    pair_window_s: float,
) -> tuple[Path, Path]:
    print(f"# decoding {pcap}")
    records = _run_tshark(tshark, pcap)
    print(f"  {len(records)} bulk packets to/from SDS100")
    states = reassemble(records)
    pairs = pair_lines(states, pair_window_s)
    print(f"  {len(pairs)} command/response pairs recovered")
    jsonl = pcap.with_suffix(".commands.jsonl")
    summary = pcap.with_suffix(".summary.md")
    write_jsonl(pairs, jsonl)
    write_summary(pairs, pcap, summary)
    print(f"  -> {jsonl.name}")
    print(f"  -> {summary.name}")
    return jsonl, summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("pcaps", nargs="+", type=Path,
                    help="One or more .pcapng files captured via USBPcap")
    ap.add_argument("--tshark", default=None,
                    help="Path to tshark.exe (auto-detected by default)")
    ap.add_argument("--pair-window-ms", type=float, default=2000.0,
                    help="Max command->response delay in ms (default 2000)")
    args = ap.parse_args()

    try:
        tshark = _find_tshark(args.tshark)
    except FileNotFoundError as exc:
        print(f"!! {exc}", file=sys.stderr)
        return 2

    pair_window_s = args.pair_window_ms / 1000.0
    for pcap in args.pcaps:
        pcap_path = _c.safe_user_path(_c.RE_ROOT, pcap)
        if not pcap_path.exists():
            print(f"!! not found: {pcap}", file=sys.stderr)
            continue
        try:
            decode_one(pcap_path, tshark, pair_window_s)
        except Exception as exc:
            print(f"!! {pcap}: {exc!r}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
