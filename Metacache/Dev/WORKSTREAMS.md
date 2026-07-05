# Active Workstreams

> Status: shipped (v0.11.x) — living index; move finished streams to
> `Recently completed`, then trim after the next release.

One row per stream. Keep this short.

## Active

| Stream | Owner | Status | Where | Notes |
| --- | --- | --- | --- | --- |
| **SDS100 live-serial RE (passive read-only)** | Local | Sessions 1–6 done. Session 6 added SUB-port systematic probe, MAIN arg-extension probes, BCDx36HP legacy probes. Catalog: `Metacache/Dev/RE/docs/SDS100_unofficial_commands.md`. **35 untriggered Sub printf format strings** remain as probe targets. | `Metacache/Dev/RE/docs/SDS100.md`, `Metacache/Dev/RE/docs/SDS100_unofficial_commands.md`, `Metacache/Dev/RE/tools/probes/serial_probe.py`, `Metacache/Dev/RE/tools/probes/sub_probe.py`, `Metacache/Dev/RE/sessions/` | Strict read-only rules unchanged. **Phase 4 (Sentinel USB capture) pending user time** — workflow in `Metacache/Dev/RE/docs/sentinel_capture.md`. |
| **SDS100 firmware static RE** | Local | Sub payload extracted Session 6. Container parser corrected: Sub firmware is plaintext ARM Cortex-M. Main `.bin` remains encrypted. | `Metacache/Dev/RE/docs/SDS100_firmware.md`, `Metacache/Dev/RE/docs/ghidra_import_runbook.md`, `Metacache/Dev/RE/firmware/` | **Phase 6.2 (Ghidra import) is the unblocker** for full Sub disassembly — runbook ready. |
| **Waterfall / spectrum view** | Local | Qt live-dock FFT+waterfall (SUB `d`/`v`/`m`). Peak-hold leak fixed 2026-06-26; marker, max-hold-time, dBFS calibration added. | `gui/live/`, `scanner_drivers/serial_sub.py`, `tests/test_qt_live.py`, `Metacache/Dev/RE/docs/SDS100_waterfall.md` | Backlog items need live SDS100/200 to verify; all read-only. |
| **Build system Phase 2 tail** | Local | Tiered pytest, lockfile, SonarCloud primary gate landed. VPS compliance mirror on self-hosted SonarQube (`sonar` runner tag). | `.gitlab-ci.yml`, `Metacache/Dev/BUILD_SYSTEM.md`, `Metacache/Dev/SONARQUBE.md`, `Metacache/ROADMAP.md` | Pending: first green dual-scan baseline (`sonar_compare.ps1`). |
| **Multi-scanner backend (residual)** | Local | Two profiles shipped. `set_active_profile()` + Qt device selector reassign at runtime. Legacy Tk `ACTIVE_PROFILE` still import-time only. | `scanner_profiles/`, `core/device_manager.py`, `gui/header.py`, `tests/test_scanner_profiles.py`, `tests/test_bt885_parity.py`, `tests/test_sds100_profile.py` | See `MULTI_SCANNER_BACKEND.md`. Remaining: migrate legacy Tk globals, retire `compat.py`, auto-detect on card load. |

## Backlog (not started)

| Stream | Trigger | Notes |
| --- | --- | --- |
| Auto profile switch on card load | User opens SD card / workspace | `detect_from_card()` shipped; Qt shows mismatch banner only. Wire full reassignment + persist `scanner_profile_id` on workspace sidecar. |
| Legacy Tk `detect_from_card` | After Qt path stable | Tk open dialog still assumes BT885. |
| Update BT885 test fixtures and aliases | Ongoing cleanup | Replace `TargetModel\tBeartracker885` fixtures with `BCDx36HP`. Drop stale `Beartracker885` alias from `Bt885Profile.target_model_aliases`. See `Metacache/Dev/RE/docs/BT885.md`. |
| Retire `scanner_profiles/compat.py` | After legacy Tk globals migrated | Step 2 of `MULTI_SCANNER_BACKEND.md`. |
| Favorites Lists editor (SDS100 / SDS200) | User demand | Round-trip via ancillary path; no dedicated UI yet. |

## Recently completed

| Stream | Released in | Notes |
| --- | --- | --- |
| **SDS100 profile (and SDS200 by extension)** | `v0.11.x` | `scanner_profiles/sds100.py`, `data/scanner_profiles.json`, `tests/test_sds100_profile.py`, `detect_from_card()` in `registry.py`. |
| **Multi-device GUI (top selector)** | `v0.11.x` | `gui/header.py`, `core/device_manager.py`, `data/devices.json`, `gui/devices_dialog.py`. As-built: `MULTI_DEVICE_GUI.md`. |
| **In-app firmware updater** | `v0.11.x` | `firmware/{library,ftp_client,updater}.py`, `gui/firmware/firmware_dock.py`. Uses `data/uniden_installers.json` + FTP discovery (not `firmware_manifest.json` yet). As-built: `FIRMWARE_UPDATER.md`. |
| **Streaming server + Qt dock** | `v0.11.x` | `streaming/server.py`, `gui/streaming/streaming_dock.py`. |
| **Qt 0.11.0 UI features** | `v0.11.0` | Virtual scanner faceplate, Live/Monitoring tabs, location sim bar, editor overhaul. |
| **Metacache GitHub export** | `v0.11.1` | `Metacache/EXPORT_POLICY.md`, `scripts/metacache_export_rules.yaml`, selective export in `publish_github.ps1`. |
| **Uniden update endpoint RE** | RE complete (2026-05-03) | `Metacache/Dev/RE/docs/uniden_update_endpoints.md`, `wiki/RE-Update-Endpoints.md`. Prod client: `firmware/ftp_client.py`. |
| **BT885 SD card RE (verified)** | 2026-04-27 | `Metacache/Dev/RE/docs/BT885.md`, `Metacache/Dev/RE/docs/SD_CARD_COMPARISON.md`. |
| v0.10.0 follow-up backlog | `v0.10.0` (2026-06-19) | Root shims removed; full-repo ruff; GitLab win/mac/linux release jobs; GitHub release deprecated to manual mirror. |
| Filesystem reorg + build/CI parity | `v0.9.0b3` (2026-06-19) | `core/`, `legacy_tk/`, vendor/test fixtures, GitLab CI primary. |
| `scanner_profiles` package + `Bt885Profile` extraction | `v0.9.0b2` (2026-04-24) | First slice of multi-scanner work. |
| Map-tile coverage heatmap | `v0.9.0b2` | `tkintermapview` integration with fallback. |
| Multiple virtual SD card profiles + snapshot history | `v0.9.0b2` | `metastore.GlobalMetaStore` profiles, `<profile_dir>/.snapshots/`. |
| Plain-English UI sweep + tone linter | `v0.9.0b2` | Style guide enforced. |
