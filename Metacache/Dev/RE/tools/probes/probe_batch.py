"""Editable batch-runner for ad-hoc SUB/MAIN probes during firmware-driven RE.

This script is **deliberately non-CLI-driven**. The "input" is the
``BATCH`` list at the top of the file - I rewrite it between iterations
to test progressively more specific hypotheses derived from the firmware
decompile. The user just needs to keep the scanner plugged in.

Each entry in ``BATCH`` is a ``ProbeSpec``:

- ``send``         - the literal bytes to send (without trailing CR; we add it).
- ``label``        - human-readable hypothesis (e.g. "DSP filter stats").
- ``args_hint``    - optional, for the report.
- ``port``         - role: ``"SUB"`` (PID 0x0019) or ``"MAIN"`` (PID 0x001A).
                     Resolved to an actual COM/tty at runtime by VID/PID.
- ``destructive``  - if True, requires explicit ``--allow-destructive``.

Usage
-----
::

    # Auto-detect SUB/MAIN by Uniden VID/PID:
    py Metacache/Dev/RE/tools/probes/probe_batch.py
    py Metacache/Dev/RE/tools/probes/probe_batch.py --tag round4_first_pass
    # Override - send everything to a specific device:
    py Metacache/Dev/RE/tools/probes/probe_batch.py --port COM5
    py Metacache/Dev/RE/tools/probes/probe_batch.py --allow-destructive
    py Metacache/Dev/RE/tools/probes/probe_batch.py --baud 115200

Outputs a timestamped markdown report under
``Metacache/Dev/RE/sessions/probe_batch_<UTC-ts>.md`` plus a JSONL log next to it.

Classification mirrors ``verify_dispatch.py``: HIT / ERR / IDENTITY /
TIMEOUT. See its docstring for semantics.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

try:
    import serial  # pyserial
except ImportError:
    sys.exit("[X] pyserial is required. Install with: py -m pip install pyserial")

# Make ``_common`` importable when running this file directly.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _common as _c  # noqa: E402

REPO_ROOT = _c.REPO_ROOT
RE_DIR = _c.RE_ROOT
SESSIONS_DIR = _c.SESSIONS_DIR

# Mirrors verify_dispatch.FORBIDDEN_HEADS.
FORBIDDEN_HEADS = {
    "DIE", "RST", "RB", "WB", "PROG", "PG", "BL", "ERA", "WIPE", "BFH", "h",
}


@dataclass
class ProbeSpec:
    send: str
    label: str
    args_hint: str = ""
    port: str = "SUB"  # role: "SUB" or "MAIN" (resolved to COMx at runtime)
    destructive: bool = False


# ============================================================================
# BATCH - the editable section. Replace contents each iteration.
# ============================================================================
# Default starter batch: a few known-good and known-bad probes to exercise
# the runner end-to-end. Replace with hypotheses-from-decompile content
# during firmware-driven RE.
BATCH: list[ProbeSpec] = [
    # Anchor probes
    ProbeSpec(send="MDL", label="anchor: SUB identity",     port="SUB"),
    ProbeSpec(send="VER", label="anchor: firmware version", port="SUB"),
    # 13 SUB-side debug commands from FUN_14006ca6
    ProbeSpec(send="o",   label="enable/toggle (FUN_1400692c)",    port="SUB"),
    ProbeSpec(send="q",   label="dump 0x100 bytes from f70 buffer", port="SUB"),
    ProbeSpec(send="w",   label="dump 0x100 bytes from f78 buffer", port="SUB"),
    ProbeSpec(send="d",   label="disable/toggle (FUN_140069d0)",    port="SUB"),
    ProbeSpec(send="r",   label="dump 0x400 bytes from f7c (1KB)",  port="SUB"),
    ProbeSpec(send="m",   label="dump 0x100+0x300 from f80 buffer", port="SUB"),
    ProbeSpec(send="z",   label="stats line (FUN_14006a64)",        port="SUB"),
    ProbeSpec(send="l",   label="record list (counter-driven)",     port="SUB"),
    ProbeSpec(send="s",   label="3-float stats (FUN_14006c00)",     port="SUB"),
    ProbeSpec(send="t",   label="silent toggle 0<->1 (mode flag)",  port="SUB"),
    ProbeSpec(send="u",   label="silent toggle 0<->2 (mode flag)",  port="SUB"),
    ProbeSpec(send="v",   label="dump 0x100+0x200 dual-stream",     port="SUB"),
]
# ============================================================================


def _resolve_role(role_or_device: str, *, override: str | None = None) -> str:
    """Resolve a ``ProbeSpec.port`` value to a real device name.

    - If ``override`` is set (CLI ``--port``), return it verbatim.
    - If ``role_or_device`` looks like a real device (e.g. ``COM5`` or
      ``/dev/ttyACM0``), return it verbatim.
    - Otherwise treat it as a role: ``SUB`` -> PID 0x0019,
      ``MAIN`` -> PID 0x001A. Auto-detect via Uniden VID/PID.
    """
    if override:
        return override
    if role_or_device.upper() == "SUB":
        return _c.find_uniden_port(pid=_c.UNIDEN_SUB_PID)
    if role_or_device.upper() == "MAIN":
        return _c.find_uniden_port(pid=_c.UNIDEN_MAIN_PID)
    return role_or_device  # already a device path


@dataclass
class ProbeResult:
    spec: ProbeSpec
    classification: str
    elapsed_ms: float
    raw: bytes = field(default=b"")
    first_line: str = ""

    def hex_preview(self, n: int = 64) -> str:
        return " ".join(f"{b:02X}" for b in self.raw[:n]) + (" ..." if len(self.raw) > n else "")


def open_port(port: str, baud: int) -> serial.Serial:
    return serial.Serial(
        port=port,
        baudrate=baud,
        bytesize=8,
        parity="N",
        stopbits=1,
        timeout=0.05,
        write_timeout=0.5,
    )


def send_and_read(
    s: serial.Serial,
    command: str,
    deadline_s: float = 2.0,
    quiet_after_cr_s: float = 0.20,
) -> tuple[bytes, float]:
    s.reset_input_buffer()
    s.write((command + "\r").encode("ascii"))
    t0 = time.monotonic()
    deadline = t0 + deadline_s
    buf = bytearray()
    last_byte_t = t0
    saw_cr = False
    while time.monotonic() < deadline:
        chunk = s.read(4096)
        if chunk:
            buf.extend(chunk)
            last_byte_t = time.monotonic()
            if b"\r" in chunk or b"\n" in chunk:
                saw_cr = True
        else:
            if saw_cr and (time.monotonic() - last_byte_t) > quiet_after_cr_s:
                break
            time.sleep(0.005)
    return bytes(buf), (time.monotonic() - t0) * 1000.0


def classify(response: bytes, anchor: bytes) -> str:
    if not response:
        return "TIMEOUT"
    if response == anchor:
        return "IDENTITY"
    txt = response.decode("ascii", errors="replace").strip()
    if txt == "ERR" or txt.endswith(",ERR"):
        return "ERR"
    return "HIT"


def first_line(raw: bytes) -> str:
    txt = raw.decode("ascii", errors="replace")
    return txt.split("\r", 1)[0] if "\r" in txt else txt.strip()


def is_safe(spec: ProbeSpec, allow_destructive: bool) -> tuple[bool, str]:
    head = spec.send.split(",", 1)[0].strip()
    if head in FORBIDDEN_HEADS and not allow_destructive:
        return False, f"forbidden head '{head}' (use --allow-destructive to override)"
    if spec.destructive and not allow_destructive:
        return False, "marked destructive=True (use --allow-destructive to override)"
    return True, ""


def run_one_port(
    port_name: str, baud: int, specs: list[ProbeSpec], allow_destructive: bool
) -> list[ProbeResult]:
    """Open the port once, anchor with MDL, run all specs."""
    print(f"[*] Opening {port_name} @ {baud}...")
    try:
        s = open_port(port_name, baud)
    except serial.SerialException as e:
        print(f"[X] Cannot open {port_name}: {e}")
        return []
    try:
        time.sleep(0.05)
        anchor_raw, _ = send_and_read(s, "MDL")
        anchor_text = first_line(anchor_raw)
        print(f"    anchor MDL -> {anchor_text!r}")
        if not anchor_raw:
            print(f"[!] {port_name}: no MDL response. Scanner may not be ready.")
            return []
        results: list[ProbeResult] = []
        for spec in specs:
            ok, reason = is_safe(spec, allow_destructive)
            if not ok:
                print(f"    SKIP {spec.send!r}: {reason}")
                continue
            raw, elapsed = send_and_read(s, spec.send)
            cls = classify(raw, anchor_raw)
            r = ProbeResult(
                spec=spec, classification=cls, elapsed_ms=elapsed,
                raw=raw, first_line=first_line(raw),
            )
            results.append(r)
            print(f"    {cls:<8} {spec.send!r:<20} {r.elapsed_ms:>5.0f}ms  {r.first_line!r}")
        return results
    finally:
        try:
            s.close()
        except Exception:
            pass


def _append_hex_previews(md: list[str], results: list[ProbeResult]) -> None:
    md.append("## Hex previews (first 128 bytes)")
    md.append("")
    for r in results:
        if r.classification in ("HIT", "ERR"):
            md.append(f"- `{r.spec.send}`: `{r.hex_preview(128)}` ({len(r.raw)} B)")
    md.append("")


def _append_full_responses(md: list[str], results: list[ProbeResult]) -> None:
    md.append("## Full responses (decoded as ASCII, first 16 lines per command)")
    md.append("")
    for r in results:
        if r.classification != "HIT" or not r.raw:
            continue
        txt = r.raw.decode("ascii", errors="replace")
        lines = txt.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        md.append(f"### `{r.spec.send}` ({len(r.raw)} B, {len(lines)} lines)")
        md.append("")
        md.append("```")
        for ln in lines[:16]:
            md.append(ln)
        if len(lines) > 16:
            md.append(f"...({len(lines) - 16} more lines truncated)")
        md.append("```")
        md.append("")


def write_report(results: list[ProbeResult], tag: str, baud: int) -> tuple[Path, Path]:
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    md_path = SESSIONS_DIR / f"probe_batch_{tag}_{ts}.md" if tag else SESSIONS_DIR / f"probe_batch_{ts}.md"
    jsonl_path = md_path.with_suffix(".jsonl")

    counts: dict[str, int] = {"HIT": 0, "ERR": 0, "IDENTITY": 0, "TIMEOUT": 0}
    for r in results:
        counts[r.classification] = counts.get(r.classification, 0) + 1

    md = [
        f"# Probe batch - {ts}" + (f" - {tag}" if tag else ""),
        "",
        f"- Baud: {baud}",
        f"- Probes run: {len(results)}",
        f"- Classifications: HIT={counts['HIT']} ERR={counts['ERR']} "
        f"IDENTITY={counts['IDENTITY']} TIMEOUT={counts['TIMEOUT']}",
        "",
        "| Class | Port | Send | Label | Args hint | Time (ms) | First line |",
        "|---|---|---|---|---|---:|---|",
    ]
    for r in results:
        md.append(
            f"| {r.classification} | {r.spec.port} | `{r.spec.send}` | "
            f"{r.spec.label} | {r.spec.args_hint or '-'} | "
            f"{r.elapsed_ms:.0f} | `{r.first_line}` |"
        )
    _append_hex_previews(md, results)
    _append_full_responses(md, results)

    md_path.write_text("\n".join(md) + "\n", encoding="utf-8")

    with jsonl_path.open("w", encoding="utf-8") as f:
        for r in results:
            row = {
                "send": r.spec.send,
                "label": r.spec.label,
                "args_hint": r.spec.args_hint,
                "port": r.spec.port,
                "destructive": r.spec.destructive,
                "classification": r.classification,
                "elapsed_ms": round(r.elapsed_ms, 1),
                "first_line": r.first_line,
                "raw_hex": r.hex_preview(n=128),
            }
            f.write(json.dumps(row) + "\n")

    return md_path, jsonl_path


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--port", default=None,
                   help="Override per-spec port (e.g. COM5, /dev/ttyACM0). If "
                        "omitted, each ProbeSpec.port role ('SUB'/'MAIN') is "
                        "auto-resolved by Uniden VID/PID.")
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--tag", default="",
                   help="Optional tag appended to the report filename "
                        "(e.g. 'round4_dsp_pass1').")
    p.add_argument("--allow-destructive", action="store_true",
                   help="Permit probes whose head is in FORBIDDEN_HEADS, "
                        "or that are marked destructive=True.")
    args = p.parse_args()

    if not BATCH:
        print("[!] BATCH is empty. Edit the BATCH list in _probe_batch.py and re-run.")
        return 0

    specs = list(BATCH)

    by_port: dict[str, list[ProbeSpec]] = {}
    for spec in specs:
        try:
            device = _resolve_role(spec.port, override=args.port)
        except _c.PortDetectionError as e:
            print(f"[X] Could not resolve {spec.port!r}: {e}")
            return 2
        by_port.setdefault(device, []).append(spec)

    all_results: list[ProbeResult] = []
    for port_name, port_specs in by_port.items():
        all_results.extend(
            run_one_port(port_name, args.baud, port_specs, args.allow_destructive)
        )

    if not all_results:
        print("[!] No probes ran successfully.")
        return 1

    md_path, jsonl_path = write_report(all_results, args.tag, args.baud)
    print()
    print(f"[+] Markdown report: {md_path.relative_to(REPO_ROOT)}")
    print(f"[+] JSONL log:       {jsonl_path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
