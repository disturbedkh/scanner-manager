# SUB Command Dispatch Table

> **Canonical narrative is in the wiki**:
> [`wiki/RE-Serial-Protocol.md`](../../../wiki/RE-Serial-Protocol.md)
> (the "SUB port" section). This file is the lab notebook with the
> full dispatch decompile.

> Manually curated from Track A Round 1-3 RE work, 2026-05-03.
> Source function: `FUN_14006ca6` (sub_1.03.15_inflated.bin, 0x14006b20-0x14006f45).
> Companion artefacts:
> - [`firmware/decompiles/14006ca6_FUN_14006ca6.json`](firmware/decompiles/14006ca6_FUN_14006ca6.json) - full decompile.
> - [`sessions/round1_2_findings_2026-05-03.md`](sessions/round1_2_findings_2026-05-03.md) - narrative.
> - [`sessions/dispatch_candidates.txt`](../sessions/dispatch_candidates.txt) - input for [`tools/probes/verify_dispatch.py`](../tools/probes/verify_dispatch.py).
>
> **Status: `pending Round 4 live verification` for the inline-emitter handlers.**
> The streaming `h` command is already empirically confirmed via earlier Phase
> 2 work and matches the decompile exactly.

## Architecture

The SDS100 SUB MCU has **two distinct command-input sources** that share a
single character-by-character parser:

```
host -- USB CDC OUT --> [SUB ring buffer at DAT_14006f4c]
                              |
                              v
                       FUN_14006ca6 (lowercase debug parser)
                              |
                  match? --yes--> handler in firmware ROM
                              |
                  match? --no--->  forward to MAIN over USART2
                                   (via FUN_14008340 channel 4)
```

Key empirical finding: the SUB firmware contains **none** of the standard
Uniden command mnemonics as strings:

| Mnemonic | Bytes searched in firmware | Hits |
|---|---|---:|
| `MDL` | `MDL\0`, `MDL,`, `MDL\r`, `MDL ` | **0** |
| `VER` | `VER\0`, `VER,`, `VER\r` | **0** |
| `STS` | `STS\0`, `STS,` | **0** |
| `GLT` | `GLT`, `GLT,SYS` | **0** |
| `BCDx36HP` (model) | direct ASCII | **0** |
| `ERR` (error response) | `ERR`, `\rERR`, `ERR\r` | **0** |
| `SDS100` | direct ASCII | 1 (at `0x14013290`) |

This is conclusive: the SUB processor **does not** handle Uniden's documented
serial command set. Those commands are forwarded over the inter-MCU bus to
MAIN, which handles parsing and response emission. The SUB acts as a
USB↔USART2 bridge for MAIN traffic, with a small **debug-only** local
command set described below.

## Local SUB-side dispatch table (lowercase debug commands)

All 13 SUB-port commands are **single ASCII characters** with no arguments,
no `\r` terminator required to dispatch (the parser fires on the first byte
and the rest is forwarded to MAIN). Per-character `cmp` chain in
`FUN_14006ca6` evaluated top-to-bottom; first match wins.

