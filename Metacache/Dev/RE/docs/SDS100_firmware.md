# SDS100 Firmware - Static RE write-up

> **Canonical narrative is in the wiki**:
> [`wiki/RE-Firmware.md`](../../../wiki/RE-Firmware.md). This file
> is the lab notebook with raw entropy + diff data.

> Captured 2026-04-27 EDT (Session 4 + static RE pass) on
> `<HOST>`. Tooling: `Metacache/Dev/RE/_firmware_strings.py`,
> `Metacache/Dev/RE/_firmware_structure.py`. Outputs in
> `Metacache/Dev/RE/firmware_analysis/`.
>
> **Bottom line: Main is encrypted (static RE infeasible). Sub is
> readable and gave us the entire RF/DSP architecture for free.**

## What we have on disk

| File | Size | Source | Note |
|---|---|---|---|
| `firmware/1.23.07_main/SDS-100_V1_23_07.bin` | 2,162,688 B | Uniden TWiki (public ZIP) | user's previous Main |
| `firmware/SDS-100_V1_26_01.bin` | 2,162,688 B | Sentinel local cache | user's current Main |
| `firmware/1.03.05_sub/SDS-100-SUB_V1_03_05.firm` | 88,864 B | Uniden TWiki (public ZIP) | user's previous Sub |
| `firmware/SDS-100-SUB_V1_03_15.firm` | 90,464 B | Sentinel local cache | user's current Sub |

Plus bridging versions: `SDS100_V1.23.20_Main.zip`,
`SDS100_V1.23.15_Main_V1.03.06_Sub.zip`,
`SDS200_V1.24.00_Main.zip` (the SDS200 1.24.00 ZIP - shares the
firmware family, useful for cross-comparison).

SHA-256:

```
Main 1.23.07 (old)  813E64F756A89DE91D25C952957A0AF8D41F2FBB5CA7E247233EBF23B60CF3FA
Main 1.26.01 (new)  CFB07E720B37F88E58A738D3BD81D25B5D1F4484711167E653BE301FBDAC7D9A
Sub  1.03.05 (old)  38F4A3BBF2BF0EC8D25FC09681A441CA1D5CA4C2BCEA5FADD2AF674AC0F189F0
Sub  1.03.15 (new)  C8FBEE4370589EE801EE8BDF97F4476F7CF5D6362ADD850A13810B0750520909
```

## Main firmware (.bin) - encrypted, dead-end for static RE

### Evidence

- **Whole-file Shannon entropy: 7.9999 / 8.0** (essentially maximum)
- **All 528 of 528 4-KiB chunks score >= 7.5 bits/byte.** No
  unencrypted region anywhere in the file.
- **First 64 and last 64 bytes look statistically random** -
  no plaintext header, no plaintext footer, no length field, no
  obvious magic bytes, no signature block, no metadata.
- **String-extraction yielded only random-ASCII noise** - 3,301
  "strings" in 1.23.07 and 3,562 in 1.26.01 with **zero overlap**
  between the two files. Real firmware versions of the same product
  share thousands of strings (error messages, format strings,
  command names, etc.). Zero overlap is the signature of strong
  encryption with version-specific keys/IVs.
- **Byte-level diff: 99.61% of bytes changed** between 1.23.07 and
  1.26.01, distributed across **8,429 changed runs** with no large
  unchanged region. Real firmware changes a small percentage of
  bytes; an avalanche of byte changes is what an encryption-with-
  changed-IV looks like.

### Conclusion

