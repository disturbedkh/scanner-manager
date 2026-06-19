"""Passive RE probe for the Uniden SDS100 SUB processor command port.

READ-ONLY by design. This is the SUB-targeted companion to
``serial_probe.py``. Where ``serial_probe.py`` walks a known-spec
whitelist on the MAIN port (COM4 / PID 0x001A), this script does
**alphabet-attack discovery** on the SUB port (COM3 / PID 0x0019).

The SUB port has a much smaller documented command surface (Uniden
never published it) and its 4x-echo response quirk means we must
decode unrecognized commands carefully:

    Send MDL:           SDS100-SUB\r SDS100-SUB\r SDS100-SUB\r SDS100-SUB\r
    Send VER:           Version 1.03.15 \r ... (4x)
    Send <unknown>:     <previous successful response repeated>   <- buffer leak

So a response is meaningful **only if it differs from the anchor
response**. The script sends MDL as an anchor before each candidate;
matching the anchor means "command not recognised", differing means
"REAL HIT".

Probe stages:
1. All 26 single letters: A-Z
2. All 676 two-letter combos: AA-ZZ
3. ~50 targeted 3-letter combos seeded from Sub firmware string-table
   tokens (IF*, RF*, LNA*, MIX*, VGA*, AGC*, ADC*, FFT*, LPF*, NCO*,
   CIC*, FIR*, R840*, plus high-value status candidates STA/STT/STAT)
4. ``,?`` write-acceptance form on every hit

Hard rules (matching the broader project's read-only stance):
- Never escalate ``,?`` to a write
- Never send anything matching the existing FORBIDDEN_FOR_READ_ONLY
  set in serial_probe.py
- Add SUB-specific forbid set covering reset / write / set / config /
  flash / erase / power / boot / update mnemonics

Usage::

    py Metacache/Dev/RE/sub_probe.py
    py Metacache/Dev/RE/sub_probe.py --port COM3
    py Metacache/Dev/RE/sub_probe.py --skip-2letter   # quick single + 3-letter only
    py Metacache/Dev/RE/sub_probe.py --only-targeted  # only the seeded 3-letter list

Outputs::
    Metacache/Dev/RE/sessions/sub_probe_<timestamp>.txt           (raw log)
    Metacache/Dev/RE/sessions/sub_probe_<timestamp>.summary.md    (hits table)
"""
from __future__ import annotations

import argparse
import datetime as _dt
import itertools
import string
import sys
import time
from pathlib import Path

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    sys.stderr.write(
        "pyserial is required. Install with:  py -m pip install --user pyserial\n"
    )
    sys.exit(2)


REPO_RE_DIR = Path(__file__).resolve().parent
SESSIONS_DIR = REPO_RE_DIR / "sessions"
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

# Anchor command - response must be deterministic and match Sub firmware.
ANCHOR_CMD = "MDL"
ANCHOR_EXPECTED_PREFIX = "SDS100-SUB"

# SUB-specific forbidden command heads. We never send a command
# whose head (split on "," then uppercased) is in this set.
# These are layered ON TOP of the MAIN-port FORBIDDEN_FOR_READ_ONLY
# (re-listed here for self-containedness).
FORBIDDEN_HEADS: set[str] = {
    # Reset / flash / erase / write / set / config
    "RST", "RES", "REB", "BOO",
    "WRT", "WR",  "SET", "STR",
    "CFG", "CFW", "CNF",
    "FLS", "FLA", "FSH",
    "ERS", "ERA", "DEL", "WIPE",
    "UPD", "UPG",
    # Power
    "POW", "POF", "PWR_OFF", "PWROFF", "PDN",
    # Anything that could trigger a flash routine via SD scan
    "BUR", "BRN", "BRN_FW",
    # Calibration / programming - probably mutating
    "CAL", "PRG", "EPG", "PGM",
    # Direct hardware writes
    "REG", "RGW", "RWR",       # we DON'T forbid REG read; explicit RGR allowed below
    # Audio output / squelch override (could be set forms)
    "MUT", "VOL_SET",
    # MAIN-side mutating (defensive in case SUB also routes them):
    "KEY", "QSH", "JNT", "NXT", "PRV", "HLD", "AVD", "JPM",
    "AST", "APR", "URC", "MNU", "MSV", "MSB", "PSI", "PWF",
    "GWF", "GW2", "SQK", "DQK", "CLR", "DLA", "MEMSET",
    "TGW", "VLO", "SLO", "WPL", "WPS",
}

