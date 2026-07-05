# Workspaces and Sync

> Status: shipped (v0.11.x)

Scanner Manager uses the word **workspace** in two related ways depending
on which shell you launch. Read the section that matches your entry
point.

## Qt workspaces (device-list bundles)

The default Qt shell (**Tools → Workspaces…**) manages **named bundles
of device manifests** — not offline SD card clones.

A workspace record points at a `devices.json` file (your registered
scanners: label, model, SD path). Switching workspaces lets you jump
between setups such as **Home** vs **Roadtrip** without overwriting
the default manifest at:

- Windows: `%APPDATA%\scanner-manager\devices.json`
- macOS: `~/Library/Application Support/scanner-manager/devices.json`
- Linux: `~/.config/scanner-manager/devices.json`

When a workspace is active the header shows **Workspace:** *name*;
otherwise **Device list: default**. The editor toolbar may prefix HPDB
status with the workspace name.

### Typical Qt workflow

1. **Tools → Workspaces… → New…** — name the workspace and pick (or
   copy) a `devices.json` path.
2. **Load** — double-click the workspace row to activate it.
3. Edit HPDB for whichever device is selected in the header.
4. **New from default devices.json** — quick shortcut to snapshot your
   current default device list.

Profile snapshots (**Tools → Profile snapshots…**) capture a full
`BCDx36HP/` folder copy for rollback — complementary to workspaces.

## Virtual SD card (legacy Tk)

The **Virtual SD card** workflow — clone the card, edit while detached,
reconcile both ways on return — lives in **`scanner-manager-tk`** under
**Workspaces → New workspace from card…** (and related push/pull menu
items).

### Why use Virtual SD card

- **Edit offline.** Car scanner stays in the car; you edit at your desk.
- **Safer experiments.** Trash a workspace folder, not a card.
- **Update cycles.** Run Uniden's updater against the card, then pull
  new firmware tables into your workspace without losing offline edits.

### Creating a virtual workspace (legacy Tk)

1. Insert the card and **Load** it.
2. **Workspaces → New workspace from card...**
3. Pick a local folder. Scanner Manager copies the BCDx36HP tree and
   writes a manifest for drift detection.

### Push / pull (legacy Tk)

- **Push workspace → card...** — file-level diff then apply; MetaStore
  events remain revertable on the card.
- **Pull card → workspace...** — three buckets (card-only, workspace-
  only, conflicts) with per-file resolution.

Conflict rules follow the same replay logic as the RadioReference update
pipeline — see [Architecture](Architecture).

## Limitations

- Qt workspaces switch device lists only; they do not replace Virtual
  SD card clone/push/pull (legacy Tk).
- Virtual SD diff UI is functional but spartan on large trees.
- No cloud sync service — everything is local folders and JSON manifests.

## Cross-references

- [Qt UI](Qt-UI) — Tools menu workspace dialog
- [Quickstart](Quickstart) — device registration
