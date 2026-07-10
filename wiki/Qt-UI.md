# Qt UI

> Status: shipped (v0.11.x)

The Qt desktop app is the default way to run Scanner Manager. Use it to
register scanners, edit the on-card channel database (**HPDB** /
**HPD** — see [Glossary](Glossary)), preview location coverage on
BearTracker 885, and (on SDS100/200) mirror live activity and stream
audio.

<details>
<summary>Classic Tk shell</summary>

The older layout is still available as `scanner-manager-tk` for
workflows not yet in Qt (RadioReference import, Virtual SD card,
CityTable editor, Alerts viewer, Export Effective Scan Set). Prefer Qt
for day-to-day editing.

</details>

## Prerequisites

- Scanner Manager installed ([Install](Install))
- For editing: SD card mounted (**Mass Storage** mode or a card reader)
- For Live / Streaming (SDS100/200): scanner in **Serial** USB mode
  (see [Glossary](Glossary))

## Quick start

```sh
pip install -e .
scanner-manager           # Qt (default)
scanner-manager-qt        # alias
```

Optional extras for streaming and firmware:

```sh
pip install -e .[streaming,firmware,radioreference]
```

Prebuilt downloads launch `ScannerManager` / `ScannerManager.exe`
directly — see [Install](Install).

## Window layout

The main window has a fixed **header** and a central stack that
switches between **Storage** (editing) and **Live** (SDS100/200).

| Area | What you see |
| --- | --- |
| **Header** | Device selector, connection LED, **Storage** / **Live** toggle, firmware status pill |
| **Storage** | Channel tree, details/inspector, location simulation bar (BT885), mismatch banner if needed |
| **Live** (SDS100/200) | **Live - Control** (faceplate) and **Live - Monitoring** (meters, call feed, waterfall); Streaming dock when visible |
| **Status bar** | Short status; optional **View → Log window…** |

BearTracker 885 hides Live and Streaming — that model has no serial
live mode in this app.

## Switching scanners

1. **Devices → Add device…** — friendly name, scanner family, optional
   SD card path. If you give a card path, the app reads `scanner.inf`
   and can prefill the family.
2. Pick the device in the header dropdown.
3. The editor and docks rebuild for that profile.

If the card's model disagrees with the device row, a mismatch banner
appears with a link to **Devices → Manage devices…**. You can also
accept a confirm dialog to switch this device to the detected profile.

## Location simulation bar (BearTracker 885)

With a BT885 device and HPDB loaded:

- Tick **Apply location filter**
- Enter ZIP, county, or GPS and adjust **Tolerance**

That drives the tree filter and coverage map center. SDS100/200 use a
three-column editor without this bar. See
[ZIP & GPS Simulation](ZIP-and-GPS-Simulation).

## Live dock (SDS100/200)

| Tab | Contents |
| --- | --- |
| **Live - Control** | Virtual faceplate — keypad, soft keys, LCD mirror |
| **Live - Monitoring** | Status mirror, signal meters, call feed, waterfall |

Connect MAIN and SUB serial ports from the Live controls. The header
LED tracks connection state.

## Menus (common actions)

### File / Devices / View

- **File → Save** — save current HPD edits
- **Devices → Add / Manage devices…** — device list
- **View → Coverage / heatmap…** — map and heatmap popout
- **View → Log window…** — application log

### Tools

- **Firmware updater…** (`Ctrl+Shift+F`)
- **Workspaces…** — named device-list bundles (not Virtual SD card)
- **Profile snapshots…** — folder-level `BCDx36HP/` rollback
- **Recent changes…** — change history with **Revert**
- **City / ZIP overrides…** — coverage geo helpers
- **Uniden tools…** — Sentinel / BT885 Update Manager (**Windows only**)

### Help

- **Open Wiki**, **Check for updates…**, **Report issue…**, **About**

## If something goes wrong

- Empty tree — confirm the device SD path and that `HPDB/hpdb.cfg`
  exists ([Quickstart](Quickstart)).
- Live won't connect — Serial mode, correct MAIN/SUB ports, close other
  apps holding the ports ([Troubleshooting](Troubleshooting)).
- Crash — **Help → Report issue…** attaches the latest crash log path.

## Classic Tk gaps

Still on `scanner-manager-tk` until ported:

- RadioReference import UI and group linking
- Virtual SD card clone / push / pull
- CityTable editor, Alerts viewer, Export Effective Scan Set
- Pure-Tk coverage map (`tkintermapview`)

## Internals

Crash logs:

- Windows: `%LOCALAPPDATA%\scanner-manager\crash\`
- macOS: `~/Library/Logs/scanner-manager/crash/`
- Linux: `~/.local/state/scanner-manager/crash/`

Contributor notes: [Architecture](Architecture),
[Streaming Server](Streaming-Server),
[Firmware Updater](Firmware-Updater).
