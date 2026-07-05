# Adding a New Scanner

> Status: shipped (v0.11.x)

Scanner Manager is architected around the `scanner_profiles` package so
more than one scanner can be managed from the same UI. Shipping profiles
as of v0.11.1: **BearTracker 885** (`uniden_bt885`) and **SDS100/200**
(`uniden_sds100`). This guide walks through what's required to add another.

Contributor ops checklist (no narrative): [`Metacache/docs/adding-a-scanner.md`](../Metacache/docs/adding-a-scanner.md).

## 1. Write a ScannerProfile subclass

Create `scanner_profiles/<model_id>.py` with a subclass of
`scanner_profiles.base.ScannerProfile`. Browse `scanner_profiles/bt885.py`
and `scanner_profiles/sds100.py` for working references.

Required methods at a glance:

| Category              | Methods                                                                                                    |
| --------------------- | ---------------------------------------------------------------------------------------------------------- |
| Identity              | `id`, `display_name`, `family`, `supports_hpd`, `supports_tgid`, `supported_file_extensions`, `target_model_aliases` |
| Capabilities          | `supports_serial_mode`, `supports_streaming`, `uses_hardware_button_semantics`, etc.                         |
| Service types         | `service_types`, `scannable_service_types`, `button_filter`, `service_label`, `service_type_help_text`      |
| RadioReference import | `rr_mode_to_hpd_mode`, `is_rr_mode_encrypted`, `guess_service_type_from_tag`                                |
| Firmware tables       | `read_zip_table`, `read_city_table`                                                                         |
| Tools                 | `preferred_installer_ids`                                                                                   |
| Card layout           | `card_identity_files`, `is_editable_config_file`                                                            |

Every method has a docstring on `ScannerProfile` explaining what the
app expects it to return. If a given scanner doesn't support a feature
(e.g. trunked talkgroups), return empty collections / `None` and flip
the relevant `supports_*` property to `False`.

Read the RE doc for your scanner under `Metacache/Dev/RE/docs/` before
implementing card layout helpers — lab notes are canonical for on-disk
shapes.

## 2. Register the profile

Register at the bottom of your profile module:

```python
from .registry import register_profile

register_profile(MyScannerProfile())
```

Import the module from `scanner_profiles/__init__.py` so registration
fires whenever the package is imported:

```python
from . import my_scanner as _my_scanner_module   # ensures register_profile runs
```

## 3. Update the manifest

Add an entry to `data/scanner_profiles.json` with the model ID, display
name, family, and the TargetModel strings the scanner writes into its
HPD files:

```json
{
  "id": "my_scanner",
  "display": "My Scanner 9000",
  "family": "my_family",
  "match_target_model": ["MY9000", "My Scanner 9000"]
}
```

On BCDx36HP-family cards every HPD writes `TargetModel\tBCDx36HP`, so
also implement **`detect_from_card()`** discrimination via
`scanner.inf` field 1 (see `scanner_profiles/registry.py`).

## 4. Add tests

Drop a `tests/test_<model_id>_profile.py` (or `_parity.py` for BT885-
style constant locks) that covers RadioReference modes, encrypted modes,
button filters, and tag-to-service mapping. SDS100 example:
`tests/test_sds100_profile.py`. BT885 canary: `tests/test_bt885_parity.py`.

## 5. Optional — installer registry

If your scanner has an update tool that should show up in the Uniden
Tools registry, add an entry to `data/uniden_installers.json` with its
download URL and SHA-256 hash, then list the tool ID first in
`preferred_installer_ids()`.

## 6. GUI integration

- Add a default row to `data/devices.json` if the model should appear
  in fresh installs.
- Qt docks read `supports_*` flags — no hard-coded model names in
  `gui/` when avoidable.
- Document user-facing behavior on the wiki (this tree) after shipping.

## Checklist

- [ ] Subclass of `ScannerProfile` with every abstract method implemented.
- [ ] Profile registered via `register_profile(...)` at import time.
- [ ] Profile module imported from `scanner_profiles/__init__.py`.
- [ ] Manifest entry in `data/scanner_profiles.json`.
- [ ] `detect_from_card()` path if the family shares `BCDx36HP` HPD headers.
- [ ] Tests under `tests/test_<id>_profile.py` (or parity test).
- [ ] Installer registry entry (if applicable).
- [ ] RE doc updated under `Metacache/Dev/RE/docs/` (Agent C / RE lane).
- [ ] CHANGELOG entry when releasing (maintainer).

## Hard rules

- **Never** `import legacy_tk.scanner_manager` from inside
  `scanner_profiles/` — circular import.
- **`tests/test_bt885_parity.py` must stay green** when touching BT885.