# Allow explicit register-READ mnemonics. RGR / REGRD is safe.
# Add to QUERIES manually below if we want to try them.


# === VALIDATED unofficial SUB-port reads (Phase 1 confirmed) ===
#
# Phase 1 (Tier ABC RE plan, 2026-04-29) systematically alphabet-attacked
# the SUB port and found exactly one true unofficial hit: ``U``.
#
# These commands are READ-ONLY and safe to send. Each entry is
# (mnemonic, classification, response shape, notes).
VALIDATED_SUB_READS: list[tuple[str, str, str, str]] = [
    (
        "MDL",
        "READ",
        r"4x 'SDS100-SUB\r' echoed",
        "Spec command; confirms SUB processor is alive. Used as anchor.",
    ),
    (
        "VER",
        "READ",
        r"4x 'Version 1.03.15 \r' echoed",
        "Spec command; firmware version of the SUB MCU.",
    ),
    (
        "U",
        "READ-VOLATILE",
        r"9 bytes: 'U5C42\r\x00<2 binary bytes>'",
        (
            "Phase 1 unique hit. Last 2 bytes change between calls "
            "(samples: <\\xC1>P, <\\xC0><\\xBC>, AC, D<\\x92>, >\\x00). "
            "Likely a register / RSSI / counter dump. Response is "
            "non-printf (no matching format string in firmware), "
            "suggesting a fixed-byte register read code path. "
            "Numeric args (U,0..U,N) are accepted but ignored - "
            "same response shape regardless of N."
        ),
    ),
    (
        "h",
        "READ-STREAMING",
        r"Multi-KB stream: 'H, %ld, %ld\r' lines + 'h, %ld, %ld\r' lines",
        (
            "Phase 1b retry MAJOR finding. Lowercase 'h' (and any "
            "trailing characters: 'h0', 'h1', 'hh', 'hQ' all "
            "trigger the same response) emits the firmware format "
            "strings 'H, %ld, %ld' and 'h, %ld, %ld'. During probe "
            "all values were zero (no signal); likely emits real "
            "ADC histogram or sample counts during voice RX. "
            "Stream is FINITE - self-terminates after a few KB. "
            "SUB recovers without power cycle. CASE-SENSITIVE: "
            "uppercase 'H' did NOT trigger this in Phase 1 alphabet "
            "attack. The leading lowercase 'h' is the trigger."
        ),
    ),
]

# Known prefix-fallback false positives. The SUB firmware echoes its
# identity string for ANY input starting with these letters with the
# echo count varying by input length. So responses to these are NOT
# real command hits - they're partial-match fallbacks.
PREFIX_FALLBACK_FALSE_POSITIVES: dict[str, str] = {
    "M*": "Returns 'SDS100-SUB' identity (same as MDL). All MA-MZ, MIX*, MXR*, etc. are false hits.",
    "V*": "Returns 'Version 1.03.15' (same as VER). All VA-VZ, VGA*, VGM*, etc. are false hits.",
}

