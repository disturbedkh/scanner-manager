# Uniden firmware inventory + RE goodies hunt - 2026-05-03

> **Sister doc**: [`uniden_update_endpoints.md`](uniden_update_endpoints.md)
> covers the FTP servers themselves and how Sentinel / BT885 Update
> Manager use them. This doc is the deeper inventory: what's on the
> servers besides the canonical updates, what's encrypted vs
> plaintext, and what's RE-actionable.

> Goal: answer the question "is there anything on Uniden's update
> servers we can use to bypass MAIN-MCU encryption, find beta
> firmware, or pull useful goodies for the RE wiki?"

> **TL;DR**: One real win (BC-WF1 Wi-Fi adapter is fully plaintext
> Cortex-M3 + WiCED), one near-miss (HomePatrol-1 firmware is in SREC
> transport but the application content is still Uniden-obfuscated),
> and confirmation that BCDx36HP MAIN encryption has been bulletproof
> from day one (2014). No betas, no SDS100-compatible plaintext
> variant.

## FTP server topology (full)

The canonical update doc only covers the user-facing paths. Here's
the complete topology our credentials can see:

| Server | Path | Access | Contents |
| --- | --- | --- | --- |
| `ftp.homepatrol.com` | `/BCDx36HP/` | enter+list+RETR | All BCDx36HP-family firmware + HPDB + Sentinel installer (`uniden_update_endpoints.md`) |
| `ftp.homepatrol.com` | `/BCDx36HP/archive/` | enter+list+RETR | Older Sentinel installers (downgrade archive) |
| `ftp.homepatrol.com` | `/Extreme/` | enter+list+RETR | HomePatrol-1 firmware (`.scn`), HomePatrol-1 HPDB (~10 MB), one stray `UBCD436-PT_V1_06_02C.bin` |
| `ftp.homepatrol.com` | `/HomePatrol/Test/` | enter+list+RETR | 4 very old MasterHpdb blobs (Dec 2010 - Sep 2011) |
| `ftp.homepatrol.com` | `/HomePatrol/Updater/` | enter+list+RETR | 2 HomePatrol-1 firmware files + 2011 weekly HPDBs + the original `Sentinel_V2_02_04.app` marker |
| `ftp.uniden.com` | `/BT885/` | enter+list+RETR | BT885 HPDB only (`uniden_update_endpoints.md`) |
| `ftp.uniden.com` | `/internal/` | **list root only, 550 on enter** | unknown - access-denied |
| `ftp.uniden.com` | `/uaceng/` | **list root only, 550 on enter** | unknown - probably "Uniden Australia/Canada Engineering" |
| `ftp.uniden.com` | `/ujeng/` | **list root only, 550 on enter** | unknown - probably "Uniden Japan Engineering" |
| `ftp.uniden.com` | `/updates/` | **list root only, 550 on enter** | unknown - generic engineering staging |

Notes:

- The `homepatrolftp` user is **not** chrooted: it sees the FTP root
  on both servers, and the unprivileged `BT885ftp2` user only sees
  `/BT885/` on `ftp.uniden.com`. So the `homepatrolftp` user has
  slightly elevated metadata visibility on `ftp.uniden.com`, but
  CWD/ACL restrictions block actual entry into the engineering dirs.
  Not a privilege escalation - just metadata leakage.
- The 4 hidden engineering dirs are interesting future-watch targets;
  if Uniden ever loosens the ACL, content could become readable. We
  do **not** attempt to brute-force or otherwise bypass.

## What's encrypted vs plaintext

We pulled a representative subset (19 blobs spanning 2014-2026, all
model lines) and measured Shannon entropy + ASCII printable ratio +
cross-pair byte diff.

| Family / artefact | Sample versions | Entropy | Status |
| --- | --- | ---: | --- |
| **BCDx36HP MAIN** (BCD436HP, BCD536HP) | 2014 oldest -> 2025 latest | 7.9999 | encrypted from day one |
| **SDS-100 / SDS200 MAIN** | 2018 launch -> 2026 latest | 7.9999 | encrypted from day one |
| **Government / fleet variants** (UBCD3600XLT, UBCD436-PT, UBCD536-PT, USDS100) | 2016 oldest -> 2025 latest | 7.9999 | encrypted, same scheme as civilian |
| **EU variants** (SDS100E, SDS200E) | 2019 onward | 7.9999 | encrypted, same scheme |
| **`UBCD436-PT_V1_06_02C.bin`** (the lone "C" variant in `/Extreme/`) | 2016 | 7.9999 | encrypted, no special properties; just an internal patch release |
| **MAIN SUB firmware** (`.firm`) | 2018 oldest -> 2025 latest | 7.18 | **plaintext** (already known; ARM Cortex-M4 / NXP LPC43xx) |
| **BC-WF1 Wi-Fi adapter** | V7.28 (2015) | 3.54 | **plaintext** (Cortex-M3 + WiCED + BCM43362) |
| **HomePatrol-1** (`.scn`) | V2_04_01, V2_06_02, V2_06_06 | 4.02 raw / 7.43 decoded | **SREC transport, but application is Uniden-obfuscated** |

