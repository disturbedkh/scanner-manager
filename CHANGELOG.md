# Changelog

All notable changes to Scanner Manager are documented in this file. The
format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.9.0b2] - 2026-04-24

First **beta** release on GitHub. Big jump from `v0.9.0a2`: a
real-map heatmap that scales, multiple virtual SD card profiles with
snapshot history, comprehensive deleted-tower visibility, a
user-facing language cleanup, and a backend driver layer that readies
the app for more than one scanner model without any frontend changes
today.

### Highlights

- **Coverage Heatmap rebuilt on real map tiles** with smooth zoom,
  tower clustering, scanner-button simulation, and a grayed-out
  overlay of removed towers.
- **Workspaces** now hold multiple virtual SD card profiles with
  snapshot history; one click to swap which profile lives on the
  physical card, automatic pre-swap snapshot of the outgoing profile.
- **Plain-English UI sweep** across tooltips, dialogs, status text,
  and the wiki, governed by a new style guide and a tone linter.
- **Scanner-profile driver layer** abstracts every BearTracker-885
  specific assumption behind a `ScannerProfile` interface, ready for
  additional models.

### Added - Coverage tools

- **Map-tile heatmap.** `CoverageHeatmapDialog` renders on real
  OpenStreetMap / Google tiles when `tkintermapview` is installed,
  with a tile-provider dropdown and tower-marker toggle. Falls back
  to the legacy Tk-canvas density grid when the map extra is missing.
- **Heatmap performance.** Intensity is quantized into a handful of
  buckets and adjacent same-bucket cells are merged into rectangles
  before hand-off to `tkintermapview`. On realistic inputs this cuts
  the number of polygons the map view has to reproject on each
  zoom/pan from 700+ cells down to ~60 rectangles. Default grid
  resolution tightened from 60 to 36.
- **Tower clustering.** Co-located repeaters collapse into a single
  marker on both the heatmap and `CoverageMapDialog`. Clicking the
  marker opens `TowerClusterDialog` - a tree of every system / group
  homed on that tower, so sites shared by multiple trunked systems no
  longer paint unreadable stacks of overlapping labels.
- **Span actually prunes markers.** Changing the heatmap's **Span (mi)**
  field now limits not just the heat grid but also which tower
  markers and coverage circles render. Zooming to 5 mi shows only the
  towers inside that box.
- **Per-tower coverage circles.** New **Show coverage circles** toggle
  outlines each active tower's advertised radius on the heatmap.
- **Scanner button simulation on the heatmap.** Police / Fire / EMS /
  DOT / Multi checkboxes plus an **Other types** toggle mirror the
  main toolbar's filter so the heatmap shows exactly what the scanner
  will scan for a given button combo.
- **Removed-tower overlay.** A **Show removed towers (grayed)** toggle
  draws every group or system the user has deleted since the last
  SD-card sync as a gray marker (and optional gray coverage ring),
  making it obvious what was pruned vs. what still lives on the card.
- **Comprehensive deleted-tower diff.** Detection no longer relies on
  delete events alone. The overlay parses the `.session.bak` session
  snapshot (the real HPD file as it was when you opened it), diffs
  it against the live tree, and unions in any unreverted delete
  events. Whole deleted systems, bulk-entry cleanups that emptied a
  group, and external edits all surface uniformly.

### Added - Workspaces and profiles

- **Multiple virtual SD card profiles with snapshot history.** Each
  workspace now keeps a per-profile snapshot vault under
  `<profile_dir>/.snapshots/`. New `sdcard.snapshot_workspace` /
  `sdcard.restore_snapshot` / `sdcard.prune_snapshots` routines power
  one-click **Activate on SD card**, **Snapshots...**, and **Restore
  Snapshot...** entries on the Workspaces manager. Activation
  automatically takes a pre-swap snapshot of the outgoing profile.
  Retention policy (max count, keep-manual flag) is stored per
  profile in `GlobalMetaStore`.
- **Toolbar Swap Profile button** plus a per-profile entry on the
  **Restore Session** menu, alongside the single legacy
  `.session.bak`.

### Added - Scanner-profile driver layer

- **`scanner_profiles/` package** encapsulates every scanner-specific
  piece of behavior behind a `ScannerProfile` ABC. The BearTracker
  885 lives in `scanner_profiles.bt885` as `Bt885Profile`, registered
  as the default. `scanner_manager.ACTIVE_PROFILE` is the single
  entry point; hot paths (`entry_passes_button_filter`,
  `_rr_trs_mode_to_hpd`, `_detect_updater_path`'s installer
  preference order) route through it.
- **Sidecars** get a new nullable `scanner_profile_id` field.
- **`data/scanner_profiles.json`** ships the manifest of known
  profiles.
- **`docs/adding-a-scanner.md`** walks through adding a new profile.

### Changed - Language

- **Plain-English UI sweep.** Rewrote `SERVICE_TYPE_HELP_TEXT` to lead
  with user outcomes, moved numeric service-type IDs into an
  "Advanced" paragraph. Status pill reads **Update pipeline: Ready /
  Needs attention / Blocked** instead of traffic-light colors.
  Tooltips on the service-type and mode columns explain what the
  control does in user terms. The **MetaStore** dialog is now
  **Change History**; the RadioReference URL hint talks about pasting
  URLs instead of editing `cid=` parameters; the TGID-edit mode blurb
  no longer opens with FDMA/TDMA acronyms; encrypted-talkgroup
  guidance leads with "the BearTracker 885 can't play them."
