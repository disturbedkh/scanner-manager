# Uniden Tools Integration

Scanner Manager detects Uniden's official desktop apps and can drive a
full **push → update → pull** cycle without you leaving the Scanner
Manager window.

## Supported tools

- **BCDx36HP Sentinel** - the long-standing Uniden programming tool.
- **BT885 Update Manager** - the BearTracker 885-specific updater.

## Detection

Open **Uniden Tools...** to see a table with one row per tool:

- Installed path + version (or "not installed").
- Scanner family.
- Buttons: **Launch**, **Launch + Auto-Sync**, **Install...**,
  **Override Path...**, **Open Data Folder**, **Refresh**.

Detection scans the usual `Program Files` / `Program Files (x86)`
locations and honors a per-tool override stored in `app_settings.json`
under `uniden_tools_overrides`.

## Installers are not redistributed

Previous pre-alpha builds shipped the Uniden installer archives inside
the repo. The alpha no longer does that. Instead:

- A pinned manifest at `data/uniden_installers.json` lists the
  download URL, expected SHA-256, and archive layout for each tool.
- Clicking **Install...** on a missing tool opens the **Download Uniden
  Installer** dialog, which fetches the archive directly from Uniden's
  CDN, verifies the SHA-256, caches it under
  `%LOCALAPPDATA%\scanner-manager\installers\`, and runs setup.
- If your network blocks the download, use **Browse for installer...**
  in the same dialog to pick a file you already have.

Subsequent installs of the same version use the cached, already-verified
copy and skip the download.

## Launch + Auto-Sync

This is the powerful one. Clicking **Launch + Auto-Sync**:

1. Snapshots the current state of the HPD file (session backup).
2. Launches the Uniden tool (Sentinel or BT885 Update Manager).
3. Waits for you to perform whatever update you wanted (write new
   firmware tables, merge RR content, etc.) and close the tool.
4. Re-reads the HPD from the card.
5. Replays Scanner Manager's MetaStore event log on top of the new
   HPD so your edits survive the Uniden tool's write.
6. Logs the whole pipeline as a **single revertable event**.

## Overrides

If you have a portable install of Sentinel, or you installed to a
non-standard path, use **Override Path...** to point Scanner Manager
at the executable directly. The override is remembered.

## Data folder

**Open Data Folder** shells out to Explorer at the tool's
per-user data directory. Useful when you want to inspect or replace
files the tool caches (e.g. Sentinel's `ZipListUs.txt`).

## Troubleshooting

- **"Hash mismatch" on download** - the manifest has a pinned SHA-256
  which did not match. Don't run the file; open a GitHub issue with
  the hash you got and the URL so the maintainers can update the
  manifest.
- **Installer runs but nothing is detected afterwards** - Uniden
  installs sometimes land in `C:\Uniden\` rather than `Program Files`;
  click **Refresh**. If it's still not found, use **Override Path...**.
