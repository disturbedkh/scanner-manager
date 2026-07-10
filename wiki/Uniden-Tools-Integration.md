# Uniden Tools Integration

> Status: shipped (v0.11.x)

Detect Uniden's official desktop apps and run a **push → update → pull**
cycle without leaving Scanner Manager — so vendor updates do not wipe
your edits.

**Windows only.** On macOS and Linux, **Tools → Uniden tools…** shows a
Windows-only notice. Uniden does not publish Mac or Linux builds of
these tools.

## Prerequisites

- Windows PC
- SD card / HPDB path bound in Scanner Manager
- Optional: Sentinel and/or BT885 Update Manager installed (or download
  via the dialog)

## Supported tools

- **BCDx36HP Sentinel** — Uniden programming tool (SDS100/200 and related)
- **BT885 Update Manager** — BearTracker 885 updater

## Steps

1. **Tools → Uniden tools…** (Qt or Classic Tk Tools menu).
2. Review each tool row: path, version (or "not installed"), family.
3. Use:
   - **Launch** — open the tool
   - **Launch + Auto-Sync** — snapshot, launch, wait for you to finish,
     re-read the card, replay your edits on top
   - **Install...** — download from Uniden's CDN (checksum verified) or
     **Browse for installer...**
   - **Override Path...** — portable or non-standard installs
   - **Open Data Folder** / **Refresh**

### Launch + Auto-Sync (what it does for you)

1. Snapshots the current HPD (session backup).
2. Launches Sentinel or BT885 Update Manager.
3. Waits until you finish and close the tool.
4. Re-reads the HPD from the card.
5. Replays your change history on top so edits survive the vendor write.
6. Records the pipeline as one revertable change-history entry.

Full orchestration is most mature in Classic Tk; Qt exposes detection,
launch, and installer download.

## Installers are not redistributed

Scanner Manager does not ship Uniden installer archives. **Install...**
fetches from Uniden's CDN using a pinned manifest (URL + checksum),
caches under `%LOCALAPPDATA%\scanner-manager\installers\`, and runs
setup. Later installs of the same version reuse the cache.

## If something goes wrong

- **"Hash mismatch"** — do not run the file; open a GitHub issue with
  URL and hashes so maintainers can update the manifest
- Installed but not detected — **Refresh**; Uniden sometimes installs
  under `C:\Uniden\` — use **Override Path...**
- **"Windows only"** on macOS/Linux — expected

More: [Troubleshooting](Troubleshooting).

## Internals

Detection scans usual Program Files locations and honors overrides in
`app_settings.json` (`uniden_tools_overrides`). Manifest:
`data/uniden_installers.json`.
