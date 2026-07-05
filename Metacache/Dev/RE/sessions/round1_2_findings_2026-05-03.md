# Track A Round 1+2 findings - 2026-05-03

## Summary (TL;DR)

The SDS100 SUB processor (LPC43xx) is **not** the host of the documented
Uniden serial command set. It is a **USB↔USART2 bridge** to MAIN, with a
small set of 13 single-character lowercase **debug commands** of its own.

| Question | Answer |
|---|---|
| Where is the SUB-side parser? | `FUN_14006ca6` (0x14006b20-0x14006f45, 860 B). |
| What's the parser shape? | Per-character `if (cVar5 == 'X')` ladder, lowercase ASCII only. |
| How many commands? | 13: `o q w d r m z h l s t u v`. |
| Are MDL / VER / STS handled here? | **No.** None of those strings exist in the SUB firmware at all. |
| What about ERR? | Also not present. The SUB does not emit `ERR\r` itself. |
| Where do uppercase commands go? | Forwarded over USART2 (115200 / 8N1) to MAIN. |
| Is `h` (streaming) confirmed? | **Yes.** The decompile of `FUN_14006ca6` matches our empirical observation exactly: 4-buffer composite dump driven from `DAT_14006bdc`. |
| What is `FUN_14010fec`? | `vfprintf`, the printf engine. (Originally hypothesised to be the parser; ruled out.) |
| What is `FUN_14010554`? | USB device init. Calls USART2 setup as part of USB device bringup -> proves the bridge architecture. |

## What we proved

### 1. USART2 is the inter-MCU bus

`FUN_14010554` (USB device init) explicitly calls `FUN_1400eb24` (USART2
mux/init) before configuring USB endpoints. `FUN_1400eb24`:

- Configures USART2 for 0x1c200 = **115200 baud, 8N1**.
- Touches GPIO + SCU + USART2 only. **No external pins** - the GPIO ops
  set `*(iVar3 + 0x2000) |= 0x100` and `*(iVar3 + 8) = 0` which are
  internal pin-mux/oscillator settings, not external I/O.
- This is consistent with USART2 being routed only to the MAIN MCU,
  not to any external connector.

The other USARTs:
- USART1, USART3 also at 115200/8N1, but with much smaller DMA buffers
  (0x20 / 0x80 vs USART2's same 0x80) - likely peripheral traffic
  (R840 tuner, audio codec).
- USART0 is initialised with a different baud loaded from `DAT_1400e704`
  - probably a slower service bus.

### 2. The SUB doesn't have a string-table dispatch

We searched the firmware exhaustively for byte patterns matching every
known SUB-port command:

```
MDL\0 -> 0 hits        VER\0 -> 0 hits        STS\0 -> 0 hits
MDL,  -> 0 hits        VER,  -> 0 hits        STS,  -> 0 hits
MDL\r -> 0 hits        VER\r -> 0 hits        GLT,SYS -> 0 hits
BCDx36HP -> 0 hits     ERR -> 0 hits          \rERR -> 0 hits
SDS100 -> 1 hit at 0x14013290 (likely a USB iSerial / device-string table)
```

So:
- The SUB cannot be the source of `MDL,BCDx36HP\r` etc.
- The SUB cannot be the source of `ERR\r` (the ubiquitous error response).
- Both must come from MAIN, transported back over USART2 and re-emitted
  on USB CDC IN.

### 3. The actual parser uses immediate-encoded characters

The per-character compares in `FUN_14006ca6` look like `if (cVar5 == 'o')`
in the decompile, but at the assembly level those are
`cmp r0, #0x6f` instructions. The byte value `0x6f` lives **inside the
instruction**, not as a separately-stored string. This is why our
"short-mnemonic string" heuristic in `SetupSubProject.java`
(`scanForShortMnemonics()`) found nothing earlier - there are no
strings to scan for.

The implication for future RE work: heuristics that look for short
ASCII strings in the data section will under-predict on tightly-coded
ARM Thumb firmware. The right primitive is **count `cmp`-immediate
instructions per function** with their immediates restricted to printable
ASCII.

### 4. The five Round-1 entry points, classified

| Function | Size | Role - confirmed |
|---|---:|---|
| `FUN_14010554` | 360 B | **USB device init**, NOT the per-packet RX handler. Calls USART2 mux init - this is where the inter-MCU bus comes online. |
| `FUN_1400e57c` | 380 B | **UART init** for all 4 USARTs. USART1/2/3 at 115200/8N1, USART0 baud from `DAT_1400e704`. |
| `FUN_1400eb24` | 68 B | **USART2 pin-mux / oscillator** - confirms USART2 is internal-only routing. |
| `FUN_1400e900` | 94 B | **5-channel UART/USB tx mux** (case 0..3 = USART0..3, case 4 = USB CDC IN via `FUN_140072ac`). Has 12 callers - the response emitters. |
| `FUN_14010fec` | 3348 B | **`vfprintf`** (printf engine). NOT the parser - ruled out. |

### 5. The actual SUB-side parser is `FUN_14006ca6`

A different function entirely, found by enumerating "0-callers, no
peripheral access, large body" and reading the first one. See
[`sub_command_dispatch.md`](../docs/sub_command_dispatch.md) for the full
dispatch table.

### 6. `FUN_14008340` is a forwarder, not a second parser

We initially suspected `FUN_14008340` (called by `FUN_14006ca6`'s
fallback) was an uppercase-command dispatch table at `DAT_14008428`. The
decompile shows a `cmp byte (table[i*8]) == param_2` loop with 76
iterations and a function-pointer fetch from `table[i*8 + 4]`. But:

- `DAT_14008428` resolves to `0x1001319C` (SRAM-linked).
- Mapping `0x1001319C` to flash via the 1:1 SRAM-to-ROM offset
  (`+0x04000000`) gives `0x1401319C`.
- Reading 80 entries at that location shows **printf format strings**
  (`%d,`, `%04X`, `%llu, %u, %u`, etc.) crammed together, not
  (byte, fn-ptr) pairs.
- So Ghidra's jumptable analysis (which itself printed
  `WARNING: Could not recover jumptable at 0x14008388`) mis-decoded a
  format-string scan as a dispatch table.

