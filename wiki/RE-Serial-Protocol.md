# RE: Serial Protocol

> Where this fits: the live command surface exposed when the SDS100
> is in **Serial mode**. Sentinel never enters Serial mode, so
> everything on this page is "extra surface our app gets that
> Sentinel doesn't". For the consolidated narrative start at
> [Reverse Engineering](Reverse-Engineering).

In Serial mode the SDS100 exposes two USB CDC virtual COM ports
(see [RE-USB-Modes](RE-USB-Modes)). They are **not interchangeable**:
each routes to a different MCU and runs a different protocol.

| Port | PID | MCU | Protocol surface |
|---|---|---|---|
| `COM4` | `0x001A` | MAIN | Documented Uniden Remote Command Protocol (V1.02 + V2.00 + BCDx36HP V1.05 inheritance) plus undocumented argument variants |
| `COM3` | `0x0019` | SUB | Identity (`MDL`/`VER`) + 13 single-character DSP/RF debug commands. Most documented mnemonics return nothing on this port. |

Throughout this page, port labels mean **which MCU**, not which
specific COM number Windows assigned. Detect the port by PID, not
COM number.

## MAIN port (PID 0x001A) - the documented surface

### Authoritative specs

| Spec | Date | Where it lives |
|---|---|---|
| BCDx36HP V1.05 | 2017-11-13 | `Metacache/Dev/RE/BCDx36HP_RemoteCommand_Specification_V1_05.txt` |
| SDS V1.02 | 2023-12-22 | (mirrored in repo) |
| SDS V2.00 | 2025-07-07 | (mirrored in repo) |

The SDS V2.00 spec adds 4 commands (`POF`, `GCS`, `GW2`, `KAL`)
relative to V1.02 and formalises `VOL`/`SQL` as #33/#34. The
BCDx36HP V1.05 spec documents extra `GLT,*` subforms not in either
SDS spec - some of which **still work on SDS100 firmware** despite
not being documented for the SDS line.

### Read-only commands working on SDS100 FW 1.26.01

| Cmd | Spec # | Yields | Notes |
|---|---|---|---|
| `MDL` | V1.02 #1 | `MDL,SDS100\r` | Model fingerprint - canonical |
| `VER` | V1.02 #2 | `VER,Version 1.26.01\r` | MAIN firmware version |
| `STS` | V1.02 #5 | 833-byte LCD scrape | Includes 14-bit status flag field, full menu state |
| `FQK` | V1.02 #9 | 100-slot Favorites Quick Key state mask | |
| `GSI` | V1.02 #13 | Full XML scanner state | **Single best command for live mirror** - replaces STS |
| `GLT,FL` | V1.02 #14 | Favorites List index | |
| `GLT,FTO` | V1.02 #14 | All 32 fire-tone-out channels (3 paginated pages) | |
| `GLT,CS_BANK` | V1.02 #14 | All 10 custom-search banks (2 pages) | |
| `GLT,AFREQ` | V1.02 #14 | Search Avoiding Frequencies | |
| `GLT,IREC_FILE` | V1.02 #14 | Inner-record files | |
| `GLT,UREC` | V1.02 #14 | User-record folders | **firmware quirk**: returns FL list when no UREC folders exist (FW 1.23.07 + 1.26.01) |
| `GLT,TRN_DISCOV` | V1.02 #14 | Trunk discovery sessions | |
| `GLT,CNV_DISCOV` | V1.02 #14 | Conventional discovery sessions | |
| `SVC` | V1.02 #17 | 47-slot mask: 37 PST + 10 CST | |
| `DTM` | V1.02 #19 | `DTM,1,2026,4,27,17,51,38,1\r` (DST flag, RTC OK flag) | |
| `LCR` | V1.02 #20 | `LCR,<LAT>,<LON>,10.0\r` (lat/lon/range) | **Wiped to zeros after firmware update** (RE Session 4 finding) |
| `MSI` | V1.02 #25 | Menu state XML; "TypeError" empty when not in menu | |
| `GST` | V1.02 #28 | LCD + Waterfall extras | |
| `VOL` | V2.00 #33 | `VOL,0\r` | Was BCDx36HP-era ghost; promoted in V2.00 |
| `SQL` | V2.00 #34 | `SQL,0\r` | Was BCDx36HP-era ghost; promoted in V2.00 |
| `GLG` | BCDx36HP | 12-field reception info | Mostly empty when idle; populated during active RX |
| `PWR` | BCDx36HP | `PWR,-76,08531875\r` (RSSI dBm, freq * 10000) | |

### Undocumented but-working commands (Phase 2/3 finds)

