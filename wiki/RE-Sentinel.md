# RE: Sentinel

> Where this fits: what Sentinel actually does over USB, and how
> our app replicates (and exceeds) it. Sentinel is a Mass-Storage
> filesystem editor - **nothing more**. For the consolidated
> narrative start at [Reverse Engineering](Reverse-Engineering).

## Headline

**Sentinel is a desktop FAT32 editor.** It puts the scanner into
[Mass-Storage mode](RE-USB-Modes), mounts the FAT32 SD card via
USB MSC / SCSI, and reads/writes the same
[BCDx36HP file shapes](RE-SD-Card) we've already RE'd. There is
no Sentinel-private serial protocol, no encrypted handshake, no
proprietary container - just SCSI READ_10 / WRITE_10 of FAT32
sectors.

This is the most consequential finding from Phase 0 of the RE
work. It means **anything Sentinel can do, our app can do** by
mounting the same volume and parsing the same files. Drive letter
+ standard FAT32 + known file paths = full functional parity, with
the additional [Serial-mode surface](RE-Serial-Protocol) thrown in
for free.

## How we know

`Metacache/Dev/RE/sentinel_pcaps`
captured every USB packet between Sentinel and the SDS100 during
operations 1 (Read From Scanner) and 2 (Write to Scanner). Phase 0c
extends to ops 3-6 (HPDB Update, Firmware Update, Backup, Restore).

The captures are decoded by `Metacache/Dev/RE/tools/sentinel/decode_sentinel_pcap.py`,
which:

1. Parses USBPcap pcap files via tshark.
2. Identifies USB Mass Storage Class CBW / data / CSW transfers.
3. Decodes SCSI READ_10 / WRITE_10 / TEST_UNIT_READY etc.
4. Reassembles the touched LBA sectors into a sparse disk image.
5. Walks the FAT32 directory of the reconstructed image to identify
   exactly which **files** Sentinel touched (not just LBAs).
6. Emits per-pcap `.scsi.jsonl` (every SCSI op), `.disk.bin` (sparse
   disk image), `.files.md` (file-touch table), `.summary.md`
   (top-level histogram).

In Phase 0a the only protocols visible were `USB`, `USBMS`, and
SCSI commands. **Zero CDC traffic.** Zero non-MSC frames. That's
the proof.

## What about Edit Display / Edit Favorites / Edit Profile?

Sentinel's GUI exposes three additional in-app editors -
**Edit Display**, **Edit Favorites**, and **Edit Profile** - that
*don't* show up in the operation list above, because they don't talk
to the scanner over USB at all. They are pure-on-disk FAT32 file
edits against files we already know:

| Sentinel function | What it edits | File(s) on the SD card |
|---|---|---|
| Edit Display | LCD colour palette + theme | `BCDx36HP/Disp/disp_*.dat` (and the per-key colour overrides in `BCDx36HP/scanner.cfg`) |
| Edit Favorites | Favorites lists + scan groups + per-channel data | `BCDx36HP/<favorites-folder>/*.hpd` (HPDB record files) |
| Edit Profile | Per-profile settings (squelch defaults, audio routing, etc.) | `BCDx36HP/Profile/*.dat`, `BCDx36HP/scanner.cfg` |

All three of these are reachable from our app via the same FAT32
parsers documented in [RE-SD-Card](RE-SD-Card). No new captures
needed; no new protocol; no GUI dependency on Sentinel.

The functional implication: **the four real Sentinel USB operations
above + the three editor functions = our app's complete coverage
target**. We already replicate the editors via direct file access;
the only remaining replication work is around the four USB ops, all
of which are pure SCSI READ_10 / WRITE_10 against the same files.

## The 6 Sentinel operations, decoded

The plan was always to capture all six high-value Sentinel
workflows. Here's where each stands.

### Op 1: Read From Scanner (DONE)

| Property | Value |
|---|---|
| Capture file | `01_read_from_scanner.pcap` |
| SCSI commands | 51 |
| READ_10 ops | 9 (42,496 B) |
| WRITE_10 ops | 3 (12,288 B) |
| Max LBA touched | 0x3EEC2 = sector 257,730 |
| Time | ~10 seconds |

Phase decomposition:

| Phase | Time | Activity | Likely role |
|---|---:|---|---|
| 1 | 0-6 s | 24× TEST_UNIT_READY + 14× REQUEST_SENSE | UMS housekeeping (Windows polling) |
| 2 | 6.3 s | 1× READ_10 31 blocks @ LBA 0x3EE40 (15.5 KB) | Read scanner manifest from end-of-volume reserved area |
| 3 | 6.3-6.5 s | 3× WRITE_10 8 blocks @ 0x4080 + 1× READ_10 1 block @ 0x4E80 | Write a single FAT/dir block + read one sector ("hello, I'm Sentinel" handshake marker) |
| 4 | 6.4 s | 5× READ_10 8 blocks @ 0x4D80...0x4DA0 (20 KB consecutive) | Read a cluster of small files |
| 5 | 6.5 s | READ_10 + READ_10 + WRITE_10 around 0x4240/0x3EEC0 | Manifest update |

