# RE: Inter-MCU Bus (USART2)

> Where this fits: how the SUB MCU and MAIN MCU talk to each other
> inside the scanner. Derived entirely from static analysis of the
> SUB firmware (the MAIN side is encrypted, so the protocol's
> human meaning is partial). For the consolidated narrative start
> at [Reverse Engineering](Reverse-Engineering).

## Status

| Layer | What we know | Source |
|---|---|---|
| **0 (physical)** | USART2, 115200/8N1, no flow control, FIFO + DMA on RX, PIO on TX, internal routing | SUB firmware decompile |
| **1 (byte-level RX)** | Two parallel paths: nibble-class control protocol (6 opcode classes) + byte-streaming command framer (3 accumulators) | SUB firmware decompile |
| **1 (byte-level TX)** | Pure synchronous THRE-poll write loop | SUB firmware decompile |
| **2 (framing)** | Three concurrent framings: 1-byte class, 5-byte commands, 2-byte commands | Inferred from accumulator state machines |
| **3 (semantics)** | TBD - which class-byte means which event ("battery low" vs "RF gain auto-set" vs ...) | **Needs MAIN MCU dump or live USART2 capture** |

## Layer 0: Physical

| Property | Value | Where in the SUB decompile |
|---|---|---|
| Bus carrier | LPC43xx **USART2** (NXP USART block) | `FUN_1400eb24` (USART2-specific GPIO/SCU init), `FUN_1400e57c` (multi-USART init) |
| Baud rate | **115200** (`0x1c200` divisor) | `FUN_1400e57c`: `FUN_1400fd40(iVar3, 0x1c200);` |
| Word format | **8N1** (LCR = 3) | `FUN_1400e57c`: `*(undefined4*)(iVar3 + 0xc) = 3;` |
| Flow control | None | LCR bits 6-7 untouched, no MCR config |
| FIFO | Enabled, default thresholds (FCR = 0x81 then 0xC7) | Standard NXP UART pattern |
| RX path | DMA (size 0x80 ring) | `FUN_1400fa74(...,0x20)` then `FUN_1400fa74(...,0x80)` |
| TX path | **PIO with THRE-poll** (no DMA on TX) | `FUN_1400eafc` polls `LSR.THRE` per byte |
| Init triggers | Called from `FUN_14010554` (USB device init) | USART2 comes online with USB |

USART2 in `FUN_1400eb24` is configured with GPIO + SCU writes that
**don't route to any external pin pad** - pin-mux ops set internal
oscillator + FIFO pin only. This confirms USART2 is SoC-internal:
the SUB and MAIN MCUs are wired together on the PCB and never
exposed externally.

## Layer 1: Byte-level RX framing

Two parallel byte-decode paths run on the SUB side, both pumped
from the same dispatcher (`FUN_1400df18`):

### Path A: Nibble-class single-byte protocol (`FUN_1400e9e0`)

This is the **primary inter-MCU control protocol**. Each byte is
self-contained. Top nibble = opcode class; low nibble = payload.

| Opcode (top nibble) | Decoder slot | Behaviour | Likely meaning |
|---:|---|---|---|
| `0x00` | `*DAT_1400eaac = byte` | Stores byte 0x00-0x0F at one byte-pointer | Generic 4-bit value (RF gain index, channel, register read result) |
| `0x10` | 4 bit-pointers `DAT_1400ea90/94/98/9c` = bit3/2/1/0 | Splits low nibble into 4 boolean flags | 4-flag status / interrupt mask |
| `0x20` | `*DAT_1400ea7c = byte & 0xF` | Stores low nibble | Generic 4-bit value (2nd channel) |
| `0x30` | `DAT_1400ea88` = bit 3 + `*pbVar2 = byte & 7` | 1-bit + 3-bit composite | Mode-select + level (e.g. squelch on/off + level 0-7) |
| `0x40` | `DAT_1400eaa4` = bit 1, `*pbVar6` = bit 0 | 2-flag status | Power state, charge state, etc. |
| `0x50` | `*DAT_1400eaa0 = byte & 1` | Single boolean | Single-flag toggle (e.g. RX mute) |

Opcodes `0x60`-`0xFF` are **unhandled** - the decoder falls through
and discards them. Either MAIN never sends those, or a sister
function we haven't mapped yet handles them.

### Path B: Byte-streaming command framer (`FUN_140068a4` → `FUN_14008340`)

A separate pipe feeds bytes into `FUN_14008340(channel, byte)`
which has **three accumulator state machines**:

