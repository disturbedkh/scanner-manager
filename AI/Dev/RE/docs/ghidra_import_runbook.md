# Ghidra Import - Guided Walkthrough (Phase 6.2)

> **Canonical narrative is in the wiki**:
> [`wiki/RE-Workflows.md`](../../../wiki/RE-Workflows.md) "Decompile
> a SUB function" recipe. This file is the lab notebook with the
> original manual walkthrough.

> **RECOMMENDED PATH (automated):** see [`AUTOMATION.md`](AUTOMATION.md).
> Two PowerShell commands install Ghidra and produce
> `firmware/analysis_dump.json` end-to-end. The manual walkthrough
> below is preserved as a fallback for when you want to do RE
> interactively in the GUI, or as a reference for what each
> automated step is doing under the hood.
>
> **Goal**: load the extracted Sub firmware payload into Ghidra
> with proper architecture, base address, memory map, and peripheral
> overlays so we can identify the SUB-port command dispatch table
> and the inter-MCU bus protocol.
>
> **Risk**: zero. Static analysis only. Scanner not involved.
>
> **Time required**:
> - 2-4 hours for one-time setup + import (Steps 1-5)
> - 4-12 hours for dispatch identification (Step 6)
> - 8-16 hours for handler-to-format-string mapping (Step 7)
> - 4-12 hours for inter-MCU bus RE (Step 8)
>
> Total: **20-50 hours of focused work**, typically spread over
> 2-4 weeks at 1-2 hours per session.

## What you'll produce

By the end of this walkthrough you'll have:

| Artifact | Format | Purpose |
|---|---|---|
| `AI/Dev/RE/firmware/SDS100_SUB.gpr` | Ghidra project | Live RE workspace |
| `AI/Dev/RE/sub_command_dispatch.md` | Markdown | Every recognized SUB mnemonic + handler address |
| `AI/Dev/RE/SDS100_inter_mcu_protocol.md` | Markdown | Wire-format of MAIN <-> SUB bus |
| Updated [`SDS100_firmware.md`](SDS100_firmware.md) | Markdown | Full disassembly summary |

## Pre-flight checklist

- [ ] Phase 6.1 complete - file
      `AI/Dev/RE/firmware/sub_1.03.15_inflated.bin` exists and is
      90,076 bytes
- [ ] [`firmware/sub_1.03.15_chunk_map.md`](firmware/sub_1.03.15_chunk_map.md)
      exists (documents reset vector at `0x140001D5`, SP at
      `0x10020000`)
- [ ] [`sub_static_analysis.md`](sub_static_analysis.md) exists
      (peripheral constant scan results - UART1 + SSP0 are top
      candidates for inter-MCU bus)
- [ ] You have ~10 GB free disk for Ghidra project + SVD files
- [ ] You can install Java 17 if not already present

## Step 1 - Install Ghidra (one-time)

> Skip if you already have Ghidra 11.x or later.

1. Confirm Java 17+ is installed:

   ```powershell
   java -version
   ```

   If older, install OpenJDK 17 from <https://adoptium.net/>.

2. Download Ghidra 11.x: <https://ghidra-sre.org/>
   - The release ZIP is large (~400 MB) but no installer required.
