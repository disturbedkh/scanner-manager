"""Interactive driver for the Sentinel passive-capture session.

This script replaces Steps 3-5 of [`sentinel_capture.md`](../../docs/sentinel_capture.md)
with an automated, prompt-driven flow:

1. Detects ``USBPcapCMD.exe`` (preferred) or ``dumpcap.exe`` (fallback).
   USBPcapCMD talks directly to the USBPcap kernel driver and does NOT
   require Npcap; dumpcap requires Npcap on Wireshark 4.x.
2. Lists USBPcap interfaces and tries to auto-pick the one carrying the
   SDS100 (VID 0x1965, PID 0x0019/0x001A) by sniffing each briefly.
   Falls back to asking the user if auto-detect is ambiguous.
3. For each of the six standard Sentinel operations (Read, Write, HPDB,
   Firmware, Backup, Restore):

   - Prints a clear instruction (e.g. "Click 'Read From Scanner' in
     Sentinel now").
   - Spawns the capture tool to write
     ``Metacache/Dev/RE/sentinel_pcaps/<NN_name>.pcap``.
     With ``--rotate-output`` (default), an existing target file is
     not overwritten; the new capture lands at
     ``<NN_name>.<UTC>.pcap`` instead. This works around the
     "Thread started with invalid write handle!" error that USBPcap
     surfaces when re-opening a previously-used filename.
   - Waits for the user to press Enter when the operation completes.
   - Sends Ctrl-Break to the capture process and waits for clean shutdown.
   - Reports byte/packet counts.
   - Optionally invokes ``decode_sentinel_pcap.py`` immediately to
     produce SCSI/UMS/FAT32 summary, sparse disk image, and a
     human-readable list of files Sentinel touched.

4. Exits with a summary of all captures.

The capture mechanism is **strictly passive** - we only observe USB
traffic, never modify it. Sentinel and the scanner cannot detect this.

Usage::

    py Metacache/Dev/RE/tools/sentinel/sentinel_session.py
    py Metacache/Dev/RE/tools/sentinel/sentinel_session.py --skip 4 --skip 6
    py Metacache/Dev/RE/tools/sentinel/sentinel_session.py --decode-only
    py Metacache/Dev/RE/tools/sentinel/sentinel_session.py --interface USBPcap2
    py Metacache/Dev/RE/tools/sentinel/sentinel_session.py --no-rotate-output

Per-operation captures are independent; a Ctrl-C between them is safe.
"""

from __future__ import annotations

import argparse
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _common as _c  # noqa: E402

REPO_ROOT = _c.REPO_ROOT
PCAP_DIR = _c.PCAPS_DIR
DECODER = (
    Path(__file__).resolve().parent / "decode_sentinel_pcap.py"
)

# Capture backend candidates. USBPcapCMD is preferred because it talks
# directly to the USBPcap kernel driver and does not require Npcap.
# dumpcap is a fallback (and in fact requires Npcap on modern Wireshark
# 4.x installs, so it usually fails on a winget-only setup).
USBPCAPCMD_CANDIDATES = [
    Path("C:/Program Files/USBPcap/USBPcapCMD.exe"),
    Path("C:/Program Files (x86)/USBPcap/USBPcapCMD.exe"),
]
WIRESHARK_CANDIDATES = [
    Path("C:/Program Files/Wireshark/dumpcap.exe"),
    Path("C:/Program Files (x86)/Wireshark/dumpcap.exe"),
]


@dataclass(frozen=True)
class Operation:
    number: int
    filename: str
    title: str
    instruction: str
    expectation: str


