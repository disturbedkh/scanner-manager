# SDS100 Inter-MCU Protocol (USART2)

> **Canonical narrative is in the wiki**:
> [`wiki/RE-Inter-MCU-Bus.md`](../../../wiki/RE-Inter-MCU-Bus.md).
> This file is the lab notebook with full bit-level detail.

> Replaces the auto-generated draft. Curated from Track A Round 5 RE work,
> 2026-05-03. This is a **first-pass** spec - some fields are inferred from
> bit-shifts in the SUB-side decoder and require MAIN-side decompile or
> live USART2 capture to fully ground.

## Layer 0: physical

| Property | Value | Source |
|---|---|---|
| Bus carrier | LPC43xx **USART2** (NXP USART block) | `FUN_1400eb24` (USART2-specific init), `FUN_1400e57c` (multi-USART init) |
| Baud rate | **115200** (`0x1c200` divisor passed to `FUN_1400fd40`) | `FUN_1400e57c` line: `FUN_1400fd40(iVar3, 0x1c200);` |
| Word format | **8N1** (LCR = 3) | `FUN_1400e57c` line: `*(undefined4 *)(iVar3 + 0xc) = 3;` |
| Flow control | None (no RTS/CTS observed in init) | LCR bits 6-7 untouched, no MCR config |
| FIFO | enabled, default thresholds (FCR = 0x81 then 0xC7) | Standard NXP UART pattern |
| RX path | DMA (FUN_1400fa74 set up size 0x80 ring) | `FUN_1400e57c` line: `FUN_1400fa74(DAT_1400e72c, ..., 0x20);` and `FUN_1400e57c` line: `FUN_1400fa74(DAT_1400e734, ..., 0x80);` |
| TX path | **PIO with THRE-poll** (no DMA on TX) | `FUN_1400eafc` polls `LSR.THRE` (bit 5) per byte |
| Init triggers | called from `FUN_14010554` (USB device init) | USART2 comes online with USB - no separate boot path |

USART2 in `FUN_1400eb24` is configured with GPIO + SCU writes that
**don't route to any external pin pad** - pin-mux ops set internal
oscillator + FIFO pin only. This is consistent with USART2 being
SoC-internal; the SUB and MAIN MCUs are presumably wired together on
the PCB and never exposed externally.

## Layer 1: byte-level RX framing

Two parallel byte-decode paths run on the SUB side, both pumped from
the same dispatcher (`FUN_1400df18`):

### Path A: nibble-class single-byte protocol (`FUN_1400e9e0`)

This is the **primary inter-MCU control protocol**. Each byte is
self-contained. The top nibble (bits 7-4) is the **opcode class**;
the low nibble (bits 3-0) is the payload, expanded into individual
flag fields.

| Opcode (top nibble) | Decoder slot at | Behavior | Likely meaning |
|---:|---|---|---|
| `0x00` | `*DAT_1400eaac = byte` | Stores the full byte (0x00-0x0F) at one byte-pointer | Generic 4-bit value (e.g. RF gain index, channel, register read result) |
| `0x10` | 4 bit-pointers `DAT_1400ea90/94/98/9c = bit3/2/1/0` | Splits the low nibble into 4 boolean flags | 4-flag status / interrupt mask |
| `0x20` | `*DAT_1400ea7c = byte & 0xF` | Stores low nibble at one byte-pointer | Generic 4-bit value (2nd channel) |
| `0x30` | 2 fields: `DAT_1400ea88` = bit 3 (1-bit flag), `*pbVar2 = byte & 7` (3-bit value) | 1-bit + 3-bit composite | Mode-select + level (e.g. squelch on/off + level 0-7) |
| `0x40` | 2 bit-pointers: `DAT_1400eaa4 = bit 1`, `*pbVar6 = bit 0` | 2-flag status | Power state, charge state, etc. |
| `0x50` | `*DAT_1400eaa0 = byte & 1` | Stores bit 0 in a single boolean | Single-flag toggle (e.g. RX mute) |

Opcodes `0x60`-`0xFF` are **unhandled** - the decoder falls through and
discards them. Either MAIN never sends these or they're reserved. (Or
the SUB has additional opcode handlers in another function we haven't
mapped yet - worth checking.)

### Path B: byte-streaming for command forwarding (`FUN_140068a4` → `FUN_14008340`)

