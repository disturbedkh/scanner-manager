# Workspaces and Sync

A **Workspace** (a.k.a. Virtual SD card) is a local folder that mirrors
the layout of a real BearTracker 885 SD card. You can edit a workspace
while the card is detached, then reconcile changes in either direction
when the card comes back.

## Why

- **Edit offline.** Car scanner stays in the car; you edit at your
  desk.
- **Safer experiments.** Trash a workspace, not a card.
- **Update cycles.** Run Uniden's updater against the card, then pull
  the new firmware tables into your workspace *without* losing the
  edits you made while disconnected.

## Creating a workspace

1. Insert the card and **Load** it.
2. **Workspaces → New workspace from card...**
3. Pick a local folder. Scanner Manager copies the BCDx36HP tree and
   writes a small manifest so it can later detect drift.

You can then close the card, eject it, and keep working. The status bar
shows you're editing a workspace, not a card.

## Pushing changes to the card

1. Insert the card and **Load** it.
2. **Workspaces → Push workspace → card...**
3. Review the file-level diff.
4. Apply.

Each HPD file changed is backed by the standard MetaStore event log on
the card, so individual edits remain revertable after a push.

## Pulling changes from the card

Use this after Uniden's Sentinel/Update Manager has touched the card,
or after a second machine has edited the card directly.

1. **Workspaces → Pull card → workspace...**
2. Scanner Manager identifies three buckets:
   - **Card-only changes** (new systems/groups/entries the card has
     that the workspace doesn't).
   - **Workspace-only changes** (your offline edits).
   - **Conflicts** (both sides edited the same entity).
3. For each conflict, pick workspace, card, or merge.
4. The workspace's event log is re-played on top of the pulled file so
   your customizations (renames, service-type overrides, deletions)
   stick.

## Conflict resolution

Conflict rules follow the same logic as the reconciliation replay used
by the RadioReference update pipeline:

- **Deleted entries** from the workspace stay deleted unless you ask
  otherwise.
- **Service-type overrides** from the workspace win.
- **Renames** follow frequency/TGID identity; if the identity still
  matches, your name is kept.

See [Architecture](Architecture) for the full replay order.

## Limitations (alpha)

- The diff UI is functional but spartan - large diffs require
  scrolling. A tree-style diff view is on the 0.9.x roadmap.
- Workspaces are single-machine; there's no sync service.
