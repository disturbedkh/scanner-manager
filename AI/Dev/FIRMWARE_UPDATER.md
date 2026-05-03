# In-App Firmware Updater - Design

> Status: design only (not implemented). Drafted 2026-04-27 EDT.
> Driven by RE finding that Uniden firmware updates are pure
> SD-card file-drops with no proprietary USB protocol involved.
> Reference: `AI/Dev/RE/SDS100.md` "Firmware update mechanism"
> section, plus the readmes inside the Uniden firmware ZIPs.

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
   them having to look it up on Uniden's TWiki.
2. **One-click update** that handles backup + download + verify +
   copy + reboot prompt + post-flash verification.
3. **Multi-version aware backups** - snapshot the SD card before
   any update so the user can revert programming if the new
   firmware introduces an incompatibility.
4. **Cross-scanner**: SDS100, SDS200, SDS150 share the same scheme.
   Beartracker 885 (same BCDx36HP family but different firmware
   track) follows the same procedure with its own .bin filename.

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

### `data/firmware_manifest.json`

Hand-curated catalogue of every published firmware version per
scanner family. Schema:

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

**Note on URL=null entries.** Sub 1.03.15 is not a public TWiki
attachment - Uniden distributes it via Sentinel only. Our manifest
records it but flags `url: null`; users who already ran a Sentinel
update have it in `C:\ProgramData\Uniden\BCDx36HP_Sentinel\Updater\`,
and we can offer to import from there. Future versions may switch
to public URLs and we update the manifest accordingly.

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

A small scraper that reads
`https://info.uniden.com/twiki/bin/view/UnidenMan4/SDS100FirmwareUpdate`
and similar pages, extracts the changelog table and attachment
list, and proposes manifest additions for human review. Don't
auto-promote - human-in-the-loop for changelog accuracy and to
catch any model/family confusion.

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
   - If in firmware_cache: verify SHA-256, use it.
   - Else if URL available in manifest: download, verify, cache.
   - Else if Sentinel cache exists locally: copy + verify.
   - Else: error out with a useful message ("This version isn't
     publicly hosted by Uniden. Run a Sentinel update first to
     pull it down, then come back.")
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
   BCDx36HP-family but uses different firmware filenames. Does
   our "drop file in BCDx36HP/firmware/" workflow apply? We need
   to read a BT885 firmware ZIP readme to confirm. Likely yes.
2. **Are the .bin SHA-256 values stable across re-uploads?**
   Uniden has historically re-uploaded ZIPs with the same name
   (we saw the SDS200_V1.24.00_Main.zip dated 2026-03-27 which
   is the 1.26.01 release date - they may overwrite). Verify
   that today's .bin is the same as yesterday's before locking
   in checksums.
3. **What does Uniden do with revoked firmware?** If a release
   gets pulled (security issue, brick risk), how do we surface
   that? We need a manifest field for `withdrawn: true`.
4. **Charger detection** - we want to require charger-attached
   for updates. `GCS` would tell us; `GCS` ERRs on FW 1.26.01.
   `<Property Battery>` in GSI is our fallback, but it's 0.0-3.3
   (a coarse 4-step indicator). Good enough for "low battery
   warn", not great for "is charger attached".

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
