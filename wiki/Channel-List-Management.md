# Channel List Management

> Status: shipped (v0.11.x)

Edit the full channel tree on the SD card — systems, groups, and
entries — with filters, bulk actions, and a revertable change history.

The **Qt** shell is the default editor. Classic Tk uses the same tree
ideas with toolbar and right-click menus.

## Prerequisites

- Device registered and **HPDB** loaded ([Quickstart](Quickstart))
- Card writable (not locked)

**HPD** files hold systems → groups → entries (frequencies or
**TGIDs**). See [Glossary](Glossary).

## Hierarchy

```
System
  ├── Group
  │     ├── Entry (conventional frequency)
  │     └── Entry (trunked talkgroup — TGID)
  └── Group
```

Add, edit, and delete work at every level; bulk actions cascade downward.

## Steps (Qt)

1. Select a node in the tree.
2. Edit fields in the details panel (SDS) or BT885 inspector.
3. **File → Save** or toolbar **Save all**.
4. **Tools → Recent changes…** — review history; **Revert** undoes an
   entry (including bulk imports as one unit).

<details>
<summary>Classic Tk shell</summary>

- Right-click any node for Edit, Delete, and bulk ops
- **Add New Entry (from RadioReference)** panel below the tree for
  quick inserts
- **Changes...** opens the same change-history idea as Qt's Recent
  changes

</details>

## Filters

- **Button filters** (Police / EMS / Fire / DOT / Multi) — BT885
  inspector in Qt; toolbar checkboxes in Classic Tk. See
  [Scanner Button Service Types](Scanner-Button-Service-Types).
- **Location filter** — [ZIP & GPS Simulation](ZIP-and-GPS-Simulation).

## Bulk remap (service types)

**Bulk: update service type** on a group or system opens a two-column
mapping: for each service type in the selection, pick a replacement.
The whole remap is one change-history entry — one **Revert** undoes it.

<details>
<summary>Classic Tk shell</summary>

Right-click menu today. Qt port is backlog.

</details>

## Profile mismatch (Qt)

If the card's model disagrees with the device row, the editor shows a
banner and may offer a confirm dialog to switch this device to the
detected profile. Decline keeps the banner and **Manage devices…**
link.

## Session safety net

Every save writes `<hpdname>.session.bak` next to the HPD file.

- Classic Tk: **Tools → Restore session snapshot...**
- Qt: copy `.session.bak` over the HPD, or use **Tools → Profile
  snapshots…** for folder-level rollback

## If something goes wrong

- Edits missing after reload — check you saved; restore `.session.bak`
  or a profile snapshot ([Troubleshooting](Troubleshooting))
- Wrong model UI — fix the device profile under **Devices → Manage
  devices…**

## Internals

Change events live in the MetaStore sidecar (`<hpdname>.meta.json`)
next to each HPD. Bulk operations share one grouped transaction so one
Revert rolls back the batch. See [Architecture](Architecture).