| Cmd | Source | Behavior |
|---|---|---|
| `GLT,SYS` | BCDx36HP V1.05 | Returns SYS list **without an FL index** - undocumented in SDS spec, works on FW 1.26.01 |
| `GSI,XML` | Phase 2 | Same as bare `GSI`; argument silently ignored |
| `GSI,RAW` | Phase 2 | Same as bare `GSI`; argument silently ignored |
| `GSI,PROP` | Phase 2 | Same as `GSI` plus a `SAD` attribute on `<SiteFrequency>` |
| `GSI,FULL` | Phase 2 | Synonym of `GSI,PROP` |
| `GSI,XML,?` | Phase 2 | Returns "no department/TGID resolved" view (Index="4294967295") |

### `,?` form semantics

Sending `cmd,?` yields one of two outcomes:

- `cmd,OK` -> the command has a write form. Observed for `VOL,?`
  and `SQL,?` (legacy BCDx36HP-era syntax that the modern firmware
  still honours).
- `cmd,ERR` -> the command has no write form. **Even spec
  Get/Set commands `SVC,?`/`DTM,?`/`LCR,?`/`FQK,?` return ERR**
  because the modern SDS commands accept their write form directly,
  without the `,?` handshake.

This is a non-mutating probe and our app never escalates `,?` to a
real write.

### GSI XML payload structure

`GSI` is by far the highest-value MAIN command. It returns the
**entire scanner state** as a typed XML attribute layout that's
trivial to parse. Sample (active P25 RX on <AGENCY>,
FW 1.26.01):

```xml
<ScannerInfo Mode="Trunk Scan" V_Screen="trunk_scan">
  <MonitorList Name="Home" Index="2" ListType="FL" Q_Key="0" N_Tag="None" DB_Counter="0" />
  <System Name="<TRUNK_SYSTEM>" Index="6"
          Avoid="Off" SystemType="P25 Trunk" Q_Key="0" N_Tag="None" Hold="Off" />
  <Department Index="4294967295" Avoid="Off" Q_Key="0" Hold="Off" />
  <TGID Name="A1 Primary" Index="54" Avoid="Off" TGID="TGID:2057"
        SetSlot="Slot Any" RecSlot="Slot None" N_Tag="None"
        Hold="Off" SvcType="Law Dispatch" P_Ch="Off" LVL="0" />
  <UnitID Name="UID:34112" U_Id="UID:34112" />
  <Site Name="Simulcast" Index="9" Avoid="Off" Q_Key="None" Hold="Off" Mod="NFM" />
  <SiteFrequency Freq=" 853.312500MHz" IFX="Off" SAS="NAC 4D2h" SAD="NAC 4D2h" />
  <DualWatch PRI="Off" CC="Off" WX="Off" />
  <Property F="Off" VOL="0" SQL="0" Sig="5" Att="Off" Rec="Off"
            KeyLock="Off" P25Status="P25" Mute="Mute" Backlight="100"
            A_Led="Off" Dir="Up" Rssi="-75" />
  <ViewDescription>
    <OverWrite Text="ID Scanning..." />
  </ViewDescription>
</ScannerInfo>
```

The `<Property>` element alone delivers VOL, SQL, Sig, Att, Rec,
KeyLock, P25Status, Mute, Backlight, A_Led, Dir, Rssi - the
entire status-bar of the live UI.

### Pagination of GLT responses

GLT subforms larger than ~11 records arrive as **multiple back-to-back
XML chunks** in a single response burst. Each chunk is a complete
XML document terminated by `<Footer No="N" EOT="0|1"/>`:

- `EOT="0"` = more pages coming
- `EOT="1"` = last page

A consumer must concatenate (e.g. `<FTO>`) elements across chunks
and stop when it sees `EOT="1"`. The scanner streams pages
automatically; we don't request them.

### Confirmed-vestigial mnemonics

These BCDx36HP-era commands consistently return `ERR` on SDS100
across all firmware versions we tested. We keep them in our probe
list as **regression markers** - if any of them ever starts
responding, that's a firmware change worth documenting.

```
RSI  BAV  BLT  CNT  DMA  SCN  CBP  CSP  LOC  GIN,GPS  CLK
OMS  BLI  MEM  PRI  ALT  GID  NTG  WFL  FAV  RLG
```

The V2.00 spec commands `GCS` (charge status) and `KAL` (keep alive)
both **error on SDS100 FW 1.26.01** even though the spec lists
them. They may be SDS200/SDS150-only, or aspirational.

### MAIN-port commands we never send (FORBIDDEN)

Hard-coded in `serial_probe.py`:

```
KEY  PRG  EPG  CLR  JNT  JPM  WPL  WPS  DLA  MEMSET  WIPE
TGW  VLO  SLO  GLT (bare write form)  RST,SET  POF  GW2  GWF  BFH
```

