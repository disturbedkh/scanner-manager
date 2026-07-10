# Contributing to Scanner Manager

Thanks for looking at the code! Scanner Manager is MIT-licensed and
accepts contributions via GitHub pull requests.

## Dev setup

Python **3.9+** (see `requires-python` in `pyproject.toml`). The default
UI is Qt (PySide6) via `scanner-manager`; legacy Tk remains as
`scanner-manager-tk`. On Linux, install your distro's Tk package if you
need the legacy entry or Tk-only tests (`sudo apt install python3-tk` on
Debian/Ubuntu).

```bash
git clone https://github.com/disturbedkh/scanner-manager.git
cd scanner-manager
python -m pip install -U pip
python -m pip install -e ".[full,dev]"
```

Smoke-test the install:

```bash
scanner-manager --help  # verifies the Qt console-script hook
pytest -m unit -q       # fast tier (default for local iteration)
ruff check core/ gui/ legacy_tk/ scanner_profiles/ scanner_drivers/ \
  firmware/ streaming/ audio/ virtual_sd/ tests/ scripts/
```

## Running tests

Pytest markers are defined in `pyproject.toml`. Use tiers to match CI
without running the full suite on every edit:

| Command | When |
| --- | --- |
| `pytest -m unit -q` | Pure logic, no GUI, no network (fast default) |
| `pytest -m qt -q` | PySide6 + pytest-qt (headless OK) |
| `pytest -m "not requires_serial" -q` | Everything except hardware serial |
| `pytest -x --maxfail=3` | Full suite before opening a PR |
| `pytest tests/test_metastore.py -x` | MetaStore event-log iteration |

On Linux CI uses `xvfb-run -a pytest` because Tk needs a display for
legacy headless dialog tests.

**Sonar / quality gate:** see
[`Metacache/Dev/SONARQUBE.md`](Metacache/Dev/SONARQUBE.md) for
SonarCloud primary gate + VPS compliance workflow.

## Contributor docs (three layers)

| Layer | Path | Use for |
| --- | --- | --- |
| User wiki | [`wiki/`](wiki/) (published to GitHub wiki) | Feature tours, quickstart |
| Ops / release | [`Metacache/docs/README.md`](Metacache/docs/README.md) | Release checklist, formats, style |
| Agent notebook | [`Metacache/Dev/README.md`](Metacache/Dev/README.md) | PROJECT_STATE, workstreams, as-built refs |

**GitHub export:** public mirror rules live in
[`Metacache/EXPORT_POLICY.md`](Metacache/EXPORT_POLICY.md).

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
  `legacy_tk/` (Tk fallback), `scanner_profiles/`, `scanner_drivers/`,
  `firmware/`, `streaming/`, `vendor/uniden_installers/` (dev-only
  MSIs), `tests/fixtures/` (committed test blobs).
- **Never bypass MetaStore for mutations.** If you're touching a
  `FreqEntry`, `GroupNode`, or `SystemNode`, route through the
  existing `_do_*` methods so the change gets logged and is revertable.
  Bulk ops should use `MetaStore.batch()` + `log=False`.
- **Optional dependencies stay optional.** Every third-party import
  must be inside a `try: import / except ImportError` guard or the
  functionality must degrade gracefully. The app has to boot on a
  stock Python install (Qt is required for the default entry).
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

See [`Metacache/Dev/WORKSTREAMS.md`](Metacache/Dev/WORKSTREAMS.md) for
the live backlog. Highlights:

- **Legacy Tk `detect_from_card`** — Tk open dialog still assumes BT885.
- **Favorites Lists editor UI** (SDS100/SDS200).
- **Waterfall live-verify items** — SUB-port span/gain probes need
  hardware confirmation.

If one of those interests you, grab the matching issue and go.
