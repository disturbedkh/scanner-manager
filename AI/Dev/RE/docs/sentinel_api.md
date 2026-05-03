# Sentinel API (reverse-engineered) - 2026-05-03

> **Canonical narrative is in the wiki**:
> [`wiki/RE-Sentinel.md`](../../../wiki/RE-Sentinel.md). This file
> is the lab notebook for ongoing decode work.

> Goal: replicate (and extend) Sentinel's functionality from our own
> app/GUI without depending on Sentinel.exe. This document captures
> what Sentinel actually does over USB, derived from
> [`sentinel_pcaps/`](sentinel_pcaps/) and decoded with
> [`_decode_sentinel_pcap.py`](_decode_sentinel_pcap.py).

## TL;DR for app developers

**Sentinel is not a protocol client; it's a USB Mass Storage filesystem
editor.** When the SDS100 is in "mass-storage mode" (long-press whatever
key the scanner uses to enter UMS mode), it presents itself to the
host as a standard SCSI block device with a FAT32 filesystem on it.
Sentinel mounts that drive and reads/writes specific files on it.

Practical implication: **anything Sentinel can do, our app can do by
mounting the same drive in Windows and parsing the same files**. No
USB CDC commands, no custom packet protocol, no firmware-level glue.
Drive letter + standard FAT32 + known file paths = full functional
parity.

The only caveat: the user has to put the scanner in mass-storage mode
first. Per Phase 0b's empirical finding, this mode is **distinct from
serial mode** (the two CDC ports `COM3`/`COM4` are gone in
mass-storage mode). If we want to support **both** modes simultaneously
we'd need a firmware mod (parked under "future RE goal: mass storage
in serial mode" - see the user note in
[`sessions/phase0b_decision_2026-05-03.md`](sessions/phase0b_decision_2026-05-03.md)).

## Sentinel's complete API surface = 4 ops, not 6

Phase 0c (2026-05-03) captured every remaining Sentinel operation
the user's build exposes. Findings:

| Sentinel op | What we captured | What it actually does |
|---|---|---|
| 1 Read From Scanner | 51 SCSI cmds, 9 reads / 3 writes (~42 KB read, 12 KB written) | Read manifest + per-device config files |
| 2 Write to Scanner | 120 SCSI cmds, 27 reads / 30 writes (1.7 MB read, 78 KB written) | Read-modify-write FAT32 update |
| 3 Get HPDB Update | 297 SCSI cmds, **0 reads / 0 writes** (only TUR + REQUEST_SENSE) | **Out-of-band HTTP** version check; would only WRITE_10 if outdated |
| 4 Update Firmware | 40 SCSI cmds, 1 read at LBA 0x4280 (4 KB) / 0 writes | Read FAT32 directory of `BCDx36HP/firmware/`; HTTP-fetch latest version; would only WRITE_10 if outdated |
| 5 Backup | 3 SCSI cmds (housekeeping only) | **Feature absent** in this Sentinel build; alias for op 1 in some other builds |
| 6 Restore | 3 SCSI cmds (housekeeping only) | **Feature absent** in this Sentinel build; alias for op 2 in some other builds |

The 4 KB read in op 4 reveals the firmware-version detection
mechanism: **the version is encoded in the filename**. From the
captured directory entry:

```
SDS-100_V1_05.bin       -> MAIN firmware v1.05
SDS-100_V1_03_05.firm   -> SUB firmware v1.03.05
CityTable_V1_...DAT     -> firmware data table
ZipTable_V1_0...DAT     -> firmware data table
```

So the firmware-update API in our app is just:

1. Walk `BCDx36HP/firmware/` and parse filenames for installed versions.
2. HTTP-fetch the current version from Uniden.
3. If outdated, drop the new file.

The HPDB-update flow uses the same out-of-band HTTP pattern with
`hpdb.cfg`'s `DateModified` field as the local-version marker.

## Volume geometry + ops 1-2 detail (from earlier Phase 0a)

### Volume geometry

