# Troubleshooting

Common failure modes and how to recover.

## My edits are gone / the scanner doesn't boot

1. **Don't panic, don't write to the card again.**
2. Pull the card. Copy every file off to a safe folder.
3. If you've been using Scanner Manager, look for `<hpdname>.session.bak`
   right next to the HPD file. That's the most recent pre-save
   snapshot.
4. Copy the `.session.bak` over the current HPD (renaming to drop
   the `.session.bak` suffix) to restore.
5. Still broken? Run Uniden's Sentinel or BT885 Update Manager to
   re-pave the card from factory defaults, then re-import your groups
   from the MetaStore event log using **Tools → Replay change log
   onto fresh HPD...**.

## "Unusable" RadioReference page

Double-check the URL. The importer wants a **category** or
**trunked-system** page:

- Good: `https://www.radioreference.com/db/sid/7728`
- Good: `https://www.radioreference.com/db/aid/123`
- Bad: `https://www.radioreference.com/apps/db/...` (homepage)

If the right URL still fails, open a GitHub issue with the URL and the
page's raw HTML if you can.

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

- **"Hash mismatch"** - do **not** bypass the check by re-running.
  Open a GitHub issue with the URL, expected hash, and observed hash;
  the maintainers will roll the manifest if Uniden rotated the
  installer.
- **Corporate network blocks** - use **Browse for installer...** in
  the Download dialog to point at a copy you obtained elsewhere.

## Coverage Map button does nothing

Install the optional dep:

```bash
python -m pip install tkintermapview
```

Restart the app. Until then, use **Heatmap...** for a pure-Tkinter
fallback.

## Donate dialog has no QR codes

Install the optional dep:

```bash
python -m pip install qrcode
```

Restart the app. Address rows and Copy buttons still work without it.

## The app crashed - where's the log?

Global crash handler writes to:

```
%LOCALAPPDATA%/scanner-manager/logs/crash-YYYYmmdd-HHMMSS.log
```

The crash dialog also offers a **Report an Issue...** button that
pre-fills the GitHub issue form with the traceback and log path. Use
it - maintainers need those logs to fix alpha bugs.

## Reset everything

If things go sideways:

1. Close Scanner Manager.
2. Delete `%LOCALAPPDATA%/scanner-manager/` (app settings, crash logs,
   installer cache).
3. Delete `<hpdname>.meta.json` and `<hpdname>.session.bak` next to
   your HPD file if you want a fresh event history too.
4. Relaunch.