- **Wiki sweep.** `Channel-List-Management.md`,
  `RadioReference-Import.md`, `Quickstart.md`, and `Glossary.md`
  replace opcode-level jargon with plain English; remaining
  internals are parked under explicit **Internals** headings.
- **Development status.** Classifier bumped from alpha to beta;
  about-dialog subtitle updated to match.

### Added - Tooling

- **`scripts/check_wiki_tone.py`** lints `wiki/*.md` against a
  denylist of developer-jargon strings forbidden in user-facing copy.
  Developer-by-design pages (`Architecture.md`) are exempt; per-page
  `## Internals` sections are exempt too.
- **`docs/style-guide.md`** codifies the three rules that govern
  user-facing text: lead with outcome, park internals under
  **Internals** heading, no scaffolding phrases.
- **`tests/test_coverage_maps.py`**, **`tests/test_profiles_and_snapshots.py`**,
  **`tests/test_scanner_profiles.py`**, **`tests/test_bt885_parity.py`**.
  The parity suite locks every BT885 constant down against the new
  profile methods so the refactor never silently drifts.

### Internals

- New helpers in `coverage_maps.py`: `quantize_intensity`,
  `heat_rectangles`, `rectangle_polygon`, `iter_coverage_items`,
  `iter_coverage_circles`, `iter_deleted_tower_items`,
  `iter_deleted_tower_items_comprehensive`,
  `iter_hpd_session_snapshot_items`, `cluster_tower_points`,
  `cluster_passes_button_filter`, `clusters_within_span`.
- `metastore.GlobalMetaStore.upsert_profile` now initializes
  `snapshots`, `retention`, and `scanner_profile_id` fields for every
  profile it stores. Pre-existing profiles are upgraded lazily on
  read.
- New constants in `sdcard.py`: `SNAPSHOT_DIRNAME`,
  `SNAP_REASON_MANUAL`, `SNAP_REASON_PRE_SWAP`,
  `SNAP_REASON_PRE_RESTORE`, `SNAP_REASON_AUTO`,
  `DEFAULT_MAX_SNAPSHOTS`. Snapshot payloads are content-hashed
  (SHA-256) for deduplication.
- PyInstaller spec `datas` list adds `scanner_profiles/` and
  `data/scanner_profiles.json`.

## [0.9.0a3] - 2026-04-19

Focused cleanup release. Two scanner-unrelated features (**Avoid** and
**Discovery**) that were left over from other Uniden editors are gone;
Uniden installer downloads now verify real SHA-256 hashes; and a
built-in GitHub-release updater lets non-Git users upgrade with one
click.

### Removed

- **Avoid feature.** The BearTracker 885 ignores the `Avoid` field on
  HPD load and tracks avoids in its own RAM (which clears on power
  loss), so editor-side avoid flipping never affected scanning. The
  toggle buttons, exclude-avoided filter, detail / export column, bulk
  action, and the `OP_SET_AVOID` event type are all gone. MetaStore
  sidecars written by 0.9.0a2 are still readable — the replayer
  silently skips legacy `set_avoid` events.
- **Discovery viewer.** BT885 has no Discovery mode; the toolbar
  button, dialog, and parsers all targeted a BCD436HP feature that
  never applied here. Removed to keep the UI honest.

### Added

- **Built-in updater (`updater.py`).** Queries the
  `disturbedkh/scanner-manager` GitHub API 5 s after startup and via
  **Help → Check for Updates...**. Offers Update Now, Skip This
  Version, Remind Me Later, and Open Release Page. Verifies the
  matching `.sha256` sibling before swapping on Windows.
- **`UpdateAvailableDialog`** renders release notes and routes
  Mac / Linux users to the release page for manual download (binary
  self-swap on those platforms is a later milestone).
- **RadioReference encrypted-TG policy.** New imports skip encrypted
  TGIDs by default; refreshing an existing system purges any entries
  that RR now flags encrypted. A single "Include encrypted talkgroups
  (not recommended)" override lives in the import dialog, remembered
  per-system.
- **Installer hash-mismatch surfacing.** `UnidenInstallerDownloadDialog`
  now shows expected vs computed SHA-256 and a direct link to file an
  issue when Uniden rotates an installer on their CDN.

### Security

- **Real SHA-256 pins for Uniden installers.** `data/uniden_installers.json`
  now carries the 64-hex hashes for both shipped tools (`bt885_update_manager`
  and `bcdx36hp_sentinel`) and `manifest_version` is bumped to 2.
  Installer downloads that fail verification raise the new
  `uniden_tools.InstallerHashMismatch` exception instead of silently
  retrying.
- `scripts/pin_uniden_hashes.py` is the one-shot helper that produced
  these values; run it whenever Uniden ships a new installer.

### Tests

- `tests/test_updater.py` covers version compare, asset picking, GitHub
  payload parsing, download + SHA-256 verify (including mismatch), and
  the Windows swap-bat shape.
- `tests/test_uniden_installer_manifest.py` now asserts every shipped
  tool has a 64-hex `sha256` and a positive `size_bytes`.
- New `test_rr_import_skips_encrypted_by_default`,
  `test_rr_refresh_purges_existing_encrypted`, and
  `test_metastore_skips_legacy_set_avoid_events` pin the new behavior.

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
  Set CSV, Alerts folder viewer.
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
