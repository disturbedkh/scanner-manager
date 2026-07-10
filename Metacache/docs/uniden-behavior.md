# Uniden desktop app behavior map

> Status: active plan — observed behavior only; no copied Uniden code.
> User-facing tool integration:
> [Uniden-Tools-Integration wiki](https://github.com/disturbedkh/scanner-manager/wiki/Uniden-Tools-Integration).

Filled incrementally from RE recon. Decompiled references live under
[`Metacache/Dev/RE/`](../Dev/RE/) — not repo-root `_re/`.

## Ground truth

Two apps ship in the Uniden ecosystem that touch the same RadioReference
data but target different scanner families:

| App | Scanner family | Exe (default) | Version observed |
| --- | --- | --- | --- |
| BT885 Update Manager | BearTracker 885 | `C:\Program Files (x86)\Uniden\BT885 Update Manager\UpdateManager.exe` | 0.0.0.5 |
| BCDx36HP Sentinel | BCD436HP / BCD536HP / SDS100 / SDS200 | `C:\Program Files (x86)\Uniden\BCDx36HP Sentinel\BCDx36HP_Sentinel.exe` | 3.1.0.1 |

## RE source locations

| Topic | Lab path |
| --- | --- |
| BT885 RE notes | [`../Dev/RE/docs/BT885.md`](../Dev/RE/docs/BT885.md) |
| SDS100 / Sentinel RE | [`../Dev/RE/docs/SDS100.md`](../Dev/RE/docs/SDS100.md) |
| Sentinel captures | [`../Dev/RE/docs/sentinel_capture.md`](../Dev/RE/docs/sentinel_capture.md) |
| Firmware / decompiles | [`../Dev/RE/firmware/decompiles/`](../Dev/RE/firmware/decompiles/) |
| Unpack helper | [`../../scripts/re_unpack.ps1`](../../scripts/re_unpack.ps1) |

*(SOAP proxy method names and shapes: TBD — document from decompiles under
`Metacache/Dev/RE/firmware/decompiles/` and cross-check against
[`rr-api-notes.md`](rr-api-notes.md).)*

## Launch / shutdown lifecycle

**TBD** — document after serial/SD capture sessions:

- Startup: connect to SD immediately vs. wait for user action?
- Shutdown: known-good card state vs. partial writes requiring flush?

## RadioReference calls observed

**TBD** — for each app, record WSDL method names, argument shapes, auth
header, and extra headers (user-agent, app key). Compare against the
public RR WSDL so clean-room `core/rr_api.py` can replicate behavior
without copying Uniden implementation.

## Local cache / data directories

Observed data locations:

- `%LOCALAPPDATA%\Uniden\...` — likely both tools
- `%APPDATA%\Uniden\...` — Favorites lists (Sentinel)
- Sentinel install dir: `ZipListUs.txt`, `ZipListCa.txt` (ZIP → state
  lookup, tab-delimited, `ZIP<tab>LAT<tab>LON<tab>ST`)

## Reconciliation heuristics

What does the Uniden app do when the card already has a modified HPD and
the user asks for a refresh?

**TBD** — key questions for decompiled flow:

- Diff by TGID, frequency, or row-ordinal?
- User-modified Alpha tags preserved, overwritten, or merged?
- User-added entries preserved when base entry is refreshed?
- How are RR-removed entries detected and dropped?

Our reconciler lives in `core/` (MetaStore + HPD apply paths); legacy Tk
still exposes `apply_customizations` in `legacy_tk/scanner_manager.py`.
Decompiled Sentinel/BT885 flows should confirm we are at least as
conservative as Uniden's own tool.

## Firmware / ancillary file layout on the card

Documented in RE lab (SDS100):

- `/HPDB/hpdb.cfg` — index file
- `/HPDB/s_*.hpd` — per-state HPDs
- `/firmware/*.dat` — ZipTable, CityTable, and related
- `/_UPDATER/*` — Uniden updater writes
- `BCDx36HP/favorites_lists/` — SDS Favorites List HPDs (see
  [`hpe-format.md`](hpe-format.md))

Ensure `core/sdcard` sync paths treat external updater touches as
expected deltas vs. unchanged data.

## Differences between BT885 and Sentinel

| Area | BT885 | Sentinel / SDS |
| --- | --- | --- |
| Scanner family | `.hpd` only | `.hpd` + Favorites Lists (`.hpe` / `f_*.hpd`) |
| Import UI | Thinner geography picker | Richer geography + Favorites editor |
| Firmware channel | BT885 update namespace | BCDx36HP / SDS namespace (see firmware FTP RE) |
| Our profile | `uniden_bt885` | `uniden_sds100` |

**TBD:** detailed flow diffs from paired capture sessions.

## Implementer checklist

- [ ] Fill SOAP method table from decompiles (no copied Uniden code).
- [ ] Document launch/shutdown card-touch behavior from capture.
- [ ] Record reconcile heuristics vs `core/` MetaStore apply paths.
- [ ] Keep BT885 vs Sentinel table current with profile flags.
- [ ] User-facing Uniden Tools steps stay on the wiki (link above).

## Related

| Doc | Purpose |
| --- | --- |
| [`rr-api-notes.md`](rr-api-notes.md) | Clean-room RR SOAP surface |
| [`hpe-format.md`](hpe-format.md) | Favorites / `.hpe` backlog |
| [`../Dev/RE/README.md`](../Dev/RE/README.md) | RE lab index + wiki mapping |
| [RE-Sentinel wiki](https://github.com/disturbedkh/scanner-manager/wiki/RE-Sentinel) | Public RE narrative |