**Read-mostly metadata sync.** Sentinel pulls the scanner's
per-device config but doesn't extract HPDB or full state.

### Op 2: Write to Scanner (DONE)

| Property | Value |
|---|---|
| Capture file | `02_write_to_scanner.pcap` |
| SCSI commands | 120 |
| READ_10 ops | 27 (1,703,936 B) |
| WRITE_10 ops | 30 (78,336 B) |

Phase decomposition:

| Phase | Time | Activity | Likely role |
|---|---:|---|---|
| 1 | 7.0-7.4 s | 22× WRITE_10 to FAT mirror pairs (`0x310C/0x3886`, `0x3129/0x38A3`, `0x310F/0x3889`) and writable cluster `0x4080` | **Allocate filesystem space** - write FAT entries to claim free clusters, write new directory entries |
| 2 | 7.4-10.2 s | **24× READ_10 of 64 KB each** at consecutive LBAs `0x23440`-`0x240C0` (1.5 MB sequential) | **Read existing HPDB-or-similar file** for read-modify-write merge |
| 3 | 10.3-10.4 s | 8× WRITE_10 to FAT mirrors and dir entries | Commit metadata - update directory entries with new sizes/timestamps, finalise FAT chains |

The FAT mirroring is unmistakable: writes always come in pairs at
LBAs that differ by exactly 0x77A = 1914 sectors (the FAT2-FAT1
offset). Confirms the volume is FAT32 with two FATs, ~1 MB each.

The 1.5 MB sequential read is the standout. That offset (LBA
0x23440 × 512 = 73,827,328) is at byte position **74 MB into the
volume**. The file there is one of:

- HPDB favourites consolidation file (~1-1.5 MB)
- CFG / global config file
- Per-channel record file holding the full state

Disambiguates by mounting the SD and computing the first-sector
LBA of each candidate file. (See "Filesystem inventory" below.)

### Op 3: HPDB Update - "already up to date" path (DONE)

| Property | Value |
|---|---|
| Capture file | `03_hpdb_update.pcap` |
| SCSI commands | 297 |
| READ_10 ops | **0** |
| WRITE_10 ops | **0** |
| Other | 198× TEST_UNIT_READY + 99× REQUEST_SENSE |

The user reported "HPDB database up to date" before clicking
"Get HPDB Update". The capture confirms what that means at the USB
layer: **Sentinel does not query the SD card at all** during the
version check. It performs the check entirely **out-of-band over
FTP** to `ftp.homepatrol.com/BCDx36HP/`, decides the local copy is
current, and exits. The 297 frames are just keep-alive housekeeping
while the FTP round-trip happens. Endpoint, credentials, and full
flow documented in [RE-Update-Endpoints](RE-Update-Endpoints).