OPERATIONS: tuple[Operation, ...] = (
    Operation(
        number=1,
        filename="01_read_from_scanner.pcap",
        title="Read From Scanner",
        instruction=(
            "In Sentinel: open Manage Scanner -> click 'Read From Scanner'.\n"
            "Wait for the read to complete (progress bar finishes)."
        ),
        expectation=(
            "USB Mass Storage SCSI READ_10 traffic. Sentinel reads HPDB "
            "record files (_NNNNNN.hpd), GlobalSetting.cfg, and per-channel "
            "data. No CDC traffic in mass-storage mode."
        ),
    ),
    Operation(
        number=2,
        filename="02_write_to_scanner.pcap",
        title="Write to Scanner",
        instruction=(
            "In Sentinel: open Manage Scanner -> click 'Write to Scanner'.\n"
            "Use the same data you just read (or a known-good config).\n"
            "Wait for the write to complete."
        ),
        expectation=(
            "USB Mass Storage SCSI WRITE_10 traffic - FAT32 directory + FAT "
            "table writes plus actual file content writes. If you don't have "
            "a config to write, --skip this op."
        ),
    ),
    Operation(
        number=3,
        filename="03_hpdb_update.pcap",
        title="HPDB Update",
        instruction=(
            "In Sentinel: Tools / Database -> 'Get HPDB Update'.\n"
            "Wait for the operation to finish."
        ),
        expectation=(
            "Heavy WRITE_10 traffic to HPDB record files (_NNNNNN.hpd). "
            "Reveals: HPDB record file format, allocation order, and how "
            "Sentinel commits a fresh database to the SD card."
        ),
    ),
    Operation(
        number=4,
        filename="04_firmware_update.pcap",
        title="Firmware Update",
        instruction=(
            "In Sentinel: trigger the firmware update flow.\n"
            "ONLY DO THIS IF YOU ACTUALLY WANT TO UPDATE THE FIRMWARE.\n"
            "Otherwise, --skip 4 and capture this next time you legitimately\n"
            "update."
        ),
        expectation=(
            "Large WRITE_10 of a single firmware blob (encrypted MAIN MCU "
            "image) plus a metadata/marker file. Reveals: filename, size, "
            "and any handoff signal between Sentinel and the scanner."
        ),
    ),
    # NOTE: Backup / Restore operations were removed. In current Sentinel
    # builds (v1.20+) these aliases are not exposed in the menu, and on
    # older builds they were just full mirrors of Read/Write traffic.
    # If a future Sentinel exposes them again and they look distinct on
    # the wire, re-add them here as ops 5 + 6.
)


@dataclass
class CaptureResult:
    op: Operation
    pcap_path: Path
    bytes_written: int
    packets: int = 0
    decoded_summary: str | None = None
    skipped: bool = False
    error: str | None = None


@dataclass
class SessionState:
    capture_tool: Path
    interface: str
    rotate_output: bool = True
    results: list[CaptureResult] = field(default_factory=list)


def find_capture_tool() -> Path | None:
    """Find USBPcapCMD.exe (preferred) or dumpcap.exe (Npcap-dependent fallback)."""
    for p in USBPCAPCMD_CANDIDATES:
        if p.exists():
            return p
    discovered = shutil.which("USBPcapCMD.exe")
    if discovered:
        return Path(discovered)
    for p in WIRESHARK_CANDIDATES:
        if p.exists():
            return p
    discovered = shutil.which("dumpcap.exe") or shutil.which("dumpcap")
    return Path(discovered) if discovered else None


def is_usbpcapcmd(tool: Path) -> bool:
    return tool.name.lower().startswith("usbpcapcmd")


