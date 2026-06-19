# Contributing to Scanner Manager

Thanks for looking at the code! Scanner Manager is MIT-licensed and
accepts contributions via GitHub pull requests.

## Dev setup

Python 3.9+ with Tkinter. On Linux, install your distro's Tk package
(`sudo apt install python3-tk` on Debian/Ubuntu).

```bash
git clone https://gitlab.com/garudadev1/scanner-manager.git
cd scanner-manager
python -m pip install -U pip
python -m pip install -e ".[full,dev]"
```

Smoke-test the install:

```bash
scanner-manager --help  # verifies the console-script hook
pytest -q               # runs the test suite
ruff check core/ gui/ legacy_tk/ scanner_profiles/ scanner_drivers/ \
  firmware/ streaming/ audio/ virtual_sd/ tests/ scripts/ AI/Dev/RE/tools/
```

## Running tests

- `pytest -x --maxfail=3` for the full suite.
- `pytest tests/test_metastore.py -x` for just the event log tests
  while iterating on MetaStore changes.
- On Linux CI uses `xvfb-run -a pytest` because Tk needs a display
  for the headless dialog tests.

## Code style

- **Ruff** is the single source of truth for formatting + linting. CI
  runs scoped `ruff check` on the product tree (see smoke-test above);
  there's no separate `black` pass.
- Line length is 100.
- Imports sorted via `ruff --select I`.
- No comments narrating obvious code - reserve comments for
  non-obvious intent, trade-offs, or external constraints.

## Architectural guidelines

- **Package layout:** `core/` (backend), `gui/` (Qt default UI),
  `legacy_tk/` (Tk fallback), `scanner_profiles/`, `vendor/uniden_installers/`
  (dev-only MSIs), `tests/fixtures/` (committed test blobs).
- **Never bypass MetaStore for mutations.** If you're touching a
  `FreqEntry`, `GroupNode`, or `SystemNode`, route through the
  existing `_do_*` methods so the change gets logged and is revertable.
  Bulk ops should use `MetaStore.batch()` + `log=False`.
- **Optional dependencies stay optional.** Every third-party import
  must be inside a `try: import / except ImportError` guard or the
  functionality must degrade gracefully. The app has to boot on a
  stock Python + Tk install.
- **No telemetry, no phone-home.** Full stop.
- **Don't bundle Uniden binaries in releases.** Production installs fetch
  via `data/uniden_installers.json`. Dev copies may live under
  `vendor/uniden_installers/`.

## Commit style

- Present-tense verb, scoped prefix: `metastore: collapse import to
  composite event`, `ui: add three-row toolbar`, `packaging: pyinstaller
  spec`.
- Reference issues in the body when relevant.

## Pull request expectations

1. Rebase on top of `main` before opening the PR.
2. All tests green (`pytest -x`) and no new ruff findings.
3. Add/update a test for anything non-trivial.
4. If it's user-facing, add a bullet to `CHANGELOG.md` under
   `[Unreleased]`.
5. Keep PRs focused. Giant drive-by refactors are hard to review.

## Reporting bugs

See [SECURITY.md](SECURITY.md) for security issues. Everything else:
open a GitHub issue. Include:

- Scanner Manager version (bottom of Help → About, or window title).
- OS + Python version.
- What you were doing, what you expected, what happened.
- If there's a crash log under `%LOCALAPPDATA%/scanner-manager/logs/`,
  attach it.

The Help → Report an Issue... menu entry pre-fills most of this.

## What needs work

- **Splitting `scanner_manager.py` into modules** - 480 KB is too
  big. Post-alpha refactor.
- **Non-Windows packaging** - no macOS app bundle or Linux AppImage
  yet. Tk works fine, just no packaged artifact.
- **Diff UI improvements** - the workspace sync dialog is functional
  but spartan.

If one of those interests you, grab the matching issue and go.
