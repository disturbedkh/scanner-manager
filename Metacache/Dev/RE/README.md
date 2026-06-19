# Reverse Engineering / Development - Lab notebook

> **Canonical narrative is the wiki.** Start at
> [`wiki/Reverse-Engineering.md`](../../wiki/Reverse-Engineering.md)
> (or `Reverse-Engineering` on the GitHub Wiki) for the consolidated
> story. The wiki tells you what we found and why it matters; this
> folder is the **lab notebook** behind it - raw probe captures,
> Ghidra projects, decompiles, pcaps, session logs, and the scripts
> that produced all of the above.
>
> Lab files in here are kept for reproducibility and for cases where
> the wiki abridges detail. They are **not** the canonical narrative.
> If a wiki page disagrees with a lab file, the file wins (it has the
> timestamp + bytes); fix the wiki.

This folder is the home of the project's **RE / Development**
workstream. Use it when you want to extend the work: add a new
scanner family, port to a new SUB firmware, capture another Sentinel
operation, etc.

## Layout

```
Metacache/Dev/RE/
├── README.md             # this file
├── tools/                # canonical scripts (live probes, firmware,
│                          #  Sentinel, automation, legacy archive)
├── docs/                 # canonical lab notebooks (BT885.md,
│                          #  SDS100.md, SD_CARD_COMPARISON.md,
│                          #  Sentinel write-ups, etc.)
├── specs/                # vendor PDFs / TXTs (Uniden Remote Command
│                          #  spec V1.02, V2.00, BCDx36HP V1.05)
├── plans/                # forward-looking RE plans (e.g. virtual
│                          #  scanner roadmap)
├── firmware/             # firmware blobs + Ghidra projects
│                          #  (gitignored; bring your own)
├── firmware_analysis/    # strings dumps + diffs (gitignored)
├── sentinel_pcaps/       # raw USBPcap captures (gitignored) + the
│                          #  decoded *.summary.md / *.files.md /
│                          #  *.scsi.jsonl artifacts (committed)
└── sessions/             # raw probe session logs (gitignored)
```

The `tools/` folder is the new home for everything executable -
serial probes, firmware analyzers, Sentinel decoders, Ghidra glue.
See `tools/README.md` for a one-line description of every script and
common workflows.

## Wiki pages this notebook backs

| Topic | Wiki page (canonical) | Backed by |
| --- | --- | --- |
| Two-MCU architecture | [RE-Architecture](../../wiki/RE-Architecture.md) | `docs/SDS100.md`, `docs/sub_static_analysis.md`, `firmware/decompiles/` |
| USB Mass Storage vs Serial mode | [RE-USB-Modes](../../wiki/RE-USB-Modes.md) | `tools/probes/list_ports.py`, `tools/automation/find_sds100_hub.ps1` |
| SD card layout (BCDx36HP family) | [RE-SD-Card](../../wiki/RE-SD-Card.md) | `docs/SD_CARD_COMPARISON.md`, `docs/BT885.md`, `docs/SDS100.md`, `tools/sentinel/compare_cards.py` |
| Serial command catalogs | [RE-Serial-Protocol](../../wiki/RE-Serial-Protocol.md) | `docs/SDS100_unofficial_commands.md`, `docs/sub_command_dispatch.md`, `tools/probes/serial_probe.py`, `tools/probes/sub_probe.py` |
| Inter-MCU USART2 protocol | [RE-Inter-MCU-Bus](../../wiki/RE-Inter-MCU-Bus.md) | `docs/SDS100_inter_mcu_protocol.md`, `firmware/decompiles/` |
| Firmware (SUB container, MAIN encryption) | [RE-Firmware](../../wiki/RE-Firmware.md) | `docs/SDS100_firmware.md`, `tools/firmware/inflate_sub.py`, `firmware/`, `tools/automation/` |
| Sentinel as UMS editor | [RE-Sentinel](../../wiki/RE-Sentinel.md) | `docs/sentinel_api.md`, `docs/sentinel_capture.md`, `sentinel_pcaps/`, `tools/sentinel/` |
| Tool inventory | [RE-Toolchain](../../wiki/RE-Toolchain.md) | `tools/README.md` and the per-script docstrings |
| Recipes / playbooks | [RE-Workflows](../../wiki/RE-Workflows.md) | `docs/AUTOMATION.md`, `docs/ghidra_import_runbook.md` |
| Virtual scanner roadmap | [Virtual-Scanner-Roadmap](../../wiki/Virtual-Scanner-Roadmap.md) | `plans/virtual_scanner.md` |
| RE glossary | [Glossary](../../wiki/Glossary.md) | (defined inline in lab docs) |

