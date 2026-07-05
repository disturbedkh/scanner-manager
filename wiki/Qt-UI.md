# Qt UI (PySide6)

> Status: shipped (v0.11.x)

> This page documents the Qt-based desktop shell that ships as the
> default `scanner-manager` console script (v0.11.1). The legacy
> Tkinter UI is still available as `scanner-manager-tk`.

## Quick start

```sh
pip install -e .
scanner-manager           # Qt shell (default)
scanner-manager-qt        # alias
scanner-manager-tk        # legacy Tk shell
```

The Qt build pulls in `PySide6`, `pyqtgraph`, `pyserial`,
`sounddevice`, and `numpy` automatically. Streaming + firmware push
features add a few more deps:

```sh
pip install -e .[streaming,firmware,radioreference]
```

## Window layout (v0.11.x)

The main window uses a **stacked central layout** (Storage vs Live)
with a fixed header strip and popout windows for coverage and firmware.

```
+----------------------------------------------------------+
| Header bar:                                              |
|   [Device selector v] [LED] [Storage|Live] [FW pill]     |
+----------------------------------------------------------+
| Central stack — Storage page (default):                  |
|   Editor dock: toolbar + location sim bar (BT885)        |
|   HPDB QTreeView | profile panels (BT885 inspector or    |
|                    SDS details + Favorites/profile.cfg)  |
|   Profile mismatch banner when card ≠ device config      |
+----------------------------------------------------------+
| Central stack — Live page (SDS100/200):                  |
|   Live dock tabs:                                        |
|     Live - Control    → virtual scanner faceplate        |
|     Live - Monitoring → GSI, meters, GLG, waterfall      |
|   Streaming dock (tabbed with Live when visible)         |
+----------------------------------------------------------+
| Status bar + optional Log window (View menu)             |
| Firmware updater opens as standalone window (Tools menu) |
| Coverage heatmap/map opens as popout (View menu)         |
+----------------------------------------------------------+
```

Docks honour profile capability flags. BearTracker 885 hides the Live
and Streaming surfaces because the BT885 has no RE'd serial mode.

## Switching scanners

The header's device selector reads `data/devices.json` (managed by
`core/device_manager.DeviceManager`). Picking a device:

1. Calls `scanner_profiles.set_active_profile(...)`.
2. Emits `MainWindow.activeDeviceChanged`.
3. Tells every dock to rebuild via `set_active_device()` /
   `set_active_profile()`.
4. Re-applies visibility using the new profile's `supports_*` flags.

Add a device via **Devices → Add device…**; the wizard asks for a
friendly label, the scanner family, and (optionally) the SD card mount
path. If you provide an SD card path the app auto-detects the scanner
family from `BCDx36HP/scanner.inf` via `detect_from_card()` and
prefills the selection. If the loaded card disagrees with the device's
configured profile, the editor shows a mismatch banner with a link to
**Manage devices…** (auto profile switch is backlog — banner only).

## Location simulation bar (0.11.0+)

For BearTracker 885 profiles, the editor toolbar includes a **location
simulation bar** (`gui/editor/location_sim_bar.py`):

- **Apply location filter** checkbox
- ZIP / county / GPS inputs and tolerance controls
- Drives the HPDB tree filter and coverage map center

SDS100/200 profiles use the three-column editor layout without this
bar (location filtering semantics differ on that hardware family).

## Live dock (0.11.0+)

The Live page splits into two tabs:

| Tab | Contents |
| --- | --- |
| **Live - Control** | Virtual scanner faceplate — clickable keypad, soft keys, LCD mirror |
| **Live - Monitoring** | GSI XML mirror, signal meters, GLG call feed, FFT/waterfall |

Connect/disconnect controls enumerate MAIN + SUB serial ports for the
active SDS profile. The header LED tracks connection state (red /
yellow / green).

## Menus

### File / Devices / View

- **File → Save** — save current HPD edits.
- **Devices → Add / Manage devices…** — device manifest editor.
- **View → Coverage / heatmap…** — popout pyqtgraph + Leaflet map.
- **View → Log window…** — rolling application log.

### Tools menu

- **Firmware updater…** (`Ctrl+Shift+F`) — FTP discovery + apply wizard.
- **Workspaces…** — switch between named `devices.json` bundles (Home
  vs Travel setups). Not the legacy Virtual SD card clone; see
  [Workspaces & Sync](Workspaces-and-Sync).
- **Profile snapshots…** — capture and roll back `BCDx36HP/` folder state.
- **Recent changes…** — MetaStore event log viewer.
- **City / ZIP overrides…** — custom geo overrides for coverage when
  bundled ZIP data is incomplete.
- **Uniden tools…** — Sentinel / BT885 Update Manager launcher.

### Help menu

- **Open Wiki** — opens the GitHub wiki in the default browser.
- **Check for updates…** — runs `core/app_updater.check_for_update()`.
- **Report issue…** — templated GitHub issue with crash log path.
- **About**.

## Crash hook

`gui.app._install_global_excepthook` writes unhandled exceptions to:

- Windows: `%LOCALAPPDATA%\scanner-manager\crash\crash-<ts>.log`
- macOS:   `~/Library/Logs/scanner-manager/crash/crash-<ts>.log`
- Linux:   `${XDG_STATE_HOME:-~/.local/state}/scanner-manager/crash/`

The Report Issue dialog references the most recent crash log.

## Legacy Tk gaps (honest fallback)

These features remain on `scanner-manager-tk` until ported:

- RadioReference import UI and group linking
- Virtual SD card clone / push / pull
- CityTable editor, Alerts viewer, Export Effective Scan Set toolbar
- Pure-Tk coverage heatmap with `tkintermapview`

## Cross-references

- Live dock + serial-mode safety: see
  [`Metacache/Dev/RE/docs/SDS100_unofficial_commands.md`](../Metacache/Dev/RE/docs/SDS100_unofficial_commands.md)
- Streaming pipeline: [Streaming-Server](Streaming-Server)
- Firmware updater: [Firmware-Updater](Firmware-Updater)
- Multi-scanner backend:
  [`Metacache/Dev/MULTI_SCANNER_BACKEND.md`](../Metacache/Dev/MULTI_SCANNER_BACKEND.md)
- Multi-device GUI design notes:
  [`Metacache/Dev/MULTI_DEVICE_GUI.md`](../Metacache/Dev/MULTI_DEVICE_GUI.md)
