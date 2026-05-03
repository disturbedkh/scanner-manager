# In-App Firmware Updater - Design

> Status: design only (not implemented). Drafted 2026-04-27 EDT.
> Updated 2026-05-03 to ground the discovery layer in the actual
> Uniden FTP endpoints (see
> [`AI/Dev/RE/docs/uniden_update_endpoints.md`](RE/docs/uniden_update_endpoints.md))
> instead of the TWiki - the TWiki turns out to be Uniden's
> *publication and downgrade-archive* site, **not** the source
> Sentinel actually checks.
>
> Driven by RE finding that Uniden firmware updates are pure
> SD-card file-drops with no proprietary USB protocol involved.
> References: `AI/Dev/RE/SDS100.md` "Firmware update mechanism"
> section, the readmes inside Uniden firmware ZIPs, and the
> live-listed FTP inventory in `uniden_update_endpoints.md`.

## Why we can ship this

The Sentinel firmware-update workflow is documented in plain English
inside every Uniden firmware ZIP's `Readme*.txt`:

> Open the "firmware" folder inside "BCDx36HP" folder. There are
> two "dat" files inside. Do not touch these files. Copy and paste
> "SDS-100_V1_xx_xx.bin" files to this folder. After the copy is
> complete, reset the power, update will start automatically. Note:
> After the process is finished, these firmware files will be
> automatically deleted from the "firmware" folder.

That's a file-copy. No bootloader handshake, no USB protocol, no key
exchange. Sentinel is a UI wrapper around three filesystem
operations: detect SD card, copy file, prompt user to reboot.

**We can ship the same UI wrapper, plus proper backups, integrity
checks, and auto-detection of which firmware to fetch.**

## Goals

1. **Show the user "you're on X, latest is Y"** at app open, without
   them having to look it up on Uniden's TWiki. We can answer this
   directly by listing
   [`ftp.homepatrol.com/BCDx36HP/`](RE/docs/uniden_update_endpoints.md)
   - the same source Sentinel uses.
2. **One-click update** that handles backup + download + verify +
   copy + reboot prompt + post-flash verification.
3. **Multi-version aware backups** - snapshot the SD card before
   any update so the user can revert programming if the new
   firmware introduces an incompatibility.
4. **Cross-scanner**: SDS100, SDS200, SDS150 share the same scheme.
   Beartracker 885 (same BCDx36HP family but different firmware
   track) follows the same procedure with its own .bin filename
   *if and when* Uniden publishes BT885 firmware - currently the
   BT885 FTP path (`ftp.uniden.com/BT885/`) carries HPDB only.

## Out of scope (for the first cut)

- **Direct USB-bootloader flashing** (PID 0x0019 is NOT a bootloader
  - that earlier hypothesis was wrong; see `AI/Dev/RE/SDS100.md`
  Session 4 "Bombshell" section).
- **Firmware decryption / static RE on Main** (Main is encrypted at
  rest, see `AI/Dev/RE/SDS100_firmware.md`).
