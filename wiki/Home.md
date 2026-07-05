# Scanner Manager

> Status: shipped (v0.11.x)

A desktop companion for Uniden scanners — **BearTracker 885 and
SDS100/200** as of **v0.11.1**. Browse and edit the SD card's HPD files,
import channels from RadioReference, preview what the scanner will scan
at a given ZIP/GPS, mirror live activity (SDS100/200) over LAN, and
keep a full audit trail of every change.

> **Default shell (0.11.x beta):** `scanner-manager` launches the
> [Qt UI](Qt-UI) (PySide6). The legacy Tkinter shell remains available
> as `scanner-manager-tk` for features not yet ported and for users
> who prefer the classic layout.

> Unofficial, community-built. Not affiliated with or endorsed by
> Uniden. See `DISCLAIMER.md` in the repo root.

## Feature tour

- **Multi-scanner shell.** Top-of-window device selector swaps the UI
  between BearTracker 885 and SDS100/200. See [Qt UI](Qt-UI).
- **Live mirror (SDS100/200).** Virtual faceplate, GSI mirror, GLG call
  feed, RSSI meters, and FFT waterfall via the official + RE'd serial
  APIs.
- **Streaming.** Soundcard capture + Opus/MP3 encoder + LAN listener
  + optional Broadcastify / Icecast push. See [Streaming Server](Streaming-Server).
- **Firmware updater.** FTP discovery, SHA-256 verified cache, atomic
  apply, post-flash verify. See [Firmware Updater](Firmware-Updater).
- **HPD editor.** Full tree view (System → Group → Entry) with filters,
  bulk operations at every level, and a revertable change log.
- **ZIP / GPS simulation.** See exactly what your scanner will scan
  when you key a ZIP code or accept a GPS fix, complete with
  nearest-systems ranking and per-group coverage tags (BT885 in Qt;
  legacy Tk for some export paths).
- **Coverage tools.** Qt: pyqtgraph heatmap + Leaflet map popout.
  Legacy Tk: optional `tkintermapview` tile map. See
  [Coverage Tools](Coverage-Tools).
- **RadioReference import.** Conventional and trunked systems, with
  both HTML scraping and the SOAP API (legacy Tk today). Each import is
  one revertable event.
- **Workspaces.** Qt: switch between named device lists (`devices.json`
  bundles). Legacy Tk: Virtual SD card clone/push/pull. See
  [Workspaces & Sync](Workspaces-and-Sync).
- **CityTable customization.** Add custom locations and export a patched
  CityTable (legacy Tk editor; Qt has ZIP/county override helpers).
- **Uniden Tools integration.** Detects Sentinel and BT885 Update
  Manager; orchestrates a push → update → pull cycle.

## Start here

1. [Install](Install)
2. [Quickstart](Quickstart)
3. [Updating](Updating)
4. Pick what's next from the sidebar:
   - [ZIP & GPS Simulation](ZIP-and-GPS-Simulation)
   - [Coverage Tools](Coverage-Tools)
   - [RadioReference Import](RadioReference-Import)
   - [Workspaces & Sync](Workspaces-and-Sync)
   - [Uniden Tools Integration](Uniden-Tools-Integration)
   - [Channel List Management](Channel-List-Management)
   - [CityTable & Custom Locations](CityTable-and-Custom-Locations)
   - [Scanner Button Service Types](Scanner-Button-Service-Types)
   - [Alerts](Alerts)

## For contributors

- [Architecture](Architecture) — MetaStore event log, batching, revert
  semantics, and the `core/` / `gui/` / `legacy_tk/` split.
- [Troubleshooting](Troubleshooting) — crash logs, session snapshots,
  and how to recover a mangled card.
- [Glossary](Glossary) — acronyms (including the RE vocabulary).

## RE / Development

How the SDS100 (and the wider BCDx36HP scanner family) actually
works on the inside, written for **contributors who want to extend
this work**. Start with [Reverse Engineering](Reverse-Engineering)
— it's the consolidated narrative for the whole tree.

- [Overview](Reverse-Engineering) — the synthesis: two USB modes,
  what each gives us, why our app exceeds Sentinel.
- [Architecture](RE-Architecture) — two MCUs, three buses, mermaid.
- [USB Modes](RE-USB-Modes) — Mass Storage vs Serial.
- [SD Card](RE-SD-Card) — FAT32 layout, BCDx36HP family file
  shapes.
- [Serial Protocol](RE-Serial-Protocol) — SUB + MAIN command
  catalogs.
- [Inter-MCU Bus](RE-Inter-MCU-Bus) — USART2 between SUB and MAIN.
- [Firmware](RE-Firmware) — Sub container, MAIN encryption,
  firmware-update flow.
- [Update Endpoints](RE-Update-Endpoints) — Uniden FTP servers the
  app and Sentinel use for firmware/HPDB discovery.
- [Sentinel](RE-Sentinel) — what Sentinel actually does over USB.
- [Toolchain](RE-Toolchain) — every script and tool grouped.
- [Workflows](RE-Workflows) — recipe playbooks.
- [Virtual Scanner Roadmap](Virtual-Scanner-Roadmap) — SDR-backed
  software scanner plan that builds on everything above.
