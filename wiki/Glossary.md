# Glossary

Scanner hobby acronyms relevant to working with Scanner Manager.

## Scanner hardware / firmware

- **BearTracker 885 (BT885)** - Uniden's all-in-one base + mobile
  scanner with DOT / EMS / Fire / Police preset buttons. The primary
  target of this project.
- **BCDx36HP** - Uniden's BCD436HP / BCD536HP hand-held / base family.
  Shares the Sentinel software and the HPD format with the BT885.
- **Firmware tables** - `ZipTable*.dat` and `CityTable*.dat` on the
  SD card. Used by the scanner to decide what to scan at a given
  location.

## File formats

- **HPD** - Uniden's binary configuration file format (`.hpd`). A
  single HPD file holds one or more systems, the groups inside them,
  and every conventional frequency and trunked talkgroup inside those
  groups. The BearTracker splits these by state.
- **`hpdb.cfg`** - the master HPD file the scanner loads from the card
  root. Points at the per-state `s_*.hpd` files.
- **`s_*.hpd`** - per-state HPD files the scanner loads on demand
  when you pick a location.
- **`.meta.json`** - Scanner Manager's change-history sidecar, stored
  next to each HPD file. It's how **Undo** knows what to reverse.
  Never hand-edit it.
- **`.session.bak`** - automatic safety copy of the HPD file written
  on every save. Used by **Tools -> Restore session snapshot** if a
  save goes wrong.

## RadioReference

- **RR** - [RadioReference.com](https://www.radioreference.com/).
- **SID** (or System ID) - RR's identifier for a trunked system.
- **TGID** - Trunked talkgroup ID.
- **Category** - An RR grouping of related frequencies.

## This app

- **MetaStore** - the event-sourced change log. See
  [Architecture](Architecture).
- **Workspace** (a.k.a. **Virtual SD card**) - local folder that
  mirrors the card for offline editing. See
  [Workspaces & Sync](Workspaces-and-Sync).
- **Pipeline / push-update-pull** - Uniden tool orchestration flow
  that snapshots, runs the Uniden tool, and replays user events on
  top. See [Uniden Tools](Uniden-Tools-Integration).

## Coverage tags

- `COVERAGE` - center point is inside the system's coverage circle.
- `NEARBY` - edge of coverage is within the nearby threshold.
- `LOCAL` - system is pinned to the active ZIP's primary county.
- `STATEWIDE` - state-level system, relevant anywhere in-state.
- `WIDE` - national / multi-state.

See [ZIP & GPS Simulation](ZIP-and-GPS-Simulation) for full details.

## Reverse engineering

The terms below are specific to the
[Reverse Engineering](Reverse-Engineering) section. See that page
for the consolidated narrative.

### Hardware

- **MAIN MCU** - the SDS100's primary microcontroller (STM32 family).
  Owns the LCD, keypad, scan engine, SD card, and USB-host endpoint.
  Firmware is **encrypted** so we can't read it statically.
- **SUB MCU** - the SDS100's secondary microcontroller (NXP LPC43xx,
  ARM Cortex-M3/M4). Owns the RF tuner and DSP. Firmware is
  **plaintext** and fully decompiled.
- **R840** - Rafael Micro silicon TV-tuner IC the SDS100 uses as
  the wide-band IF tuner. Driven over I2C from SUB.
- **USART2** - LPC43xx UART block used as the **inter-MCU bus**
  between SUB and MAIN. 115200/8N1, no flow control, internal
  routing only.

### USB modes

- **Mass-Storage mode** (or **UMS mode**) - one of the two USB
  modes of the SDS100. The SD card appears as a removable FAT32
  drive. Sentinel's only mode.
- **Serial mode** - the other USB mode. Two CDC virtual COM ports
  appear (`PID 0x0019` SUB and `PID 0x001A` MAIN). The SD volume
  is hidden in this mode.
- **CDC** - Communications Device Class. The USB class that
  presents a serial-port-like interface to the host.
- **MSC / UMS** - Mass Storage Class / USB Mass Storage. The class
  that presents a SCSI block device to the host.
- **BOT** - Bulk-Only Transport. The USB mass-storage transport
  layer that wraps SCSI commands in CBW/CSW packets over bulk
  endpoints.