def list_usbpcap_interfaces(tool: Path) -> list[tuple[str, str]]:
    """Return [(interface_id, friendly_name), ...] for USBPcap roots."""
    if is_usbpcapcmd(tool):
        # USBPcapCMD's --extcap-interfaces output looks like:
        #   interface {value=\\.\USBPcap1}{display=USBPcap1}
        out = subprocess.run(
            [str(tool), "--extcap-interfaces"],
            capture_output=True,
            text=True,
            check=False,
        )
        interfaces: list[tuple[str, str]] = []
        for line in out.stdout.splitlines():
            if "value=" not in line:
                continue
            try:
                token = line.split("value=", 1)[1].split("}", 1)[0]
                display = line.split("display=", 1)[1].split("}", 1)[0] if "display=" in line else token
                interfaces.append((token, f"{display} ({token})"))
            except IndexError:
                continue
        return interfaces

    # dumpcap path (legacy fallback).
    out = subprocess.run(
        [str(tool), "-D"], capture_output=True, text=True, check=False,
    )
    interfaces = []
    for raw_line in out.stdout.splitlines():
        line = raw_line.strip()
        if "USBPcap" not in line:
            continue
        idx = line.find("\\\\.\\USBPcap")
        if idx < 0:
            idx = line.find("USBPcap")
        if idx < 0:
            continue
        tail = line[idx:]
        token = tail.split()[0].rstrip("()").rstrip()
        if not token.startswith("\\\\.\\"):
            token = "\\\\.\\" + token
        interfaces.append((token, line))
    return interfaces


def _spawn_capture(
    tool: Path,
    interface: str,
    out_path: Path,
    devices: str | None = None,
) -> subprocess.Popen:
    """Start a capture subprocess and return it. Caller is responsible for
    sending CTRL_BREAK_EVENT to stop it."""
    if is_usbpcapcmd(tool):
        cmd = [str(tool), "-d", interface, "-o", str(out_path), "-A"]
        if devices:
            cmd += ["--devices", devices]
    else:
        cmd = [str(tool), "-i", interface, "-w", str(out_path), "-q"]
    return subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        stdin=subprocess.PIPE,  # USBPcapCMD reads from stdin in non-extcap mode
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    )


def _stop_capture(proc: subprocess.Popen, timeout: float = 10.0) -> None:
    """Stop a capture subprocess cleanly. USBPcapCMD requires CTRL_BREAK
    delivered to its process group; dumpcap accepts the same signal."""
    try:
        proc.send_signal(signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]
    except Exception:
        proc.terminate()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass


def probe_interface_for_sds100(
    tool: Path, interface: str, seconds: float = 2.0
) -> bool:
    """Briefly capture on `interface` and return True if SDS100 USB
    descriptors (VID 1965, any PID) appear in the bytes.

    Uses a per-call temporary directory so that:
      a) leftover probe files from a previous run can't block this one
         with a Windows file-lock (USBPcapCMD releases handles lazily); and
      b) we never pollute PCAP_DIR with `_probe_*` files that look like
         real captures.
    """
    tmp_dir = Path(tempfile.mkdtemp(prefix="sentinel_probe_"))
    tmp = tmp_dir / "probe.pcap"
    try:
        proc = _spawn_capture(tool, interface, tmp)
        time.sleep(seconds)
        _stop_capture(proc, timeout=5.0)
        if not tmp.exists():
            return False
        # Windows: USBPcapCMD sometimes releases the file handle a few
        # hundred ms after the process exits. Retry reads a couple of
        # times before giving up.
        data: bytes | None = None
        for _ in range(5):
            try:
                data = tmp.read_bytes()
                break
            except PermissionError:
                time.sleep(0.3)
        if data is None:
            return False
        sds_markers = (b"\x65\x19\x19\x00", b"\x65\x19\x1a\x00", b"\x65\x19\x17\x00")
        return any(m in data for m in sds_markers)
    finally:
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass


def _pnp_locate_sds100_hub() -> str | None:
    """Run the PowerShell PnP-trace helper and return the matched
    `\\\\.\\USBPcapN` interface, or None if not on Windows / not found."""
    helper = REPO_ROOT / "AI" / "Dev" / "RE" / "tools" / "automation" / "find_sds100_hub.ps1"
    if not helper.exists():
        # Legacy path (pre-tools-reorg) - kept as a fallback for old checkouts.
        helper = REPO_ROOT / "AI" / "Dev" / "RE" / "automation" / "_find_sds100_hub.ps1"
    if not helper.exists():
        return None
    try:
        out = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(helper),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    for line in out.stdout.splitlines():
        line = line.strip()
        if line.startswith("USBPCAP_INTERFACE="):
            value = line.split("=", 1)[1].strip()
            return value or None
    return None