### Cross-version byte diff (encrypted MAIN firmware)

Every pair we tested (same model different versions, same version
different models, civilian vs government, oldest vs newest) showed
**~99.6% diff**. That's exactly what you'd expect from a stream
cipher with random IV: a one-byte change in plaintext causes
completely uncorrelated ciphertext.

```
SDS-100_V1_26_01.bin     vs SDS200_V1_26_01.bin             diff = 99.614%   (same date, same family)
SDS-100_V1_23_07.bin     vs SDS-100_V1_26_01.bin            diff = 99.609%   (consecutive versions)
SDS-100_V1_02_02.bin     vs SDS-100_V1_07_04.bin            diff = 99.605%   (5 versions apart)
UBCD436-PT_V1_28_24.bin  vs UBCD3600XLT_V1_28_24.bin        diff = 99.689%   (same version, different govt variants)
UBCD3600XLT_V1_02_00.bin vs BCD436HP_V1_03_00.bin           diff = 99.611%   (govt vs civilian, same era)
USDS100_V1_23_15.bin     vs SDS-100_V1_23_07.bin            diff = 99.584%   (govt-export vs civilian)
BCD436HP_V1_03_00.bin    vs BCD536HP_V1_02_03.bin           diff = 99.606%   (handheld vs base, oldest both)
```

### Chunked entropy (looking for non-encrypted regions)

Per-64KB-chunk entropy across multiple MAIN firmwares stayed in the
range **7.9965-7.9978 for every single chunk** of every single file.
No header section, no footer section, no padding gaps - the
encryption fills all 2,162,688 bytes uniformly. There is **no
unencrypted bootloader / version header / signature region** to
exploit.

### Conclusion on MAIN encryption

- Stream cipher (or randomized-IV block cipher) with per-build IV.
- No structural weakness across 12+ years and 20+ products.
- No exploitable plaintext segments.
- No "older version was plaintext" loophole - the encryption
  predates BCDx36HP and was already mature when the BCD436HP/536HP
  launched in 2014.
- Static RE of MAIN remains infeasible. (Already documented in
  [RE-Firmware](../../../wiki/RE-Firmware.md); this analysis just
  closes off the "maybe an older variant is plaintext" hypothesis.)

## BC-WF1 Wi-Fi adapter - the actionable RE win

`ftp://ftp.homepatrol.com/BCDx36HP/BC-WF1_V7_28.bin` is a 992 KB,
**fully plaintext** firmware blob with all its build identifiers,
debug strings, and library headers preserved.

### Architecture

| Layer | What it is |
| --- | --- |
| Host MCU | **STM32** (likely STM32F2xx / F4xx) acting as USB device + SDIO host bridge to the WiFi chip |
| WiFi SoC | **Broadcom BCM43362** (802.11b/g/n) over SDIO from the STM32 |
| RTOS / TCP/IP | **Express Logic NetX** Cortex-M3/GNU `Version G5.4.5.0`, license `SN: 23451-108-0509` |
| WiFi stack | **WiCED SDK** (formerly Broadcom, now Cypress / Infineon) |
| WLAN firmware blob | `43362a2-roml/sdio-p2p-idsup-idauth-pno Version: 5.90.230.7 CRC: 218e2282 Date: Mon 2014-02-10 11:30:12 EST FWID 01-555f783e` |

### USB topology

The BC-WF1 enumerates as a **USB CDC ACM virtual COM port** to the
scanner. Strings include:

```
STM32 Virtual ComPort in FS Mode
STM32 Virtual ComPort in HS mode
%s: Broadcom SDPCMD CDC driver
sdpcmdcdc%d
VCP Config
```

So the SDS100 (and any BCDx36HP scanner) talks to the BC-WF1 using
**plain USB CDC** - the same surface as serial mode - over which
WiFi-streamed audio and control flow. **This is RE-able with USBPcap**
the same way we captured Sentinel's mass-storage traffic.

### Module identification

The first 16 bytes of the firmware contain `WMNBM14-SEUC1` which is
the **module / board ID**. Common Broadcom-WiCED modules with this
naming pattern are made by Murata (the "WM" prefix is a Murata
convention; "BM" is Broadcom-module). Cross-referencing the BCM43362
+ "SEUC" suffix points strongly at a **Murata-made WiCED module**
shipped under Broadcom's reference design - probably the **Murata
SN8000** or close cousin.

