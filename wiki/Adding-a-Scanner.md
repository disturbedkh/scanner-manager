# Adding a New Scanner

> Status: shipped (v0.11.x)

## What you'll build

A new scanner in Scanner Manager is a **profile**: a small Python class
that teaches the app how that model names service types, lays out its
SD card, and (when supported) talks over serial, streams audio, or
applies firmware. The rest of the stack — Qt docks, MetaStore, device
list — stays shared; you plug in behavior instead of forking the UI.

Shipping profiles in **0.11.x**: **BearTracker 885** (`uniden_bt885`)
and **SDS100/200** (`uniden_sds100`). Working references live in
`scanner_profiles/bt885.py` and `scanner_profiles/sds100.py`.

### The shape of the work

1. **Subclass `ScannerProfile`** — implement identity, capabilities,
   service-type maps, RadioReference helpers, firmware-table readers,
   and card-layout hooks. Unsupported features return empty collections
   / `None` with the matching `supports_*` flag set `False`.
2. **Register and declare** — call `register_profile()` at import time,
   import the module from `scanner_profiles/__init__.py`, and add a row
   to `data/scanner_profiles.json`. Families that share `BCDx36HP` HPD
   headers also need `detect_from_card()` discrimination via
   `scanner.inf` field 1.
3. **Lock it with tests** — a `tests/test_<model_id>_profile.py` (or a
   BT885-style parity canary) covering RR modes, encryption, button
   filters, and tag-to-service mapping.
4. **Optional polish** — installer registry entry, default
   `devices.json` row, and wiki notes for user-facing behavior.

Read the RE doc for your scanner under `Metacache/Dev/RE/docs/` before
implementing card-layout helpers — lab notes are canonical for on-disk
shapes.

### Hard rules (do not skip)

- **Never** `import legacy_tk.scanner_manager` from inside
  `scanner_profiles/` — circular import.
- **`tests/test_bt885_parity.py` must stay green** when touching BT885.

## Ops checklist (SSOT)

Step-by-step checkboxes, method tables, and code pointers live in the
ops checklist — **do not duplicate them here**:

[`Metacache/docs/adding-a-scanner.md`](../Metacache/docs/adding-a-scanner.md)
