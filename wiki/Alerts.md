# Alerts

The BearTracker 885 writes metadata (and often an audio clip) into
`alert/` on the SD card whenever a user-defined alert trigger fires
(for example, a priority channel hit). Scanner Manager ships a light
viewer for that folder so you don't have to open it in Explorer.

## Alerts viewer

**Alerts...** on the toolbar opens the viewer. It:

1. Walks the card's `alert/` folder recursively.
2. Lists every non-hidden file with size + modification timestamp.
3. Lets you **Open** a file in the OS default handler or **Reveal in
   Explorer**.

Audio files open in your default audio player; CSV/TXT files in your
default text editor.

## What the viewer doesn't do (yet)

- No in-app audio playback.
- No cross-session aggregation or statistics.

Those are on the roadmap; track and file requests on the
[issues page](https://github.com/disturbedkh/scanner-manager/issues).