| Order | Char | Hex | Handler | Side effect | Output shape |
|---:|:---:|:---:|---|---|---|
| 1 | `o` | 0x6F | `FUN_1400692c` | calls into another module | (none directly) |
| 2 | `q` | 0x71 | inline dump of 0x100 bytes from `DAT_14006f70` | reads a 256-byte SRAM buffer | header line + 128 short values via `%04X`-class format |
| 3 | `w` | 0x77 | inline dump of 0x100 bytes from `DAT_14006f78` | second 256-byte buffer dump (paired with `q`) | same shape as `q` |
| 4 | `d` | 0x64 | `FUN_140069d0` | calls into another module | (none directly) |
| 5 | `r` | 0x72 | inline dump of 0x400 bytes from `DAT_14006f7c` | **1024-byte buffer** dump | 128 short values via per-element format |
| 6 | `m` | 0x6D | inline: copy 0x100 from `DAT_14006f80`, zero 0x300 trailing, then dump 0x200 elements | 256-byte read + 768-byte zero-fill | 512 short values |
| 7 | `z` | 0x7A | `FUN_14006a64` | calls into another module | (none directly) |
| 8 | `h` | 0x68 | inline: 4-buffer composite dump | reads 0x80 + 0x80 + 0x80 + 0x80 from `DAT_14006bdc..0xbec` | header + 128 paired-column rows + header + 16 paired-column rows. **Empirically confirmed: this is the high-volume streaming command.** |
| 9 | `l` | 0x6C | inline: conditional dump driven by `*DAT_14006f90` counter | reads 4 byte/word streams in parallel | header + N records (N = `*DAT_14006f90`) of `(uint64, uint64, uint32, uint8)` shape via `%llu`-style format |
| 10 | `s` | 0x73 | `FUN_14006c00` | calls into another module | (none directly) |
| 11 | `t` | 0x74 | toggles `*DAT_14006f68` between 0 and 1 | flips a 1-byte mode flag | (no output - silent toggle) |
| 12 | `u` | 0x75 | cycles `*DAT_14006f68` between 2 and 0 | sets to 0 if currently 2, else 2 | (no output - silent toggle) |
| 13 | `v` | 0x76 | inline: 2-buffer dump (0x100 + 0x200 elements) | reads `DAT_14006f84` and `DAT_14006f88` (paired) | header + 256 paired records (32-bit, 32-bit) |

After the per-character ladder, any unmatched byte falls through to
`FUN_14008340(channel=4, byte)`, which is the bridge into the MAIN-bound
forwarding path (uppercase commands, ASCII digits, `\r`, etc. all flow
through here).

## Handler details

### `o` -> `FUN_1400692c` (134 B, 4 callees)
Calls FUN_14006328 + FUN_140063b8 (or similar internal helper). No format
strings emitted directly. Likely **enables / disables** some peripheral
or DSP block. Round 4 candidate: send `o\r` and observe state change with
follow-up `q` or `r` dumps.

### `d` -> `FUN_140069d0` (122 B, 5 callees)
Same shape as `o`. Likely paired toggle (`d` for disable, `o` for enable
or vice versa). Round 4: send `d\r`, capture before/after `r` output.

### `z` -> `FUN_14006a64` (164 B, 5 callees)
Larger than `o`/`d`. Calls FUN_14012bb0 + FUN_140105e4 + FUN_140072ac which
together emit a formatted line out the USB CDC TX. So **`z` produces a
single response line** (likely a stats / state report).

### `s` -> `FUN_14006c00` (114 B, 3 callees)
Compact. Likely **start / stop streaming** since it pairs naturally with the
`h` streaming dump. Round 4: send `s` once with `h` running and observe
whether the stream pauses.

### `t` and `u` (mode flags at `DAT_14006f68`)
- `t` writes `*DAT_14006f68 = (*DAT_14006f68 != 1)` -> toggles 0 <-> 1.
- `u` writes `*DAT_14006f68 = ((*DAT_14006f68 == 2) ? 0 : 2)` -> toggles
  0 <-> 2. So the byte at `0x14006f68 -> *0x100xxxxx` (SRAM) takes one of
  three values: 0, 1, or 2.

This is most likely a 3-state debug-output mode: 0 = silent, 1 = (`t`
mode), 2 = (`u` mode). Round 4: send `t`, then `q` and observe whether
output formatting changes; same with `u`.

### `q`, `w`, `r`, `m`, `v` (raw buffer dumps)
These are the **DSP/RF debug taps**:

| Char | Source pointer | Element count | Likely contents |
|---:|---|---:|---|
| `q` | `*DAT_14006f70` | 128 | 256 bytes of `something_short` - prob ADC histogram bucket |
| `w` | `*DAT_14006f78` | 128 | second 256-byte buffer paired with `q` (I/Q?) |
| `r` | `*DAT_14006f7c` | 128 | **1024-byte raw window** - either FFT bin magnitudes or 16-bit I/Q samples |
| `m` | `*DAT_14006f80` | 512 | 256-byte head + 768-byte zero - looks like spectrum mask (initialised at top, padded to 1KB) |
| `v` | `*DAT_14006f84`/`*DAT_14006f88` | 256 pairs | dual-stream 32-bit values - prob NCO / channel-power log |