def _measure_traffic(tool: Path, ifaces: list[tuple[str, str]], seconds: float = 2.0) -> dict[str, int]:
    """Capture on each interface for `seconds` and return {iface: bytes}.
    Heaviest-traffic hub usually carries the SDS100 (continuous CDC polling)."""
    PCAP_DIR.mkdir(parents=True, exist_ok=True)
    sizes: dict[str, int] = {}
    for ifid, _ in ifaces:
        safe = ifid.replace("\\", "_").replace(":", "_").lstrip("_")
        tmp = PCAP_DIR / f"_traffic_{safe}.pcap"
        try:
            proc = _spawn_capture(tool, ifid, tmp)
            time.sleep(seconds)
            _stop_capture(proc, timeout=5.0)
            sizes[ifid] = tmp.stat().st_size if tmp.exists() else 0
        except Exception:
            sizes[ifid] = 0
        finally:
            try:
                tmp.unlink()
            except OSError:
                pass
    return sizes


def _probe_each_interface(tool: Path, ifaces: list[tuple[str, str]], seconds: float = 3.0) -> dict[str, bool]:
    """For each USBPcap interface, capture briefly and check for VID 0x1965
    descriptor markers. Returns {iface: True if SDS100 traffic detected}.
    More specific than _measure_traffic - a busy keyboard hub will look
    big but won't carry the SDS100 VID marker.
    """
    found: dict[str, bool] = {}
    for ifid, _label in ifaces:
        print(f"      probing {ifid} for VID 0x1965 ({seconds:.0f}s)...", end=" ", flush=True)
        hit = probe_interface_for_sds100(tool, ifid, seconds=seconds)
        found[ifid] = hit
        print("YES (SDS100 found)" if hit else "no")
    return found


def auto_select_interface(tool: Path) -> tuple[str | None, str]:
    """Returns (interface, source) where `source` describes the strategy
    that picked it. Used by main() to decide whether the post-pick
    verification probe is needed.

      "single"  - only one USBPcap interface exists
      "pnp"     - Windows PnP parent-chain trace (deterministic)
      "vid"     - per-interface VID 0x1965 descriptor probe
      "traffic" - traffic-volume tiebreaker (low confidence)
      "none"    - nothing matched
    """
    print("[*] Listing USBPcap interfaces...")
    ifaces = list_usbpcap_interfaces(tool)
    if not ifaces:
        print("[X] No USBPcap interfaces found. Is USBPcap installed and the system rebooted?")
        return None, "none"
    print(f"[+] Found {len(ifaces)} USBPcap interface(s):")
    for ifid, label in ifaces:
        print(f"      {ifid}   ({label})")

    iface_ids = {ifid for ifid, _ in ifaces}
    valid_ifaces = list(ifaces)
    if len(valid_ifaces) == 1:
        only = valid_ifaces[0][0]
        print(f"[+] Only one USBPcap interface present; using {only}")
        return only, "single"

    # Strategy 1: deterministic Windows PnP parent-chain trace.
    pnp = _pnp_locate_sds100_hub()
    if pnp and pnp in iface_ids:
        print(f"[+] PnP trace -> {pnp}")
        return pnp, "pnp"
    if pnp:
        print(f"[!] PnP trace returned {pnp} but it is not in the USBPcap interface list.")

    # Strategy 2: VID 0x1965 descriptor probe on each interface. Only
    # reliable when the scanner enumerates during the probe window
    # (e.g. just plugged in, or actively transferring).
    print("[*] Probing each interface for VID 0x1965 USB descriptors...")
    found = _probe_each_interface(tool, valid_ifaces, seconds=3.0)
    hits = [ifid for ifid, h in found.items() if h]
    if len(hits) == 1:
        print(f"[+] VID 0x1965 found on {hits[0]}")
        return hits[0], "vid"
    if len(hits) > 1:
        print(f"[!] VID 0x1965 found on multiple interfaces: {hits}")
        # Multiple hits is unusual but not impossible (e.g. user has two
        # scanners or USBPcap is filtering oddly). Manual select.
        return None, "none"

    # Strategy 3: traffic-volume tiebreaker (only applicable if we still
    # don't know which is the scanner - e.g. scanner currently idle in
    # mass-storage mode and no enumeration in this window).
    print("[!] No interface positively identified; falling back to traffic volume.")
    print("[*] Measuring traffic on each interface (2s each)...")
    sizes = _measure_traffic(tool, valid_ifaces, seconds=2.0)
    for ifid in sizes:
        print(f"      {ifid}: {sizes[ifid]:,} bytes")
    if sizes:
        best = max(sizes, key=lambda k: sizes[k])
        if sizes[best] > 0 and (
            len(sizes) == 1
            or sizes[best] >= 4 * max(v for k, v in sizes.items() if k != best)
        ):
            print(f"[+] Traffic heuristic -> {best}")
            return best, "traffic"

    print("[!] Auto-detect ambiguous; manual selection required.")
    return None, "none"