- **CBW / CSW** - Command Block Wrapper / Command Status Wrapper.
  The CBW (31 bytes, magic `USBC`) carries the SCSI command;
  CSW (13 bytes, magic `USBS`) carries the response status.

### Files / format

- **BCDx36HP** - Uniden's firmware family name. Folder name on the
  SD card. Shared by BT885, SDS100, SDS200, SDS150, BCD436HP,
  BCD536HP. **NOT a model identifier** - real model is in
  `scanner.inf`.
- **HPD** / **`s_*.hpd`** - per-state Hpdb-Per-... payload file.
  Tab-separated record-oriented format. See [RE-SD-Card](RE-SD-Card).
- **`f_*.hpd`** - per-favorite payload (SDS100 only).
- **`hpdb.cfg`** - master state/county/agency index.
- **`scanner.inf`** - identity file. Field 1 of the `Scanner` line
  is the canonical model fingerprint.
- **`profile.cfg`** - giant settings file (SDS100 only). 184 lines
  covering waterfall, GPS, weather, display, etc.
- **`app_data.cfg`** - last-active scan state (SDS100 only).
  Ephemeral.
- **`discvery.cfg`** (sic) - discovery config stub (SDS100 only).
  The typo is in the firmware - preserve verbatim.
- **`.bin`** - MAIN MCU firmware image (encrypted, ~2.16 MB).
  Dropped into `BCDx36HP/firmware/` to update.
- **`.firm`** - SUB MCU firmware image (plaintext, ~88-90 KB).
  Same drop-and-reboot mechanism.

### Tooling

- **Sentinel** - Uniden's official SDS100 desktop tool. Just a
  Mass-Storage filesystem editor with a UI. See [RE-Sentinel](RE-Sentinel).
- **Ghidra** - the NSA's open-source software reverse-engineering
  framework. We use it for headless analysis of the SUB firmware.
- **USBPcap** - kernel-level USB packet capture driver for Windows.
  Required to capture Sentinel's USB traffic.
- **tshark** - Wireshark's CLI. Used by our SCSI/UMS/FAT32 decoder
  to parse pcaps.
- **LPC43xx SVD** - System View Description XML for the LPC43xx
  family. Loaded into Ghidra to overlay peripheral register names
  on memory accesses.

### Probes / techniques

- **Whitelist + forbidden-list probe** - the safety contract our
  probes follow. Mutating commands are hard-coded forbidden;
  read-only commands must be on the whitelist before being sent.
- **Anchor-and-compare** - re-send a known-good command (e.g.
  `MDL`) between probes to detect buffer leakage on the SUB port.
- **Buffer leakage** - SUB-port behaviour where an unrecognised
  command returns the **previous** successful response. Defeated
  by anchor-and-compare.
- **Prefix fallback** - SUB-port behaviour where any input starting
  with `M` returns identity, anything starting with `V` returns
  version. Looks like distinct commands but isn't.
- **Per-character `cmp` chain** - the SUB firmware's command parser
  does not use a string table. It compares input bytes one at a
  time against immediate constants (`cmp #imm8`). The 13 debug
  commands were extracted from this chain by hand.
- **Live falsification** - sending a Ghidra-predicted mnemonic to
  the live scanner to confirm or refute the prediction.

### Findings

- **GSI XML** - the MAIN-port command that returns the entire
  scanner state as XML. Single best command for a live mirror.
- **GLT,SYS** - undocumented GLT subform that works on SDS100
  (Phase 3 finding from BCDx36HP V1.05).
- **The 13 SUB debug commands** - `o q w d r m z h l s t u v`. DSP
  / RF debug taps in the SUB firmware. See
  [RE-Serial-Protocol](RE-Serial-Protocol).
- **`U5C42`** - the only undocumented uppercase SUB command found.
  Returns a 9-byte response with 5-byte ASCII prefix and 2 binary
  bytes (probably a register dump).
- **Phase 0a/0c** - the Sentinel USB capture phases. Confirmed
  Sentinel uses Mass Storage / SCSI / FAT32 only.
- **Phase 6** - SUB firmware static RE. Extract + Ghidra import
  + dispatch table enumeration + live-falsify. **DONE** for the
  SUB-side surface.
