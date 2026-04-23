# Alerts and Discovery

The BearTracker 885 writes two kinds of artifacts to the SD card as
you use it:

- **Alerts** - when a user-defined alert trigger (e.g. a priority
  channel hitting) fires, the scanner writes metadata and often an
  audio clip into `alert/`.
- **Discovery** - if enabled, the scanner dumps CSVs and per-event
  files describing frequencies / TGIDs it heard during a discovery
  session into `discovery/`.

Scanner Manager includes simple viewers for both so you don't have to
open the folders in Explorer.

## Alerts viewer

**Alerts...** on the toolbar opens the viewer. It:

1. Walks the card's `alert/` folder recursively.
2. Lists every non-hidden file with size + modification timestamp.
3. Lets you **Open** a file in the OS default handler or **Reveal in
   Explorer**.

Audio files will open in your default audio player; CSV/TXT files in
your default text editor.

## Discovery viewer

**Discovery...** opens the same style viewer against `discovery/`. In
addition to listing raw files, it surfaces the summary rows from the
per-session CSV so you can see which sessions are worth opening.

## What the viewers don't do (yet)

- No in-app audio playback.
- No cross-session aggregation or statistics.
- No "push discovery hits into a group" shortcut.

Those are on the 0.9.x / 1.0 roadmap and are tracked on the
[issues page](https://github.com/disturbedkh/scanner-manager/issues).
