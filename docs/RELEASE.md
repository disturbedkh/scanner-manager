# Release checklist

Follow this file every time you cut a new version.

## 0. Pre-flight

- [ ] `git status` is clean on `main`.
- [ ] `pytest -q` is green locally.
- [ ] Scoped ruff passes on the product tree:

  ```bash
  ruff check core/ gui/ legacy_tk/ scanner_profiles/ scanner_drivers/ \
    firmware/ streaming/ audio/ virtual_sd/ tests/ scripts/
  ```

  (`AI/Dev/RE/tools/` is excluded until a separate cleanup MR.)
- [ ] `CHANGELOG.md` has a heading for the new version (move content
      from `[Unreleased]` into `[0.9.0b3] - YYYY-MM-DD`).
- [ ] `pyproject.toml` `version` matches.
- [ ] `data/uniden_installers.json` hashes are pinned when rotating
      installers (re-run `scripts/pin_uniden_hashes.py` or verify
      against freshly downloaded files).

Install path for local checks and CI:

```bash
python -m pip install -e ".[full,dev]"
```

## 1. GitLab CI (primary gate)

Every push to `main` runs `.gitlab-ci.yml` (lint + test matrix).

For a release candidate or final tag:

```bash
git tag -a v0.9.0b3 -m "v0.9.0b3 - layout reorg and GitLab CI parity"
git push origin v0.9.0b3
```

GitLab CI builds the Windows EXE on `v*` tags (`release:windows` job)
and uploads artifacts with SHA-256 sidecars.

## 2. Smoke test

On a clean Windows 10 / 11 machine:

1. Download the EXE + its `.sha256` from GitLab job artifacts (or
   GitHub Release if mirroring publicly).
2. Verify the hash matches.
3. Run the EXE. SmartScreen warns because it's unsigned; click
   *More info → Run anyway*.
4. First-run notice appears. Dismiss.
5. Load an SD card; basic tree browsing works in the Qt UI.
6. `Help → About` shows the new version.
7. Import smoke (dev/CI also runs this):

   ```bash
   python -c "import gui.app; import core.metastore, core.uniden_tools"
   python -c "import legacy_tk.scanner_manager"
   ```

8. Trigger an intentional error (e.g. mangle a `.meta.json`) to
   confirm the crash hook writes a log and offers a pre-filled issue
   URL.

If anything fails, fix on `main`, bump to `-rc2` or a new beta tag, and
repeat. Do **not** re-use a tag for a second attempt.

## 3. Public mirror (optional)

GitHub Actions `.github/workflows/release.yml` still publishes public
Release assets when tags are pushed to the GitHub remote. Prefer GitLab
tags for the private full-context mirror; mirror to GitHub only when
intentionally publishing a lean subset.

Draft release notes from `CHANGELOG.md`.

## 4. Announce

- Post `docs/forum-announcement.md` to the RadioReference Forums and
  /r/scanners when ready for a public beta.
- Pin the release announcement on the repo.
- Reply to any "is this tool still maintained?" threads you've been
  saving for this moment.

## 5. Post-release

- [ ] Add a new empty `[Unreleased]` section to `CHANGELOG.md`.
- [ ] Bump `pyproject.toml` to the next development version.
- [ ] Close the release milestone; open the next.
