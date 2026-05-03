# RE: Uniden update endpoints

> Where this fits: how Sentinel and the BT885 Update Manager actually
> check for updates and download new firmware / HPDB. Spoiler: it's
> plain anonymous-ish FTP, not the TWiki, not an HTTP API. For the
> consolidated narrative start at
> [Reverse Engineering](Reverse-Engineering).

## Headline

Both Uniden desktop apps - Sentinel (BCDx36HP family) and the BT885
Update Manager - read updates from **plain FTP** servers with
hardcoded credentials baked into the installers. There is no HTTP
manifest API, no signed metadata, no JSON catalog. The "what's the
latest version?" question is answered by listing a directory and
parsing filenames.

This means our app can replicate Sentinel's "Get Firmware Update" and
"Get HPDB Update" flows in pure Python with `ftplib`, with no scraping
and no Sentinel binary involved.

## The two endpoints

| Surface                           | Server                  | Path           | User              | Pass         |
| --------------------------------- | ----------------------- | -------------- | ----------------- | ------------ |
| **Sentinel** (firmware + HPDB)    | `ftp.homepatrol.com`    | `/BCDx36HP/`   | `homepatrolftp`   | `green7Corn` |
| **BT885 Update Manager** (HPDB only) | `ftp.uniden.com`     | `/BT885/`      | `BT885ftp2`       | `89jZ53Ba`   |

Plain FTP, no FTPS / SFTP. Passive mode supported. The BT885 user is
jailed to `/BT885/` (root listing only shows that one directory). Both
credentials were extracted from the publicly-shipped Sentinel and
BT885 Update Manager installers via static analysis of the .NET
binaries.

The TWiki at `info.uniden.com/twiki/...` is a **publication site** for
human-readable changelogs and downgrade ZIPs. Sentinel never reads the
TWiki. The desktop apps go straight to FTP.

## How we know

Static analysis: the .NET binaries store their FTP URL, username, and
password as plain UTF-16LE string-table entries. Hex-dumping the bytes
right after `ftp://` reveals four consecutive length-prefixed strings:

- the URL
- the username
- the password
- (Sentinel only) a TWiki info-link URL

See the lab notes in
`AI/Dev/RE/docs/uniden_update_endpoints.md` for the exact PowerShell
+ raw bytes used to extract them, and for the follow-up live FTP
listings we ran to confirm the layout.

## What's on the Sentinel server

`ftp.homepatrol.com/BCDx36HP/` is the **complete update infrastructure**
for the BCDx36HP family - one flat directory containing everything
Sentinel ever needs to fetch.

### Inventory (snapshot 2026-05-03)

| Filename pattern                              | Approx count | Purpose |
| --------------------------------------------- | -----------: | ------- |
| `MasterHpdb_<MM>_<DD>_<YYYY>.gz`              |          161 | Weekly HPDB snapshot (gzipped). New file every Sunday. |
| `<MODEL>_V<M>_<MM>_<PP>.bin`                  |         105+ | Main MCU firmware. ~2.16 MB each. |
| `<MODEL>-SUB_V<M>_<MM>_<PP>.firm`             |           26 | Sub MCU firmware. ~80-90 KB each. |
| `BCDx36HP_Sentinel_V<X>_<YY>_<ZZ>.app`        |            1 | "Currently shipping Sentinel" marker (0-2 byte file). Filename = current Sentinel version. |
| `BCDx36HP_Sentinel_Version_<X>_<YY>_<ZZ>.zip` |            1 | Current Sentinel installer ZIP. |
| `CityTable_V*.dat`, `ZipTable_V*.dat`         |            2 | City/ZIP lookup tables. Static since 2013. |
| `BC-WF1_V<X>_<XX>.bin`                        |            1 | BC-WF1 Wi-Fi adapter firmware. |
| `hpdb.hp1`                                    |            1 | Reference master HPDB blob (legacy seed). |
| `archive/`                                    |          dir | Older Sentinel installers and `.app` markers, used for downgrades. |

### Models present in the firmware listing

