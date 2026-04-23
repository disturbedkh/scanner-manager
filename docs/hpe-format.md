# Sentinel `.hpe` Favorites-List Format Notes

> Working doc. Sentinel (BCDx36HP / SDS) uses `.hpe` Favorites List files
> in addition to `.hpd` per-state database files. BT885 only uses `.hpd`,
> so everything below is **deferred work** — see Phase 5 in the Uniden
> integration plan.

## What we know today

- `.hpe` = Sentinel's serialized Favorites List. The BCDx36HP / SDS
  scanners boot these directly (they aren't the same thing as a `.hpd`).
- File is consumed by Sentinel's WinForms UI; likely one of:
  1. XML (Sentinel's older save formats were XML),
  2. .NET `BinaryFormatter` graph (possible but unlikely for a config
     file),
  3. A purpose-built binary with a short fixed header + TLV body.
- Co-exists with `.hpd`: you can have a state HPD loaded and then layer
  a Favorites List on top to pick just the systems you want scanned.

## What we need to learn (post Phase 2 recon)

1. Header bytes + magic — confirm whether the file is text or binary.
2. Block/record layout — one record per system? per TGID? per site?
3. Which fields are mandatory vs. optional.
4. How Sentinel cross-references `.hpe` entries back to the canonical
   RadioReference IDs (SID/AID/CTID) so we can round-trip them.
5. What the `.hpe` file looks like on the card itself vs. inside
   `%LOCALAPPDATA%\Uniden\BCDx36HP_Sentinel\`.

## Scope note

We deliberately don't support `.hpe` today because:

- Our current user target is the BearTracker 885 (no `.hpe` support).
- `.hpe` is a Sentinel-only container; until we own a BCDx36HP / SDS we
  can't end-to-end validate any reader / writer we build.

When that changes, this doc becomes the specification for an `hpe.py`
module analogous to the existing HPD parser.
