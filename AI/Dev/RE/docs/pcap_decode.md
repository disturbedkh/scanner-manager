# Decoding Sentinel USB Captures - Guided Walkthrough (Phase 4 cont.)

> **Canonical narrative is in the wiki**:
> [`wiki/RE-Sentinel.md`](../../../wiki/RE-Sentinel.md) and the
> "Capture a Sentinel op" recipe in
> [`wiki/RE-Workflows.md`](../../../wiki/RE-Workflows.md). This
> file is the lab notebook with the early manual walkthrough; the
> SCSI/UMS/FAT32 decoder (`_decode_sentinel_pcap.py`) supersedes
> the CDC-style decoder this doc was originally about.

> **Goal**: turn the 6 `.pcapng` captures from
> [`sentinel_capture.md`](sentinel_capture.md) into structured
> command/response data we can diff, search, and feed into Phase 5
> correlation.
>
> **Risk**: zero. Pure offline analysis. Scanner not involved.
>
> **Time required**: ~5 minutes once Wireshark is installed.

## Outputs

For each input `<name>.pcapng`, the decoder writes:

| File | Format | Contents |
|---|---|---|
| `<name>.commands.jsonl` | JSON Lines | One object per `(command, response)` pair |
| `<name>.summary.md` | Markdown | Per-device mnemonic frequency + flagged novel commands |

Each JSONL row has the form:

```json
{"ts":1.234,"device":"1.4:0x1965:0x001A","command":"GSI","head":"GSI",
 "response":"<ScannerInfo .../>","response_delay_ms":12.4}
```

## Pre-flight checklist

- [ ] You finished [`sentinel_capture.md`](sentinel_capture.md) -
      so `AI/Dev/RE/sentinel_pcaps/` exists with `.pcapng` files
- [ ] Wireshark is installed (the decoder uses `tshark.exe`
      bundled with it)
- [ ] You can run Python from the repo root

## Step 1 - Locate `tshark.exe`

The decoder auto-detects `tshark.exe` in the standard install
locations. To verify:

```powershell
where.exe tshark
# or check:
ls "C:\Program Files\Wireshark\tshark.exe"
```

If neither finds it, you can pass the path explicitly later via
`--tshark`. If Wireshark isn't installed, install it (see
[`sentinel_capture.md`](sentinel_capture.md) Step 2).

## Step 2 - Decode all captures

From the repo root:

```powershell
py AI\Dev\RE\_decode_pcap.py AI\Dev\RE\sentinel_pcaps\*.pcapng
```

The decoder will:

1. Run `tshark.exe` on each `.pcapng`, extracting USB Bulk
   transfer fields.
2. Filter to packets matching VID `0x1965` (SDS100).
3. Reassemble bytes per device per direction into ASCII lines
   split on `\r`.
4. Pair each command line with the next response line on the
   same device that arrives within 2 seconds (configurable via
   `--pair-window-ms`).
5. Write `.commands.jsonl` and `.summary.md` next to each input.

Expected output:

```
# decoding AI\Dev\RE\sentinel_pcaps\01_read_from_scanner.pcapng
  4732 bulk packets to/from SDS100
  892 command/response pairs recovered
  -> 01_read_from_scanner.commands.jsonl
  -> 01_read_from_scanner.summary.md
# decoding AI\Dev\RE\sentinel_pcaps\02_write_to_scanner.pcapng
...
```

## Step 3 - Read the summaries

Open each `<name>.summary.md`. Look for two things:

### 3a. Per-device breakdown

Each device shows top mnemonics. Two devices are expected:

| Device | VID:PID | What you should see |
|---|---|---|
| MAIN port | `1965:001A` | Many GSI/GLT/GST/MSI/STS reads and MSV writes |
| SUB port | `1965:0019` | Possibly empty, possibly U/h/MDL traffic |

If the SUB device shows up with non-trivial traffic, that's the
biggest-value section of the capture. Sentinel does talk to SUB
sometimes, but we don't know exactly when.

### 3b. Novel mnemonics

The summary's "Novel mnemonics" section lists every command head
that's NOT in the union of:

- SDS V1.02 + V2.00 specs
- BCDx36HP V1.05 spec
- Phase 1 / 1b SUB probe hits (`U`, `h`)
- Phase 2 / 3 MAIN probe hits

