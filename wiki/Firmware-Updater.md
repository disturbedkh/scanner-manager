# Firmware Updater

> Status: shipped (v0.11.x)

Find Main / Sub firmware and HPDB channel-database snapshots from
Uniden's update servers, download them safely, and apply them to your
SD card with backup and verification.

Open **Tools → Firmware updater…** in the Qt app (also available from
the Classic Tk Tools menu). The header **FW** pill shows on-card
Main/Sub versions when an SD path is bound.

## Prerequisites

- SD card mounted with a `BCDx36HP` folder (**Mass Storage** or card
  reader)
- Device registered with the correct scanner family ([Qt UI](Qt-UI))
- Internet access to Uniden's FTP update hosts
- Enough free space for a full `BCDx36HP/` backup beside the card

## Steps

1. **Tools → Firmware updater…**
2. Discover / refresh available Main, Sub, and HPDB packages for your
   scanner family.
3. Download the package you want (cached locally with a checksum).
4. Click **Run update wizard…** and follow the prompts:
   1. Pre-flight checks (card identity, checksum, optional Sub minimum)
   2. Backup of `BCDx36HP/`
   3. Apply to the card
   4. Eject / reboot guidance
   5. Post-flash verify against `scanner.inf`

Always eject the card safely after a write — especially on Linux VFAT
([Troubleshooting](Troubleshooting)).

## Scanner families and servers

| Family | Update host (read-only) |
| --- | --- |
| BCDx36HP / SDS100/200 | Uniden HomePatrol FTP (`/BCDx36HP/`) |
| BT885 | Uniden FTP (`/BT885/`) |

Scanner Manager only lists and downloads; it never uploads to those
servers.

## What gets written on the card

```
BCDx36HP/
  scanner.inf
  HPDB/          ← HPDB snapshots
  firmware/      ← Main .bin (scanner removes after flash)
    sub/         ← Sub .firm (scanner removes after flash)
```

## If something goes wrong

- Pre-flight fails — confirm `scanner.inf` matches the selected device
  family and that the download checksum passed.
- Apply interrupted — restore from the backup folder created beside the
  card (`scanner-manager-backups/…`), then retry.
- Scanner won't boot after flash — restore the backup, or re-pave with
  Uniden Tools on Windows ([Uniden Tools](Uniden-Tools-Integration)).

## Internals

Typical package names:

| Pattern | Meaning |
| --- | --- |
| `<MODEL>_V… .bin` | Main firmware |
| `<MODEL>-SUB_V… .firm` | Sub firmware |
| `MasterHpdb_… .gz` | Weekly HPDB snapshot |
| `CityTable_… .dat` / `ZipTable_… .dat` | Location tables |

Cache lives under the user cache directory
(`…/scanner-manager/firmware_cache/<family>/…`) with sidecar checksums.
Apply uses write-to-`.partial` then atomic replace; stale firmware files
are purged first (same idea as Sentinel).

Contributor docs: [Architecture](Architecture). Deep endpoint notes live
in the RE lab (not required for normal updates).