| Accumulator | Counter | Threshold | Fires | Likely role |
|---|---|---:|---|---|
| A | `*DAT_1400841c` | 5 bytes | `FUN_14006328()` + `FUN_1400640c(buf, x)` | 5-byte framed command from MAIN |
| B | `*DAT_14008424` | 5 bytes | `FUN_1400ae00()` + `FUN_1400ae0c(x, base)` | Second 5-byte channel (different command class) |
| C | `*DAT_1400842c` | 2 bytes | `FUN_14006328()` + `FUN_1400615c()` | 2-byte short-form command |

When **none** of the accumulators is currently filling, a fresh byte
gets stored at `*DAT_14008420` and an internal jumptable selects
which accumulator state machine to start, based on the first byte.

A special-case at the top: if the byte is `0x52` (`'R'`), it
bypasses all three state machines and jumps directly to
`*DAT_14008440` - the SRAM function pointer at `0x10007145` (after
Thumb-bit strip, mapping to flash `0x14007144`). This is **likely a
"reset / resync" byte** that re-initialises all three accumulators
to a known state. Open empirical follow-up: send `R\r` on COM3 (it
falls through the lowercase parser into this path) and observe.

## Layer 1: Byte-level TX framing (`FUN_1400eafc`)

```c
int FUN_1400eafc(undefined4 chan, byte *buf, int len) {
    while (len-- > 0) {
        while ((LSR & THRE_MASK) == 0);    // poll THRE bit
        *USART_DATA = *buf++;
    }
    return len;
}
```

Pure synchronous write loop. No timeout, no retry, no CRC. The PHY
provides reliability via 8N1 line discipline; the protocol layer
provides reliability via opcode classes that each fully overwrite
a single state slot, so a missed byte at most temporarily desyncs.

## Layer 2: Framing summary

There are **three concurrent framings** on USART2:

1. **Class-byte control** (Path A above). Each byte is a complete
   command. No length, no CRC. Used for low-rate state notifications
   ("battery low", "RX squelch open", "RF gain auto-set to 4").
2. **5-byte commands** via accumulators A and B. Format unknown -
   needs decompile of `FUN_1400640c` (340 bytes) and `FUN_1400ae0c`
   (306 bytes). Likely 1-byte opcode + 4-byte payload (e.g.
   frequency in Hz, big-endian).
3. **2-byte commands** via accumulator C. Likely 1-byte opcode +
   1-byte arg ("set foo to N").

The split between A/B (both 5-byte) and C (2-byte) is sized for
the two payload-size classes:

- Frequency / dB / numeric arguments -> A or B
- Quick state writes / acks -> C

## Layer 3: Command/response semantics (TBD)

We don't have the MAIN firmware. The SUB-side decoder tells us
**what gets received**, but the MAIN-side **emitter** (which would
tell us the human meaning of each opcode and payload bit) lives on
a different MCU whose flash we haven't extracted (and almost
certainly can't, given it's encrypted).

Open questions for a future "Phase 7":

- Which class-byte (Path A) opcode means "battery state", which
  means "RF gain", which means "PTT", etc.?
- What's in the 5-byte payloads on accumulator A vs B? Is one of
  them frequency? Squelch threshold? Volume?
- Is the 2-byte form (accumulator C) a request/ack pair, or two
  independent low-rate commands?
- What does the `'R'` reset byte actually do at the MAIN end?

## Open empirical follow-ups (don't need MAIN flash)

These can be done with `_probe_batch.py`
and (for the bus tap) a USART2 logic-analyser on the PCB:

1. **Wake / sleep**: does sending bytes on COM3 keep USART2 traffic
   flowing during display sleep, or does the SUB reduce its TX
   rate? Capture a 30 s baseline + 30 s post-sleep.
2. **Reset byte (`'R'`)**: send `R\r` on COM3 and observe whether
   the SUB visibly resyncs or gets cranky.
3. **Class-byte fuzzing**: the SUB decoder consumes bytes
   `0x60`-`0xFF` silently. If we inject these on USART2 (requires
   a soldering pad), we'd see whether MAIN ever uses them. Probably
   does for vendor commands we haven't seen.

## Cross-reference (decompiles)

All under `Metacache/Dev/RE/firmware/decompiles`:

- `1400e9e0_FUN_1400e9e0.json` - USART2 RX class decoder (Path A)
- `1400eafc_FUN_1400eafc.json` - USART2 TX (THRE-poll loop)
- `14008340_FUN_14008340.json` - byte-stream framer (Path B)
- `140068a4_FUN_140068a4.json` - channel-1 byte feeder
- `1400e57c_FUN_1400e57c.json` - 4-USART init (baud, LCR)
- `1400eb24_FUN_1400eb24.json` - USART2-specific GPIO/SCU mux
