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

- **Entry:** Edit, Toggle Avoid, Delete.
- **Group:** Edit, Bulk update service type, Bulk toggle avoid,
  Refresh from RadioReference (when the group is linked), Delete.
- **System:** Edit, macro-level bulk ops (update service type on all
  entries, toggle avoid on all entries), Delete.

## Add panel (below the tree)

Use it to quickly add a conventional frequency or trunked TGID into
the selected group. It validates frequency format and service-type
presence before committing.

## Bulk remap

**Bulk: update service type** on a group or system opens the
**BulkRemapDialog**, a two-column mapping: for every service type that
currently appears in the selection, pick a replacement. All changes run
under a single MetaStore batch, producing one revertable event per
bulk action.

## Filters

- **Show scannable only** - hides entries with `Avoid=1` and systems
  containing only avoided entries.
- **Exclude avoided** - orthogonal filter that also excludes anything
  flagged Avoid regardless of the scannable check.
- **Button filters** (Police/EMS/Fire/DOT/Multi) - see
  [Scanner Button Service Types](Scanner-Button-Service-Types).
- **Location filter** - see
  [ZIP & GPS Simulation](ZIP-and-GPS-Simulation).

## The Changes dialog

**Changes...** opens the MetaStore change log. Each row is one event:

- Timestamp, operation (`ADD_CFREQ`, `SET_AVOID`, `IMPORT_APPLY`, ...),
  target path, and a human-readable summary.
- **Revert** button to undo just that event.

Events applied during a bulk op or import share a `txn_id` and revert
together. Composite import events roll back every row the import
touched in one click.

## Session safety net

Every save also writes `<hpdname>.session.bak` next to the HPD file.
If everything goes sideways, **Tools → Restore session snapshot...**
reloads from the backup (the change log is preserved so you can pick
up where you left off).
