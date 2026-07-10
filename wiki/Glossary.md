# Glossary

> Status: shipped (v0.11.x)

Short definitions for terms you will see in Scanner Manager and on the
SD card. Reverse-engineering vocabulary is in the section at the bottom
— day-to-day users can stop after **Coverage tags**.

## Scanner hardware / firmware

- **BearTracker 885 (BT885)** — Uniden base/mobile scanner with DOT /
  EMS / Fire / Police buttons. A primary target of this project.
- **SDS100 / SDS200** — Uniden handheld/base scanners in the BCDx36HP
  family. Scanner Manager 0.11.x supports serial live mirror, streaming,
  and firmware updates for these.
- **BCDx36HP** — Folder name on the SD card shared by several Uniden
  models. **Not** a model name by itself — read `scanner.inf` for the
  real model.
- **Firmware tables** — `ZipTable*.dat` and `CityTable*.dat` on the
  card. Used to decide what to scan at a location.

## USB modes

- **Mass Storage** — USB mode where the SD card appears as a removable
  drive. Use this (or a card reader) to edit files with Scanner Manager
  or Sentinel.
- **Serial** — USB mode with virtual COM ports for live control and
  monitoring (SDS100/200). The SD volume is hidden in this mode.

## File formats

- **HPD** — Uniden channel-database file (`.hpd`). Holds systems,
  groups, and entries (frequencies or talkgroups). The BearTracker
  often splits these by state (`s_*.hpd`).
- **HPDB** — The on-card channel database as a whole: master
  `hpdb.cfg` plus the HPD files it references.
- **`hpdb.cfg`** — Master index the scanner loads; points at per-state
  `s_*.hpd` files.
- **`s_*.hpd`** — Per-state HPD files loaded when you pick a location.
- **`f_*.hpd`** — Per-favorite payload (SDS100 only).
- **`profile.cfg`** — Large settings file (SDS100 only).
- **`.meta.json`** — Scanner Manager change-history sidecar next to
  each HPD. How **Revert** knows what to undo. Do not hand-edit.
- **`.session.bak`** — Automatic safety copy written on save. Use it to
  recover a bad save.

## RadioReference

- **RR** — [RadioReference.com](https://www.radioreference.com/).
- **SID** (System ID) — RR identifier for a trunked system.
- **TGID** — Trunked talkgroup ID.
- **Category** — RR grouping of related frequencies.

## This app

- **Change history / MetaStore** — Revertable log of edits and imports.
  Open **Tools → Recent changes…** in Qt. See [Architecture](Architecture).
- **Workspace (Qt)** — Named device-list bundle (`devices.json`) for
  Home vs Travel setups. See [Workspaces & Sync](Workspaces-and-Sync).
- **Virtual SD card (Classic Tk)** — Offline clone of the card for
  edit-while-detached. Same wiki page, different section.
- **Push → update → pull** — Uniden tool cycle that snapshots, runs
  Sentinel / BT885 Update Manager, then replays your edits. See
  [Uniden Tools](Uniden-Tools-Integration).
- **Card detect** — Reads `scanner.inf` to recognize the scanner model;
  Qt can warn or confirm a profile switch when the device row disagrees.

## Coverage tags

- `COVERAGE` — Center point is inside the group's coverage circle.
- `NEARBY` — Edge of coverage is within the nearby threshold.
- `LOCAL` — Pinned to the active ZIP's primary county.
- `STATEWIDE` — State-level system, relevant anywhere in-state.
- `WIDE` — National / multi-state.

See [ZIP & GPS Simulation](ZIP-and-GPS-Simulation).

## Reverse engineering

Terms below are for the [Reverse Engineering](Reverse-Engineering)
section. Everyday use of Scanner Manager does not require them.

### Hardware

- **MAIN MCU** — SDS100 primary microcontroller. Owns LCD, keypad,
  scan engine, SD card, USB-host. Firmware is encrypted.
- **SUB MCU** — SDS100 secondary microcontroller. Owns RF tuner and
  DSP. Firmware is plaintext and heavily analyzed.
- **R840** — Wide-band IF tuner IC driven from SUB.
- **USART2** — Inter-MCU serial link between SUB and MAIN.

### USB modes (detail)

- **Mass-Storage / UMS mode** — SD card as FAT32 drive (Sentinel's mode).
- **Serial mode** — Two CDC COM ports (SUB and MAIN); SD hidden.
- **CDC** — USB class that looks like a serial port.
- **MSC / UMS** — Mass Storage Class.
- **BOT** — Bulk-Only Transport for mass-storage commands.
- **CBW / CSW** — Command / status wrappers for SCSI-over-USB.

### Files / format

- **HPD** / **`s_*.hpd`** — Per-state payload files. See
  [RE-SD-Card](RE-SD-Card).
- **`scanner.inf`** — Identity file; field 1 is the model fingerprint.
- **`.bin`** — MAIN firmware image (encrypted).
- **`.firm`** — SUB firmware image (plaintext).

### Tooling

- **Sentinel** — Uniden's official SDS100 desktop tool (mass-storage
  editor). See [RE-Sentinel](RE-Sentinel).
- **Ghidra** — Open-source reverse-engineering framework used on SUB
  firmware.
- **USBPcap** — Windows USB capture driver.
- **tshark** — Wireshark CLI used to decode captures.

### Probes / techniques

- **Whitelist + forbidden-list probe** — Safety contract: mutating
  commands forbidden; read-only commands must be whitelisted.
- **Anchor-and-compare** — Re-send a known-good command between probes
  to detect buffer leakage.
- **Live falsification** — Send a predicted command to the live scanner
  to confirm or refute it.

### Findings

- **GSI XML** — MAIN-port status dump used for the live mirror.
- **GLT,SYS** — Undocumented GLT subform on SDS100.
- **The 13 SUB debug commands** — DSP / RF debug taps. See
  [RE-Serial-Protocol](RE-Serial-Protocol).
