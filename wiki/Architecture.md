# Architecture

> Status: shipped (v0.11.x)

Notes for contributors and anyone trying to understand why Scanner
Manager behaves the way it does. For release checklists and file-format
specs, see
[`Metacache/docs/`](https://github.com/disturbedkh/scanner-manager/tree/main/Metacache/docs).

## Product layout (v0.11.x)

Scanner Manager is no longer a single `scanner_manager.py` monolith.
The default entry (`scanner-manager`) launches the PySide6 shell under
`gui/`. Domain logic lives in UI-free packages so both Qt and the legacy
Tk fallback can share it.

```
core/                 # HPD model, MetaStore, device manager, RR SOAP, sdcard helpers
gui/                  # PySide6 default shell (editor, live, streaming, firmware docks)
legacy_tk/            # Tkinter fallback (`scanner-manager-tk`)
scanner_profiles/     # BearTracker 885 + SDS100/200 profile classes + registry
scanner_drivers/      # SDS100/200 serial MAIN/SUB drivers + USB port detection
firmware/             # FTP discovery, SHA-256 cache, card apply pipeline
streaming/            # FastAPI LAN server + Icecast/Broadcastify push
audio/                # Soundcard capture + Opus/MP3/WAV encoders
data/
  devices.json        # Default device manifest (overridden per workspace)
  scanner_profiles.json
  uniden_installers.json
tests/                # pytest headless tests
packaging/            # PyInstaller specs + Qt entry shim
wiki/                 # In-repo wiki SSOT (published to GitHub wiki)
```

## Data model

HPD parsing and the tree model live in `core/hpd.py`:

```
HpdFile
  └── SystemNode (conventional or trunked)
        └── GroupNode
              └── FreqEntry  (name, freq or TGID, service_type,
                              lat, lon, range, extras)
```

Every node carries a stable `uid` field so the MetaStore can reference
it across renames and re-parses. `legacy_tk/scanner_manager.py`
re-exports these types for backward compatibility; new code should
import from `core.hpd`.

## MetaStore event log

`core/metastore.py` defines an `Event` dataclass plus a `MetaStore`
singleton backed by a sidecar JSON file (`<hpdname>.meta.json`).

### Event types

- `OP_ADD_GROUP`, `OP_ADD_CFREQ`, `OP_ADD_TGID` — additions.
- `OP_EDIT_ENTRY`, `OP_EDIT_GROUP`, `OP_EDIT_SYSTEM` — in-place edits.
- `OP_DELETE_ENTRY`, `OP_DELETE_GROUP`, `OP_DELETE_SYSTEM` — removals.
- `OP_SET_SERVICE` — low-level field mutation the bulk ops route
  through. (An older `set_avoid` op exists in v0.9.0a2 sidecars; the
  replayer silently skips it for forward compatibility.)
- `OP_IMPORT_APPLY` — **composite** event summarising a whole import
  so it reverts in one click.
- `OP_EXTERNAL_CHANGE` — wraps a Uniden-updater pass; the replayer
  re-applies pre-existing events on top.

### Batching

`MetaStore.batch()` is a context manager. Inside it:

- `begin_batch()` / `end_batch()` bump a depth counter; nested batches
  compose correctly.
- `flush()` returns early if `_batch_depth > 0`.
- The outermost `end_batch()` triggers exactly one disk write.

Callers that perform hundreds of mutations inside a batch (imports,
bulk remaps, pipeline updates) therefore produce exactly one sidecar
write regardless of mutation count.

### `log=False`

Mutation helpers accept an optional `log: bool = True`. Inside a batch
the caller can opt out of the per-mutation event and rely on a single
composite event (e.g. the import apply). This keeps the change log
small and human-readable.

### Revert semantics

`Event.revert(tree)` is responsible for undoing itself. For composite
events, that means walking the payload and reversing every sub-
mutation in reverse order. The UI never re-derives revert logic; it
just calls `Event.revert()`.

## Multi-scanner backend

`scanner_profiles/` registers concrete profiles at import time via
`register_profile()`. The active profile is a runtime singleton
(`get_active_profile()` / `set_active_profile()`).

Shipping profiles (v0.11.1):

| ID | Scanner | Notes |
| --- | --- | --- |
| `uniden_bt885` | BearTracker 885 | Default profile; hardware button semantics |
| `uniden_sds100` | SDS100 / SDS200 | Serial live mirror, streaming, firmware FTP |

`detect_from_card(sd_path)` reads `BCDx36HP/scanner.inf` field 1 and
returns the matching profile. On mismatch, the Qt editor offers a
confirm dialog to switch the device profile (and persist
`scanner_profile_id`); decline keeps the mismatch banner
(`gui/editor/editor_dock.py` → `MainWindow._on_profile_switch_from_card`).
**Legacy Tk does not call `detect_from_card()` today.**

`data/scanner_profiles.json` is the manifest of known models;
`data/devices.json` holds user device rows (label, profile id, SD path).

## Device manager

`core/device_manager.py` loads and persists the device manifest.
The Qt header combobox (`gui/header.py`) lists registered devices and
emits `deviceChanged`; `gui/main_window.py` rebroadcasts
`activeDeviceChanged` so every dock reloads HPDB state for the new
device.

## Import pipeline

RadioReference import (HTML scrape + optional SOAP via `core/rr_api.py`)
is implemented in `legacy_tk/scanner_manager.py` and its helper
modules. The Qt shell exposes **Recent changes…** for the MetaStore log
but does not yet port the full RR import UI — use `scanner-manager-tk`
for import workflows until the Qt editor catches up.

Typical import flow (Tk):

1. Open a `MetaStore.batch()`.
2. For each row in the diff: add/edit/delete with `log=False`.
3. Build an `OP_IMPORT_APPLY` payload capturing enough state to reverse
   the whole operation.
4. `record(payload)` once; end the batch (one sidecar write).

## Update pipeline

`_run_update_pipeline` (legacy Tk) wraps Uniden tool runs in an
`OP_EXTERNAL_CHANGE` event and replays pre-existing user events on top
of whatever the tool wrote. Qt exposes the same Uniden Tools dialog
(`gui/dialogs/uniden_tools.py`) for launch/detection; the full
push → update → pull orchestration remains strongest in legacy Tk.

## Session snapshot

On every save, the app copies the current HPD to
`<hpdname>.session.bak`. This is a single-file safety net; it is
deliberately not timestamped or rotated.

## Qt shell structure

`gui/main_window.py` hosts:

- **Header** — device selector, connection LED, firmware pill, mode
  toggle (Storage vs Live).
- **Editor dock** — HPDB tree, profile panels, location sim bar (BT885),
  profile mismatch banner.
- **Live dock** — Control (virtual faceplate) + Monitoring (GSI, meters,
  GLG, waterfall) tabs; SDS100/200 only.
- **Streaming dock** — soundcard + LAN server + push targets.
- **Firmware** — standalone window from Tools menu (`FirmwareDock`).

Coverage heatmap/map opens as a popout window (`View → Coverage /
heatmap…`) using `pyqtgraph` + QtWebEngine/Leaflet — not the legacy
Tk `tkintermapview` path.

See [Qt UI](Qt-UI) for the user-facing tour.

## Legacy Tk fallback

`legacy_tk/scanner_manager.py` is the original monolith, split into
helper modules (`sm_helpers.py`, `geo_tables.py`, `import_dialogs.py`,
etc.) but still one process. It retains features not yet ported to Qt:

- RadioReference import and group linking
- Virtual SD card clone / push / pull
- CityTable editor, Alerts viewer, Export Effective Scan Set
- Pure-Tk coverage heatmap with optional `tkintermapview`

Launch with `scanner-manager-tk`. Parity constants for BT885 remain
locked by `tests/test_bt885_parity.py`.

## Tests

- `tests/test_metastore.py` — event logging, batching, revert.
- `tests/test_scanner_profiles.py` / `tests/test_sds100_profile.py` —
  profile registry and SDS100 behavior.
- `tests/test_firmware_*.py` — FTP client, cache, updater card apply.
- `tests/test_qt_*.py` — Qt dock smoke tests (live, firmware, workspace).
