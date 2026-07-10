# RadioReference Import

> Status: shipped (v0.11.x) — import UI in Classic Tk; shared backend

Pull channel rows from [RadioReference.com](https://www.radioreference.com)
into your on-card **HPD** database, review a diff, and apply — with the
whole import undoable as one change-history entry.

<details>
<summary>Classic Tk shell (required for import UI today)</summary>

The full **Import from RR...** dialog, group linking, and refresh flows
run in **`scanner-manager-tk`**. Qt records imports in change history
and shares the API client, but does not yet expose the import dialog.
Use Classic Tk for imports until the Qt port lands.

</details>

## Prerequisites

- Card loaded in Classic Tk ([Install](Install), [Quickstart](Quickstart))
- A RadioReference category or trunked-system URL (or premium account
  for the official API)
- Optional: `pip install -e .[radioreference]` for SOAP API + keyring
  credential storage

## Modes

### HTML scrape (no account needed)

Paste a public RadioReference URL. Works for conventional categories,
FCC callsign pages, and trunked talkgroup listings. Do not hammer the
site — RadioReference rate-limits aggressive scraping.

### SOAP API (RR account)

With a premium RadioReference subscription:

1. **Settings → RadioReference account** (Classic Tk) — username and
   password. Stored in the OS credential vault (never clear-text on
   disk).
2. The import dialog prefers the API when credentials are present, and
   falls back to HTML scrape if the API is unreachable.

SOAP is better for large trunked systems; HTML scrape is fine for
one-off categories.

## Steps (Classic Tk)

1. Load the card, then click **Import from RR...**.
2. Paste a URL.
3. Review the two-column diff: left = current HPD, right = RadioReference.
4. Tick the rows to add or overwrite; leave the rest alone.
5. **Apply**.

View or undo later in Qt via **Tools → Recent changes…** even if the
import ran in Classic Tk — one **Revert** rolls the whole import back.

## Reconciliation on refresh

When you re-import later:

- Your **Delete** flags, service-type overrides, and renames are kept
  when rows still match by frequency or **TGID**
- New RR rows are added; rows you deleted stay deleted

## Encrypted talkgroups

The BearTracker 885 cannot decode encrypted audio, so by default:

- New imports skip encrypted TGIDs
- Refreshes remove entries RR has since marked encrypted (same undo
  bundle as the import)
- Optional checkbox: **Include encrypted talkgroups (not recommended)**
  — remembered per system

## If something goes wrong

- **"Unusable page"** — use a category or trunked-system URL, not a site
  index ([Troubleshooting](Troubleshooting))
- Slow loads — enter RR credentials so the API is used
- Login errors — clear credentials in Settings and re-enter

## Internals

The whole import is one change-history event (not hundreds of row
edits), so one **Revert** undoes everything. Contributor detail:
[Architecture](Architecture).