These either mutate state or are entry points to programming mode.
**Never send any of these from any code path - even with `,?`.**

> **GUI exception for `KEY` (deliberate).** The above rule governs the
> read-only RE *probe* tooling. The desktop app's Live (Serial Mode)
> dock intentionally drives the **full keypad** via `KEY,<code>,<mode>`
> so the user can operate the scanner from the PC exactly like the
> physical buttons (ProScan-style virtual scanner). This is funneled
> through the validated `SerialMainDriver.send_key` path (whitelisted
> against the V2.00 key-code sheet, `KEYPAD_KEYS`); the generic
> read-only `send_query` path still rejects `KEY` outright. Probes
> remain read-only.

## SUB port (PID 0x0019) - 13 debug commands + identity

The SUB port is documented by Uniden... not at all. The Uniden
specs cover the MAIN port only. Everything below was discovered
empirically and confirmed by static RE of the SUB firmware.

### Discovery methodology

1. **Phase 1**: alphabet attack with `sub_probe.py` - send single
   chars A-Z, two-letter combos, targeted three-letter combos.
   Found `U` (returns `U5C42\r\x00<2 binary bytes>`) and identified
   the prefix-fallback identity behaviour (`MA`->`SDS100-SUB`,
   `VA`->version).
2. **Phase 6**: extracted SUB firmware
   (`Metacache/Dev/RE/firmware/sub_1.03.15_inflated.bin`),
   imported into Ghidra, decompiled the parser at `FUN_14006ca6`.
   The parser uses a per-character `cmp #imm8` chain - no string
   table - so the only way to enumerate is to read the chain.
3. **Round 4**: live-falsified all 13 candidate mnemonics on COM3.
   11 HIT + 2 silent toggle, matching the decompile exactly.

### Identity commands

| Cmd | Response | Mechanism |
|---|---|---|
| `MDL` | `SDS100-SUB\r` × 4 | Per-character compare in `FUN_14006ca6` |
| `VER` | `Version 1.03.15 \r` × 4 | Per-character compare in `FUN_14006ca6` |

The 4× echo is the canonical "command understood" pattern. The
buffered-fifo behaviour also produces:

- **Prefix fallback**: any input starting with `M` returns N copies
  of `SDS100-SUB\r`; anything starting with `V` returns N copies
  of `Version 1.03.15 \r`. So `MA, MB, ..., MZ, MIXG` are all the
  same fallback path, NOT distinct commands.
- **Buffer leakage**: an unrecognised command sometimes returns the
  *previous* successful response. Use anchor-and-compare technique
  (send `MDL` between probes) to detect this.

### The 13 single-character debug commands

All parsed by `FUN_14006ca6` via `cmp #imm8` ladder. First match
wins. From the `sub_command_dispatch.md`
table:

| Char | Hex | Handler | Response shape | Likely DSP/RF role |
|:---:|:---:|---|---|---|
| `o` | 0x6F | `FUN_1400692c` | 2.2 KB ASCII, 512 records `<adc>\r<adc>\r<bit>\r` | **DSP front-end ADC dump** (12-bit). Triple = `(channel_a, channel_b, status_bit)` |
| `q` | 0x71 | inline dump 0x100 from `*DAT_14006f70` | 1.3-1.5 KB, 256 lines int16 (-5071..+1491) | **DSP buffer A** - one channel of an I/Q stream |
| `w` | 0x77 | inline dump 0x100 from `*DAT_14006f78` | same shape as `q` | **DSP buffer B** - paired with `q` |
| `d` | 0x64 | `FUN_140069d0` | 5.5 KB, 512 records `<int16>,<int16>` | **Complex (I,Q) baseband samples** - q+w interleaved |
| `r` | 0x72 | inline dump 0x400 from `*DAT_14006f7c` | 1.6 KB, 256 lines int16 (full ±32767 range) | **Audio or post-filter samples** |
| `m` | 0x6D | inline 0x100 + 0x300 zero-pad from `*DAT_14006f80` | 2.9 KB, 1024 lines int16 with `32767` markers | **FFT magnitude / spectrum** (peak markers) |
| `z` | 0x7A | `FUN_14006a64` | 1.9 KB, 256 lines int16 (-12185..+19366) | **Accumulator / state dump** |
| `h` | 0x68 | inline 4-buffer composite | 128 + 16 paired-column rows: header + `H, %ld, %ld\r` | **Confirmed streaming command** - DSP register/counter monitor |
| `l` | 0x6C | inline conditional dump | 79 KB, 2051 lines `(float, float, int)` | **Largest dump: log buffer** (hits or DSP events) |
| `s` | 0x73 | `FUN_14006c00` | 42 B, two copies of `0, 198, 4, 8, 0, 0` | **Compact stats counters** - probable packet/frame count |
| `t` | 0x74 | `*DAT_14006f68 ^= 1` | (silent, 2 s timeout) | **Silent toggle**: flips a 1-bit mode flag |
| `u` | 0x75 | `*DAT_14006f68 = (==2 ? 0 : 2)` | (silent, 2 s timeout) | **Silent toggle**: flips a different bit of the same flag |
| `v` | 0x76 | inline 2-buffer dump | 5.2 KB, 256 records `<int32>, <int32>` | **Wide-precision dual-stream** (32-bit, accumulated phase / freq deviation) |

