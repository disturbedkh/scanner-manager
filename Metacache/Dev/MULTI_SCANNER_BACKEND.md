# Multi-Scanner Backend (scanner_profiles/)

> Status: **in progress**, started by another contributor, landed in
> the `v0.9.0b2` beta. Do not regress.

The goal is to support multiple Uniden scanner models from the same
desktop app without rewriting `scanner_manager.py`. The chosen pattern
is a **driver layer**: every model-specific piece of behavior is
hidden behind a `ScannerProfile` interface and resolved at runtime.

## Where the code lives

| File | Role |
| --- | --- |
| `scanner_profiles/base.py` | `ScannerProfile` ABC. The full surface area of "things an app must know about a scanner". |
| `scanner_profiles/bt885.py` | `Bt885Profile` - the Uniden BearTracker 885 implementation. Currently the only shipping profile. Self-contained: all constants live in this module (no imports from `scanner_manager`). |
| `scanner_profiles/registry.py` | `register_profile`, `get_profile`, `list_profiles`, `profiles_for_target_model`. `DEFAULT_PROFILE_ID = "uniden_bt885"`. |
| `scanner_profiles/compat.py` | Transitional shim re-exporting `SERVICE_TYPES`, `SCANNABLE_TYPES`, `SERVICE_TYPE_HELP_TEXT`, `rr_mode_to_hpd`, `is_rr_mode_encrypted`, `guess_service_type_from_tag` from the default profile under the old module-level names. |
| `scanner_profiles/__init__.py` | Package entry. Imports `bt885` for its registration side effect; re-exports the public API. |
| `data/scanner_profiles.json` | User-facing manifest: id / display / family / `match_target_model` aliases. |
| `Metacache/docs/adding-a-scanner.md` | Step-by-step guide for adding a new profile. |
| `tests/test_scanner_profiles.py` | Registry tests: defaults, fallback, target-model resolution. |
| `tests/test_bt885_parity.py` | **Parity canary.** Keeps `Bt885Profile` in lock-step with the duplicated module-level constants in `scanner_manager.py`. |

## The `ScannerProfile` surface

Grouped by concern (each is an `@abstractmethod` unless noted):

- **Identity**: `id`, `display_name`, `family`, `supports_hpd`,
  `supports_tgid`, `supported_file_extensions`,
  `target_model_aliases`.
- **Service types + buttons**: `service_types`,
  `scannable_service_types`, `button_filter`, `service_label`,
  `service_type_help_text`.
- **RadioReference import mapping**: `rr_mode_to_hpd_mode`,
  `is_rr_mode_encrypted`, `guess_service_type_from_tag`.
- **Firmware tables**: `read_zip_table`, `read_city_table`.
- **Tools**: `preferred_installer_ids` (+ default
  `default_installer_id`).
- **Card layout**: `card_identity_files`, `is_editable_config_file`.

If a future scanner does not support a feature, return empty
collections / `None` and flip the relevant `supports_*` flag to
`False`.

## How `scanner_manager.py` consumes profiles today

- Imports: `from scanner_profiles import DEFAULT_PROFILE_ID, get_profile`
  (line 59).
- Sets `ACTIVE_PROFILE = get_profile(DEFAULT_PROFILE_ID)` at module
  load (line 145).
- Call sites that already use `ACTIVE_PROFILE`:
  - `scannable_service_types()` for entry-filter logic (~ line 2387).
  - `rr_mode_to_hpd_mode(...)` for RR import (~ line 2912).
  - `preferred_installer_ids()` for the Uniden Tools panel
    (~ line 5651).
  - `scannable_service_types()` again for cluster filtering in the
    coverage heatmap (~ line 10806).
- Call sites that still hit module-level constants
  (`SERVICE_TYPES`, `SCANNABLE_TYPES`, `SERVICE_TYPE_HELP_TEXT`,
  `SERVICE_CHOICES`, RR mappings) instead of going through
  `ACTIVE_PROFILE`. Intentional: parity test enforces equality.
  Migrating these is the next chunk of work.

## What's already wired through metastore / sidecars

- `metastore.GlobalMetaStore.upsert_profile` defaults
  `scanner_profile_id` to `None` for every workspace profile (this is
  the **virtual SD card profile**, not the scanner driver - the names
  collide; see "Naming gotcha" below).
- The schema docstring (`metastore.py` line 626) already lists
  `scanner_profile_id` alongside `target_model` and
  `content_fingerprint`.
- Nothing currently writes a non-null `scanner_profile_id`. When the
  open-card path learns to detect the scanner family it should write
  this on first save.

## Naming gotcha (read this once)

