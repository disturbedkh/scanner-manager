# Troubleshooting

> Status: shipped (v0.11.x)

Common problems and how to recover. Prefer the **Qt** app unless a tip
says Classic Tk.

## My edits are gone / the scanner doesn't boot

1. **Don't panic — don't write to the card again.**
2. Pull the card. Copy every file to a safe folder.
3. Look for `<hpdname>.session.bak` next to the **HPD** file — that is
   the most recent pre-save snapshot.
4. Copy `.session.bak` over the current HPD (drop the `.session.bak`
   suffix) to restore.
5. Still broken? On Windows, use Sentinel or BT885 Update Manager to
   re-pave the card, then re-apply edits from change history if you
   have a Classic Tk **Replay change log onto fresh HPD...** path — or
   restore from your full card backup.

Qt: **Tools → Profile snapshots…** if you took a folder-level backup.

## Profile mismatch banner (Qt)

The editor warns when `scanner.inf` on the card disagrees with the
device's configured model. Use **Devices → Manage devices…** to fix the
profile or SD path, or accept the confirm dialog to switch this device
to the detected profile.

## "Unusable" RadioReference page

Use a **category** or **trunked-system** page (not a site homepage):

- Good: `https://www.radioreference.com/db/sid/7728`
- Good: `https://www.radioreference.com/db/aid/123`

Import runs in **Classic Tk** today (`scanner-manager-tk`). See
[RadioReference Import](RadioReference-Import).

## SmartScreen won't run the EXE

The Windows build is not code-signed. Click **More info → Run anyway**.
Or run from source ([Install](Install)).

## Uniden Tools aren't detected

- **Refresh** after installing
- Non-standard path (for example `C:\Uniden\`) → **Override Path...**
- Expected **"Windows only"** on macOS / Linux

See [Uniden Tools Integration](Uniden-Tools-Integration).

## Installer download fails

- **"Hash mismatch"** — do not bypass; open a GitHub issue with URL and
  hashes
- Corporate network blocks → **Browse for installer...** with a local
  copy

## Coverage map empty or missing tiles

**Qt:** use the **Heatmap** tab, or install a PySide6 build with
WebEngine.

**Classic Tk:**

```bash
python -m pip install -e .[map]
```

Restart. Pure-Tk heatmap still works without tiles.

## Donate dialog has no QR codes (Classic Tk)

```bash
python -m pip install -e .[donate-qr]
```

Address rows and Copy still work without it.

## The app crashed — where's the log?

```
Windows:  %LOCALAPPDATA%\scanner-manager\crash\crash-….log
macOS:    ~/Library/Logs/scanner-manager/crash\crash-….log
Linux:    ~/.local/state/scanner-manager/crash\crash-….log
```

**Help → Report issue…** (Qt) pre-fills a GitHub issue with the log
path.

## Reset everything

1. Close Scanner Manager.
2. Delete the user data directory ([Install](Install) lists paths).
3. Optionally delete `<hpdname>.meta.json` and `.session.bak` next to
   the HPD for a fresh change history.
4. Relaunch.

## Serial / Live dock won't connect (SDS100/200)

- Scanner must be in **Serial** USB mode (two COM ports /
  `/dev/ttyACM*`), not Mass Storage only — see [Glossary](Glossary)
- Pick MAIN and SUB in the Live dock; **Refresh** after plugging in
- Close Sentinel or any other app holding the ports
- **Linux:** `dialout` group + udev rule
  (`packaging/linux/99-uniden-scanner.rules`) — see [Install](Install)

## Blank window / map broken on Linux

- Needs a real display (or `xvfb-run` for tests)
- Wayland: try `QT_QPA_PLATFORM=xcb`
- Minimal distros: `libxcb-cursor0` and GL/EGL packages
  ([Install](Install))

## Firmware write then unplug (Linux VFAT)

After applying firmware or HPDB, eject safely (Desktop eject, `sync`, or
`udisksctl unmount`) before removing the media.

## Streaming clients cannot connect

Default LAN port is **8765**. Allow it in the firewall or bind only on
trusted networks ([Streaming Server](Streaming-Server)).