| Family                              | Versions seen   | Latest (2026-05-03) |
| ----------------------------------- | --------------: | ------------------- |
| BCD436HP                            |              27 | 1.28.24             |
| BCD536HP                            |              28 | 1.28.24             |
| SDS-100                             |              16 | **1.26.01**         |
| SDS200                              |              16 | **1.26.01**         |
| SDS150                              |               2 | 1.01.02             |
| SDS100E / SDS200E (EU variants)     |          7 / 8  | 1.23.15             |
| USDS100 (regional variant)          |               4 | 1.23.15             |
| UBCD3600XLT, UBCD436-PT, UBCD536-PT |        3-5 each | 1.28.24             |
| BCD996P2                            |               1 | 1.10.02 (dormant)   |

### `.app` marker files

`BCDx36HP_Sentinel_V3_01_01.app` is **2 bytes** (`\r\n`). Older ones
are 0 bytes. They exist solely so Sentinel can answer "what's the
current Sentinel?" by parsing the filename - the file content is
never read. Cheap, listable, no API needed.

## What's on the BT885 server

`ftp.uniden.com/BT885/` only carries HPDB-related files:

| Filename pattern                  | Approx count | Purpose |
| --------------------------------- | -----------: | ------- |
| `MasterHpdb_<MM>_<DD>_<YYYY>.gz`  |          158 | Weekly HPDB. ~5.5 MB compressed (smaller than the BCDx36HP variant). |
| `CityTable_V1_00_00.dat`          |            1 | Same city table. |
| `ZipTable_V1_00_00.dat`           |            1 | Same ZIP table. |

**No firmware files are present.** The BT885 has not received a
firmware update Uniden distributes via this FTP path. The Update
Manager's firmware-update UI exists but in practice ships only HPDB.
We watch this directory in case Uniden ever publishes a `BT885_V*.bin`,
at which point our BT885 backend can pick it up using the same
algorithm as the Sentinel one.

## FTP commands the apps actually use

| Command  | Purpose |
| -------- | ------- |
| `LIST`   | Long-format listing (Sentinel default). |
| `NLST`   | Bare filename list (BT885 default - cheaper to parse). |
| `SIZE`   | File size for progress-bar denominators. |
| `MDTM`   | Last-modified timestamp - "is this newer than what we have?" |
| `RETR`   | Download. |

That's the entire surface. We can match it with `ftplib.FTP.nlst()`,
`.size()`, `.sendcmd("MDTM ...")`, and `.retrbinary()`.

## Update-check algorithm (reconstructed)

```text
def check_for_updates(scanner_family):
    listing = ftp.nlst("/BCDx36HP/")

    # 1. HPDB latest
    hpdb = max(parse_date(f) for f in listing
               if f.startswith("MasterHpdb_") and f.endswith(".gz"))
    if hpdb > installed_hpdb_date:
        offer_hpdb_update(hpdb)

    # 2. Main firmware latest (per scanner family glob, e.g. "SDS-100_V*.bin")
    main = max(parse_version(f) for f in listing
               if matches(scanner_family.main_glob, f))
    if main > installed_main_version:
        offer_main_firmware_update(main)

    # 3. Sub firmware latest (e.g. "SDS-100-SUB_V*.firm")
    # ... same shape

    # 4. Sentinel self-update
    sentinel_app = max(parse_version(f) for f in listing
                       if f.startswith("BCDx36HP_Sentinel_V")
                       and f.endswith(".app"))
    if sentinel_app > my_sentinel_version:
        offer_sentinel_self_update(sentinel_app)
```

Version parsing: `<MODEL>_V<MAJOR>_<MINOR>_<PATCH>.bin` → tuple,
lex-compare. HPDB version: `MM_DD_YYYY` → date, date-compare.

## What this gives our app

Direct integration. We do not need to:

- Ship the Sentinel binary
- Wrap or automate Sentinel via UI scripting
- Scrape the TWiki HTML
- Maintain a hand-curated firmware manifest with hardcoded URLs