The Main MCU firmware ships as **a sealed encrypted blob** that the
on-device bootloader decrypts using a hardware-fused key (probably
in the STM32's OTP or in a security IC paired with it). We have no
practical way to recover the key from a software-only attack:

- We cannot extract the bootloader from a working device (no JTAG /
  SWD interface exposed)
- We cannot guess the key (256-bit search space)
- We cannot side-channel attack without specialized power-analysis
  hardware
- We cannot dump the STM32 die without electron microscopy

**Static RE on Main firmware is therefore infeasible** for this
project. We document this finding loudly so future-us doesn't
re-try it.

### What this means for the project

- **In-app firmware updater is unaffected.** We don't need to decrypt
  to flash. The bootloader does that. We just copy bytes.
- **Live serial RE remains the only path to learn what Main is
  doing.** The V1.02 + V2.00 spec + our captures of GSI / GLT / STS /
  GLG / etc. is the canonical source. Static RE was supposed to be a
  bonus; that bonus is unavailable.
- **Forget about finding undocumented Main commands via firmware
  string scan.** They're not extractable.

## Sub firmware (.firm) - readable; full DSP architecture decoded

### Container format

The Sub firmware **is not encrypted**. It's a plaintext-headed
container around mostly-compressed code:

```
Offset    Size  Field
00000000   12   "SDS-100-SUB\0"        (model magic, ASCII + NUL)
0000000C   12   0xFF padding
00000018   16   "Version 1.03.15 \0"   (version string, space + NUL padded)
00000028    4   length-or-flag-1       (e.g. 00 01 60 5C in 1.03.15)
0000002C    4   length-or-flag-2       (e.g. 00 00 00 80)
00000030    4   length-or-flag-3       (e.g. 00 01 60 E0)
00000034   12   0xFF padding
00000040  ...   <compressed payload, mostly LZMA1 + zlib chunks>
...
EOF-16     12   0xFF padding
EOF-4       4   CRC-32 or signature    (e.g. 57 e6 b5 2a in 1.03.15)
EOF       12   "SDS-100-SUB\0"        (footer magic)
```

Whole-file entropy is **7.18 / 8.0** - high but not maxed out, which
matches a binary of mostly-compressed code with some uncompressed
metadata.

### Decoded architecture from real strings

The Sub firmware leaks the entire RF / DSP architecture in printf
format strings, debug labels, and source-file paths.

#### Source paths -> SUB MCU is NXP LPC43xx

```
../src/lpc43xx_i2c.c
```

That source path is from the **NXP LPC43xx series** - an ARM
Cortex-M4 + Cortex-M0 dual-core SoC (NXP LPC4350/LPC4357 family,
typically). This identifies the SUB processor unambiguously.
Reset-vector candidates were also found at offsets `0x1bc` and
`0x204`, consistent with an ARM Cortex-M flash layout (vector table
near the top of flash with a stack-pointer init at the very start).

#### RF tuner -> Rafael Micro R840

```
R840_FM
R840_DVB_T2_1_7M
```

The Rafael Micro **R840** is a wideband silicon TV-tuner IC
(originally for DVB-T2 demodulation) which Uniden uses as the wide
IF tuner in the SDS100. The `R840_DVB_T2_1_7M` mode is the
DVB-T2-class 1.7 MHz bandwidth filter setting; `R840_FM` is the
narrow-FM filter. The SUB MCU clearly drives the R840 directly via
I2C (matches the `lpc43xx_i2c.c` source path).

#### Digital signal-path

The SUB firmware contains debug-print format strings that map the
entire DSP pipeline:

```
ADC P-P, %d, %fmV
CIC OUT   min,%6d,  max=%6d, err=%6d
FIR1 OUT  min,%6d,  max=%6d, err=%6d
FIR2 OUT  min,%6d,  max=%6d, err=%6d
FFT_PEAK,%ddB
FFT_FREQ,%d
FIR2_Range,%d, %ddB
NCO_Range,min=%6d, max=%6d, dif=%6d
Noise Squelch,%6d
Window,%d
IF=%d, STD= %s
```

That's a complete textbook digital-down-conversion + filtering chain:

```
RF -> R840 tuner -> IF analog -> ADC -> CIC -> FIR1 -> FIR2 -> NCO mix -> FFT
                                                                            |
                                                                            v
                                                                    Waterfall display
                                                                    Noise squelch
```

Implications:
- **The waterfall display data we see in `GST` and `GWF` is computed
  on the SUB processor**, then shipped over the SUB-to-MAIN link
  for display. That's why `GWF` toggling streams a heavy continuous
  payload (it's pumping live FFT output through the MAIN port).
- **Squelch is digital, computed in DSP** (`Noise Squelch`
  parameter). Not a simple analog threshold.
- **`IF=%d, STD= %s`** suggests the SUB exposes IF frequency and
  standard (narrow/wide/AM/FM/etc.) over its command port. We
  haven't found the query for it yet.

#### Gain chain

```
RF_gain_comb,%d, LNAGain1,%d, LNAGain2,%d, MixerGain,%d
RF_GainMode,MANUAL
RF_GainMode,AUTO
VGA Mode Auto(Pin)
VGA Mode Manual,%d
LNAGain1,Auto / LNAGain1,%d
LNAGain2,Auto / LNAGain2,%d
MixerGain,Auto / MixerGain,%d
dBm,%d,LNAGain1,%d, LNAGain2,%d, MixerGain,%d, Max,%d, ADC_P-P,%d
IfRssi,%d
RssiDbm,%d
```

Four-stage AGC: **LNA1 -> LNA2 -> Mixer -> VGA**. Each stage can
be individually `Auto` or `Manual`. `RssiDbm` is the
post-conversion RSSI in dBm (this is what `PWR` reports on MAIN).

#### LPF (low-pass filter) settings

```
Widest LPF, %d
Narrowest LPF, %d
LPF, %d
Default LPF, %d
```

Multiple LPF presets. Probably what the V2.00 spec mentions when it
says (for 1.23.20 Sub) "Improved WFM/FMB Squelch Threshold
Adjustment".

### SUB-port status format (1.03.05 -> 1.03.15 diff)

The most interesting concrete protocol change between Sub versions:

```
1.03.05:  S%02X%04X%04X%04X%04X%01X
1.03.15:  S%02X%04X%04X%04X%04X%01X%04X     (added one trailing %04X field)
```

So the SUB processor's status report format added a new 16-bit field
in 1.03.15. We don't yet know what it carries (some new ADC stat,
maybe?), but the format is concrete and parseable.

This is a **read-only command** the SUB port answers - we just don't
know its mnemonic yet because the SUB port has a different command
set than MAIN. Probing the SUB port with single-letter commands and
short tokens during Session 5 should expose the status query.

### SUB strings diff (1.03.05 -> 1.03.15)

Real strings that appeared/disappeared between the two Sub versions
(after filtering out random-ASCII noise from compressed regions):

| Direction | String | Notes |
|---|---|---|
| Added | `Version 1.03.15 ` | new version string |
| Added | `S%02X%04X%04X%04X%04X%01X%04X` | new status format with extra field |
| Added | `*SDS-100-SUB` | possibly new boot banner variant |
| Removed | `Version 1.03.05 ` | old version string |
| Removed | `S%02X%04X%04X%04X%04X%01X` | old status format |

The rest of the diff (~85 strings) is high-entropy noise from
compressed code regions, not real changes.

## Cross-cutting findings & next steps

1. **Don't waste time on Main static RE.** Document, move on.
2. **Sub firmware is the static-RE surface for this scanner.** When
   we want to know what tuner / DSP / squelch parameters exist, the
   Sub strings are the cheat sheet.
3. **The waterfall stream is SUB-sourced.** A future "live waterfall"
   feature in scanner-manager should consume from the SUB port
   directly if possible, bypassing MAIN's `GWF` stream toggle.
4. **The SUB port is under-explored.** Session 4 only sent 10
   commands to it; we should write a SUB-targeted whitelist
   (`Metacache/Dev/RE/sub_probe.py`) and walk a short alphabet of
   1-3-letter mnemonics looking for the status-S query, IF-frequency
   query, gain-state query, FFT-stream query, etc.
5. **SDS150 (UB3912) is the same firmware family.** Per the V2.00
   spec the new SDS150 shares the same .bin / .firm format as
   SDS100 / SDS200. Same encryption, same SUB MCU. So everything
   here applies to SDS150 too - which matters when we add SDS150
   to the multi-device GUI.

## Tooling reference

- `Metacache/Dev/RE/_firmware_strings.py` - extracts ASCII runs from each
  firmware image, writes per-file string lists, computes set diffs
  between old/new of each MCU, scans for command-mnemonic candidates.
- `Metacache/Dev/RE/_firmware_structure.py` - per-image entropy profile,
  hex dump of head/tail, magic-byte signature scan, byte-level diff
  between same-MCU versions.
- `Metacache/Dev/RE/firmware_analysis/firmware_structure_report.md` - the
  rendered structural report.
- `Metacache/Dev/RE/firmware_analysis/sub_1.03.15.strings.txt` etc. - raw
  string lists; the Sub ones are the readable goldmine, the Main
  ones are noise-only.

---

## Session 6 update (2026-04-29) - Sub payload extracted, NOT compressed

> **Important correction.** Session 4 reported the Sub firmware as
> "mostly compressed code" with putative zlib + LZMA1 chunks. That
> was wrong. The "zlib magic" hits in the structural scan were
> coincidental matches in plaintext ARM Cortex-M machine code. The
> Sub `.firm` container is a thin header / footer wrapping a
> **plaintext ARM payload** - no compression of any kind.

### Sub payload extraction

[`_inflate_sub.py`](_inflate_sub.py) parses the container header
and writes the payload directly:
[`firmware/sub_1.03.15_inflated.bin`](firmware/sub_1.03.15_inflated.bin)
(90,076 bytes; full chunk map in
[`firmware/sub_1.03.15_chunk_map.md`](firmware/sub_1.03.15_chunk_map.md)).

Container layout (corrected):

```
Offset    Size  Field
00000000   12   "SDS-100-SUB\0"            (model magic)
0000000C   12   0xFF padding
00000018   16   "Version 1.03.15 \0"
00000028    4   00 01 60 5C   payload_end_offset (= 0x1605C + 0x24 footer = 0x16080)
0000002C    4   00 00 00 80   header_size_marker (= 0x80 = payload start)
00000030    4   00 01 60 E0   total_file_size_minus_4 (cross-check)
00000034   12   0xFF padding
00000080  ...   <plaintext ARM Cortex-M payload, 90,076 bytes>
0001605C   28   trailing CRC + footer block
EOF-12     12   "SDS-100-SUB\0"            (footer magic)
```

CRC-32 of `[0x00, 0x16080)` matches the trailing 4-byte CRC field
exactly - integrity check confirmed.

### Decoded ARM Cortex-M reset vector

First 16 32-bit words of the payload form a Cortex-M vector table:

| Index | Vector | Value | Notes |
|---|---|---|---|
| 0 | Initial SP | `0x10020000` | LPC43xx local SRAM bank 0 top (0x10000000+128KB) |
| 1 | Reset PC | `0x140001D5` | Thumb bit set; entry at flash 0x140001D4 (SPIFI flash region) |
| 2 | NMI | `0x14005A89` | flash |
| 3 | HardFault | `0x14005AAB` | flash |
| 4-10 | reserved/MM/UF | flash | |
| 11 | SVCall | `0x14005AAD` | flash |
| 14 | PendSV | `0x14005AAF` | flash |
| 15 | SysTick | `0x10006295` | **SRAM** - copy-on-boot routine |

Most exception handlers live in `0x14000000+` SPIFI flash; the
SysTick handler is in SRAM, indicating a `.fastcode`-style copy at
boot. **Confirms the Sub is an ARM Cortex-M3/M4 on the LPC43xx
family, executing from SPIFI-attached external flash, with a small
SRAM-resident fastpath**.

### Static analysis (Phases 6.3-6.5 best-effort, no Ghidra)

[`_sub_static_analysis.py`](_sub_static_analysis.py) searches for
ASCII command-mnemonic candidates and 32-bit constants matching
LPC43xx peripheral base addresses. Results are
[`sub_static_analysis.md`](sub_static_analysis.md).

| Peripheral | Base | Hits in payload | Plausible role |
|---|---|---|---|
| `SRAM_BANK0` | 0x10000000 | many | RAM access (literal pool) |
| `ADC1` | 0x400E4000 | 8 | ADC sampling for IF |
| `SCT` | 0x40000000 | 9 | timer / DMA pacing |
| `UART1` | 0x40082000 | 6 | likely inter-MCU control link |
| `SSP0` | 0x40083000 | 6 | likely inter-MCU SPI link or external peripheral |
| `USB0` | 0x40006000 | 5 | host-side USB CDC port |
| `I2S0/I2S1` | 0x400A2000/3000 | 0 (via constant scan) | accessed via struct pointer indirection, not direct literals |
| `I2C0` | 0x400A1000 | low | drives R840 tuner (matches `lpc43xx_i2c.c` source path) |

**Inter-MCU bus inference**: between UART1 (6 refs) and SSP0 (6
refs), the most likely candidates for the SUB-to-MAIN control
channel are one of those two. Neither has a dominant lead, so a
Ghidra disassembly is needed to disambiguate by tracing register
read/write semantics. The runbook for that work is in
[`ghidra_import_runbook.md`](ghidra_import_runbook.md) - estimate
20-50 hours of focused effort.

The mnemonic-candidate clustering yielded 45 candidates / 31
clusters but no obvious dispatch table - the dispatch is probably
implemented as a table of (string-pointer, function-pointer) pairs
indexed indirectly, or as a chain of `strcmp` blocks, neither of
which is detectable without disassembly.

### Live correlation results

[`_correlate_responses.py`](_correlate_responses.py) joins
SUB-probe hits (from `sessions/sub_probe_*`) against the Sub
firmware string table by converting printf format strings into
regexes. Output:
[`sub_command_response_map.md`](sub_command_response_map.md).

Findings:
- 38 unique SUB-probe hits, 269 firmware strings, **35 untriggered
  printf format strings**.
- The lone `U` hit (response `U5C42\\r<\\x00><2 binary bytes>`)
  did NOT match any firmware format string. The response is most
  likely a fixed-byte register dump emitted by direct
  `write(stdout, &reg, 9)` rather than a `printf`.
- Identity-fallback hits (`M*`, `V*`) emit `SDS100-SUB` /
  `Version 1.03.15` directly - hard-coded, not via format string.

The 35 untriggered format strings are the highest-value targets
for future SUB probing. Listed in
[`sub_command_response_map.md`](sub_command_response_map.md);
they cover R840 tuner mode, RF gain readouts, FFT debug,
CIC/FIR/NCO debug, ADC P-P, and squelch threshold.

### Updated next steps

1. **Phase 6.2 (Ghidra import)** - the runbook is written
   ([`ghidra_import_runbook.md`](ghidra_import_runbook.md)),
   the payload is extracted, the load address (`0x14000000`) and
   architecture (Cortex-M3/M4 little-endian Thumb) are known.
   This is the single biggest unblock for finishing Phases 6.3-6.5.
2. **Phase 4 (Sentinel USB capture)** - workflow documented in
   [`sentinel_capture.md`](sentinel_capture.md); needs user to
   drive Sentinel through 6 operations with USBPcap recording.
3. **Targeted SUB re-probe** based on the 35 untriggered format
   strings - extend [`sub_probe.py`](sub_probe.py) with mnemonic
   candidates derived from the string fragments (`RF_GainMode`
   -> try `RFGM`, `RFG`, `GAIN`; `R840_FM` -> try `R840`, `STD`,
   `MODE`; etc.).
