# RE Automation Pipeline

> Status: shipped (v0.11.x) — one-command Ghidra + Sentinel flows.

> **Canonical narrative is in the wiki**:
> [`wiki/RE-Toolchain.md`](../../../wiki/RE-Toolchain.md). This
> file is the lab notebook with the original implementation
> details + troubleshooting notes.

Three coordinated layers replace the manual runbooks
[`ghidra_import_runbook.md`](ghidra_import_runbook.md) and
[`sentinel_capture.md`](sentinel_capture.md) with one-command flows.

## Layout

```
Metacache/Dev/RE/tools/
├── automation/                       # Layer 1 + 2 (PowerShell + Java)
│   ├── check_prereqs.ps1             # Read-only audit of all prereqs
│   ├── bootstrap_ghidra.ps1          # Installs Ghidra to C:\Tools\
│   ├── fetch_lpc43xx_svd.ps1         # Downloads LPC43xx.svd
│   ├── run_ghidra_setup.ps1          # Drives analyzeHeadless.bat
│   ├── .ghidra_env.ps1               # Auto-generated GHIDRA_HOME helper (gitignored)
│   └── ghidra_scripts/
│       ├── SetupSubProject.java      # Pre-script: memory map + SVD + Thumb
│       └── DumpAnalysis.java         # Post-script: emits analysis_dump.json
├── firmware/analyze_ghidra_dump.py   # Consumer of analysis_dump.json
├── probes/verify_dispatch.py         # Live falsification probe (SUB port)
└── sentinel/sentinel_session.py      # Layer 3: passive USBPcap capture driver
```

Full script index: [`tools/README.md`](../tools/README.md).

## One-time setup

1. **Install Java 21 (system-wide, on PATH):**

   ```powershell
   winget install --id EclipseAdoptium.Temurin.21.JDK -e --source winget
   ```

   Open a fresh PowerShell window after install so the new PATH is picked up.
   Verify with `java -version`.

2. **Install Wireshark + USBPcap (only needed for Sentinel capture):**

   ```powershell
   winget install --id WiresharkFoundation.Wireshark -e --source winget
   winget install --id desowin.USBPcap -e --source winget
   ```

   **Reboot after USBPcap install** so the kernel driver loads.

3. **Bootstrap Ghidra:**

   ```powershell
   powershell -ExecutionPolicy Bypass -File Metacache\Dev\RE\tools\automation\bootstrap_ghidra.ps1
   powershell -ExecutionPolicy Bypass -File Metacache\Dev\RE\tools\automation\fetch_lpc43xx_svd.ps1
   ```

   Bootstrap downloads ~500 MB Ghidra ZIP to `C:\Tools\ghidra_<ver>_PUBLIC\`,
   sets `GHIDRA_HOME`, and smoke-tests `analyzeHeadless.bat`. Idempotent.

4. **Audit:**

   ```powershell
   powershell -ExecutionPolicy Bypass -File Metacache\Dev\RE\tools\automation\check_prereqs.ps1
   ```

## Happy-path workflow

### Static side: extract command vocabulary from firmware

```powershell
# Phase 6.1 (firmware extraction) must already be done -
# Metacache/Dev/RE/firmware/sub_1.03.15_inflated.bin must exist.

# 1. Run Ghidra import + analysis + JSON dump.
powershell -ExecutionPolicy Bypass -File Metacache\Dev\RE\tools\automation\run_ghidra_setup.ps1

# 2. Consume the JSON. Produces docs/sub_command_dispatch.md,
#    docs/SDS100_inter_mcu_protocol.md, sessions/dispatch_candidates.txt,
#    and an auto-generated annotation block in docs/sub_command_response_map.md.
py Metacache\Dev\RE\tools\firmware\analyze_ghidra_dump.py
```

To re-run with a freshly-edited Java post-script use `-Force`:

```powershell
powershell -ExecutionPolicy Bypass -File Metacache\Dev\RE\tools\automation\run_ghidra_setup.ps1 -Force
```

To re-run only the dump (skip ~1 minute analyze-everything cycle):

```powershell
powershell -ExecutionPolicy Bypass -File Metacache\Dev\RE\tools\automation\run_ghidra_setup.ps1 -DumpOnly
```

### Dynamic side: capture Sentinel USB traffic

```powershell
# Plug the SDS100 in and power it on.
py Metacache\Dev\RE\tools\sentinel\sentinel_session.py
# Auto-detects the USBPcap interface, then prompts you through the six
# Sentinel operations in sequence. Each operation produces one .pcapng.

# Re-decode without re-capturing:
py Metacache\Dev\RE\tools\sentinel\sentinel_session.py --decode-only

# Skip operations you don't want this session:
py Metacache\Dev\RE\tools\sentinel\sentinel_session.py --skip 4 --skip 6
```

### Falsification: confirm Ghidra's predictions on the live scanner

```powershell
# After analyze_ghidra_dump.py has produced dispatch_candidates.txt:
py Metacache\Dev\RE\tools\probes\verify_dispatch.py --port COM3
```

This sends each predicted mnemonic to the SUB processor with the same
`MDL` anchor-and-compare technique as `sub_probe.py`, classifies each
response as HIT / ERR / IDENTITY / TIMEOUT, and writes
`sessions/dispatch_verification_<UTC>.md`.

## Known limitations

- **The SUB firmware doesn't use string-table dispatch.** Empirically
  confirmed in Session 7 - the firmware contains `SDS100-SUB` but does
  *not* contain literal `MDL` / `VER` / etc. as ASCII strings. Commands
  are parsed character-by-character (`if (in[0]=='M' && in[1]=='D' && in[2]=='L')`).
  The `dispatch_candidates` heuristic correctly returns 0 for this
  firmware - that's a true negative, not a bug. To enumerate this style
  of dispatch, decompile the function that processes the COM-port input
  buffer and read off each `cmp` chain manually.
- USBPcap requires a reboot after install before the kernel driver
  starts capturing. `sentinel_session.py` will report "no SDS100
  traffic seen" if it ran before the reboot.
- The dispatch-candidate verifier (`verify_dispatch.py`) produces an
  empty report if `dispatch_candidates.txt` is empty (because of the
  finding above). It still works as soon as the candidates file has
  content - useful when you start probing other firmware variants.

## When to use which path

- **Need to add a Sub-firmware mnemonic to the catalog?** -> static side.
- **Need to find Sentinel-private commands?** -> dynamic side.
- **Need to verify a hypothesis about a SUB command?** -> falsification.

The static and dynamic sides are independent. Either can be skipped
in any session.
