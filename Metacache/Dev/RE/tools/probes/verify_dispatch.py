"""Live falsification probe for Ghidra-predicted SUB-port mnemonics.

Reads the ``dispatch_candidates.txt`` produced by
``analyze_ghidra_dump.py``, sends each mnemonic to the SUB processor
CDC port using the same ``MDL`` anchor-and-compare technique as
``sub_probe.py``, and classifies the response as one of:

- HIT             - response differs from the ``MDL`` anchor and is
                    not an explicit ERR. Strong evidence that the
                    mnemonic is a real command.
- ERR             - scanner returned ``ERR`` or ``,ERR``. Mnemonic is
                    parsed but rejected (likely needs args).
- IDENTITY        - response matches the ``MDL`` anchor verbatim. The
                    SUB port leaks the previous response when it
                    doesn't recognise the input - this is a NEGATIVE.
- TIMEOUT         - no response within the deadline.

Output: ``Metacache/Dev/RE/sessions/dispatch_verification_<UTC-ts>.md``.

This script is the closes-the-loop step of the Ghidra automation
pipeline: Ghidra predicts (statically), the live scanner confirms
(empirically). Mnemonics that Ghidra flags but the scanner classifies
as IDENTITY/TIMEOUT are evidence of dead code or the heuristic over-
reaching. Mnemonics that Ghidra flags AND the scanner says HIT/ERR are
real, undocumented commands.

Usage::

    # Auto-detect SUB port by Uniden VID/PID:
    py Metacache/Dev/RE/tools/probes/verify_dispatch.py
    py Metacache/Dev/RE/tools/probes/verify_dispatch.py --port COM5
    py Metacache/Dev/RE/tools/probes/verify_dispatch.py --candidates path/to/list.txt

Requires `pyserial`. Will not run if the candidates file is missing
or empty.
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

try:
    import serial  # pyserial
except ImportError:
    sys.exit("[X] pyserial is required. Install with: py -m pip install pyserial")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _common as _c  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
RE_DIR = REPO_ROOT / "AI" / "Dev" / "RE"
DEFAULT_CANDIDATES = RE_DIR / "sessions" / "dispatch_candidates.txt"

# Mnemonics we never want to send. Most of these can hang or
# brick the SUB port. Consult sub_probe.py FORBIDDEN_HEADS for the
# canonical list (we mirror it here to keep this script standalone).
FORBIDDEN_HEADS = {
    # Confirmed unsafe heads from Phase 1 (sub_probe.py).
    "DIE", "RST", "RB", "WB", "PROG", "PG", "BL", "ERA", "WIPE",
    # `h` triggers a multi-KB stream; out of scope for falsification.
    "h",
}

ANCHOR = "MDL"


@dataclass
class ProbeResult:
    mnemonic: str
    classification: str
    elapsed_ms: float
    first_line: str
    raw_hex_preview: str


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
    port: serial.Serial,
    command: str,
    deadline_s: float = 0.6,
    quiet_after_cr_s: float = 0.08,
) -> tuple[bytes, float]:
    """Mirrors `sub_probe.send_and_read`. Returns (raw, elapsed_ms)."""
    port.reset_input_buffer()
    port.write((command + "\r").encode("ascii"))
    t0 = time.monotonic()
    deadline = t0 + deadline_s
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
    if "\r" in txt:
        return txt.split("\r", 1)[0]
    return txt.strip()


def hex_preview(raw: bytes, n: int = 64) -> str:
    return " ".join(f"{b:02X}" for b in raw[:n]) + (" ..." if len(raw) > n else "")


def load_candidates(path: Path) -> list[str]:
    safe_path = _c.safe_user_path(_c.RE_ROOT, path)
    if not safe_path.exists():
        sys.exit(f"[X] candidates file not found: {safe_path}\n"
                 f"    Run Metacache/Dev/RE/tools/firmware/analyze_ghidra_dump.py first.")
    raw = safe_path.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    seen: set[str] = set()
    for line in raw:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        head = line.split(",", 1)[0]
        if head in FORBIDDEN_HEADS:
            continue
        if line in seen:
            continue
        seen.add(line)
        out.append(line)
    return out


def write_report(results: list[ProbeResult], anchor_text: str, port: str, baud: int) -> Path:
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = RE_DIR / "sessions" / f"dispatch_verification_{ts}.md"
    out.parent.mkdir(parents=True, exist_ok=True)

    counts: dict[str, int] = {"HIT": 0, "ERR": 0, "IDENTITY": 0, "TIMEOUT": 0}
    for r in results:
        counts[r.classification] = counts.get(r.classification, 0) + 1

    md = [
        f"# SUB Dispatch Verification - {ts}",
        "",
        f"- Port: `{port}` @ {baud}",
        f"- Anchor: `{anchor_text}`",
        f"- Candidates probed: {len(results)}",
        f"- Classifications: HIT={counts['HIT']} ERR={counts['ERR']} "
        f"IDENTITY={counts['IDENTITY']} TIMEOUT={counts['TIMEOUT']}",
        "",
        "## HIT (likely real undocumented commands)",
        "",
        "| Mnemonic | Time (ms) | First response line |",
        "|---|---:|---|",
    ]
    for r in results:
        if r.classification == "HIT":
            md.append(f"| `{r.mnemonic}` | {r.elapsed_ms:.0f} | `{r.first_line}` |")
    if not any(r.classification == "HIT" for r in results):
        md.append("| _(none)_ | | |")

    md += [
        "",
        "## ERR (recognised mnemonic; likely needs arguments)",
        "",
        "| Mnemonic | Time (ms) | Response |",
        "|---|---:|---|",
    ]
    for r in results:
        if r.classification == "ERR":
            md.append(f"| `{r.mnemonic}` | {r.elapsed_ms:.0f} | `{r.first_line}` |")
    if not any(r.classification == "ERR" for r in results):
        md.append("| _(none)_ | | |")

    md += [
        "",
        "## IDENTITY (anchor leakage; mnemonic NOT recognised)",
        "",
        f"_The SUB port returns the previous response (`{anchor_text}`) when_"
        " _it doesn't recognise the input. {n} mnemonics fall here, and these_"
        " _are evidence that Ghidra's heuristic over-reached._".format(
            n=counts["IDENTITY"]),
        "",
        "<details><summary>List ({n} mnemonics)</summary>".format(n=counts["IDENTITY"]),
        "",
    ]
    for r in results:
        if r.classification == "IDENTITY":
            md.append(f"- `{r.mnemonic}`")
    md.append("</details>")
    md.append("")

    md += [
        "## TIMEOUT",
        "",
        "<details><summary>List ({n} mnemonics)</summary>".format(n=counts["TIMEOUT"]),
        "",
    ]
    for r in results:
        if r.classification == "TIMEOUT":
            md.append(f"- `{r.mnemonic}`")
    md.append("</details>")
    md.append("")

    out.write_text("\n".join(md) + "\n", encoding="utf-8")
    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    _c.add_port_arg(p, help_extra="Defaults to the SUB processor (PID 0x0019).")
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    p.add_argument("--limit", type=int, default=0,
                   help="Stop after N mnemonics (0=all). Useful for smoke-testing.")
    args = p.parse_args()

    try:
        port_name = _c.require_port(args, pid=_c.UNIDEN_SUB_PID)
    except _c.PortDetectionError as e:
        sys.exit(f"[X] {e}")

    candidates = load_candidates(_c.safe_user_path(_c.RE_ROOT, args.candidates))
    if args.limit > 0:
        candidates = candidates[: args.limit]
    if not candidates:
        sys.exit(f"[X] no candidates loaded from {args.candidates}")

    print(f"[*] Opening {port_name} @ {args.baud}...")
    port = open_port(port_name, args.baud)
    print(f"[+] Port open. Anchoring with '{ANCHOR}'...")
    try:
        anchor_raw, _ = send_and_read(port, ANCHOR)
        if not anchor_raw:
            sys.exit(f"[X] anchor returned no data; is the scanner powered on and on {port_name}?")
        print(f"[+] anchor response: {first_line(anchor_raw)!r} ({len(anchor_raw)} bytes)")

        results: list[ProbeResult] = []
        for i, mnem in enumerate(candidates, start=1):
            raw, ms = send_and_read(port, mnem)
            cls = classify(raw, anchor_raw)
            results.append(
                ProbeResult(
                    mnemonic=mnem,
                    classification=cls,
                    elapsed_ms=ms,
                    first_line=first_line(raw),
                    raw_hex_preview=hex_preview(raw),
                )
            )
            tag = {"HIT": "+", "ERR": "?", "IDENTITY": "-", "TIMEOUT": "."}[cls]
            print(f"  [{tag}] {i:>4}/{len(candidates)} {mnem!r:<10} -> {cls} ({ms:.0f} ms): {first_line(raw)!r}")

            # Re-anchor every 25 probes - the SUB port can drift after
            # binary or streaming responses leak between commands.
            if (i % 25) == 0:
                fresh, _ = send_and_read(port, ANCHOR)
                if fresh and fresh != anchor_raw:
                    print(f"  [*] anchor refreshed: {first_line(fresh)!r}")
                    anchor_raw = fresh
    finally:
        try:
            port.close()
        except Exception:
            pass

    out_path = write_report(results, first_line(anchor_raw), args.port, args.baud)
    print(f"[+] wrote {out_path.relative_to(REPO_ROOT)}")
    print(f"[*] HIT={sum(1 for r in results if r.classification == 'HIT')} "
          f"ERR={sum(1 for r in results if r.classification == 'ERR')} "
          f"IDENTITY={sum(1 for r in results if r.classification == 'IDENTITY')} "
          f"TIMEOUT={sum(1 for r in results if r.classification == 'TIMEOUT')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
