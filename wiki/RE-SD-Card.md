# RE: SD Card

> Status: shipped (v0.11.x) — on-disk layout for BT885 + SDS100 profiles.

> Where this fits: the FAT32 layout the BCDx36HP family writes to
> the microSD, and how its file shapes are the actual API our app
> (and Sentinel) uses for persistent edits. For the consolidated
> narrative start at [Reverse Engineering](Reverse-Engineering).

The SDS100, BT885, BCD436HP, BCD536HP, SDS200, and SDS150 all
write the same on-disk layout. We've imaged BT885 and SDS100
cards directly; the deltas are documented inline.

## Volume properties

| Property | BT885 | SDS100 | Notes |
|---|---|---|---|
| Filesystem | FAT32 | FAT32 | Always |
| Total size | 3.6 GiB | 7.5 GiB | Card-dependent |
| Volume label | (none) | (none) | Both |
| Sector size | 512 B | 512 B | Standard |

The volume's **content fingerprint is not a model differentiator**
in our app's `sdcard.py:_content_fingerprint` because BT885 and
SDS100 ship bit-identical `CityTable*.dat` and `ZipTable*.dat`
files (same SHA-256). Use volume serial + `scanner.inf` for
identity instead. See `Metacache/Dev/RE/docs/SD_CARD_COMPARISON.md`.

## Folder skeleton

Both BT885 and SDS100 have the **identical folder skeleton**.
The SDS100 just populates more of it.

```
<DRIVE>:\
└── BCDx36HP\                              <-- canonical scanner-data root
    ├── activity_log\                      (empty on stock card)
    ├── alert\                             (empty on stock card)
    ├── audio\
    │   ├── inner_rec\                     (empty on stock; populated when scanner records)
    │   └── user_rec\                      (empty on stock; populated by user record button)
    ├── discovery\
    │   ├── Conventional\                  (empty until Discovery sessions run)
    │   └── Trunk\                         (empty until Discovery sessions run)
    ├── favorites_lists\
    │   ├── f_list.cfg                     SDS100 populated; BT885 empty 42-B stub
    │   └── f_NNNNNN.hpd                   SDS100 only (per-favorite payload)
    ├── firmware\
    │   ├── CityTable_V1_00_00.dat         566,492 B   (bit-identical BT885 = SDS100)
    │   └── ZipTable_V1_00_00.dat          693,758 B   (bit-identical BT885 = SDS100)
    ├── HPDB\
    │   ├── hpdb.cfg                       state/county/agency master index
    │   └── s_NNNNNN.hpd                   per-state HPD payloads
    ├── scanner.inf                        identity / firmware versions
    ├── profile.cfg                        SDS100 only (giant settings file)
    ├── app_data.cfg                       SDS100 only (last-active state)
    └── discvery.cfg                       SDS100 only (discovery stub - sic, typo in firmware)
```

> The folder name `BCDx36HP` is the firmware **family**, not the
> scanner model. Treat it as fixed; never localise it.
> Likewise `discvery.cfg` is missing an `o` - this is a Uniden
> typo and we must preserve it verbatim.

## File-by-file reference

### `scanner.inf` - identity (always present)

3 records, tab-separated. Sample lines from each scanner:

```
# BT885
TargetModel	BCDx36HP
FormatVersion	1.00
Scanner	BT885-SCN	<SERIAL>	1.01.02 	01		1.00.00	1.00.00	0

# SDS100
TargetModel	BCDx36HP
FormatVersion	1.00
Scanner	SDS100	<SERIAL>	1.23.07 	01		1.00.00	1.00.00	0	1.03.05
```

The `Scanner` line is **the canonical model fingerprint**. Field 1
is the literal model string (`BT885-SCN` vs `SDS100`); field 9
is **only present on SDS100** and carries the SUB MCU firmware
version (BT885 has no SUB MCU).

| Idx | BT885 | SDS100 | Likely meaning |
|---:|---|---|---|
| 1 | `BT885-SCN` | `SDS100` | **Model fingerprint** |
| 2 | `41626-...` | `38326-...` | Serial / part number |
| 3 | `1.01.02` | `1.23.07` | MAIN firmware version |
| 4 | `01` | `01` | Hardware revision |
| 5 | (blank) | (blank) | Reserved |
| 6 | `1.00.00` | `1.00.00` | DSP firmware? |
| 7 | `1.00.00` | `1.00.00` | DSP firmware? |
| 8 | `0` | `0` | Reserved flag |
| 9 | (absent) | `1.03.15` | **SUB firmware (SDS100-only)** |

