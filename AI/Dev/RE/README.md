# Reverse Engineering Notes

Per-scanner RE notes captured from real SD cards. Treat these as the
canonical source of truth for "what does this scanner actually write
to disk", because Uniden does not publish a spec.

> If a fact in here disagrees with code in `scanner_manager.py` or
> `scanner_profiles/`, **the RE note wins**. The code may pre-date
> the RE or be wrong. Reconcile by updating the code, never by
> editing the RE note to match buggy code.

## Files in this folder

| File | Purpose |
| --- | --- |
| `SDS100.md` | Uniden SDS100 (+ SDS200 by extension) - SD card RE plus live serial-mode RE. RE'd from real card on `D:\` and live USB serial on `MINILAPTOP`, both `2026-04-27`. |
| `serial_probe.py` | **READ-ONLY** passive probe for live scanners. Sends only commands from a vetted whitelist; refuses to send anything from a hard-coded forbidden list. See "Running the probes" below. |
| `com6_listen.py` | Listen-only baud sweep used to determine whether a CDC port is GPS NMEA, idle command port, or something else. Writes nothing. |
| `sessions/` | Timestamped raw probe captures. Committed so the analysis in `SDS100.md` is reproducible from raw bytes. Filename convention: `<probe>_<timestamp>.txt`. |

## Running the probes (live scanner over USB)

The SDS100 (and SDS200) needs to be in **Serial Mode** at the boot-time
USB connection prompt (press the **`.`** / period key). It then
enumerates **two** Uniden CDC virtual COM ports:

| PID | Role | Probe target? |
| --- | --- | --- |
| `0x0019` | SUB processor bootloader | NO - only useful for Sentinel firmware flashing; not a general protocol |
| `0x001A` | MAIN processor command port | **YES** - this is where the Uniden Remote Command Protocol lives |

Find the right COM port:

```powershell
Get-CimInstance Win32_PnPEntity |
  Where-Object { $_.DeviceID -match 'VID_1965' } |
  Select-Object Name, DeviceID
```

The port whose DeviceID contains `PID_001A` is your target.

Prerequisites:

```powershell
# Anywhere - the scripts use only stdlib + pyserial
py -m pip install --user pyserial
```

Run the probe (replace `COM6` with whatever PID `0x001A` enumerated as):

```powershell
py AI\Dev\RE\serial_probe.py --port COM6
```

Output goes to `AI/Dev/RE/sessions/sds100_serial_<timestamp>.txt` and is
also streamed to the terminal. The probe takes ~20 seconds (36 commands
x ~600 ms timeout, faster when responses arrive early).

## Safety contract for the probes

- **Whitelist-only.** New mnemonics may be added to `serial_probe.py`'s
  `QUERIES` list **only** after confirming in the Uniden Operation
  Specification that they have no "set" semantics.
- **Hard-coded forbidden list.** `KEY`, `PRG`, `EPG`, `JNT`, `JPM`,
  `WPL`, `WPS`, `CLR`, `DLA`, `MEMSET`, `WIPE`, `TGW`, `VLO`, `SLO`,
  `GLT`, `RST,SET` will never be sent regardless of the whitelist.
- **No `,?` -> `set` escalation.** Even if the scanner answers `OK` to
  a `cmd,?` write-test, do NOT follow up with an actual `cmd,value`
  call; that's by definition a state change.
- **MAIN port only (PID `0x001A`).** Don't probe the SUB bootloader
  with anything beyond the Session-1 capture already in `SDS100.md`.

## Adding a new scanner RE

1. Plug the scanner's SD card in. Note the drive letter, volume label,
   filesystem, and total / free size.
2. Mirror the structure of `SDS100.md`:
   - Identity files and what they contain.
   - Top-level layout with sizes / counts.
   - Per-folder analysis (HPDB, favorites, discovery, audio, etc.).
   - Record-type tally for at least one large HPD file.
   - Sample raw lines for every record type.
   - Delta vs. the closest already-supported model.
   - Open questions / fields we don't yet understand.
3. **Don't paraphrase**. Paste actual file contents (truncated where
   sensible) so the next agent can verify without the physical card.
4. Cross-reference into `AI/Dev/MULTI_SCANNER_BACKEND.md` so the
   driver-layer plan stays accurate.

## What goes in here vs. `docs/adding-a-scanner.md`

- `docs/adding-a-scanner.md` is **public-facing** developer
  documentation - generic, prescriptive, terse. Lives in git, ships
  with the project.
- `AI/Dev/RE/*` is **internal RE artifacts** - verbose, raw,
  hostname-tagged, includes sample data dumps and conjecture. Also
  in git so cross-machine syncs work, but the audience is "us"
  (humans + AI agents) not "external contributors adding a profile".

When you add a new scanner profile, both files exist - the RE doc
captures _what the scanner writes_, the public doc captures _how to
slot a profile into the codebase_.
