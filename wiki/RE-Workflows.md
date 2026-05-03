# RE: Workflows

> Where this fits: recipe playbooks for common RE tasks. Each
> recipe says **why**, **prereqs**, **steps**, and **outputs**.
> For the consolidated narrative start at [Reverse Engineering](Reverse-Engineering).

## Quick reference: which recipe for which goal

| If you want to... | Use recipe |
|---|---|
| Confirm the scanner is reachable on either USB mode | [Verify connectivity](#verify-connectivity) |
| Add a new MAIN-port command to our app safely | [Vet a MAIN command](#vet-a-main-command) |
| Discover undocumented SUB-port commands | [Probe the SUB port](#probe-the-sub-port) |
| Understand what Sentinel does for operation N | [Capture a Sentinel op](#capture-a-sentinel-op) |
| Reverse-engineer one specific SUB function | [Decompile a SUB function](#decompile-a-sub-function) |
| Diff two firmware versions | [Diff two firmware images](#diff-two-firmware-images) |
| Validate a hypothesis about the inter-MCU bus | [Test an inter-MCU bus hypothesis](#test-an-inter-mcu-bus-hypothesis) |
| Set up a fresh dev machine for RE work | [Bootstrap a new machine](#bootstrap-a-new-machine) |

## Verify connectivity

**Why**: confirm the scanner is plugged in, in the mode you expect,
and reachable.

**Prereqs**: scanner powered on with USB connected.

**Steps**:

```pwsh
# Lists Uniden VID 1965 USB devices and their COM ports / topology
py AI\Dev\RE\tools\probes\list_ports.py

# If in Mass-Storage mode, also confirm drive letter:
.\AI\Dev\RE\tools\sentinel\dump_sd_inventory.ps1
```

**Outputs**:

- A short list of detected COM ports with PIDs, OR
- A drive letter + filesystem inventory in `sessions/`.

**Interpretation** (see [RE-USB-Modes](RE-USB-Modes)):

- Two CDC ports (PIDs `0x0019` + `0x001A`), no SDS volume = **Serial mode**.
- One MSC interface + a removable FAT32 volume = **Mass-Storage mode**.
- Neither = scanner is off, or USB cable not connected, or scanner
  is in normal scan mode without USB.

## Vet a MAIN command

**Why**: you found a candidate read-only command in the spec or in
RR/forums and want to add it to our app.

**Prereqs**: scanner in Serial mode; SDS100 connected to host PC;
PowerShell open at repo root.

**Steps**:

1. Verify the command is **not in any FORBIDDEN list** in
   `serial_probe.py`. If it is, stop - that means the command is
   destructive.
2. Cross-reference against the spec PDFs in `AI/Dev/RE/`:
   - SDS V1.02 (`SDS200_RemoteCommand_Specification_V1_02.pdf` if mirrored)
   - SDS V2.00 (`SDS_Series_RemoteCommand_Specification_V2_00.pdf` if mirrored)
   - BCDx36HP V1.05 (`BCDx36HP_RemoteCommand_Specification_V1_05.txt`)
3. If the command is **read-only** per spec, add it to `QUERIES` in
   `serial_probe.py` (with a comment citing the spec).
4. Run a probe pass:
   ```pwsh
   py AI\Dev\RE\tools\probes\serial_probe.py --port COM4
   ```
5. Inspect `AI/Dev/RE/sessions/sds100_serial_<UTC>.txt`.

**Outputs**:

- Verbatim response in the session file.
- Updated `serial_probe.py` whitelist if accepted.
- Add a row to [RE-Serial-Protocol](RE-Serial-Protocol) for the
  documented behaviour, and to
  `AI/Dev/RE/docs/SDS100_unofficial_commands.md`
  for any non-spec finding.

## Probe the SUB port

**Why**: discover undocumented SUB-port commands or test an
existing one.

**Prereqs**: scanner in Serial mode.

**Steps**:

1. **Anchor first**: confirm SUB responds to `MDL`:
   ```pwsh
   py AI\Dev\RE\tools\legacy\check_sub_alive.py --port COM3
   ```
2. **Single-character probe** (covers the entire 13-char debug
   ladder):
   ```pwsh
   # Edit BATCH list in _probe_batch.py to include 'o','q','w','d','r','m','z','h','l','s','t','u','v'
   py AI\Dev\RE\tools\probes\probe_batch.py --port COM3
   ```
3. **Multi-character probe** (alphabet attack):
   ```pwsh
   py AI\Dev\RE\tools\probes\sub_probe.py --port COM3
   ```
4. **Falsify a Ghidra prediction**:
   ```pwsh
   py AI\Dev\RE\tools\probes\verify_dispatch.py --port COM3 --candidates AI\Dev\RE\sessions\dispatch_candidates.txt
   ```

**Safety**: every SUB probe uses **anchor-and-compare** (re-send
`MDL` between probes) to detect buffer leakage and avoid false hits.

**Outputs**:

- Markdown report in `AI/Dev/RE/sessions/probe_batch_*.md` with
  HIT / TIMEOUT / IDENTITY / ERR classification per probe.
- Add new findings to `SDS100_unofficial_commands.md`.

## Capture a Sentinel op

**Why**: see exactly which files Sentinel reads/writes during
"Read From Scanner" / "Write to Scanner" / etc.

**Prereqs**:

- Scanner in **Mass-Storage mode** (long-press the dot/period key
  at power-on, or pick "Mass Storage" from the boot prompt).
- Sentinel installed.
- USBPcap installed (reboot after first install).
- Scanner shows up as a removable drive in Explorer.

**Steps**:

```pwsh
# 1. Capture (auto-detects USBPcap interface, prompts you through ops)
py AI\Dev\RE\tools\sentinel\sentinel_session.py
# When prompted, perform the op in Sentinel, wait for completion,
# then press Enter in the terminal.

# 2. Skip ops you don't want this session
py AI\Dev\RE\tools\sentinel\sentinel_session.py --skip 1 --skip 2 --decode

# 3. Re-decode an existing pcap
py AI\Dev\RE\tools\sentinel\decode_sentinel_pcap.py AI\Dev\RE\sentinel_pcaps\03_hpdb_update.pcap
```

**Outputs**:

- `sentinel_pcaps/<NN_name>.pcap` - raw USB capture.
- `sentinel_pcaps/<NN_name>.scsi.jsonl` - one JSON object per SCSI
  command (LBA, blocks, sha12 of payload).
- `sentinel_pcaps/<NN_name>.disk.bin` - sparse-reconstructed FAT32
  disk image (only the sectors Sentinel touched).
- `sentinel_pcaps/<NN_name>.files.md` - file-touch table walked
  from the FAT32 directory of the reconstructed image.
- `sentinel_pcaps/<NN_name>.summary.md` - top-level histogram +
  byte counts.

**Interpretation**: see [RE-Sentinel](RE-Sentinel) for the per-op
meaning of common LBA ranges and Sentinel's internal phase
structure.

## Decompile a SUB function

**Why**: understand the logic of a specific function in the SUB
firmware (e.g. a parser, a state machine, a peripheral driver).

**Prereqs**: Ghidra installed (run `bootstrap_ghidra.ps1` once);
SUB firmware imported (run `run_ghidra_setup.ps1` once); the
target function's address (e.g. `0x14006ca6`).

**Steps**:

```pwsh
# Re-import + analyse + dump (run once or after firmware version change)
powershell -ExecutionPolicy Bypass -File AI\Dev\RE\tools\automation\run_ghidra_setup.ps1

# Targeted decompile of one or more functions (comma-separated addrs or names)
$env:DECOMPILE_TARGETS = "0x14006ca6,FUN_14008340,0x1400e9e0"
powershell -ExecutionPolicy Bypass -File AI\Dev\RE\tools\automation\run_ghidra_decompile.ps1

# Show the resulting decompile
py AI\Dev\RE\tools\firmware\decompile_pull.py --show 0x14006ca6
```

**Outputs**:

- `AI/Dev/RE/firmware/decompiles/<addr>_<name>.json` per target -
  full C decompile + callers + callees + peripheral access + string
  xrefs.
- `AI/Dev/RE/firmware/decompiles/<addr>_<name>.md` - human-readable
  view of the same.

**Notes**:

- The decompiler default timeout is 60 s. Some functions
  (e.g. `FUN_14010650`) are too big - you'll see "decompiler
  timed out" in the output. Either increase the timeout in the
  Java post-script or trace the function indirectly via callers
  and callees.
- Check `_decompile_pull.py --list` to see what's already been
  decompiled.

## Diff two firmware images

**Why**: identify what changed between two MAIN or two SUB firmware
versions.

**Prereqs**: both firmware files in `AI/Dev/RE/firmware/`.

**Steps**:

```pwsh
# Per-image entropy + magic-byte scan + head/tail hex dump
py AI\Dev\RE\tools\firmware\firmware_structure.py --image AI\Dev\RE\firmware\sub_1.03.05.firm
py AI\Dev\RE\tools\firmware\firmware_structure.py --image AI\Dev\RE\firmware\sub_1.03.15.firm

# String extraction + version diff (two images of same MCU)
py AI\Dev\RE\tools\firmware\firmware_strings.py --old AI\Dev\RE\firmware\sub_1.03.05.firm \
                                   --new AI\Dev\RE\firmware\sub_1.03.15.firm

# Byte-level diff (computes changed runs)
py AI\Dev\RE\tools\firmware\firmware_structure.py --diff old=AI\Dev\RE\firmware\X --new=AI\Dev\RE\firmware\Y
```

**Outputs**:

- `AI/Dev/RE/firmware_analysis/<name>.strings.txt` - per-image
  string list.
- `AI/Dev/RE/firmware_analysis/firmware_structure_report.md` -
  rendered structural report with entropy, signatures, head/tail.
- Stdout shows the version-diff (added / removed strings).

**Interpretation**:

- **MAIN diffs are useless** - encryption changes ~99.6% of bytes
  per version with no meaningful structure to compare.
- **SUB diffs are gold** - real strings appear/disappear, real
  format strings change, real CRC field updates. See
  [RE-Firmware](RE-Firmware) for the 1.03.05 -> 1.03.15 SUB diff
  example.

## Test an inter-MCU bus hypothesis

**Why**: validate (or refute) a guess about what a USART2 byte
means.

**Prereqs**: SUB firmware decompile available; ideally a USART2
logic-analyser tap (PCB rework required), or just observable
side-effects via SUB-port commands.

**Steps**:

1. Predict from decompile (see [RE-Inter-MCU-Bus](RE-Inter-MCU-Bus)).
2. Trigger the side: e.g. send a SUB-port command, wait for the
   `t`/`u` mode to flip, send another SUB-port command, observe.
3. Compare the predicted state-byte against the observed output.

**Example**: We hypothesize that `'R'` (0x52) on USART2 resets the
3 accumulator state machines. We can't directly inject USART2
bytes without hardware tap, but `R` falls through the SUB-port
lowercase parser into `FUN_14008340`, which is the same byte-stream
framer the USART2 RX feeds. Sending `R\r` on COM3 and observing
whether the SUB visibly resyncs is a partial test.

**Outputs**:

- Session note in `AI/Dev/RE/sessions/` documenting the test.
- Update [RE-Inter-MCU-Bus](RE-Inter-MCU-Bus) with the result.

## Bootstrap a new machine

**Why**: clone the repo on a new computer and need to be ready to
do RE.

**Steps** (run as administrator at repo root):

```pwsh
# 1. Python + pip packages
winget install Python.Python.3.13
py -m pip install --user pyserial

# 2. Java (Ghidra prereq)
winget install --id EclipseAdoptium.Temurin.21.JDK -e --source winget
# Open a fresh PowerShell window so PATH picks up Java

# 3. Ghidra + LPC43xx SVD
powershell -ExecutionPolicy Bypass -File AI\Dev\RE\tools\automation\bootstrap_ghidra.ps1
powershell -ExecutionPolicy Bypass -File AI\Dev\RE\tools\automation\fetch_lpc43xx_svd.ps1

# 4. Wireshark + USBPcap (for Sentinel captures)
winget install --id WiresharkFoundation.Wireshark -e --source winget
winget install --id desowin.USBPcap -e --source winget
# Reboot now so the USBPcap kernel driver loads

# 5. After reboot, audit
powershell -ExecutionPolicy Bypass -File AI\Dev\RE\tools\automation\check_prereqs.ps1
```

**Verification**:

- `py -V` shows Python 3.10+
- `java -version` shows 21
- `Test-Path <GHIDRA_INSTALL>\support\analyzeHeadless.bat` is `True`
- `& "C:\Program Files\Wireshark\tshark.exe" --version` works
- `Test-Path "C:\Program Files\USBPcap\USBPcapCMD.exe"` is `True`

If any of these fail, see `AI/Dev/RE/docs/AUTOMATION.md`
for the original troubleshooting notes.

## Future RE goals (not yet recipes)

These are flagged in the wiki but don't have full playbooks yet.
Add a section above when the recipe matures.

- **Mass storage in serial mode** - fork SUB firmware to expose the
  SD card as a USB MSC interface alongside the two CDC ports, so
  users don't need to reboot to switch modes. Static RE on SUB is
  done; live patching of the SUB firmware would be next, then a
  bootloader handoff to test.
- **MAIN MCU live USART2 capture** - logic analyser on the USART2
  pads to capture both directions of the inter-MCU bus, giving us
  Layer 3 semantics for free. Requires PCB rework.
- **Mode-sweep for SUB debug commands** - cycle `t`/`u` through all
  9 (mode_t × mode_u) combinations and re-run `q`/`r`/`m`/etc. to
  enumerate all 35 untriggered format strings.
- **GLG full-schema capture** - wait for an active P25 voice frame
  (or DMR / NXDN / analog) and capture `GLG` populated to lock down
  the 12-field schema across modulations.
- **STS bit-decode** - user toggles HOLD / ATT / KEY LOCK / PRI / CC
  one at a time while we capture STS before/after to map the 14-bit
  status flag field at position 1.
