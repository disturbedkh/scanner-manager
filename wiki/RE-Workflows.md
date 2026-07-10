# RE: Workflows

> Status: shipped (v0.11.x) — RE recipe playbooks.

> Where this fits: why / prereqs / steps / outputs for common RE
> tasks. Start at [Reverse Engineering](Reverse-Engineering).
> Full command catalogs: [RE-Toolchain](RE-Toolchain) →
> `tools/README.md`.

## What this answers

Which recipe to run for a given goal, with correct paths under
`Metacache/Dev/RE/tools/`, `docs/`, and `sessions/`.

## Known vs OPEN

| Recipe | State |
|---|---|
| Verify connectivity | DONE |
| Vet MAIN command / probe SUB / capture Sentinel | DONE |
| Decompile SUB fn / diff firmware / bootstrap machine | DONE |
| Inter-MCU hypothesis (software-only) | Partial — hardware tap OPEN |
| Mass-storage-in-serial / mode-sweep / STS bit-decode | OPEN (goals, not recipes yet) |

## Deep dive

### Quick reference

| If you want to... | Recipe |
|---|---|
| Confirm USB mode / reachability | [Verify connectivity](#verify-connectivity) |
| Add a MAIN command safely | [Vet a MAIN command](#vet-a-main-command) |
| Discover / falsify SUB commands | [Probe the SUB port](#probe-the-sub-port) |
| Decode Sentinel op N | [Capture a Sentinel op](#capture-a-sentinel-op) |
| Decompile one SUB function | [Decompile a SUB function](#decompile-a-sub-function) |
| Diff two firmware images | [Diff two firmware images](#diff-two-firmware-images) |
| Test USART2 hypothesis | [Test an inter-MCU bus hypothesis](#test-an-inter-mcu-bus-hypothesis) |
| Set up a new RE machine | [Bootstrap a new machine](#bootstrap-a-new-machine) |

### Verify connectivity

**Why:** confirm mode and reachability.

```pwsh
py Metacache\Dev\RE\tools\probes\list_ports.py
# Mass-Storage only:
.\Metacache\Dev\RE\tools\sentinel\dump_sd_inventory.ps1
```

**Outputs:** COM/PID list or inventory under `sessions/` (or cwd per
script). Interpretation: [RE-USB-Modes](RE-USB-Modes) — two CDCs =
Serial; MSC + FAT32 volume = Mass Storage.

### Vet a MAIN command

1. Not in FORBIDDEN list in `tools/probes/serial_probe.py`.
2. Cross-check `Metacache/Dev/RE/specs/` (V1.02 / V2.00 / BCDx36HP V1.05).
3. If read-only per spec, add to `QUERIES` with spec citation.
4. `py Metacache\Dev\RE\tools\probes\serial_probe.py` (auto-detects
   MAIN PID; optional `--port`).
5. Inspect `Metacache/Dev/RE/sessions/` capture; update
   `docs/SDS100_unofficial_commands.md` + [RE-Serial-Protocol](RE-Serial-Protocol)
   for non-spec finds.

### Probe the SUB port

Prefer canonical probes (not `tools/legacy/`):

```pwsh
py Metacache\Dev\RE\tools\probes\list_ports.py
# Edit BATCH in probe_batch.py, then:
py Metacache\Dev\RE\tools\probes\probe_batch.py
py Metacache\Dev\RE\tools\probes\sub_probe.py
py Metacache\Dev\RE\tools\probes\verify_dispatch.py --candidates Metacache\Dev\RE\sessions\dispatch_candidates.txt
```

All use **anchor-and-compare** (`MDL` between probes) against buffer
leak. Promote findings to `docs/SDS100_unofficial_commands.md`.

### Capture a Sentinel op

**Prereqs:** Mass Storage mode; Sentinel; USBPcap (reboot after
install); removable drive visible.

```pwsh
py Metacache\Dev\RE\tools\sentinel\sentinel_session.py
py Metacache\Dev\RE\tools\sentinel\sentinel_session.py --skip 1 --skip 2 --decode
py Metacache\Dev\RE\tools\sentinel\decode_sentinel_pcap.py Metacache\Dev\RE\sentinel_pcaps\03_hpdb_update.pcap
```

**Outputs** under `sentinel_pcaps/`: `.pcap`, `.scsi.jsonl`,
`.disk.bin`, `.files.md`, `.summary.md`. Meaning:
[RE-Sentinel](RE-Sentinel).

### Decompile a SUB function

```pwsh
powershell -ExecutionPolicy Bypass -File Metacache\Dev\RE\tools\automation\run_ghidra_setup.ps1
$env:DECOMPILE_TARGETS = "0x14006ca6,FUN_14008340,0x1400e9e0"
powershell -ExecutionPolicy Bypass -File Metacache\Dev\RE\tools\automation\run_ghidra_decompile.ps1
py Metacache\Dev\RE\tools\firmware\decompile_pull.py --show 0x14006ca6
py Metacache\Dev\RE\tools\firmware\decompile_pull.py --list
```

**Outputs:** `Metacache/Dev/RE/firmware/decompiles/<addr>_<name>.{json,md}`.
Large functions may hit the 60 s decompiler timeout — raise in Java
post-script or approach via callers/callees. Runbook:
`docs/ghidra_import_runbook.md`.

### Diff two firmware images

```pwsh
py Metacache\Dev\RE\tools\firmware\firmware_structure.py
py Metacache\Dev\RE\tools\firmware\firmware_strings.py
```

Defaults auto-discover blobs under `firmware/`. MAIN diffs are
noise (encryption); SUB diffs are meaningful. Reports under
`firmware_analysis/`. See [RE-Firmware](RE-Firmware).

### Test an inter-MCU bus hypothesis

1. Predict from [RE-Inter-MCU-Bus](RE-Inter-MCU-Bus) /
   `docs/SDS100_inter_mcu_protocol.md`.
2. Trigger via SUB CDC side effects (`probe_batch.py`) or hardware
   USART2 tap (PCB rework).
3. Log result under `sessions/`; update wiki + lab doc.

Example: `'R'` (0x52) as framer resync — partial test via `R\r` on
SUB CDC (falls into `FUN_14008340`).

### Bootstrap a new machine

```pwsh
winget install Python.Python.3.13
py -m pip install --user pyserial
winget install --id EclipseAdoptium.Temurin.21.JDK -e --source winget
powershell -ExecutionPolicy Bypass -File Metacache\Dev\RE\tools\automation\bootstrap_ghidra.ps1
powershell -ExecutionPolicy Bypass -File Metacache\Dev\RE\tools\automation\fetch_lpc43xx_svd.ps1
winget install --id WiresharkFoundation.Wireshark -e --source winget
winget install --id desowin.USBPcap -e --source winget
# reboot for USBPcap, then:
powershell -ExecutionPolicy Bypass -File Metacache\Dev\RE\tools\automation\check_prereqs.ps1
```

Troubleshoot via `docs/AUTOMATION.md`.

### Future RE goals (no full recipes yet)

- Mass storage alongside Serial (SUB firmware fork).
- MAIN USART2 logic-analyser capture (Layer 3).
- `t`/`u` mode-sweep for 35 untriggered format strings.
- GLG schema across modulations; STS bit-decode via toggle-and-diff.

## Lab pointers

| Path | Role |
|---|---|
| `Metacache/Dev/RE/tools/README.md` | Canonical workflows A/B/C |
| `Metacache/Dev/RE/docs/AUTOMATION.md` | Prereq / Ghidra troubleshooting |
| `Metacache/Dev/RE/docs/ghidra_import_runbook.md` | Import + analyse |
| `Metacache/Dev/RE/docs/SDS100_unofficial_commands.md` | Command SSOT |
| `Metacache/Dev/RE/sessions/` | Recipe outputs |
| `Metacache/Dev/RE/specs/` | Vendor command specs |
