"""Test the `t` and `u` mode-toggle hypotheses.

Decompile says:
- `t` toggles `*DAT_14006f68` between 0 and 1.
- `u` toggles `*DAT_14006f68` between 0 and 2.

So this byte takes 3 values: {0, 1, 2}. The handlers for q/w/r/m/v/o
likely consult this flag and emit different formats / data depending on
its value.

Sequence:
1. Send 'q' (baseline, mode = ?)
2. Send 't' (silent toggle)
3. Send 'q' (with new mode)
4. Send 't' (toggle back)
5. Send 'q' (should match step 1)
6. Send 'u' (silent toggle to value 2 or 0)
7. Send 'q' (with mode = 2)
8. Send 'u' (toggle to 0)
9. Send 'q' (mode = 0)

We compare bytes-out of each `q` to detect format/content changes.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import serial

ROOT = Path(__file__).resolve().parents[3]
PORT = sys.argv[1] if len(sys.argv) > 1 else "COM3"
SESS = ROOT / "AI" / "Dev" / "RE" / "sessions" / "round4_toggle_test.md"


def send_and_read(s: serial.Serial, cmd: str, deadline: float = 1.5) -> bytes:
    s.reset_input_buffer()
    s.write((cmd + "\r").encode("ascii"))
    t0 = time.monotonic()
    buf = bytearray()
    last = t0
    while time.monotonic() < t0 + deadline:
        chunk = s.read(4096)
        if chunk:
            buf.extend(chunk)
            last = time.monotonic()
        elif buf and time.monotonic() - last > 0.18:
            break
        else:
            time.sleep(0.005)
    return bytes(buf)


s = serial.Serial(PORT, 115200, timeout=0.05, write_timeout=0.5)
print(f"[*] {PORT} open. Anchoring with MDL...")
anchor = send_and_read(s, "MDL")
first_line = anchor.decode("ascii", errors="replace").split("\r", 1)[0]
print(f"    anchor first line: {first_line!r}")
time.sleep(0.1)


def fp(label: str, b: bytes) -> dict:
    """Brief signature of a response."""
    return {
        "label": label,
        "bytes": len(b),
        "first16hex": b[:16].hex(),
        "last16hex": b[-16:].hex() if len(b) > 16 else "",
        "lines": b.count(b"\r") + b.count(b"\n"),
        "first_line": b.decode("ascii", errors="replace").split("\r", 1)[0][:80],
    }


# Run the experiment
results = []
for label, cmd in [
    ("baseline q", "q"),
    ("after t#1",  "t"),  # silent
    ("q (mode B)", "q"),
    ("after t#2",  "t"),  # silent
    ("q (back)",   "q"),
    ("after u#1",  "u"),  # silent
    ("q (mode C)", "q"),
    ("after u#2",  "u"),  # silent
    ("q (back2)",  "q"),
    # Also test 'r' modes
    ("baseline r", "r"),
    ("after t#3",  "t"),
    ("r (mode B)", "r"),
    ("after t#4",  "t"),
    ("r (back)",   "r"),
]:
    raw = send_and_read(s, cmd)
    fp_ = fp(label, raw)
    results.append((cmd, fp_))
    print(f"  {label:20s} send={cmd!r:>5}  {fp_['bytes']:>5} B  "
          f"first_line={fp_['first_line']!r}")
s.close()

# Save markdown
md = ["# Round 4 toggle test - t/u mode flags", ""]
md.append("Hypothesis: t toggles a byte 0<->1, u toggles 0<->2. The byte is "
          "consulted by q/r and possibly other dump commands. Comparing q "
          "and r outputs across toggle states should reveal the dependency.")
md.append("")
md.append("| Step | Sent | Bytes | First 16 hex | Lines | First line |")
md.append("|---|---:|---:|---|---:|---|")
for cmd, f in results:
    md.append(
        f"| {f['label']} | `{cmd}` | {f['bytes']} | `{f['first16hex']}` | "
        f"{f['lines']} | `{f['first_line']}` |"
    )
md.append("")
md.append("## Analysis")
md.append("")

# Compare q outputs
q_steps = [r for r in results if r[0] == "q"]
if len(q_steps) >= 2:
    md.append("### `q` byte-count by toggle state")
    md.append("")
    for _cmd, f in q_steps:
        md.append(f"- {f['label']}: {f['bytes']} B, first_line `{f['first_line']}`")
    md.append("")
    sigs = [(f["bytes"], f["first16hex"]) for _, f in q_steps]
    if len(set(sigs)) > 1:
        md.append("**Conclusion: q output VARIES across toggle states - "
                  "t and/or u DO modify q's output format/content.**")
    else:
        md.append("**Conclusion: q output is identical across toggle states - "
                  "t and u DO NOT affect q (might affect other dumps).**")
    md.append("")

r_steps = [r for r in results if r[0] == "r"]
if len(r_steps) >= 2:
    md.append("### `r` byte-count by toggle state")
    md.append("")
    for _cmd, f in r_steps:
        md.append(f"- {f['label']}: {f['bytes']} B, first_line `{f['first_line']}`")
    md.append("")

SESS.parent.mkdir(parents=True, exist_ok=True)
SESS.write_text("\n".join(md) + "\n", encoding="utf-8")
print(f"[+] Wrote {SESS.relative_to(ROOT)}")
