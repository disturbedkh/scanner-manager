# RE: Serial Protocol

> Status: shipped (v0.11.x) — read-only catalog; live-serial UI backlog.

> Where this fits: live command surface in **Serial mode**. Sentinel
> never enters Serial — everything here is extra surface our app gets.
> Start at [Reverse Engineering](Reverse-Engineering).

## What this answers

Which commands work on MAIN vs SUB CDC ports, what is safe to probe,
and where the full mnemonic catalog lives in the lab (this page
summarizes; it does not paste every response dump).

## Known vs OPEN

| Topic | State | Notes |
|---|---|---|
| MAIN read-only surface (V1.02 + V2.00 + inheritance) | DONE | FW 1.26.01 verified |
| Undocumented `GLT,SYS` / `GSI,PROP|FULL` | DONE | Phase 2/3 |
| Vestigial / V2.00-only ERR mnemonics | DONE as regression markers | `GCS`/`KAL` ERR on SDS100 |
| SUB 13-char dispatch + MDL/VER | DONE | Decompile + live falsify |
| 35 untriggered SUB format strings | OPEN | Likely `t`/`u` mode alts |
| Mode-sweep (`t`/`u` × dump cmds) | OPEN | |
| GLG full schema across modulations | OPEN | Need busy RX captures |
| STS 14-bit flag decode | OPEN | Toggle-and-diff |

## Deep dive

In Serial mode the SDS100 exposes two USB CDC ports
([RE-USB-Modes](RE-USB-Modes)). Detect by **PID**, not COM number.

| Role | PID | MCU | Protocol |
|---|---|---|---|
| MAIN | `0x001A` | MAIN | Documented Uniden Remote Command Protocol + undocumented variants |
| SUB | `0x0019` | SUB | Identity + 13 single-char DSP/RF debug commands |

### MAIN port — documented surface

**Authoritative specs** (under `Metacache/Dev/RE/specs/`):

| Spec | Date | Path |
|---|---|---|
| BCDx36HP V1.05 | 2017-11-13 | `specs/BCDx36HP_RemoteCommand_Specification_V1_05.txt` (+ `.pdf`) |
| SDS V1.02 | 2023-12-22 | `specs/SDS200_RemoteCommand_Specification_V1_02.txt` (+ `.pdf`) |
| SDS V2.00 | 2025-07-07 | `specs/SDS_Series_RemoteCommand_Specification_V2_00.txt` (+ `.pdf`) |

V2.00 adds `POF`, `GCS`, `GW2`, `KAL` and formalises `VOL`/`SQL`.
BCDx36HP V1.05 documents extra `GLT,*` subforms — some still work on
SDS100 despite not being in the SDS specs.

**High-value read-only commands** (FW 1.26.01): `MDL`, `VER`, `STS`,
`FQK`, `GSI` (best live mirror), `GLT,*` family, `SVC`, `DTM`, `LCR`,
`MSI`, `GST`, `VOL`, `SQL`, `GLG`, `PWR`. Full response shapes and
quirks (e.g. `GLT,UREC` returning FL when empty; `LCR` wiped after
MAIN update) live in the lab catalog — do not treat this wiki table
as complete.

**Undocumented-but-working:** `GLT,SYS`; `GSI,XML|RAW` (ignored args);
`GSI,PROP` / `GSI,FULL` (adds `SAD` on `<SiteFrequency>`);
`GSI,XML,?` (unresolved Index view).

**`,?` form:** `OK` ⇒ write form exists (e.g. `VOL,?`); `ERR` ⇒ no
`,?` handshake (even some Get/Set cmds). Probes never escalate `,?`
to a real write.

**GLT pagination:** multi-chunk XML with `<Footer No="N" EOT="0|1"/>`;
concatenate until `EOT="1"`.

**Vestigial / ERR markers** (keep in probes for regression):
`RSI BAV BLT CNT DMA SCN CBP CSP LOC GIN,GPS CLK OMS BLI MEM PRI ALT
GID NTG WFL FAV RLG`. Spec-listed `GCS` / `KAL` also ERR on SDS100
1.26.01 (may be SDS200/150-only).

**FORBIDDEN (probes never send):**
`KEY PRG EPG CLR JNT JPM WPL WPS DLA MEMSET WIPE TGW VLO SLO GLT`
(bare write) `RST,SET POF GW2 GWF BFH`. Hard-coded in
`tools/probes/serial_probe.py`.

> **GUI exception for `KEY`:** Live dock may send
> `KEY,<code>,<mode>` via `SerialMainDriver.send_key` (whitelisted
> key codes). Generic `send_query` and all RE probes still reject
> `KEY`.

`GSI` returns full scanner state as XML (`<Property>` alone covers
VOL/SQL/Sig/Rssi/…). Sample payloads: lab catalog.

### SUB port — 13 debug commands + identity

Undocumented by Uniden. Discovered via alphabet attack + Ghidra
parser `FUN_14006ca6` (`cmp #imm8` ladder) + live falsification.

| Cmd | Role (summary) |
|:---:|---|
| `MDL` / `VER` | Identity (`SDS100-SUB`, version); 4× echo; prefix fallback on `M*`/`V*` |
| `o` | ADC peak-to-peak dump |
| `q` / `w` | DSP buffer A / B (I/Q channels) |
| `d` | Interleaved I,Q |
| `r` | Audio / post-filter samples |
| `m` | FFT magnitude |
| `z` | Accumulator dump |
| `h` | Streaming `H, %ld, %ld` monitor |
| `l` | Large log buffer |
| `s` | Compact stats |
| `t` / `u` | Silent mode-flag toggles |
| `v` | 32-bit dual-stream |

Handler addresses, byte sizes, and response shapes:
`docs/sub_command_dispatch.md`. Unmatched bytes forward toward
USART2 (`FUN_14008340`). Uppercase `U` is a special binary path
(not fully decompiled). ~35 printf format strings remain untriggered
— likely alt modes of `t`/`u`.

### How our app uses both ports

| Use case | Port | Command(s) |
|---|---|---|
| Detect model | MAIN | `MDL` |
| Live UI mirror | MAIN | `GSI` poll |
| Activity feed | MAIN | `GLG` during RX |
| Waterfall / ADC / audio scope | SUB | `m` / `o` / `r` |
| Safety | n/a | Whitelist + forbidden list in probes |

## Lab pointers

| Path | Role |
|---|---|
| `Metacache/Dev/RE/docs/SDS100_unofficial_commands.md` | **SSOT** command catalog (safety classes, sources) |
| `Metacache/Dev/RE/docs/sub_command_dispatch.md` | SUB dispatch from decompile |
| `Metacache/Dev/RE/docs/sub_command_response_map.md` | Probe ↔ string correlation |
| `Metacache/Dev/RE/specs/` | Vendor Remote Command PDFs/TXTs |
| `Metacache/Dev/RE/tools/probes/serial_probe.py` | MAIN whitelist probe |
| `Metacache/Dev/RE/tools/probes/sub_probe.py` | SUB alphabet / format-string probe |
| `Metacache/Dev/RE/tools/probes/probe_batch.py` | Editable batch runner |
| `Metacache/Dev/RE/tools/probes/verify_dispatch.py` | Live-falsify Ghidra candidates |
| `Metacache/Dev/RE/sessions/` | Timestamped raw captures |
