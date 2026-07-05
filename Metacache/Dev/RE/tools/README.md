# RE / Development tools

> Status: shipped (v0.11.x) — canonical script home under `tools/`.
> GitHub export tiers: [`Metacache/EXPORT_POLICY.md`](../../EXPORT_POLICY.md).

This is the canonical home for the Python and PowerShell scripts used
to reverse-engineer the Uniden SDS100 (and the wider BCDx36HP scanner
family). The scripts here are written to be **portable across
contributor machines** - no hard-coded COM ports, drive letters, or
firmware filenames. Anything that varies per developer is either
auto-detected by USB VID/PID or is required to be passed as a CLI
argument.

> Companion docs:
> - `Metacache/Dev/RE/docs/` - canonical lab notebooks (BT885.md, SDS100.md,
>   Sentinel write-ups, etc.). Read these to understand **what** was
>   discovered.
> - `wiki/Reverse-Engineering.md` and the `RE-*.md` wiki pages -
>   audience-friendly synthesis for new contributors.
> - `Metacache/Dev/RE/specs/` - vendor PDFs / TXTs of the official Uniden
>   Remote Command specification.

## Layout

```
Metacache/Dev/RE/tools/
├── _common.py            # shared helpers (VID/PID, path constants,
│                          #  port auto-detection, firmware-blob
│                          #  resolver, pcap rotation)
├── probes/               # live-scanner probes (require pyserial)
├── firmware/             # static firmware analysis (no scanner needed)
├── sentinel/             # USB Mass Storage / Sentinel capture & decode
├── automation/           # PowerShell + Ghidra Java automation
└── legacy/               # historical / superseded scripts (do not
                          #  build on these; see legacy/README.md)
```

## probes/ - live-scanner CDC probes

| Script | Purpose |
| --- | --- |
| `list_ports.py` | One-shot dump of every USB serial port with VID/PID, highlighting Uniden CDCs. |
| `serial_probe.py` | Read-only whitelist probe of the MAIN port (Uniden Remote Command Protocol). Modes: `query` (default), `poll`, `diff`. |
| `sub_probe.py` | Read-only first-byte / two-byte / format-string-derived probe of the SUB port. Auto-detects the SUB CDC by VID/PID. |
| `probe_batch.py` | Editable batch runner. Edit the `BATCH = [...]` list at the top to test specific hypotheses, then run. Resolves `port="SUB"` / `"MAIN"` to a real device automatically. |
| `verify_dispatch.py` | Anchor-and-compare verifier for Ghidra-predicted SUB-port mnemonics. Reads `dispatch_candidates.txt`, classifies each as HIT / ERR / IDENTITY / TIMEOUT. |

All probe scripts default to auto-detecting the relevant Uniden CDC
port; pass `--port COM5` (or `/dev/ttyACM0` etc.) to override.

## firmware/ - static firmware analysis

| Script | Purpose |
| --- | --- |
| `inflate_sub.py` | Extract the ARM Cortex-M payload from a Uniden `*.firm` SUB container. Auto-discovers the most recent `*.firm` in `firmware/`; pass `--input` and `--version` to override. |
| `firmware_strings.py` | Walk every MAIN/SUB blob in `firmware/`, dump strings, diff consecutive versions, and emit a command-surface report. |
| `firmware_structure.py` | Per-image entropy profile, magic-byte signature scan, and byte-level diff between consecutive versions. |
| `check_sub_strings.py` | Quick sanity scan for known SUB identity strings in a given firmware blob. |
| `sub_static_analysis.py` | Mnemonic-cluster / peripheral-register / format-string-xref report. Output: `docs/sub_static_analysis.md`. |
| `correlate_responses.py` | Cross-correlate live probe responses with SUB strings + payload. Output: `docs/sub_command_response_map.md`. |
| `find_parser.py` | Hunt for the SUB-port command parser by byte-pattern + 0-caller-function heuristic. |
| `find_mdl_handler.py` | Locate the SUB function that emits `SDS100-SUB` via literal-pool reference scan. |
| `extract_dispatch.py` | Decode the SUB-port command-dispatch table at the configurable literal-pool word. |
| `inspect_func.py` | Hex+disasm dump of a function in the SUB firmware (for spot-checking Ghidra output). |
| `analyze_ghidra_dump.py` | Post-process `analysis_dump.json` from Ghidra into a `dispatch_candidates.txt` for `verify_dispatch.py`. |
| `decompile_pull.py` | Pull decompiled C from Ghidra's headless analyzer for one or more functions. |

All firmware tools accept `--firmware <path>` (default: most-recent
`*_inflated.bin` in `Metacache/Dev/RE/firmware/`) so you can re-run the
whole pipeline against a new SUB firmware version without editing
source code.

## sentinel/ - USB Mass Storage / Sentinel capture

