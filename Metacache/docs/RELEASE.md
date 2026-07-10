# Release checklist

> Status: shipped (v0.11.x) — follow every tagged release.
> User-facing update notes:
> [Updating wiki](https://github.com/disturbedkh/scanner-manager/wiki/Updating).

Build-system design: [`../Dev/BUILD_SYSTEM.md`](../Dev/BUILD_SYSTEM.md).
Sonar gates: [`../Dev/SONARQUBE.md`](../Dev/SONARQUBE.md).
Release-blocker triage / GA gate: [`../ROADMAP.md`](../ROADMAP.md).
GitHub Metacache filter: [`../EXPORT_POLICY.md`](../EXPORT_POLICY.md).

Prefer version wording **`0.11.x`** in docs; pin **`0.11.2` / `v0.11.2`**
only where the cut must match `pyproject.toml` + tag.

## 0. Pre-flight

- [ ] `git status` is clean on `main`.
- [ ] `pytest -m "not requires_serial and not slow" -q` is green locally.
      (Qt teardown ACCESS_VIOLATION / segfault after a fully green log is
      tolerated in CI; do not treat that alone as a release blocker for beta.)
- [ ] Scoped ruff passes on the product tree:

  ```bash
  ruff check core/ gui/ legacy_tk/ scanner_profiles/ scanner_drivers/ \
    firmware/ streaming/ audio/ virtual_sd/ tests/ scripts/ Metacache/Dev/RE/tools/
  ```
- [ ] `requirements.lock` is fresh (`.\scripts\refresh_lockfile.ps1` if
      `pyproject.toml` deps changed).
- [ ] Sonar: SonarCloud gate green on GitHub `main`; optional local
      `.\scripts\sonar_scan.ps1` (VPS compliance) + `.\scripts\sonar_compare.ps1`.
- [ ] **Version sync (hard gate):** all three match the intended release:
      1. `pyproject.toml` `version` (e.g. `0.11.2`)
      2. `CHANGELOG.md` heading `## [0.11.2] - YYYY-MM-DD`
      3. Intended annotated tag name `v0.11.2`
- [ ] **Tag existence check:** confirm the intended tag is **not** already
      on GitLab, and that you are not shipping a version that will remain
      tagless:

  ```powershell
  # Local describe (may show commits past last tag — that is the gap to close)
  git describe --tags --always
  # Remote tags on GitLab (origin)
  git ls-remote --tags origin "refs/tags/v*"
  ```

  **Do not** announce or publish a version whose annotated tag is missing
  from GitLab `origin`. Tree claims (`pyproject` / `CHANGELOG`) without a
  matching `v*` tag are a release-integrity failure.
- [ ] **Claimed vs tagged (catch-up cuts):** if `pyproject` / `CHANGELOG`
      already advertise `X.Y.Z` but GitLab never received `vX.Y.Z`, either:
      - cut annotated catch-up tag `vX.Y.Z` on the commit that matches those
        notes, and note “catch-up tag” in the GitLab Release description; or
      - bump to `X.Y.(Z+1)`, move post-claim commits into the new CHANGELOG
        section, then tag that. Prefer bump when HEAD has material product
        changes not covered by the existing `X.Y.Z` notes.
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

**Human-gated:** annotated tag creation, `git push origin v*`, waiting on
GitLab Release jobs, and `publish_github.ps1` are **not** agent-automatic.
Only cut/push a tag when a human explicitly requests that release step.

For a release candidate or final tag:

```bash
git tag -a v0.11.2 -m "v0.11.2 - description"
git push origin v0.11.2
```

GitLab CI on `v*` tags:

1. Builds release artifacts under `build/<OS>/Release/`
2. Runs frozen `--smoke` verification + SHA-256 sidecar checks
3. Publishes a **GitLab Release** with permanent assets

| OS | Artifact |
| -- | -------- |
| Windows | `ScannerManager-windows-x64.zip` (+ `.sha256`) |
| macOS | `ScannerManager-macos.tar.gz` (+ `.sha256`) |
| Linux | `ScannerManager-linux-x64.tar.gz` (+ `.sha256`) — smoke/verify SSOT |
| Linux | `ScannerManager-x86_64.AppImage` (+ `.sha256`) |

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
imports, version print). Linux verify SSOT is the **tar.gz** (not AppImage).

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

Linux bare-metal HIL (optional, Phase 4): 
[`../Dev/LINUX_BARE_METAL_HANDOFF.md`](../Dev/LINUX_BARE_METAL_HANDOFF.md).

If anything fails, fix on `main`, bump to `-rc2` or a new beta tag, and
repeat. Do **not** re-use a tag for a second attempt.

## 3. Public GitHub mirror

After GitLab-validated tag, publish the filtered public tree:

```powershell
.\scripts\publish_github.ps1 -Tag v0.11.2 -Force
```

**Required reading:** [`../EXPORT_POLICY.md`](../EXPORT_POLICY.md) —
tiers `public_original` / `public_sanitize` / `gitignore_only`; machine
rules in `scripts/metacache_export_rules.yaml`.

**Secondary:** manually dispatch `.github/workflows/release.yml` on the
public GitHub mirror when intentionally publishing lean release assets.
Draft release notes from `CHANGELOG.md`.

## 4. Announce

- Reuse [`forum-announcement.md`](forum-announcement.md) only as a
  **historical** template; refresh wording against wiki + `CHANGELOG.md`
  before posting to RadioReference / Reddit.
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
| [`../EXPORT_POLICY.md`](../EXPORT_POLICY.md) | GitLab full tree vs GitHub filtered export |
| [`../ROADMAP.md`](../ROADMAP.md) | Build phases, release-blocker triage, GA gate |
| [`../Dev/LINUX_BARE_METAL_HANDOFF.md`](../Dev/LINUX_BARE_METAL_HANDOFF.md) | Ubuntu HIL checklist |
| [Updating wiki](https://github.com/disturbedkh/scanner-manager/wiki/Updating) | End-user update instructions |
