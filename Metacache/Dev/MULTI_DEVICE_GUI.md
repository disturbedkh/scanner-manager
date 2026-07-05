# Multi-Device GUI — As-Built Reference

> Status: **shipped (v0.11.0)** — Qt header device selector, Live/Storage mode
> gating, workspace-aware device manifests. Residual gaps listed below.

Companion to [`MULTI_SCANNER_BACKEND.md`](MULTI_SCANNER_BACKEND.md). The
backend doc covers `scanner_profiles/`; this doc covers the **Qt GUI shell**
that lets a user switch between registered scanners and see the right docks.

User-facing tour: [Qt UI wiki](https://github.com/disturbedkh/scanner-manager/wiki/Qt-UI).

## What shipped

A persistent **header bar** at the top of the Qt main window:

```
+------------------------------------------------------------------+
| Scanner: [Uniden SDS100 / SDS200 — My SDS100 ▼]  Add…  Manage     |
| Mode: [Live] [Storage]   ● FW: Main 1.26.01 / Sub 1.03.15  [Check for updates…] |
+------------------------------------------------------------------+
|  Central stack: Storage (editor)  OR  Live (faceplate + monitoring) |
+------------------------------------------------------------------+
```

Implemented in:

| Module | Role |
| --- | --- |
| `gui/header.py` | `HeaderBar` — device combobox, Live/Storage `ModeSwitcher`, connection LED, FW label, update button. |
| `gui/main_window.py` | Wires `deviceChanged` → `set_active_profile()`; gates central stack + docks by profile flags. |
| `gui/devices_dialog.py` | Add Device / Manage Devices wizards; optional `detect_from_card()` when an SD path is given. |
| `core/device_manager.py` | `Device`, `DeviceManager` — load/save `data/devices.json`. |
| `data/devices.json` | Shipped default device manifest (schema v1). |
| `gui/editor/editor_dock.py` | Mismatch banner when loaded SD card profile ≠ selected device (`detect_from_card()`). |

## What "device" means

A **Device** (`core/device_manager.Device`) is the union of:

1. A **`scanner_profile_id`** — which `ScannerProfile` drives service types,
   serial capability, waterfall, etc.
2. An optional **`metastore_profile_id`** — which virtual SD workspace profile
   is active (may be `null` for live-only devices).
3. Optional **`sd_card_path`**, cached firmware versions, **`connection_mode`**
   (`live` / `storage` / `auto`).

The header combobox lists every registered device. Picking one emits
`HeaderBar.deviceChanged`; `MainWindow` calls `set_active_profile()` and
rebinds docks.

## Header bar behavior

### Device selector

- Populated from `DeviceManager.list_devices()`.
- Label format: `{profile.display_name} — {device.label}`.
- **Add…** → `AddDeviceDialog` (pick profile, label, optional SD path).
- **Manage** → `ManageDevicesDialog` (rename, remove, set default).

### Live / Storage mode switcher

Hardware is mutually exclusive between USB serial mode and mass storage.
`ModeSwitcher` emits `connectionModeChanged`; `MainWindow` swaps the central
`QStackedWidget` between the editor (Storage) and live docks (Live).

Profiles declare `supported_connection_modes` on `ScannerProfile`. BT885
clamps to Storage only (no serial mode). SDS100/200 enable both.

### Connection status LED

Three-state `StatusLight` in the header:

| State | Meaning |
| --- | --- |
| red | No scanner detected |
| yellow | SD card mounted, not in serial mode |
| green | Serial port reachable (`MDL`/`VER`) |

Updated by the live-mode driver layer (`gui/main_window.py` + serial hooks).

### Firmware pill + update button

- `set_firmware_version(main, sub)` on the header.
- **Check for updates…** opens the firmware dock / window (see
  [`FIRMWARE_UPDATER.md`](FIRMWARE_UPDATER.md)).

### Workspaces

Named workspaces can point at alternate `devices.json` bundles
(`gui/dialogs/workspaces.py`). Header shows workspace context via
`set_data_source_context()`.

## Main window dock gating

`gui/main_window.py` hides or disables docks based on the active profile:

| Dock | BT885 | SDS100/200 |
| --- | --- | --- |
| Editor (Storage) | yes | yes |
| Live / faceplate / waterfall | no | yes |
| Streaming | no | yes (when serial supported) |
| Firmware | yes (HPDB; no Main/Sub bins on FTP today) | yes |

On device switch (`HeaderBar.deviceChanged` → `MainWindow._on_device_changed`):

1. Calls `set_active_profile(device.resolve_profile())`.
2. Clamps `device.connection_mode` (`live` / `storage` / `auto`) to the
   profile's `supported_connection_modes()` and updates the header switcher.
3. Flips the central `QStackedWidget` immediately (`_apply_mode_visibility`).
4. Emits `activeDeviceChanged(device, profile)` so live/streaming docks rebind.
5. Defers heavy editor work via `QTimer.singleShot(0, _finish_device_switch)`:
   in **Live** mode on serial-capable profiles, HPDB load is skipped until the
   operator switches back to Storage (`load_hpdb=False` on first pass).

**Check for updates…** (`updateFirmwareRequested`): auto-selects Storage mode
(disconnects live serial), then opens `FirmwareWindow` — the radio cannot
serve mass storage and CDC serial at once.

## Storage: `data/devices.json`

Schema (v1):

```json
{
  "schema_version": 1,
  "devices": [
    {
      "id": "<uuid>",
      "label": "My SDS100",
      "scanner_profile_id": "uniden_sds100",
      "metastore_profile_id": null,
      "sd_card_path": null,
      "last_known_main_fw": null,
      "last_known_sub_fw": null,
      "last_seen": null,
      "connection_mode": "live"
    }
  ],
  "default_device_id": "<uuid>"
}
```

`DeviceManager` ignores unknown keys for forward compatibility. Path defaults
via `core/device_manager._default_devices_path()` (user-data override supported).

Workspaces may redirect to a bundled copy under the workspace directory.

## Card detection (partial)

`detect_from_card()` is **wired for awareness, not auto-switch**:

- **Add Device** wizard: suggests profile from SD path.
- **Editor dock**: shows a banner when the mounted card's detected profile
  differs from the selected device's `scanner_profile_id`.
- Does **not** automatically change the header selection or call
  `set_active_profile()` on card insert.

Backlog: full detect-on-open device matching (see `WORKSTREAMS.md`).

## Residual gaps

| Gap | Today | Target |
| --- | --- | --- |
| Auto profile switch on card load | Mismatch banner only | Select matching device or prompt to create one |
| Legacy Tk multi-device | Not implemented | Qt-only; Tk remains single-profile |
| Simultaneous USB scanners | One scanner at a time | Out of scope |
| Favorites Lists editor | No dedicated UI | Future editor tab |
| Cloud sync of devices | Local JSON only | Out of scope |

## Cross-references

- [`MULTI_SCANNER_BACKEND.md`](MULTI_SCANNER_BACKEND.md) — profiles, `detect_from_card()`, `set_active_profile()`.
- [`FIRMWARE_UPDATER.md`](FIRMWARE_UPDATER.md) — firmware dock opened from header.
- [`Metacache/Dev/RE/docs/SDS100.md`](RE/docs/SDS100.md) — serial command surface for live dock.
- [`Metacache/Dev/RE/docs/BT885.md`](RE/docs/BT885.md) — BT885 capability differences.

## Out of scope (unchanged)

- Multiple scanners connected simultaneously over USB.
- Cloud sync of Devices across machines.
- Scanner-to-scanner migration wizards.
