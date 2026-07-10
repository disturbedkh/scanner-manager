# Install

> Status: shipped (v0.11.x)

Get Scanner Manager running on your PC so you can edit scanner channel
files, preview coverage, and (on supported models) mirror live activity.

The same core features work on Windows, macOS, and Linux. **Uniden
Tools** (Sentinel and BT885 Update Manager) are **Windows only** — on
macOS and Linux that panel shows a Windows-only notice; everything else
still works.

## Prerequisites

- A desktop PC (Windows, macOS, or Linux)
- For SD-card editing: the scanner's microSD card (or the scanner in
  **Mass Storage** USB mode — the card appears like a USB drive; see
  [Glossary](Glossary))
- Optional: USB serial connection for SDS100/200 live features (**Serial**
  mode — see [Glossary](Glossary))

## Prebuilt downloads (easiest)

Every tagged release ships binaries for Windows, macOS, and Linux. Open
the [Releases page](https://github.com/disturbedkh/scanner-manager/releases)
and download the build for your OS. Prebuilt builds open the **Qt** app
(`ScannerManager` / `ScannerManager.exe`).

### Windows

1. Download `ScannerManager-windows-x64.zip`.
2. Unzip anywhere. Double-click `ScannerManager.exe`.
3. Windows SmartScreen may warn because the EXE isn't code-signed;
   click **More info → Run anyway**.

### macOS

1. Download `ScannerManager-macos.tar.gz`.
2. Double-click to extract, then move `ScannerManager.app` to
   `/Applications`.
3. First launch: right-click the app → **Open**. Gatekeeper warns once
   because the app isn't notarized; after you approve it, later launches
   are normal.

### Linux

Tagged releases ship two Linux downloads (same program, different
packaging):

| Download | When to use it |
| --- | --- |
| `ScannerManager-x86_64.AppImage` | Easiest on a desktop — one file you can double-click |
| `ScannerManager-linux-x64.tar.gz` | Portable folder; also what **Update Now** can replace automatically |

**AppImage (recommended for most desktops):**

```bash
chmod +x ScannerManager-x86_64.AppImage
./ScannerManager-x86_64.AppImage
```

**Tar.gz (folder install):**

```bash
tar -xzf ScannerManager-linux-x64.tar.gz
chmod +x ScannerManager
./ScannerManager
```

The binary was built on Ubuntu 22.04 and includes the Qt runtime. On
minimal distros, install display libraries:

```bash
sudo apt install libxcb-cursor0 libegl1 libgl1 libglib2.0-0
```

**Live serial (SDS100/200):** add your user to the `dialout` group,
install the udev rule so ModemManager does not grab the scanner ports,
then log out and back in:

```bash
sudo usermod -aG dialout "$USER"
sudo cp packaging/linux/99-uniden-scanner.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
```

(The AppImage does **not** install udev rules for you. A copy of the
rule file is bundled under `usr/share/doc/scanner-manager/` inside the
AppImage.)

**Wayland:** if the window is blank or the coverage map fails, try:

```bash
QT_QPA_PLATFORM=xcb ./ScannerManager
```

(Same environment variable works with the AppImage.)

After writing firmware or HPDB files to a VFAT card, eject the card
safely (or run `sync`) before unplugging.

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

Compare the result to the value inside the `.sha256` file next to the
download. If they don't match, do **not** run the binary.

### Staying current

After the first install you usually don't need to re-download by hand.
Use **Help → Check for Updates...** inside the app. See
[Updating](Updating) for what **Update Now** does on each platform
(Windows, Linux tar.gz, Linux AppImage, macOS).

## First run (Qt default)

1. Launch `ScannerManager` (prebuilt) or `scanner-manager` (from source).
2. **Devices → Add device…** — choose BearTracker 885 or SDS100/200,
   give it a name, and point at your SD card's `BCDx36HP` folder (or the
   card root — the app finds `BCDx36HP/HPDB/hpdb.cfg` for you).
3. Pick the device in the header dropdown.

**HPDB** is the scanner's channel database on the card (`hpdb.cfg` plus
the `s_*.hpd` files). The tree loads when a valid path is bound. See
[Glossary](Glossary) and [Quickstart](Quickstart).

## From source (any OS)

Requires **Python 3.11+**. Qt is the default; Classic Tk is optional.

