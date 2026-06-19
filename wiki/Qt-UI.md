# Qt UI (PySide6 rebuild)

> This page documents the Qt-based desktop shell that ships as the
> default `scanner-manager` console script as of v0.10.0. The legacy
> Tkinter UI is still available as `scanner-manager-tk` for one
> release.

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

## Window layout

```
+----------------------------------------------------------+
| Header bar:                                              |
|   [Device selector v] [LED] [FW pill] [Update btn]       |
+----------------------------------------------------------+
| Center: Editor dock                                      |
|   - HPDB QTreeView                                       |
|   - Details / Bulk-edit panel                            |
|   - Profile-gated side panel                             |
|     * BT885: scanner-button checkboxes                   |
|     * SDS100/200: Favorites Lists + profile.cfg tabs     |
|   - Coverage panel: pyqtgraph heatmap +                  |
|     QtWebEngine Leaflet map                              |
+----------------------------------------------------------+
| Right docks (tabbed):                                    |
|   - Live (SDS100/200): GSI mirror, GLG feed,             |
|     RSSI meters, FFT waterfall                           |
|   - Streaming: soundcard picker, encoder, LAN listener,  |
|     Broadcastify / Icecast push                          |
+----------------------------------------------------------+
| Bottom docks (tabbed):                                   |
|   - Firmware: FTP discovery + update wizard              |
|   - Log                                                  |
+----------------------------------------------------------+
```

Docks honour profile capability flags. For example, a BearTracker 885
device hides the Live and Streaming docks because the BT885 has no
RE'd serial mode.

## Switching scanners

The header's device selector reads `data/devices.json` (managed by
`device_manager.DeviceManager`). Picking a device:

1. Calls `scanner_profiles.set_active_profile(...)`.
2. Emits `MainWindow.activeDeviceChanged`.
3. Tells every dock to rebuild via `set_active_device()` /
   `set_active_profile()` (whichever the dock implements).
4. Re-applies dock visibility using the new profile's `supports_*`
   flags.

Add a device via **Devices > Add device…**; the wizard asks for a
friendly label, the scanner family, and (optionally) the SD card mount
path. If you provide an SD card path the app will auto-detect the
scanner family by reading `BCDx36HP/scanner.inf` and prefill the
selection.

## Tools menu

Phase 6 ports the secondary Tk dialogs to Qt:

- **Workspaces…** — load / save named devices.json bundles
  (`gui.dialogs.workspaces`).
- **Profile snapshots…** — capture and roll back HPDB state
  (`gui.dialogs.profile_snapshots`).
- **Recent changes…** — metastore event log viewer
  (`gui.dialogs.changes`).
- **City / ZIP overrides…** — custom geo data for the heatmap
  (`gui.dialogs.city_manager`).
- **Uniden tools…** — Sentinel / BT885 Update Manager launcher
  (`gui.dialogs.uniden_tools`).

## Help menu

- **Open Wiki** — opens this wiki in the default browser.
- **Check for updates…** — runs `updater.check_for_update()` and shows
  the result via `UpdateAvailableDialog` (`gui.dialogs.update_available`).
- **Report issue…** — `ReportIssueDialog` opens a templated GitHub
  issue with the latest crash log attached
  (`gui.dialogs.report_issue`).
- **About**.

## Crash hook

`gui.app._install_global_excepthook` writes unhandled exceptions to:

- Windows: `%LOCALAPPDATA%\scanner-manager\crash\crash-<ts>.log`
- macOS:   `~/Library/Logs/scanner-manager/crash/crash-<ts>.log`
- Linux:   `${XDG_STATE_HOME:-~/.local/state}/scanner-manager/crash/`

The Report Issue dialog auto-attaches the most recent crash log so the
maintainers can see exactly what blew up.

## Cross-references

- Live dock + serial-mode safety: see
  [`Metacache/Dev/RE/docs/SDS100_unofficial_commands.md`](../Metacache/Dev/RE/docs/SDS100_unofficial_commands.md)
- Streaming pipeline (audio + telemetry):
  [`Streaming-Server.md`](Streaming-Server.md)
- Firmware updater (FTP discovery): [`Firmware-Updater.md`](Firmware-Updater.md)
- Multi-device backend:
  [`Metacache/Dev/MULTI_SCANNER_BACKEND.md`](../Metacache/Dev/MULTI_SCANNER_BACKEND.md)