- **Bypassing the version-compatibility checks** Uniden ships into
  the scanner (e.g., Sub 1.03.15 requires Main 1.23.20 or later -
  we'll honor those constraints in the manifest).
- **Beta / pre-release firmware** - only ship official Uniden
  releases.

## Phase 1: Firmware library (data plumbing, no scanner contact)

### Discovery layer: live FTP, no hand-curation

Sentinel itself does not maintain a hand-curated manifest. Instead it
lists `ftp.homepatrol.com/BCDx36HP/` and parses filenames - that
directory is the source of truth. Our Phase 1 follows the same
approach: a thin `UnidenFtpClient` that LISTs the directory, parses
filenames into `FirmwareVersion` records, and caches the listing for
~1 hour.

This eliminates the previously-planned TWiki scraper and the
hand-curated `firmware_manifest.json` discovery loop. The TWiki is
still useful as a *secondary* source - for changelog text, downgrade
ZIPs in `archive/`, and human-readable release notes - but it is not
on the critical path for "what versions exist?".

Implementation sketch (full version in
[`uniden_update_endpoints.md`](RE/docs/uniden_update_endpoints.md)):

```python
SENTINEL_FTP = FtpEndpoint(
    host="ftp.homepatrol.com",
    path="/BCDx36HP/",
    user="homepatrolftp",
    password="green7Corn",
)

class UnidenFtpClient:
    def listing(self) -> list[FtpEntry]: ...
    def download(self, filename: str, dst: Path) -> None: ...

class FirmwareLibrary:
    def discover(self, family: str, kind: str) -> list[FirmwareVersion]:
        """List available firmware blobs at the FTP server, parse versions."""
        listing = self._ftp_for(family).listing()
        return [parse_filename_to_version(f) for f, _, _ in listing
                if matches_glob(family.glob(kind), f)]

    def latest(self, family: str, kind: str) -> FirmwareVersion:
        return max(self.discover(family, kind), key=lambda v: v.tuple)
```

A small **optional** `data/firmware_manifest.json` lives alongside
this for *enrichment* only - changelog excerpts, `requires_sub_min`
constraints, withdrawn-firmware flags, and SHA-256 baselines for
files we've already verified. The manifest is no longer the source
of "what exists"; it's annotation on top of FTP discovery. Schema:

```json
{
  "schema_version": 1,
  "scanners": {
    "SDS100": {
      "model_aliases": ["SDS100", "UB3832"],
      "main_filename_glob": "SDS-100_V*.bin",
      "sub_filename_glob": "SDS-100-SUB_V*.firm",
      "firmware_folder_on_card": "BCDx36HP/firmware",
      "do_not_touch_files": [
        "BCDx36HP/firmware/CityTable_*.dat",
        "BCDx36HP/firmware/ZipTable_*.dat"
      ],
      "main_versions": [
        {
          "version": "1.26.01",
          "release_date": "2026-03-27",
          "url": "https://info.uniden.com/twiki/pub/UnidenMan4/SDS100FirmwareUpdate/SDS100_V1.26.01_Main.zip",
          "sha256_zip": null,
          "sha256_bin": "CFB07E720B37F88E58A738D3BD81D25B5D1F4484711167E653BE301FBDAC7D9A",
          "bin_size": 2162688,
          "requires_sub_min": "1.03.15",
          "changelog_excerpt": "Added Type option to the P25 Manual Band Plan. Enabled Slot Selection option for DMR OFT frequencies. Improved late entry reception for DMR Capacity Max (Tier 3). [...]"
        },
        {
          "version": "1.24.00",
          "release_date": "2025-12-20",
          "url": "https://info.uniden.com/twiki/pub/UnidenMan4/SDS200FirmwareUpdate/SDS200_V1.24.00_Main.zip",
          "sha256_bin": "<TBD>",
          "bin_size": 2162688,
          "requires_sub_min": "1.03.15",
          "changelog_excerpt": "..."
        }
      ],
      "sub_versions": [
        {
          "version": "1.03.15",
          "release_date": "2025-10-17",
          "url": null,
          "sha256_firm": "C8FBEE4370589EE801EE8BDF97F4476F7CF5D6362ADD850A13810B0750520909",
          "firm_size": 90464,
          "changelog_excerpt": "Improved WFM/FMB Squelch Threshold Adjustment. Resolved an issue where no audio was output during P25 voice decoding on P16 3600 baud systems."
        }
      ]
    },
    "SDS200": { "model_aliases": ["SDS200", "UB3842"], "..." : "..." },
    "SDS150": { "model_aliases": ["SDS150", "UB3912"], "..." : "..." },
    "BT885":  { "model_aliases": ["BT885", "BT885-SCN", "Beartracker885"], "..." : "..." }
  }
}
```

**Note on URL=null entries.** With FTP discovery this is rarely
needed - the FTP server holds every published Sub firmware
(`SDS-100-SUB_V*.firm`) as well as Main. The `url: null` fallback
is reserved for two cases: (a) versions that have never been
published to FTP (none observed to date), and (b) future scenarios
where Uniden migrates to a different distribution mechanism. The
"import from Sentinel cache" path
(`%PROGRAMDATA%\Uniden\BCDx36HP_Sentinel\Updater\`) remains a
backup ingestion route for users without internet access at update
time.

### `firmware_cache/` directory

User-app local cache. Layout:

```
<user_data_dir>/firmware_cache/
  SDS100/
    main_1.23.07/
      SDS100_V1.23.07_Main.zip          (downloaded, verified)
      SDS-100_V1_23_07.bin              (extracted)
      Readme SDS100 V1_23_07.txt
      sha256.json                        (per-file checksums)
    main_1.26.01/
      SDS-100_V1_26_01.bin               (imported from Sentinel cache)
      sha256.json
    sub_1.03.15/
      ...
```

### Manifest refresh

Two complementary refresh paths:

1. **Primary (automatic):** the FTP listing is the source of truth
   for "what exists". `FirmwareLibrary.discover()` runs on demand
   and is cheap (~1-2s for a fresh listing).
2. **Annotation (human-in-the-loop):** a small scraper reads
   `https://info.uniden.com/twiki/bin/view/UnidenMan4/SDS100FirmwareUpdate`
   and similar pages, extracts the changelog table, and proposes
   `changelog_excerpt` / `requires_sub_min` additions to the
   enrichment manifest for human review. Don't auto-promote -
   human-in-the-loop for changelog accuracy and to catch any
   model/family confusion. Note that the TWiki has a known habit of
   serving mislabeled files (e.g., a "1.24" page hosting a 1.26
   ZIP), so the FTP server is where we go for the actual blobs;
   TWiki is for the prose.

### "Firmware Library" GUI panel

A standalone tab/panel:

- Tree by scanner family -> Main / Sub list
- Per-row badges:
  - "current on connected scanner"
  - "downloaded"  / "not downloaded" / "Sentinel cached"
  - "outdated" (if there's a newer one)
- Click a row -> changelog excerpt, file size, requires-sub-min
- Buttons: **Download**, **Verify**, **Import from Sentinel cache**

Phase 1 ships independent of any scanner. Useful even without an
update flow.

## Phase 2: Update workflow

### Pre-flight

Before showing the "Update Firmware" button, verify:

1. **Scanner is connected and detected** in either:
   - USB Mass Storage mode (`H:\BCDx36HP\` visible to OS), OR
   - USB Serial mode (we can read `MDL`/`VER` over the MAIN port,
     and ask the user to switch to Mass Storage)
2. **`scanner.inf` model field matches the firmware family.** Don't
   let the user accidentally drop SDS200 .bin onto an SDS100 card.
3. **The SD card is the one paired with this scanner** - we can
   detect this via the metastore profile system already in place.
4. **`requires_sub_min` is satisfied.** If updating Main to 1.26.01
   needs Sub >= 1.03.15 and the scanner is on Sub 1.03.06, surface
   a "this update requires updating Sub first" guard with a
   suggested order.
5. **No existing `.bin` or `.firm` already in the firmware folder**
   (Uniden's readme: "Do not put different firmware versions on the
   SD card at the same time"). If found, offer to clear or refuse.
6. **Battery is charged enough or charger plugged in.** We can read
   `<Property Battery="0.0-3.3">` from `GSI` over serial, or
   eventually `GCS` if/when it works on FW 1.26.01 (currently ERRs).

### Update steps

```
[Click "Update to 1.26.01"]
    |
    v
1. Make a backup of the SD card
   - Reuse existing snapshot/backup manager
   - Tag the backup: pre_main_1.23.07_to_1.26.01_<timestamp>
   - User-visible: "Backup created so you can revert if needed."
    |
    v
2. Resolve the firmware file
   - If in firmware_cache: verify SHA-256 (if we have one), use it.
   - Else: download from FTP (`ftp.homepatrol.com/BCDx36HP/`),
     verify reported size matches `SIZE` from the listing, cache.
   - Else if Sentinel local cache exists
     (`%PROGRAMDATA%\Uniden\BCDx36HP_Sentinel\Updater\`):
     copy + verify.
   - Else: error out with a useful message ("Uniden update server
     unreachable; you can manually drop the .bin onto the SD card
     yourself and we'll detect it.")
    |
    v
3. Validate the SD card pre-state
   - Confirm `BCDx36HP/firmware/` exists.
   - Confirm `CityTable_*.dat` and `ZipTable_*.dat` are still there
     (would brick startup if missing - per Uniden readme).
   - Confirm folder is empty of any prior `.bin`/`.firm`.
    |
    v
4. Copy the firmware
   - Copy SDS-100_V1_26_01.bin -> H:\BCDx36HP\firmware\
   - Verify SHA-256 of the file *as written on SD* matches manifest.
   - (Sub firmware is .firm extension; same flow.)
    |
    v
5. Show "ready to flash" instructions
   - Modal:
       "Firmware copied to the SD card.
        1. Eject the scanner from your computer (don't just unplug).
        2. The scanner will reboot automatically when ejected, or
           power-cycle it manually.
        3. Do NOT turn the scanner off until the update finishes.
           This typically takes 1-2 minutes; the screen will show
           a progress bar.
        4. Click 'I rebooted' below when the scanner is back at
           its normal scan screen."
   - User clicks "I rebooted".
    |
    v
6. Verify post-flash
   - Wait for scanner to re-mount (may take ~30s).
   - Read scanner.inf to confirm new version stamp.
   - If serial mode reachable: query VER, confirm matches target.
   - Confirm the .bin/.firm file was auto-deleted by the scanner.
   - If anything is wrong: surface it loudly, offer to restore from
     the pre-flash backup.
    |
    v
7. Update manifest "current" state
   - Mark the new version as "current on this scanner".
   - Move the pre-flash backup to the user's normal backup history.
```

### Failure modes & mitigations

| Failure | Mitigation |
|---|---|
| User pulls SD card mid-copy | We write atomically (copy to temp + rename); if interrupted, no partial .bin |
| User unplugs power mid-flash | Same risk Sentinel has - unavoidable. We warn before step 5. Battery + charger check. |
| User puts wrong-family .bin in folder (e.g., SDS200 onto SDS100) | We never copy a .bin whose model magic doesn't match `scanner.inf`. |
| Multiple .bin files end up in folder | Pre-flight detects and refuses. |
| Scanner self-deletes the .bin but reports old VER | Detect the mismatch in step 6 and surface "flash may have failed; recheck" |
| Network error during download | Retry with backoff; cache partial on disk; resumable downloads via HTTP Range. |
| Manifest URL 404s (Uniden moved the file) | Manifest has `sha256_zip` so we can also fetch from a mirror; in the worst case we offer the user a manual-import flow. |

## Phase 3: QoL features (post-launch polish)

- **Update notification on app start** - quiet badge, not nag-y.
- **Pinned versions** - "stay on 1.23.07" suppresses prompts.
- **Downgrade UI** - Uniden's own readmes literally document
  downgrades, so support them with a "this is intentional" guard.
- **Pair with multi-SD-card-profiles** - lock a profile to a
  firmware version when relevant.
- **Compatibility matrix display** - "Main 1.26.01 needs Sub
  >= 1.03.15. Your Sub is 1.03.05. Update Sub first."
- **Differential update history per scanner** - "this scanner has
  been on Main 1.23.07 (4 days), now on 1.26.01 (since today)."

## Open questions to resolve before implementation

1. **What about the BT885 (Beartracker)?** The BT885 is also
   BCDx36HP-family. The BT885 Update Manager UI exposes a
   firmware-update flow, but its FTP path
   (`ftp.uniden.com/BT885/`) currently carries *only* HPDB blobs
   - no `.bin` or `.firm` files. So either Uniden has not shipped
   firmware updates for the BT885 in the lifetime of the product,
   or they ship through a different mechanism we haven't seen
   yet. **For now: BT885 support = HPDB sync only.** Watch the
   FTP path; if firmware appears, our existing `FirmwareLibrary`
   picks it up automatically using the same algorithm.
2. **Are the .bin SHA-256 values stable on FTP?** The FTP server
   serves the canonical blob. Uniden has occasionally re-uploaded
   files with the same name, so when we cache a .bin we record
   the FTP `MDTM` (modification timestamp) alongside the SHA-256.
   On every later update check we re-verify `MDTM` matches; a
   change triggers a re-download.
3. **What does Uniden do with revoked firmware?** If a release
   gets pulled (security issue, brick risk), how do we surface
   that? Two signals: the file disappears from the live FTP
   listing (we detect this on next `discover()`), and the TWiki
   page typically gets a "this version was withdrawn" note (we
   surface that via the enrichment scraper). We need a manifest
   field `withdrawn: true` for the latter.
4. **Charger detection** - we want to require charger-attached
   for updates. `GCS` would tell us; `GCS` ERRs on FW 1.26.01.
   `<Property Battery>` in GSI is our fallback, but it's 0.0-3.3
   (a coarse 4-step indicator). Good enough for "low battery
   warn", not great for "is charger attached".
5. **FTP credential rotation.** If Uniden ever changes the FTP
   credentials, our discovery layer fails. Handling: explicit
   error path → "Uniden update server unavailable; please update
   the app". Our app's `data/uniden_installers.json` already
   pins SHA-256 of the current Sentinel installer, so we can
   detect when Uniden ships a new Sentinel and prompt the user
   (or our maintainer) to re-extract creds. See
   [`uniden_update_endpoints.md`](RE/docs/uniden_update_endpoints.md)
   "Risks / etiquette".

## Code-level sketch

A small new module (`scanner_manager/firmware_updater.py` is fine
for now; can move into the future multi-scanner backend's
`scanner_profiles/` package later):

```python
@dataclass
class FirmwareVersion:
    version: str               # "1.26.01"
    release_date: date
    bin_filename: str          # "SDS-100_V1_26_01.bin"
    sha256: str
    size_bytes: int
    requires_sub_min: str | None
    changelog: str
    url: str | None

@dataclass
class FirmwareManifest:
    by_family: dict[str, FamilyManifest]   # "SDS100" -> ...
    @classmethod
    def load(cls, path: Path) -> "FirmwareManifest": ...

class FirmwareLibrary:
    """Local cache + download orchestrator. No scanner contact."""
    def is_cached(self, family: str, kind: str, version: str) -> bool: ...
    def download(self, family: str, kind: str, version: str) -> Path: ...
    def import_from_sentinel(self, ...) -> Path: ...

class FirmwareUpdater:
    """The actual update workflow. Talks to the SD card and (optionally) the scanner serial port."""
    def preflight(self, sd_card: Path, scanner: ScannerHandle, target: FirmwareVersion) -> list[Issue]: ...
    def apply(self, sd_card: Path, target: FirmwareVersion) -> ApplyResult: ...
    def post_flash_verify(self, scanner: ScannerHandle, target: FirmwareVersion) -> VerifyResult: ...
```

GUI integration is a separate panel; integration into the existing
backup manager is one extra hook (tag pre-flash snapshots).

---

**Ready to implement when you say go.** Phases 1 and 2 together are
1-2 days of work. Phase 1 is independent and can ship first.