def manual_select_interface(tool: Path) -> str | None:
    ifaces = list_usbpcap_interfaces(tool)
    if not ifaces:
        return None
    # Probe each interface so the user can see which one carries the SDS100.
    print()
    print("[*] Probing each interface so you can see which one carries the SDS100...")
    found = _probe_each_interface(tool, ifaces, seconds=3.0)
    print()
    for i, (ifid, label) in enumerate(ifaces, start=1):
        marker = "  <-- SDS100" if found.get(ifid) else ""
        print(f"  [{i}] {ifid}   ({label}){marker}")
    raw = input("Pick interface number (or paste full \\\\.\\USBPcapN): ").strip()
    if raw.startswith("\\\\.\\"):
        return raw
    try:
        idx = int(raw)
        return ifaces[idx - 1][0]
    except (ValueError, IndexError):
        return None


def verify_interface_or_warn(tool: Path, interface: str) -> bool:
    """Final guard: probe the chosen interface and warn loudly if it does
    not carry VID 0x1965 traffic. Returns True if the interface looks
    correct, False otherwise. The session continues either way (the user
    is interactive and can decide), but the warning makes the failure
    impossible to miss.
    """
    print(f"[*] Final check: does {interface} carry VID 0x1965 traffic?")
    if probe_interface_for_sds100(tool, interface, seconds=3.0):
        print(f"[+] Confirmed: SDS100 USB descriptors visible on {interface}")
        return True
    print()
    print("=" * 70)
    print(f"  [!] WARNING: no VID 0x1965 (Uniden) descriptors on {interface}")
    print("=" * 70)
    print("  - Is the scanner powered on and in Mass Storage mode?")
    print("  - Did you pick the right USBPcap interface? Try re-running")
    print("    with --interface \\\\.\\USBPcapN to override.")
    print("  - The scanner has to enumerate during the probe window for")
    print("    USBPcap to see its descriptors. Replug it if needed.")
    print("=" * 70)
    print()
    cont = input("Continue anyway? [y/N]: ").strip().lower()
    return cont == "y"