### Default-AP / WPS setup mode

```
WiCED_Default_AP                    <-- the SSID broadcast in setup mode
WFA-SimpleConfig-Enrollee-1-0       <-- WPS enrollee role
WFA-SimpleConfig-Registrar-1-0      <-- WPS registrar role
Wi-Fi Easy and Secure Key Derivation
```

When first plugged in, the BC-WF1 likely comes up as a soft-AP
broadcasting `WiCED_Default_AP` and lets the user configure their
home SSID via WPS or a captive-portal flow.

### Network stack capabilities

```
NetX BSD TCP Socket / NetX BSD UDP Socket / NetX BSD Block Pool /
NetX BSD Events / NetX BSD Protection Mutex / NetX DHCP Client /
WICED DHCP Client / DHCPserver
```

So the BC-WF1 has:
- BSD-style sockets (TCP + UDP)
- DHCP client (joining the user's network)
- DHCP server (when in setup mode it runs its own DHCP for the phone)
- BSD-Sockets-over-NetX layer for app-level networking

### Crash / debug surface

The firmware has Cortex-M trap / panic-handler format strings:

```
TRAP %x(%x): pc %x, lr %x, sp %x, psr %x, xpsr %x
   r0 %x, r1 %x, r2 %x, r3 %x, r4 %x, r5 %x, r6 %x
   r7 %x, r8 %x, r9 %x, r10 %x, r11 %x, r12 %x
   sp+0  %08x %08x %08x %08x
   sp+10 %08x %08x %08x %08x
```

If we can drive the device into a fault and capture its CDC log, we
get a full register/stack dump with addresses we can map back to
this firmware. Useful for any later JTAG/SWD work on a real BC-WF1.

### Why this matters for our app

Our app's USB-serial layer can already enumerate Uniden-VID
(`0x1965`) CDC devices. **We already see the BC-WF1 if it's plugged
into the user's PC** (or, by extension, if the scanner has it
attached and is in WiFi-streaming mode). Capturing the CDC traffic
between the scanner and the BC-WF1 - the same way we captured
Sentinel's USB MSC traffic - would reveal the audio-streaming
protocol Uniden uses for "scanner over WiFi" features.

This is not on the firmware-updater critical path, but it's a
documented future surface for any "stream scanner audio to network"
work the app might want to do.

## HomePatrol-1 firmware - SREC + obfuscated app

Three HomePatrol-1 firmware files exist on the server:

| File | Size | Loc |
| --- | --- | --- |
| `HomePatrol-1_V2_04_01.scn` | 13.8 MB | `/Extreme/` |
| `HomePatrol-1_V2_06_02.scn` | 13.8 MB | `/HomePatrol/Updater/` |
| `HomePatrol-1_V2_06_06.scn` | 13.8 MB | `/Extreme/` |

The `.scn` extension is Motorola **S-Record (SREC)** format - ASCII
hex-encoded firmware records with addresses + checksums. Easy to
parse:

```
S0 15 0000 [header bytes] [chksum]
S3 25 [32-bit addr] [60 hex chars data] [chksum]
S3 25 ...
S8 05 [32-bit entry point] [chksum]
```

`HomePatrol-1_V2_06_06.scn` decodes to **9 contiguous regions**
spanning addresses `0x00000000` to `0x20700100`:

```
0x00000000 - 0x00000400    1 KB   (boot vectors / reset vector)
0x00002600 - 0x00002a00    1 KB   (configuration / interrupt vector table)
0x00020000 - 0x00028480   33 KB   (bootloader)
0x00040000 - 0x00042200  8.5 KB   (small data)
0x00042580 - 0x00042d80    2 KB   (more data, all 'T' bytes 0x54 - padding signature)
0x00043000 - 0x00416d80  3.9 MB   (MAIN APP - obfuscated)
0x00416f00 - 0x0041a280   13 KB   (tail data, all '2' bytes 0x32 - padding signature)
0x0041a300 - 0x0066e680  2.4 MB   (continued main app or resources, also obfuscated)
0x20700000 - 0x20700100   256 B   (RAM init data: PLAINTEXT Cortex-M Thumb-2 instructions)
```

### Architecture confirmation

The address layout (low-flash code at `0x00000000`+, RAM init data
at `0x20700000`) is classic **Cortex-M memory map**. The 256-byte
region at `0x20700000` parses as plausible Thumb-2 instructions
(`20 22` = `MOVS R0, #0x22`, `60 29` = `STR R1, [R5, #0]`, etc.),
confirming the HomePatrol-1 is a **Cortex-M MCU** (probably NXP
LPC1xxx given the era and Uniden's later use of NXP for the SDS100
SUB).