3. Extract to e.g. `C:\Tools\ghidra_11.x_PUBLIC\`.
4. Launch with `ghidraRun.bat` from that folder.
5. **Verify** the splash screen says "Ghidra 11.x" and the main
   window opens.

## Step 2 - Install the SVD-Loader plugin (one-time)

The SDS100 SUB MCU is an NXP LPC43xx. Loading its SVD (System
View Description) file teaches Ghidra the names and locations of
every memory-mapped peripheral register, so disassembly shows
`USART1_DLL` instead of `[0x40081000]`.

1. Download the SVD-Loader extension:
   <https://github.com/leveldown-security/SVD-Loader-Ghidra/releases>
   Pick the build matching your Ghidra version.
2. In Ghidra: File -> Install Extensions -> green "+" -> select
   the downloaded `.zip`.
3. Restart Ghidra when prompted.
4. **Verify** under Window -> Script Manager that
   `SVD-Loader-Ghidra` appears.

## Step 3 - Get the LPC43xx SVD file (one-time)

1. Go to <https://github.com/posborne/cmsis-svd>
   -> `data/NXP/`.
2. Download `LPC43xx.svd` (or `LPC4350_4350.svd` if you want a
   variant-specific file). Save to
   `AI/Dev/RE/firmware/LPC43xx.svd`.

> Note: the LPC4350 vs LPC4357 distinction is mostly about
> integrated flash size, which doesn't matter here because the
> SDS100 boots from external SPIFI flash. Either SVD will work.

## Step 4 - Create project + import binary

1. Ghidra: **File -> New Project** -> Non-Shared Project.
2. Name it `SDS100_SUB`. Save under
   `AI\Dev\RE\firmware\SDS100_SUB\` (Ghidra creates a folder for
   project files).
3. **File -> Import File** -> select
   `AI\Dev\RE\firmware\sub_1.03.15_inflated.bin`.
4. In the import dialog:
   - **Format**: `Raw Binary`
   - **Language**: click `...` -> filter "Cortex" -> select
     `ARM:LE:32:Cortex` (little-endian, Thumb-capable Cortex-M3/M4)
   - Click **Options...**:
     - **Block Name**: `flash`
     - **Base Address**: `0x14000000`
     - Leave "File offset" at 0
   - Click OK twice.
5. **Verify** in the Project window: a single program named
   `sub_1.03.15_inflated.bin` (or similar) appears, with a small
   icon indicating successful import.
6. **Double-click** the program to open the CodeBrowser.

## Step 5 - Define the memory map

The flat binary only covers `0x14000000-0x14016080`. The firmware
references SRAM, peripherals, and NVIC. Adding empty memory blocks
for those regions makes cross-references resolve cleanly.

In CodeBrowser: **Window -> Memory Map** -> green "+" for each row:

| Name | Start | Length | R | W | X | Volatile | Initialized |
|---|---|---|---|---|---|---|---|
| `sram_loc0` | `0x10000000` | `0x20000` | yes | yes | yes | no | **no** |
| `sram_loc1` | `0x10080000` | `0x12000` | yes | yes | yes | no | **no** |
| `sram_ahb` | `0x20000000` | `0x10000` | yes | yes | no | no | **no** |
| `peripherals` | `0x40000000` | `0x100000` | yes | yes | no | **yes** | **no** |
| `nvic` | `0xE0000000` | `0x100000` | yes | yes | no | **yes** | **no** |

**Critical**: keep "Initialized" unchecked. We don't have content
for these regions; they exist only as valid pointer targets.

**Verify**: the Memory Map window now shows 6 blocks (the original
`flash` plus the 5 you just added).

## Step 6 - Apply the SVD overlay

1. Window -> Script Manager.
2. Find `SVD-Loader-Ghidra` -> Run Script.
3. Browse to `AI\Dev\RE\firmware\LPC43xx.svd` -> OK.
4. Wait ~30 seconds for the import.
5. **Verify** Window -> Memory Map now shows lots of small named
   blocks like `USART0`, `USART1`, `SSP0`, `I2C0`, `ADC0`, etc.,
   inside the `peripherals` region.

## Step 7 - Set entry point and disassemble

The reset vector says PC = `0x140001D5` (Thumb bit set ->
actual instruction at `0x140001D4`).

1. **Navigation -> Go To...** (or G key) -> `0x140001d4`.
2. Right-click that address -> **Disassemble** (or D key).
3. The disassembly should immediately show valid Thumb-2
   instructions. If you see ARM-32 nonsense, the Thumb bit is
   missing - press D again with the address `0x140001d5` (Ghidra
   accepts the Thumb bit as a hint).
4. Tools -> Analysis -> **Auto Analyze**. Accept the defaults
   plus enable:
   - **Embedded Media** (string detection)
   - **ARM Constant Reference Analyzer**
   - **Stack** analysis
   - **Decompiler Switch Analysis**

   Click **Analyze**. Expect 5-15 minutes wall time.

5. **Verify**: the Symbol Tree should now show many functions and
   strings discovered. Functions tab should have hundreds of
   entries; Strings tab should include `MDL`, `VER`, `R840_FM`,
   `Noise Squelch,%6d`, etc.

## Step 8 - Identify the command dispatch table

This is where the real RE work begins. The goal: find the routine
that maps incoming command strings to handler functions.

### 8a. Locate `MDL` references

1. Symbol Tree -> Strings -> filter `MDL`. There should be
   exactly one match (`MDL\0` or `MDL,?`-related).
2. Right-click that string entry -> **References -> Show
   References to Address**.
3. Each xref points to code that uses the string. There should
   be 1-3 xrefs.

### 8b. Decompile the user

1. Double-click an xref entry to navigate.
2. Press **F5** to open the Decompiler view.
3. The function calling `MDL`'s reference is the dispatch lookup.

### 8c. Recognize the dispatch pattern

Common patterns:

| Pattern | Look for | Implication |
|---|---|---|
| **Linear `strcmp` chain** | A series of `strcmp(input, "MDL")`, `strcmp(input, "VER")`, ... each followed by `if (==0) handler()` | Easiest to enumerate; just walk the chain. |
| **Sorted binary search** | Single `bsearch` call against a sorted `(string, fn)` table | Find the table base in the literal pool. |
| **First-character switch** | A `switch (input[0])` with cases for each prefix letter | Each case has its own sub-dispatch; enumerate per-character. |
| **Hash-indexed lookup** | An expression like `table[hash(input) % N]` | Reverse the hash to enumerate, or grep the table for ASCII strings. |

### 8d. Enumerate every handler

For each entry in the dispatch:

1. Note the command string (the literal in the comparison).
2. Note the handler function address (the called function).
3. Rename the handler in Ghidra to `handler_<command>` for
   readability.
4. Append a row to `AI/Dev/RE/sub_command_dispatch.md`:

   ```markdown
   | Command | Handler | Notes |
   |---|---|---|
   | `MDL` | `0x140012F4` | Returns SDS100-SUB identity |
   | `VER` | `0x140013A0` | Returns Version 1.03.15 string |
   ...
   ```

**Verify**: every command found in
[`SDS100_unofficial_commands.md`](SDS100_unofficial_commands.md)
SUB-port section should appear in the dispatch. Plus all 35
"untriggered format string" hypothesis targets should map to
handlers - if any don't, that's evidence of dead code.

## Step 9 - Map handlers to format strings

For each handler identified in Step 8:

1. Decompile the handler (F5).
2. Look for calls to `printf`/`sprintf`/`fprintf`-like functions.
   They typically take a format string in r0 and varargs.
3. The first argument is a pointer into the strings region. Click
   it - Ghidra shows the format string as a comment.
4. Cross-reference against
   [`sub_command_response_map.md`](sub_command_response_map.md)'s
   "Untriggered format strings" section. Each format string you
   match here is a SOLVED hypothesis target - update the table
   with the now-known trigger command.

**Verify**: ideally all 35 untriggered format strings get
matched to a handler. Realistic outcome: 20-30 will match (some
format strings are in dead/disabled code paths).

## Step 10 - Inter-MCU bus protocol RE

The static analysis hints UART1 and SSP0 each have ~6 register
references, making them the prime candidates. With Ghidra's
SVD-decoded labels, this becomes tractable.

### 10a. Find UART1 / SSP0 init

1. Window -> References Browser. Search for references to
   `UART1_LCR` (or whichever LCR equivalent the SVD names) -
   that's the line-control init register.
2. The function writing it is `uart1_init`. Decompile it. Read
   off the configured baud rate (from `DLL`/`DLM`), word length,
   parity, stop bits.

### 10b. Find the RX path

1. Find references to `UART1_RBR` (Read Buffer Register) or
   `UART1_IER` (Interrupt Enable Register set with RX bit).
2. The interrupt handler will be in the vector table at
   `0x14000000` + offset for UART1's IRQ. Decompile it.
3. Trace what it does with received bytes:
   - Stored to a ring buffer? Then look for the consumer.
   - Parsed inline? Decode the parser - this IS the inter-MCU
     protocol parser.

### 10c. Find the TX path

1. Find writes to `UART1_THR` (Transmit Holding Register).
2. Backtrack to the function building the TX frame.
3. Note: byte 0 = sync? bytes 1-2 = command code? bytes 3+ =
   payload? last byte = checksum/CRC?

### 10d. Document the wire format

Write findings to `AI/Dev/RE/SDS100_inter_mcu_protocol.md`:

```markdown
# SDS100 inter-MCU bus protocol