# Targeted 3-letter combos seeded from Sub firmware string-table.
# Source: Metacache/Dev/RE/firmware_analysis/sub_1.03.15.strings.txt content
# clusters around the printf format strings.
TARGETED_COMBOS: list[str] = [
    # IF / RSSI / RF / std
    "IF",  "IFR", "IFS", "IFQ", "IFM", "IFN",
    "RF",  "RFG", "RFM", "RFR", "RFS", "RFQ",
    "STD", "STM", "STA", "STT", "STAT",
    "RSI", "RSS", "RDB",
    # Gain stages - LNA1, LNA2, Mixer, VGA
    "LNA", "LN1", "LN2", "LNG", "LNAG", "LNM",
    "MIX", "MXG", "MXR", "MIXG",
    "VGA", "VGM", "VGN", "VGAM",
    "AGC", "AGM", "AGS", "AGCM",
    # ADC / DAC
    "ADC", "ADP", "ADR", "ADS", "DAC",
    # Filters
    "LPF", "LPS", "LPW", "LPN", "LPB",
    "FIR", "FR1", "FR2", "FIR1", "FIR2",
    "CIC", "CIO", "CIS",
    # NCO / FFT
    "NCO", "NCR", "NCS",
    "FFT", "FFP", "FFQ", "FFR", "FFTP", "FFTQ", "FFTR",
    # R840 tuner
    "RDR", "RGR", "TUN", "TNR", "TUNE", "TFR", "TBW",
    "R8",  "R84", "R840",
    # Audio / squelch / window
    "SQM", "SQR", "NSQ", "NSL",   # noise squelch read
    "WIN", "WND",
    # Window / status candidates not already in single-letter pass
    "DBG", "DBR", "INF", "GET", "QRY", "QRD", "REA",
    # Frequency
    "FRQ", "FREQ",
    # Heartbeat / ping-style queries the SUB may answer
    "PNG", "PIN", "ACK", "HRT", "HBT",
    # Spec V2.00 commands (already errored on COM4, retest on COM3)
    "GCS", "KAL",
]


