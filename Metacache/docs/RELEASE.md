# Release checklist

Follow this file every time you cut a new version.

## 0. Pre-flight

- [ ] `git status` is clean on `main`.
- [ ] `pytest -q` is green locally.
- [ ] Scoped ruff passes on the product tree:

  ```bash
  ruff check core/ gui/ legacy_tk/ scanner_profiles/ scanner_drivers/ \
    firmware/ streaming/ audio/ virtual_sd/ tests/ scripts/ Metacache/Dev/RE/tools/
  ```
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

GitLab CI builds release artifacts under `build/<OS>/Release/` on
`v*` tags (`release:windows`, `release:macos`, `release:linux`):

| OS | Artifact path |
| -- | ------------- |
| Windows | `build/Windows/Release/ScannerManager.exe` (+ zip) |
| macOS | `build/macOS/Release/ScannerManager-macos.tar.gz` |
| Linux | `build/Linux/Release/ScannerManager-linux-x64.tar.gz` |

Local PyInstaller smoke (Development default):

```powershell
pyinstaller packaging/scanner-manager.spec --noconfirm
dir build\Windows\Development\
```

Release-mode local smoke: `$env:SCANNER_MANAGER_BUILD_TYPE='Release'`

**Deprecated mirror:** GitHub Actions `.github/workflows/release.yml` is
manual (`workflow_dispatch`) only — use it to publish public GitHub
Release assets after a GitLab-validated tag.

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

**Secondary:** manually dispatch `.github/workflows/release.yml` on the
public GitHub mirror when intentionally publishing lean release assets.
Draft release notes from `CHANGELOG.md`.

## 4. Announce

- Post `Metacache/docs/forum-announcement.md` to the RadioReference Forums and
  /r/scanners when ready for a public beta.
- Pin the release announcement on the repo.
- Reply to any "is this tool still maintained?" threads you've been
  saving for this moment.

## 5. Post-release

- [ ] Add a new empty `[Unreleased]` section to `CHANGELOG.md`.
- [ ] Bump `pyproject.toml` to the next development version.
- [ ] Close the release milestone; open the next.
