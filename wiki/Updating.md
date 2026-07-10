# Updating Scanner Manager

> Status: shipped (v0.11.x)

Keep Scanner Manager current without hunting the Releases page every
time. Use the built-in updater from inside the app.

## Prerequisites

- A working install ([Install](Install))
- Internet access (the app checks GitHub Releases)

## One-click updates

1. **Help → Check for Updates...** always shows a dialog — even when
   you are already on the latest version.
2. About five seconds after startup, the app also checks quietly in the
   background. If a newer release exists (and you have not skipped that
   version), an **Update available** dialog appears.
3. The dialog shows release notes and four actions:
   - **Update Now** — behavior depends on how you installed (see below).
   - **Open Release Page** — opens GitHub Releases for a manual download.
   - **Skip This Version** — stops prompting for this version until a
     newer one ships.
   - **Remind Me Later** — closes the dialog; you may be prompted again
     after about 24 hours.

### What Update Now does

| How you installed | What **Update Now** does |
| --- | --- |
| **Windows** (`.exe` zip) | Opens the release page so you can download and replace the EXE. An automatic swap helper is not fully wired in the Qt dialog yet. |
| **Linux tar.gz** | Downloads `ScannerManager-linux-x64.tar.gz`, checks its checksum, replaces the `ScannerManager` binary, and relaunches. |
| **Linux AppImage** | **Not supported in-place.** Download the new `ScannerManager-x86_64.AppImage` from the release page, replace the old file, and run `chmod +x` again if needed. |
| **macOS** | Opens the release page. In-place swaps need Gatekeeper handling that is not built yet — replace the app manually. |
| **From source** (`pip` / git) | Opens the release page. Update with `git pull` and `pip install -e . --upgrade` (see below). |

**AppImage vs tar.gz (Linux):** if you want one-click **Update Now**,
prefer the tar.gz folder install. If you prefer a single double-click
file, use the AppImage and replace it by hand when a release drops.

## Running from source

```bash
git pull
pip install -e . --upgrade
```

**Help → Check for Updates...** still works — it points you at the
release page rather than swapping a binary.

## Skipping or turning off the check

- **Skip This Version** in the dialog remembers that version so you are
  not prompted again until a newer release appears.
- To allow prompts for a version you previously skipped, clear the
  skipped-version setting (see Internals below) or wait for a newer
  release.

## Privacy

The updater talks only to
`https://api.github.com/repos/disturbedkh/scanner-manager/releases/latest`
with a normal User-Agent header. No analytics, no telemetry.

## If something goes wrong

- Dialog says you are up to date but GitHub shows a newer tag — try
  **Help → Check for Updates...** again, or download from the
  [Releases page](https://github.com/disturbedkh/scanner-manager/releases)
  manually.
- Linux tar.gz update fails mid-swap — re-download the release archive
  and replace `ScannerManager` by hand, then `chmod +x ScannerManager`.
- AppImage still runs the old build — confirm you replaced the file you
  actually launch (shortcuts can point at an old path).

More help: [Troubleshooting](Troubleshooting).

## Internals

Settings live in `app_settings.json`:

| Key | Default | Notes |
| --- | --- | --- |
| `updater_check_on_startup` | `true` | Silent background check after launch |
| `updater_skipped_version` | `""` | Set by **Skip This Version** |
| `updater_last_check_at` | `0` | Last check time; used for the ~24h remind debounce |

Clearing `updater_skipped_version` re-enables prompts for a previously
skipped release.

Development uses a private GitLab mirror; the public GitHub repo is a
filtered export (see [`Metacache/EXPORT_POLICY.md`](../Metacache/EXPORT_POLICY.md)).
Release tags and binaries are published from GitHub only. Safe Metacache
RE docs and tools ship on GitHub as of 0.11.x; agent notebooks, firmware
blobs, and raw captures do not.
