# Test fixtures

Binary and capture files used by the pytest suite. Not user runtime state.

| Path | Purpose |
| --- | --- |
| `firmware/SDS-100-SUB_V1_03_15.firm` | Real Sub firmware blob for parser/updater tests |
| `captures/sds-capture-20260503-170346.json` | Reference serial diagnostic capture |

Use `tests.conftest.fixtures_dir()` to resolve paths from test code.
