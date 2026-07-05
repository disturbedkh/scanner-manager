# Adding a new scanner profile (ops checklist)

> Status: shipped (v0.11.x) — implementer checklist and code pointers.
> User-facing walkthrough:
> [Adding-a-Scanner wiki](https://github.com/disturbedkh/scanner-manager/wiki/Adding-a-Scanner).

Scanner Manager uses the `scanner_profiles` package for per-model behavior.
**Shipping profiles today:** `uniden_bt885` (BearTracker 885) and
`uniden_sds100` (SDS100/SDS200). See `data/scanner_profiles.json`.

**Before coding:** read the RE doc for your scanner family under
[`Metacache/Dev/RE/docs/`](../Dev/RE/docs/) (e.g.
[`SDS100.md`](../Dev/RE/docs/SDS100.md), [`BT885.md`](../Dev/RE/docs/BT885.md)).
The lab notebook is the canonical record of on-card layout.

## 1. Subclass `ScannerProfile`

Create `scanner_profiles/<model_id>.py` extending
`scanner_profiles.base.ScannerProfile`. Reference implementations:

| Profile | Module | Test |
| --- | --- | --- |
| BearTracker 885 | `scanner_profiles/bt885.py` | `tests/test_bt885_parity.py` |
| SDS100 / SDS200 | `scanner_profiles/sds100.py` | `tests/test_sds100_profile.py` |

Required surface (implement every abstract method):

| Category | Methods |
| --- | --- |
| Identity | `id`, `display_name`, `family`, `supports_hpd`, `supports_tgid`, `supported_file_extensions`, `target_model_aliases` |
| Service types | `service_types`, `scannable_service_types`, `button_filter`, `service_label`, `service_type_help_text` |
| RadioReference | `rr_mode_to_hpd_mode`, `is_rr_mode_encrypted`, `guess_service_type_from_tag` |
| Firmware tables | `read_zip_table`, `read_city_table` |
| Tools | `preferred_installer_ids` |
| Card layout | `card_identity_files`, `is_editable_config_file` |

**Hard rule:** do not import `legacy_tk.scanner_manager` from inside
`scanner_profiles/*` (circular import).

## 2. Register the profile

At module bottom:

```python
from .registry import register_profile

register_profile(MyScannerProfile())
```

Import the module from `scanner_profiles/__init__.py` so registration runs
at package import (see existing `bt885` / `sds100` lines).

## 3. Update the manifest

Add an entry to `data/scanner_profiles.json`:

```json
{
  "id": "my_scanner",
  "display": "My Scanner 9000",
  "family": "my_family",
  "match_target_model": ["MY9000", "My Scanner 9000"]
}
```

Optional flags used by Qt (see SDS100 entry): `supports_serial_mode`,
`supports_waterfall`, `supports_favorites_lists`, `supports_profile_cfg`,
`usb_vid_pid_main` / `usb_vid_pid_sub`.

## 4. Card detection (Qt)

`scanner_profiles/registry.py` exposes `detect_from_card()` — used by the
Qt editor mismatch banner (`gui/editor/editor_dock.py`). Legacy Tk does
**not** call it yet (backlog).

## 5. Tests

| Profile type | Test file pattern |
| --- | --- |
| BT885-style parity | `tests/test_<id>_parity.py` (locks RR modes, tags, filters) |
| SDS100-style profile | `tests/test_<id>_profile.py` (see `test_sds100_profile.py`) |

Keep `tests/test_bt885_parity.py` green — it is the canary vs.
`legacy_tk/scanner_manager.py` module-level constants.

## 6. Optional — installer registry

For Uniden update tools in the app registry, add to
`data/uniden_installers.json` and list the tool ID first in
`preferred_installer_ids()`. Re-pin hashes with
`scripts/pin_uniden_hashes.py` when rotating installers.

## Checklist

- [ ] `ScannerProfile` subclass with every abstract method implemented.
- [ ] RE doc read / updated under `Metacache/Dev/RE/docs/`.
- [ ] `register_profile(...)` at import time; module imported in `__init__.py`.
- [ ] Manifest entry in `data/scanner_profiles.json`.
- [ ] Tests under `tests/test_<id>_parity.py` or `tests/test_<id>_profile.py`.
- [ ] Installer registry entry (if applicable).
- [ ] `CHANGELOG.md` entry for the new supported model (release cutter).
- [ ] Wiki [Adding-a-Scanner](https://github.com/disturbedkh/scanner-manager/wiki/Adding-a-Scanner) updated if user steps change (Agent B lane).

## Related

| Doc | Purpose |
| --- | --- |
| [`../Dev/MULTI_SCANNER_BACKEND.md`](../Dev/MULTI_SCANNER_BACKEND.md) | Registry, `set_active_profile()`, backend layout |
| [`hpe-format.md`](hpe-format.md) | Favorites List (`.hpe`) format — SDS backlog |
| [`../Dev/WORKSTREAMS.md`](../Dev/WORKSTREAMS.md) | Residual gaps (auto profile switch, Tk `detect_from_card`) |
