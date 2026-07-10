# RE: USB Modes

> Status: shipped (v0.11.x) — Mass Storage vs Serial mode reference.

> Where this fits: how the SDS100 presents itself to the host, and
> which surface (filesystem vs serial) each mode gives you. Start at
> [Reverse Engineering](Reverse-Engineering).

## What this answers

How to put the scanner into Mass Storage or Serial mode, what Windows
(or Linux) enumerates in each mode, and how scripts should detect
which mode is active — without hard-coding COM numbers.

## Known vs OPEN

| Topic | State | Notes |
|---|---|---|
| Dual-mode boot prompt | DONE | Lab: SDS100.md “How to enter Remote (Serial) Mode” |
| Mass Storage = FAT32 MSC | DONE | Sentinel’s only mode |
| Serial = two CDCs `0x0019` + `0x001A` | DONE | Detect by VID/PID |
| Simultaneous MSC + CDC | OPEN / not observed | Future “mass storage in serial mode” goal |
| Exact MSC interface PID | Varies | Identify via hub topology script |

## Deep dive

The SDS100 (and SDS200, SDS150, BCD436HP, BCD536HP, BT885 — the
BCDx36HP family) shows a **mode-select prompt** on the LCD when it
boots with USB connected. The user picks **once per session**.

Per lab (`docs/SDS100.md`, FW 1.23.07+):

- **Mass Storage** — pick Mass Storage from the boot prompt → SD as
  removable drive.
- **Serial** — period (`.` ) key on the keypad (or pick Serial) → two
  CDC ACM ports; SD volume disappears.

### Mass-Storage mode

| Question | Answer |
|---|---|
| How to enter | Pick **Mass Storage** at the USB boot prompt |
| Windows sees | Removable drive (e.g. `D:\`, `E:\`, `H:\`) |
| Filesystem | **FAT32** |
| Drive size (stock SDS100) | ~7.5 GiB (8 GB card) |
| Drive size (stock BT885) | ~3.6 GiB (4 GB card) |
| Volume label | none |
| What you can do | Mount, walk `BCDx36HP/`, read/write persistent files |
| What you cannot do | Live RSSI / scan state / CDC commands |
| Sentinel uses | **YES** — only mode |
| Our app uses | YES — SD edits and firmware drops |

**USB descriptor**: VID `0x1965`, Mass Storage Class. MSC PID can
vary; identify via hub that also enumerates CDCs `0x0019`/`0x001A`
when rebooted into Serial — see
`Metacache/Dev/RE/tools/automation/find_sds100_hub.ps1`.

### Serial mode

| Question | Answer |
|---|---|
| How to enter | Period (`.` ) key at boot prompt (FW 1.23.07+), or pick Serial |
| Windows sees | **Two** “USB Serial Device” entries |
| Identification | VID `0x1965`, PIDs `0x0019` (SUB) and `0x001A` (MAIN) |
| Visible filesystem | **none** |
| What you can do | MAIN Remote Command Protocol; SUB debug commands; live state |
| What you cannot do | SD file I/O |
| Sentinel uses | **NO** |
| Our app uses | YES — live mirror, GSI, RSSI, DSP introspection |

Ports are not interchangeable:

| Role | PID | MCU | Protocol |
|---|---|---|---|
| MAIN | `0x001A` | MAIN | Documented Uniden Remote Command Protocol + undocumented variants |
| SUB | `0x0019` | SUB | `MDL`/`VER` + 13 single-char DSP/RF debug commands |

Full catalogs: [RE-Serial-Protocol](RE-Serial-Protocol).

### Identifying which COM number is which PID

Windows assigns COM numbers semi-randomly. **Never assume**
`COM3 == SUB`. Prefer:

```powershell
Get-CimInstance Win32_PnPEntity |
  Where-Object { $_.DeviceID -match 'VID_1965' } |
  Select-Object Name, DeviceID
```

`PID_001A` = MAIN, `PID_0019` = SUB. Probes use the same logic via
`Metacache/Dev/RE/tools/probes/list_ports.py` (auto-detect; override
with `--port`).

### Mode signalling cheat sheet

| Topology you observe | Mode |
|---|---|
| Uniden VID `0x1965` MSC + removable FAT32 volume | Mass Storage |
| Two Uniden CDCs (`0x0019` + `0x001A`), no Uniden MSC | Serial |
| Neither | Off, cable out, or normal scan without USB mode |

Simultaneous MSC + CDC has **not** been seen on stock firmware
(parked future RE goal).

### Why the choice matters for our app

- **SD edits / firmware drops** → Mass Storage.
- **Live state / DSP / discovery probes** → Serial.
- Sentinel only ever uses Mass Storage; our app extends both.

## Lab pointers

| Path | Role |
|---|---|
| `Metacache/Dev/RE/docs/SDS100.md` | Boot-prompt / dual-CDC discovery notes |
| `Metacache/Dev/RE/tools/probes/list_ports.py` | VID/PID → COM map |
| `Metacache/Dev/RE/tools/automation/find_sds100_hub.ps1` | USBPcap interface via hub topology |
| `Metacache/Dev/RE/README.md` | Probe safety + Serial-mode prerequisites |
| `Metacache/Dev/RE/sessions/` | Timestamped `list_ports` / probe captures |