# Phase 1b retry list seeded directly from the 35 untriggered Sub
# firmware format strings (see Metacache/Dev/RE/sub_command_response_map.md).
# The first probe pass found 0 of 35 format strings triggered, so this
# pass walks 4-5 letter mnemonics derived from the format-string tokens.
#
# Format strings used as seeds, grouped by token cluster:
#   "Widest LPF"/"Narrowest LPF"/"Default LPF"/"LPF, %d"
#   "LNAGain1"/"LNAGain2"/"MixerGain"/"RF_gain_comb"
#   "ADC P-P"/"ADC_P-P"
#   "CIC OUT"/"FIR1 OUT"/"FIR2 OUT"/"FIR2_Range"
#   "FFT_PEAK"/"FFT_FREQ"/"NCO_Range"
#   "Noise Squelch"
#   "Window"
#   "IF=%d, STD= %s"
#   "IfRssi"/"RssiDbm"
#   "REG[..]"
#   "H, %ld, %ld" / "h, %ld, %ld"   (note lowercase form in firmware)
TARGETED_COMBOS_V2: list[str] = [
    # === LPF preset / query candidates ===
    # Strings: "Widest LPF", "Narrowest LPF", "LPF, %d", "Default LPF"
    "LPFW", "LPFN", "LPFD", "LPFQ", "LPFR", "LPFS",
    "WLPF", "NLPF", "DLPF", "QLPF",
    "WIDE", "NAR",  "WID",  "DEF",
    # === Gain readout candidates ===
    # Strings: "RF_gain_comb,%d", "LNAGain1,%d", "LNAGain2,%d", "MixerGain,%d"
    "RFGN", "RFGC", "RFGM", "RFGQ", "RFGR",
    "RFC",  "RFCN", "RFCG",
    "GAIN", "GN",   "GAN",  "GNQ",  "GNR",
    "LNG1", "LNG2", "LG1",  "LG2",
    "LNAG", "LNAQ", "LNAR",
    # MIX / MXG / MXR triggered M*-fallback in pass 1; skip those heads.
    # Try 4-5 letter forms that don't start with M.
    # === ADC P-P candidates ===
    # String: "ADC P-P, %d, %fmV", "ADC_P-P,%d"
    "ADCP", "ADPP", "ADCQ", "ADCR", "ADP",
    "APP",  "ADCS",
    # === CIC / FIR / NCO / FFT debug ===
    # Strings: "CIC OUT", "FIR1 OUT", "FIR2 OUT", "FIR2_Range",
    #         "FFT_PEAK,%ddB", "FFT_FREQ,%d", "NCO_Range"
    "CICO", "CICR", "CICQ", "CICS",
    "FIRO", "FIRR", "FIRQ", "FIRS",
    "FIR1Q", "FIR2Q", "FIR1R", "FIR2R",
    "FOUT", "F1O",  "F2O",  "FRO",
    "FFTQ", "FFTR", "FFTP", "FFTF",
    "NCOQ", "NCOR", "NCOR2",
    "PEAK", "PEAQ", "PEK",
    "RNG",  "RANGE",
    # === Noise squelch / window ===
    # Strings: "Noise Squelch,%6d", "Window,%d"
    "NSQ",  "NSQR", "NSQQ", "NS",   "NSL",
    "WND",  "WIN",  "WINQ", "WNDQ", "WINDOW",
    # === IF / STD / RSSI ===
    # Strings: "IF=%d, STD= %s", "IfRssi,%d", "RssiDbm,%d"
    "IF",   "IFR",  "IFQ",  "IFS",  "IFN",  "IFRS",
    "STD",  "STDQ", "STDR", "STDM", "STDV",
    "RSSI", "RSDB", "RSD",  "RDB",  "RDBM", "DBM",
    "IRS",  "IRSI",
    # === REG[..] register dump ===
    # String: "REG[%2d],%02X, REG[%2d],%02X, ..."
    # NOTE: bare REG is in FORBIDDEN_HEADS. Use RGR / RDR / read-style.
    "RGR",  "RGRD", "RDR",  "RD",   "RR",
    "REGR", "REGQ", "REGN",
    # === STATUS string variants ===
    # String: "S%02X%04X%04X%04X%04X%01X%04X" already shows the wire format.
    # Try uncovered S-prefix variants (avoid forbidden STR/SET/STR0).
    "STX",  "STZ",  "STSQ", "STSR", "SR",   "SS",   "SQRY",
    "STAT", "STAR", "STATU", "S0",   "S1",
    # === Lowercase variants ===
    # Strings include both "H, %ld, %ld" and "h, %ld, %ld" - the
    # firmware has uppercase- and lowercase-keyed handlers. Test
    # lowercase forms by sending raw bytes that bypass the
    # gen_alphabet upcasing path.
    "h",    "h0",   "h1",   "hh",   "hQ",
    # === Numeric-arg forms for already-tested heads ===
    # If U returns a register dump, U,1 / U,2 / U0 / U1 might select
    # which register is dumped.
    "U,0",  "U,1",  "U,2",  "U,3",  "U0",   "U1",   "U2",   "U3",
    "U?",
    # === Status with numeric ===
    "S,0",  "S,1",  "S,2",
    # === Common short-RPC mnemonics not yet covered ===
    "GET",  "READ", "RD0",  "RD1",  "PEEK",
    "DBG0", "DBG1", "DBG2", "DBGM",
    "QRY",  "PING", "ECHO", "ID",   "WHO",
    "SYS",  "SYSI", "SI",   "SYSQ", "STAT0",
]

DESCRIBE_PORTS_HEADER = "# Available ports at start:\n"


def list_ports() -> list[str]:
    return [p.device for p in serial.tools.list_ports.comports()]


def describe_ports() -> str:
    out = []
    for p in serial.tools.list_ports.comports():
        out.append(f"#   {p.device}  {p.description}  [HWID {p.hwid}]")
    return "\n".join(out) if out else "#   (no COM ports found)"


def auto_pick_sub_port() -> str | None:
    """Pick the first COM port matching VID 0x1965 PID 0x0019."""
    for p in serial.tools.list_ports.comports():
        if p.vid == 0x1965 and p.pid == 0x0019:
            return p.device
    return None


def show(buf: bytes) -> str:
    """Pretty-print bytes for logs."""
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


def head_of(cmd: str) -> str:
    return cmd.split(",", 1)[0].strip().upper()


def is_forbidden(cmd: str) -> bool:
    return head_of(cmd) in FORBIDDEN_HEADS


