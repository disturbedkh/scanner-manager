# RE: SD Card

> Status: shipped (v0.11.x) — on-disk layout for BT885 + SDS100 profiles.

> Where this fits: the FAT32 layout the BCDx36HP family writes to
> microSD — the real API Sentinel and our app use for persistent
> edits. Start at [Reverse Engineering](Reverse-Engineering).

## What this answers

What lives under `BCDx36HP/` on BT885 vs SDS100, which files are
round-trip-safe, and how to fingerprint a mounted card without
trusting `TargetModel`.

## Known vs OPEN

| Topic | State | Notes |
|---|---|---|
| Folder skeleton (family-wide) | DONE | Identical dirs; SDS100 populates more |
| `scanner.inf` model fingerprint | DONE | Field 1 = model; field 9 = SUB (SDS-only) |
| HPD record alphabet + SDS trailing fields | DONE | Parser in `core/hpd.py` |
| Favorites (`f_list.cfg` + `f_*.hpd`) | DONE (round-trip); UI backlog | |
| `profile.cfg` (~30 record types) | Round-trip DONE; record-level UI OPEN | |
| Populated `discvery.cfg` / discovery payloads | OPEN | Stub only on imaged cards |
| SDS150 / SDS200 card image | OPEN | Expected same family layout |

## Deep dive

We've imaged BT885 and SDS100 cards directly. SDS200 is expected to
match SDS100 (~99% shared per lab); confirm when a card is available.

### Volume properties

| Property | BT885 | SDS100 | Notes |
|---|---|---|---|
| Filesystem | FAT32 | FAT32 | Always |
| Total size | 3.6 GiB | 7.5 GiB | Card-dependent |
| Volume label | (none) | (none) | Both |
| Sector size | 512 B | 512 B | Standard |

Content fingerprint via `CityTable`/`ZipTable` SHA-256 is **not** a
model differentiator (bit-identical across family). Use volume serial
+ `scanner.inf` instead. See
`Metacache/Dev/RE/docs/SD_CARD_COMPARISON.md`.

### Folder skeleton

```
<DRIVE>:\
└── BCDx36HP\                              <-- canonical scanner-data root
    ├── activity_log\                      (empty on stock card)
    ├── alert\                             (empty on stock card)
    ├── audio\
    │   ├── inner_rec\
    │   └── user_rec\
    ├── discovery\
    │   ├── Conventional\
    │   └── Trunk\
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
    └── discvery.cfg                       SDS100 only (discovery stub - sic)
```

`BCDx36HP` is the firmware **family** name, not the model. Preserve
`discvery.cfg` spelling — Uniden typo.

### File-by-file (summary)

**`scanner.inf`** — 3 tab-separated records. `Scanner` field 1 is the
canonical model fingerprint (`BT885-SCN` vs `SDS100`). Field 9 (SUB
FW) exists only on SDS100. Detect on field 1, **not** `TargetModel`
(both write `TargetModel\tBCDx36HP`).

**`HPDB/hpdb.cfg`** — same shape; BT885 ~178 KB (state-only), SDS100
~1.6 MB (state + county + agency). Preserve trailing tabs.

**`HPDB/s_*.hpd`** — SDS100 record set is a **strict superset** of
BT885 (extra trailing fields). Preserve empties — they are feature
slots. See lab comparison for per-record field counts.

**`favorites_lists/`** — BT885: empty `f_list.cfg` stub. SDS100:
populated `F-List` rows + `f_*.hpd` with `DQKs_Status` masks.

**`profile.cfg`** — SDS100-only (~15.6 KB, ~30 record types:
`GlobalSetting`, `ServiceType`, `Waterfall`, `QuickKeys`, …).
Round-trip verbatim; don't rebuild from a minimal field set.

**`app_data.cfg`** — ephemeral last-active scan state; copy verbatim
on push.

**`firmware/CityTable_*.dat` + `ZipTable_*.dat`** — required for boot;
parsed in `legacy_tk/geo_tables.py`. **Never delete or modify.**
Firmware update drops (`.bin` / `.firm`) also land here — see
[RE-Firmware](RE-Firmware).

### What this means for our app

| Need | File(s) | Supported? |
|---|---|---|
| Identify mounted scanner | `scanner.inf` field 1 | Yes — `detect_from_card()` in Qt |
| Channels | `HPDB/s_*.hpd` | Yes |
| Favourites | `favorites_lists/` | Round-trip yes; editor UI backlog |
| SDS100 settings | `profile.cfg` | Round-trip yes; record UI pending |
| Firmware drop | `firmware/*.bin` / `*.firm` | Yes — Firmware Updater + FTP |
| Backup / restore | walk `BCDx36HP/` | Yes |

Same ops Sentinel does ([RE-Sentinel](RE-Sentinel)), plus MetaStore
audit trail, workspaces, and RR import.

## Lab pointers

| Path | Role |
|---|---|
| `Metacache/Dev/RE/docs/SD_CARD_COMPARISON.md` | Exhaustive BT885 vs SDS100 diff |
| `Metacache/Dev/RE/docs/BT885.md` | BT885 SD-card RE notes |
| `Metacache/Dev/RE/docs/SDS100.md` | SDS100 SD-card + serial lab notebook |
| `Metacache/Dev/RE/tools/sentinel/compare_cards.py` | Read-only side-by-side |
| `Metacache/Dev/RE/tools/sentinel/dump_sd_inventory.ps1` | Mounted-card inventory |
| `Metacache/Dev/RE/sessions/` | Inventory dumps / probe notes |
