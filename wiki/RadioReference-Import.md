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

## How the import is logged

A multi-hundred-entry import would normally produce one MetaStore event
per added row. Instead, Scanner Manager:

1. Enters a MetaStore **batch** so only one sidecar write hits disk.
2. Performs every add / update / avoid / delete with `log=False` so no
   per-entry event is recorded.
3. Records **one composite `OP_IMPORT_APPLY` event** summarizing the
   entire operation, with enough payload to reverse it later.

Result: imports are fast, produce tiny change-log entries, and one
**Revert** click in the Changes dialog rolls the whole import back.

## Reconciliation with user edits

When you re-run an import later:

- Your **Avoid** and **Delete** flags are preserved.
- Your **service-type overrides** are preserved.
- Renames you've made are preserved when RR can still be matched by
  frequency or TGID.
- New RR rows are added.
- RR rows you deleted stay deleted.

See [Architecture](Architecture) for how the event replay logic backs
this up.

## Troubleshooting

- **"Unusable page"** - double-check the URL. A `.../db/sid/...` that
  shows talkgroups should work; a site index page won't.
- **Slow / stuck loading** - the SOAP API has better per-request
  throughput than scraping; consider entering RR credentials.
- **Login errors** - clear the credential via Settings and re-enter.