- Bus: UART1 (or SSP0 if that's the conclusion)
- Baud: <decoded>
- Word: 8N1 (typical)
- Frame:
  - Byte 0: sync byte 0xXX
  - Bytes 1-2: little-endian command code
  - Bytes 3-N-1: payload
  - Byte N: checksum / CRC

## Known command codes
- 0xXXXX: <inferred meaning>
- ...
```

## Step 11 - Update SDS100_firmware.md

Append a new section "Full Sub disassembly results" summarizing:

- Total functions found
- Total static strings catalogued
- Dispatch table location and shape
- Inter-MCU bus characterization
- A handful of handler highlights

## Verification checkpoints

After each major step you should have a way to confirm progress:

| After step | Quick check | Expected result |
|---|---|---|
| 4 (import) | Memory Map shows 1 block named `flash` at `0x14000000` | OK if length is `0x16080` |
| 5 (memory map) | Memory Map shows 6 blocks | OK |
| 6 (SVD) | Memory Map shows lots of named peripheral blocks | UART0..3, SSP0..1, ADC0..1, USB0, etc. all visible |
| 7 (analyze) | Symbol Tree -> Functions has hundreds of entries | OK if includes `_start` near `0x140001d4` |
| 8 (dispatch) | `sub_command_dispatch.md` has at least 5 entries | MDL + VER at minimum |
| 9 (formats) | At least 50% of the 35 untriggered format strings now have a known trigger command | Stretch goal |
| 10 (bus) | `SDS100_inter_mcu_protocol.md` has a frame definition | Even partial is enough to share |

## Troubleshooting

**`MDL` string isn't in the Strings tab**
- Auto-analysis didn't pick up short strings. Manually navigate
  to a known offset (search the binary file for "MDL" - it's
  somewhere in the `0x140xxxx` range), select 4 bytes,
  right-click -> Data -> string.

**Decompiler shows garbage code**
- The function wasn't disassembled in Thumb mode. Set the address
  to Thumb (right-click -> Processor Options or Set Register
  Values, set TMode = 1).

**No xrefs to peripheral registers despite SVD load**
- The SVD overlay may not have created memory blocks for the
  exact addresses your code accesses. Check Memory Map; if a
  register address is in an "uninitialized peripheral region",
  Ghidra still shows xrefs but as raw addresses.

**Project file is huge / slow to open**
- That's normal for a fully-analyzed firmware. Backup the .gpr
  before making major changes (Ghidra has built-in version
  control if you enable it).

**Auto-analysis hangs**
- Disable Decompiler Switch Analysis if it's stuck in a loop.
  Re-run Auto Analyze without it.

## Status (snapshot)

- **Phase 6.1** (extract payload): ✅ COMPLETE -
  `firmware/sub_1.03.15_inflated.bin` ready to import
- **Phase 6.2** (Ghidra import): ⏳ NOT STARTED - this runbook
- **Phase 6.3** (dispatch enumeration): ⚠️ PARTIAL -
  static-analysis pass in
  [`_sub_static_analysis.py`](_sub_static_analysis.py) found 45
  candidate mnemonics + 31 clusters but no clear table; needs
  Ghidra to confirm
- **Phase 6.4** (inter-MCU bus): ⚠️ PARTIAL - peripheral constant
  scan flags UART1 and SSP0 as top candidates; Ghidra disambiguates
- **Phase 6.5** (handler docs): ⏳ NOT STARTED - depends on 6.2-6.4
