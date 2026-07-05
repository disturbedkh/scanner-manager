# Alerts

> Status: shipped (v0.11.x) — legacy Tk viewer only

The BearTracker 885 writes metadata (and often an audio clip) into
`alert/` on the SD card whenever a user-defined alert trigger fires
(for example, a priority channel hit). Scanner Manager ships a light
viewer for that folder so you don't have to open it in Explorer.

## Alerts viewer

**Legacy Tk only** (`scanner-manager-tk`): **Alerts...** on the toolbar
opens the viewer. It:

1. Walks the card's `alert/` folder recursively.
2. Lists every non-hidden file with size + modification timestamp.
3. Lets you **Open** a file in the OS default handler or **Reveal in
   Explorer**.

Audio files open in your default audio player; CSV/TXT files in your
default text editor.

The Qt shell does not port this dialog yet — launch `scanner-manager-tk`
with the same SD path, or browse `alert/` in your file manager.

## What the viewer doesn't do (yet)

- No in-app audio playback.
- No cross-session aggregation or statistics.
- No Qt port.

Track requests on the
[issues page](https://github.com/disturbedkh/scanner-manager/issues).
