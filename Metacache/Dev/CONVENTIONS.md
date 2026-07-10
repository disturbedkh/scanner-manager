# House Conventions

> Status: **active plan** — house rules for code, tests, docs, and agents.

Rules of the road for editing this repo. Read once, follow always.

## Code

- **Python 3.11+**. Default UI is Qt (`gui/`). Legacy Tk lives in
  `legacy_tk/scanner_manager.py`. Shared backend modules live in
  `core/` — import `core.metastore`, `core.sdcard`, etc. in new code.
- **No new top-level `.py` modules** at repo root. Add code under
  `core/`, `gui/`, `scanner_profiles/`, `firmware/`, `streaming/`, or an
  existing package.
- **No new top-level globals in `legacy_tk/scanner_manager.py`** without
  a reason. Prefer `get_active_profile()` / `set_active_profile()` or
  `core/` helpers in new Qt code.
- **Don't import `legacy_tk.scanner_manager` from inside `scanner_profiles/`.**
  Circular import. The profile package must be self-contained.
- **Type hints** where the rest of the file already uses them. Don't
  retrofit a whole file in passing.
- **Docstrings** on public classes and module-level functions.

## Tests

- `pytest -q` from the repo root must stay green.
- Scanner-profile work must keep these green:
  - `tests/test_bt885_parity.py`
  - `tests/test_scanner_profiles.py`
  - `tests/test_sds100_profile.py`
  - `tests/test_detect_from_card.py` (when touching registry detection)
- If you change `Bt885Profile`, update the matching module-level constants
  in `legacy_tk/scanner_manager.py` and re-run the parity test.
- Adding a profile? Mirror `tests/test_bt885_parity.py` as
  `tests/test_<id>_profile.py` (or `_parity.py` where applicable). See
  `Metacache/docs/adding-a-scanner.md`.

## Lint

- Full-repo ruff (product code + `Metacache/Dev/RE/tools/`):

  ```bash
  ruff check core/ gui/ legacy_tk/ scanner_profiles/ scanner_drivers/ \
    firmware/ streaming/ audio/ virtual_sd/ tests/ scripts/ Metacache/Dev/RE/tools/
  ```

  GitLab CI runs the same scope. Keep it clean.

## Commits and PRs

- **Don't commit unless the user explicitly asks.** Standard policy
  for this project.
- Match the existing terse, capital-first commit subject style:
  - `Beta release v0.11.1 - Metacache export tiers`
  - `Fix ruff lint errors on main (post-v0.10.0)`
- Feature work goes through PRs per `CONTRIBUTING.md`. Read that
  before opening one.

## Documentation

Pick the **right layer** when docs need to change. Language levels
**L0–L4** (AI notebook → human front door): [`Metacache/docs/style-guide.md`](../docs/style-guide.md).

| Change type | Edit first | Lang | Also update |
| --- | --- | --- | --- |
| User-visible feature / UX tour | `wiki/<Page>.md` | L4/L3 | Root `README.md` link table (Agent E) |
| Release / format / contributor checklist | `Metacache/docs/` | L1 | Cross-link from wiki if users need a pointer |
| Agent snapshot, as-built architecture, workstreams | `Metacache/Dev/` (this tree) | L0 | `WORKSTREAMS.md` if status changed |
| Scanner on-disk / serial facts | `Metacache/Dev/RE/docs/` | L0/L2 | Wiki RE pages (Agent C); lab wins on conflict |
| Version / changelog | `CHANGELOG.md` + `pyproject.toml` | — | `PROJECT_STATE.md`, root README |

**Lifecycle banners** on topic docs you touch:

```markdown
> Status: shipped (v0.11.x) | active plan | historical
```

- **shipped** — implemented in code; describe as-built, not backlog.
- **active plan** — living notebook (PROJECT_STATE, WORKSTREAMS, conventions).
- **historical** — superseded; keep for context, mark clearly.

Other rules:

- User-facing release notes: `CHANGELOG.md` (do not edit unless tasked).
- Wiki sources are checked in under `wiki/`; edit there, not on GitHub
  directly.
- Cross-links between layers: prefer full GitHub wiki URLs from repo-root
  docs; sibling links inside `wiki/`.
- `WORKER_LOG.md` append-only; `REVIEW_YYYY-MM.md` historical (factual
  residual fixes OK — do not rewrite narrative).

## Working with the multi-scanner backend

- **Always** read `Metacache/Dev/MULTI_SCANNER_BACKEND.md` before touching
  anything in `scanner_profiles/` or any active-profile call site in
  `legacy_tk/scanner_manager.py` or Qt `gui/` code.
- Use `set_active_profile()` in Qt; do not assume import-time
  `ACTIVE_PROFILE` is current in the default app.
- Don't widen `ScannerProfile` to add abstract methods unless every
  shipping profile implements them in the same change set.

## AI / agent etiquette

- Update `Metacache/Dev/WORKER_LOG.md` at the end of each substantive
  session. One entry, terse, newest on top (**append-only**).
- Update topic docs (`PROJECT_STATE.md`, `MULTI_SCANNER_BACKEND.md`,
  `WORKSTREAMS.md`, as-built design refs) if the work you did invalidates them.
- Don't delete / rewrite historical notebook content; append or mark
  `historical`. Other workers may rely on it.
