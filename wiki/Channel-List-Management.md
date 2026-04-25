# Channel List Management

Scanner Manager is a full editor for the HPD tree, not just a viewer.

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

## Quick actions (right-click menu)

- **Entry:** Edit, Delete.
- **Group:** Edit, Bulk update service type, Refresh from
  RadioReference (when the group is linked), Delete.
- **System:** Edit, macro-level bulk ops (update service type on all
  entries), Delete.

## Add panel (below the tree)

Use it to quickly add a conventional frequency or trunked TGID into
the selected group. It validates frequency format and service-type
presence before committing.

## Bulk remap

**Bulk: update service type** on a group or system opens a two-column
mapping dialog: for every service type that currently appears in the
selection, pick a replacement. The whole remap is recorded as a single
entry in the Change History, so you can undo the entire bulk operation
with one click.

## Filters

- **Button filters** (Police/EMS/Fire/DOT/Multi) - see
  [Scanner Button Service Types](Scanner-Button-Service-Types).
- **Location filter** - see
  [ZIP & GPS Simulation](ZIP-and-GPS-Simulation).

## The Change History dialog

**Changes...** opens the Change History. Each row is one edit:

- Timestamp, a plain-language summary (e.g. "Added frequency",
  "Changed service type", "Applied RadioReference import"),
  and the group or entry it touched.
- **Revert** button to undo just that change.

Edits made together during a bulk operation or an import are grouped
so you can undo the entire operation in one click instead of reverting
each row.

## Session safety net

Every save also writes a recovery copy next to the HPD file.
If everything goes sideways, **Tools → Restore session snapshot...**
reloads from the backup. The Change History is preserved so you can
pick up where you left off.

---

## Internals

- Change events are stored by the `MetaStore` as typed opcodes
  (`ADD_CFREQ`, `SET_SERVICE`, `IMPORT_APPLY`, etc.) with a shared
  `txn_id` for bulk operations.
- Session snapshots are written to `<hpdname>.session.bak` alongside
  the HPD file.
