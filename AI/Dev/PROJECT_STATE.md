# Project State

_Last refreshed: 2026-04-27 (afternoon)._
_Cross-machine handoff: this snapshot reflects the SDS100 SD-card RE
plus a live serial-mode RE session against a connected SDS100. See
`AI/Dev/RE/SDS100.md` for full notes and `AI/Dev/RE/sessions/` for
raw probe captures._

## Snapshot

| Field | Value |
| --- | --- |
| Repo | (this repo) |
| Default branch | `main` |
| Latest commit | `fb75913` - "Fix ruff lint errors on main (post-v0.9.0b2)" |
| Latest tag | `v0.9.0b2` (2026-04-24) |
| Status | **0.9.0 alpha/beta**, core feature-complete, polish + multi-scanner refactor in flight |
| Languages | Python 99.5%, PowerShell 0.5% |
| Min Python | 3.9+ with Tkinter |

## Top-level layout

```
scanner-manager/
├── scanner_manager.py          # main app (~13,800 lines, single-file Tk UI)
├── metastore.py                # MetaStore + GlobalMetaStore (callsign index, profiles, snapshots)
├── sdcard.py                   # SD card read/write, ZipTable / CityTable
├── coverage_maps.py            # ZIP/GPS coverage simulation, heatmap math
├── rr_api.py                   # RadioReference HTML scrape + SOAP (zeep)
├── uniden_tools.py             # Sentinel / BT885 Update Manager detection
├── updater.py                  # in-app self-update via Help -> Check for Updates
├── scanner_profiles/           # NEW: per-model driver layer (see MULTI_SCANNER_BACKEND.md)
│   ├── base.py                 #   ScannerProfile ABC
│   ├── bt885.py                #   Uniden BearTracker 885 profile (only shipping profile)
│   ├── registry.py             #   register_profile / get_profile / target-model lookup
│   ├── compat.py               #   transitional shim re-exporting old module-level names
│   └── __init__.py
├── data/
│   ├── scanner_profiles.json   #   manifest of known profiles
│   ├── uniden_installers.json  #   installer download URLs + SHA-256 (not redistributed)
│   └── zip_county_map_sample.json
├── tests/                      # pytest; key files for the multi-scanner work:
│   ├── test_scanner_profiles.py
│   ├── test_bt885_parity.py    #   PARITY CANARY - keep green
│   ├── test_metastore.py
│   ├── test_merge_and_zip.py
│   └── test_sdcard.py
├── docs/
│   └── adding-a-scanner.md     #   how to add a second profile
├── packaging/                  # PyInstaller spec, installer scripts
├── scripts/                    # build / dev helpers
├── wiki/                       # checked-in wiki sources
├── pyproject.toml
├── requirements.txt
├── requirements-dev.txt
├── CHANGELOG.md
├── CONTRIBUTING.md
├── DISCLAIMER.md
├── SECURITY.md
├── THIRD_PARTY_NOTICES.md
└── LICENSE                     # MIT
```

## Run / dev commands

```powershell
# from repo root
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt
python -m pip install -e .

# launch the desktop app
scanner-manager
# or:
python -m scanner_manager   # if entry point not registered yet on this machine

# tests
pytest -q
pytest tests/test_scanner_profiles.py tests/test_bt885_parity.py -q

# lint
ruff check .
```

## What is _not_ in git locally

- `.venv/`, `__pycache__/`, `.pytest_cache/`, `.ruff_cache/` (gitignored).
- `app_settings.json` - **user state, not tracked**. Includes RR
  credentials reference, last SD card path, tool overrides.
- Any `*.backup_*` files emitted by the app (gitignored).

## Known good points

- Default profile resolves: `get_profile("uniden_bt885")` returns
  `Bt885Profile`.
- Parity test `tests/test_bt885_parity.py` enforces that
  `scanner_manager.SERVICE_TYPES`, `SCANNABLE_TYPES`, and
  `SERVICE_TYPE_HELP_TEXT` match what `Bt885Profile` exposes.
- `scanner_manager.ACTIVE_PROFILE` is the single agreed-upon way to
  reach profile data from inside the main app today.

## Open questions / TODOs known at refresh time

- `ACTIVE_PROFILE` is set at import time and never reassigned.
  `scanner_manager.py:144` says "when multi-scanner support lands, the
  workspace open path flips this to match the HPD's TargetModel
  header" - that flip is **not yet implemented**. See
  `MULTI_SCANNER_BACKEND.md` for the plan.
- **`TargetModel` is not a per-model id in the BCDx36HP family.**
  Confirmed against a real SDS100 card and a real BT885 card on
  2026-04-27 - **both** write `TargetModel\tBCDx36HP` in every
  header. The detector must read
  `BCDx36HP/scanner.inf`'s `Scanner` line, field 1, to get the actual
  model (`BT885-SCN` vs `SDS100`). The current
  `Bt885Profile.target_model_aliases = ("Beartracker885", ...)` is
  **stale** - real BT885 hardware never writes `Beartracker885`.
  See `AI/Dev/RE/SD_CARD_COMPARISON.md` and `AI/Dev/RE/BT885.md`.
- Sidecars carry a nullable `scanner_profile_id`; nothing writes a
  non-null value yet.
- `scanner_profiles/compat.py` exists specifically to avoid renaming
  every call site at once. Long-term we should retire it.
- **SDS100 / SDS200 profile not implemented.** SD-card RE complete
  for both BT885 and SDS100 (side-by-side diffed); live serial-mode
  RE in progress. Implementation plan lives in `AI/Dev/RE/SDS100.md`.
- **Firmware data tables are bit-identical across the family.**
  `firmware/CityTable_V1_00_00.dat` and `firmware/ZipTable_V1_00_00.dat`
  have the same SHA-256 on a real BT885 card and a real SDS100 card.
  Same parser, same output. The bundled-tables-per-family approach
  is justified.

## Live SDS100 RE - latest state (2026-04-27 PM)

- Scanner connected via USB, in **Serial Mode**
  (period key at boot prompt). Enumerates **two** Uniden CDC ports:
  - `VID 1965 PID 0019` = SUB processor bootloader (NOT useful for
    command-surface RE; only `M*`/`V*` first-char triggers)
  - `VID 1965 PID 001A` = **MAIN processor command port - full Uniden
    Remote Command Protocol** (`MDL,SDS100\r`, `VER,Version 1.23.07\r`,
    `STS`, `GLG`, `PWR`, `VOL`, `SQL`, `GST` all working)
- 8 of 36 whitelisted commands work; 22 return clean `ERR` (recognized
  but require Programming Mode or are SDS100-unsupported).
- Tooling lives in `AI/Dev/RE/`:
  - `serial_probe.py` - read-only probe with hard-coded forbidden list
    (`KEY`, `PRG`, `EPG`, `JNT`, `JPM`, `WPL`, `WPS`, `CLR`, `DLA`,
    `MEMSET`, `WIPE`, `TGW`, `VLO`, `SLO`, `GLT`, `RST,SET`)
  - `com6_listen.py` - listen-only baud-sweep (no writes)
  - `sessions/` - timestamped raw captures (committed for
    cross-machine reproducibility)
- Pyserial dependency installed via user-site (`py -m pip install
  --user pyserial`).
- Next planned passes (all read-only, COM6 only):
  1. STS payload bit-decoding by toggling scanner features
  2. GLG capture during a real transmission
  3. Vet + add a second batch of read-only mnemonics (`RMB`, `WIN`,
     `DGR`, `RIN`, `LCB`, `BTV`, `BSV`, `SUM`, `PSI`)
