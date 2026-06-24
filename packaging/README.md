# Packaging

Everything needed to produce cross-platform Scanner Manager binaries
from the **Qt default** entry (`packaging/entry_qt.py` → `gui.app:main`).

## Files

- `entry_qt.py` - PyInstaller bootstrap; imports `gui.app.main` as a package.
- `scanner-manager.spec` - PyInstaller spec. Bundles `data/*.json`, legal
  notices, and the full Qt + `core/` backend (including `virtual_sd`,
  firmware, streaming). Does **not** bundle `vendor/uniden_installers/`.
- `icon.ico` / `icon.icns` - app icons for Windows/Linux and macOS.

## Build locally

Preferred (orchestrator — matches CI tag builds):

```powershell
pip install -r requirements.lock
pip install -e . --no-deps
python scripts/build_release.py --type Development
python scripts/build_release.py --type Release --smoke
```

Manual PyInstaller (same output paths):

```powershell
python -m pip install -e ".[full,dev]"
pyinstaller packaging/scanner-manager.spec --noconfirm
```

Outputs land under `build/<OS>/<Release|Development>/`:

| Platform | Default (Development) | CI tag builds (Release) |
| -------- | --------------------- | ----------------------- |
| Windows | `build/Windows/Development/ScannerManager.exe` | `build/Windows/Release/ScannerManager.exe` (+ zip in CI) |
| macOS | `build/macOS/Development/ScannerManager.app` | `build/macOS/Release/ScannerManager.app` (+ tar.gz in CI) |
| Linux | `build/Linux/Development/ScannerManager` | `build/Linux/Release/ScannerManager` (+ tar.gz in CI) |

Set `SCANNER_MANAGER_BUILD_TYPE=Release` for release-mode local smoke.
Set `SCANNER_MANAGER_VERSION` when building macOS bundles so Info.plist
matches the git tag.

PyInstaller intermediate files go to
`build/<OS>/<Type>/.pyinstaller-work/` (gitignored via `build/`).

**Note:** `python -m build` (wheel/sdist for PyPI-style publish) still
writes to repo-root `dist/` — that is separate from PyInstaller output.

## CI / release

**Primary:** GitLab CI (`.gitlab-ci.yml`) — lint, tiered tests, coverage gate,
optional self-hosted SonarQube, then on `v*` tags: build → `--smoke` verify →
GitLab Release publish. See `Metacache/Dev/BUILD_SYSTEM.md`.

**Deprecated mirror:** `.github/workflows/release.yml` is manual
(`workflow_dispatch`) only — use it to publish public GitHub Release
assets after a GitLab-validated tag.

Do not hand-upload EXEs — let CI produce artifacts so SHA-256 sidecars
match the build environment.