Anything listed here is **a Sentinel-private command** - the
primary deliverable of Phase 4.

## Step 4 - Investigate novel mnemonics

For each novel command:

1. Open the corresponding `.commands.jsonl` and grep:

   ```powershell
   Select-String -Path AI\Dev\RE\sentinel_pcaps\01_read_from_scanner.commands.jsonl `
                 -Pattern '"head":"<MNEMONIC>"' | Select-Object -First 5
   ```

2. Read the surrounding context: what command came before it?
   What response came back? Is it always paired with another
   mnemonic (suggesting a multi-step operation)?

3. Check the response shape - does it match any of the 35
   untriggered Sub firmware format strings in
   [`sub_command_response_map.md`](sub_command_response_map.md)?
   If yes, you've cracked one of those triggers.

4. Cross-reference against
   [`AI/Dev/RE/firmware_analysis/sub_1.03.15.strings.txt`](firmware_analysis/sub_1.03.15.strings.txt)
   for matching debug-print fragments.

## Step 5 - Update the catalog

For each confirmed Sentinel-private command, append a row to
[`SDS100_unofficial_commands.md`](SDS100_unofficial_commands.md):

```markdown
## Sentinel-private commands

| Mnemonic | Source | Safety | Response shape | Notes |
|---|---|---|---|---|
| `<MNEMONIC>` | Phase 4 capture #N | READ/WRITE | <observed> | <inferred semantics> |
```

Promote it to `serial_probe.py` `QUERIES` if it's read-only and
safe; otherwise add to `FORBIDDEN_FOR_READ_ONLY`.

## Step 6 - Cross-correlation (Phase 5 redux)

Re-run [`_correlate_responses.py`](_correlate_responses.py) once
the new mnemonics are in the catalog - the response-text-to-format-
string match logic will now have many more strings to chew through:

```powershell
py AI\Dev\RE\_correlate_responses.py
```

This regenerates [`sub_command_response_map.md`](sub_command_response_map.md)
with Sentinel's responses joined into the format-string table.
Untriggered-format-string count should drop noticeably.

## Troubleshooting

**`tshark.exe not found`**
- Install Wireshark, or pass `--tshark "C:\path\to\tshark.exe"`.

**Decoder runs but produces 0 pairs**
- The pcap was captured on the wrong USBPcapN interface and
  contains zero SDS100 traffic. Re-capture per
  [`sentinel_capture.md`](sentinel_capture.md) Step 3.

**Pairs are misaligned (responses don't match commands)**
- Increase `--pair-window-ms` to e.g. 5000 if the scanner is
  slow on long XML responses.
- Or reduce it to e.g. 500 if very rapid command/response
  pairs are getting cross-paired.

**JSONL is huge**
- That's expected. Each capture can have thousands of pairs.
  Use `Get-Content ... | Select-String` or `jq` for filtering.

**Novel mnemonic list shows commands that ARE in the spec**
- The decoder's `KNOWN_HEADS` set may be stale. Edit it in
  `_decode_pcap.py` to add missing heads, then re-run.

## Decoder design notes

- **Why tshark not pyshark**: pyshark wraps tshark anyway and is
  flaky on Windows. Calling tshark directly via subprocess is
  faster, simpler, and doesn't add a Python dependency.
- **Why ASCII reassembly with `\r` split**: the SDS100 uses a
  line-oriented ASCII protocol. The only exception is `GCS` which
  uses `\n`; if Sentinel ever uses `GCS` we'd need to special-case
  that head, but in practice `GCS` ERR'd on FW 1.26.01 so Sentinel
  probably doesn't use it.
- **Why per-device pairing**: a single pcap can contain BOTH MAIN
  and SUB traffic. Pairing by device key prevents cross-port
  confusion (e.g. an MDL on MAIN getting paired with an SDS100-SUB
  reply on SUB).

## What's next

After Phase 4 decode:

1. Phase 5 cross-correlation rerun (Step 6 above).
2. Targeted SUB re-probe with any newly-discovered SUB-port
   commands added to `sub_probe.py` `VALIDATED_SUB_READS`.
3. Phase 6.2 Ghidra import (see
   [`ghidra_import_runbook.md`](ghidra_import_runbook.md)) -
   the dispatch table can be confirmed against Sentinel's
   actual command usage.
