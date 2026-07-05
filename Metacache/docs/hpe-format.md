# Sentinel `.hpe` Favorites-List format notes

> Status: active plan — SDS100 profile shipped; `.hpe` reader/writer and
> Favorites List editor UI still backlog.
> User context:
> [Channel-List-Management wiki](https://github.com/disturbedkh/scanner-manager/wiki/Channel-List-Management).

## Scope (v0.11.x)

| Scanner | `.hpd` | `.hpe` / Favorites Lists | Profile |
| --- | --- | --- | --- |
| BearTracker 885 | Yes | No (N/A) | `uniden_bt885` — `supports_favorites_lists: false` |
| SDS100 / SDS200 | Yes | Yes (on-card + Sentinel) | `uniden_sds100` — `supports_favorites_lists: true` |

The SDS100 profile (`scanner_profiles/sds100.py`) models Favorites Lists
as per-list HPDs under `BCDx36HP/favorites_lists/f_*.hpd` with manifest
metadata. We do **not** yet parse or write standalone `.hpe` blobs or ship
a Favorites List editor UI — see [`../Dev/WORKSTREAMS.md`](../Dev/WORKSTREAMS.md).

## What we know today

- `.hpe` = Sentinel's serialized Favorites List container. BCDx36HP / SDS
  scanners can boot these directly (distinct from per-state `.hpd` files).
- File is consumed by Sentinel's WinForms UI; likely one of:
  1. XML (Sentinel's older save formats were XML),
  2. .NET `BinaryFormatter` graph (possible but unlikely for a config file),
  3. A purpose-built binary with a short fixed header + TLV body.
- Co-exists with `.hpd`: a state HPD can be loaded, then a Favorites List
  layered on top to pick systems / talkgroups to scan.

## What we need to learn

1. Header bytes + magic — confirm text vs. binary.
2. Block/record layout — one record per system? per TGID? per site?
3. Mandatory vs. optional fields.
4. How Sentinel cross-references `.hpe` entries to RadioReference IDs
   (SID/AID/CTID) for round-trip.
5. On-card `.hpe` layout vs.
   `%LOCALAPPDATA%\Uniden\BCDx36HP_Sentinel\`.

## RE references

| Resource | Path |
| --- | --- |
| SDS100 on-card layout | [`../Dev/RE/docs/SDS100.md`](../Dev/RE/docs/SDS100.md) |
| Sentinel behavior map | [`uniden-behavior.md`](uniden-behavior.md) |
| Sentinel RE wiki | [RE-Sentinel](https://github.com/disturbedkh/scanner-manager/wiki/RE-Sentinel) |

When `.hpe` support lands, this doc becomes the specification for an
`hpe.py` module (analogous to `core/hpd.py`).

## Implementation checklist (future)

- [ ] Capture sample `.hpe` files from card + `%LOCALAPPDATA%`.
- [ ] Document magic, endianness, record boundaries.
- [ ] Map records → internal Favorites List model used by SDS profile.
- [ ] Round-trip test against Sentinel-written files.
- [ ] Qt Favorites List editor (wiki UX narrative when shipped).