The actual purpose of `FUN_14008340` is **outbound byte forwarding** with
three accumulator state machines (5-byte, 2-byte, 5-byte) that frame
host commands into MAIN-bound USART2 packets. Round 5 (inter-MCU bus
spec) will document the framing.

## What's left for Round 4

Live falsification of the 13 SUB-side commands on COM3:
- All except `h` (already known) need empirical validation.
- `t` and `u` modify a mode flag silently - test by paired probes:
  `t`, then `q`/`w`/`r`/`m`/`v` and observe whether output format changes.
- `o` and `d` look like enable/disable pairs - test by sequencing.
- `l` is conditional on a counter - test will return either header-only
  (counter=0) or rows.

Also pending: live confirmation that uppercase commands sent on COM3 are
forwarded to MAIN - we infer this but haven't proven it timing-wise.
This belongs in Round 5 anyway (inter-MCU bus spec).

## Files produced

- [`firmware/decompiles/14006ca6_FUN_14006ca6.json`](../firmware/decompiles/14006ca6_FUN_14006ca6.json) - the parser.
- [`firmware/decompiles/14010554_FUN_14010554.json`](../firmware/decompiles/14010554_FUN_14010554.json) - USB init.
- [`firmware/decompiles/1400e57c_FUN_1400e57c.json`](../firmware/decompiles/1400e57c_FUN_1400e57c.json) - UART init.
- [`firmware/decompiles/1400eb24_FUN_1400eb24.json`](../firmware/decompiles/1400eb24_FUN_1400eb24.json) - USART2 mux.
- [`firmware/decompiles/1400e900_FUN_1400e900.json`](../firmware/decompiles/1400e900_FUN_1400e900.json) - tx mux.
- [`firmware/decompiles/14010fec_FUN_14010fec.json`](../firmware/decompiles/14010fec_FUN_14010fec.json) - vfprintf.
- [`firmware/decompiles/14008340_FUN_14008340.json`](../firmware/decompiles/14008340_FUN_14008340.json) - forwarder.
- Plus all 13 handler decompiles at varying granularity.

Tooling produced this round:
- `automation/ghidra_scripts/DecompileFunctions.java` - per-function decompile dumper.
- `automation/run_ghidra_decompile.ps1` - PowerShell wrapper.
- `_decompile_pull.py` - Python orchestrator (default targets + `--list` + `--show`).
- `_inspect_func.py` - one-off function inspector (cmp count + decompile preview).
- `_extract_dispatch.py` - reads firmware bytes at SRAM-linked addresses.
- `_find_parser.py` - parser-hunting helpers (string xrefs, USB peripherals, 0-callers).