## Running the probes (live scanner over USB)

The SDS100 (and SDS200) needs to be in **Serial Mode** at the boot-time
USB connection prompt (press the **`.`** / period key). It then
enumerates **two** Uniden CDC virtual COM ports:

| PID | Role | Probe target? |
| --- | --- | --- |
| `0x0019` | SUB processor command port | **YES** - 13 single-character debug commands plus `MDL` / `VER`. |
| `0x001A` | MAIN processor command port | **YES** - this is where the Uniden Remote Command Protocol lives. |

Prerequisites:

```powershell
py -m pip install --user pyserial
```

Each probe auto-detects the right CDC by VID/PID, no hard-coded COM
number required:

```powershell
py Metacache\Dev\RE\tools\probes\list_ports.py
py Metacache\Dev\RE\tools\probes\serial_probe.py
py Metacache\Dev\RE\tools\probes\sub_probe.py
```

Override with `--port COM5` (or `/dev/ttyACM0`) if you need to.

Output goes to `Metacache/Dev/RE/sessions/<probe>_<timestamp>.txt` (and to
stdout). The `sessions/` folder is gitignored so probe captures stay
local; promote anything reproducible into `docs/` after sanitising.

## Safety contract for the probes

- **Whitelist-only.** New mnemonics may be added to
  `tools/probes/serial_probe.py`'s `QUERIES` list **only** after
  confirming in the Uniden Operation Specification that they have no
  "set" semantics.
- **Hard-coded forbidden list.** `KEY`, `PRG`, `EPG`, `JNT`, `JPM`,
  `WPL`, `WPS`, `CLR`, `DLA`, `MEMSET`, `WIPE`, `TGW`, `VLO`, `SLO`,
  `GLT`, `RST,SET` will never be sent regardless of the whitelist.
- **No `,?` -> `set` escalation.** Even if the scanner answers `OK` to
  a `cmd,?` write-test, do NOT follow up with an actual `cmd,value`
  call; that's by definition a state change.
- **Read-only by default.** Anything that can mutate the scanner, the
  SD card, or the firmware blobs MUST require an explicit
  `--allow-destructive` (or equivalent) opt-in flag.

## Adding a new scanner RE

1. Plug the scanner's SD card in. Note the drive letter, volume label,
   filesystem, and total / free size.
2. Mirror the structure of `docs/SDS100.md`:
   - Identity files and what they contain.
   - Top-level layout with sizes / counts.
   - Per-folder analysis (HPDB, favorites, discovery, audio, etc.).
   - Record-type tally for at least one large HPD file.
   - Sample raw lines for every record type. Sanitise PII.
   - Delta vs. the closest already-supported model.
   - Open questions / fields we don't yet understand.
3. **Don't paraphrase**. Paste actual file contents (truncated where
   sensible) so the next contributor can verify without the physical
   card. Strip GPS, agency names, hostnames, scanner serial numbers.
4. Cross-reference into `Metacache/Dev/MULTI_SCANNER_BACKEND.md` so the
   driver-layer plan stays accurate.

## What goes in here vs. `Metacache/docs/adding-a-scanner.md`

- `Metacache/docs/adding-a-scanner.md` (top-level) is **public-facing**
  developer documentation - generic, prescriptive, terse. Lives in
  git, ships with the project.
- `Metacache/Dev/RE/*` is the **lab notebook** - verbose, raw, includes
  sample data dumps and conjecture. Also in git so cross-machine
  syncs work, but the audience is "RE contributors" not "users
  adding a profile".

When you add a new scanner profile, both files exist - the RE doc
captures _what the scanner writes_, the public doc captures _how to
slot a profile into the codebase_.
