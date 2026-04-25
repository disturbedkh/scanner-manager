# Install

Scanner Manager runs on all three major desktop OSes. The core — HPD
editing, RadioReference import, ZIP/GPS simulation, workspaces,
MetaStore — works identically everywhere. The Uniden vendor tools
(Sentinel and BT885 Update Manager) are Windows-only binaries, so on
macOS and Linux the Uniden Tools panel shows a "Windows only" notice.
Everything else is unaffected.

## Prebuilt downloads (easiest)

Every tagged release ships binaries for Windows, macOS, and Linux. Go
to the [Releases page](https://github.com/disturbedkh/scanner-manager/releases)
and grab the one for your OS.

### Windows

1. Download `ScannerManager-windows-x64.zip`.
2. Unzip anywhere. Double-click `ScannerManager.exe`.
3. Windows SmartScreen may warn because the EXE isn't code-signed;
   click **More info → Run anyway**.

### macOS

1. Download `ScannerManager-macos.tar.gz`.
2. Double-click to extract, move `ScannerManager.app` to `/Applications`.
3. First launch: right-click the app → **Open**. Gatekeeper will warn
   once because the app isn't notarized; after you approve it, it
   launches normally from then on.

### Linux

1. Download `ScannerManager-linux-x64.tar.gz`.
2. Extract:

   ```bash
   tar -xzf ScannerManager-linux-x64.tar.gz
   chmod +x ScannerManager
   ./ScannerManager
   ```

3. The binary was built on Ubuntu 22.04, so it needs glibc 2.31+ and
   Tk. On Debian/Ubuntu:

   ```bash
   sudo apt install python3-tk
   ```

### Verifying the download

Each asset ships with a matching `.sha256` file.

```powershell
# Windows
(Get-FileHash -Algorithm SHA256 .\ScannerManager-windows-x64.zip).Hash
```

```bash
# macOS / Linux
shasum -a 256 ScannerManager-macos.tar.gz
sha256sum   ScannerManager-linux-x64.tar.gz
```

Compare against the value inside the `.sha256` file next to the
download. If they don't match, do **not** run the binary.

### Staying current

After the first install you don't need to re-download manually. **Help
→ Check for Updates...** from inside the app will pull the next
release directly from GitHub, verify its SHA-256, and swap the EXE
for you on Windows. See [Updating](Updating) for the full flow.

## First-run

The first launch shows an *alpha notice* modal. Dismiss it once; it
won't appear again. The app will land on an empty tree view with the
status bar reading "Ready. Browse to your SD card's BCDx36HP folder to
begin."

## From source (any OS)

Requires Python 3.9+ with Tkinter support.

```bash
git clone https://github.com/disturbedkh/scanner-manager.git
cd scanner-manager
python -m pip install -r requirements.txt
python -m pip install -e .
scanner-manager
```

### Per-OS notes

- **Windows**: the standard python.org installer ships Tk. Nothing
  else needed.
- **macOS**: prefer the python.org build — the Apple-supplied system
  Python has a stripped Tk that breaks some dialogs. Alternatively
  `brew install python-tk@3.12` (matching your Python minor version).
- **Linux**: install your distro's Tk package:

  ```bash
  sudo apt install python3-tk           # Debian / Ubuntu
  sudo dnf install python3-tkinter      # Fedora / RHEL
  sudo pacman -S tk                     # Arch
  ```

## Optional extras

Scanner Manager runs with a minimal core and enables extra features as
dependencies become available:

| Install                                             | Adds                                                  |
| --------------------------------------------------- | ----------------------------------------------------- |
| `pip install zeep keyring`                          | RadioReference SOAP API access + credential storage.  |
| `pip install tkintermapview`                        | Real tile-server map in the Coverage Map dialog.      |
| `pip install qrcode`                                | QR codes in the Donate dialog.                        |
| `pip install beartracker-885-scanner-manager[full]` | All of the above.                                     |

## Uninstall / reset

Prebuilt binaries are self-contained — just delete the EXE / .app /
binary and the data it wrote next to itself (`app_settings.json`,
`scanner_manager.meta.json`, `*.session.bak`, `zip_county_map.json`).
Source installs: `pip uninstall beartracker-885-scanner-manager`.

## Troubleshooting

- **`ImportError: No module named _tkinter`** — install your distro's
  Tk package (Linux) or reinstall Python with Tk support.
- **macOS dialogs look cut off or fonts render oddly** — almost always
  the system Python's Tk build. Switch to python.org Python.
- **Blank window on Linux/X11 over SSH** — Scanner Manager needs a
  real display or `xvfb-run`.
- **EXE / .app doesn't start at all** — delete the companion files
  it wrote next to itself and try again; a corrupt `app_settings.json`
  can block startup.
- **Uniden Tools panel says "Windows only"** — expected on macOS /
  Linux. Uniden doesn't publish Mac or Linux builds of Sentinel or
  the BT885 Update Manager. Use a Windows host (or Wine / Crossover
  at your own risk) to run those specific vendor tools.