Instead, the firmware updater (see `AI/Dev/FIRMWARE_UPDATER.md`)
discovers what's available by listing the FTP directory at runtime,
parses filenames, downloads via plain `RETR`, verifies file size and
SHA-256, and copies onto the SD card. The on-card flow (Uniden's
"copy file then reboot" mechanism) is unchanged from
[RE-Firmware](RE-Firmware).

It also gives us **HPDB sync** as a free side-effect - the same FTP
client lists HPDB blobs, picks the latest, downloads, and writes to
`BCDx36HP/HPDB/` on the card.

## Etiquette and risk

- Cache the listing for ~1 hour per session; don't poll continuously.
- If Uniden rotates credentials our app surfaces a "Uniden update
  server unavailable" message and falls back to manual import + the
  cached-from-Sentinel path documented in FIRMWARE_UPDATER.md.
- We never modify firmware blobs, never bypass version-compatibility
  checks, never publish credentials extracted from third-party
  binaries elsewhere. This page documents what we observed in the
  course of legitimate interoperability RE; the credentials are
  trivially extractable by anyone who installs the publicly-shipped
  apps.

## Beyond the canonical surface: hidden directories and goodies

The published Sentinel + BT885 paths only scratch the top of the
servers we have access to. Cross-referencing both servers turns up
a handful of additional directories of varying usefulness:

| Server | Path | Status | Notes |
| --- | --- | --- | --- |
| `ftp.homepatrol.com` | `/Extreme/` | accessible | HomePatrol-1 firmware (`.scn`), HomePatrol-1 HPDB (~10 MB), one stray `UBCD436-PT_V1_06_02C.bin` |
| `ftp.homepatrol.com` | `/HomePatrol/Test/` | accessible | Four very old (2010-2011) MasterHpdb blobs |
| `ftp.homepatrol.com` | `/HomePatrol/Updater/` | accessible | HomePatrol-1 firmware + 2011 weekly HPDBs |
| `ftp.uniden.com` | `/internal/`, `/uaceng/`, `/ujeng/`, `/updates/` | **list-but-no-enter** (550) | engineering staging dirs; ACL-blocked |

A separate "RE goodies hunt" pass (`AI/Dev/RE/docs/uniden_firmware_inventory.md`)
went deeper on what's downloadable. Highlights:

- **BC-WF1 Wi-Fi adapter firmware is fully plaintext** (entropy 3.54)
  and is a **Broadcom BCM43362 + STM32 USB bridge running NetX +
  WiCED**. It enumerates as USB CDC ACM to the scanner, so the
  WiFi-streaming protocol is potentially capturable with the same
  tooling we use for serial mode.
- **HomePatrol-1 firmware uses Motorola SREC transport** (`.scn`)
  with a clear Cortex-M memory map (low-flash code + `0x20700000`
  RAM init), but the application content is itself wrapped in a
  Uniden-specific obfuscation - even the 2010-era firmware is not
  trivially plaintext.
- **BCDx36HP MAIN encryption has been bulletproof since 2014** - we
  verified across 12 years of releases, 4 model lines, and govt /
  regional variants. No exploitable plaintext segment, no header
  signature, no bootloader gap. Static RE of MAIN remains
  infeasible.
- **No beta firmware, no plaintext SDS100-compatible variant**
  exists in any directory we can read.

Full methodology + entropy tables + BC-WF1 string mining live in
`AI/Dev/RE/docs/uniden_firmware_inventory.md`.

## Cross-references

- [RE-Firmware](RE-Firmware) - on-card update mechanism (file drop +
  scanner self-deletes after flash).
- [RE-Sentinel](RE-Sentinel) - what Sentinel does over USB
  (mass-storage file ops only); the update **check** is network-side,
  which this page covers.
- [RE-SD-Card](RE-SD-Card) - target SD-card layout.
- [Reverse Engineering](Reverse-Engineering) - high-level overview.
- Lab notebook: `AI/Dev/RE/docs/uniden_update_endpoints.md` with the
  raw bytes, hex dumps, and reproduction steps.
- Goodies hunt: `AI/Dev/RE/docs/uniden_firmware_inventory.md` covers
  the wider FTP topology, encryption analysis across the family, and
  the BC-WF1 RE win.
