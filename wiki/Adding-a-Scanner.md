# Adding a New Scanner

Scanner Manager is architected around the `scanner_profiles` package so
more than one scanner can eventually be managed from the same UI.
Today the shipping profiles include the Uniden BearTracker 885
(`uniden_bt885`) and the Uniden SDS100 (`uniden_sds100`). This guide
walks through what's required to add a new profile.

## 1. Write a ScannerProfile subclass

Create `scanner_profiles/<model_id>.py` with a subclass of
`scanner_profiles.base.ScannerProfile`. The smallest viable profile
implements every abstract method. Browse `scanner_profiles/bt885.py`
for a working reference - the BearTracker 885 profile is intentionally
verbose so other profiles can crib from it.

Required methods at a glance:

| Category              | Methods                                                                                                    |
| --------------------- | ---------------------------------------------------------------------------------------------------------- |
| Identity              | `id`, `display_name`, `family`, `supports_hpd`, `supports_tgid`, `supported_file_extensions`, `target_model_aliases` |
| Service types         | `service_types`, `scannable_service_types`, `button_filter`, `service_label`, `service_type_help_text`      |
| RadioReference import | `rr_mode_to_hpd_mode`, `is_rr_mode_encrypted`, `guess_service_type_from_tag`                                |
| Firmware tables       | `read_zip_table`, `read_city_table`                                                                         |
| Tools                 | `preferred_installer_ids`                                                                                   |
| Card layout           | `card_identity_files`, `is_editable_config_file`                                                            |

Every method has a docstring on `ScannerProfile` explaining what the
app expects it to return. If a given scanner doesn't support a feature
(e.g. trunked talkgroups), return empty collections / `None` and flip
the relevant `supports_*` property to `False`.

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

## 4. Add a parity test

Drop a `tests/test_<model_id>_parity.py` that locks down the profile's
behavior for the RadioReference modes, encrypted modes, button filters,
and tag-to-service mapping that matter for this scanner. This is the
safety net for future refactors.

## 5. Optional - installer registry

If your scanner has an update tool that should show up in the Uniden
Tools registry, add an entry to `data/uniden_installers.json` with its
download URL and SHA-256 hash, then list the tool ID first in
`preferred_installer_ids()`.

## Checklist

- [ ] Subclass of `ScannerProfile` with every abstract method implemented.
- [ ] Profile registered via `register_profile(...)` at import time.
- [ ] Profile module imported from `scanner_profiles/__init__.py`.
- [ ] Manifest entry in `data/scanner_profiles.json`.
- [ ] Parity tests under `tests/test_<id>_parity.py`.
- [ ] Installer registry entry (if applicable).
- [ ] CHANGELOG updated with the new supported model.
