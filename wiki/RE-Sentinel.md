# RE: Sentinel

> Status: shipped (v0.11.x) — UMS decode complete; actual-update WRITE traces OPEN.

> Where this fits: what Sentinel does over USB, and how our app
> replicates (and exceeds) it. Sentinel is a Mass-Storage filesystem
> editor — **nothing more**. Start at
> [Reverse Engineering](Reverse-Engineering).

## What this answers

Whether Sentinel speaks a private protocol (it doesn’t), what each
UI operation does at the SCSI/FAT32 layer, and which files our
parsers must cover for parity.

## Known vs OPEN

| Topic | State | Notes |
|---|---|---|
| Sentinel = UMS only (no CDC) | DONE | Phase 0a/0b |
| Ops 1–2 Read/Write decode | DONE | Full SCSI traces |
| Ops 3–4 up-to-date path | DONE | FTP out-of-band; 0 or 1 READ_10 |
| Ops 5–6 Backup/Restore | DONE — absent / aliases | |
| In-app editors = on-disk files | DONE | Paths match [RE-SD-Card](RE-SD-Card) |
| Actual HPDB/firmware WRITE_10 update | OPEN | Need outdated-card capture |
| LBA → file map for every touch | Partial | Inventory + `.files.md` |

## Deep dive

### Headline

**Sentinel is a desktop FAT32 editor.** It uses
[Mass-Storage mode](RE-USB-Modes), mounts the SD via USB MSC/SCSI,
and reads/writes the same [BCDx36HP shapes](RE-SD-Card) we already
RE’d. No Sentinel-private serial protocol, no encrypted handshake —
SCSI READ_10 / WRITE_10 only.

Anything Sentinel can do, our app can do by mounting the same volume.
Serial mode ([RE-Serial-Protocol](RE-Serial-Protocol)) is extra.

### How we know

Captures under `Metacache/Dev/RE/sentinel_pcaps/`, decoded by
`Metacache/Dev/RE/tools/sentinel/decode_sentinel_pcap.py`
(USBPcap → SCSI → sparse disk → FAT32 file-touch table →
`.summary.md` / `.files.md`). Phase 0a: protocols visible were USB /
USBMS / SCSI only — **zero CDC**.

### In-app editors (no USB op list)

Edit Display / Favorites / Profile talk to the card as ordinary
files (when mounted), not a separate wire protocol:

| Sentinel function | On-card target (lab-aligned) |
|---|---|
| Edit Display | Display-related records in `BCDx36HP/profile.cfg` (`DispOptItems`, `DispColors`, `DisplayOption`, …) |
| Edit Favorites | `BCDx36HP/favorites_lists/f_list.cfg` + `f_*.hpd` |
| Edit Profile | `BCDx36HP/profile.cfg` (and related settings records) |

There is **no** lab evidence for separate `Disp/`, `Profile/`, or
`scanner.cfg` trees on SDS100 cards we imaged — those names were
wiki speculation; corrected to match [RE-SD-Card](RE-SD-Card).

### The six operations (four real)

#### Op 1: Read From Scanner — DONE

`01_read_from_scanner.pcap`: ~51 SCSI cmds; read-mostly metadata
sync (manifest + small files). Details in lab `sentinel_api.md` /
pcap `.summary.md`.

#### Op 2: Write to Scanner — DONE

`02_write_to_scanner.pcap`: FAT mirror pair writes (offset 0x77A
sectors) + large sequential READ then metadata commit —
read-modify-write of HPDB-scale content.

#### Op 3: HPDB Update (“up to date”) — DONE

`03_hpdb_update.pcap`: **0** READ_10 / WRITE_10. Version check is
**out-of-band FTP** to `ftp.homepatrol.com/BCDx36HP/`
([RE-Update-Endpoints](RE-Update-Endpoints)). USB only used if
outdated (WRITE not yet captured).

Local compare: `hpdb.cfg` `DateModified` vs latest
`MasterHpdb_*.gz` date on FTP.

#### Op 4: Firmware Update (“up to date”) — DONE

`04_firmware_update.pcap`: one READ_10 (4 KB @ LBA 0x4280) =
`BCDx36HP/firmware/` directory entry; then FTP version check; WRITE
only if outdated (not captured). Versions encoded in `.bin` /
`.firm` filenames.

#### Ops 5–6: Backup / Restore — DONE (absent)

Captures are housekeeping only. User’s Sentinel build has no distinct
backup/restore USB ops. Treat as aliases of Read / Write. Our
Workspaces / MetaStore already cover the product need.

### What Sentinel never does

- Open CDCs `0x0019` / `0x001A`
- Send Uniden Remote Command Protocol
- Use anything other than SCSI block I/O for the scanner link

### API surface (conceptual)

Ops reduce to FAT32 file I/O + **FTP** (not HTTP) for version checks:

```python
# Sketch — production code lives in core/ + firmware/
class SDS100MassStorage:
    def read_all(self) -> ScannerSnapshot: ...
    def write_snapshot(self, snap: ScannerSnapshot) -> None: ...
    def get_installed_hpdb_version(self) -> str: ...  # hpdb.cfg DateModified
    def check_hpdb_update_available(self) -> bool: ...  # vs FTP listing
    def install_hpdb_update(self, hpdb_zip: Path) -> None: ...
    def get_installed_firmware_versions(self) -> FirmwareVersions: ...
    def install_firmware(self, fw_image: Path, kind: Literal["main", "sub"]) -> None: ...
```

| Question | Where |
|---|---|
| MAIN / SUB installed version | `scanner.inf` fields 3 / 9, or `firmware/` filenames |
| HPDB version | `HPDB/hpdb.cfg` `DateModified` |
| Available versions | **FTP** listing — not a USB question |

### Capture more ops

```pwsh
py Metacache\Dev\RE\tools\sentinel\sentinel_session.py --skip 1 --skip 2
py Metacache\Dev\RE\tools\sentinel\decode_sentinel_pcap.py Metacache\Dev\RE\sentinel_pcaps\03_hpdb_update.pcap
.\Metacache\Dev\RE\tools\sentinel\dump_sd_inventory.ps1
```

Full recipe: [RE-Workflows](RE-Workflows).

## Lab pointers

| Path | Role |
|---|---|
| `Metacache/Dev/RE/docs/sentinel_api.md` | Lab API write-up (note: still says “HTTP” in places — wiki/FTP wins; flag for RELab) |
| `Metacache/Dev/RE/docs/sentinel_capture.md` | Capture methodology |
| `Metacache/Dev/RE/sentinel_pcaps/` | Raw pcaps + decoded artefacts |
| `Metacache/Dev/RE/tools/sentinel/decode_sentinel_pcap.py` | SCSI/UMS/FAT32 decoder |
| `Metacache/Dev/RE/tools/sentinel/sentinel_session.py` | Guided capture |
| `Metacache/Dev/RE/tools/sentinel/dump_sd_inventory.ps1` | Card inventory |
| `Metacache/Dev/RE/sessions/phase0b_decision_2026-05-03.md` | “Sentinel = UMS, not CDC” |
