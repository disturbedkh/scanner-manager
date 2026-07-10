# RE: Inter-MCU Bus (USART2)

> Status: shipped (v0.11.x) — Layers 0–2 from SUB decompile; Layer 3 OPEN.

> Where this fits: how SUB and MAIN talk inside the scanner. Derived
> from SUB static analysis (MAIN flash is encrypted). Start at
> [Reverse Engineering](Reverse-Engineering).

## What this answers

Physical link parameters and byte-level framing on the internal
USART2 bus — enough to reason about taps and hypotheses — and what
is still unknown without MAIN-side semantics.

## Known vs OPEN

| Layer | What we know | State |
|---|---|---|
| **0 (physical)** | USART2, 115200/8N1, no FC, FIFO+DMA RX, PIO TX, internal routing | DONE |
| **1 (RX)** | Nibble-class control (6 opcode classes) + 3-accumulator byte framer | DONE |
| **1 (TX)** | Synchronous THRE-poll write loop | DONE |
| **2 (framing)** | 1-byte class, 5-byte cmds (×2), 2-byte cmds | DONE (inferred) |
| **3 (semantics)** | Human meaning of opcodes / payloads | **OPEN** — needs MAIN dump or live USART2 capture |

## Deep dive

### Layer 0: Physical

| Property | Value | Decompile anchor |
|---|---|---|
| Bus | LPC43xx **USART2** | `FUN_1400eb24`, `FUN_1400e57c` |
| Baud | **115200** (`0x1c200`) | `FUN_1400fd40(..., 0x1c200)` |
| Format | **8N1** (LCR = 3) | |
| Flow control | None | |
| RX | DMA ring size 0x80 | |
| TX | PIO, poll `LSR.THRE` | `FUN_1400eafc` |
| Init | From USB device init `FUN_14010554` | Comes up with USB |

Pin-mux does **not** route to an external pad — SoC-internal wiring
between SUB and MAIN.

### Layer 1: RX — Path A (nibble-class, `FUN_1400e9e0`)

Primary control protocol: each byte self-contained. Top nibble =
opcode class; low nibble = payload.

| Opcode | Behaviour (summary) |
|---:|---|
| `0x00` | Store 4-bit value |
| `0x10` | Split low nibble → 4 boolean flags |
| `0x20` | Store low nibble (2nd channel) |
| `0x30` | 1-bit flag + 3-bit level |
| `0x40` | 2-flag status |
| `0x50` | Single boolean |
| `0x60`–`0xFF` | Unhandled / discarded (or unmapped sister decoder) |

### Layer 1: RX — Path B (byte-stream framer, `FUN_14008340`)

Three accumulators:

| Acc | Threshold | Likely role |
|---|---:|---|
| A | 5 bytes | Framed command class 1 |
| B | 5 bytes | Framed command class 2 |
| C | 2 bytes | Short-form command |

Fresh first byte selects which machine to start. Special case:
byte `0x52` (`'R'`) bypasses accumulators → likely reset/resync
(SRAM fn ptr). Partial empirical test: send `R\r` on SUB CDC (falls
through lowercase parser into same framer).

### Layer 1: TX (`FUN_1400eafc`)

Pure synchronous write; no CRC. Reliability = 8N1 + opcode classes
that overwrite single state slots.

### Layer 2: Framing summary

1. **Class-byte control** — low-rate state notifications.
2. **5-byte commands** (A/B) — likely opcode + 4-byte payload
   (freq / numeric); handlers `FUN_1400640c` / `FUN_1400ae0c` not
   fully semanticized.
3. **2-byte commands** (C) — opcode + 1-byte arg.

### Layer 3: Semantics (OPEN)

Without MAIN emitter code we know **what SUB receives**, not the
human labels. Open questions: which class-byte is battery / RF gain /
PTT; contents of 5-byte payloads; whether C is request/ack; what
`'R'` does on MAIN.

### Empirical follow-ups (no MAIN flash required)

Use `Metacache/Dev/RE/tools/probes/probe_batch.py` and (for a true
bus tap) a USART2 logic analyser after PCB rework:

1. Wake/sleep USART2 traffic rate via side effects.
2. `'R'` resync behaviour from SUB CDC.
3. Class-byte fuzz `0x60`–`0xFF` only with a hardware inject pad.

## Lab pointers

| Path | Role |
|---|---|
| `Metacache/Dev/RE/docs/SDS100_inter_mcu_protocol.md` | **SSOT** bit-level lab write-up |
| `Metacache/Dev/RE/firmware/decompiles/` | `1400e9e0`, `1400eafc`, `14008340`, `140068a4`, `1400e57c`, `1400eb24`, … |
| `Metacache/Dev/RE/docs/sub_static_analysis.md` | Peripheral / string context |
| `Metacache/Dev/RE/tools/probes/probe_batch.py` | Hypothesis batch runner |
| `Metacache/Dev/RE/sessions/` | Empirical test notes |