| Property | Value | Source |
|---|---|---|
| Volume size | ~131 MB | max LBA touched 0x3EEC2 (op 1), volume larger |
| Sector size | 512 bytes | SCSI READ_10 / WRITE_10 default |
| Filesystem | **FAT32** | not directly proven yet (boot sector wasn't captured), but FAT-mirroring pattern is unmistakable: 30 of 30 writes appear at two LBAs that differ by exactly 0x77A = 1914 sectors -> FAT1 + FAT2 mirror |
| Probable FAT regions | FAT1 ~0x3000-0x37FF, FAT2 ~0x3800-0x3FFF | Inferred from mirrored writes at 0x310C/0x3886, 0x3129/0x38A3, 0x310F/0x3889 |
| Probable data region start | LBA ~0x4000 (16384) | Most "directory" writes target 0x4080-0x4DA0 cluster |
| Probable end-of-volume reserved | LBA 0x3EE40-0x3EEC2 | small cluster of reads/writes near max LBA - looks like a backup boot sector or device-specific reserved region |

To confirm geometry: open the SDS100 in mass-storage mode, look at
the drive in `fsutil fsinfo ntfsinfo X:` (works for FAT too) or
`lsblk` / `diskpart` - this gives bytes-per-sector,
sectors-per-cluster, FAT-size, root-cluster directly.

### Op 1: "Read from Scanner" (414 KB capture, 51 SCSI commands)

| Phase | Time | Activity | Likely role |
|---|---:|---|---|
| 1 | 0-6 s | 24× TEST_UNIT_READY + 14× REQUEST_SENSE | Standard UMS housekeeping (Windows polling whether device is ready) |
| 2 | 6.3 s | 1× READ_10 31 blocks @ LBA 0x3EE40 (15.5 KB) | **Read scanner manifest** from the end-of-volume reserved area |
| 3 | 6.3-6.5 s | 3× WRITE_10 8 blocks @ 0x4080 + 1× READ_10 1 block @ 0x4E80 | Write a single FAT/dir block + read one sector (probably a "hello, I'm Sentinel" handshake file marker) |
| 4 | 6.4 s | 5× READ_10 8 blocks @ 0x4D80...0x4DA0 (20 KB consecutive) | **Read a cluster of small files** (consecutive cluster sectors, FAT-walked) |
| 5 | 6.5 s | READ_10 + READ_10 + WRITE_10 around 0x4240/0x3EEC0 | Manifest update |

Total transferred: ~42 KB read, 12 KB written. This op is **read-mostly metadata
sync** - Sentinel pulls the scanner's per-device config but doesn't extract HPDB
or full state.

### Op 2: "Write to Scanner" (2.1 MB capture, 120 SCSI commands)

| Phase | Time | Activity | Likely role |
|---|---:|---|---|
| 1 | 7.0-7.4 s | 22× WRITE_10, mostly to FAT mirror pairs (0x310C/0x3886, 0x3129/0x38A3, 0x310F/0x3889) and a writable cluster at 0x4080 | **Allocate filesystem space**: write FAT entries to claim free clusters, plus write the new directory entries pointing at them |
| 2 | 7.4-10.2 s | **24× READ_10 of 64 KB each** at consecutive LBAs 0x23440-0x240C0 (1.5 MB total, sequential) | **Read existing HPDB-or-similar file** for read-modify-write merge |
| 3 | 10.3-10.4 s | 8× WRITE_10 to FAT mirrors and dir entries | Commit metadata: update directory entries with new sizes / timestamps, finalize FAT chains |

Total transferred: 1.7 MB read, 78 KB written. The signature shape is
**"read-then-write on a FAT32 volume"** - exactly what a desktop
filesystem editor would do.

The 1.5 MB sequential read at LBA 0x23440 is the standout signal.
That offset times 512 = 73,827,328 bytes = position **74 MB into the
volume**. The file we're reading there is one of:

- The **HPDB favorites file** (consolidated single-file database;
  would be ~1-1.5 MB for a fully populated SDS100).
- The **CFG / global config file**.
- A **per-channel record file** that holds the full channel/system
  state.

We can disambiguate by:

1. Mounting the SDS100 in mass-storage mode and listing files.
2. Comparing each file's size to ~1.5 MB.
3. Computing each file's first-sector LBA and checking against 0x23440.

### Strings we already pulled (from raw byte search of pcaps)

Earlier free-form decoding revealed Sentinel manipulates these
content types (strings observed in the captured sectors):

- **HPDB record markers**: `HPDB`, `XWIX`, `XW.\`, `IX..`
- **HPDB record files**: `_000001.hpd ... _000113.hpd` (113 records),
  `f_000001.hpd ... f_000003.hpd` (3 files of a different class)
- **CFG payload structures**: `TargetModel.BCDx36HP`,
  `FormatVersion.1.00`, `ProductName.SDS100`, `GlobalSetting`,
  `LimitSearch.SrchId=...`, `BandDefault.BandId=...`,
  `DispOptItems.DispOptId=...`
- **List-style markers**: `LIST`, `_LIST`, `F_LIST`

The `_NNNNNN.hpd` numbering with up to 113 entries means the SD card
holds **per-record HPDB files**, not a single monolithic HPDB. So
the 1.5 MB read in op 2 is likely the **HPDB-INDEX or LIST file**
that catalogs all 113 records.

## Sentinel API surface (final)

```python
class SDS100MassStorage:
    def __init__(self, drive_letter: str): ...

    # Op 1: Read From Scanner / "Backup"
    def read_all(self) -> ScannerSnapshot: ...
    def read_scanner_inf(self) -> ScannerInf: ...
    def read_hpdb(self) -> HpdbDatabase: ...
    def read_favorites(self) -> list[FavoritesList]: ...
    def read_profile(self) -> ProfileConfig: ...

    # Op 2: Write to Scanner / "Restore"
    def write_snapshot(self, snap: ScannerSnapshot) -> None: ...
    def write_hpdb(self, hpdb: HpdbDatabase) -> None: ...
    def write_favorites(self, lists: list[FavoritesList]) -> None: ...
    def write_profile(self, profile: ProfileConfig) -> None: ...

    # Op 3: Get HPDB Update (HTTP-mediated)
    def get_installed_hpdb_version(self) -> str: ...           # parses hpdb.cfg
    def check_hpdb_update_available(self) -> bool: ...         # HTTP
    def install_hpdb_update(self, hpdb_zip: Path) -> None: ... # writes s_*.hpd

    # Op 4: Update Firmware (HTTP-mediated)
    def get_installed_firmware_versions(self) -> FirmwareVersions: ...  # walks BCDx36HP/firmware/
    def install_firmware(self, fw_image: Path, kind: Literal["main", "sub"]) -> None: ...
```

Backup and Restore are aliases (`backup() = read_all()` + save;
`restore() = write_snapshot()` of saved data) - not separate USB
operations. Sentinel's official surface is 4 ops, not 6.

## Open follow-up: capture an actual update

We have the "up-to-date" path for ops 3 and 4 (which is itself
useful: it confirms the version-check is HTTP-mediated and tells
us where Sentinel reads the firmware-version directory entry).
We don't yet have a capture of an actual HPDB or firmware update
that triggers WRITE_10s.

To capture an actual update we'd need either:
- Sentinel pointing to an internal/test version that's older than
  the latest, or
- A controlled stale-version setup (downgrade the SDS100 SUB or
  MAIN firmware to a known older version, then capture Sentinel
  performing a real upgrade).

The actual write pattern is **strongly predicted** by what we've
seen: `READ_10` of FAT-dir at LBA 0x4280, then `WRITE_10` of the
new `.bin` or `.firm` blob (filename version-encoded), then FAT
mirror updates on the way out. Same shape as op 2 ("Write to
Scanner") just with a different file.

## Future: full file-system inventory pass

Even before ops 3-6 land, we can extract enormous value from the
SD card directly:

```pwsh
# When SDS100 is in mass-storage mode and shows up as drive E:
Get-ChildItem -Path E:\ -Recurse -File | Select-Object FullName, Length, LastWriteTime > AI\Dev\RE\sessions\sds100_sd_inventory.txt
Get-Content E:\Internal\GlobalSetting.cfg | Out-File AI\Dev\RE\sessions\sds100_global_setting.txt
```

(Adjust drive letter and paths once we know them.) This walk will
tell us:

- Exact file naming convention (`_NNNNNN.hpd` vs `f_NNNNNN.hpd` etc.)
- File sizes (so we can identify the 1.5 MB file Sentinel read)
- Directory structure (`/Internal/`, `/HPDB/`, etc.)
- Timestamps (lets us correlate with capture timestamps)

This is **a 30-second job** the next time the user has the scanner
in mass-storage mode. We'll script it as
[`_dump_sd_inventory.ps1`](_dump_sd_inventory.ps1) so it's a single
button-press.