def send_and_read(
    port: serial.Serial,
    command: str,
    deadline_s: float = 0.6,
    quiet_after_cr_s: float = 0.08,
) -> tuple[bytes, float]:
    """Send a command and read until quiet. Returns (bytes, elapsed_ms).

    Same pattern as serial_probe._send_and_read, slightly faster
    timeout because SUB responses are short and the alphabet-attack
    has 700+ probes.

    Defensive cleanup: aggressively drains both buffers before each
    send so leftover bytes from a previous binary response (some SUB
    commands return non-ASCII bytes that don't terminate cleanly)
    don't bleed into the next read.
    """
    # Pre-send drain: clear any leftover bytes from a previous binary
    # response (some SUB commands return non-ASCII bytes that don't
    # terminate cleanly). reset_input_buffer is fast on USB CDC and
    # mirrors what _com3_probe.py and serial_probe.py do.
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


def classify(
    response: bytes,
    anchor_response: bytes,
) -> str:
    """Return one of: 'unrecognised', 'err', 'timeout', 'hit'."""
    if not response:
        return "timeout"
    txt = response.decode("ascii", errors="replace")
    # The buffer-leak fingerprint: response equals the anchor.
    if response == anchor_response:
        return "unrecognised"
    # Recognised-but-invalid-form
    stripped = txt.strip()
    if stripped == "ERR" or stripped.endswith(",ERR"):
        return "err"
    # Anything else is a real hit (different from anchor and non-ERR).
    return "hit"


def first_response_line(response: bytes) -> str:
    """Return the first \\r-terminated line, stripped."""
    txt = response.decode("ascii", errors="replace")
    if "\r" in txt:
        return txt.split("\r", 1)[0]
    return txt.strip()


def gen_alphabet(stages: list[str]) -> list[str]:
    """Build the candidate command list for the requested stages.

    stages: subset of ['1', '2', 'targeted', 'targeted2']

    Note: stages '1' / '2' / 'targeted' upcase their entries (case
    didn't matter for the original firmware-string seeds). Stage
    'targeted2' preserves case verbatim because the format-string
    table contains both uppercase ("H, %ld, %ld") and lowercase
    ("h, %ld, %ld") variants - the firmware has distinct handlers
    for each case. We pass 'h' through unmodified.
    """
    out: list[str] = []
    seen: set[str] = set()

    def add(c: str, *, preserve_case: bool = False) -> None:
        if not preserve_case:
            c = c.upper()
        if c in seen:
            return
        seen.add(c)
        out.append(c)

    if "1" in stages:
        for c in string.ascii_uppercase:
            add(c)
    if "2" in stages:
        for a, b in itertools.product(string.ascii_uppercase, repeat=2):
            add(a + b)
    if "targeted" in stages:
        for c in TARGETED_COMBOS:
            add(c)
    if "targeted2" in stages:
        for c in TARGETED_COMBOS_V2:
            add(c, preserve_case=True)
    return out


