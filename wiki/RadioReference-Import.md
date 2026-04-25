# RadioReference Import

Scanner Manager can pull channel rows straight from
[RadioReference.com](https://www.radioreference.com) in two modes,
depending on what's available.

## Modes

### HTML scrape (no account needed)

Paste any public RadioReference URL and Scanner Manager parses the
page. Works for:

- Conventional frequency **categories**
  (`/db/aid/...` / `/db/sid/...` conventional pages).
- FCC callsign pages.
- Trunked **talkgroup** listings.

Login isn't required for HTML scraping but RadioReference rate-limits
aggressive scraping - don't hammer it.

### SOAP API (requires an RR account)

If you have a RadioReference premium subscription, Scanner Manager can
talk to the official SOAP API via `zeep`:

1. **Settings → RadioReference account** - enter your username +
   password. They're stored in the OS credential vault (Windows
   Credential Manager / macOS Keychain / Secret Service on Linux) via
   `keyring`. Scanner Manager never writes credentials to disk in
   clear text.
2. The Import dialog will prefer the SOAP API when credentials are
   present, falling back to the HTML scraper only if the API is
   unreachable.

SOAP is more reliable for trunked systems with many TGIDs and for
bulk pulls; the HTML scraper is handy for one-off categories.

## The import dialog

1. Click **Import from RR...**.
2. Paste a URL.
3. Scanner Manager loads and parses, then shows a two-column diff:
   - **Left:** what's currently in the HPD.
   - **Right:** what RR has.
4. Tick the rows you want to add or overwrite; leave the rest alone.
5. **Apply**.

## How the import is recorded

Instead of logging hundreds of separate edits, the whole import is
recorded as a **single entry in the Change History**. That means:

- Imports stay fast and don't bloat the change log.
- One **Revert** click rolls the entire import back in one go.
- The RadioReference refresh data you most care about - the rows that
  were added, updated, or deleted - is captured as a single summary
  you can undo cleanly.

## Reconciliation with user edits

When you re-run an import later:

- Your **Delete** flags are preserved.
- Your **service-type overrides** are preserved.
- Renames you've made are preserved when RR can still be matched by
  frequency or TGID.
- New RR rows are added.
- RR rows you deleted stay deleted.

See [Architecture](Architecture) for how the event replay logic backs
this up.

## Encrypted talkgroups

The BearTracker 885 can't decode encrypted audio, so Scanner Manager
defaults to keeping these out of your HPD:

- **New imports** skip encrypted TGIDs entirely.
- **Refreshes** of an existing system delete any existing entries that
  RadioReference has since flagged encrypted. Those deletions are
  bundled into the same Change History entry as the import, so one
  Revert click restores everything.
- **Override:** the import dialog has a "Include encrypted talkgroups
  (not recommended)" checkbox for power users who want the entries in
  the tree anyway. The choice is remembered per-system.

## Troubleshooting

- **"Unusable page"** - double-check the URL. A `.../db/sid/...` that
  shows talkgroups should work; a site index page won't.
- **Slow / stuck loading** - the SOAP API has better per-request
  throughput than scraping; consider entering RR credentials.
- **Login errors** - clear the credential via Settings and re-enter.
