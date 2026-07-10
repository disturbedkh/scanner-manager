# Channel List Management

> Status: shipped (v0.11.x)

Scanner Manager is a full editor for the HPD tree, not just a viewer.
The Qt shell is the default editor; legacy Tk exposes the same tree
semantics with toolbar-centric navigation.

## Hierarchy

```
System
  ├── Group
  │     ├── Entry (conventional frequency)
  │     └── Entry (trunked talkgroup - "TGID")
  └── Group
        └── ...
```

Every level supports add / edit / delete, and bulk operations cascade
from the level you're acting on down to entries.

## Quick actions

- **Qt:** select a node in the tree; edit fields in the details panel
  (SDS) or BT885 inspector. Context menus are minimal — use the panel
  actions and toolbar.
- **Legacy Tk:** right-click any node for Edit, Delete, and bulk ops.

## Add panel (legacy Tk)

The legacy shell includes an **Add New Entry (from RadioReference)**
panel below the tree for quick conventional frequency or TGID inserts
with validation.

## Bulk remap

**Bulk: update service type** on a group or system opens a two-column
mapping dialog: for every service type that currently appears in the
selection, pick a replacement. The whole remap is recorded as a single
MetaStore entry — one **Revert** undoes the entire operation.

(Legacy Tk: right-click menu. Qt port backlog.)

## Filters

- **Button filters** (Police/EMS/Fire/DOT/Multi) — see
  [Scanner Button Service Types](Scanner-Button-Service-Types).
  BT885 inspector in Qt; toolbar checkboxes in legacy Tk.
- **Location filter** — see
  [ZIP & GPS Simulation](ZIP-and-GPS-Simulation).

## The Change History dialog

**Tools → Recent changes…** (Qt) or **Changes...** (legacy Tk) opens
the MetaStore log. Each row shows:

- Timestamp and plain-language summary.
- **Revert** to undo that change.

Bulk operations and imports group into composite events so one Revert
rolls back the whole batch.

## Profile mismatch / auto switch (Qt)

When `detect_from_card()` finds a different model than the device's
configured profile, the editor offers a **confirm dialog** to switch
this device to the detected profile (persists `scanner_profile_id` on
the device manifest and linked metastore workspace sidecar). Decline
keeps the mismatch banner and **Manage devices…** link. Legacy Tk still
does not call `detect_from_card()`.

## Session safety net

Every save writes `<hpdname>.session.bak` next to the HPD file.
**Tools → Restore session snapshot...** (legacy Tk) reloads from the
backup. Qt: copy `.session.bak` over the HPD manually or use profile
snapshots for folder-level rollback.

## Internals

- Change events live in `core/metastore.py` as typed opcodes with shared
  `txn_id` for bulk operations.
- Sidecar: `<hpdname>.meta.json` alongside each HPD file.

See [Architecture](Architecture).
