# SD card side-by-side: BT885 vs SDS100

> **Canonical narrative is in the wiki**:
> [`wiki/RE-SD-Card.md`](../../../wiki/RE-SD-Card.md). This file is
> the lab notebook with the exhaustive byte-level diff.

> Captured 2026-04-27 on `<HOST>` from real cards. BT885 mounted
> at `E:\`, SDS100 at `H:\`. Both FAT32, both BCDx36HP-family.
>
> Reproduce with: `py AI\Dev\RE\compare_cards.py --bt E:\ --sds H:\`
> (read-only; full session is at
> `AI/Dev/RE/sessions/card_compare_20260427T171130.txt`).

This doc is the single source of truth for "what is the same, what is
different, and what we have / have not RE'd" across the two scanners
in the family. It supersedes the "what's new on SDS100" claims in
older notes.

---

## TL;DR

1. **The firmware data tables are bit-identical.** `CityTable_V1_00_00.dat`
   and `ZipTable_V1_00_00.dat` have the same SHA-256 on both cards
   (47,204 city records / 41,771 ZIPs respectively). The same parser
   (`FirmwareCityTable` / `FirmwareZipTable` in `scanner_manager.py`)
   produces identical output on both. **They can be bundled once and
   shared by every scanner in the family.**
2. **The folder skeleton is identical.** Both cards have the full
   `BCDx36HP/{activity_log,alert,audio/{inner_rec,user_rec},discovery/{Conventional,Trunk},favorites_lists,firmware,HPDB}/`
   tree on disk. Most are empty on the BT885 because the firmware has
   no UI for those features; the dirs still exist.
3. **`TargetModel` is `BCDx36HP` on both scanners.** Verified on a real
   BT885 card. The codebase aliases
   (`("Beartracker885", "BearTracker885", "BT885")`) are stale - they
   never matched real hardware. **Detection must read `scanner.inf`'s
   `Scanner` field 1, not `TargetModel`.**
4. **HPD record types are a strict superset on the SDS100.** Every
   record type the BT885 writes is also written by the SDS100. The
   SDS100 adds extra trailing tab fields per record (more feature
   slots) and a few new record types
   (`BandPlan_Mot`, `DQKs_Status`, `Trunk` extra fields) plus the
   favorites-list HPD shape (still composed of the same primitive
   record types).
5. **What's truly SDS100-only on the card** = `app_data.cfg`,
   `discvery.cfg`, `profile.cfg`, populated `f_list.cfg` +
   `favorites_lists/f_*.hpd`. The BT885 ships an empty 42-byte
   `f_list.cfg` stub but no other config files.
6. **The BT885 SD card ships with an installer.** `E:\Setup\` contains
   the Uniden BT885 Update Manager MSI plus its bootstraps (.NET 4.0
   client, Windows Installer 3.1). `data/uniden_installers.json`
   already declares `bt885_update_manager`; the SD card is the
   factory-shipped copy. No equivalent is shipped on the SDS100 card
   (Sentinel for SDS100 is downloaded from Uniden's website).

---

## Volumes

| Card | Drive | Filesystem | Size | Used | Free |
| --- | --- | --- | --- | --- | --- |
| BT885 | `E:\` | FAT32 | 3,856,662,528 B (~3.6 GiB) | 137 MB | 3.55 GiB |
| SDS100 | `H:\` | FAT32 | 8,026,849,280 B (~7.5 GiB) | 58 MB | 7.42 GiB |

Both are removable mass-storage volumes. Neither uses a volume label.

---

## File inventory diff

### Files present on **BT885 only**

```
Setup\setup.exe                                              428,032 B   Uniden BT885 Update Manager (factory)
Setup\Setup.msi                                            6,188,032 B
Setup\DotNetFX40Client\dotNetFx40_Client_x86_x64.exe      43,000,680 B   .NET 4.0 client redist
Setup\WindowsInstaller3_1\WindowsInstaller-KB893803-...   2,585,872 B   Windows Installer 3.1
BCDx36HP\HPDB\s_000012.hpd.meta.json                      10,792,470 B   *** scanner-manager sidecar
BCDx36HP\HPDB\s_000012.hpd.session.bak                       869,806 B   *** scanner-manager sidecar
BCDx36HP\HPDB\s_000012.hpd.reconcile_*.log                   862,064 B   *** scanner-manager sidecar
scanner-workspaces\Main\...                              (~25 MB tree)  *** scanner-manager virtual SD profile mirror
```

The `scanner-workspaces\Main\` tree is **our app's** virtual SD card
profile feature persisting a copy back to the physical card. The
Uniden firmware ignores it. Treat the entire `scanner-workspaces\`
hierarchy as opaque to RE - it's a mirror of the live `BCDx36HP\`
tree, not a separate Uniden artifact.

### Files present on **SDS100 only**

```
BCDx36HP\app_data.cfg                388 B   Last-active state on power-down
BCDx36HP\discvery.cfg                 42 B   42-byte stub: header only (sic - "discvery")
BCDx36HP\profile.cfg              15,612 B   Giant settings file (184 lines)
BCDx36HP\favorites_lists\f_000001.hpd   3,662 B   Populated favorites list "<COUNTY>"
BCDx36HP\favorites_lists\f_000002.hpd   4,922 B   Populated favorites list "Home"
BCDx36HP\favorites_lists\f_000003.hpd   2,305 B   Populated favorites list "Williston"
```

These are the SDS100-specific files. Nothing on the BT885 corresponds
to `profile.cfg` or `app_data.cfg`.

### Files present on **both**

| Path | BT885 | SDS100 | SHA-256 same? |
| --- | ---: | ---: | :---: |
| `BCDx36HP\firmware\CityTable_V1_00_00.dat` | 566,492 B | 566,492 B | yes (`e59c0e03...`) |
| `BCDx36HP\firmware\ZipTable_V1_00_00.dat` | 693,758 B | 693,758 B | yes (`69ea964e...`) |
| `BCDx36HP\favorites_lists\f_list.cfg` | 42 B (stub) | 1,498 B (3 F-Lists) | no |
| `BCDx36HP\scanner.inf` | 112 B | 117 B | no |
| `BCDx36HP\HPDB\hpdb.cfg` | 177,902 B | 1,610,512 B | no |
| `BCDx36HP\HPDB\s_*.hpd` (per-state) | various | various | no |

The same-name common files differ only in payload, not in shape.

### Empty directory skeleton (present on **both** cards)

```
BCDx36HP\activity_log\
BCDx36HP\alert\
BCDx36HP\audio\inner_rec\
BCDx36HP\audio\user_rec\
BCDx36HP\discovery\Conventional\
BCDx36HP\discovery\Trunk\
BCDx36HP\favorites_lists\
```

Earlier RE notes (and `RE/SDS100.md` before this diff was run)
described these as "what's new on SDS100" - that was wrong. The
folders are part of the BCDx36HP firmware spec; the BT885 just never
populates them because it has no UI for favorites / discovery /
audio recording / activity log / alerts.

---

## `scanner.inf` differences

Both files share the same shape (TSV, 3 records). They differ in
field count on the `Scanner` row.

```
# BT885
TargetModel	BCDx36HP
FormatVersion	1.00
Scanner	BT885-SCN	<SERIAL>	1.01.02 	01		1.00.00	1.00.00	0
                ^                       ^                        ^
                model                   firmware                 (no extra trailing field)

