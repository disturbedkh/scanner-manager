# Release checklist

> Status: shipped (v0.11.x) — follow every tagged release.
> User-facing update notes:
> [Updating wiki](https://github.com/disturbedkh/scanner-manager/wiki/Updating).

Build-system design: [`../Dev/BUILD_SYSTEM.md`](../Dev/BUILD_SYSTEM.md).
Sonar gates: [`../Dev/SONARQUBE.md`](../Dev/SONARQUBE.md).

## 0. Pre-flight

- [ ] `git status` is clean on `main`.
- [ ] `pytest -m "not requires_serial and not slow" -q` is green locally.
- [ ] Scoped ruff passes on the product tree:

  ```bash
  ruff check core/ gui/ legacy_tk/ scanner_profiles/ scanner_drivers/ \
    firmware/ streaming/ audio/ virtual_sd/ tests/ scripts/ Metacache/Dev/RE/tools/
  ```
- [ ] `requirements.lock` is fresh (`.\scripts\refresh_lockfile.ps1` if
      `pyproject.toml` deps changed).
- [ ] Sonar: SonarCloud gate green on GitHub `main`; optional local
      `.\scripts\sonar_scan.ps1` (VPS compliance) + `.\scripts\sonar_compare.ps1`.
- [ ] `CHANGELOG.md` has a heading for the new version (move content
      from `[Unreleased]`).
- [ ] `pyproject.toml` `version` matches (e.g. `0.11.1`).
- [ ] `data/uniden_installers.json` hashes are pinned when rotating
      installers (re-run `scripts/pin_uniden_hashes.py` or verify
      against freshly downloaded files).

Install path for local checks and CI:

```bash
pip install -r requirements.lock
pip install -e . --no-deps
```

## 1. GitLab CI (primary gate)

Every push to `main` runs `.gitlab-ci.yml` (lint + tiered tests + coverage
gate + optional SonarQube VPS).

For a release candidate or final tag:

```bash
git tag -a v0.11.1 -m "v0.11.1 - description"
git push origin v0.11.1
```

GitLab CI on `v*` tags:

1. Builds release artifacts under `build/<OS>/Release/`
2. Runs frozen `--smoke` verification + SHA-256 sidecar checks
3. Publishes a **GitLab Release** with permanent assets

| OS | Artifact |
| -- | -------- |
| Windows | `ScannerManager-windows-x64.zip` (+ `.sha256`) |
| macOS | `ScannerManager-macos.tar.gz` (+ `.sha256`) |
| Linux | `ScannerManager-linux-x64.tar.gz` (+ `.sha256`) |

Also attached: wheel/sdist, `build-provenance.json`.

Local PyInstaller smoke:

```powershell
python scripts/build_release.py --type Release --smoke
```

**Deprecated mirror:** GitHub Actions `.github/workflows/release.yml` is
manual (`workflow_dispatch`) only — use after GitLab-validated tag.

## 2. Smoke test

### CI (automatic on tag)

Frozen binaries run `--smoke` in the `verify` stage (bundled data,
imports, version print).

### Manual (clean machine)

On a clean Windows 10 / 11 machine:

1. Download assets from the **GitLab Release** page (not ephemeral job
   artifacts).
2. Verify the `.sha256` sidecar matches.
3. Run the EXE. SmartScreen warns because it's unsigned; click
   *More info → Run anyway*.
4. Optional CLI smoke: `ScannerManager.exe --smoke`
5. Full UI: first-run notice, load an SD card, `Help → About` version
   (`0.11.x`).
6. Import smoke (dev/CI also runs this):

   ```bash
   python -c "import gui.app; import core.metastore, core.uniden_tools"
   python -c "import legacy_tk.scanner_manager"
   ```

If anything fails, fix on `main`, bump to `-rc2` or a new beta tag, and
repeat. Do **not** re-use a tag for a second attempt.

## 3. Public GitHub mirror

After GitLab-validated tag, publish the filtered public tree:

```powershell
.\scripts\publish_github.ps1 -Tag v0.11.1 -Force
```

See [`../EXPORT_POLICY.md`](../EXPORT_POLICY.md) for Metacache export
tiers (`public_original` / `public_sanitize` / `gitignore_only`).

**Secondary:** manually dispatch `.github/workflows/release.yml` on the
public GitHub mirror when intentionally publishing lean release assets.
Draft release notes from `CHANGELOG.md`.

## 4. Announce

- Post [`forum-announcement.md`](forum-announcement.md) to RadioReference
  Forums and /r/scanners when ready for a public beta.
- Pin the release announcement on the repo.
- Reply to any "is this tool still maintained?" threads you've been
  saving for this moment.

## 5. Post-release

- [ ] Add a new empty `[Unreleased]` section to `CHANGELOG.md`.
- [ ] Bump `pyproject.toml` to the next development version.
- [ ] Close the release milestone; open the next.

## Related

| Doc | Purpose |
| --- | --- |
| [`README.md`](README.md) | Ops doc index |
| [`../ROADMAP.md`](../ROADMAP.md) | Build Phase 2 (SonarCloud + VPS) |
| [Updating wiki](https://github.com/disturbedkh/scanner-manager/wiki/Updating) | End-user update instructions |