There are two unrelated concepts both called "profile":

1. **Scanner profile** - a `ScannerProfile` subclass in
   `scanner_profiles/`. Per scanner _model_. There is exactly one of
   these per supported scanner (`Bt885Profile` today).
2. **Workspace profile / virtual SD profile** - a user's saved SD
   card configuration in `metastore.GlobalMetaStore.profiles`. Per
   _user-saved card image_. A user can have many.

The sidecar field `scanner_profile_id` ties workspace profiles back
to a scanner profile. Don't conflate them.

## Active TODOs (in priority order)

1. **Detect-on-open.** When a workspace is opened, identify the
   scanner model and reassign `ACTIVE_PROFILE` (or thread the
   profile through instead of using a module-level global -
   preferred long-term). Persist `scanner_profile_id` on the
   workspace's sidecar via `metastore.upsert_profile`.

   **Important caveat (verified 2026-04-27 against real BT885 + SDS100
   cards).** `TargetModel` is **NOT a per-model identifier on
   BCDx36HP-family cards** - it's the firmware-family name. Both BT885
   and SDS100 write `TargetModel\tBCDx36HP` in every header. The
   detector must read `BCDx36HP/scanner.inf` (the `Scanner` record's
   field 1 is the canonical model string: `BT885-SCN` for BT885,
   `SDS100` for SDS100) and fall back to `BCDx36HP/profile.cfg`'s
   `ProductName` row when present, falling back to `TargetModel`
   last (it just identifies the family). See
   `Metacache/Dev/RE/SD_CARD_COMPARISON.md` and `Metacache/Dev/RE/BT885.md` for
   the verification. The current
   `Bt885Profile.target_model_aliases = ("Beartracker885", ...)` is
   **stale** - real BT885 hardware writes `BCDx36HP`, never
   `Beartracker885`. The aliases should be retired alongside this
   detector refactor; the test fixtures using
   `TargetModel\tBeartracker885` need to switch to
   `TargetModel\tBCDx36HP`.
2. **Stop branching on globals.** Migrate remaining
   `SERVICE_TYPES`/`SCANNABLE_TYPES`/etc. reads in
   `scanner_manager.py` to go through `ACTIVE_PROFILE` (or the
   per-workspace profile from step 1). Once every call site is
   migrated, delete `scanner_profiles/compat.py` and the duplicated
   module-level constants. The parity test goes away with them.
3. **Second profile - SDS100 (and SDS200).** Add `Sds100Profile` to
   prove the abstraction holds. SD card already RE'd in
   `Metacache/Dev/RE/SDS100.md`; that doc's "What to change in the
   codebase" section enumerates the exact files to add/edit.
   SDS200 is expected to share ~99% of firmware and SD layout with
   SDS100; one profile should cover both via a
   `match_scanner_inf: ["SDS100", "SDS200"]` manifest entry.
   Follow `Metacache/docs/adding-a-scanner.md` for the public-doc checklist;
   follow `Metacache/Dev/RE/SDS100.md` for the actual data and field
   shapes.
4. **UI surface for model selection.** Today the workspace open
   dialog assumes BT885. Once #1 lands the UI should display the
   resolved scanner family per workspace and refuse incompatible
   imports (e.g. importing a P25 Phase 2 talkgroup into a profile
   whose `supports_tgid` is False).
5. **Installer registry.** `data/uniden_installers.json` should
   eventually carry per-family entries; today it's BT885-shaped.

## Don't-touch list

- The two **sources of truth** for BT885 service types
  (`scanner_profiles/bt885.py` constants and `scanner_manager.py`
  module-level constants) MUST stay equal. Always run
  `pytest tests/test_bt885_parity.py` after any change to either.
- Don't import from `scanner_manager` inside `scanner_profiles/*`. It
  creates a circular import at app start.
- Don't add abstract methods to `ScannerProfile` without also
  implementing them in `Bt885Profile` in the same commit - the
  package import will crash otherwise.
- `register_profile` is called at the bottom of
  `scanner_profiles/bt885.py`. Keep registration there, not in
  `__init__.py`, so the registration is co-located with the class.

## Quick verification snippet

```python
from scanner_profiles import (
    DEFAULT_PROFILE_ID,
    get_profile,
    list_profiles,
    profiles_for_target_model,
)

assert get_profile(DEFAULT_PROFILE_ID).id == "uniden_bt885"
assert profiles_for_target_model("BT885").id == "uniden_bt885"
assert profiles_for_target_model("Whistler TRX-2") is None
print([p.id for p in list_profiles()])
# -> ['uniden_bt885']
```