> Codebase note: `Bt885Profile.target_model_aliases =
> ("Beartracker885", "BearTracker885", "BT885")` is **stale**.
> Real BT885 firmware writes `TargetModel\tBCDx36HP`. Detect on
> `scanner.inf` field 1, not `TargetModel`.

### `HPDB/hpdb.cfg` - state/county/agency master index

The same shape on both cards; sizes differ:

- **BT885**: 178 KB - state-only index. The BT885 is happy with
  just-the-states.
- **SDS100**: 1.6 MB - state + county + agency index. The SDS100
  needs the deeper hierarchy for its bigger UI.

Sample lines:

```
TargetModel	BCDx36HP
FormatVersion	1.00
DateModified	04/07/2024 17:00:01
StateInfo	StateId=0	CountryId=0	_MultipleStates	
StateInfo	StateId=1	CountryId=1	Alabama	AL
...
```

Round-trip rule: preserve every record verbatim, including
trailing tabs.

### `HPDB/s_NNNNNN.hpd` - per-state HPDs

Tab-separated record-oriented format. The same record types appear
on both BT885 and SDS100 - **the SDS100 record set is a strict
superset**. Every record type the BT885 writes is also written by
the SDS100, just with extra trailing fields.

| Record | Purpose | BT885 fields | SDS100 fields |
|---|---|---:|---:|
| `Conventional` | Conventional system | 7 | 14 |
| `Trunk` | Trunked system | varies | varies |
| `Site` | Trunked site | ~10 | 13 |
| `T-Group` | Talkgroup category | varies | varies |
| `T-Freq` | Trunked control/voice | varies | varies |
| `TGID` | Talkgroup ID | varies | varies |
| `C-Group` | Conventional group | 8 | 10 |
| `C-Freq` | Conventional frequency | 7 | 17 |
| `AreaState` | State binding | 2 | 2 |
| `AreaCounty` | County binding | 2 | 2 |
| `BandPlan_Mot` | Motorola band plan | not used | observed |
| `FleetMap` | Motorola fleet map | not observed | observed |
| `DateModified` | Header | yes | **no** (BT885-only) |

The trailing tab fields on SDS100 are real and round-trip-significant
- preserve them. Our parser does. The empty trailing slots are
"feature slots" (lockout count, recording hold, per-channel volume,
etc.) that the firmware allocates but the user doesn't always
populate.

### `favorites_lists/` - SDS100 favourites system

BT885 has the empty 42-byte stub `f_list.cfg`; that's the only
indication on disk that the family format includes favourites.
The BT885 firmware lacks the UI to populate it. SDS100 fills it
in:

#### `f_list.cfg` (manifest)

One `F-List` row per favourite list. 116 columns:
- Idx 1: display name
- Idx 2: per-list payload filename (`f_NNNNNN.hpd`)
- Idx 3-118: 116 enable/disable slots (Quick Key + per-favorite-bit
  mask; exact slot semantics TBD)

Sample:

```
F-List	Alachua	f_000001.hpd	Off	Off	...   (116 columns)
F-List	Home	f_000002.hpd	Off	On	...
```

#### `f_NNNNNN.hpd` (per-favorite payloads)

Same record alphabet as `s_*.hpd` (Trunk / Site / T-Freq / T-Group
/ TGID / Conventional / C-Group / C-Freq) plus:

- **`DQKs_Status`** at the top of each system: 100-slot Department
  Quick Key on/off mask.
- Site rows have 13 fields (vs ~10 on BT885 state HPDs).
- No `Id` fields on records (favourites are name-keyed, not
  ID-keyed).

This is one of the things our app already reads/writes for the
SDS100 even though Sentinel is doing the same job - we have the
parser, we have the schema.

### `profile.cfg` - giant SDS100 settings (SDS100-only)

15.6 KB, 184 lines. Every SDS100-specific feature lives here.
Header lines:

```
TargetModel	BCDx36HP
FormatVersion	1.00
ProductName	SDS100
GlobalSetting	Off	Off		Off	Off	Off	2	100	Custom1	Custom2	Custom3	Off	Auto	0	2	Off	Off	Ignore	Normal	0
```

Major record types (~30):

