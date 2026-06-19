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
| Windows | `dist/ScannerManager.exe` (+ `ScannerManager-windows-x64.zip` in CI) |
| macOS | `dist/ScannerManager.app` (+ `ScannerManager-macos.tar.gz` in CI) |
| Linux | `dist/ScannerManager` (+ `ScannerManager-linux-x64.tar.gz` in CI) |

Set `SCANNER_MANAGER_VERSION` when building macOS bundles so Info.plist
matches the git tag.

## CI / release

**Primary:** GitLab CI (`.gitlab-ci.yml`) runs lint + test on every push
and builds all three platform artifacts on `v*` tags (`release:windows`,
`release:macos`, `release:linux`).

**Deprecated mirror:** `.github/workflows/release.yml` is manual
(`workflow_dispatch`) only — use it to publish public GitHub Release
assets after a GitLab-validated tag. Do not treat GitHub as the primary
release gate.

Do not hand-upload EXEs — let CI produce artifacts so SHA-256 sidecars
match the build environment.
