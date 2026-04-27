# Active Workstreams

One row per stream. Keep this short. Move finished streams to the
`Recently completed` section, then delete after a release.

## Active

| Stream | Owner | Status | Where | Notes |
| --- | --- | --- | --- | --- |
| Multi-scanner backend (`scanner_profiles/`) | Other contributor (committed via `disturbedkh` upstream) | Foundation landed in `v0.9.0b2`. `ACTIVE_PROFILE` is wired but never reassigned at runtime. Migration of remaining module-level constants is pending. | `scanner_profiles/`, `scanner_manager.py`, `metastore.py`, `tests/test_scanner_profiles.py`, `tests/test_bt885_parity.py` | See `MULTI_SCANNER_BACKEND.md` for the full plan and don't-touch list. |
| **SDS100 profile (and SDS200 by extension)** | Local | SD-card RE complete (see `RE/SDS100.md`); live serial-mode RE in progress (Session 2 captured the MAIN-processor command port). Profile not yet implemented. | New `scanner_profiles/sds100.py` (planned), `data/scanner_profiles.json`, `tests/test_sds100_parity.py` (planned), plus changes to detection in `scanner_profiles/registry.py` or a new `detect_from_card()` helper. | Real card RE'd 2026-04-27 from `D:\` (FW 1.23.07). Live SDS100 Serial Mode RE same day: `MDL,SDS100`, full Remote Command Protocol on PID `0x001A` only. Tooling in `AI/Dev/RE/serial_probe.py` + `com6_listen.py`, captures in `AI/Dev/RE/sessions/`. SDS200 expected to share ~99% of code/data layout - one profile should cover both. |
| **SDS100 live-serial RE (passive read-only)** | Local | Session 1 + 2 done; mapped `MDL`/`VER`/`STS`/`GLG`/`PWR`/`VOL`/`SQL`/`GST`. Next: STS bit-decode by feature-toggle, GLG-during-RX capture, second whitelist batch (`RMB`, `WIN`, `DGR`, `RIN`, `LCB`, `BTV`, `BSV`, `SUM`, `PSI`). | `AI/Dev/RE/SDS100.md` (notes), `AI/Dev/RE/serial_probe.py`, `AI/Dev/RE/sessions/` | Strict rules: never send `KEY`/`PRG`/`EPG`/`JNT`/`JPM`/`WPL`/`WPS`/`CLR`/`DLA`/`MEMSET`/`WIPE`/`TGW`/`VLO`/`SLO`/`GLT`/`RST,SET`. Always probe COM matching `VID 1965 PID 001A`, never PID `0019`. |

## Backlog (not started)

| Stream | Trigger | Notes |
| --- | --- | --- |
| Detect-on-open scanner profile reassignment | After multi-scanner backend foundation lands | Step 1 of `MULTI_SCANNER_BACKEND.md`. **Blocks SDS100 profile** because `TargetModel` alone is insufficient on BCDx36HP-family cards (both BT885 and SDS100 write `TargetModel BCDx36HP`). Detector needs to read `scanner.inf`. |
| Retire `scanner_profiles/compat.py` | After all module-level constants in `scanner_manager.py` are migrated | Step 2 of `MULTI_SCANNER_BACKEND.md`. |
| Favorites Lists editor (SDS100 / SDS200) | After SDS100 profile lands | Round-trips today via the ancillary path; no UI to edit yet. |
| Discovery session reader | After we have a populated `discvery.cfg` to RE | Schema unknown until populated. |

## Recently completed

| Stream | Released in | Notes |
| --- | --- | --- |
| `scanner_profiles` package + `Bt885Profile` extraction | `v0.9.0b2` (2026-04-24) | First slice of multi-scanner work. |
| Map-tile coverage heatmap | `v0.9.0b2` | `tkintermapview` integration with fallback. |
| Multiple virtual SD card profiles + snapshot history | `v0.9.0b2` | `metastore.GlobalMetaStore` profiles, `<profile_dir>/.snapshots/`. |
| Plain-English UI sweep + tone linter | `v0.9.0b2` | Style guide enforced. |
