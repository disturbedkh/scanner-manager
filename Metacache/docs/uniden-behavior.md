# Uniden Desktop App Behavior Map

> Working document. Filled in from the Phase 2 recon pass (see
> [`scripts/re_unpack.ps1`](../scripts/re_unpack.ps1)). Contains observed
> behavior only — no copied code.

## Ground truth

Two apps ship in the Uniden ecosystem that touch the same
RadioReference data but target different scanner families:

| App | Scanner Family | Exe (default) | Version observed |
| --- | --- | --- | --- |
| BT885 Update Manager | BearTracker 885 | `C:\Program Files (x86)\Uniden\BT885 Update Manager\UpdateManager.exe` | 0.0.0.5 |
| BCDx36HP Sentinel | BCD436HP / BCD536HP / SDS100 / SDS200 | `C:\Program Files (x86)\Uniden\BCDx36HP Sentinel\BCDx36HP_Sentinel.exe` | 3.1.0.1 |

## Launch / shutdown lifecycle

*(to be filled in after recon)*

- Startup: does the tool connect to the SD card immediately, or does it
  wait for a user action?
- Shutdown: does it leave the card in a known-good state, or does it
  write partial data that must be flushed?

## RadioReference calls observed

*(fill in from decompiled SOAP proxies under
`_re/{bt885,sentinel}/decompiled/`)*

Document the WSDL method names, argument shapes, the auth header they
send, and any extra headers (user-agent, app key, etc.). We will
compare these against the public RR WSDL so our clean-room
`rr_api.py` in Phase 3 can replicate the same behavior without
copying their implementation.

## Local cache / data directories

Observed data locations:

- `%LOCALAPPDATA%\Uniden\...` — likely both tools
- `%APPDATA%\Uniden\...` — Favorites lists (Sentinel)
- Sentinel install dir: `ZipListUs.txt`, `ZipListCa.txt` (ZIP → state
  lookup, tab-delimited, `ZIP<tab>LAT<tab>LON<tab>ST`)

## Reconciliation heuristics

What does the Uniden app do when the card already has a modified HPD
and the user asks for a refresh? Key questions the decompiled flow
should answer:

- Does it diff by TGID, by frequency, or by row-ordinal?
- Are user-modified Alpha tags preserved, overwritten, or merged?
- Are user-added entries preserved when the base entry is refreshed?
- How does it detect and drop entries that RR has removed?

Our Reconciler in `scanner_manager.py` (see `apply_customizations`)
already has an opinion here; the decompiled source should confirm we
are at least as conservative as Uniden's own tool.

## Firmware / ancillary file layout on the card

- `/HPDB/hpdb.cfg` — index file
- `/HPDB/s_*.hpd` — per-state HPDs
- `/firmware/*.dat` — ZipTable, CityTable, and related
- `/_UPDATER/*` — what the Uniden tools write when they do an update run

Document exactly which files get touched during an update so
`sdcard.sync_pull` knows what to expect as "external changes" vs. truly
unchanged data.

## Differences between BT885 and Sentinel

*(to be filled in)*

Expected divergence:

- **Scanner family**: BT885 uses `.hpd` files exclusively; Sentinel
  uses `.hpe` Favorites Lists in addition to `.hpd`.
- **Import flow**: Sentinel has a richer UI for picking by geography;
  BT885 is thinner.
- **Firmware channel**: BT885 and the BCDx36HP family ship different
  firmware under the same Uniden update server namespace.
