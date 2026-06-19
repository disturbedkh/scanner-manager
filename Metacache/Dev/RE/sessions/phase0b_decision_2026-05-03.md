# Phase 0b decision - 2026-05-03

## Inputs

| Capture | Bytes | Decoded CDC pairs |
|---|---:|---:|
| `sentinel_pcaps/01_read_from_scanner.pcap` | 414,126 | 0 |
| `sentinel_pcaps/02_write_to_scanner.pcap` | 2,165,287 | 0 |

`_decode_pcap.py` returned **0 devices observed, 0 pairs decoded** for both
files. tshark did parse the captures successfully (LINKTYPE 152 = USBPcap)
but found no USB CDC class traffic of the form the decoder was built for.

## Observation

A direct dump of the bulk-transfer payloads on the SDS100's two device
addresses (8 and 12) shows **FAT32/SCSI mass-storage traffic**:

- File-system text strings: `TargetModel.BCDx36HP`, `FormatVersion.1.00`,
  `ProductName.SDS100`, plus `GlobalSetting`, `LimitSearch.SrchId=...`,
  `BandDefault.BandId=...`, `DispOptItems.DispOptId=...`, etc.
- HPDB favorites file blobs: many `_000001.hpd` ... `_000113.hpd` and
  `f_000001.hpd ... f_000003.hpd` records with `XWIX`, `XW.\`, `IX..` and
  `HPDB`, `CFG`, `LIST`, `_LIST`, `F_LIST` magic markers.

These are SCSI READ_10 / WRITE_10 transfers carrying FAT32 filesystem blocks
out of the SDS100's microSD card. There are **no `\r`-terminated ASCII command
lines and no CDC interfaces** in either capture.

## Confirmed by user

> "Note: The scanner must be put in mass storage mode for sentinel to work.
> It doesnt work through serial mode."

So Sentinel is a **filesystem editor**, not a serial-protocol client. It
mounts the scanner's SD card via USB Mass Storage Class (UMS / BOT) and
reads/writes the on-card config and HPDB files directly. The MAIN MCU only
participates in the boot path that exposes the card; the SUB MCU is not
involved at all from Sentinel's perspective.

## Phase 0b Decision

The original decision rule was:

> If Sentinel sends >=5 distinct SUB-port mnemonics, fold them into Round 4
> as a known-good baseline and prioritize those handlers in Rounds 2-3.
> If <5, treat Sentinel data as MAIN-side only and proceed with pure static
> SUB RE.

**Decision: pure static SUB RE.** SUB-port mnemonic count from Sentinel = 0
(by design, not by accident). Track A Rounds 1-5 are the only path to the
SUB command vocabulary.

## Implications and follow-ups

1. **`_decode_pcap.py` is the wrong shape for Sentinel.** It was built for
   CDC-ASCII traffic. To extract anything useful from the mass-storage
   captures we need a **SCSI/FAT32 decoder** that reconstructs the file
   reads/writes Sentinel issued. That's a separate project, scoped under
   "Sentinel UMS protocol RE" rather than "SUB serial RE".

2. **Phase 0c (ops 3-6) is reframed.** HPDB / Firmware update / Backup /
   Restore captures are still useful, but for understanding Sentinel's
   filesystem layout (HPDB record format, CFG layout, firmware update
   image structure) - not for SUB command discovery. Defer until Track A
   is done.

3. **User-suggested research question (parked for Round 4):** Is there an
   undocumented SUB or MAIN command that flips the scanner into
   mass-storage-while-still-serial mode? That would let Sentinel and a
   serial probe coexist. Look for any handler in the dispatch table that
   touches USB peripheral configuration registers (USB0 base 0x40006000
   on LPC43xx) when we map the dispatch table in Round 3. Candidate
   mnemonic shapes: anything with `MS`, `STG`, `SD`, `MASS`, `MOUNT`,
   `UMS`. (Likely the actual control sits on the MAIN side, not SUB,
   since MAIN owns the boot-time USB descriptor selection - but worth
   ruling out on SUB first.)

4. **Architectural finding to fold into the wiki:** SDS100 has at least
   two host-facing modes - "serial mode" (two CDC ports + mass storage
   visible) and "mass-storage-only mode" (Sentinel mode). The captures
   we just took were taken with the user in mass-storage-only mode.

## Next step

Proceed directly to Track A Round 1: decompile the four entry points
(`FUN_14010554`, `FUN_1400e57c`, `FUN_1400eb24`, `FUN_1400e900`,
`FUN_14010fec`) via `_decompile_pull.py`.