The `t` and `u` flags are 3-state: 0 / 1 / 2. They likely control
the format of the other dumps - `q`/`r`/`m` may emit different
formats per mode. Sweeping `(mode, command)` combinations is one
of the open follow-ups.

### Anything else on the SUB port

The remainder of the lowercase ladder doesn't match. After the
ladder, any unmatched byte (uppercase, digit, `\r`, etc.) is
forwarded to `FUN_14008340(channel=4, byte)`, which feeds the
inter-MCU forwarding path - i.e. the byte travels over USART2 to
MAIN. So sending `STS\r` on COM3 doesn't error; it just ends up
on MAIN, which doesn't recognise STS coming from that direction
either. The result: silence.

`U` (uppercase) is special - it returns the 9-byte
`U5C42\r\x00<2 binary bytes>` response. It's outside the lowercase
ladder; almost certainly a non-printf register-read code path
emitting bytes directly. Not yet decompiled in detail.

### 35 untriggered SUB format strings

The SUB firmware contains 35 `printf`-style format strings with
no commands found yet that trigger them. Sample (full list in
`Metacache/Dev/RE/docs/SDS100_unofficial_commands.md`):

```
Manual LNAGain1,%d, LNAGain2,%d, MixerGain,%d, ADC_P-P,%d
RF_GainMode,MANUAL  /  RF_GainMode,AUTO
dBm,%d,LNAGain1,...,Max,%d, ADC_P-P,%d
IfRssi,%d  /  RssiDbm,%d
LNAGain1,%d  /  LNAGain2,%d  /  MixerGain,%d
LNAGain1,Auto  (and analogues)
Noise Squelch,%6d
FFT_PEAK,%ddB  /  FFT_FREQ,%d
FIR2_Range,%d, %ddB
NCO_Range,min=%6d, max=%6d, dif=%6d
CIC OUT min,%6d, max=%6d, err=%6d
FIR1 OUT  /  FIR2 OUT min,...,err=%6d
Widest LPF, %d  /  Narrowest LPF, %d  /  LPF, %d  /  Default LPF, %d
IF=%d, STD= %s
Window,%d
VGA Mode Manual,%d
REG[%2d],%02X, REG[%2d],%02X, REG[%2d],%02X, REG[%2d],%02X
R840_FM  /  R840_DVB_T2_1_7M
S%02X%04X%04X%04X%04X%01X%04X
```

These are likely the alt-mode outputs of the existing `q`/`r`/`m`
commands (different format depending on `*DAT_14006f68`'s value).
Mode-sweep enumeration is open.

## How our app uses both ports together

| Use case | Port | Command(s) |
|---|---|---|
| Detect which scanner is connected | MAIN | `MDL` |
| Show live tuning/RSSI/signal in the UI | MAIN | `GSI` (poll every 100-500 ms) |
| Show "current activity / hits" feed | MAIN | `GLG` (poll during RX) |
| Show waterfall data in our UI | SUB | `m` (FFT magnitude) - bypasses Sentinel and MAIN's `GWF` toggle |
| Show ADC peak-to-peak meter | SUB | `o` |
| Audio-level oscilloscope | SUB | `r` |
| Diagnostic log dump | SUB | `l` |
| Detect destructive commands | n/a | Whitelist + forbidden list in our probe scripts |

## Lab data

- `Metacache/Dev/RE/docs/SDS100_unofficial_commands.md` - the canonical command catalog with safety classes, sources, and full notes.
- `Metacache/Dev/RE/docs/sub_command_dispatch.md` - SUB-side dispatch table from the decompile.
- `Metacache/Dev/RE/tools/probes/serial_probe.py` - safe MAIN-port probe with whitelist + forbidden list.
- `Metacache/Dev/RE/tools/probes/sub_probe.py` - SUB-port probe (alphabet attack with anchor-and-compare).
- `Metacache/Dev/RE/tools/probes/probe_batch.py` - batch probe driver with full-response capture.
- `Metacache/Dev/RE/tools/probes/verify_dispatch.py` - live falsification of Ghidra-predicted mnemonics.
- `Metacache/Dev/RE/sessions` - timestamped raw probe captures.