| Record | Slots | Purpose |
|---|---:|---|
| `ProductName` | - | Model name |
| `GlobalSetting` | 20 | Global toggles (key beep, opening msg, charge time, contrast, attenuator) |
| `SearchCommon` | 12 | Search-mode global params |
| `PresetBroadcastScreen` | 5 | Pre-defined skip bands (FM, weather, ...) |
| `CustomBroadcastScreen` | 30 | 10 user-defined skip-bands |
| `CurrentLocation` | 3 | Last GPS fix (lat, lon, accuracy radius) |
| `GpsOption` | 2 | GPS coordinate display + serial baud |
| `ServiceType` | 36 | **36-slot service-type mask (vs BT885's 14)** |
| `CustomServiceType` | 10 | 10 user-defined service-type slots |
| `Weather` / `WxSameList` | several | Weather priority + SAME alerts |
| `DisplayOption`, `DispOptItems`, `DispColors` | many | Layout/colour customization |
| `Backlight`, `Battery`, `OwnerInfo`, `ClockOption` | - | Hardware settings |
| `RecordingOption`, `StandbyOption` | several | Recording + standby |
| `LimitSearch` | 10 rows × ~16 | User-defined limit-search ranges |
| `CloseCall` | ~16 | Close Call (RF nearest-frequency capture) |
| `ToneOut` | 32 rows | Paging tone-out slots |
| `Waterfall`, `CustomWfBand` × 10 | many | SDS100 waterfall display (not on BT885) |
| `WfColors` | 6 | Waterfall colour palette (hex) |
| `IfxFreqs` | - | Intermod frequencies |
| `BandDefault` | 31 | Per-band default mod + step |
| `QuickKeys` | 100 | Quick-key enable mask (not on BT885) |

Round-trip rule: capture every record verbatim. Don't rebuild
from a minimal field set or the firmware silently reverts to
defaults. Our parser already does this via opaque preservation
of unrecognised records.

### `app_data.cfg` - last-active state (SDS100-only)

386-486 bytes. Sample:

```
TargetModel	BCDx36HP
FormatVersion	1.00
ModeInfo	IDscan
ScanListType	FavoritesList	Home
ScanTrunkSystem	Off	Trunk	... (per-trunk state)
ScanT-Group	Off	T-Group	... (per-group state)
ScanSite	Off	Site	... (per-site state)
ScanT-Freq	T-Freq	... (per-freq state)
```

Treat as ephemeral. Don't merge or version. On a push, copy
verbatim.

### `discvery.cfg` (SDS100-only, sic - the typo is in the firmware)

42 bytes; just the standard header. Discovery records will be
appended after a Discovery session - we have not yet RE'd the
populated state.

### `firmware/` - firmware data tables

```
firmware/
├── CityTable_V1_00_00.dat    566,492 B   (bit-identical BT885 = SDS100)
└── ZipTable_V1_00_00.dat     693,758 B   (bit-identical BT885 = SDS100)
```

Already RE'd in `legacy_tk/geo_tables.py` (`FirmwareCityTable` /
`FirmwareZipTable`) and used by both scanner profiles. 47,204 city
records and 41,771 ZIPs respectively. Same SHA-256 across the family.

> **Never** delete or modify these files - the scanner refuses to
> boot without them. They're also where firmware updates are
> dropped (see [RE-Firmware](RE-Firmware) and
> [RE-Sentinel](RE-Sentinel)).

## What this means for our app

| Need | File(s) | Already supported in our parser? |
|---|---|---|
| Identify which scanner is mounted | `BCDx36HP/scanner.inf` field 1 | Yes — `detect_from_card()` in Qt (legacy Tk: manual profile) |
| Read/write per-state channel data | `BCDx36HP/HPDB/s_*.hpd` | Yes |
| Read/write favourites | `BCDx36HP/favorites_lists/f_*.hpd` + `f_list.cfg` | Yes (round-trip preservation; Favorites Lists editor UI backlog) |
| Read/write SDS100 settings | `BCDx36HP/profile.cfg` | Round-trip yes; record-level UI for edit pending |
| Drop a firmware update | `BCDx36HP/firmware/*.bin` (MAIN) or `*.firm` (SUB) | Yes — Firmware Updater dock + FTP discovery ([RE-Update-Endpoints](RE-Update-Endpoints)) |
| Backup everything | walk `BCDx36HP/` | Yes |
| Restore everything | walk `BCDx36HP/` in reverse | Yes |

This is the same set of operations Sentinel does (see
[RE-Sentinel](RE-Sentinel)). Our app does them with the additional
benefit of the MetaStore audit trail, virtual SD workspaces, and
RadioReference import - all features Sentinel doesn't have.

## Lab data

- `Metacache/Dev/RE/docs/SD_CARD_COMPARISON.md` - exhaustive BT885 vs SDS100 diff with raw bytes.
- `Metacache/Dev/RE/docs/BT885.md` - per-scanner SD-card RE notes.
- `Metacache/Dev/RE/docs/SDS100.md` - same for SDS100.
- `Metacache/Dev/RE/tools/sentinel/compare_cards.py` - read-only side-by-side script.