def capture_one_operation(state: SessionState, op: Operation) -> CaptureResult:
    PCAP_DIR.mkdir(parents=True, exist_ok=True)
    out_path = PCAP_DIR / op.filename
    if state.rotate_output:
        out_path = _c.rotate_path(out_path)

    print()
    print("=" * 70)
    print(f"  Operation {op.number} of 6: {op.title}")
    print("=" * 70)
    print()
    print(op.instruction)
    print()
    print(f"Expected traffic: {op.expectation}")
    print()
    print(f"Output file: {out_path}")
    print()
    input("Press Enter to START the capture (then perform the action in Sentinel)...")

    proc = _spawn_capture(state.capture_tool, state.interface, out_path)
    time.sleep(0.5)
    if proc.poll() is not None:
        err = proc.stderr.read().decode(errors="replace") if proc.stderr else ""
        tool_name = state.capture_tool.name
        return CaptureResult(op=op, pcap_path=out_path, bytes_written=0, error=f"{tool_name} exited immediately: {err}")

    print(f"[*] Capturing on {state.interface} -> {out_path}")
    print(f"[*] PID {proc.pid}. When the Sentinel operation finishes, press Enter here.")
    input()

    _stop_capture(proc, timeout=10.0)

    if not out_path.exists():
        return CaptureResult(op=op, pcap_path=out_path, bytes_written=0, error=f"{state.capture_tool.name} did not produce a file")
    size = out_path.stat().st_size
    pkts = quick_packet_count(state.capture_tool, out_path)
    print(f"[+] Capture saved: {size:,} bytes, ~{pkts} packets.")
    return CaptureResult(op=op, pcap_path=out_path, bytes_written=size, packets=pkts)


