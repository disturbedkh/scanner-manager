# RE: USB Modes

> Where this fits: how the SDS100 presents itself to the host PC,
> and which surface (filesystem vs serial) you get from each mode.
> For the consolidated narrative start at
> [Reverse Engineering](Reverse-Engineering).

The SDS100 (and SDS200, SDS150, BCD436HP, BCD536HP, BT885 -
the entire BCDx36HP family) shows a **mode-select prompt** on the
LCD when it boots while connected over USB. The user picks **once
per session** between two mutually-exclusive modes.

## Mass-Storage mode

| Question | Answer |
|---|---|
| How to enter | Hold the dot/period key on the keypad while powering on, OR pick "Mass Storage" from the boot prompt |
| Windows sees | Removable drive (e.g. `D:\`, `E:\`, `H:\`) |
| Filesystem | **FAT32** |
| Drive size on a stock SDS100 | ~7.5 GiB (8 GB card) |
| Drive size on a stock BT885 | ~3.6 GiB (4 GB card) |
| Volume label | none |
| What you can do | Mount, walk `BCDx36HP/`, read/write any persistent file |
| What you cannot do | Anything live - no RSSI, no scan state, no commands. The CDC ports are gone in this mode. |
| Sentinel uses | **YES** - this is Sentinel's only mode |
| Our app uses | YES - for SD-card edits and firmware drops |

**USB descriptor**: VID `0x1965`, with a Mass Storage Class
interface. The MSC interface PID can vary; the topology trick we
use to identify it is "USB device whose USBPcap interface trace
goes back to a hub that also enumerates the SDS100 family CDC
PIDs `0x0019`/`0x001A` when the device is rebooted into Serial
mode" - see `Metacache/Dev/RE/tools/automation/find_sds100_hub.ps1`.

## Serial mode

| Question | Answer |
|---|---|
| How to enter | Pick "Serial" from the boot prompt (the dot/period key per FW 1.23.07) |
| Windows sees | **Two** "USB Serial Device" entries in Device Manager |
| Identification | VID `0x1965`, PIDs `0x0019` (SUB) and `0x001A` (MAIN) |
| Visible filesystem | **none** - the SD volume disappears in this mode |
| What you can do | Send Uniden Remote Command Protocol on COM4 (MAIN); send debug commands on COM3 (SUB); poll live state |
| What you cannot do | Read or write SD-card files |
| Sentinel uses | **NO** - never enters this mode |
| Our app uses | YES - for live state, GSI mirror, RSSI plots, DSP introspection |

The two CDC ports are not interchangeable. They route to different
MCUs and run different protocols:

| Port | PID | MCU | Protocol surface |
|---|---|---|---|
| `COM4` | `0x001A` | MAIN | Documented Uniden Remote Command Protocol (V1.02 + V2.00) plus undocumented argument variants and `GLT,SYS` |
| `COM3` | `0x0019` | SUB | Identity (`MDL`/`VER`) + 13 single-character DSP/RF debug commands. Does **not** speak the documented Remote Command Protocol; most documented mnemonics return nothing on this port |

See [RE-Serial-Protocol](RE-Serial-Protocol) for the full command
catalogs of both ports.

### Identifying which COM number is which PID

Windows assigns COM numbers semi-randomly. Don't assume `COM3 ==
SUB`. Instead, on PowerShell:

```powershell
Get-CimInstance Win32_PnPEntity |
  Where-Object { $_.DeviceID -match 'VID_1965' } |
  Select-Object Name, DeviceID
```

The `DeviceID` substring `PID_001A` is MAIN, `PID_0019` is SUB.

In Python (used by our probes):

```python
import serial.tools.list_ports
ports = {p.pid: p.device for p in serial.tools.list_ports.comports() if p.vid == 0x1965}
main_port = ports.get(0x001A)
sub_port  = ports.get(0x0019)
```

This is what `Metacache/Dev/RE/tools/probes/list_ports.py`
does, and it's reused by every probe script.

## Mode signalling cheat sheet

If you're a script trying to tell what mode the scanner is in:

| Topology you observe | Mode |
|---|---|
| One Uniden VID `0x1965` USB MSC interface present + a removable FAT32 volume | Mass Storage |
| Two Uniden VID `0x1965` CDC interfaces (PIDs `0x0019` and `0x001A`) and **no** Uniden MSC | Serial |
| Neither | Scanner is off, or in normal scan mode without USB connected, or USB cable disconnected |

A simultaneous mass-storage volume + CDC port pair would be the
"future RE goal" the user flagged ("mass storage in serial mode
so the user doesn't have to switch") - we have not seen this
combination on any stock firmware.

## Why the choice matters for our app

- **SD-card edits** (favourites, settings, HPDB, firmware drops):
  Mass Storage. The user briefly switches modes for these.
- **Live state mirror** (current TGID, RSSI, scan list, DSP
  introspection): Serial. Users keep the scanner in Serial mode
  during normal "running with the app open" sessions.
- **Discovery / capture / fuzzing**: Serial. Driven by our probe
  scripts.

Sentinel only ever uses Mass Storage. Our app strictly extends.
See [Reverse Engineering](Reverse-Engineering) for the synthesis.
