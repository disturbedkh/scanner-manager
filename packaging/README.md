# Packaging

Everything needed to produce the one-file Windows EXE for Scanner Manager.

## Files

- `scanner-manager.spec` - PyInstaller spec. Runs the PyInstaller
  `--onefile --windowed` build and bundles `data/uniden_installers.json`,
  the LICENSE, and related legal notices inside the EXE.
- `icon.ico` - placeholder app icon (256x256 PNG-in-ICO). Swap in a real
  piece of art before the 1.0 release; the build will pick it up
  automatically.

## Build locally

From the repo root:

```bash
python -m pip install pyinstaller
pyinstaller packaging/scanner-manager.spec --noconfirm
```

The output lands at `dist/ScannerManager.exe` (~25 MB on Python 3.12).

## CI

`.github/workflows/release.yml` runs this same command on a `v*` tag,
computes the EXE's SHA-256, and attaches both the EXE and its checksum
file to the GitHub Release. Don't run locally and upload - let the
workflow produce the release artifact so the checksum matches CI.
