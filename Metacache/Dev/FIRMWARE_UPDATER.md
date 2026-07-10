# In-App Firmware Updater — As-Built Reference

> Status: **shipped (v0.11.x)** — FTP discovery, local cache, SD-card apply
> workflow, Qt firmware dock. Optional enrichment manifest not shipped.

User-facing tour: [Firmware Updater wiki](https://github.com/disturbedkh/scanner-manager/wiki/Firmware-Updater).

RE grounding: Uniden updates are **SD-card file drops** (no proprietary USB
flash protocol). Sentinel and our app wrap backup → download → verify → copy →
reboot prompt. See
[`Metacache/Dev/RE/docs/uniden_update_endpoints.md`](RE/docs/uniden_update_endpoints.md)
and [`Metacache/Dev/RE/docs/SDS100.md`](RE/docs/SDS100.md) (firmware update
mechanism).

## Module map

| Module | Role |
| --- | --- |
| `firmware/ftp_client.py` | `UnidenFtpClient` — LIST/RETR against vendor FTP servers; credentials from `data/uniden_installers.json`. |
| `firmware/library.py` | Filename parsing (`FirmwareVersion`, `HpdbVersion`), `FirmwareCache` under user-data dir, SHA-256 verify. |
| `firmware/updater.py` | `preflight`, `apply_*`, `backup_card`, `postflash_verify` — SD-card side effects. |
| `firmware/vendor_ftp_transport.py` | Host allowlist + safe path handling for FTP downloads. |
| `gui/firmware/firmware_dock.py` | Qt UI: FTP refresh worker, library trees (Main/Sub/HPDB), update wizard, log + progress. |
| `gui/windows.py` | `FirmwareWindow` — standalone firmware window from header/menu. |
| `data/uniden_installers.json` | **Shipped SSOT** for FTP endpoints, allowed hosts, installer metadata. |

### Planned but not shipped: `data/firmware_manifest.json`

The original design doc described an optional enrichment manifest for
changelog excerpts, `requires_sub_min` constraints, and withdrawn flags.
**This file is not in the repo.** Discovery uses live FTP listings; constraints
are applied where coded in `firmware/updater.py` and profile-specific paths.
A future manifest would be annotation-only, not the source of "what exists."

## Discovery layer (live FTP)

Two endpoints (credentials loaded at runtime from `uniden_installers.json`):

| Key | Host | Contents |
| --- | --- | --- |
| `sentinel` | `ftp.homepatrol.com` / `BCDx36HP/` | Main `.bin`, Sub `.firm`, HPDB `.gz`, table `.dat` — SDS100/200/150 family |
| `bt885` | `ftp.uniden.com` / `BT885/` | HPDB snapshots only (no firmware bins observed) |

`UnidenFtpClient.listing()` parses `NLST` entries; `FirmwareLibrary` filters
by family-specific globs (`filter_main_firmware`, `filter_sub_firmware`,
`filter_hpdb` in `firmware/library.py`).

TWiki pages are **not** on the critical path for version discovery; they remain
useful for human changelog text only.

## Local cache layout

Under the OS user-data directory (see `FirmwareCache` in `firmware/library.py`):

```
<firmware_cache>/
  SDS100/
    main_1.26.01/
      SDS-100_V1_26_01.bin
      sha256.json
    sub_1.03.15/
      SDS-100-SUB_V1_03_15.firm
      sha256.json
```

Downloads verify SHA-256 when a baseline is known; FTP `MDTM` is recorded for
re-validation.

## Update workflow (`firmware/updater.py`)

1. **`backup_card()`** — timestamped copy of `BCDx36HP/` before any write.
2. **`preflight()`** — `scanner.inf` model match, `requires_sub_min` when
   applicable, cache SHA-256, empty firmware folder guard.
3. **`apply_main_firmware()` / `apply_sub_firmware()` / `apply_hpdb()`** —
   atomic copy (`.partial` → rename) to:
   - Main: `BCDx36HP/firmware/<filename>`
   - Sub: `BCDx36HP/firmware/sub/<filename>`
   - HPDB: `BCDx36HP/HPDB/<filename>`
4. **`postflash_verify()`** — re-read `scanner.inf` after user ejects/reboots;
   confirm version field updated and staging file removed by scanner.

Raises `FirmwareError` on failed preflight or apply steps.

## Qt UI (`gui/firmware/firmware_dock.py`)

- **Refresh from Uniden** — background `_RefreshWorker` thread hits FTP.
- Tabbed trees: Main firmware, Sub firmware, HPDB (badges: current / latest /
  cached).
- Details panel: filename, size, MDTM, SHA-256, cache status.
- Update wizard: runs preflight → apply → post-flash instructions modal.
- Integrates with `virtual_sd.VirtualCard` for staged SD paths when not writing
  directly to a drive letter.
- Opened from header **Check for updates…** or Tools menu (`FirmwareWindow`).

Dock receives `set_active_profile()` / device context from `MainWindow` so
family-specific globs match the selected scanner.

## Family support matrix

| Scanner | Main/Sub FTP | HPDB FTP | Notes |
| --- | --- | --- | --- |
| SDS100 / SDS200 / SDS150 | yes (Sentinel path) | yes | Primary target |
| BT885 | no bins on FTP today | yes (`bt885` path) | HPDB sync only until Uniden publishes firmware |

## Safety mitigations (implemented)

- Pre-flash SD backup (reuse snapshot manager where wired).
- SHA-256 verify on cached blobs; size check against FTP `SIZE`.
- `scanner.inf` model-field guard — refuse wrong-family `.bin`.
- Refuse multiple `.bin`/`.firm` already in firmware folders.
- Atomic write to SD (partial file + rename).

## Out of scope (unchanged)

- Direct USB-bootloader flashing (PID `0x0019` is not a bootloader).
- Main firmware decryption / static RE.
- Bypassing Uniden version-compatibility checks baked into scanner firmware.
- Beta / pre-release firmware channels.

## Residual / future work

- Ship optional `data/firmware_manifest.json` for enrichment (changelog,
  withdrawn flags) — **not shipped**; FTP filename parsing is the SSOT today.
- BT885 Main/Sub updates if Uniden adds bins to the BT885 FTP path.
- Charger-attached guard (`GCS` unreliable on some FW versions; GSI battery
  property is coarse).
- Downgrade UI polish, pinned versions, update nag on app start.

## Cross-references

- [`MULTI_DEVICE_GUI.md`](MULTI_DEVICE_GUI.md) — header FW pill + update button.
- [`MULTI_SCANNER_BACKEND.md`](MULTI_SCANNER_BACKEND.md) — per-profile firmware folder layout.
- [`Metacache/Dev/RE/docs/uniden_update_endpoints.md`](RE/docs/uniden_update_endpoints.md) — FTP RE artifacts.
- [`Metacache/EXPORT_POLICY.md`](../EXPORT_POLICY.md) — RE installer binaries export tier.

## Quick verification

```powershell
pytest tests/test_firmware_ftp_client.py tests/test_firmware_library.py tests/test_firmware_updater.py -q
ruff check firmware/ gui/firmware/
```
