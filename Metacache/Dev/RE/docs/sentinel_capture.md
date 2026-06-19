# Sentinel USB Traffic Capture - Guided Walkthrough (Phase 4)

> **Canonical narrative is in the wiki**:
> [`wiki/RE-Sentinel.md`](../../../wiki/RE-Sentinel.md) and the
> "Capture a Sentinel op" recipe in
> [`wiki/RE-Workflows.md`](../../../wiki/RE-Workflows.md).

> **RECOMMENDED PATH (automated):** run
> `py Metacache\Dev\RE\_sentinel_session.py` and follow the prompts. It
> auto-detects the USBPcap interface, drives `dumpcap.exe` for each
> of the six operations, and (optionally) decodes the resulting
> `.pcapng` files immediately. See [`AUTOMATION.md`](AUTOMATION.md).
> The manual Wireshark walkthrough below is the fallback for when
> you want a click-through workflow or need to inspect the captures
> live in Wireshark.
>
> **Goal**: capture every byte Sentinel exchanges with the SDS100 over
> USB during 6 standard operations, so we can recover Sentinel's
> private (non-spec) command vocabulary and confirm the SD-card
> firmware update theory.
>
> **Risk**: zero. USBPcap is a passive kernel-mode snooper. Sentinel
> and the scanner cannot detect it. The scanner is in the same serial
> mode our Phase 1-3 probes already used safely.
>
> **Time required**: ~1.5 hours hands-on. Most of it is waiting for
> Sentinel to read/write/update.

## What you'll produce

By the end of this walkthrough, the directory
`Metacache/Dev/RE/sentinel_pcaps/` will contain:

| File | Source operation |
|---|---|
| `01_read_from_scanner.pcapng` | Sentinel "Read From Scanner" |
| `02_write_to_scanner.pcapng` | Sentinel "Write to Scanner" |
| `03_hpdb_update.pcapng` | Sentinel "Get HPDB Update" |
| `04_firmware_update.pcapng` | Sentinel "Update Firmware" |
| `05_backup.pcapng` | Sentinel "Backup" |
| `06_restore.pcapng` | Sentinel "Restore" |

The decoder script (`_decode_pcap.py`, separate guide) will then
turn these into JSONL command/response pairs.

## Background context

The SDS100 exposes two USB CDC virtual COM ports. Both run the same
ASCII Remote Command Protocol but route to different MCUs:

| Port | VID:PID | MCU | Visible at |
|---|---|---|---|
| MAIN | `1965:001A` | STM32 (encrypted firmware) | COM4 here |
| SUB | `1965:0019` | NXP LPC43xx (plaintext firmware) | COM3 here |

Sentinel almost certainly talks to **both**. The MAIN port carries
documented commands (GSI, GLT, etc.) plus Sentinel's private `.hpe`
config-dump commands. The SUB port traffic is what we're most
curious about - we have only sparse coverage of it from Phase 1.

## Pre-flight checklist

Before you start, verify all of these:

- [ ] SDS100 is connected via USB and powered on
- [ ] You can see two SDS100 entries in Device Manager under
      "Ports (COM & LPT)" - one PID 0019 and one PID 001A
- [ ] Sentinel is installed and you've successfully done at least
      one Read-From-Scanner cycle in the past
- [ ] You have ~5 GB free disk for the pcaps and logs
- [ ] You can run installers as Administrator (USBPcap needs admin)

If any are missing, fix those first.

## Step 1 - Install USBPcap (one-time)

> Skip this step if you've already installed USBPcap. Verify by
> looking for `C:\Program Files\USBPcap\USBPcapCMD.exe`.

1. Download the bundled installer:
   <https://desowin.org/usbpcap/>
2. Right-click the `.exe` -> **Run as administrator**.
3. Default settings are fine. Accept the GPL license.
4. **Reboot when prompted.** The kernel driver only loads after
   a reboot.

## Step 2 - Install Wireshark (one-time)

> Skip if Wireshark is already installed.

1. <https://www.wireshark.org/download.html> -> Windows installer.
2. Run as administrator. Accept defaults.
3. When the installer asks "Install USBPcap?", check the box if
   you skipped Step 1; otherwise leave unchecked.
4. **No reboot needed** for Wireshark itself.

## Step 3 - Identify the SDS100's USBPcap interface

Done once per session.

1. Plug the SDS100 in and power it on.
2. Open Wireshark.
3. On the welcome screen, look for `USBPcapN` interfaces (USBPcap1,
   USBPcap2, etc.). Each is a separate USB root hub.
4. Click the gear icon next to each `USBPcapN`. A "Capture
   Interfaces" dialog opens listing the devices on that hub.
5. Find the hub that lists **both**:
   - `Vendor 1965 Product 0019`
   - `Vendor 1965 Product 001A`

   That's your scanner's hub. **Write down the USBPcapN number.**
   Example: USBPcap2.
6. Close the dialog.

> Tip: the SDS100's PID `0x0019` and `0x001A` are unique enough
> that searching the dialog text usually finds them instantly.
> If you only see one of the two, the other isn't enumerating;
> unplug, wait 5 seconds, and replug.

## Step 4 - Verify capture works (sanity check)

1. In Wireshark, double-click the `USBPcapN` interface from Step 3
   to start capturing.
2. Open Sentinel.
3. In Sentinel, click any **read** action that talks to the scanner
   (e.g. open the "Manage Scanner" / "Read From Scanner" pane and
   trigger an info read).
4. Watch Wireshark. You should immediately see USB Bulk-OUT
   transfers and Bulk-IN responses.

