# Install

> Status: shipped (v0.11.x)

Scanner Manager runs on all three major desktop OSes. The core — HPD
editing, ZIP/GPS simulation, workspaces, MetaStore — works identically
everywhere on whichever shell you launch. The Uniden vendor tools
(Sentinel and BT885 Update Manager) are Windows-only binaries, so on
macOS and Linux the Uniden Tools panel shows a "Windows only" notice.
Everything else is unaffected.

## Prebuilt downloads (easiest)

Every tagged release ships binaries for Windows, macOS, and Linux. Go
to the [Releases page](https://github.com/disturbedkh/scanner-manager/releases)
and grab the one for your OS. Prebuilt builds launch the **Qt shell**
(`ScannerManager` / `ScannerManager.exe`).

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

3. The binary was built on Ubuntu 22.04 and bundles the Qt runtime.
   You may need `libxcb-cursor0` or similar X11 libs on minimal
   distros.

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

## First-run (Qt default)

Launch `scanner-manager` (or the prebuilt binary). Register your
scanner under **Devices → Add device…**, point it at your SD card's
`BCDx36HP` folder (or the card root — the app resolves
`BCDx36HP/HPDB/hpdb.cfg` automatically), and pick the device in the
header dropdown. The HPDB tree loads when a valid path is bound.

## From source (any OS)

Requires **Python 3.9+**. Qt is the default; Tk is optional for the
legacy entry only.

```bash
git clone https://github.com/disturbedkh/scanner-manager.git
cd scanner-manager
python -m pip install -r requirements.txt
python -m pip install -e .
scanner-manager          # Qt (default)
scanner-manager-tk       # legacy Tk fallback
```

### Per-OS notes

- **Windows**: the standard python.org installer is fine for Qt.
  Install Tk only if you need `scanner-manager-tk`.
- **macOS**: prefer the python.org build for Tk fallback; Qt/PySide6
  works with Homebrew or python.org Python.
- **Linux**: for legacy Tk, install your distro's Tk package:

  ```bash
  sudo apt install python3-tk           # Debian / Ubuntu
  sudo dnf install python3-tkinter      # Fedora / RHEL
  sudo pacman -S tk                     # Arch
  ```

## Optional extras

Install feature groups as needed:

| Install | Adds |
| --- | --- |
| `pip install -e .[radioreference]` | RadioReference SOAP API (`zeep`) + credential storage (`keyring`). |
| `pip install -e .[streaming]` | LAN streaming server (FastAPI, encoders). |
| `pip install -e .[firmware]` | Firmware FTP client (included in full installs). |
| `pip install -e .[map]` | Legacy Tk tile map (`tkintermapview`). Qt coverage uses PySide6 + Leaflet instead. |
| `pip install -e .[donate-qr]` | QR codes in the Donate dialog (legacy Tk). |
| `pip install -e .[full]` | All optional groups above. |

## Uninstall / reset

Prebuilt binaries are self-contained — delete the EXE / .app /
binary. User data lives under:

- Windows: `%LOCALAPPDATA%\scanner-manager\`
- macOS: `~/Library/Application Support/scanner-manager/` (and crash logs under `~/Library/Logs/scanner-manager/`)
- Linux: `~/.config/scanner-manager/` or `$XDG_STATE_HOME/scanner-manager/`

Source installs: `pip uninstall beartracker-885-scanner-manager`.

## Troubleshooting

- **`ImportError: No module named _tkinter`** — only affects
  `scanner-manager-tk`. Install your distro's Tk package or use the Qt
  default.
- **macOS dialogs look cut off (Tk only)** — switch to python.org Python
  or use the Qt shell.
- **Blank window on Linux/X11 over SSH** — Scanner Manager needs a
  real display or `xvfb-run`.
- **EXE / .app doesn't start** — delete corrupt files under
  `%LOCALAPPDATA%\scanner-manager\` and relaunch.
- **Uniden Tools panel says "Windows only"** — expected on macOS /
  Linux. Use a Windows host for Sentinel / BT885 Update Manager.