# SDS100
TargetModel	BCDx36HP
FormatVersion	1.00
Scanner	SDS100	<SERIAL>	1.23.07 	01		1.00.00	1.00.00	0	1.03.05
                ^                       ^                        ^
                model                   MAIN firmware            10th field = SUB firmware
```

| Index after `Scanner` | BT885 | SDS100 | Best guess |
| ---: | --- | --- | --- |
| 1 | `BT885-SCN` | `SDS100` | **Model fingerprint** |
| 2 | `<SERIAL>` | `<SERIAL>` | Serial / part number |
| 3 | `1.01.02 ` | `1.23.07 ` | MAIN firmware version (trailing space is real) |
| 4 | `01` | `01` | Hardware revision? |
| 5 | (empty) | (empty) | Reserved |
| 6 | `1.00.00` | `1.00.00` | DSP firmware? |
| 7 | `1.00.00` | `1.00.00` | DSP firmware? |
| 8 | `0` | `0` | Reserved |
| 9 | - | `1.03.05` | **SDS100 only**: SUB-processor firmware version |

Field 9 is **only present on the SDS100** because that scanner has
the second SUB MCU (the bootloader CDC port we identified in serial
RE). BT885 has no SUB processor and the field is absent.

**Detection rule for the family:** read `Scanner` row, split on `\t`,
field 1 is the canonical model.

---

## HPD record-shape differences

The two scanners write the **same record types** for the same data,
but with different field counts.

### Record-type tallies for `s_000010.hpd` (Delaware)

| Record | BT885 | SDS100 |
| --- | ---: | ---: |
| `TargetModel` | 1 | 1 |
| `FormatVersion` | 1 | 1 |
| `DateModified` | 1 | **0** |
| `Conventional` | 7 | 14 |
| `Trunk` | 3 | 15 |
| `Site` | 21 | 38 |
| `T-Group` | 66 | 86 |
| `T-Freq` | 108 | 165 |
| `C-Group` | 27 | 82 |
| `C-Freq` | 117 | 419 |
| `TGID` | 390 | 900 |
| `AreaState` | 10 | 29 |
| `AreaCounty` | 10 | 29 |
| `BandPlan_Mot` | 0 | 5 |

### Header difference

- **BT885** writes `TargetModel` + `FormatVersion` + `DateModified`.
- **SDS100** writes `TargetModel` + `FormatVersion` only.

`DateModified` is BT885-specific. The HPD parser must continue to
handle it as optional (it already does - `header_records` accepts
arbitrary key/value pairs).

### `Conventional` row width

```
# BT885 (7 fields after the record name)
Conventional	CountyId=312	StateId=10	Kent	Off	04/14/2026 09:59:07	Conventional

