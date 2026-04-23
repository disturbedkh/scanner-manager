# Glossary

Scanner hobby acronyms relevant to working with Scanner Manager.

## Scanner hardware / firmware

- **BearTracker 885 (BT885)** - Uniden's all-in-one base + mobile
  scanner with DOT / EMS / Fire / Police preset buttons. The primary
  target of this project.
- **BCDx36HP** - Uniden's BCD436HP / BCD536HP hand-held / base family.
  Shares the Sentinel software and the HPD format with the BT885.
- **Firmware tables** - `ZipTable*.dat` and `CityTable*.dat` on the
  SD card. Used by the scanner to decide what to scan at a given
  location.

## File formats

- **HPD** - Uniden's configuration file format; the name derives from
  the `.hpd` file extension on the state-split files. Binary.
  Contains systems, groups, entries, and metadata.
- **`hpdb.cfg`** - master HPD file written to the card root.
  References the per-state `s_*.hpd` files.
- **`s_*.hpd`** - per-state HPD files; loaded on demand depending on
  the selected state.
- **`.meta.json`** - MetaStore sidecar. Never hand-edit.
- **`.session.bak`** - per-session HPD safety snapshot.

## RadioReference

- **RR** - [RadioReference.com](https://www.radioreference.com/).
- **SID** (or System ID) - RR's identifier for a trunked system.
- **TGID** - Trunked talkgroup ID.
- **Category** - An RR grouping of related frequencies.

## This app

- **MetaStore** - the event-sourced change log. See
  [Architecture](Architecture).
- **Workspace** (a.k.a. **Virtual SD card**) - local folder that
  mirrors the card for offline editing. See
  [Workspaces & Sync](Workspaces-and-Sync).
- **Pipeline / push-update-pull** - Uniden tool orchestration flow
  that snapshots, runs the Uniden tool, and replays user events on
  top. See [Uniden Tools](Uniden-Tools-Integration).

## Coverage tags

- `COVERAGE` - center point is inside the system's coverage circle.
- `NEARBY` - edge of coverage is within the nearby threshold.
- `LOCAL` - system is pinned to the active ZIP's primary county.
- `STATEWIDE` - state-level system, relevant anywhere in-state.
- `WIDE` - national / multi-state.

See [ZIP & GPS Simulation](ZIP-and-GPS-Simulation) for full details.
