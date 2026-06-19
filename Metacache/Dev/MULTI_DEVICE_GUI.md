# Multi-Device GUI - Top-Level Device Selector

> Status: design only (not implemented). Drafted 2026-04-27 EDT.
> Companion to `MULTI_SCANNER_BACKEND.md`. Where the backend doc
> covers the `scanner_profiles/` driver layer, this doc covers the
> **GUI surface** that lets a user switch between scanners and
> have the right device-specific UI come up.

## The goal in one sentence

A persistent header at the top of the window with a **scanner
device selector** that, when the user picks a different model,
swaps in the correct UI panels, hides irrelevant ones, and shows
device-specific controls (heatmap features, firmware versions,
serial-mode live panel, etc.) without restarting the app.

## What "device" means here

A **Device** in the GUI is the union of:

1. A `ScannerProfile` (from `scanner_profiles/`) - tells us what
   the *model* can do.
2. A specific **SD card profile** (one of the multiple virtual
   profiles in `metastore.GlobalMetaStore`) - tells us which card
   layout we're editing right now.
3. Optionally, a live **serial connection** to that scanner -
   tells us what's happening *right now*.

A user might have:
- An SDS100 with two SD card profiles ("Home" and "Roadtrip")
- A BT885 with one profile ("Truck")

That's **3 Devices** in the selector.

## Header bar (sketch)

```
+-----------------------------------------------------------------------------+
|  [Uniden SDS100 - Home]  [v]   FW: Main 1.26.01 / Sub 1.03.15  [Update...]  |
|        ^- selector dropdown    ^- live status from connected scanner        |
+-----------------------------------------------------------------------------+
|                                                                             |
|   <existing tabs / panels - filtered to what this device supports>          |
|                                                                             |
+-----------------------------------------------------------------------------+
```

The dropdown lists every Device (ScannerProfile + card-profile
combination) the app knows about, plus an "Add..." item that walks
the user through setting up a new one.

When the user picks a different Device, the app rebinds the UI to
that profile's `ACTIVE_PROFILE` (which already exists in the
backend) and re-renders.

## What changes per device

The backend already encodes most of this in `ScannerProfile`. The
GUI just has to honor those flags:

| GUI element | Driven by |
|---|---|
| Service-type buttons (Police/EMS/Fire/DOT) | `profile.service_types`, `profile.scannable_service_types`, `profile.button_filter`, `profile.service_label` |
| Service-type help text | `profile.service_type_help_text(svc_id)` |
| Channel/group editor scope | `profile.supports_hpd`, `profile.supports_tgid` |
| Firmware updater panel target | `profile.id` -> `firmware_manifest.scanners[id]` |
| Heatmap "show towers by button" | `profile.button_filter` (BT885 has 4 fixed buttons; SDS100 doesn't) |
| Live-scanner panel (GSI/STS/GLG mirror) | `profile.supports_serial_mode` (new flag, see below) |
| Waterfall display | `profile.supports_waterfall` (new flag) |
| Multiple Favorites Lists support | `profile.supports_favorites_lists` (new flag) |
| File extensions filter on import | `profile.supported_file_extensions` |
| Card identity files for detect-on-open | `profile.card_identity_files` |

## New flags to add to `ScannerProfile`

The current ABC handles most of what we need. Three additions:

```python
class ScannerProfile(ABC):
    # ... existing ...

    @property
    def supports_serial_mode(self) -> bool:
        """True if this scanner exposes the Uniden Remote Command
        Protocol over USB CDC. SDS100/200/150 = yes; BT885 = ? (TBD).
        """
        return False

    @property
    def supports_waterfall(self) -> bool:
        """True if this scanner supports the Waterfall display +
        FFT command set (PWF/GWF/GST/GW2). SDS100/200 = yes.
        """
        return False

    @property
    def supports_favorites_lists(self) -> bool:
        """True if user can create multiple FLs (named, with their
        own quick keys). SDS100/200 = yes; BT885 = no (single FL).
        """
        return False

    @property
    def usb_vid_pid_serial(self) -> tuple[int, int] | None:
        """The (VID, PID) the scanner enumerates as in serial mode.
        Used by the GUI's USB detector. None = scanner has no
        serial mode."""
        return None
```

## Backend changes needed

**Mostly already done** - the backend was designed for this. What's
missing:

1. **`ACTIVE_PROFILE` is set once at module load and never
   reassigned.** Need to change to a function-level lookup or a
   "profile context" pattern so the GUI can swap it.
2. **Module-level constants in `scanner_manager.py`** (`SERVICE_TYPES`,
   `SCANNABLE_TYPES`, `SERVICE_TYPE_HELP_TEXT`, etc.) - these
   leak through `scanner_profiles/compat.py` and assume the BT885
   defaults. Need to migrate call sites to `ACTIVE_PROFILE.<X>`.
   This is the open task in `MULTI_SCANNER_BACKEND.md` step 2.
3. **`metastore.GlobalMetaStore` SD-card-profile model needs to
   know which `ScannerProfile.id` it belongs to.** Today profiles
   are name-keyed; we need a `scanner_profile_id` field per profile.
4. **Detect-on-open scanner profile reassignment** - already in the
   backlog of `MULTI_SCANNER_BACKEND.md`. Critical for this GUI:
   when a user plugs in a card we can't expect them to manually
   select the matching device first.

## GUI surface changes

Concretely in the existing Tk app:

### A. New top header frame (above the main notebook)

- Replaces the existing "title bar" widgets if any.
- Holds:
  - **Device selector** (ttk.Combobox in readonly mode, populated
    from `ProfileRegistry.list_profiles()` cross-joined with
    `GlobalMetaStore.list_profiles()`)
  - **Add Device** button - opens a wizard to set up a new
    profile (pick scanner type, pick or create an SD card folder
    layout, name the profile)
  - **Edit/Delete Device** dropdown menu
  - **Connection status** indicator (red/yellow/green dot):
    - **Red**: no scanner detected at all
    - **Yellow**: scanner detected on SD card / in mass storage
      but not in serial mode
    - **Green**: scanner reachable on serial port and we can read
      `MDL`/`VER`
  - **Firmware version** label - either reads `scanner.inf` from
    SD or queries `VER` over serial, whichever is available
  - **Update button** (only shows when a newer version is in the
    firmware manifest)

### B. Tab-level visibility

Each of the existing tabs declares a "supports" predicate against
the ScannerProfile:

```python
class ChannelEditorTab:
    def is_supported_for(self, profile: ScannerProfile) -> bool:
        return profile.supports_hpd or profile.supports_tgid

class WaterfallTab:
    def is_supported_for(self, profile: ScannerProfile) -> bool:
        return profile.supports_waterfall

class LiveScannerTab:  # new in a later phase
    def is_supported_for(self, profile: ScannerProfile) -> bool:
        return profile.supports_serial_mode

class FirmwareUpdaterTab:
    def is_supported_for(self, profile: ScannerProfile) -> bool:
        return profile.id in FIRMWARE_MANIFEST_SCANNERS
```

When the active device changes, the notebook re-builds its tab
list from the supported predicates.

### C. Per-tab content reloading

Tabs that depend on profile-driven data (the service-type editor
especially) listen for an `on_active_profile_changed` event and
re-render. The plumbing here is small if we accept a "rebuild from
scratch" approach (cheap because tabs are stateless w.r.t. their
selected device).

