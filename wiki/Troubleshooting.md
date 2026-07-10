# Troubleshooting

> Status: shipped (v0.11.x)

Common failure modes and how to recover.

## My edits are gone / the scanner doesn't boot

1. **Don't panic, don't write to the card again.**
2. Pull the card. Copy every file off to a safe folder.
3. Look for `<hpdname>.session.bak` right next to the HPD file. That's
   the most recent pre-save snapshot.
4. Copy the `.session.bak` over the current HPD (renaming to drop
   the `.session.bak` suffix) to restore.
5. Still broken? Run Uniden's Sentinel or BT885 Update Manager to
   re-pave the card from factory defaults, then re-import your groups
   from the MetaStore event log using **Tools → Replay change log
   onto fresh HPD...** (legacy Tk).

Qt users can also try **Tools → Profile snapshots…** if a folder-level
backup was taken.

## Profile mismatch banner (Qt)

The editor warns when `scanner.inf` on the card disagrees with the
device's configured model (e.g. SDS100 card under a BT885 device row).
Open **Devices → Manage devices…** and fix the profile or SD path.
Automatic profile switch on load is not implemented yet.

## "Unusable" RadioReference page

Double-check the URL. The importer wants a **category** or
**trunked-system** page:

- Good: `https://www.radioreference.com/db/sid/7728`
- Good: `https://www.radioreference.com/db/aid/123`
- Bad: `https://www.radioreference.com/apps/db/...` (homepage)

RadioReference import runs in **legacy Tk** today (`scanner-manager-tk`).

## SmartScreen won't run the EXE

Because the EXE isn't code-signed, Windows SmartScreen treats it as
unknown. Click **More info → Run anyway**. After a few users have
reported the file as safe, SmartScreen usually relaxes.

You can always run from source instead (`pip install -e .`).

## Uniden Tools aren't detected

- Click **Refresh** after installing.
- If the tool landed in a non-standard path (e.g. `C:\Uniden\`), use
  **Override Path...** and point at the EXE directly.
- Check `app_settings.json` under `%LOCALAPPDATA%/scanner-manager/` to
  see what override got stored.

## Installer download fails

- **"Hash mismatch"** — do **not** bypass the check by re-running.
  Open a GitHub issue with the URL, expected hash, and observed hash;
  the maintainers will roll the manifest if Uniden rotated the
  installer.
- **Corporate network blocks** — use **Browse for installer...** in
  the Download dialog to point at a copy you obtained elsewhere.

## Coverage map empty or missing tiles

**Qt:** install a PySide6 build that includes QtWebEngine, or use the
heatmap tab (pyqtgraph) which does not need tiles.

**Legacy Tk:**

```bash
python -m pip install -e .[map]
```

Restart the app. Until then, the pure-Tk heatmap fallback still works.

## Donate dialog has no QR codes (legacy Tk)

```bash
python -m pip install -e .[donate-qr]
```

Address rows and Copy buttons still work without it.

## The app crashed — where's the log?

Global crash handler writes to:

```
# Qt + legacy (v0.11.x)
Windows:  %LOCALAPPDATA%\scanner-manager\crash\crash-YYYYmmdd-HHMMSS.log
macOS:    ~/Library/Logs/scanner-manager/crash/crash-....log
Linux:    ~/.local/state/scanner-manager/crash/crash-....log
```

**Help → Report issue…** (Qt) pre-fills a GitHub issue with the log
path. Use it — maintainers need tracebacks to fix beta regressions.

## Reset everything

1. Close Scanner Manager.
2. Delete the user data directory (see [Install](Install) for paths).
3. Delete `<hpdname>.meta.json` and `<hpdname>.session.bak` next to
   your HPD file if you want a fresh event history too.
4. Relaunch.

## Serial / Live dock won't connect (SDS100/200)

- Scanner must be in **serial USB mode** (two COM ports / `/dev/ttyACM*`),
  not mass storage only.
- Pick MAIN and SUB ports in the Live dock; click Refresh if you just
  plugged in.
- Only one host app should hold the serial ports — close Sentinel if
  it has the device open.
- **Linux:** join the `dialout` group and install
  `packaging/linux/99-uniden-scanner.rules` so ModemManager does not
  claim the CDC ports (see [Install](Install)).

## Blank window / map broken on Linux

- Need a real display (or `xvfb-run` for tests).
- On Wayland, try `QT_QPA_PLATFORM=xcb`.
- Minimal distros may need `libxcb-cursor0` and GL/EGL packages
  ([Install](Install)).

## Firmware write then unplug (Linux VFAT)

After applying firmware/HPDB to a card, eject safely (Desktop eject, or
`sync` / `udisksctl unmount`) before removing the media.
