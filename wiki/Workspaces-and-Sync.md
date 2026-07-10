# Workspaces and Sync

> Status: shipped (v0.11.x)

Keep separate scanner setups without juggling files by hand. In Qt,
**workspaces** are named device lists (Home vs Travel). In Classic Tk,
**Virtual SD card** clones the card for offline edit and push/pull.

## Prerequisites

- Scanner Manager installed ([Install](Install))
- At least one device registered ([Quickstart](Quickstart))

## Qt workspaces (device-list bundles)

**Tools → Workspaces…** manages named bundles of your device list — not
offline SD card clones.

A workspace points at a `devices.json` (label, model, SD path for each
scanner). Switching workspaces jumps between setups without overwriting
the default list:

- Windows: `%APPDATA%\scanner-manager\devices.json`
- macOS: `~/Library/Application Support/scanner-manager/devices.json`
- Linux: `~/.config/scanner-manager/devices.json`

When a workspace is active the header shows **Workspace:** *name*;
otherwise **Device list: default**.

### Typical Qt workflow

1. **Tools → Workspaces… → New…** — name it and pick (or copy) a
   `devices.json` path.
2. **Load** — double-click the row to activate.
3. Edit HPDB for the device selected in the header.
4. Optional: **New from default devices.json** to snapshot the current
   default list.

**Tools → Profile snapshots…** captures a full `BCDx36HP/` folder for
rollback — complementary to workspaces.

<details>
<summary>Classic Tk — Virtual SD card</summary>

Clone the card, edit while detached, then reconcile both ways.

### Why use it

- Edit at your desk while the scanner stays in the car
- Experiment safely (trash a folder, not a card)
- Run Uniden's updater on the card, then pull new tables without losing
  offline edits

### Create

1. Insert the card and **Load** it.
2. **Workspaces → New workspace from card...**
3. Pick a local folder. Scanner Manager copies the `BCDx36HP` tree.

### Push / pull

- **Push workspace → card...** — file-level diff, then apply
- **Pull card → workspace...** — card-only / workspace-only / conflicts
  with per-file resolution

</details>

## Limitations

- Qt workspaces switch device lists only; they do not replace Virtual
  SD card clone/push/pull (Classic Tk)
- Virtual SD diff UI is functional but plain on large trees
- No cloud sync — local folders and JSON only

## If something goes wrong

- Wrong scanners after a switch — confirm the header **Workspace:**
  name and reopen **Tools → Workspaces…**
- Need folder rollback — **Tools → Profile snapshots…** or restore from
  a card backup ([Troubleshooting](Troubleshooting))

## Internals

Conflict / replay rules for Virtual SD align with the RadioReference
update pipeline — see [Architecture](Architecture).
