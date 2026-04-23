# Forum Announcement (copy-pasteable)

Copy this text into the RadioReference Forums / /r/scanners thread when
the alpha drops. Strip the frontmatter comments first; they're just a
heads-up to the editor.

---

**Scanner Manager v0.9.0-alpha.1 — Open Alpha for BearTracker 885 Users**

Hey folks,

I've been building an open-source desktop companion for the Uniden
BearTracker 885 and I'd love your help testing it. This is an alpha,
so please be a little gentle with your scanner's SD card — always make
a full backup before running it.

**What is it?**

Scanner Manager is a Windows (and from-source) desktop app that lets
you manage the BearTracker 885's SD card outside of Uniden's tools. It
reads and writes HPD files directly, keeps a full revertable change
log, and adds a few capabilities that have been on the community's
wishlist for a while:

- **ZIP/GPS simulation** — enter a ZIP or GPS fix and see exactly
  what your scanner will scan at that point, including statewide and
  national coverage overlays, with nearest-systems ranking.
- **Coverage tools** — heatmap + optional real-tile map showing
  overlapping coverage, plus a CSV export of the effective scan set
  for spreadsheet analysis.
- **RadioReference import** — paste any RR category or trunked-system
  URL. Works with the SOAP API if you have an RR subscription, or
  falls back to HTML scraping. Each import is a single revertable
  event in the change log, so rolling back is one click.
- **Workspaces (virtual SD cards)** — clone the card, keep editing
  while it's unplugged, reconcile both ways when it returns. Survives
  Uniden updater runs.
- **CityTable editing** — add custom locations and export a patched
  CityTable the scanner will load.
- **Uniden Tools integration** — detects installed Sentinel / BT885
  Update Manager and drives a full push → update → pull cycle. It
  does not redistribute Uniden's installers; it downloads them from
  Uniden's CDN with SHA-256 verification on first use.
- **Revertable change log** — every edit is logged and individually
  undo-able from the Changes dialog.

**How to get it**

- **Easiest:** grab `ScannerManager.exe` from the GitHub Releases page
  below. Windows SmartScreen will warn because it isn't code-signed;
  click "More info → Run anyway". You can verify the SHA-256 against
  the `.sha256` file attached to the release.
- **From source:** `pip install -e .` from the repo. Works on Linux/
  macOS too though the target scanner is BT885 specifically.

Download + source: https://github.com/disturbedkh/scanner-manager/releases
Wiki + docs:      https://github.com/disturbedkh/scanner-manager/wiki
Issues:           https://github.com/disturbedkh/scanner-manager/issues

**What I'd love from testers**

- Try the ZIP simulation with your local ZIP and tell me what it gets
  wrong relative to what your 885 actually scans.
- Try the RadioReference import on a trunked system or a conventional
  category. Does the service-type prefill make sense?
- Use the Uniden Tools panel to run a Sentinel/BT885 update cycle and
  verify your edits survive it.
- **Back up your SD card first.** Then please file any bug at the
  Issues link above with a crash log from
  `%LOCALAPPDATA%/scanner-manager/logs/` if there is one.

**What this is not**

- It is not affiliated with Uniden. I'm just a user with too much free
  time.
- It is not a firmware flasher. Uniden's updaters still do that.
- It is not code-signed yet. SmartScreen is normal. If that makes you
  nervous, install from source.

**Donate**

If this saves you hours of Sentinel wrangling and you feel like
buying me a coffee, there's a Donate button inside the app (Help →
Donate / Support...) with PayPal and crypto options. Totally optional,
and huge thanks to anyone who does.

Feedback, issues, and PRs all welcome. Happy scanning.