**Implication for our app**: the "is HPDB current?" check is *not*
a USB question. It's `(read DateModified field from hpdb.cfg) ==
(latest MasterHpdb_*.gz date on FTP)`. If outdated, Sentinel would
then WRITE_10 the new HPDB blob - we don't have a capture of that
yet, but the format is identical to the records already documented
in [RE-SD-Card](RE-SD-Card).

### Op 4: Firmware Update - "already up to date" path (DONE)

| Property | Value |
|---|---|
| Capture file | `04_firmware_update.pcap` |
| SCSI commands | 40 |
| READ_10 ops | **1** (4,096 B at LBA 0x4280) |
| WRITE_10 ops | **0** |
| Other | 24× TEST_UNIT_READY + 14× REQUEST_SENSE + 1× MODE_SENSE_6 |

Same context: user reported "firmware up to date". The single
READ_10 at **LBA 0x4280 (sector 17024, byte 8,716,288) of 4 KB**
is the **FAT32 directory entry for `BCDx36HP/firmware/`**. Strings
visible in the read payload include:

```
CityTable_V1_...                    CITYTA~1DAT
SDS-100_V1_03_05.firm               DS-10~1FIR
ZipTable_V1_0...                    ZIPTAB~1DAT
SDS-100_V1_05.bin                   DS-10~1BIN
_V1_03_05.firm                      (tmp/)
```

So Sentinel's firmware-update check is:

1. Read the FAT32 directory of `BCDx36HP/firmware/` (one 4 KB
   sector at LBA 0x4280 on this card).
2. Parse out the `.bin` and `.firm` filenames; the version is
   embedded in the name (`SDS-100_V1_05.bin` = MAIN v1.05;
   `_V1_03_05.firm` = SUB v1.03.05).
3. FTP-fetch the latest version from `ftp.homepatrol.com/BCDx36HP/`
   (filename pattern `<MODEL>_V*.bin` for MAIN, `<MODEL>-SUB_V*.firm`
   for SUB; full inventory in
   [RE-Update-Endpoints](RE-Update-Endpoints)).
4. If outdated, would WRITE_10 the new file. We don't see writes
   in this capture because the firmware was current.

The MODE_SENSE_6 at frame 1641 is Sentinel asking "is this device
write-protected?" - standard pre-write probe.

**Implication for our app**: same one-sector read works for our
firmware-update check. Mount the volume, walk `BCDx36HP/firmware/`,
parse the version-encoded filenames. No special API needed.

### Op 5+6: Backup and Restore - feature absent (DONE)

| Property | 05_backup.pcap | 06_restore.pcap |
|---|---:|---:|
| SCSI commands | 3 | 3 |
| READ_10 ops | 0 | 0 |
| WRITE_10 ops | 0 | 0 |
| Other | 1×TUR + 1×REQ_SENSE + 1×TUR | 1×TUR + 1×REQ_SENSE + 1×TUR |

User reported: **"no backup/restore feature present"** in their
Sentinel build. The captures (3 frames each, all keep-alive) confirm
nothing happens at the USB layer. So Sentinel's official surface is
**4 ops, not 6**:

1. Read From Scanner
2. Write to Scanner
3. Get HPDB Update
4. Update Firmware

**Backup = Read From Scanner** (just save the result somewhere).
**Restore = Write to Scanner** (with previously-saved state).
Sentinel's UI in some versions exposes these as menu items, but
they're not distinct USB operations.

**Implication for our app**: we don't need a separate "backup"
code path. We need:

- A snapshot mechanism that copies the result of "Read From
  Scanner" into our MetaStore as a Workspace.
- A push mechanism that takes a saved Workspace and runs "Write
  to Scanner" on it.

We already have both - Workspaces and the MetaStore push pipeline.
**Sentinel parity for backup/restore is "feature complete" today**
without any new code.

## What Sentinel never does

- Open or speak to the CDC ports `PID 0x0019` / `0x001A` (Serial
  mode is unused).
- Send any documented Uniden Remote Command Protocol commands.
- Use any encrypted / signed / authenticated transport.
- Use anything other than SCSI block-level read/write.

So a complete reverse-engineering of Sentinel's wire protocol
**reduces to**: enumerate every file the FAT32 walker reports as
"touched". That's what `.files.md` outputs.

## Sentinel API surface (final, after Phase 0c capture)

Sentinel's complete USB API is **4 ops, not 6**, and every one of
them reduces to standard FAT32 file operations on the SD card.
Our app replicates the surface as:

```python
class SDS100MassStorage:
    def __init__(self, drive_letter: str): ...

    # === Op 1: Read From Scanner ===
    # Walk BCDx36HP/ and pull every persistent file we know how to
    # parse. Backup is just "read all + save the result".
    def read_all(self) -> ScannerSnapshot: ...
    def read_scanner_inf(self) -> ScannerInf: ...
    def read_hpdb(self) -> HpdbDatabase: ...
    def read_favorites(self) -> list[FavoritesList]: ...
    def read_profile(self) -> ProfileConfig: ...

    # === Op 2: Write to Scanner ===
    # Reverse of read_all. Restore is just "write a saved snapshot".
    def write_snapshot(self, snap: ScannerSnapshot) -> None: ...
    def write_hpdb(self, hpdb: HpdbDatabase) -> None: ...
    def write_favorites(self, lists: list[FavoritesList]) -> None: ...
    def write_profile(self, profile: ProfileConfig) -> None: ...

    # === Op 3: Get HPDB Update ===
    # Sentinel does this OUT-OF-BAND over HTTP, NOT over USB.
    # USB is only used to write the new payload if outdated.
    def get_installed_hpdb_version(self) -> str:
        # Read DateModified from BCDx36HP/HPDB/hpdb.cfg
        ...
    def check_hpdb_update_available(self) -> bool:
        # 1. v_local = self.get_installed_hpdb_version()
        # 2. v_remote = http_get_uniden_hpdb_version()
        # 3. return v_remote > v_local
        ...
    def install_hpdb_update(self, hpdb_zip: Path) -> None:
        # Unzip HPDB bundle and write each s_*.hpd into BCDx36HP/HPDB/
        ...

    # === Op 4: Update Firmware ===
    # Same pattern as HPDB: HTTP for version check, USB only for write.
    def get_installed_firmware_versions(self) -> FirmwareVersions:
        # Walk BCDx36HP/firmware/ and parse SDS-100_V1_XX.bin
        # and *.firm filenames (versions are embedded in filename).
        ...
    def install_firmware(self, fw_image: Path, kind: Literal["main", "sub"]) -> None:
        # Drop *.bin or *.firm into BCDx36HP/firmware/.
        # IMPORTANT: never have two .bin files in the folder
        # simultaneously (Uniden's readme: upload won't start).
        # User reboots scanner to apply.
        ...

    # === Backup + Restore (NOT separate ops; aliases) ===
    def backup(self, dst: Path) -> None:
        snap = self.read_all()
        snap.save(dst)
    def restore(self, src: Path) -> None:
        snap = ScannerSnapshot.load(src)
        self.write_snapshot(snap)