Filter test:

```
usb.transfer_type == 0x03
```

If you see ASCII bytes like `MDL\r` and `SDS100\r` in the packet
bytes pane, capture is working.

5. Stop the capture (red square button or **Ctrl+E**).
6. **Discard** this sanity capture - don't save it. We just wanted
   to confirm the interface.

If you saw nothing in step 3, the wrong USBPcapN was selected.
Go back to Step 3.

## Step 5 - Capture each of the 6 operations

For each operation in the table below, repeat this 4-step ritual:

1. **Wireshark**: File -> Close (clear previous capture).
   Capture -> Options -> select USBPcapN. Click Start.
2. **Sentinel**: trigger the operation. Wait for it to complete.
3. **Wireshark**: stop capture (Ctrl+E).
4. **Wireshark**: File -> Save As ->
   `<repo>\Metacache\Dev\RE\sentinel_pcaps\<NN_name>.pcapng`.

> Make the directory first:
> `mkdir Metacache\Dev\RE\sentinel_pcaps` (or use Explorer).

| # | Filename | Sentinel action | What we expect to see | Notes |
|---|---|---|---|---|
| 1 | `01_read_from_scanner.pcapng` | Manage Scanner -> **Read From Scanner** | Many MAIN-port reads (GSI, GLT,*, MSI), private `.hpe` commands, possibly SUB-port reads | Highest-yield capture. Let the read finish completely before stopping. |
| 2 | `02_write_to_scanner.pcapng` | Manage Scanner -> **Write to Scanner** (use the same data already loaded) | Many MAIN-port writes (MSV, MNU navigation), confirms which write commands Sentinel uses | If you don't have a config to write, skip - or read first then write back. |
| 3 | `03_hpdb_update.pcapng` | Tools / Database -> **Get HPDB Update** | Probably very little USB traffic; HPDB is an SD-card delivery per our theory | If the operation just dumps a file to the card without scanner contact, the pcap will be small. That's the expected result. |
| 4 | `04_firmware_update.pcapng` | Help / About -> **Update Firmware** (or whatever the menu path is in your Sentinel version) | Very little or zero USB traffic - confirms the SD-card-only firmware update path | **Only run this if you actually want a firmware update applied.** Otherwise, skip and capture next time you legitimately update. |
| 5 | `05_backup.pcapng` | File -> **Backup** | Heavy reads of model, version, full config | The "read everything to a local file" workflow. Likely overlaps significantly with #1. |
| 6 | `06_restore.pcapng` | File -> **Restore** | Heavy writes of full config back to the scanner | The mirror of Backup. Likely overlaps significantly with #2. |

> Optional: also save `00_sanity.pcapng` from Step 4 - it's a small
> baseline of "what does idle Sentinel look like" that's useful as
> a control.

## Step 6 - Hand off to the decoder

When all the pcaps are in `Metacache/Dev/RE/sentinel_pcaps/`, run:

```powershell
py Metacache\Dev\RE\_decode_pcap.py Metacache\Dev\RE\sentinel_pcaps\*.pcapng
```

(See [`pcap_decode.md`](pcap_decode.md) for the decoder runbook.)
The decoder produces:

- `<filename>.commands.jsonl` - one JSON object per
  `(command, response)` pair.
- `<filename>.summary.md` - human-readable per-operation summary
  with mnemonic frequency and any never-before-seen commands
  flagged.

## Step 7 - Update the catalog

Manually copy any **new** mnemonics found by the decoder into
[`SDS100_unofficial_commands.md`](SDS100_unofficial_commands.md)
under the appropriate section. Cross-reference each against:

- The SDS V1.02 + V2.00 spec
- The BCDx36HP V1.05 spec
- Phase 1 (`sub_probe`) hits
- Phase 2/3 (`serial_probe`) hits

Anything not in any of those lists is a **Sentinel-private command**
and is the highest-value finding from this phase.

## Troubleshooting

**Wireshark doesn't show any USBPcapN interfaces**
- USBPcap driver not loaded. Reboot. If still missing, reinstall
  USBPcap as admin.

**Wireshark capture starts but no SDS100 traffic appears**
- Wrong USBPcapN. Go back to Step 3.
- Sentinel isn't actually talking to the scanner (it cached
  results). Click a forced-refresh action.

**`Permission denied` opening pcaps later**
- Wireshark may have left the file locked. Close Wireshark before
  running the decoder.

**Sentinel hangs when opening with USBPcap running**
- USBPcap doesn't typically interfere, but some antivirus tools
  flag it. Whitelist `USBPcapCMD.exe` and the kernel driver.

**Captures are huge (multi-GB)**
- You captured on the wrong USBPcapN that has lots of other
  devices. Re-do Step 3, narrow to the correct hub.

## Risk reminder

| Risk | Likelihood | Mitigation |
|---|---|---|
| USBPcap install requires admin / reboot | Certain | Plan for it |
| Sentinel detects packet capture | Negligible | USBPcap is transparent at kernel level |
| Capture file too large | Low | Per-operation captures keep them under 50 MB |
| Wrong USBPcapN -> empty capture | Medium | Step 4 sanity check |
| Capturing causes destructive scanner action | **Zero** | Capture is passive observation only |

## When to do this

This phase requires:
- ~5 minutes for one-time installs (Steps 1-2)
- ~10 minutes for per-session interface ID + sanity check (Steps 3-4)
- ~1.5 hours for the 6 capture operations (Step 5)

The next time you'd do a normal Sentinel firmware update, run
USBPcap simultaneously and you'll get capture #4 for free.