Bytes received on a different channel (likely USART2 in raw-stream
mode, or an alt source - the decompile is ambiguous and uses
`FUN_1400e8b4(1, ...)` which we haven't fully mapped) are passed into
**`FUN_14008340(channel=1, byte)`**, which has three accumulator
state machines:

| Accumulator state | Counter at | Threshold | Fires | Likely role |
|---|---|---:|---|---|
| A | `*DAT_1400841c` | 5 bytes | `FUN_14006328()` + `FUN_1400640c(buf, x)` | 5-byte framed command from MAIN |
| B | `*DAT_14008424` | 5 bytes | `FUN_1400ae00()` + `FUN_1400ae0c(x, base)` | second 5-byte channel (likely a different command class) |
| C | `*DAT_1400842c` | 2 bytes | `FUN_14006328()` + `FUN_1400615c()` | 2-byte short-form command |

When **none** of the accumulators is currently filling, a fresh byte
gets stored at `*DAT_14008420` (the channel ID register) and an
internal jumptable is consulted. The Ghidra decompile mis-recovered
this jumptable as a 76-entry dispatch table at `DAT_14008428`, but the
target address `0x1001319C` is actually a region of concatenated
printf format strings, not (byte, fn-ptr) entries. The actual
purpose of this code is to **start one of the three accumulator
state machines** based on the first byte of the framed command.

A special-case at the top: if the byte is `0x52` (`'R'`), it bypasses
all three state machines and jumps directly to `*DAT_14008440` - the
SRAM function pointer at `0x10007145` (after Thumb-bit strip:
`0x10007144`, mapping to flash `0x14007144`). This is likely a
**"reset / resync"** byte that re-initialises all three accumulators
to a known state.

## Layer 1: byte-level TX framing (`FUN_1400eafc`)

```c
int FUN_1400eafc(undefined4 chan, byte *buf, int len) {
    while (len-- > 0) {
        while ((LSR & THRE_MASK) == 0);    // poll THRE bit (LSR<<26 sign)
        *USART_DATA = *buf++;
    }
    return len;
}
```

Pure synchronous write loop. No timeout, no retry, no CRC. The PHY
provides reliability via 8N1 line discipline; the protocol layer
provides reliability via opcode classes that each fully overwrite a
single state slot, so a missed byte at most temporarily desyncs.

## Layer 2: framing summary

There are **three concurrent framings** on USART2:

1. **Class-byte control** (path A above). Each byte is a complete
   command. No length, no CRC. Used for low-rate state notifications
   (e.g. "battery low", "RX squelch open", "RF gain auto-set to 4").
2. **5-byte commands** via accumulator A (path B). Format unknown -
   need to decompile `FUN_1400640c` (340 bytes) and `FUN_1400ae0c`
   (306 bytes) to find out. Likely: 1-byte opcode + 4-byte payload
   (e.g. frequency in Hz, big-endian).
3. **2-byte commands** via accumulator C (path B). Likely: 1-byte
   opcode + 1-byte arg (e.g. simple "set foo to N").

The split between A/B (both 5-byte) and C (2-byte) is sized for the
two payload-size classes of the underlying use cases:

- Frequency / dB / numeric arguments -> A or B
- Quick state writes / acks -> C

## Layer 3: command/response semantics (TBD - requires MAIN MCU dump)

We don't have the MAIN firmware. The SUB-side decoder tells us **what
gets received**, but the MAIN-side **emitter** (which would tell us
the human meaning of each opcode and payload bit) lives on a
different MCU whose flash we haven't extracted.

Open questions for Phase 7 (MAIN MCU dump):

- Which class-byte (path A) opcode means "battery state", which means
  "RF gain", which means "PTT", etc.?
- What's in the 5-byte payloads on accumulator A vs B? Is one of
  them frequency? squelch threshold? volume?
- Is the 2-byte form (accumulator C) a request/ack pair, or two
  independent low-rate commands?
- What does the `'R'` (0x52) reset byte actually do at the MAIN end?

## Open empirical follow-ups

These don't need MAIN flash; they can be done with `_probe_batch.py`
and a USART2 logic-analyser tap (the latter requires opening the
scanner case):

1. **Wake / sleep:** does sending bytes on COM3 keep USART2 traffic
   flowing during display sleep, or does the SUB reduce its TX rate?
   Capture a 30-second baseline + 30-second post-sleep.
2. **Reset byte (`'R'`):** send `R\r` on COM3 (it falls through the
   lowercase parser and lands in `FUN_14008340`). Observe whether the
   SUB visibly resyncs or gets cranky.
3. **Class-byte fuzzing:** the SUB decoder consumes bytes 0x60-0xFF
   silently. If we could **inject** these on USART2 (which requires
   a soldering pad), we'd see whether MAIN ever uses them. Probably
   it does for vendor commands we haven't seen.

## Cross-reference

- [`firmware/decompiles/1400e9e0_FUN_1400e9e0.json`](firmware/decompiles/1400e9e0_FUN_1400e9e0.json) - USART2 RX class decoder
- [`firmware/decompiles/1400eafc_FUN_1400eafc.json`](firmware/decompiles/1400eafc_FUN_1400eafc.json) - USART2 TX
- [`firmware/decompiles/14008340_FUN_14008340.json`](firmware/decompiles/14008340_FUN_14008340.json) - byte-stream framer
- [`firmware/decompiles/140068a4_FUN_140068a4.json`](firmware/decompiles/140068a4_FUN_140068a4.json) - channel-1 byte feeder
- [`firmware/decompiles/1400e57c_FUN_1400e57c.json`](firmware/decompiles/1400e57c_FUN_1400e57c.json) - 4-USART init (baud, LCR)
- [`firmware/decompiles/1400eb24_FUN_1400eb24.json`](firmware/decompiles/1400eb24_FUN_1400eb24.json) - USART2-specific GPIO/SCU mux
