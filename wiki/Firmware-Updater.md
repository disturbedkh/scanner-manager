# Firmware Updater

> The Firmware dock discovers Main / Sub firmware images and HPDB
> snapshots from Uniden's two FTP servers, caches them locally with
> SHA-256 verification, and applies them to the SD card with
> backup + atomic copy + post-flash verify.

The full reverse-engineered endpoint reference lives at
[`AI/Dev/RE/docs/uniden_update_endpoints.md`](../AI/Dev/RE/docs/uniden_update_endpoints.md);
this page is the user-facing summary.

## Endpoints

| Family              | Server                  | Path           |
| ------------------- | ----------------------- | -------------- |
| BCDx36HP / SDS100/200 | `ftp.homepatrol.com`  | `/BCDx36HP/`   |
| BT885               | `ftp.uniden.com`        | `/BT885/`      |

Both are plain FTP, anonymous-ish credentials baked into Uniden's
publicly-distributed installers (Sentinel + BT885 Update Manager).
We only ever issue `LIST + SIZE + MDTM + RETR`; we never write back
to either server.

## Filename grammar

| Pattern | Decoded as |
| ------- | ---------- |
| `<MODEL>_V<MAJ>_<MIN>_<PAT>.bin`        | Main MCU firmware |
| `<MODEL>-SUB_V<MAJ>_<MIN>_<PAT>.firm`   | Sub MCU firmware  |
| `MasterHpdb_<MM>_<DD>_<YYYY>.gz`        | Weekly HPDB snapshot |
| `CityTable_V<x>_<yy>_<zz>.dat`          | City lookup table |
| `ZipTable_V<x>_<yy>_<zz>.dat`           | ZIP code lookup table |
| `BC-WF1_V<X>_<XX>.bin`                  | BC-WF1 Wi-Fi adapter firmware |

`firmware.library.FirmwareVersion.parse` / `HpdbVersion.parse` decode
each pattern into a sortable record. The dock filters per family by
matching `FAMILY_MAIN_MODELS[family_id]`.

## Cache layout

`firmware.library.FirmwareCache` stores blobs under:

```
<user_cache>/scanner-manager/firmware_cache/
    <family_id>/
        main_<version>/
            <filename>
            <filename>.sha256
        sub_<version>/
            ...
```

`FirmwareCache.verify(family, version)` rehashes the blob and compares
to the sidecar. The Update wizard refuses to apply a cached file that
fails verification.

## Wizard flow

The dock's **Run update wizard…** button orchestrates:

1. **Pre-flight** (`firmware.updater.preflight`)
   - Confirm the SD card has `BCDx36HP/scanner.inf`.
   - Confirm field 1 matches the active scanner profile.
   - Verify the cached blob's SHA-256.
   - If `requires_sub_min` is supplied, ensure the on-card sub firmware
     meets the minimum.
2. **Backup** (`firmware.updater.backup_card`) - copies
   `BCDx36HP/` to `<card_parent>/scanner-manager-backups/<ts>/`.
3. **Apply** (`apply_main_firmware` / `apply_sub_firmware` /
   `apply_hpdb`)
   - Purge stale `.bin` / `.firm` from the target dir (Sentinel does
     the same to avoid bootloader name-precedence weirdness).
   - Write to a `.partial` sibling, then `os.replace` for atomic
     swap.
4. **Eject + reboot** (modal in the dock).
5. **Post-flash verify** (`postflash_verify`) - re-reads
   `scanner.inf` after reboot and compares the new version field to
   what we expected.

## SD card layout

```
\BCDx36HP\
    scanner.inf
    \HPDB\
        MasterHpdb*.gz                <- HPDB snapshots land here
    \firmware\
        <MODEL>_V*.bin                <- Main firmware (transient,
                                         scanner self-deletes after flash)
        \sub\
            <MODEL>-SUB_V*.firm       <- Sub firmware (transient)
```

## Tests

- `tests/test_firmware_library.py` - filename parsing + cache
  store / verify roundtrips.
- `tests/test_firmware_ftp_client.py` - fake `ftplib.FTP` validates
  protocol verbs + MDTM parsing + chunked download.
- `tests/test_firmware_updater.py` - card-shape fixtures cover
  pre-flight, atomic apply, purge of stale firmware, post-flash
  verify.
- `tests/test_qt_firmware.py` - smoke tests for the dock UI.

## Cross-references

- [Qt UI](Qt-UI.md)
- [`AI/Dev/RE/docs/uniden_update_endpoints.md`](../AI/Dev/RE/docs/uniden_update_endpoints.md)
- [`AI/Dev/FIRMWARE_UPDATER.md`](../AI/Dev/FIRMWARE_UPDATER.md)