```bash
git clone https://github.com/disturbedkh/scanner-manager.git
cd scanner-manager
python -m pip install -U pip
python -m pip install -r requirements.lock
python -m pip install -e . --no-deps
scanner-manager          # Qt (default)
```

<details>
<summary>Classic Tk shell</summary>

```bash
scanner-manager-tk       # legacy Tk fallback
```

Use this only if you need a Classic Tk workflow (for example RadioReference
import) or prefer the older layout.

</details>

### Per-OS notes

- **Windows:** the standard python.org installer is fine for Qt.
  Install Tk only if you need `scanner-manager-tk`.
- **macOS:** Qt/PySide6 works with Homebrew or python.org Python.
  Prefer the python.org build if you use Classic Tk.
- **Linux (Debian/Ubuntu):**

  ```bash
  sudo apt install libegl1 libgl1 libglib2.0-0 libxcb-cursor0 \
    libportaudio2 python3-tk
  sudo usermod -aG dialout "$USER"   # re-login after
  sudo cp packaging/linux/99-uniden-scanner.rules /etc/udev/rules.d/
  sudo udevadm control --reload-rules && sudo udevadm trigger
  ```

  Fedora: `sudo dnf install python3-tkinter portaudio`. Arch:
  `sudo pacman -S tk portaudio`.

## Optional extras (from source)

Install feature groups as needed:

| Install | Adds |
| --- | --- |
| `pip install -e .[radioreference]` | RadioReference SOAP API + credential storage |
| `pip install -e .[streaming]` | LAN streaming server |
| `pip install -e .[firmware]` | Firmware FTP client (included in full installs) |
| `pip install -e .[map]` | Classic Tk tile map (`tkintermapview`). Qt coverage uses PySide6 + Leaflet instead |
| `pip install -e .[donate-qr]` | QR codes in the Donate dialog (Classic Tk) |
| `pip install -e .[full]` | All optional groups above |

## Uninstall / reset

Prebuilt binaries are self-contained — delete the EXE / `.app` /
binary / AppImage. User data lives under:

- Windows: `%APPDATA%\scanner-manager\` (config),
  `%LOCALAPPDATA%\scanner-manager\` (cache/state)
- macOS: `~/Library/Application Support/scanner-manager/`
  (crash logs under `~/Library/Logs/scanner-manager/`)
- Linux:
  - Config: `~/.config/scanner-manager/` (or `$XDG_CONFIG_HOME/...`)
  - Cache: `~/.cache/scanner-manager/`
  - State/crash: `~/.local/state/scanner-manager/`
  - Data (virtual cards, backups): `~/.local/share/scanner-manager/`

Source installs: `pip uninstall beartracker-885-scanner-manager`.

## If something goes wrong

- **`ImportError: No module named _tkinter`** — only affects
  `scanner-manager-tk`. Install your distro's Tk package, or use the Qt
  default.
- **macOS dialogs look cut off (Classic Tk only)** — switch to
  python.org Python or use the Qt shell.
- **Blank window on Linux** — needs a real display. On Wayland, try
  `QT_QPA_PLATFORM=xcb`. Over SSH, use a local desktop or `xvfb-run`.
- **Permission denied on `/dev/ttyACM*`** — add yourself to `dialout`
  and install the udev rule (Linux section above).
- **Streaming clients cannot connect** — the LAN server listens on port
  `8765`. Allow it in your firewall (`ufw allow 8765/tcp` on Ubuntu) or
  bind only on trusted networks.
- **EXE / .app doesn't start** — delete corrupt files under the
  user-data paths above and relaunch.
- **Uniden Tools panel says "Windows only"** — expected on macOS /
  Linux. Use a Windows PC for Sentinel / BT885 Update Manager.

More recovery tips: [Troubleshooting](Troubleshooting).

## Internals

Operators verifying a full Ubuntu/Debian install (Live serial, SD,
streaming, updater) can follow
[`Metacache/Dev/LINUX_BARE_METAL_HANDOFF.md`](../Metacache/Dev/LINUX_BARE_METAL_HANDOFF.md).
That checklist is not required for a normal desktop install.

From-source installs that prefer an editable resolve without the lock
file can use `python -m pip install -e ".[full,dev]"` instead of the
`requirements.lock` + `--no-deps` path above.