# SDS100 (14 fields - adds 7 trailing empty slots)
Conventional	CountyId=312	StateId=10	Kent	Off		Conventional								
```

The trailing tabs are real and must be preserved on round-trip. The
SDS100 carries unused-but-allocated feature slots; the BT885 only
writes what it can populate.

### `C-Group` row trailing fields

- **BT885**: ends at `Circle` (8 fields after record name, last is shape).
- **SDS100**: ends at `Off	Global` (10 fields - last two are
  per-group flags, likely "favorite-list flag" and "scope" =
  Global / Local).

### `C-Freq` row trailing fields

- **BT885**: 7 fields (CFreqId, CGroupId, name, on/off, freq, mod, tone, attenuator).
- **SDS100**: 17 fields - the first 8 match BT885, then ~10 more empty
  trailing slots (likely lock-out count, recording hold time,
  per-channel volume, etc.).

### New record types on SDS100

- `BandPlan_Mot` - Motorola band plan rows. Observed in trunked HPDs;
  not in BT885's HPDs because the BT885 doesn't auto-discover band
  plans.
- `DQKs_Status` - Department Quick Key on/off mask **inside favorites
  HPDs** (`f_*.hpd`). 100 `On`/`Off` slots per row, one per DQK.

### Round-trip rule

Anything we don't explicitly understand, **preserve verbatim**. Don't
strip trailing tabs. Don't normalize empty fields. The parser already
does this via `record.fields = parts[1:]` and writer emits all parts
joined with `\t`; verify that is still true after any refactor.

---

## `favorites_lists/` shapes

### `f_list.cfg` (manifest)

- **BT885**: 42 bytes, header-only stub
  (`TargetModel\tBCDx36HP\r\nFormatVersion\t1.00\r\n`). Always empty
  on real BT885 hardware - the scanner has no UI to populate favorites.
- **SDS100**: 1,498 bytes, populated. One `F-List` row per favorites
  list, each row has 116 tab-separated columns:
  `F-List` + name + filename + 113 enable/disable slots (one per
  Department Quick Key + per-favorite-bit?). Exact slot semantics TBD
  but the count is consistent across rows.

### `f_*.hpd` (per-favorite payloads, SDS100 only)

Same record-type alphabet as state HPDs: `Trunk` / `Site` / `T-Group`
/ `T-Freq` / `TGID` / `Conventional` / `C-Group` / `C-Freq`. Plus:

- **`DQKs_Status`** row at the top of each trunk/conventional system
  - the per-system DQK enable mask (100 slots).
- **`Site` rows have 13 fields on SDS100 vs ~10 on BT885 state HPDs**
  - the extra fields are Standard / Wide modulation flags and
    site-search defaults.

Sample (Florida `Home` list, `f_000002.hpd`, first 5 lines):

```
TargetModel	BCDx36HP
FormatVersion	1.00
Trunk			<TRUNK_SYSTEM>	Off		P25Standard	Off	Off	Auto	Ignore	Srch	Off	Off	0	Off	Off	Analog	Off	Off	On	NEXEDGE
DQKs_Status		On	On	On	On	On	On	On	On	... (100 slots total) ...
Site			Simulcast	Off	<LAT>	<LON>	24.0	AUTO	Standard	Wide	Circle	Off	400	Auto	8	Off	4D2	Global
```

---

## What this means for the codebase

| Today | What real cards say | Action |
| --- | --- | --- |
| `Bt885Profile.target_model_aliases = ("Beartracker885","BearTracker885","BT885")` | BT885 writes `TargetModel\tBCDx36HP` | Aliases were never accurate. Stop matching on `TargetModel` for model-detection. Switch to `scanner.inf` `Scanner` field 1. |
| `Bt885Profile.card_identity_files = ["hpdb.cfg"]` | Real BT885 keeps `hpdb.cfg` under `BCDx36HP\HPDB\` | Update to `["BCDx36HP/HPDB/hpdb.cfg", "BCDx36HP/scanner.inf"]`. Same path works on SDS100. |
| `data/scanner_profiles.json` `match_target_model` for BT885 = `["Beartracker885", ...]` | Stale. | Add `match_scanner_inf: ["BT885-SCN", "BT885*"]` and demote `match_target_model` to a fallback. |
| Tests use `TargetModel\tBeartracker885` fixtures (`tests/test_sdcard.py`, `tests/test_metastore.py`, `tests/test_merge_and_zip.py`) | BT885 firmware writes `TargetModel\tBCDx36HP` | Update fixtures to match real hardware. The change is mechanical but touches several test files. |
| `_PREFERRED_INSTALLERS` for BT885 includes `bt885_update_manager` | Confirmed: shipped at `E:\Setup\setup.exe` on the BT885 SD card | No change. Optional: detect the in-card installer path and surface a "run installer from card" shortcut. |
| `RE/SDS100.md` "what's new on SDS100" lists `activity_log/`, `alert/`, `audio/`, `discovery/`, `favorites_lists/` empty dirs | These dirs exist on the BT885 too | Move those out of the "new" list - they're family-wide. The "new" list shrinks to: `app_data.cfg`, `discvery.cfg`, `profile.cfg`, populated favorites HPDs, populated `f_list.cfg`, populated `discovery/` payload (when in use). |
| `_content_fingerprint` digests first 1 MB of `ZipTable*.dat` + `CityTable*.dat` + TargetModel | Both cards have the same firmware tables and the same TargetModel | Confirmed: **the content fingerprint will collide between BT885 and SDS100 cards**. Already documented; reaffirmed here. Volume serial + `scanner.inf` is the real fingerprint. |

The full TODO list lives in `WORKSTREAMS.md` and `MULTI_SCANNER_BACKEND.md`.

---

## Reproduction tooling

Everything in this doc is reproducible by running:

```powershell
py AI\Dev\RE\compare_cards.py --bt E:\ --sds H:\ --sample-hpd s_000010.hpd
```

The script is read-only. It hashes the binary firmware tables, runs
the live `FirmwareZipTable` / `FirmwareCityTable` parsers from
`scanner_manager.py` against both cards, samples the requested per-state
HPD's record-type tally on each card, and compares text headers of
`scanner.inf` and `hpdb.cfg`. Output is suitable for piping into
`AI/Dev/RE/sessions/`.