def quick_packet_count(tool: Path, pcap: Path) -> int:
    """Use a sibling capinfos.exe (Wireshark) if available; otherwise return 0."""
    capinfos_candidates = [
        tool.parent / "capinfos.exe",
        Path("C:/Program Files/Wireshark/capinfos.exe"),
        Path("C:/Program Files (x86)/Wireshark/capinfos.exe"),
    ]
    capinfos = next((c for c in capinfos_candidates if c.exists()), None)
    if not capinfos:
        return 0
    try:
        out = subprocess.run(
            [str(capinfos), "-c", str(pcap)],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
        for line in out.stdout.splitlines():
            if "Number of packets" in line:
                value = line.split(":", 1)[1].strip().replace(",", "").split()[0]
                try:
                    return int(value)
                except ValueError:
                    return 0
    except Exception:
        return 0
    return 0


def maybe_decode(result: CaptureResult, do_decode: bool) -> None:
    if not do_decode or result.error or result.skipped or result.bytes_written == 0:
        return
    if not DECODER.exists():
        print(f"[!] Decoder not found at {DECODER}; skipping decode.")
        return
    print(f"[*] Decoding {result.pcap_path.name} ...")
    try:
        rc = subprocess.call([sys.executable, str(DECODER), str(result.pcap_path)])
        summary = result.pcap_path.with_suffix("").with_suffix(".summary.md")
        if rc == 0 and summary.exists():
            result.decoded_summary = str(summary.relative_to(REPO_ROOT))
            print(f"[+] Decoded -> {result.decoded_summary}")
        else:
            print(f"[!] Decoder exit code {rc}; see output above.")
    except Exception as e:
        print(f"[!] Decoder error: {e}")


def run_session(args: argparse.Namespace) -> int:
    PCAP_DIR.mkdir(parents=True, exist_ok=True)

    if args.decode_only:
        existing = sorted(list(PCAP_DIR.glob("*.pcap")) + list(PCAP_DIR.glob("*.pcapng")))
        if not existing:
            print(f"[!] No pcaps under {PCAP_DIR} to decode.")
            return 1
        for p in existing:
            print(f"[*] Decoding {p.name}")
            subprocess.call([sys.executable, str(DECODER), str(p)])
        return 0

    tool = find_capture_tool()
    if not tool:
        print("[X] No capture tool found. Install USBPcap (preferred):")
        print("    winget install --id DesowinTools.USBPcap -e")
        print("  or Wireshark + Npcap as a fallback.")
        return 1
    print(f"[+] Capture tool: {tool}  ({'USBPcapCMD' if is_usbpcapcmd(tool) else 'dumpcap'})")

    interface = args.interface
    source = "user" if interface else "none"
    if not interface:
        interface, source = auto_select_interface(tool)
    if not interface:
        print()
        interface = manual_select_interface(tool)
        source = "manual" if interface else "none"
    if not interface:
        print("[X] No interface selected. Aborting.")
        return 1

    # Final guard: confirm the chosen interface actually carries SDS100
    # traffic before running captures against the wrong bus. Only run
    # this when selection confidence is low, i.e. the traffic-volume
    # heuristic was the deciding strategy. PnP / VID-descriptor / single-
    # interface / explicit-flag / manual selections are already trusted.
    needs_verify = (
        source == "traffic"
        and not args.no_verify_interface
    )
    if needs_verify:
        if not verify_interface_or_warn(tool, interface):
            print("[X] Aborting at user request.")
            return 1

    state = SessionState(
        capture_tool=tool,
        interface=interface,
        rotate_output=args.rotate_output,
    )
    skip_set = set(args.skip or [])

    for op in OPERATIONS:
        if op.number in skip_set:
            print(f"[*] Skipping operation {op.number} ({op.title}) per --skip flag.")
            state.results.append(CaptureResult(op=op, pcap_path=PCAP_DIR / op.filename, bytes_written=0, skipped=True))
            continue
        result = capture_one_operation(state, op)
        state.results.append(result)
        maybe_decode(result, do_decode=args.decode)

    print_summary(state)
    return 0


def print_summary(state: SessionState) -> None:
    print()
    print("=" * 70)
    print("  Session summary")
    print("=" * 70)
    for r in state.results:
        if r.skipped:
            status = "SKIPPED"
            detail = "(per --skip flag)"
        elif r.error:
            status = "ERROR"
            detail = r.error
        else:
            status = "OK"
            detail = f"{r.bytes_written:,} bytes, ~{r.packets} pkts"
        print(f"  {status:<8} op{r.op.number}: {r.op.title}")
        print(f"           {r.pcap_path}")
        print(f"           {detail}")
        if r.decoded_summary:
            print(f"           summary: {r.decoded_summary}")
    print()
    print(f"All pcaps under: {PCAP_DIR}")
    print("Run the decoder explicitly with:")
    print(f"  py Metacache/Dev/RE/_decode_pcap.py {PCAP_DIR}/*.pcap")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument(
        "--skip",
        type=int,
        action="append",
        metavar="N",
        help="Skip operation N (1..6). Repeatable: --skip 4 --skip 6.",
    )
    p.add_argument(
        "--interface",
        type=str,
        default=None,
        help="Force a specific USBPcap interface (e.g. \\\\.\\USBPcap2). "
        "If omitted, the script auto-detects.",
    )
    p.add_argument(
        "--decode",
        action="store_true",
        help="Run _decode_pcap.py against each capture immediately after it completes.",
    )
    p.add_argument(
        "--decode-only",
        action="store_true",
        help="Skip capture; just decode any existing pcaps under sentinel_pcaps/.",
    )
    p.add_argument(
        "--rotate-output",
        dest="rotate_output",
        action="store_true",
        default=True,
        help="If a pcap of the same name already exists, rotate the new "
             "one to <stem>.<UTC>.<ext> rather than overwriting. Default: "
             "on. Mitigates USBPcap's 'Thread started with invalid write "
             "handle!' error on repeat runs.",
    )
    p.add_argument(
        "--no-rotate-output",
        dest="rotate_output",
        action="store_false",
        help="Disable output rotation; reuse the canonical filename "
             "(may collide with USBPcap's stale handle).",
    )
    p.add_argument(
        "--no-verify-interface",
        dest="no_verify_interface",
        action="store_true",
        help="Skip the post-selection probe that confirms the chosen "
             "USBPcap interface actually carries VID 0x1965 (Uniden) "
             "traffic. Use only if you're certain about the interface.",
    )
    return p.parse_args()


if __name__ == "__main__":
    try:
        sys.exit(run_session(parse_args()))
    except KeyboardInterrupt:
        print("\n[!] Interrupted by user.")
        sys.exit(130)
