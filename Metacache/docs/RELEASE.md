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
      on the private Forgejo remote (`gitea`), and that you are not shipping
      a version that will remain tagless:

  ```powershell
  git describe --tags --always
  git ls-remote --tags gitea "refs/tags/v*"
  ```

  **Do not** announce or publish a version whose annotated tag is missing
  from Forgejo `gitea`. Tree claims (`pyproject` / `CHANGELOG`) without a
  matching `v*` tag are a release-integrity failure.
- [ ] **Claimed vs tagged (catch-up cuts):** if `pyproject` / `CHANGELOG`
      already advertise `X.Y.Z` but Forgejo never received `vX.Y.Z`, either:
      - cut annotated catch-up tag `vX.Y.Z` on the commit that matches those
        notes; or
      - bump to `X.Y.(Z+1)`, then tag that.
- [ ] `data/uniden_installers.json` hashes are pinned when rotating
      installers (re-run `scripts/pin_uniden_hashes.py` or verify
      against freshly downloaded files).

Install path for local checks and CI:

```bash
pip install -r requirements.lock
pip install -e . --no-deps
```

## 1. CI / tag gate (Forgejo SSOT)

Private SSOT: Forgejo `gitea` →
`https://git.kjhuttoenterprises.com/disturbedkh/Scanner-Manager`.
[`.gitlab-ci.yml`](../../.gitlab-ci.yml) is **historical** (GitLab.com
deprecated). Forgejo Actions cutover is a **follow-up** — until then, run
lint/tests locally before tagging.

**Human-gated:** annotated tag creation, `git push gitea v*`, and
`publish_github.ps1` are **not** agent-automatic.

```bash
git tag -a v0.11.2 -m "v0.11.2 - description"
git push gitea v0.11.2
```

Local PyInstaller smoke:

```powershell
python scripts/build_release.py --type Release --smoke
```

**Public mirror:** GitHub Actions `.github/workflows/release.yml` remains
manual (`workflow_dispatch`) for lean public assets after
`publish_github.ps1`.

## 2. Smoke test

### Manual (clean machine)

On a clean Windows 10 / 11 machine:

1. Download assets from the **GitHub Releases** page (after publish) or
   a private build artifact you trust.
2. Verify the `.sha256` sidecar matches.
3. Run the EXE. SmartScreen warns because it's unsigned; click
   *More info → Run anyway*.
4. Optional CLI smoke: `ScannerManager.exe --smoke`
5. Full UI: first-run notice, load an SD card, `Help → About` version
   (`0.11.x`).
6. Import smoke:

   ```bash
   python -c "import gui.app; import core.metastore, core.uniden_tools"
   python -c "import legacy_tk.scanner_manager"
   ```

Linux bare-metal HIL (optional, Phase 4):
[`../Dev/LINUX_BARE_METAL_HANDOFF.md`](../Dev/LINUX_BARE_METAL_HANDOFF.md).

If anything fails, fix on `main`, bump, and repeat. Do **not** re-use a
tag for a second attempt.

## 3. Public GitHub mirror

After the private tag is on Forgejo `gitea`, publish the filtered public tree:

```powershell
.\scripts\publish_github.ps1 -Tag v0.11.2 -Force
```

**Required reading:** [`../EXPORT_POLICY.md`](../EXPORT_POLICY.md) —
tiers `public_original` / `public_sanitize` / `gitignore_only`; machine
rules in `scripts/metacache_export_rules.yaml`. Needs `GITEA_TOKEN` /
`FORGEJO_TOKEN` to clone the private HTTPS remote.

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
