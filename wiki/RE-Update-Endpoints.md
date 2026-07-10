# RE: Uniden update endpoints

> Status: shipped (v0.11.x) — RE source for prod `firmware/ftp_client.py`.

> Where this fits: how Sentinel and the BT885 Update Manager fetch
> firmware / HPDB. Spoiler: **plain FTP**, not TWiki, not HTTP API.
> Start at [Reverse Engineering](Reverse-Engineering).

## What this answers

Where updates live, how version discovery works (directory listing +
filename parse), and how our shipped FTP client mirrors that without
shipping Sentinel.

## Known vs OPEN

| Topic | State | Notes |
|---|---|---|
| Sentinel FTP host + path + creds | DONE | From .NET string tables |
| BT885 Update Manager FTP | DONE | HPDB-only in practice |
| Filename → version algorithm | DONE | Implemented in `firmware/ftp_client.py` |
| Credential rotation handling | Soft OPEN | App falls back to manual import |
| Actual WRITE_10 during live update | OPEN | Capture still needed — [RE-Sentinel](RE-Sentinel) |

## Deep dive

Both Uniden desktop apps read updates from **plain FTP** with
credentials baked into the installers. No HTTP manifest, no signed
metadata, no JSON catalog. “What’s latest?” = `LIST`/`NLST` + parse
filenames.

### The two endpoints

| Surface | Server | Path | User | Pass |
|---|---|---|---|---|
| **Sentinel** (firmware + HPDB) | `ftp.homepatrol.com` | `/BCDx36HP/` | `homepatrolftp` | `green7Corn` |
| **BT885 Update Manager** (HPDB) | `ftp.uniden.com` | `/BT885/` | `BT885ftp2` | `89jZ53Ba` |

Plain FTP (no FTPS/SFTP), passive OK. BT885 user jailed to `/BT885/`.
Credentials extracted from publicly shipped installers (UTF-16LE
string tables after `ftp://`). TWiki at `info.uniden.com` is
human changelog / downgrade ZIPs only — apps do not scrape it.

Reproduction bytes and listings:
`Metacache/Dev/RE/docs/uniden_update_endpoints.md`.

### What’s on the Sentinel server (summary)

`ftp.homepatrol.com/BCDx36HP/` is a flat directory: weekly
`MasterHpdb_*.gz`, `<MODEL>_V*.bin` MAIN images, `<MODEL>-SUB_V*.firm`,
Sentinel `.app` markers + installer ZIPs, City/Zip tables, BC-WF1
firmware, `archive/`. Snapshot counts and per-model latest versions
(2026-05-03): lab inventory — don’t treat wiki as live catalog.

`.app` markers are 0–2 bytes; version is **in the filename**.

### What’s on the BT885 server

`ftp.uniden.com/BT885/`: HPDB + City/Zip tables only. **No firmware
blobs** observed. Watch for a future `BT885_V*.bin`.

### FTP commands used

`LIST` / `NLST`, `SIZE`, `MDTM`, `RETR`. Match with `ftplib`.

### Update-check algorithm (reconstructed)

1. List `/BCDx36HP/` (or `/BT885/`).
2. Latest HPDB = max date in `MasterHpdb_MM_DD_YYYY.gz` vs
   `hpdb.cfg` `DateModified`.
3. Latest MAIN/SUB = max version tuple in family glob vs
   `scanner.inf` / on-card filenames.
4. Sentinel self-update = max `BCDx36HP_Sentinel_V*.app` filename.

Prod path: [Firmware Updater](Firmware-Updater) +
`firmware/ftp_client.py` / `firmware/updater.py`. On-card apply
unchanged from [RE-Firmware](RE-Firmware).

### Etiquette

Cache listings (~1 h/session); don’t poll continuously. On credential
rotation, surface “server unavailable” and fall back to manual
import. Documenting observed interoperability RE — credentials are
trivially extractable from the public apps.

### Beyond the canonical paths

Accessible extras (`/Extreme/`, `/HomePatrol/…`) and ACL-blocked
`ftp.uniden.com` engineering dirs: see
`docs/uniden_firmware_inventory.md`. Highlights: BC-WF1 plaintext
Broadcom/STM32 bridge; HomePatrol-1 SREC with obfuscated app;
MAIN encryption continuous since 2014; no beta/plaintext SDS MAIN.

## Lab pointers

| Path | Role |
|---|---|
| `Metacache/Dev/RE/docs/uniden_update_endpoints.md` | **SSOT** extraction + FTP listings |
| `Metacache/Dev/RE/docs/uniden_firmware_inventory.md` | Wider topology, entropy, BC-WF1 |
| `firmware/ftp_client.py` | Production client |
| `firmware/updater.py` | SD apply pipeline |
| [RE-Firmware](RE-Firmware) / [RE-Sentinel](RE-Sentinel) / [RE-SD-Card](RE-SD-Card) | Apply path + USB vs network split |
