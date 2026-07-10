# SDS100 unofficial / undocumented commands

> **Canonical narrative is in the wiki**:
> [`wiki/RE-Serial-Protocol.md`](../../../../wiki/RE-Serial-Protocol.md).
> This file is the lab notebook - exhaustive raw catalog with the
> probe captures behind it. The wiki abridges; this file does not.

Canonical catalog of every command discovered across Phase 1-3 of the
Tier ABC RE plan, plus pending discoveries from Phase 4 (Sentinel
USB capture) and Phase 6 (Sub firmware disassembly).

This document is the **single source of truth** for what the SDS100
accepts beyond the published Uniden specs (V1.02, V2.00, BCDx36HP
V1.05). Anything *in* the official specs is omitted from this catalog
unless the spec is wrong about it.

## Methodology

- **Source columns** explained:
  - `V1.02` — Uniden SDS100/SDS200 Remote Command Spec V1.02 (2023-12-22)
  - `V2.00` — Uniden SDS Series Remote Command Spec V2.00 (2025-07-07)
  - `BCDx36HP V1.05` — BCDx36HP Remote Command Spec V1.05 (2017-11-13;
    parent of the SDS spec)
  - `Phase 1` — SUB-port systematic probe (`sub_probe.py`)
  - `Phase 2` — MAIN-port argument-extension probe (`serial_probe.py`)
  - `Phase 3` — BCDx36HP V1.05 legacy probe (extension of `serial_probe.py`)
  - `Phase 4` — Sentinel USB packet capture (PENDING)
  - `Phase 6` — Sub firmware static RE format-string analysis
- **Safety class**:
  - `READ` — confirmed read-only on a probe-tested firmware
  - `WRITE` — known to mutate state (firmware spec explicit, or
    behavior change observed)
  - `UNKNOWN` — observed to respond but semantics unclear
  - `NORESP` — accepts the command but produces no response (likely
    a write or a side-effect-only call)
- **Port**:
  - `MAIN` — VID 1965 PID 001A (COM4)
  - `SUB` — VID 1965 PID 0019 (COM3)

## SUB-port commands (PID 0x0019)

The Uniden specs **never document the SUB port at all**. Everything
below is undocumented by definition.

**Round 1-4 firmware-static-RE finding (2026-05-03):** the SUB-port
parser in `FUN_14006ca6` of `sub_1.03.15_inflated.bin` uses
**per-character `cmp #imm8`** dispatch (no string table). The 13
single-character debug commands listed below were enumerated directly
from the parser's compare ladder and then live-falsified on COM3.

