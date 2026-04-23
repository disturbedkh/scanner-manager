# Changelog

All notable changes to Scanner Manager are documented in this file. The
format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

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
