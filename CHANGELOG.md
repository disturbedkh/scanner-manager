# Changelog

All notable changes to Scanner Manager are documented in this file. The
format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.9.0a2] - 2026-04-24

Cross-platform alpha. Scanner Manager now builds and runs on Windows,
macOS, and Linux. The Uniden vendor tools (Sentinel, BT885 Update
Manager) remain Windows-only because Uniden doesn't publish macOS /
Linux builds of them; the Uniden Tools panel now shows a clear
"Windows only" notice on other platforms instead of appearing broken.

### Added

- **macOS and Linux builds.** Tag-triggered release workflow now
  matrix-builds on `windows-latest`, `macos-latest`, and
  `ubuntu-latest`, attaching `ScannerManager-windows-x64.zip`,
  `ScannerManager-macos.tar.gz`, and `ScannerManager-linux-x64.tar.gz`
  (plus per-file SHA-256 sidecars) to every GitHub Release.
- **macOS `.app` bundle.** PyInstaller spec now emits a proper
  `ScannerManager.app` with `Info.plist` (display name, version,
  removable-volume usage description). Bundle identifier:
  `org.disturbedkh.scanner-manager`.
- **Cross-platform file-manager opener.** "Open Data Folder" now
  uses `os.startfile` on Windows, `open` on macOS, and `xdg-open`
  on Linux.
- **CI smoke-import check.** CI now asserts every top-level module
  imports cleanly on all three OSes before running the test matrix.

### Changed

- **PyInstaller spec is single-source.** One `packaging/scanner-manager.spec`
  now branches on `sys.platform` to produce a Windows EXE, a macOS
  `.app`, or a Linux binary. Icon selection prefers `icon.icns` on
  macOS when present, else falls back to `icon.ico`.
- **Uniden Tools detection is OS-aware.** `_candidate_exe_paths()`
  returns an empty list on non-Windows (truthfully, there's nowhere
  real to look) and normalizes path separators so the unit tests
  exercise the detection code on Linux CI runners too.
- **PyInstaller-aware state dir.** When running from a frozen bundle,
  `app_settings.json` / MetaStore / `.session.bak` live next to the
  binary instead of inside `_MEIPASS` (which is wiped on exit).
- **Bundled resource lookup.** Added `bundled_resources_dir()` so
  `data/uniden_installers.json` and `data/zip_county_map_sample.json`
  are read from `_MEIPASS` when frozen and from the checkout dir
  otherwise.
- **CI matrix extended to macOS.** `.github/workflows/ci.yml` now
  runs on `macos-latest` (py3.11 + py3.12) alongside Windows and
  Ubuntu.

### Fixed

- **`test_detect_picks_up_installed_exe` was red on Ubuntu CI.** Root
  cause was hard-coded backslash separators in the Uniden installer
  relpaths plus `%VAR%` env expansion that only works on Windows.
  Detection now normalizes separators and reads env vars directly,
  so the same test passes on all three OSes.

## [0.9.0a1] - 2026-04-19

First public alpha. The core editing, simulation, and RadioReference
integration flows are feature-complete and tested; polish and packaging
items are still being finalized.

### Added

- **HPD editor.** Load, browse, and save `hpdb.cfg` + per-state `s_*.hpd`
  from a Uniden BearTracker 885 SD card. Edit individual entries, groups,
  and whole systems. Add / delete at every level of the hierarchy. Macro
  bulk ops at System level cascade down to entries with a single atomic
  event.
- **Event-sourced change log (MetaStore).** Every mutation is recorded as
  a reversible event with a composite `OP_IMPORT_APPLY` entry for bulk
  imports; a batching API collapses a 200-entry import down to a single
  sidecar write. Session safety snapshot (`.session.bak`) is kept alongside
  the HPD file.
- **Virtual SD card / Workspaces.** Clone the physical card into a local
  folder; keep editing while the card is detached; reconcile both ways
  when it returns, including after Uniden's updater has touched the card.
- **ZIP / GPS simulation.** Enter a ZIP or GPS coordinate and see the
  effective scan set: local, statewide, and national coverage with
  radius-based `COVERAGE`, `NEARBY`, `LOCAL`, `STATEWIDE`, and `WIDE`
  tagging. "Apply Location Filter" with per-group nearest-system ranking.
- **Coverage tools.** Coverage Heatmap (pure-Tk 200x200 grid), optional
  Coverage Map (tkintermapview tiles, OSM/Google), Export Effective Scan
  Set CSV, Alerts folder viewer, Discovery folder viewer.
- **RadioReference import.** Conventional categories, FCC callsigns, and
  trunked talkgroups via both HTML scraping and direct SOAP API (with
  `zeep`). Composite import log; reconciles against user edits on update.
- **CityTable custom locations.** Add user locations, export a patched
  `CityTable.dat` the scanner will load.
- **Uniden Tools integration.** Detects installed Sentinel / BT885 Update
  Manager; can launch either and orchestrate a push-update-pull cycle.
  Installers are not redistributed - a pinned-URL + SHA-256 manifest
  downloads directly from Uniden's CDN on first use
  (`data/uniden_installers.json`).
- **Help menu** with Wiki / Report Issue / Donate / About entries.
- **Donate dialog** with PayPal and BTC/ETH/USDT crypto addresses,
  copy-to-clipboard buttons, and optional QR codes when `qrcode` is
  installed.
- **First-run alpha notice** shown once per install.
- **Global crash hook** that writes timestamped crash logs under
  `%LOCALAPPDATA%\scanner-manager\logs\` and offers a pre-filled
  GitHub issue link.

### Changed

- Version number exposed via `importlib.metadata` and prepended to the
  window title.
- Distribution: source install via `pip install -e .` and a one-file
  Windows EXE produced on tag by the GitHub Actions release workflow.
- README slimmed to a landing page; feature-tour content moved to the
  GitHub Wiki.

### Removed

- Vendored Uniden installer folders (`BCDx36HP_Sentinel_Version_*/`,
  `BT885_UpdateManager_V*/`). Scanner Manager now fetches them from
  Uniden on demand and verifies the SHA-256.
- `max_backups` plumbing on the HPD writer; replaced by the single
  `.session.bak` snapshot pattern.

### Security / Legal

- Added `LICENSE` (MIT), `DISCLAIMER.md`, and `THIRD_PARTY_NOTICES.md`.
- `.gitignore` updated to keep user-state files (meta sidecar, session
  backups, app settings, ZIP cache) out of the repo.