| Script | Purpose |
| --- | --- |
| `sentinel_session.py` | Interactive driver for the 6-operation Sentinel capture flow (Read, Write, HPDB Update, Firmware Update, Backup, Restore). Auto-rotates output filenames to mitigate USBPcap's "invalid write handle" issue. |
| `decode_sentinel_pcap.py` | Decode a USBPcap capture into SCSI READ_10/WRITE_10 ops, reconstruct a sparse FAT32 disk image, list files Sentinel touched. |
| `decode_pcap.py` | Earlier, simpler USB pcap decoder (CDC-leaning). Kept for the SUB-port pcap workflow. |
| `show_scsi.py` | Quick inspector for `*.scsi.jsonl` (output of `decode_sentinel_pcap.py`). |
| `dump_sd_inventory.ps1` | Auto-detects the SDS100 SD card on Windows and dumps a full directory inventory (markdown + TSV). |
| `compare_cards.py` | Side-by-side compare of two scanner SD-card layouts (used for BT885 vs SDS100 family diff). |

## automation/ - one-shot setup + Ghidra glue

| Script | Purpose |
| --- | --- |
| `bootstrap_ghidra.ps1` | Idempotent install + setup of Ghidra (no admin, per-user). |
| `check_prereqs.ps1` | Verify Java, Ghidra, USBPcap, Wireshark, Python on the current machine. |
| `fetch_lpc43xx_svd.ps1` | Download the LPC43xx CMSIS-SVD definition for register annotation. |
| `find_sds100_hub.ps1` | Map the SDS100 to the right USBPcap interface number. |
| `run_ghidra_setup.ps1` | Headless Ghidra: import + auto-analyze a SUB firmware blob. |
| `run_ghidra_decompile.ps1` | Headless Ghidra: dump decompiled C for predicted parser/dispatch functions. |
| `ghidra_scripts/SetupSubProject.java` | Ghidra Java post-script: configure SUB-firmware project (memory map, processor, etc.). |
| `ghidra_scripts/DumpAnalysis.java` | Ghidra Java post-script: dump analysis output as JSON. |
| `ghidra_scripts/DecompileFunctions.java` | Ghidra Java post-script: bulk-decompile a list of functions to JSON. |

## legacy/ - kept for historical reference

See `legacy/README.md` - one-shot or hard-coded scripts that have been
superseded by canonical replacements above. **Do not build on these.**

## Common workflows

### A. Live-probe the connected scanner (read-only)

```powershell
# 1. Confirm both CDC ports are visible
py Metacache/Dev/RE/tools/probes/list_ports.py

# 2. Sweep MAIN with the documented Uniden Remote Command surface
py Metacache/Dev/RE/tools/probes/serial_probe.py

# 3. Sweep SUB with first-byte / two-byte / format-string probes
py Metacache/Dev/RE/tools/probes/sub_probe.py
```

### B. Reverse a new SUB firmware version

```powershell
# 1. Drop the new SDS-100-SUB_VX_YZ_AB.firm into Metacache/Dev/RE/firmware/

# 2. Inflate -> ARM payload + chunk-map markdown
py Metacache/Dev/RE/tools/firmware/inflate_sub.py

# 3. Extract strings (auto-diffs against the previous SUB version)
py Metacache/Dev/RE/tools/firmware/firmware_strings.py

# 4. Static analysis report
py Metacache/Dev/RE/tools/firmware/sub_static_analysis.py

# 5. (optional) Run Ghidra headless on the new payload
.\Metacache\Dev\RE\tools\automation\run_ghidra_setup.ps1
.\Metacache\Dev\RE\tools\automation\run_ghidra_decompile.ps1
py Metacache/Dev/RE/tools/firmware/analyze_ghidra_dump.py
```

### C. Capture a Sentinel session (passive USB)

```powershell
# Switch the scanner into Mass-Storage mode (period key at boot, then
# the Mass Storage option). Plug in. Sentinel must be installed.
py Metacache/Dev/RE/tools/sentinel/sentinel_session.py --decode

# Decode an existing pcap on its own:
py Metacache/Dev/RE/tools/sentinel/decode_sentinel_pcap.py path/to/01_read.pcap
```

## Contribution guidelines

1. **Don't hard-code per-machine values.** No `COM3`, no `E:\\`, no
   `c:\\Users\\<name>\\...`. Use `_common.find_uniden_port()` for
   serial ports, `_common.resolve_firmware()` for firmware paths,
   and `_common.PCAPS_DIR` etc. for output locations.
2. **CLI-args over editing source.** New parameters go behind
   `argparse`, not as module-level constants. Defaults should be
   either auto-discovered (preferred) or sentinel values that fail
   loudly when missing.
3. **Read-only by default.** Anything that can mutate the scanner,
   the SD card, or the firmware blobs MUST require an explicit
   `--allow-destructive` (or equivalent) opt-in flag.
4. **Sanitise output.** Reports written to `docs/` or `sessions/` are
   committed when canonical; treat them as public. Strip GPS, agency
   names, hostnames, scanner serial numbers, etc. before emitting.
5. **Don't grow `legacy/`.** New scratch scripts go in a topic branch
   or your personal `notes/` folder. `legacy/` is purely historical.
6. **Add a row to this README.** New canonical script -> document it
   here. New legacy / superseded script -> document it in
   `legacy/README.md`.