### D. Theme / minor brand cues (optional, low priority)

When the user is on an SDS100, the title says "Uniden SDS100"; on
a BT885, "Uniden BearTracker 885". A small accent color or icon
per device to make it clear which one the controls apply to. Not
essential for the first cut.

## Storage layout for "Devices"

A new `data/devices.json` (or extend `metastore`) storing:

```json
{
  "devices": [
    {
      "id": "uuid-1",
      "label": "SDS100 - Home",
      "scanner_profile_id": "uniden_sds100",
      "metastore_profile_id": "home",
      "sd_card_path": "H:\\",
      "last_known_main_fw": "1.26.01",
      "last_known_sub_fw": "1.03.15",
      "last_seen": "2026-04-27T18:45:46Z"
    },
    {
      "id": "uuid-2",
      "label": "SDS100 - Roadtrip",
      "scanner_profile_id": "uniden_sds100",
      "metastore_profile_id": "roadtrip",
      "sd_card_path": null,
      "last_seen": null
    },
    {
      "id": "uuid-3",
      "label": "BearTracker 885 - Truck",
      "scanner_profile_id": "uniden_bt885",
      "metastore_profile_id": "truck",
      "sd_card_path": "E:\\",
      "last_seen": "2026-04-25T12:11:09Z"
    }
  ],
  "default_device_id": "uuid-1"
}
```

The metastore SD-card profiles already exist - this just adds a
device-level wrapper that pairs them with a scanner-profile choice
and an optional last-known SD card mount point.

## Phases

### Phase 1: backend prep (no GUI changes yet)
- Add the new `ScannerProfile` flags
  (`supports_serial_mode`/`supports_waterfall`/`supports_favorites_lists`/`usb_vid_pid_serial`)
- Make `ACTIVE_PROFILE` reassignable at runtime
- Migrate the remaining module-level constants in
  `scanner_manager.py` to `ACTIVE_PROFILE.X` (the dangling step 2
  of `MULTI_SCANNER_BACKEND.md`)
- Land the SDS100 profile (`scanner_profiles/sds100.py`)
- Add `data/devices.json` schema + a Devices manager class

### Phase 2: header bar + selector
- Build the top frame with selector / connection status / firmware
  version / update button
- Wire device selection to a global event bus
- Tabs subscribe and rebuild

### Phase 3: per-tab support gating
- Existing tabs declare `is_supported_for(profile)`
- Hide tabs that don't apply
- Rename/relabel tabs per profile (e.g., Heatmap label hints)

### Phase 4: detect-on-open device matching
- When user plugs in an SD card, the detector reads `scanner.inf`
  Scanner field 1 plus `BCDx36HP/HPDB/hpdb.cfg` `TargetModel`,
  matches against known profiles, and either selects the matching
  Device or offers to create a new one.

### Phase 5: live serial panel (per-device)
- A new tab visible only when the connected scanner supports serial
  mode and is currently reachable.
- Polls `GSI` once a second, parses the XML, displays the live
  scanner state - mirrors the LCD effectively.
- Future: spectrum/waterfall display fed by `GST` (FW 1.23.01+)
  or a SUB-port FFT direct read.

## Cross-references

- `Metacache/Dev/MULTI_SCANNER_BACKEND.md` - the existing backend doc.
  This GUI plan implements its "GUI follow-up" deferred items.
- `Metacache/Dev/RE/SDS100.md` - what we know about the SDS100's serial
  command surface; informs the live panel's design.
- `Metacache/Dev/RE/BT885.md` - the BT885's surface; informs why some
  flags differ (no FLs, no waterfall, no serial mode).
- `Metacache/Dev/FIRMWARE_UPDATER.md` - the firmware updater's GUI
  panel which fits naturally as one tab in this multi-device shell.

## Out of scope (for now)

- Multiple scanners connected simultaneously over USB (we'd have
  to disambiguate which COM ports belong to which scanner). Treat
  as one-scanner-at-a-time for now.
- Cloud sync of Devices across machines.
- Scanner-to-scanner migration tools (export from SDS100 -> import
  to SDS200). The data formats are similar enough that this is
  doable later.
