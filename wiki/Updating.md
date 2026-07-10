# Updating Scanner Manager

> Status: shipped (v0.11.x)

Scanner Manager ships with a built-in GitHub-release updater so you
don't need to use git or track the download page to stay current.

## One-click updates

1. **Help → Check for Updates...** runs a fresh query and always shows
   a dialog, even when you're already on the latest version.
2. The app also does a silent background check ~5 seconds after
   startup. If a newer release is out — and you haven't skipped that
   specific version — an *Update available* dialog appears.
3. The dialog shows release notes and four actions:
   - **Update Now** — platform-dependent (see below).
   - **Open Release Page** — sends you straight to the GitHub
     Releases page for manual download.
   - **Skip This Version** — remembers the version in
     `app_settings.json` so we won't prompt again until a newer one
     drops.
   - **Remind Me Later** — closes the dialog but leaves the check
     alive so it'll re-prompt after 24 hours.

### Windows EXE (frozen)

**Update Now** opens the release page for a manual EXE replace today.
An in-place `.bat` swap helper exists in code but is not fully wired
in the Qt dialog yet.

### Linux tar.gz / ELF (frozen)

**Update Now** downloads `ScannerManager-linux-x64.tar.gz`, verifies
its SHA-256 against the sibling `.sha256` asset, extracts the
`ScannerManager` binary, swaps it over the running file via a small
shell helper, and relaunches.

### Linux AppImage

In-place Update Now is **not** supported for AppImage installs.
Download the new `ScannerManager-x86_64.AppImage` from the release
page and replace the old file (`chmod +x` again if needed).

### macOS

The updater detects new releases and opens the release page. In-place
swaps need Gatekeeper handling that isn't built yet; download the new
archive and replace your install manually.

## Running from source (`pip install`)

Source installs update the same way any other editable Python package
does:

```bash
git pull
pip install -e . --upgrade
```

The in-app **Check for Updates...** dialog still works — it'll simply
direct you to the release page rather than attempting a binary swap.

## Skipping / disabling the check

`app_settings.json` stores three relevant keys:

| Key | Default | Notes |
|---|---|---|
| `updater_check_on_startup` | `true` | Toggle to disable the silent background check. |
| `updater_skipped_version` | `""` | Set by the **Skip This Version** button. |
| `updater_last_check_at` | `0` | Unix timestamp of the last attempt; the 24h debounce runs off this. |

Deleting or zeroing `updater_skipped_version` will re-enable prompts
for a previously-skipped release.

## Repository mirrors

Development happens on a private GitLab mirror with full RE context.
The public GitHub repo is a **filtered export** — see
[`Metacache/EXPORT_POLICY.md`](../Metacache/EXPORT_POLICY.md). Safe
Metacache RE files (docs, tools, specs) ship on GitHub as of v0.11.1;
agent notebooks, firmware blobs, and raw captures do not. Release tags
and binaries are published from GitHub only.

## Privacy

The updater talks only to
`https://api.github.com/repos/disturbedkh/scanner-manager/releases/latest`
with a standard User-Agent header. No analytics, no telemetry.
