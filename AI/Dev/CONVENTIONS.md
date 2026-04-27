# House Conventions

Rules of the road for editing this repo. Read once, follow always.

## Code

- **Python 3.9+**, single-file desktop app in `scanner_manager.py` plus
  focused helper modules (`metastore`, `sdcard`, `coverage_maps`,
  `rr_api`, `uniden_tools`, `updater`, `scanner_profiles/`).
- **No new top-level globals in `scanner_manager.py`** without a
  reason. Prefer pushing data into the active `ScannerProfile` or a
  helper module.
- **Don't import `scanner_manager` from inside `scanner_profiles/`.**
  Circular import. The profile package must be self-contained.
- **Type hints** where the rest of the file already uses them. Don't
  retrofit a whole file in passing.
- **Docstrings** on public classes and module-level functions.

## Tests

- `pytest -q` from the repo root must stay green.
- New scanner-profile work must keep
  `tests/test_bt885_parity.py` and `tests/test_scanner_profiles.py`
  green. If you change `Bt885Profile`, update the matching
  module-level constants in `scanner_manager.py` and re-run the
  parity test.
- Adding a profile? Mirror `tests/test_bt885_parity.py` as
  `tests/test_<id>_parity.py`. See `docs/adding-a-scanner.md`.

## Lint

- `ruff check .` clean. The headline commit on `main` right now
  (`fb75913`) is literally a ruff-cleanup commit; don't reintroduce.

## Commits and PRs

- **Don't commit unless the user explicitly asks.** Standard policy
  for this project.
- Match the existing terse, capital-first commit subject style:
  - `Beta release v0.9.0b2 - heatmap, profiles, scanner-driver layer`
  - `Fix ruff lint errors on main (post-v0.9.0b2)`
- Feature work goes through PRs per `CONTRIBUTING.md`. Read that
  before opening one.

## Documentation

- User-facing changes: update `README.md` and `CHANGELOG.md`.
- Architecture / refactor changes: update the relevant doc in
  `docs/` and the matching topic file in `AI/Dev/`.
- Wiki sources are checked in under `wiki/`; edit there, not on
  GitHub directly.

## Working with the multi-scanner backend

- **Always** read `AI/Dev/MULTI_SCANNER_BACKEND.md` before touching
  anything in `scanner_profiles/` or any `ACTIVE_PROFILE` call site
  in `scanner_manager.py`.
- Don't widen `ScannerProfile` to add abstract methods unless
  `Bt885Profile` implements them in the same change set.

## AI / agent etiquette

- Update `AI/Dev/WORKER_LOG.md` at the end of each substantive
  session. One entry, terse, newest on top.
- Update topic docs (`PROJECT_STATE.md`, `MULTI_SCANNER_BACKEND.md`,
  `WORKSTREAMS.md`) if the work you did invalidates them.
- Don't delete content from these notes; archive instead. Other
  workers may rely on it.
