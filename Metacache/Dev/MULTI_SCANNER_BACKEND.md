# Multi-Scanner Backend (scanner_profiles/)

> Status: shipped (v0.11.x) — two profiles live (BT885 + SDS100/200).
> Residual migration work in legacy Tk; do not regress parity tests.

The goal is to support multiple Uniden scanner models from the same
desktop app without rewriting the legacy Tk monolith. The chosen pattern
is a **driver layer**: every model-specific piece of behavior is
hidden behind a `ScannerProfile` interface and resolved at runtime.

## Where the code lives

| File | Role |
| --- | --- |
| `scanner_profiles/base.py` | `ScannerProfile` ABC. Capability flags include `supports_serial_mode`, `supports_waterfall`, `supports_favorites_lists`. |
| `scanner_profiles/bt885.py` | `Bt885Profile` — BearTracker 885. Parity with `legacy_tk.scanner_manager` module-level constants. |
| `scanner_profiles/sds100.py` | `Sds100Profile` — SDS100/200 (shared layout). |
| `scanner_profiles/registry.py` | `register_profile`, `get_profile`, `list_profiles`, `profiles_for_target_model`, **`detect_from_card()`**, **`set_active_profile()`** / `get_active_profile()`. |
| `scanner_profiles/compat.py` | Transitional shim re-exporting legacy module-level names from the default profile. |
| `scanner_profiles/__init__.py` | Imports profiles for registration side effects; re-exports public API. |
| `data/scanner_profiles.json` | User-facing manifest: id / display / family / `match_target_model` aliases. |
| `Metacache/docs/adding-a-scanner.md` | Step-by-step guide for adding a new profile. |
| `tests/test_scanner_profiles.py` | Registry tests: defaults, fallback, target-model resolution. |
| `tests/test_bt885_parity.py` | **Parity canary** for BT885 vs legacy Tk constants. |
| `tests/test_sds100_profile.py` | SDS100 constants, card helpers, profile surface. |

## Active profile API

```python
from scanner_profiles import get_active_profile, set_active_profile, detect_from_card

set_active_profile("uniden_sds100")  # Qt header on device switch
profile = get_active_profile()

detected_id, reason = detect_from_card(Path("D:/"))  # reads scanner.inf
```

- **Qt** calls `set_active_profile()` when the user picks a device in
  `gui/header.py`.
- **Legacy Tk** still sets `ACTIVE_PROFILE = get_profile(DEFAULT_PROFILE_ID)`
  at import time in `legacy_tk/scanner_manager.py` — not reassigned at runtime.
- **`detect_from_card()`** — reads `BCDx36HP/scanner.inf` field 1 (`BT885-SCN`
  vs `SDS100`). Qt editor offers confirm-to-switch on mismatch (banner if
  declined); legacy Tk does not call it yet.

## The `ScannerProfile` surface

Grouped by concern (each is an `@abstractmethod` unless noted):

- **Identity**: `id`, `display_name`, `family`, `supports_hpd`,
  `supports_tgid`, `supported_file_extensions`,
  `target_model_aliases`.
- **Capabilities**: `supports_serial_mode`, `supports_waterfall`,
  `supports_favorites_lists`, `usb_vid_pid_serial`.
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

## Naming gotcha (read this once)

There are two unrelated concepts both called "profile":

1. **Scanner profile** — a `ScannerProfile` subclass in
   `scanner_profiles/`. Per scanner _model_.
2. **Workspace profile / virtual SD profile** — a user's saved SD
   card configuration in `metastore.GlobalMetaStore.profiles`. Per
   _user-saved card image_.

The sidecar field `scanner_profile_id` ties workspace profiles back
to a scanner profile. Don't conflate them.

## Residual TODOs (priority order)

1. **Legacy Tk detect path.** Port `detect_from_card()` to Tk open dialog.
2. **Stop branching on globals in legacy Tk.** Migrate remaining
   `SERVICE_TYPES`/`SCANNABLE_TYPES` reads to `ACTIVE_PROFILE`; retire
   `compat.py` and parity test when done.
3. **Installer registry.** `data/uniden_installers.json` is BT885-shaped;
   extend per-family as needed.

**Shipped (2026-07-10):** Qt auto profile switch on card load (confirm
dialog → `Device.scanner_profile_id` + metastore sidecar; banner on
decline). BT885 fixtures/aliases use `BCDx36HP` (stale `Beartracker885`
removed).

## Adding a third profile

Follow `Metacache/docs/adding-a-scanner.md` for the public checklist;
follow the per-scanner RE doc in `Metacache/Dev/RE/docs/` for field
shapes (e.g. `SDS100.md` "What to change in the codebase").

## Don't-touch list

- **`tests/test_bt885_parity.py`** must stay green after any BT885 constant change.
- Don't import from `legacy_tk.scanner_manager` inside `scanner_profiles/*`.
- Don't add abstract methods to `ScannerProfile` without implementing them
  in every shipping profile in the same commit.
- `register_profile` stays at the bottom of each profile module, co-located
  with the class.

## Quick verification snippet

```python
from scanner_profiles import (
    DEFAULT_PROFILE_ID,
    get_profile,
    list_profiles,
    detect_from_card,
)

assert get_profile(DEFAULT_PROFILE_ID).id == "uniden_bt885"
assert get_profile("uniden_sds100").family == "BCDx36HP"
print(sorted(p.id for p in list_profiles()))
# -> ['uniden_bt885', 'uniden_sds100']
```

## Cross-links

- Multi-device GUI: `MULTI_DEVICE_GUI.md`
- RE card comparison: `Metacache/Dev/RE/docs/SD_CARD_COMPARISON.md`
- As-built firmware: `FIRMWARE_UPDATER.md`