| Mnemonic | Source | Safety | Response shape | Notes |
|---|---|---|---|---|
| `MDL` | Phase 1, V1.02 inheritance | READ | `SDS100-SUB\\r` × 4 | Identity. 4× echo is the canonical "command understood" pattern on SUB. Parsed by SUB locally as `cmp #'M'; cmp #'D'; cmp #'L'`. |
| `VER` | Phase 1, V1.02 inheritance | READ | `Version 1.03.15 \\r` × 4 | Sub firmware version (separate from MAIN firmware). |
| `U` | Phase 1 | UNKNOWN | `U5C42\\r<\\x00><binary 2 bytes>` | Returns a 9-byte response with a stable 5-byte ASCII prefix and 2 changing binary bytes. Looks like a register read (`U5C42` could be address `0x5C42` in some peripheral), with the changing bytes being live counter/RSSI/temperature. |
| `U,N` (any arg) | Phase 1b retry | UNKNOWN | Same 9-byte shape as `U` (`U5C42\\r\\x00<2 bytes>`) | Argument is silently ignored. Tested `U,0`, `U,1`. Same response shape; trailing 2 bytes still volatile across calls but appear to be unaffected by N. |
| `o` | **Round 4 firmware RE** | READ | 2.2 KB ASCII, 512 records of `<adc>\\r<adc>\\r<bit>\\r` | **DSP front-end ADC dump.** Values up to 4095 (= 2¹²−1) confirm 12-bit ADC. Triple looks like `(channel_a, channel_b, status_bit)` per sample. Exactly matches `FUN_1400692c` invocation in the parser. |
| `q` | **Round 4 firmware RE** | READ | 1.3-1.5 KB ASCII, 256 lines of signed int16 | **DSP buffer A.** Values in -5071..+1491 range - looks like one channel of an I/Q sample buffer or filter output. Driven from `*DAT_14006f70`. |
| `w` | **Round 4 firmware RE** | READ | 1.3-1.4 KB ASCII, 256 lines of signed int16 | **DSP buffer B.** Paired with `q` (likely the other half of a complex-sample stream from `*DAT_14006f78`). |
| `d` | **Round 4 firmware RE** | READ | 5.5 KB ASCII, 512 records of `<int16>,<int16>` | **Complex (I, Q) baseband samples.** Each line is a full complex sample. Equivalent to running `q` and `w` interleaved. Calls `FUN_140069d0`. |
| `r` | **Round 4 firmware RE** | READ | 1.6 KB ASCII, 256 lines of signed int16 (full ±32767 range) | **Audio or post-filter sample stream.** Saturation seen at `-32053`, `+25696` etc. Reads from a 1024-byte source buffer at `*DAT_14006f7c`. |
| `m` | **Round 4 firmware RE** | READ | 2.9 KB ASCII, 1024 lines of signed int16 with `32767` markers | **FFT magnitude / spectrum**. Multiple `32767` saturation markers in the stream suggest peak-flagging. Reads 0x100 bytes from `*DAT_14006f80` and pads with 0x300 zeros. |
| `z` | **Round 4 firmware RE** | READ | 1.9 KB ASCII, 256 lines of signed int16 | **Accumulator / state dump.** Mixed magnitude (-12185..+19366). Calls `FUN_14006a64` to format. |
| `h` | Phase 1b retry, Round 4 RE | **READ-STREAMING** | Continuous stream of `H, %ld, %ld\\r` lines + interleaved `h, %ld, %ld\\r` lines | **Confirmed by both empirical streaming AND firmware decompile.** Composite dump of 4 buffers at `DAT_14006bdc..0xbec`: 128 paired records + 16 paired records. The leading `h` is the trigger; trailing characters are ignored. Stream is finite (self-terminates). |
| `l` | **Round 4 firmware RE** | READ | **79 KB** ASCII, 2051 lines of `(float, float, int)` | **Largest dump: log buffer.** Conditional on `*DAT_14006f90 > 0`. Many records show clearly-uninitialized float bits (e.g. `-7.9e21`) - confirms this is a circular log read past valid records. Likely a frequency-hit log or DSP event log. |
| `s` | **Round 4 firmware RE** | READ | 42 B, two copies of `0, 198, 4, 8, 0, 0` | **Compact stats counters.** 6-tuple: 0, 198, 4, 8, 0, 0. The `198` is suggestive of a packet/frame count; the `4, 8` could be flag fields. Calls `FUN_14006c00`. |
| `t` | **Round 4 firmware RE** | NORESP (silent) | (timeout, 2 s) | **Silent toggle.** Decompile shows `*DAT_14006f68 ^= 1`. Round 4 toggle test (q before / after t) found small size variation but no clear content shift - likely affects a hardware mode (DSP filter? gain?) that needs an RF stimulus to observe. |
| `u` | **Round 4 firmware RE** | NORESP (silent) | (timeout, 2 s) | **Silent toggle.** Decompile shows `*DAT_14006f68 = (*DAT_14006f68 == 2 ? 0 : 2)`. Same flag as `t`. The flag takes 3 values: 0/1/2. Same observability constraint as `t`. |
| `v` | **Round 4 firmware RE** | READ | 5.2 KB ASCII, 256 records of `<int32>, <int32>` | **Wide-precision dual-stream.** 32-bit values per channel (vs `d`'s 16-bit). Range up to ±275 million, suggesting accumulated phase / frequency-deviation samples or 32-bit ADC. Reads from `*DAT_14006f84` + `*DAT_14006f88`. |
| `STS` | Phase 1 | NORESP | (timeout, 1.5s) | Recognized in spec V1.02, no response on SUB. |
| `GSI` | Phase 1 | NORESP | (timeout) | Same. |
| `GCS` | Phase 1, V2.00 | NORESP | (timeout) | Get Charge Status; spec says targets SUB but doesn't respond. |
| `KAL` | Phase 1, V2.00 | NORESP | (timeout) | Keep Alive heartbeat - no response expected per spec, confirmed. |
| `VOL` | Phase 1 | NORESP | (timeout, but BUFFER LEAK) | Documented BCDx36HP. Returns the *previous* successful response (the buffer-leak fingerprint), not its own data. |
| `SQL`, `PWR`, `GLG` | Phase 1 | NORESP | (timeout) | All BCDx36HP-inherited; SUB ignores them. |

### Round 4 firmware-static-RE notes (2026-05-03)

The 13 lowercase debug commands above (`o q w d r m z h l s t u v`) are
**all parsed directly by the SUB MCU**, not forwarded. Empirical
falsification with [`tools/probes/probe_batch.py`](../tools/probes/probe_batch.py) returned HIT for all 11 emitting
commands and TIMEOUT for both silent toggles - matching the decompile
exactly. Full session report:
[`sessions/probe_batch_round4_pass1_*.md`](../sessions/).

The dispatch lives in `FUN_14006ca6` (0x14006b20-0x14006f45). Format
strings for the responses live in the data section starting at
`0x14013100` and contain `H, %ld, %ld`, `Manual LNAGain1,...`,
`FFT_PEAK,...`, `Widest LPF,...` etc - many of these we listed below
as "untriggered format strings" but they're actually triggered by
**different** state values of the `t`/`u` mode flag (so `q` in mode 0
emits one format, in mode 1 a different one, in mode 2 a third). To
trigger them we need to enumerate (mode, command) combinations, not
new mnemonics.

### Prefix-match false positives (not real commands)

The SUB firmware seems to do partial-prefix matching on the first
1-2 characters of the input, returning identity strings. We see:

- Anything starting with `M` → `SDS100-SUB\\r` repeated N times
- Anything starting with `V` → `Version 1.03.15 \\r` repeated N times
- N = number of bytes after the prefix character

So `MA, MB, ..., MZ, MIXG` all return SDS100-SUB-style responses;
`VGA, VGM, VGN, VGAM` all return Version-style responses. These are
NOT distinct commands - they are the firmware's prefix-fallback path.

### Untriggered SUB format strings (35 hypothesis targets)

The Sub firmware contains 35 `printf`-style format strings whose
trigger commands we haven't found yet. Each represents code that
would output the format if executed - so each is a candidate command
we should keep probing for. From `sub_command_response_map.md`:

| Format string | Likely command name |
|---|---|
| `S%02X%04X%04X%04X%04X%01X%04X` | (unknown) - high-bandwidth status line |
| `Manual LNAGain1,%d, LNAGain2,%d, MixerGain,%d, ADC_P-P,%d` | manual gain readout |
| `RF_GainMode,MANUAL` / `RF_GainMode,AUTO` | gain mode |
| `dBm,%d,LNAGain1,...,Max,%d, ADC_P-P,%d` | full RF status |
| `IfRssi,%d` / `RssiDbm,%d` | IF / RSSI dBm |
| `LNAGain1,%d` / `LNAGain2,%d` / `MixerGain,%d` | per-stage gains |
| `LNAGain1,Auto` / similar | gain auto indicators |
| `Noise Squelch,%6d` | noise squelch level |
| `FFT_PEAK,%ddB` / `FFT_FREQ,%d` | FFT peak finder |
| `FIR2_Range,%d, %ddB` | FIR2 range |
| `NCO_Range,min=%6d, max=%6d, dif=%6d` | NCO range stats |
| `CIC OUT min,%6d, max=%6d, err=%6d` | CIC filter stats |
| `FIR1 OUT / FIR2 OUT min,...,err=%6d` | FIR filter stats |
| `Widest LPF, %d` / `Narrowest LPF, %d` / `LPF, %d` / `Default LPF, %d` | LPF stages |
| `IF=%d, STD= %s` | IF filter / standard mode |
| `Window,%d` | windowing function index |
| `VGA Mode Manual,%d` | VGA gain mode |
| `REG[%2d],%02X, REG[%2d],%02X, REG[%2d],%02X, REG[%2d],%02X` | 4-register peek dump |
| `R840_FM` / `R840_DVB_T2_1_7M` | Rafael R840 mode strings |
| `H, %ld, %ld` / `h, %ld, %ld` | **TRIGGERED in Phase 1b retry by lowercase `h`** - see SUB-port commands table |
| `%f, %f, %d` / `%ld, %ld, %ld, %ld, %ld, %ld` | (unknown) |

Future probe sessions should target 3-4 letter combinations
suggested by these format strings (e.g. `RFGM` for RF Gain Mode,
`NSL` for Noise Squelch Level, `IFRS` for IfRssi, `FFTP` for FFT
peak, etc.).

**Phase 1b retry results (2026-04-29)**: ran 154 candidates derived
directly from the 35 format strings via `sub_probe.py
--only-targeted2`. New findings:
- Lowercase `h` triggers the `H, %ld, %ld` / `h, %ld, %ld` debug
  stream (above).
- `U,N` accepts numeric args but ignores them (same 9-byte response
  as bare `U`).
- All other gain-readout / FFT / CIC / FIR / IF / RSSI / Window /
  REG candidates timed out. Their format strings remain untriggered;
  the trigger is likely either case-sensitive (lowercase, like `h`)
  or requires a multi-character prefix we haven't guessed yet.

The case-sensitivity finding is critical: probe stage 1 and 2
upcase all candidates, so any lowercase-keyed handler was
systematically missed in the first pass. Future probes should
include lowercase A-Z and lowercase aa-zz passes.

## MAIN-port commands (PID 0x001A)

### Phase 2: Argument-extension findings

The MAIN port accepts undocumented argument variants on documented
commands. Most are no-ops (return identical content to the bare
form), but a few have measurable differences.

| Command | Source | Safety | Behavior | Notes |
|---|---|---|---|---|
| `GSI,XML` | Phase 2 | READ | Same as bare `GSI` | Argument accepted silently. |
| `GSI,RAW` | Phase 2 | READ | Same as bare `GSI` | Argument accepted silently. |
| `GSI,PROP` | Phase 2 | READ | Same as `GSI`, **plus** a `SAD` attribute on `<SiteFrequency>` | Slightly more verbose response. |
| `GSI,FULL` | Phase 2 | READ | Same as `GSI,PROP` | Synonym. |
| `GSI,XML,?` (qform) | Phase 2 | READ | Returns GSI XML with `Department`/`TGID Index="4294967295"` | Different from bare GSI - returns "no department/TGID resolved" view. Useful for forcing a "scanning..." snapshot. |
| `STS,1` / `STS,WIDE` / `STS,FULL` | Phase 2 | (n/a) | `STS,ERR` | Bare STS is the only valid form. |
| `MSI,STAT` / `MSI,PEEK` / `MSI,CURR` | Phase 2 | READ | Same as bare `MSI` (TypeError empty XML, since not in menu) | All MSI args fall through to the documented MSI handler. |
| `GST,1` / `GST,X` / `GST,FULL` | Phase 2 | (n/a) | `GST,ERR` | Bare GST is the only valid form. |

### Phase 3: BCDx36HP V1.05-derived GLT subforms

The BCDx36HP V1.05 spec documents GLT subforms not in SDS V1.02 / V2.00.
Probing them on the SDS100 reveals which subforms the SDS firmware
inherits.

| Command | Source | Safety | Behavior | Notes |
|---|---|---|---|---|
| `GLT,SYS` | BCDx36HP V1.05, Phase 3 | READ | Returns the SYS list **without an FL index** | Undocumented in SDS spec but works! Lists all systems across all FLs. |
| `GLT,DEPT` | BCDx36HP V1.05, Phase 3 | READ | Empty `<GLT><Footer/></GLT>` | Recognized but needs index. |
| `GLT,SITE` | BCDx36HP V1.05, Phase 3 | READ | Empty `<GLT><Footer/></GLT>` | Recognized but needs index. |
| `GLT,STGID` | BCDx36HP V1.05, Phase 3 | READ | Empty | Recognized; needs site_index. |
| `GLT,CC` | BCDx36HP V1.05, Phase 3 | READ | Empty | Close Call list - empty since CC not running. |
| `GLT,WX` | BCDx36HP V1.05, Phase 3 | READ | Empty | Weather channels list - empty. |
| `GLT,SWS_FREQ` | BCDx36HP V1.05, Phase 3 | READ | Empty | Search-with-Scan freqs. |
| `GLT,CCHIT` | BCDx36HP V1.05, Phase 3 | READ | Empty | Close Call hits. |
| `GLT,CS_FREQ` | BCDx36HP V1.05, Phase 3 | READ | Empty | Custom Search freqs. |
| `GLT,QS_FREQ` | BCDx36HP V1.05, Phase 3 | READ | Empty | Quick Search freqs. |
| `GLT,RPTR_FREQ` | BCDx36HP V1.05, Phase 3 | READ | Empty | Repeater Find freqs. |
| `GLT,UREC_FOLDER` | BCDx36HP V1.05, Phase 3 | READ | Empty | User Record folders. |
| `GLT,BAND_SCOPE` | BCDx36HP V1.05, Phase 3 | READ | Empty | Band scope freqs. |
| `GLT,ATGID,0` | BCDx36HP V1.05, Phase 3 | READ | Truncated `<GLT>` (no Footer EOT) | Returns shorter response than other GLT subforms - possibly a firmware bug or a different output format. |
| `GLT,UREC_FILE,0` | BCDx36HP V1.05, Phase 3 | NORESP | (timeout, 1505 ms) | **Hangs** the response stream. Possibly an actual bug; possibly waiting for SD card read with no folder. **Do not use** until investigated. |

### Phase 3: Inherited BCDx36HP commands not in SDS spec

| Command | Source | Safety | Behavior |
|---|---|---|---|
| `VOL,?` | BCDx36HP V1.05 inherited | WRITE | Returns `VOL,OK` - the qform of a write command |
| `SQL,?` | BCDx36HP V1.05 inherited | WRITE | Returns `SQL,OK` - same |
| `BFH` | BCDx36HP V1.05 | WRITE | **NEVER PROBED** - mutating (Band Scope Frequency Hold). Added to FORBIDDEN list. |

### Confirmed-ERR legacy commands (regression markers)

These BCDx36HP-era commands consistently return `ERR` on the SDS100,
but are kept in the probe list to detect any firmware regression.

| Command | All-firmware behavior |
|---|---|
| `RSI`, `BAV`, `BLT`, `CNT`, `DMA`, `SCN`, `CBP`, `CSP`, `LOC`, `GIN,GPS`, `CLK`, `OMS`, `BLI`, `MEM`, `PRI`, `ALT`, `GID`, `NTG`, `WFL`, `FAV`, `RLG` | All return `ERR\\r` |

## Pending: Phase 4 - Sentinel USB capture

Sentinel almost certainly uses commands not in any spec. Per
`sentinel_capture.md`, capturing the 6 high-value workflows
(Read From Scanner, Write to Scanner, Get HPDB Update, Update
Firmware, Backup, Restore) should reveal Sentinel's private
command vocabulary. **Expected yield**: 5-20 commands, especially
around the `.hpe` config-dump workflow.

This phase requires user time to drive Sentinel; not started.

## Phase 6 (2026-05-03): Sub firmware disassembly - COMPLETE for SUB-side dispatch

Phases 6.1-6.4 are now DONE for the lowercase debug command set:

- Phase 6.1 (extract payload): COMPLETE.
- Phase 6.2 (Ghidra headless import + auto-analysis): COMPLETE via
  `tools/automation/run_ghidra_setup.ps1`. Project lives at
  `../firmware/SDS100_SUB.gpr`.
- Phase 6.3 (locate dispatch): COMPLETE. Parser is `FUN_14006ca6`.
  Documented in [`sub_command_dispatch.md`](sub_command_dispatch.md).
- Phase 6.4 (live-falsify): COMPLETE for the 13 single-char debug
  commands. See [`sessions/probe_batch_round4_pass1_*`](../sessions/).

What's still **PENDING**:

- Round 5: inter-MCU bus protocol spec (USART2 frame format between
  SUB and MAIN, the actual byte-stream Sentinel + MAIN commands ride
  on). Outline and entry points are in
  [`sessions/round1_2_findings_2026-05-03.md`](../sessions/round1_2_findings_2026-05-03.md).
- Mode-state probing: re-run `q`/`r`/`m` after pre-toggling `t` and
  `u` to enumerate the format-string variants that the same dump
  emits in different modes (the 35 "untriggered format strings"
  earlier in this doc are likely the alt-mode outputs of these
  same commands).
- MAIN MCU disassembly: the SUB's USART2 outbound side is now
  understood; the matching protocol on the MAIN side requires the
  MAIN firmware (encrypted, not yet extracted).

## Maintenance

When any of the pending phases produces new commands, append them
to the appropriate section above. Keep the methodology / safety /
source columns consistent. Promote READ-classified commands into
`serial_probe.py` / `sub_probe.py` whitelists; add WRITE / mutating
commands to FORBIDDEN.
