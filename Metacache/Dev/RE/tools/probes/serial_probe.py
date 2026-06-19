"""Passive RE probe for the Uniden SDS100 (and SDS200) over serial / USB CDC.

READ-ONLY by design. This script is for reverse-engineering the live
scanner's command surface without touching its state. Every command in
the WHITELIST below is sourced from the official Uniden
``SDS100/SDS200/SDS150 Remote Command Specification`` - V1.02
(2023-12-22) for the original surface and V2.00 (2025-07-07) for
commands added in firmware 1.23.20+ (``KAL``, ``GCS``, ``GW2``,
``POF``). Both spec PDFs are mirrored at ``Metacache/Dev/RE/`` in this repo.

The script:

- enumerates COM ports, picks the new one introduced by the scanner
  switching into serial mode (or honors --port);
- opens it at 115200 8N1 (USB CDC virtual COM port - baud is nominal,
  the scanner ignores it but pyserial wants a value);
- sends each whitelisted command, waits up to ~1 s for a response;
- captures every byte verbatim into a timestamped session log under
  ``Metacache/Dev/RE/sessions/``;
- never sends anything that simulates a key press, enters programming
  mode, writes config, starts/stops a recording or analysis pass,
  enables a continuous push stream, or otherwise changes scanner
  state.

To extend the probe with a new query command, add it to ``QUERIES``
ONLY after confirming it is read-only in the spec. The bare form must
take no arguments (or only well-known constant arguments like
``GLT,FL``) and must NOT enable a periodic push (``PSI``, ``PWF``,
``GWF`` are forbidden for that reason).

Modes:

- ``--mode query`` (default): runs the QUERIES list once and exits.
- ``--mode poll``: repeatedly sends a single command (default GLG) at
  ``--poll-interval`` for ``--poll-duration`` seconds. Use to catch
  GLG-during-RX or to map STS bit churn over time.
- ``--mode diff``: snapshot / pause-for-input / snapshot loop. Use to
  diff STS or GSI between two scanner states (e.g. "before pressing
  HOLD" vs "after"). User drives the toggle on the scanner.

Usage::

    py Metacache/Dev/RE/serial_probe.py
    py Metacache/Dev/RE/serial_probe.py --port COM4
    py Metacache/Dev/RE/serial_probe.py --mode poll --poll-cmd GLG --poll-duration 30
    py Metacache/Dev/RE/serial_probe.py --mode diff --diff-cmd STS

Outputs are written into ``Metacache/Dev/RE/sessions/<timestamp>.txt`` and
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

# ---------------------------------------------------------------------------
# Spec-aligned query whitelist
# ---------------------------------------------------------------------------
# Sources are tagged in the comment column:
#   [SPEC]    = command #N in the Uniden SDS100/SDS200 Remote Command Spec
#               V1.02. Read-only bare/parameterised form, no push enable.
#   [INH]     = inherited BCDx36HP-family command, NOT in the SDS100/SDS200
#               spec but observed to work on this firmware (Session 2).
#               Kept for regression coverage.
#   [LEGACY?] = inherited BCDx36HP-family command that ERR'd on Session 2.
#               Kept to catch any firmware revival; expected to ERR.
#   [QFORM]   = ",?" write-acceptance probe (non-mutating; the scanner
#               replies "OK" if the command has a write form, "ERR" if not).
#               We never escalate ",?" to an actual write.
# ---------------------------------------------------------------------------

QUERIES: List[tuple[str, str]] = [
    # === SDS100/SDS200 Remote Command Spec V1.02 - read-only ===
    ("model",                "MDL"),         # [SPEC #1]  Get Model Info
    ("firmware",             "VER"),         # [SPEC #2]  Get Firmware Version
    ("status_display",       "STS"),         # [SPEC #5]  Get Current Status
    ("favorites_qkeys",      "FQK"),         # [SPEC #9]  Get FL Quick-Key states (bare = read)
    ("get_scanner_info",     "GSI"),         # [SPEC #13] Get Scanner Information (XML, single-shot)
    ("svc_types",            "SVC"),         # [SPEC #17] Get Service Type mask (37 PST + 10 CST)
    ("date_time",            "DTM"),         # [SPEC #19] Get Date and Time + RTC status
    ("location_range",       "LCR"),         # [SPEC #20] Get Location and Range
    ("menu_status",          "MSI"),         # [SPEC #25] Get Menu Status Info (returns ERR outside menu mode; that's fine)
    ("scanner_status_wf",    "GST"),         # [SPEC #28] Get scanner status (for Waterfall) - superset of STS
    # === V2.00 spec additions (2025-07-07; need FW 1.23.20 or later) ===
    ("charge_status",        "GCS"),         # [SPEC V2.00 #32] Get Charge Status (read-only; \n-terminated!)
    ("keep_alive",           "KAL"),         # [SPEC V2.00] Keep Alive - no response expected (heartbeat)
    # GLT (Get xxx List) - read-only structured queries. The "FL" form
    # has no parameter and works at any time. The other GLT subforms
    # require an index from a previous response and are skipped here;
    # add them to a deeper probe pass once we've parsed FL output.
    ("glt_favorites",        "GLT,FL"),          # [SPEC #14] List favorites
    ("glt_search_avoid",     "GLT,AFREQ"),       # [SPEC #14] List avoiding frequencies
    ("glt_fire_tone_out",    "GLT,FTO"),         # [SPEC #14] List FTO channels
    ("glt_custom_banks",     "GLT,CS_BANK"),     # [SPEC #14] List custom-search banks
    ("glt_inner_rec",        "GLT,IREC_FILE"),   # [SPEC #14] List inner-record files
    ("glt_user_rec_folders", "GLT,UREC"),        # [SPEC #14] List user-record folders
    ("glt_trunk_discovery",  "GLT,TRN_DISCOV"),  # [SPEC #14] List trunk discovery sessions
    ("glt_conv_discovery",   "GLT,CNV_DISCOV"),  # [SPEC #14] List conventional discovery sessions

    # === Inherited BCDx36HP commands NOT in the spec, observed to work ===
    # Session 2 confirmed these still respond on FW 1.23.07 even though
    # the SDS100/SDS200 spec V1.02 doesn't list them. They look like
    # holdovers from the BCD536HP/BCD436HP spec V1.05 from which the
    # SDS200 spec was forked (per the spec's revision history).
    ("glcd_info",            "GLG"),         # [INH] Reception info (12 fields; populated only during RX)
    ("power_freq",           "PWR"),         # [INH] RSSI dBm + tuned frequency
    ("volume",               "VOL"),         # [INH] Current volume (also exposed in GSI <Property VOL>)
    ("squelch",              "SQL"),         # [INH] Current squelch (also exposed in GSI <Property SQL>)

    # === Inherited commands that ERR'd in Session 2 (regression check) ===
    # Kept in the run so we'll notice if a firmware update revives any
    # of these. Each is expected to return ERR or no response.
    ("rsi",                  "RSI"),         # [LEGACY?] RSSI/radio status info
    ("battery",              "BAV"),         # [LEGACY?] battery voltage (BCD-era)
    ("backlight",            "BLT"),         # [LEGACY?]
    ("contrast",             "CNT"),         # [LEGACY?]
    ("display_mode",         "DMA"),         # [LEGACY?]
    ("scan_state",           "SCN"),         # [LEGACY?]
    ("close_call_band",      "CBP"),         # [LEGACY?]
    ("custom_search_status", "CSP"),         # [LEGACY?]
    ("location_get",         "LOC"),         # [LEGACY?] (LCR replaces this on SDS spec)
    ("gps_get",              "GIN,GPS"),     # [LEGACY?]
    ("clock",                "CLK"),         # [LEGACY?] (DTM replaces this on SDS spec)
    ("owner_info",           "OMS"),         # [LEGACY?]
    ("backlight_info",       "BLI"),         # [LEGACY?]
    ("memory_info",          "MEM"),         # [LEGACY?]
    ("priority_state",       "PRI"),         # [LEGACY?]
    ("alert_status",         "ALT"),         # [LEGACY?]
    ("get_remote_id",        "GID"),         # [LEGACY?]
    ("number_tag",           "NTG"),         # [LEGACY?]
    ("waterfall_setting",    "WFL"),         # [LEGACY?]
    ("favorite_list",        "FAV"),         # [LEGACY?] (FQK replaces this on SDS spec)
    ("rangelist_get",        "RLG"),         # [LEGACY?]

    # === ",?" write-acceptance probes (non-mutating; never escalated) ===
    # On Session 2 we observed VOL,? -> VOL,OK and SQL,? -> SQL,OK,
    # indicating ",?" is a "does this command accept writes?" probe.
    # We use it to distinguish "command not recognised at all" from
    # "command is a known-write that is read elsewhere."
    ("model_qform",          "MDL,?"),       # [QFORM]
    ("firmware_qform",       "VER,?"),       # [QFORM]
    ("status_qform",         "STS,?"),       # [QFORM]
    ("glcd_qform",           "GLG,?"),       # [QFORM]
    ("volume_qform",         "VOL,?"),       # [QFORM]
    ("squelch_qform",        "SQL,?"),       # [QFORM]
    ("svc_qform",            "SVC,?"),       # [QFORM]
    ("dtm_qform",            "DTM,?"),       # [QFORM]
    ("lcr_qform",            "LCR,?"),       # [QFORM]
    ("fqk_qform",            "FQK,?"),       # [QFORM]
    ("gcs_qform",            "GCS,?"),       # [QFORM] V2.00 read-only - expect ERR
    ("kal_qform",            "KAL,?"),       # [QFORM] V2.00 keep-alive - expect ERR

    # === Phase 2: Argument-extension probes (B1) - undocumented arg forms ===
    # Firmware sometimes accepts undocumented arg variants on documented
    # commands. These probes exercise plausible variants on GSI / STS /
    # GLT / MSI / GST. None should mutate state - they're just trying
    # extra args on commands we already know are read-only.
    # === VALIDATED unofficial reads (Phase 2 confirmed READ-only on FW 1.26.01) ===
    ("gsi_xml",              "GSI,XML"),     # [B1-VALIDATED-READ] same payload as bare GSI
    ("gsi_raw",              "GSI,RAW"),     # [B1-VALIDATED-READ] same payload as bare GSI
    ("gsi_prop",             "GSI,PROP"),    # [B1-VALIDATED-READ] adds <SiteFrequency SAD=...> attr
    ("gsi_full",             "GSI,FULL"),    # [B1-VALIDATED-READ] adds <SiteFrequency SAD=...> attr
    ("sts_1",                "STS,1"),       # [B1] alternate status view
    ("sts_wide",             "STS,WIDE"),    # [B1] wide status view
    ("sts_full",             "STS,FULL"),    # [B1] full status view
    ("glt_chn",              "GLT,CHN"),     # [B1] channel list (undocumented?)
    ("glt_grp",              "GLT,GRP"),     # [B1] group list
    ("glt_sys",              "GLT,SYS"),     # [B1-VALIDATED-READ] returns full system list across all FLs (undocumented but works)
    ("glt_dept",             "GLT,DEPT"),    # [B1] department list
    ("glt_site",             "GLT,SITE"),    # [B1] site list
    ("glt_uid",              "GLT,UID"),     # [B1] talkgroup ID list
    ("glt_rx",                "GLT,RX"),     # [B1] RX history list
    ("glt_log",              "GLT,LOG"),     # [B1] event log list
    ("glt_bnd",              "GLT,BND"),     # [B1] band plan list
    ("glt_bank",             "GLT,BANK"),    # [B1] bank list
    ("msi_stat",             "MSI,STAT"),    # [B1] MSI without menu entry
    ("msi_peek",             "MSI,PEEK"),    # [B1] MSI peek
    ("msi_curr",             "MSI,CURR"),    # [B1] MSI current
    ("gst_1",                "GST,1"),       # [B1] GST variant 1
    ("gst_x",                "GST,X"),       # [B1] GST variant X
    ("gst_full",             "GST,FULL"),    # [B1] GST full
    ("gsi_qform2",           "GSI,XML,?"),   # [QFORM-VALIDATED] returns "no department/TGID resolved" XML view (Index="4294967295" placeholders) - useful mid-handoff diagnostic

    # === Phase 3: BCDx36HP V1.05 spec-derived GLT subforms (A2) ===
    # The BCDx36HP V1.05 spec documents additional GLT subforms that
    # weren't in SDS V1.02 / V2.00. Sourced from
    # Metacache/Dev/RE/BCDx36HP_RemoteCommand_Specification_V1_05.txt:
    # GLT command tables list these as valid read keywords. Most need
    # a parent index, so we probe the bare form first (may ERR with
    # informative shape) and an index=0 form for index-required ones.
    ("glt_stgid_bare",       "GLT,STGID"),       # [V1.05] TGID in ID Search
    ("glt_stgid_0",          "GLT,STGID,0"),     # [V1.05] (needs site_index)
    ("glt_cc_bare",          "GLT,CC"),          # [V1.05] Close Call list
    ("glt_wx_bare",          "GLT,WX"),          # [V1.05] Weather channel list
    ("glt_sws_freq_bare",    "GLT,SWS_FREQ"),    # [V1.05] search-with-scan freqs
    ("glt_sws_freq_0",       "GLT,SWS_FREQ,0"),  # [V1.05] (needs dept_index)
    ("glt_cchit_bare",       "GLT,CCHIT"),       # [V1.05] CC Hits Channel
    ("glt_cchit_0",          "GLT,CCHIT,0"),     # [V1.05] (needs dept_index)
    ("glt_cs_freq_bare",     "GLT,CS_FREQ"),     # [V1.05] Custom Search freqs
    ("glt_cs_freq_0",        "GLT,CS_FREQ,0"),   # [V1.05] (needs bank_index)
    ("glt_qs_freq_bare",     "GLT,QS_FREQ"),     # [V1.05] Quick Search freqs
    ("glt_rptr_freq_bare",   "GLT,RPTR_FREQ"),   # [V1.05] Repeater Find freqs
    ("glt_urec_folder_bare", "GLT,UREC_FOLDER"), # [V1.05] User Record folders
    ("glt_band_scope_bare",  "GLT,BAND_SCOPE"),  # [V1.05] Band scope freqs
    # Indexed GLT subforms (already in spec V1.02, but we never tried index=0)
    ("glt_sys_0",            "GLT,SYS,0"),       # [V1.05] System (needs fl_index)
    ("glt_dept_0",           "GLT,DEPT,0"),      # [V1.05] Department (needs system_index)
    ("glt_site_0",           "GLT,SITE,0"),      # [V1.05] Site (needs system_index)
    ("glt_cfreq_0",          "GLT,CFREQ,0"),     # [V1.05] Conv Freq (needs dept_index)
    ("glt_tgid_0",           "GLT,TGID,0"),      # [V1.05] TGID (needs dept_index)
    ("glt_sfreq_0",          "GLT,SFREQ,0"),     # [V1.05] Site Freq (needs site_index)
    ("glt_atgid_0",          "GLT,ATGID,0"),     # [V1.05-VALIDATED-READ] returns truncated XML (parser tolerant)
    # NOTE: GLT,UREC_FILE,0 was tested in Phase 3 and CAUSES THE SCANNER
    # TO HANG with no response (>1.5s timeout). Removed from probe.
    # Suspected pre-existing firmware bug. Do not re-enable without
    # confirming the scanner can recover. See SDS100_unofficial_commands.md.
    # ("glt_urec_file_0",      "GLT,UREC_FILE,0"), # [V1.05-NORESP-DONOTSEND]
]


# Commands that look query-ish but are CONFIRMED mutating; never send.
#
# Sourced from the SDS100/SDS200 Remote Command Spec V1.02 plus the
# BCDx36HP-era commands the SDS spec was forked from. Anything that:
#   - takes a key code, jump target, hold/avoid action, or analyze
#     start/pause command
#   - enters or exits programming/menu mode
#   - starts/stops a recording or analyze pass
#   - enables a periodic push stream (PSI, PWF, GWF) - even if the
#     bare form looks like a query, the response is multi-shot and
#     leaves the scanner in a different state until a matching
#     "off" parameter is sent. Since we never send the off form
#     either, we just don't enter the on form at all.
#   - powers the scanner off
# is on this list. The probe head-checks ``cmd.split(",", 1)[0]``
# against this set, so e.g. ``KEY,K,P`` is rejected.
#
# Special note on ``GLT``: the bare ``GLT`` form is illegal per the
# spec (it requires a sub-list keyword like ``GLT,FL``). We allow
# specific safe ``GLT,xxx`` strings via the QUERIES whitelist; the
# raw head ``GLT`` is NOT on the forbidden list because each
# individual GLT command is reviewed in QUERIES instead.
FORBIDDEN_FOR_READ_ONLY = {
    # SDS100/SDS200 spec V1.02 mutating commands:
    "KEY",          # [SPEC #3]  Push KEY
    "QSH",          # [SPEC #4]  Go to quick search hold mode (mode change!)
    "JNT",          # [SPEC #6]  Jump Number Tag (navigation change)
    "NXT",          # [SPEC #7]  Next (navigation change)
    "PRV",          # [SPEC #8]  Previous (navigation change)
    "HLD",          # [SPEC #15] Hold (state change)
    "AVD",          # [SPEC #16] Avoid (mutates avoid list)
    "JPM",          # [SPEC #18] Jump Mode (mode change)
    "AST",          # [SPEC #21] Analyze Start (enables continuous push at 200ms)
    "APR",          # [SPEC #22] Analyze Pause/Resume
    "URC",          # [SPEC #23] User Record Control - starts/stops recording!
    "MNU",          # [SPEC #24] Menu Mode (enters menu, side effect on UI)
    "MSV",          # [SPEC #26] Menu Set Value (writes config)
    "MSB",          # [SPEC #27] Menu Structure Back (navigation)
    "PSI",          # [SPEC #12] Push Scanner Information - enables periodic push
    "PWF",          # [SPEC #29] Push Waterfall FFT - enables FFT stream
    "GWF",          # [SPEC #30] Get Waterfall FFT - requires [ON/OFF] arg, may toggle stream
    "GW2",          # [SPEC V2.00] Get Waterfall FFT without separator - same stream-toggle semantic as GWF
    # SQK and DQK have read-with-required-arg forms; sending the bare
    # head with no args is harmless (returns ERR) but we choose to
    # forbid them for now to avoid noise. Add explicit
    # "SQK,<idx>" entries to QUERIES once GLT,FL gives us indices.
    "SQK",          # [SPEC #10] Get/Set System Quick Keys (needs FL arg)
    "DQK",          # [SPEC #11] Get/Set Department Quick Keys (needs FL+SYS args)

    # BCDx36HP/older-era commands we treat as forbidden out of caution:
    "PRG", "EPG",                 # programming mode entry/exit
    "CLR", "DLA", "MEMSET",       # destructive memory ops
    "TGW", "VLO", "SLO",          # writes to scan list state
    "WPL", "WPS", "WIPE",         # destructive
    "POF",                        # power-off (some FWs accept this)
    # BCDx36HP V1.05 spec additions:
    "BFH",                        # [V1.05] Band Scope Frequency Hold (mutating)
}
# NOTE on head-only checking: the probe extracts cmd.split(",", 1)[0]
# and uppercases it before lookup. So "GLT,FL" -> head "GLT" is NOT
# forbidden because each GLT,xxx subform must be approved individually
# via the QUERIES list. To deny the bare "GLT" with no args (which is
# illegal per spec), we never put "GLT" alone in QUERIES.


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


def _send_and_read(
    port: serial.Serial,
    command: str,
    deadline_s: float = 1.5,
    quiet_after_cr_s: float = 0.10,
) -> tuple[bytes, float]:
    """Send a command and read until quiet. Returns (bytes, elapsed_ms).

    Read terminates on whichever happens first:
      - the buffer ends with CR/LF AND we observe ``quiet_after_cr_s``
        seconds of silence (handles multi-line XML responses from
        GSI / GLT, which arrive as a tight burst of CR-terminated lines),
      - or the total elapsed time exceeds ``deadline_s``.
    """
    payload = (command + "\r").encode("ascii", errors="replace")
    port.reset_input_buffer()
    t0 = time.perf_counter()
    port.write(payload)
    port.flush()

    deadline = t0 + deadline_s
    response = bytearray()
    saw_terminator = False
    while time.perf_counter() < deadline:
        n = port.in_waiting
        if n:
            chunk = port.read(n)
            response.extend(chunk)
            saw_terminator = saw_terminator or response.endswith(b"\r") or response.endswith(b"\n")
            if saw_terminator:
                # Quiet window: keep slurping bytes until the line goes
                # silent for quiet_after_cr_s. Resets on every new byte.
                quiet_until = time.perf_counter() + quiet_after_cr_s
                while time.perf_counter() < quiet_until and time.perf_counter() < deadline:
                    n2 = port.in_waiting
                    if n2:
                        response.extend(port.read(n2))
                        quiet_until = time.perf_counter() + quiet_after_cr_s
                    else:
                        time.sleep(0.005)
                break
        else:
            time.sleep(0.005)

    return bytes(response), (time.perf_counter() - t0) * 1000


def probe_one(port: serial.Serial, label: str, command: str, log) -> None:
    """Send one query, capture response, log everything."""
    head = command.split(",", 1)[0].upper()
    if head in FORBIDDEN_FOR_READ_ONLY:
        log(f"[skip] {label:<24}  cmd={command!r}  (head {head!r} is on FORBIDDEN list)")
        return

    log("")
    log(f">>> {label:<24}  cmd={command!r}")

    try:
        response, elapsed_ms = _send_and_read(port, command)
    except Exception as exc:
        log(f"[error] write/read failed: {exc}")
        return

    if response:
        log(f"<<< {len(response)} bytes in {elapsed_ms:.0f} ms")
        log(f"    raw  : {response!r}")
        log(f"    show : {_safe_decode(response)}")
    else:
        log(f"<<< (no response, {elapsed_ms:.0f} ms timeout)")


def run_poll_mode(port: serial.Serial, command: str, interval_s: float,
                  duration_s: float, log) -> None:
    """Send the same command repeatedly and log every response.

    Logs only deltas after the first response (to keep the log short
    when nothing changes). Useful for catching GLG-during-RX or
    watching STS bits flip when the user toggles a feature.
    """
    head = command.split(",", 1)[0].upper()
    if head in FORBIDDEN_FOR_READ_ONLY:
        log(f"[abort] cmd={command!r} head {head!r} is on FORBIDDEN list")
        return

    log("")
    log("## POLL MODE")
    log(f"   cmd       : {command!r}")
    log(f"   interval  : {interval_s*1000:.0f} ms (~{1/interval_s:.1f} Hz)")
    log(f"   duration  : {duration_s:.1f} s")
    log("")

    deadline = time.perf_counter() + duration_s
    last_response: Optional[bytes] = None
    n_total = 0
    n_changed = 0
    n_empty = 0

    while time.perf_counter() < deadline:
        try:
            response, elapsed_ms = _send_and_read(port, command, deadline_s=0.5,
                                                  quiet_after_cr_s=0.04)
        except Exception as exc:
            log(f"[error] poll iteration failed: {exc}")
            return

        n_total += 1
        wallclock = _dt.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        if not response:
            n_empty += 1
        if response != last_response:
            n_changed += 1
            log(f"[{wallclock}] #{n_total:04d}  {elapsed_ms:5.0f} ms  "
                f"{len(response):4d}B  CHG  {_safe_decode(response)}")
            last_response = response
        # else: identical to previous; suppress unless caller wanted noisy mode

        # Sleep the remainder of the interval, but no less than 5ms.
        remaining = interval_s - (elapsed_ms / 1000.0)
        if remaining > 0:
            time.sleep(remaining)

    log("")
    log(f"## POLL SUMMARY: {n_total} iterations, {n_changed} unique responses, {n_empty} empty")


def run_diff_mode(port: serial.Serial, command: str, log) -> None:
    """Snapshot / pause-for-input / snapshot loop.

    Operator drives the toggle on the scanner between snapshots. We
    diff the responses byte-by-byte and highlight changed positions.
    Useful for mapping STS bits to specific scanner features.
    """
    head = command.split(",", 1)[0].upper()
    if head in FORBIDDEN_FOR_READ_ONLY:
        log(f"[abort] cmd={command!r} head {head!r} is on FORBIDDEN list")
        return

    log("")
    log("## DIFF MODE")
    log(f"   cmd : {command!r}")
    log("   You will be asked to take a snapshot, then change one")
    log("   thing on the scanner, then take another snapshot. Type")
    log("   'quit' at any prompt to exit.")
    log("")

    snapshot_n = 0
    prev: Optional[bytes] = None

    while True:
        snapshot_n += 1
        try:
            label = input(f"[diff] snapshot #{snapshot_n} - press Enter "
                          f"(or describe state, or 'quit'): ").strip()
        except EOFError:
            label = "quit"
        if label.lower() == "quit":
            log("")
            log(f"## DIFF SESSION: ended after {snapshot_n - 1} snapshot(s)")
            return

        try:
            response, elapsed_ms = _send_and_read(port, command)
        except Exception as exc:
            log(f"[error] diff snapshot failed: {exc}")
            continue

        wallclock = _dt.datetime.now().strftime("%H:%M:%S")
        log("")
        log(f"--- snapshot #{snapshot_n} @ {wallclock}  label={label!r}  "
            f"{len(response)}B in {elapsed_ms:.0f} ms ---")
        log(f"    raw  : {response!r}")
        log(f"    show : {_safe_decode(response)}")

        if prev is not None:
            log("    diff vs previous:")
            for line in _byte_diff(prev, response):
                log(f"      {line}")

        prev = response


def _byte_diff(a: bytes, b: bytes, max_lines: int = 32) -> list[str]:
    """Return up to max_lines '@offset: 0xAA -> 0xBB (chars)' rows."""
    out: list[str] = []
    n = min(len(a), len(b))
    for i in range(n):
        if a[i] != b[i]:
            ca = chr(a[i]) if 32 <= a[i] < 127 else "."
            cb = chr(b[i]) if 32 <= b[i] < 127 else "."
            out.append(f"@{i:04d}: 0x{a[i]:02X} {ca!r} -> 0x{b[i]:02X} {cb!r}")
            if len(out) >= max_lines:
                out.append(f"... (more diffs suppressed; first {max_lines} only)")
                return out
    if len(a) != len(b):
        out.append(f"length: {len(a)} -> {len(b)} bytes "
                   f"(tail = {(b[n:n+32] if len(b) > n else a[n:n+32])!r})")
    if not out:
        out.append("(no byte-level differences)")
    return out


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
                        help="Output log path. Default: Metacache/Dev/RE/sessions/<timestamp>.txt.")
    parser.add_argument("--mode", choices=("query", "poll", "diff"), default="query",
                        help="Run mode. 'query' (default) sends the QUERIES list once. "
                             "'poll' repeats one command at a fixed interval. "
                             "'diff' snapshots between user-driven scanner state changes.")
    parser.add_argument("--poll-cmd", default="GLG",
                        help="Command to repeat in --mode poll (default: GLG).")
    parser.add_argument("--poll-interval", type=float, default=0.25,
                        help="Seconds between poll iterations (default: 0.25 = 4 Hz).")
    parser.add_argument("--poll-duration", type=float, default=30.0,
                        help="Total seconds to poll (default: 30).")
    parser.add_argument("--diff-cmd", default="STS",
                        help="Command to snapshot in --mode diff (default: STS).")
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

    repo_root = Path(__file__).resolve().parent.parent.parent.parent  # Metacache/Dev/RE/.. -> repo root
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

    log("# SDS100 passive serial probe")
    log(f"# When     : {_dt.datetime.now().isoformat(timespec='seconds')}")
    log(f"# Host     : {os.environ.get('COMPUTERNAME', '?')}")
    log(f"# Port     : {port_name}  (baud={args.baud}, 8N1)")
    log(f"# Output   : {out_path}")
    log(f"# Probe ID : {_dt.datetime.now().strftime('%Y%m%dT%H%M%S')}")
    log(f"# Mode     : {args.mode}")
    if args.mode == "poll":
        log(f"#   poll-cmd      : {args.poll_cmd!r}")
        log(f"#   poll-interval : {args.poll_interval}s")
        log(f"#   poll-duration : {args.poll_duration}s")
    elif args.mode == "diff":
        log(f"#   diff-cmd : {args.diff_cmd!r}")
    log("#")
    log(f"# Forbidden (never sent): {sorted(FORBIDDEN_FOR_READ_ONLY)}")
    log(f"# Whitelist size        : {len(QUERIES)}")
    log("#")
    log("# Available ports at start:")
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

        if args.mode == "query":
            for label, cmd in QUERIES:
                probe_one(ser, label, cmd, log)
        elif args.mode == "poll":
            run_poll_mode(ser, args.poll_cmd, args.poll_interval,
                          args.poll_duration, log)
        elif args.mode == "diff":
            run_diff_mode(ser, args.diff_cmd, log)
        else:
            log(f"[fatal] unknown mode {args.mode!r}")

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
