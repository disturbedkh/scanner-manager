# Scanner Manager

> Status: shipped (v0.11.x)

A desktop companion for Uniden **BearTracker 885** and **SDS100/200**
scanners. Browse and edit the SD card's channel files (**HPD** /
**HPDB** — Uniden's on-card channel database; see [Glossary](Glossary)),
import channels from RadioReference, preview what the scanner will hear
at a ZIP or GPS location, mirror live activity on SDS100/200 over your
LAN, and keep a full undo history of every change.

> **Default app (0.11.x):** downloads and `scanner-manager` open the
> [Qt UI](Qt-UI). Prefer that path for day-to-day use.
>
> <details>
> <summary>Classic Tk shell</summary>
>
> The older Tkinter layout is still available as `scanner-manager-tk`
> for a few workflows not yet in Qt (notably RadioReference import) and
> for anyone who prefers the classic screens. See [Install](Install).
>
> </details>

> Unofficial, community-built. Not affiliated with or endorsed by
> Uniden. See `DISCLAIMER.md` in the repo root.

## Start here

1. [Install](Install) — download or build, then launch
2. [Quickstart](Quickstart) — first edit in five steps
3. [Updating](Updating) — stay on the latest release
4. **Features** — pick what you need next (sidebar or list below)
5. **Help** — [Troubleshooting](Troubleshooting) and [Glossary](Glossary)
6. **RE** — [Reverse Engineering](Reverse-Engineering) (contributors)

## Feature tour

- **Multi-scanner shell.** A device selector at the top of the window
  switches between BearTracker 885 and SDS100/200. See [Qt UI](Qt-UI).
- **Live mirror (SDS100/200).** On-screen faceplate, call feed, signal
  meters, and waterfall while the scanner is connected over the network
  or serial link.
- **Streaming.** Capture scanner audio, encode it, and share it on your
  LAN (optional Broadcastify / Icecast). See
  [Streaming Server](Streaming-Server).
- **Firmware updater.** Finds updates, verifies downloads, and applies
  them to the SD card safely. See [Firmware Updater](Firmware-Updater).
- **Channel editor.** Tree view (System → Group → Entry) with filters,
  bulk edits, and a revertable change history.
- **ZIP / GPS preview.** See what the scanner would scan for a ZIP code
  or GPS fix, with nearest-systems ranking and coverage tags (BT885 in
  Qt; some export paths still use Classic Tk).
- **Coverage tools.** Heatmap and map popout in Qt. See
  [Coverage Tools](Coverage-Tools).
- **RadioReference import.** Pull conventional and trunked systems from
  RadioReference (Classic Tk today). Each import is one undoable event.
  See [RadioReference Import](RadioReference-Import).
- **Workspaces.** Named device lists and card sync helpers. See
  [Workspaces & Sync](Workspaces-and-Sync).
- **CityTable customization.** Custom locations and patched CityTable
  export (Classic Tk editor; Qt has ZIP/county helpers). See
  [CityTable & Custom Locations](CityTable-and-Custom-Locations).
- **Uniden Tools.** Detects Sentinel and BT885 Update Manager and can
  orchestrate push → update → pull. **Windows only** — on macOS and
  Linux the panel shows a Windows-only notice. See
  [Uniden Tools Integration](Uniden-Tools-Integration).

## Help

- [Troubleshooting](Troubleshooting) — crash logs, bad cards, recovery
- [Glossary](Glossary) — HPD, HPDB, TGID, Mass Storage, Serial, and more
- [Architecture](Architecture) — how change history and the app layers fit
  together (for contributors)

## RE / Development

How the SDS100 (and the wider BCDx36HP family) works on the inside —
for **contributors who want to extend this work**. Start with
[Reverse Engineering](Reverse-Engineering).

- [Overview](Reverse-Engineering)
- [Architecture](RE-Architecture)
- [USB Modes](RE-USB-Modes) — Mass Storage vs Serial
- [SD Card](RE-SD-Card)
- [Serial Protocol](RE-Serial-Protocol)
- [Inter-MCU Bus](RE-Inter-MCU-Bus)
- [Firmware](RE-Firmware)
- [Update Endpoints](RE-Update-Endpoints)
- [Sentinel](RE-Sentinel)
- [Toolchain](RE-Toolchain)
- [Workflows](RE-Workflows)
- [Virtual Scanner Roadmap](Virtual-Scanner-Roadmap)
