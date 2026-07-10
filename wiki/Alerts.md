# Alerts

> Status: shipped (v0.11.x) — Classic Tk viewer only

Browse alert files the BearTracker 885 writes to the SD card when a
user-defined alert fires (for example a priority channel hit) — without
digging through Explorer by hand.

## Prerequisites

- BearTracker 885 SD card with an `alert/` folder
- Classic Tk shell (`scanner-manager-tk`) — Qt does not port this dialog
  yet

## Steps (Classic Tk)

1. Load the card in `scanner-manager-tk`.
2. Click **Alerts...** on the toolbar.
3. Browse the list (size + modification time for each non-hidden file).
4. **Open** in the OS default app, or **Reveal in Explorer**.

Audio opens in your default player; text/CSV in your default editor.

In Qt, use the same SD path in Classic Tk, or browse `alert/` in your
file manager.

## What the viewer does not do yet

- No in-app audio playback
- No cross-session stats
- No Qt port

Feature requests:
[issues page](https://github.com/disturbedkh/scanner-manager/issues).

## If something goes wrong

- Empty list — confirm `alert/` exists on the card and the correct SD
  path is loaded
- File won't open — check the OS file association for that extension