The format strings driving these emitters live in
`Metacache/Dev/RE/firmware/analysis_dump.json` under `format_strings[]` and
match the patterns we already saw raw-bytes-dumped above
(`X%04`, `%d, %d`, `H, %`, etc.).

### `h` (streaming command - confirmed)
Already empirically validated in earlier Phase 2 work. The decompile
confirms the structure:

```
header line
for i in 0..127:                # 128 paired rows of dual-column %d
    emit "<word from DAT_14006bdc[i]>, <word from DAT_14006bdc+0x80[i]>"
header line
for i in 0..15:                 # 16 paired rows
    emit "<word from DAT_14006bdc+0x100[i]>, <word from DAT_14006bdc+0x180[i]>"
```

A single `h` invocation produces 128 + 16 = 144 lines of `int, int` text
plus 2 header lines = 146 lines total. The streaming behaviour we observed
empirically (`h` dumps continuously over many seconds) implies that
either:
- The four buffers (`bdc`, `bdc+0x80`, `bdc+0x100`, `bdc+0x180`) are
  continuously updated by an interrupt-driven DSP block while the
  emit-loop walks them - so each `h` press produces ~146 lines, but
  multiple presses or polling produces many more, OR
- There is an **outer caller of `FUN_14006ca6` that loops** (re-arming
  the parser after each successful command), and `h` keeps re-firing.

Round 4 to disambiguate: send single `h\r`, count lines until quiet.

### `l` (record-list / log)
Conditional on `*piVar2 = *DAT_14006f90 > 0`. Loops `*DAT_14006f90` times
emitting per-record lines via four parallel pointer increments
(`DAT_14006f60`, `DAT_14006f5c`, `DAT_14006f58`, plus a step loop counter).
Each record is `(uint64, uint64, uint32, uint8)` -> 21 bytes per record
formatted via `%llu, %u, %u`-style.

This shape strongly suggests a **frequency / hit log**: 64-bit timestamp,
64-bit frequency, 32-bit count, 8-bit flags. Round 4: send `l\r` and
observe whether it returns rows or just the header (depending on whether
the counter is non-zero).

## Forwarding fallback (`FUN_14008340`)

Any byte that doesn't match the above lowercase chars is sent to
`FUN_14008340(channel=4, byte)`. We do **not** treat `FUN_14008340` itself
as a command parser - the apparent dispatch table at `DAT_14008428`
turned out to be Ghidra mis-decoding a region of concatenated printf
format strings, not real (byte, fn) entries. The actual purpose of
`FUN_14008340` is to **bridge** characters into the SUB's per-channel
state machines (USART/USB-bound queues) for forwarding to MAIN.

The three pre-table state-machine blocks in `FUN_14008340`:
- accumulator at `*DAT_1400841c` collects 5 bytes then fires `FUN_1400640c`
- accumulator at `*DAT_1400842c` collects 2 bytes then fires `FUN_1400615c`
- accumulator at `*DAT_14008424` collects 5 bytes then fires `FUN_1400ae0c`

These are **outbound MAIN-port command formatter / framer** state
machines, not inbound parsers. They take the host's CDC bytes,
accumulate them, and emit framed packets over USART2 to MAIN. The
exact framing belongs in Round 5.

The special-case `param_2 == 0x52 ('R')` likely flags a control byte
that bypasses the accumulator (resync / reset), but this is not yet
confirmed.

## Round 4 candidates file

The 13 mnemonics above are written into
[`sessions/dispatch_candidates.txt`](sessions/dispatch_candidates.txt) for
[`tools/probes/verify_dispatch.py`](../tools/probes/verify_dispatch.py) to falsify against the live
COM3 port. Five of them (`h`, plus `t`, `u`, `s` per their handler
shapes) we expect to be silent or behave specially - the verifier will
classify them as `IDENTITY` or `TIMEOUT` and we annotate manually after.