def probe(
    port_dev: str,
    candidates: list[str],
    log_path: Path,
    summary_path: Path,
    qform_on_hit: bool = True,
) -> dict[str, list]:
    """Run the alphabet attack. Returns a results dict for the summary."""
    print(f"# Opening {port_dev} @ 115200 8N1 ...")
    p = serial.Serial(port_dev, 115200, timeout=0.05)

    # Stats
    hits: list[tuple[str, bytes, float]] = []
    errs: list[tuple[str, float]] = []
    unrec_count = 0
    timeout_count = 0
    forbidden_skipped: list[str] = []

    log = open(log_path, "w", encoding="utf-8", errors="replace", buffering=1)
    log.write("# SDS100 SUB-port systematic probe\n")
    log.write(f"# When     : {_dt.datetime.now().isoformat()}\n")
    log.write(f"# Port     : {port_dev}\n")
    log.write(f"# Anchor   : {ANCHOR_CMD!r} (expected to start with {ANCHOR_EXPECTED_PREFIX!r})\n")
    log.write(f"# Forbidden: {sorted(FORBIDDEN_HEADS)}\n")
    log.write(DESCRIBE_PORTS_HEADER)
    log.write(describe_ports() + "\n\n")

    try:
        # Set the anchor.
        anchor_resp, anchor_ms = send_and_read(p, ANCHOR_CMD)
        log.write(f">>> ANCHOR={ANCHOR_CMD}   {len(anchor_resp)}B in {anchor_ms:.1f} ms\n")
        log.write(f"    raw  : {anchor_resp!r}\n")
        log.write(f"    show : {show(anchor_resp)}\n\n")
        if not anchor_resp.startswith(ANCHOR_EXPECTED_PREFIX.encode()):
            log.write(
                f"!! ANCHOR did not start with {ANCHOR_EXPECTED_PREFIX!r} - "
                f"sub port may be in an unexpected mode. Continuing anyway.\n"
            )

        last_progress_t = time.monotonic()
        for i, cmd in enumerate(candidates, 1):
            if is_forbidden(cmd):
                forbidden_skipped.append(cmd)
                continue

            response, elapsed_ms = send_and_read(p, cmd)
            cls = classify(response, anchor_resp)

            # Periodic progress so the user sees the probe is alive.
            now = time.monotonic()
            if now - last_progress_t >= 5.0:
                msg = (
                    f"# progress {i}/{len(candidates)}  "
                    f"hits={len(hits)}  errs={len(errs)}  "
                    f"unrec={unrec_count}  to={timeout_count}"
                )
                print(msg, flush=True)
                log.write(msg + "\n")
                last_progress_t = now

            if cls == "hit":
                hits.append((cmd, response, elapsed_ms))
                log.write(
                    f"[{i:5d}/{len(candidates):5d}]  HIT      {cmd:8s}  "
                    f"{len(response):4d}B in {elapsed_ms:6.1f} ms  "
                    f"| {show(response)}\n"
                )
            elif cls == "err":
                errs.append((cmd, elapsed_ms))
                log.write(
                    f"[{i:5d}/{len(candidates):5d}]  err      {cmd:8s}  "
                    f"{len(response):4d}B in {elapsed_ms:6.1f} ms\n"
                )
            elif cls == "timeout":
                timeout_count += 1
            else:
                unrec_count += 1

            # If response is non-ASCII binary, the SUB may still be
            # streaming bytes for a long time. Pause heavily and skip
            # both qform and re-anchor to avoid hanging the probe on
            # leftover buffered bytes.
            response_is_binary = any(b > 0x7e or b < 0x09 for b in response)
            if response_is_binary:
                time.sleep(0.2)
                # Drain any stragglers.
                drain_until = time.monotonic() + 0.1
                while time.monotonic() < drain_until:
                    if p.in_waiting:
                        p.read(p.in_waiting)
                        drain_until = time.monotonic() + 0.05
                    else:
                        time.sleep(0.005)
                continue  # next candidate without qform / re-anchor

            if cls == "hit" and qform_on_hit and "," not in cmd:
                qf = cmd + ",?"
                if not is_forbidden(qf):
                    qresp, qms = send_and_read(p, qf)
                    qcls = classify(qresp, anchor_resp)
                    log.write(
                        f"            qform   {qf:8s}  "
                        f"{len(qresp):4d}B in {qms:6.1f} ms  cls={qcls}  "
                        f"| {show(qresp)}\n"
                    )

            # Re-anchor after any non-timeout event so buffer drift
            # doesn't bleed a previous hit's response into the next
            # unrecognised candidate's classification.
            if cls in ("hit", "err"):
                new_anchor, _ = send_and_read(p, ANCHOR_CMD)
                # Only update anchor if it looks valid; otherwise keep the
                # original to avoid lock-step misclassification on weird
                # SUB states.
                if new_anchor.startswith(ANCHOR_EXPECTED_PREFIX.encode()):
                    anchor_resp = new_anchor

        log.write(
            f"\n# Done. {len(hits)} HIT, {len(errs)} err, "
            f"{unrec_count} unrec, {timeout_count} timeout, "
            f"{len(forbidden_skipped)} forbidden-skipped of {len(candidates)} candidates.\n"
        )

    finally:
        p.close()
        log.close()

    # Summary file
    with open(summary_path, "w", encoding="utf-8", errors="replace") as s:
        s.write("# SDS100 SUB-port probe - hits summary\n\n")
        s.write(f"- Port: `{port_dev}`\n")
        s.write(f"- Anchor: `{ANCHOR_CMD}` -> `{first_response_line(anchor_resp)}`\n")
        s.write(f"- Total candidates: {len(candidates)}\n")
        s.write(f"- HITS: **{len(hits)}**\n")
        s.write(f"- ERR:  {len(errs)}\n")
        s.write(f"- Unrecognised (buffer-echo): {unrec_count}\n")
        s.write(f"- Timeouts: {timeout_count}\n")
        s.write(f"- Forbidden-skipped: {len(forbidden_skipped)}\n\n")
        s.write("## Hits (response differs from anchor and is not ERR)\n\n")
        s.write("| Cmd | Bytes | First line | Raw (escaped) |\n")
        s.write("| --- | ---: | --- | --- |\n")
        for cmd, resp, _ms in hits:
            first = first_response_line(resp).replace("|", "\\|")[:80]
            raw = show(resp).replace("|", "\\|")[:120]
            s.write(f"| `{cmd}` | {len(resp)} | `{first}` | `{raw}` |\n")
        s.write("\n## ERRs (recognised but invalid form)\n\n")
        for cmd, _ms in errs[:200]:
            s.write(f"- `{cmd}`\n")
        if len(errs) > 200:
            s.write(f"- ... and {len(errs) - 200} more\n")

    return {
        "hits": hits,
        "errs": errs,
        "unrec": unrec_count,
        "timeout": timeout_count,
        "forbidden": forbidden_skipped,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", default=None,
                    help="COM port (default: auto-detect VID 1965 PID 0019)")
    ap.add_argument("--skip-1letter", action="store_true",
                    help="Skip the single-letter pass")
    ap.add_argument("--skip-2letter", action="store_true",
                    help="Skip the two-letter pass (use for quick run)")
    ap.add_argument("--skip-targeted", action="store_true",
                    help="Skip the targeted 3-letter pass")
    ap.add_argument("--only-targeted", action="store_true",
                    help="Only run the targeted 3-letter pass")
    ap.add_argument("--only-targeted2", action="store_true",
                    help="Only run the format-string-derived 4-5 letter pass (Phase 1b retry)")
    ap.add_argument("--include-targeted2", action="store_true",
                    help="Add the format-string-derived 4-5 letter pass on top of selected stages")
    ap.add_argument("--no-qform", action="store_true",
                    help="Skip the ,? form on hits")
    args = ap.parse_args()

    port = args.port or auto_pick_sub_port()
    if not port:
        sys.stderr.write(
            "Could not find an SDS100 SUB port (VID 0x1965 PID 0x0019).\n"
            "Specify --port manually.\n\n"
            "Available ports:\n" + describe_ports() + "\n"
        )
        sys.exit(1)

    if args.only_targeted2:
        stages = ["targeted2"]
    elif args.only_targeted:
        stages = ["targeted"]
    else:
        stages = []
        if not args.skip_1letter:
            stages.append("1")
        if not args.skip_2letter:
            stages.append("2")
        if not args.skip_targeted:
            stages.append("targeted")
        if args.include_targeted2:
            stages.append("targeted2")

    candidates = gen_alphabet(stages)
    print(f"# stages={stages}  candidates={len(candidates)}  port={port}")

    ts = _dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    log_path = SESSIONS_DIR / f"sub_probe_{ts}.txt"
    sum_path = SESSIONS_DIR / f"sub_probe_{ts}.summary.md"

    results = probe(
        port,
        candidates,
        log_path,
        sum_path,
        qform_on_hit=not args.no_qform,
    )

    print("\n# Probe complete.")
    print(f"# Hits: {len(results['hits'])}")
    print(f"# Errs: {len(results['errs'])}")
    print(f"# Forbidden-skipped: {len(results['forbidden'])}")
    print(f"# Log:     {log_path}")
    print(f"# Summary: {sum_path}")

    if results["hits"]:
        print("\n# Hits:")
        for cmd, resp, _ms in results["hits"]:
            first = first_response_line(resp)[:80]
            print(f"  {cmd:8s}  {first}")


if __name__ == "__main__":
    main()
