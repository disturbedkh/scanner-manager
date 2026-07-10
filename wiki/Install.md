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

Tagged releases ship two Linux artifacts (same binary payload):

| Artifact | Use |
| --- | --- |
| `ScannerManager-linux-x64.tar.gz` | Portable extract (CI SSOT / smoke) |
| `ScannerManager-x86_64.AppImage` | Double-click / desktop launcher |

**AppImage (easiest on a desktop):**

```bash
chmod +x ScannerManager-x86_64.AppImage
./ScannerManager-x86_64.AppImage
```

**Tar.gz:**

```bash
tar -xzf ScannerManager-linux-x64.tar.gz
chmod +x ScannerManager
./ScannerManager
```

The binary was built on Ubuntu 22.04 and bundles the Qt runtime.
On minimal distros install host X11/GL libs:

```bash
sudo apt install libxcb-cursor0 libegl1 libgl1 libglib2.0-0
```

**Live serial (SDS100/200):** add your user to `dialout`, install the
udev rule so ModemManager does not claim the CDC ports, then re-login:

```bash
sudo usermod -aG dialout "$USER"
sudo cp packaging/linux/99-uniden-scanner.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
```

(The AppImage does **not** install udev rules automatically; a copy is
bundled under `usr/share/doc/scanner-manager/` inside the AppDir.)

**Wayland:** if the window is blank or the coverage map fails, try
`QT_QPA_PLATFORM=xcb ./ScannerManager` (same env works with the AppImage).

After writing firmware/HPDB to a VFAT card, eject safely (or
`sync` / `udisksctl unmount -b /dev/sdX1`) before unplugging.

**Bare-metal verification (operators / agents):** full Ubuntu/Debian
smoke checklist (Live serial, SD, streaming, updater) lives in
[`Metacache/Dev/LINUX_BARE_METAL_HANDOFF.md`](../Metacache/Dev/LINUX_BARE_METAL_HANDOFF.md)—not
required for a normal install.

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

Requires **Python 3.11+**. Qt is the default; Tk is optional for the
legacy entry only.

```bash
git clone https://github.com/disturbedkh/scanner-manager.git
cd scanner-manager
python -m pip install -U pip
# Prefer the universal lock (CI SSOT), then editable without re-resolving:
python -m pip install -r requirements.lock
python -m pip install -e . --no-deps
# Or: python -m pip install -e ".[full,dev]"
scanner-manager          # Qt (default)
scanner-manager-tk       # legacy Tk fallback
```

### Per-OS notes

- **Windows**: the standard python.org installer is fine for Qt.
  Install Tk only if you need `scanner-manager-tk`.
- **macOS**: prefer the python.org build for Tk fallback; Qt/PySide6
  works with Homebrew or python.org Python.
- **Linux (Debian/Ubuntu)**:

  ```bash
  sudo apt install libegl1 libgl1 libglib2.0-0 libxcb-cursor0 \
    libportaudio2 python3-tk
  sudo usermod -aG dialout "$USER"   # re-login after
  sudo cp packaging/linux/99-uniden-scanner.rules /etc/udev/rules.d/
  sudo udevadm control --reload-rules && sudo udevadm trigger
  ```

  Fedora: `sudo dnf install python3-tkinter portaudio`. Arch: `sudo pacman -S tk portaudio`.

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

- Windows: `%APPDATA%\scanner-manager\` (config), `%LOCALAPPDATA%\scanner-manager\` (cache/state)
- macOS: `~/Library/Application Support/scanner-manager/` (and crash logs under `~/Library/Logs/scanner-manager/`)
- Linux:
  - Config: `$XDG_CONFIG_HOME/scanner-manager/` (default `~/.config/scanner-manager/`)
  - Cache: `$XDG_CACHE_HOME/scanner-manager/` (default `~/.cache/scanner-manager/`)
  - State/crash: `$XDG_STATE_HOME/scanner-manager/` (default `~/.local/state/scanner-manager/`)
  - Data (virtual cards, card backups): `$XDG_DATA_HOME/scanner-manager/` (default `~/.local/share/scanner-manager/`)

Source installs: `pip uninstall beartracker-885-scanner-manager`.

## Troubleshooting

- **`ImportError: No module named _tkinter`** — only affects
  `scanner-manager-tk`. Install your distro's Tk package or use the Qt
  default.
- **macOS dialogs look cut off (Tk only)** — switch to python.org Python
  or use the Qt shell.
- **Blank window on Linux/X11 over SSH** — Scanner Manager needs a
  real display or `xvfb-run`. On Wayland, try `QT_QPA_PLATFORM=xcb`.
- **Permission denied on `/dev/ttyACM*`** — add yourself to `dialout`
  and install `packaging/linux/99-uniden-scanner.rules` (see Linux
  section above).
- **Streaming clients cannot connect** — the LAN server binds
  `0.0.0.0:8765`. Allow the port in your firewall (`ufw allow 8765/tcp`
  on Ubuntu) or bind only on trusted networks.
- **EXE / .app doesn't start** — delete corrupt files under the
  user-data paths above and relaunch.
- **Uniden Tools panel says "Windows only"** — expected on macOS /
  Linux. Use a Windows host for Sentinel / BT885 Update Manager.
