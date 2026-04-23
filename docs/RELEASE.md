# Release checklist

Follow this file every time you cut a new version. It's written around
`v0.9.0-alpha.1` but the steps generalize.

## 0. Pre-flight

- [ ] `git status` is clean on `main`.
- [ ] `pytest -x` is green locally.
- [ ] `ruff check .` passes.
- [ ] `CHANGELOG.md` has a heading for the new version (move content
      from `[Unreleased]` into `[0.9.0a1] - YYYY-MM-DD`).
- [ ] `pyproject.toml` `version` matches.
- [ ] `data/uniden_installers.json` hashes are pinned. If you're
      rotating installers this release, bump `manifest_version` and
      re-run `python -c "import uniden_tools, hashlib; ..."` against
      the freshly downloaded file to verify the pin.

## 1. Release candidate tag

```bash
git checkout -b release/v0.9.0-alpha.1-rc1
git push -u origin release/v0.9.0-alpha.1-rc1
git tag -a v0.9.0-alpha.1-rc1 -m "v0.9.0-alpha.1-rc1"
git push origin v0.9.0-alpha.1-rc1
```

GitHub Actions fires `.github/workflows/release.yml`:

- Builds `ScannerManager.exe` on `windows-latest` via the PyInstaller
  spec.
- Computes `ScannerManager.exe.sha256`.
- Builds the source + wheel distributions on `ubuntu-latest`.
- Publishes a **pre-release** GitHub Release with EXE, checksum,
  tarball, and wheel attached.

The release is flagged as pre-release automatically because the tag
contains `alpha`, `beta`, or `rc`.

## 2. Smoke test

On a clean Windows 10 / 11 machine:

1. Download the EXE + its `.sha256`.
2. Verify the hash matches.
3. Run the EXE. SmartScreen warns because it's unsigned; click
   *More info -> Run anyway*.
4. First-run alpha notice appears. Dismiss.
5. Load an SD card; basic tree browsing works.
6. `Help -> About` shows the new version.
7. `Help -> Donate / Support...` opens cleanly; copy-to-clipboard
   works on every row.
8. `Uniden Tools -> Install... (for a tool you don't have)` opens the
   download dialog, downloads from Uniden's CDN, verifies the hash,
   and runs the installer.
9. Trigger an intentional error (e.g. mangle a `.meta.json`) to
   confirm the crash hook writes a log and offers a pre-filled issue
   URL.

If anything fails, fix it on `main`, bump to `-rc2`, and repeat. Do
**not** re-use the `-rc1` tag for a second attempt.

## 3. Public tag

Once the RC smoke-tests clean:

```bash
git checkout main
git tag -a v0.9.0-alpha.1 -m "v0.9.0-alpha.1"
git push origin v0.9.0-alpha.1
```

That tag runs the same workflow and produces the public
pre-release. Draft the release notes from `CHANGELOG.md`.

## 4. Announce

- Post `docs/forum-announcement.md` to the RadioReference Forums and
  /r/scanners.
- Pin the release announcement on the repo.
- Reply to any "is this tool still maintained?" threads you've been
  saving for this moment.

## 5. Post-release

- [ ] Add a new empty `[Unreleased]` section to `CHANGELOG.md`.
- [ ] Bump `pyproject.toml` to the next development version
      (`0.9.1a0.dev0` or whatever is next on the roadmap).
- [ ] Close the release milestone; open the next.
