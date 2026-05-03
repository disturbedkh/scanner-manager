# Uniden update endpoints (reverse-engineered) - 2026-05-03

> **Canonical narrative is in the wiki**:
> [`wiki/RE-Update-Endpoints.md`](../../../wiki/RE-Update-Endpoints.md). This
> file is the lab notebook for ongoing endpoint work.

> Goal: implement firmware + HPDB update flows in our app **without**
> shipping or depending on Sentinel / BT885 Update Manager. This
> document captures Uniden's actual update infrastructure, derived
> from static analysis of the official desktop apps and live FTP
> reconnaissance.

## TL;DR for app developers

Uniden's "update check" is **not an HTTP API and not the TWiki**. Both
Sentinel (BCDx36HP family) and BT885 Update Manager talk to plain
**anonymous-ish FTP servers** with hardcoded credentials baked into the
desktop apps. The "what is the latest version?" question is answered
by listing the FTP directory and parsing filenames - no manifest API,
no version JSON, no signed metadata.

Implications:

- We can replicate Sentinel's "Get Firmware Update" / "Get HPDB Update"
  flow in pure Python with `ftplib`. No reverse-engineered protocol,
  no scraping HTML.
- The TWiki (`info.uniden.com/twiki/...`) is a **publication site**,
  not the authoritative source. Sentinel never reads it. The TWiki is
  for humans ("read the changelog, download the ZIP manually if you
  want"), and is also the official downgrade archive.
- We do **not** need to ship or wrap the Sentinel binary. The FTP
  surface is everything our updater needs.

## The two endpoints

| What                                | Server                  | Path           | User             | Pass        |
| ----------------------------------- | ----------------------- | -------------- | ---------------- | ----------- |
| **Sentinel** (firmware + HPDB)      | `ftp.homepatrol.com`    | `/BCDx36HP/`   | `homepatrolftp`  | `green7Corn` |
| **BT885 Update Manager** (HPDB only) | `ftp.uniden.com`        | `/BT885/`      | `BT885ftp2`      | `89jZ53Ba`  |

Notes:

- Plain FTP, **no FTPS / no SFTP**. Passive mode works.
- The BT885 user is jailed to `/BT885/`; root listing only shows that
  one directory.
- Sentinel uses anonymous-ish creds + a public archive directory. BT885
  uses a slightly more credential-shaped string but it's still in the
  installer plaintext.
- Both creds are extracted from publicly-distributed installers (no
  binary patching, no MITM) - this is straight reverse engineering for
  interoperability.

## How we know

### Static extraction from the .NET binaries

```powershell
# Sentinel
$bytes = [System.IO.File]::ReadAllBytes("C:\Program Files (x86)\Uniden\BCDx36HP Sentinel\BCDx36HP_Sentinel.exe")
$utf16 = [System.Text.Encoding]::Unicode.GetString($bytes)
$idx   = $utf16.IndexOf('ftp://ftp.homepatrol.com')
# Hex-dump 400 bytes after $idx*2 -> reveals four length-prefixed strings:
#   ftp://ftp.homepatrol.com/BCDx36HP/   (URL)
#   homepatrolftp                        (user)
#   green7Corn                           (pass)
#   http://info.uniden.com/twiki/...     (TWiki info link, UI-only)
```

The bytes form .NET `#US` heap entries - each is `<varint length>
<UTF-16 string> <flag>`. We confirmed the layout for both binaries.
See [`AI/Dev/RE/sentinel_decompile/strings/`](../sentinel_decompile/strings/)
for the raw UTF-8 + UTF-16 string dumps used for the search.

### Live FTP reconnaissance

```powershell
$cred = New-Object System.Net.NetworkCredential("homepatrolftp","green7Corn")
$ftp  = [System.Net.FtpWebRequest]::Create("ftp://ftp.homepatrol.com/BCDx36HP/")
$ftp.Method      = [System.Net.WebRequestMethods+Ftp]::ListDirectoryDetails
$ftp.Credentials = $cred
$ftp.UsePassive  = $true
($ftp.GetResponse().GetResponseStream() | %{ (New-Object IO.StreamReader $_).ReadToEnd() })
```

Both endpoints listed cleanly. Inventories captured 2026-05-03; see
inventories below.

## Sentinel server inventory (`ftp.homepatrol.com/BCDx36HP/`)

### Top-level (single flat directory)

This is the **complete update infrastructure** for the BCDx36HP family.
Everything Sentinel needs is in one listable directory:

| Filename pattern                          | Count | Purpose |
| ----------------------------------------- | ----- | ------- |
| `MasterHpdb_<MM>_<DD>_<YYYY>.gz`          | 161   | Weekly HPDB snapshot, gzipped. New one published every Sunday. |
| `<MODEL>_V<M>_<MM>_<PP>.bin`              | 105+  | Main MCU firmware. One per model per release. ~2.16 MB each. |
| `<MODEL>-SUB_V<M>_<MM>_<PP>.firm`         | 26    | Sub MCU firmware. ~80-90 KB each. |
| `BCDx36HP_Sentinel_V<X>_<YY>_<ZZ>.app`    | 1     | "Currently shipping" Sentinel marker (0-2 byte file). Filename = current Sentinel version. |
| `BCDx36HP_Sentinel_Version_<X>_<YY>_<ZZ>.zip` | 1 | Current Sentinel installer ZIP. |
| `CityTable_V<x>_<yy>_<zz>.dat`            | 1     | City lookup table. Static since 2013. |
| `ZipTable_V<x>_<yy>_<zz>.dat`             | 1     | ZIP-code lookup table. Static since 2013. |
| `BC-WF1_V<X>_<XX>.bin`                    | 1     | BC-WF1 Wi-Fi adapter firmware. ~990 KB. |
| `hpdb.hp1`                                | 1     | Reference master HPDB blob (legacy / original seed). |
| `archive/`                                | dir   | Older Sentinel installers + their `.app` markers, for downgrades. |

### Models present (Main `.bin` files seen in listing)

| Family   | Versions seen | Latest (2026-05-03) | Releases since 2018 |
| -------- | ------------- | ------------------- | ------------------- |
| BCD436HP | 27 versions, 2014 to present | `1.28.24` | active |
| BCD536HP | 28 versions, 2014 to present | `1.28.24` | active |
| BCD996P2 | 1 version (`1.10.02`) | dormant | dormant |
| SDS-100  | 16 versions | **`1.26.01`** | active |
| SDS200   | 16 versions | **`1.26.01`** | active |
| SDS150   | 2 versions  | `1.01.02`     | new (2025+) |
| SDS100E / SDS200E | 7-8 versions each | `1.23.15` | EU variant, active |
| USDS100  | 4 versions | `1.23.15` | regional variant |
| UBCD3600XLT, UBCD436-PT, UBCD536-PT | 3-5 each | `1.28.24` | gov / fleet variants |

### Sub firmware

Same naming, `.firm` extension. The Sub is shared across models that
share the same Sub MCU - SDS-100 and SDS200 share the same `SDS-100-SUB`
firmware files, for example. Latest as of capture: `1.03.15`
(2025-10-17).

### HPDB snapshots

`MasterHpdb_MM_DD_YYYY.gz` published every Sunday. Inventory has every
weekly snapshot back to 2023-04-02. Sizes: ~12 MB compressed (Sentinel
flow), ~5.5 MB compressed (BT885 flow).

### `.app` marker files

`BCDx36HP_Sentinel_V3_01_01.app` is **2 bytes** (`\r\n`). Older ones
(`SDS_Sentinel_V2_01_03.app`, `USDS_Sentinel_V2_05_03.app`) are 0
bytes. They exist solely so Sentinel can pick the latest available
Sentinel by listing the directory and parsing filenames - the file
content is never read. This is a beautifully cheap "what's the latest
version?" mechanism: `LIST` + filename parse, no manifest API needed.

## BT885 server inventory (`ftp.uniden.com/BT885/`)

| Filename pattern                | Count | Purpose |
| ------------------------------- | ----- | ------- |
| `MasterHpdb_<MM>_<DD>_<YYYY>.gz` | 158   | Weekly HPDB. Smaller (~5.5 MB) than the BCDx36HP variant - presumably a BT885-tailored subset. |
| `CityTable_V1_00_00.dat`        | 1     | Same city table. |
| `ZipTable_V1_00_00.dat`         | 1     | Same ZIP table. |

**No firmware files present.** The BT885 has not received any firmware
updates that Uniden distributes via this FTP path. The Update Manager's
firmware-update UI exists, but in practice only HPDB ever ships through
it. (We monitor for new files; if Uniden ever drops a `BT885_V*.bin`
here, our app's BT885 backend can pick it up automatically using the
same algorithm as Sentinel.)

## FTP commands the desktop apps actually use

Confirmed via string-table extraction (BT885 binary contains literal
command tokens, Sentinel binary uses .NET `FtpWebRequest` whose verbs
match):

| Command  | Purpose |
| -------- | ------- |
| `LIST`   | Get long-format directory listing (Sentinel default). |
| `NLST`   | Get bare filename list (BT885's path - cheaper to parse). |
| `SIZE`   | Get file size in bytes (used for progress-bar denominator). |
| `MDTM`   | Get last-modified timestamp (used to compare "newer than what we have"). |
| `RETR`   | Download a file (implicit). |

That's the entire surface. Both apps are thin clients of plain FTP
verbs. We can match them with `ftplib.FTP.nlst()`, `.size()`,
`.sendcmd("MDTM ...")`, `.retrbinary()` directly.

## Update-check algorithm (reconstructed)

Sentinel's "Check for updates" flow, distilled from the strings + the
file inventory + the Phase 0c USB capture (which showed nothing went
out over USB - update checks are pure host-side network):

```text
on_check_for_updates():
    listing = FTP.nlst("/BCDx36HP/")

    # 1. HPDB latest
    hpdb_files = [f for f in listing if f.startswith("MasterHpdb_") and f.endswith(".gz")]
    latest_hpdb_date = max(parse_date(f) for f in hpdb_files)
    if latest_hpdb_date > installed_hpdb_date:
        offer_hpdb_update(latest_hpdb_date)

    # 2. Main firmware latest (per scanner family)
    main_glob   = scanner_family.main_filename_glob   # e.g. "SDS-100_V*.bin"
    main_files  = [f for f in listing if matches(main_glob, f)]
    latest_main = max(parse_version(f) for f in main_files)
    if latest_main > installed_main_version:
        offer_main_firmware_update(latest_main)

    # 3. Sub firmware latest (per scanner family)
    sub_glob   = scanner_family.sub_filename_glob     # e.g. "SDS-100-SUB_V*.firm"
    # ... same shape

    # 4. Sentinel self-update
    app_files = [f for f in listing if f.startswith("BCDx36HP_Sentinel_V") and f.endswith(".app")]
    latest_sentinel_version = max(parse_version(f) for f in app_files)
    if latest_sentinel_version > my_version:
        offer_sentinel_self_update(latest_sentinel_version)
```

Version parsing: `<MODEL>_V<MAJOR>_<MINOR>_<PATCH>.bin` -> `(MAJOR,
MINOR, PATCH)` tuple, lex-compare. HPDB version: `MM_DD_YYYY` -> date,
date-compare. That's it.

## What lives on the SD card vs. what lives at FTP

The FTP server is a **library of named blobs**. The SD card and the
local app side are responsible for "currently installed" tracking:

| State on FTP | State on SD card | State in Sentinel local data |
| ------------ | ---------------- | ---------------------------- |
| `MasterHpdb_<date>.gz` | `\BCDx36HP\HPDB\hpdb.cfg` `DateModified` field | `%PROGRAMDATA%\Uniden\BCDx36HP_Sentinel\Database\` cached blob |
| `<MODEL>_V*.bin` | written into `\BCDx36HP\firmware\` then auto-deleted by scanner | `%PROGRAMDATA%\Uniden\BCDx36HP_Sentinel\Updater\` cached |
| `<MODEL>-SUB_V*.firm` | same | same |
| `BCDx36HP_Sentinel_V*.app` | n/a | Sentinel binary version itself (registry / EXE attrs) |

This means our firmware updater can also **import from the local
Sentinel cache** (a user who already ran a Sentinel update has the
firmware blob on disk), and we can fall back to FTP when the cache is
empty. See `Phase 1` of [FIRMWARE_UPDATER.md](../../FIRMWARE_UPDATER.md).

## Other goodies harvested from the binaries

### Sentinel local-app folder layout

From the strings dump, Sentinel's local data lives at (typically)
`%PROGRAMDATA%\Uniden\BCDx36HP_Sentinel\` with this structure:

```
Uniden\BCDx36HP_Sentinel\
    Database\           # cached HPDB blobs (MasterHpdb*.hp1, MasterHpdb_*.gz)
    Updater\            # cached firmware blobs (*.bin, *.firm)
    BuiltIn\            # built-in defaults bundled with installer
    Profile\
        profile.cfg
    Discovery\
    activity_log\
    app_data.cfg        # session/preference state
```

### Common SD-card paths (BCDx36HP family)

(Both Sentinel and BT885 Update Manager target this same layout - BT885
units share the BCDx36HP folder name.)

```
\BCDx36HP\
    \HPDB\
        hpdb.cfg
        MasterHpdb.hp1
        MasterHpdb.tmp
    \firmware\
        CityTable_V*.dat
        ZipTable_V*.dat
        <MODEL>_V*.bin              # transient: drop, scanner self-deletes
        <MODEL>-SUB_V*.firm         # transient: drop, scanner self-deletes
    \favorites_lists\
        f_list.cfg
    \Profile\
    \activity_log\
    \alert\
    \audio\
        \inner_rec\
        \user_rec\
    \discovery\
    scanner.inf
```

### "Mismatch" guards

Strings include `"Mismatch Model name."` and `"Mismatch File format
version."` - Sentinel's own pre-flight when reading existing card
state, presumably triggered by `TargetModel` and `FormatVersion`
fields in CFG files. Worth replicating the same guards in our updater
(don't write a profile to a card that belongs to a different model).

### UI strings worth borrowing

- `"After you disconnect the USB cable, the firmware update will begin."`
- `"Checking Uniden Server"`
- `"Downloading Update from Uniden Server"`
- `"Reconstructing Full Database"`
- `"Erasing scanner"` / `"Writing to scanner"` / `"Complete"`
- `"A new version of firmware is available. Do you want to update?"`
  (BT885 only)

We don't need to ship those exact strings, but matching the user's
mental model from Sentinel reduces support-question drift.

## Implementation outline for our app

### `scanner_manager/uniden_ftp.py` (new)

```python
"""Minimal client for Uniden's two update FTP servers.

These credentials come from the publicly-distributed Sentinel and BT885
Update Manager installers. We only LIST + RETR; never write back.
"""

from dataclasses import dataclass
import ftplib

@dataclass(frozen=True)
class FtpEndpoint:
    host: str
    path: str
    user: str
    password: str

SENTINEL_FTP = FtpEndpoint(
    host="ftp.homepatrol.com",
    path="/BCDx36HP/",
    user="homepatrolftp",
    password="green7Corn",
)
BT885_FTP = FtpEndpoint(
    host="ftp.uniden.com",
    path="/BT885/",
    user="BT885ftp2",
    password="89jZ53Ba",
)

class UnidenFtpClient:
    def __init__(self, ep: FtpEndpoint):
        self.ep = ep

    def listing(self) -> list[tuple[str, int, str]]:
        """Returns [(filename, size_bytes, modified_iso)] for ep.path."""
        with ftplib.FTP(self.ep.host, timeout=30) as ftp:
            ftp.login(self.ep.user, self.ep.password)
            ftp.cwd(self.ep.path)
            names = ftp.nlst()
            out = []
            for n in names:
                try:
                    size = ftp.size(n)
                    mdtm = ftp.sendcmd(f"MDTM {n}").split()[-1]  # "20260419..."
                except ftplib.error_perm:
                    continue
                out.append((n, size or 0, mdtm))
            return out

    def download(self, filename: str, dst_path: str) -> None:
        with ftplib.FTP(self.ep.host, timeout=120) as ftp:
            ftp.login(self.ep.user, self.ep.password)
            ftp.cwd(self.ep.path)
            with open(dst_path, "wb") as f:
                ftp.retrbinary(f"RETR {filename}", f.write)
```

### `scanner_manager/firmware_updater.py` augmentation

Replace the manifest's hard-coded TWiki URLs with on-demand FTP
discovery:

```python
class FirmwareLibrary:
    def discover(self, family: str, kind: str) -> list[FirmwareVersion]:
        """List available firmware blobs at the FTP server, parse versions."""
        listing = self._ftp_for(family).listing()
        return [parse_version_from_filename(f) for f, _, _ in listing
                if matches_glob(family.glob(kind), f)]

    def latest(self, family: str, kind: str) -> FirmwareVersion:
        return max(self.discover(family, kind), key=lambda v: v.tuple)
```

### Where this slots into the Sentinel-vs-our-app comparison

| Capability              | Sentinel | BT885 UM | Our app (planned) |
| ----------------------- | -------- | -------- | ----------------- |
| HPDB sync via FTP       | yes      | yes      | yes (Phase 1)     |
| Firmware list via FTP   | yes      | UI only  | yes (Phase 1)     |
| Firmware download       | yes      | UI only  | yes (Phase 2)     |
| Self-update             | yes      | no       | yes (via GitHub Releases - existing code) |
| Backup before flash     | partial  | partial  | **yes (full)**, multi-version aware |
| Pre-flight model check  | yes      | yes      | yes |
| Multi-card profiles     | no       | no       | **yes**, already shipping |
| Differential update log | no       | no       | **yes** |

## Risks / etiquette

- **Rate limiting**: FTP is cheap but listing 161+ files is not free
  for Uniden. Cache the `LIST` response with a TTL of ~1 hour in our
  app, the way Sentinel itself does (it polls on user click, not
  continuously).
- **Anonymous access etiquette**: don't hammer; one listing per user
  per session is plenty. Set a polite User-Agent equivalent (FTP
  doesn't have one, but use a non-default username if Uniden ever
  rotates).
- **Credential rotation**: if Uniden changes the password, our app's
  next listing fails - we surface a "Uniden update server unavailable;
  please update the app" message and fall back to manual file import
  + the existing FIRMWARE_UPDATER.md cache-import path. This is
  actually a useful liveness check for our distribution.
- **Legality**: We're using publicly-shipped credentials baked into
  publicly-distributed installers, talking to the same server those
  installers talk to, in the same way they talk to it, for the
  documented purpose of interoperability with hardware the user
  legally owns. This is bog-standard reverse engineering for
  interop.
- **No firmware bypass**: We do not modify firmware blobs, do not
  bypass any version-compatibility checks, do not flash beta /
  unsigned firmware. The blobs are dropped on the SD card byte-for-byte
  exactly as Sentinel would.

## Future work

1. **Discover whether Uniden ever publishes BT885 firmware** to
   `ftp.uniden.com/BT885/`. Periodic check (weekly), surface in the
   AI brain so we know when to extend BT885 support.
2. **Sentinel's `archive/` subdirectory** - this is the
   official downgrade source. Useful for the downgrade UI in
   `FIRMWARE_UPDATER.md` Phase 3.
3. **Investigate whether other Uniden products** (BC125AT, BCT15X,
   etc.) use the same FTP infrastructure. Could enable broader
   product support.
4. **Mirror an offline cache**: for users on metered connections or
   air-gapped environments, the app could ship with a one-shot
   "snapshot all current firmware" tool that pulls the FTP listing
   into local cache for later use.
5. **Confirm `MasterHpdb_*.gz` differs between the two endpoints.**
   The Sentinel server's HPDB blobs are ~12 MB gzipped; BT885's are
   ~5.5 MB. Either the BT885 HPDB is genuinely a smaller subset, or
   it's compressed differently. Worth a one-time diff to understand
   what BT885 strips out (probably encoded modes the BT885 doesn't
   support).

## Cross-references

- [`FIRMWARE_UPDATER.md`](../../FIRMWARE_UPDATER.md) - design for the
  in-app firmware updater, now grounded in real endpoints rather than
  TWiki scraping.
- [`sentinel_api.md`](sentinel_api.md) - what Sentinel does over USB
  (mass-storage file ops only); update-check is **not** in that
  surface, it's network-side, which this doc covers.
- [`SDS100_firmware.md`](SDS100_firmware.md) - on-card firmware blob
  format and update-by-file-drop semantics.
- [`AI/Dev/RE/sentinel_decompile/strings/`](../sentinel_decompile/strings/) - raw
  string-extract artifacts that produced the endpoint discoveries.
- [Reverse Engineering wiki home](../../../wiki/Reverse-Engineering.md) -
  high-level overview of the RE work.