### Why we can't strings-mine the main app

The 3.9 MB main app region has entropy **7.4357** - too high for
plaintext machine code (typical Cortex-M code is 5.5-6.5). Strings
extraction returns no meaningful identifiers; we see clusters of
ASCII letters with periodic patterns like `BM"C$B"CBMgb` repeating,
which is not a single-byte XOR (we tested all 256 keys) and not LZ77
output.

Most likely explanation: **Uniden wraps the main app in a custom
LZSS / LZ4 / Stac-style compressed encoding** before SREC-encoding
it, with a small bootloader-side decompressor that runs at flash
time. This is consistent with the bootloader region (33 KB at
`0x00020000`, entropy 6.79, also no meaningful strings - probably
the obfuscated decompressor itself).

### What this rules out

- The HomePatrol-1 firmware is **not a plaintext predecessor** to
  the BCDx36HP family. Even in 2010-2016, Uniden was already wrapping
  application content in an opaque format.
- This invalidates the "older firmware = plaintext = stepping stone"
  hypothesis. Encryption / opacity has been Uniden's default
  posture for at least 16 years.

### Why it might still be worth eventually

If we ever care about HomePatrol-1 RE (e.g., extending app support
to that older product), the SREC-format gives us a clear region map
and a known Cortex-M target. Cracking the obfuscation would be a
medium-difficulty pure-static exercise (the decompressor lives in
those 33 KB at `0x00020000`). For now: **deferred**, no current
business value.

## Confirmed: no SDS100-compatible alternative firmware

We considered the hypothesis "maybe a government / regional variant
runs on SDS100 hardware and is unencrypted or differently-encrypted".
None of the variants we tested support this:

- `USDS100_V*.bin` (the closest "U-prefix" candidate): same encryption,
  100% byte-different from `SDS-100_V*.bin` of the same era. Even if
  it were flashable onto an SDS100, it is encrypted with the same
  scheme and provides no static RE leverage.
- `UBCD436-PT_V*.bin` / `UBCD3600XLT_V*.bin`: same conclusion.
- `SDS100E_V*.bin` (European variant): not pulled in this hunt, but
  has the same naming convention and 2.16 MB exact size as civilian
  SDS-100, strongly implying same encryption.

## What's not on the server (and why we checked)

| Hypothesis | Result |
| --- | --- |
| `/Beta/` or `/beta/` subdirectories | not present (550) |
| `/Test/` or `/test/` subdirectories at top level | not present (only `/HomePatrol/Test/` exists, and it's just old HPDB blobs) |
| `/Internal/` accessible content | no - 550 on enter |
| `/SDS100/`, `/SDS150/`, `/BC125AT/`, `/BCT15X/`, `/BCD325P2/`, `/Polmar/` | none present (not how Uniden organizes the server) |
| Symbol files / debug builds (`.elf`, `.map`, `.lst`, `.sym`) | none observable |
| Source-code dumps (`/src/`) | not present |

## Reproduction (if anyone wants to verify)

All the above is reproducible with the credentials documented in
`uniden_update_endpoints.md`. Quick recipe:

```powershell
$cred = New-Object System.Net.NetworkCredential("homepatrolftp","green7Corn")

# Top-level listing of both servers
foreach ($host in @("ftp.homepatrol.com","ftp.uniden.com")) {
    $req = [System.Net.FtpWebRequest]::Create("ftp://${host}/")
    $req.Method = "LIST"
    $req.Credentials = $cred
    (New-Object IO.StreamReader $req.GetResponse().GetResponseStream()).ReadToEnd()
}

# Pull the BC-WF1 (the actionable plaintext blob)
$wc = New-Object System.Net.WebClient
$wc.Credentials = $cred
$wc.DownloadFile("ftp://ftp.homepatrol.com/BCDx36HP/BC-WF1_V7_28.bin", "BC-WF1_V7_28.bin")
```

Don't commit the resulting blobs - they're Uniden's binaries and
we don't redistribute. The findings above are the published record;
re-verify against the live server if Uniden ever updates the layout.

## Cross-references

- [`uniden_update_endpoints.md`](uniden_update_endpoints.md) - the
  canonical update-endpoint doc this builds on.
- [`SDS100_firmware.md`](SDS100_firmware.md) - on-card MAIN firmware
  blob format and Sub firmware container parsing.
- [`sub_static_analysis.md`](sub_static_analysis.md) - what we did
  pull out of the SDS100 SUB MCU plaintext firmware.
- [Reverse Engineering wiki](../../../wiki/Reverse-Engineering.md) -
  high-level RE narrative.
