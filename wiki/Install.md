# Install

## Windows one-file EXE (easiest)

1. Go to the
   [Releases page](https://github.com/disturbedkh/scanner-manager/releases).
2. Download the `ScannerManager.exe` attached to the latest release,
   plus its `ScannerManager.exe.sha256` file if you want to verify.
3. Double-click. Windows SmartScreen may warn you because the EXE is
   not code-signed; click **More info → Run anyway**.

### Verifying the download

```powershell
(Get-FileHash -Algorithm SHA256 .\ScannerManager.exe).Hash
```

Compare the result (lowercased) against the value inside the `.sha256`
file. If they don't match, do **not** run the EXE.

### First-run

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

### Linux

`python3-tk` is usually not installed by default on Debian/Ubuntu:

```bash
sudo apt install python3-tk
```

### macOS

macOS Python from python.org already ships Tk. If you installed Python
via Homebrew, also install `python-tk@3.12` (or whatever version you
use).

## Optional extras

Scanner Manager runs with a minimal core and enables extra features as
dependencies become available:

| Install                                   | Adds                                                  |
| ----------------------------------------- | ----------------------------------------------------- |
| `pip install zeep keyring`                | RadioReference SOAP API access + credential storage.  |
| `pip install tkintermapview`              | Real tile-server map in the Coverage Map dialog.      |
| `pip install qrcode`                      | QR codes in the Donate dialog.                        |
| `pip install beartracker-885-scanner-manager[full]` | All of the above. |

## Troubleshooting

- **`ImportError: No module named _tkinter`** - install your distro's
  Tk package (Linux) or reinstall Python with Tk support.
- **Blank window on Linux/X11 over SSH** - Scanner Manager needs a
  real display or `xvfb-run`.
- **EXE doesn't start at all** - delete `%LOCALAPPDATA%/scanner-manager`
  and try again; a corrupt `app_settings.json` can block startup.
