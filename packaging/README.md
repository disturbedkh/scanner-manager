# Packaging

Everything needed to produce cross-platform Scanner Manager binaries
from the **Qt default** entry (`gui/app.py`).

## Files

- `scanner-manager.spec` - PyInstaller spec. Bundles `data/*.json`, legal
  notices, and the full Qt + `core/` backend (including `virtual_sd`,
  firmware, streaming). Does **not** bundle `vendor/uniden_installers/`.
- `icon.ico` / `icon.icns` - app icons for Windows/Linux and macOS.

## Build locally

From the repo root (matches CI/release install path):

```powershell
python -m pip install -e ".[full,dev]"
pyinstaller packaging/scanner-manager.spec --noconfirm
```

Outputs:

| Platform | Artifact |
| -------- | -------- |
| Windows | `dist/ScannerManager.exe` |
| macOS | `dist/ScannerManager.app` |
| Linux | `dist/ScannerManager` |

Set `SCANNER_MANAGER_VERSION` when building macOS bundles so Info.plist
matches the git tag.

## CI / release

**Primary:** GitLab CI (`.gitlab-ci.yml`) runs lint + test on every push
and builds the Windows EXE on `v*` tags.

**Secondary:** `.github/workflows/release.yml` still publishes public
GitHub Release assets when tags are pushed to GitHub. Prefer GitLab tags
for the private full-context mirror.

Do not hand-upload EXEs — let CI produce artifacts so SHA-256 sidecars
match the build environment.