```

### Where the version-check info lives

| Question | Answer (file or sector to read) |
|---|---|
| Current MAIN firmware version | `BCDx36HP/scanner.inf` field 3 of the `Scanner` line, OR the `.bin` filename in `BCDx36HP/firmware/` |
| Current SUB firmware version | `BCDx36HP/scanner.inf` field 9, OR the `.firm` filename in `BCDx36HP/firmware/` |
| Current HPDB version | `BCDx36HP/HPDB/hpdb.cfg` `DateModified` line |
| Current SDS100 settings version | Embedded in `BCDx36HP/profile.cfg` `FormatVersion` line |
| Available version (any of above) | HTTP fetch from Uniden's update service - **NOT** a USB question |

Our app builds on this directly. The `SDS100MassStorage` class
above maps 1:1 to features we already have (read_all / write_all,
HPDB import, firmware drop) plus a thin "check Uniden HTTP service"
glue layer that we can implement at our leisure.

## Filesystem inventory

When Sentinel is in Mass-Storage mode and the SDS100 mounts as a
drive letter, run:

```pwsh
.\Metacache\Dev\RE\tools\sentinel\dump_sd_inventory.ps1
```

This script auto-detects the SDS100 drive (by USB topology
matching VID 1965), walks the entire `BCDx36HP/` tree, and produces:

- `sds100_sd_inventory_<UTC>.tsv` - full file list (path, size,
  mtime, attributes)
- `sds100_sd_inventory_<UTC>.md` - top-level summary (top files
  by size, files-by-extension histogram, directory tree)

Once we have this and the Phase 0c captures, we can map every
LBA range Sentinel touches to a specific file - turning "Sentinel
read 1.5 MB at LBA 0x23440" into "Sentinel read
`BCDx36HP/HPDB/hpdb.cfg`" or whichever file actually starts there.

## Visible strings in captured sectors

While exhaustive file mapping is pending, we've already identified
the content types Sentinel manipulates by string-searching the
captured sector data:

- **HPDB record markers**: `HPDB`, `XWIX`, `XW.\`, `IX..`
- **HPDB record files**: `_000001.hpd ... _000113.hpd` (113 records),
  `f_000001.hpd ... f_000003.hpd` (3 files of a different class)
- **CFG payload structures**: `TargetModel.BCDx36HP`,
  `FormatVersion.1.00`, `ProductName.SDS100`, `GlobalSetting`,
  `LimitSearch.SrchId=...`, `BandDefault.BandId=...`,
  `DispOptItems.DispOptId=...`
- **List-style markers**: `LIST`, `_LIST`, `F_LIST`

All of these correspond directly to file shapes documented in
[RE-SD-Card](RE-SD-Card).

## How to capture more Sentinel ops

```pwsh
# Per-op:
py Metacache\Dev\RE\tools\sentinel\sentinel_session.py --skip 1 --skip 2

# Re-decode any existing pcap with the new SCSI decoder:
py Metacache\Dev\RE\tools\sentinel\decode_sentinel_pcap.py Metacache\Dev\RE\sentinel_pcaps\03_hpdb_update.pcap
```

The session driver auto-detects the USBPcap interface (by USB
topology, then traffic-volume heuristic), prompts you through the
operation, and decodes the resulting pcap. See [RE-Workflows](RE-Workflows)
for the full recipe.

## Lab data

- `Metacache/Dev/RE/sentinel_pcaps` - all captured pcaps + decoded artefacts.
- `Metacache/Dev/RE/docs/sentinel_api.md` - the original raw write-up.
- `Metacache/Dev/RE/tools/sentinel/decode_sentinel_pcap.py` - SCSI/UMS/FAT32 decoder.
- `Metacache/Dev/RE/tools/sentinel/sentinel_session.py` - guided capture driver.
- `Metacache/Dev/RE/tools/sentinel/dump_sd_inventory.ps1` - read-only SD card walker.
- `Metacache/Dev/RE/sessions/phase0b_decision_2026-05-03.md` - the "Sentinel = UMS, not CDC" finding.
