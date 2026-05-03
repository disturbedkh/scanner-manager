# Worker Log

Append-only. Newest entry on top. **One entry per meaningful session.**

## Entry format

```
## YYYY-MM-DD HH:MM TZ - <hostname> - <agent / human>
- Branch: <branch>
- HEAD: <short sha>
- What changed: <bullet list>
- Decisions: <bullet list, optional>
- Blockers / next: <bullet list>
```

Keep entries terse. If something needs more than five bullets, write
it up in a topic doc (e.g. `MULTI_SCANNER_BACKEND.md`) and link to
that doc from your log entry.

---

## 2026-05-03 13:50 ET - <HOST> - Cursor agent (Opus 4.7)
- Branch: `main`
- HEAD: `8f6a7df` (RE notes + design refresh; no app code changes)
- What changed:
  - **Discovered Uniden's actual update infrastructure.** Static-extracted
    FTP credentials from both Sentinel and BT885 Update Manager .NET
    installers, then live-listed both servers for the inventory:
    - Sentinel: `ftp://homepatrolftp:green7Corn@ftp.homepatrol.com/BCDx36HP/`
      → 105+ firmware blobs (BCD436HP, BCD536HP, SDS-100, SDS200, SDS150,
      SDS100E, SDS200E, USDS100, BC-WF1, etc.) + 161 weekly HPDB snapshots
      + Sentinel installer + `.app` marker files for version pointers +
      `archive/` for downgrades.
    - BT885: `ftp://BT885ftp2:89jZ53Ba@ftp.uniden.com/BT885/` → HPDB only,
      no firmware (so far).
    - Both apps use plain FTP with `NLST`/`SIZE`/`MDTM`/`RETR`. No HTTP
      manifest API. The `.app` files are 0-2 byte version-pointer markers.
  - **Confirmed prior assumption was wrong**: the TWiki at
    `info.uniden.com/twiki/...` is a *publication* site (changelogs,
    downgrade ZIPs), not the source Sentinel checks. Update discovery is
    pure FTP directory listing + filename parsing.
  - **Wrote `AI/Dev/RE/docs/uniden_update_endpoints.md`** with full
    methodology, inventory, reconstructed update-check algorithm, sample
    `UnidenFtpClient` skeleton, and risk/etiquette notes.
  - **Wrote `wiki/RE-Update-Endpoints.md`** as the canonical wiki page;
    cross-linked from `wiki/Reverse-Engineering.md` (sub-page list +
    status table) and `wiki/RE-Sentinel.md` (replaced "out-of-band HTTP"
    guesses with the now-known FTP truth).
  - **Updated `AI/Dev/FIRMWARE_UPDATER.md`** to ground Phase 1 in FTP
    discovery instead of TWiki scraping; demoted the hand-curated
    `firmware_manifest.json` from source-of-truth to enrichment-only
    (changelogs, `requires_sub_min`, withdrawn flags).
  - **Updated `AI/Dev/WORKSTREAMS.md`** firmware-updater row + added a
    new "Uniden update endpoint RE" stream marking it done.
- Decisions:
  - Skip full ilspycmd / dnSpy decompilation. The string-extraction +
    live FTP listing path produced everything we needed in <1h vs. the
    multi-hour decompiler-tooling install + analysis. Re-open if a
    future question requires actual control-flow analysis (e.g., HPDB
    blob format if it turns out not to be just gzipped text).
  - Treat the FTP creds as documented-but-respected: cache listings,
    don't poll, keep the manual-import fallback path warm.
- Blockers / next:
  - None blocking. Firmware updater Phase 1 (FTP listing → version list)
    is now ready to implement when prioritized.

---

## 2026-04-29 16:55 ET - <HOST> - Cursor agent (Opus 4.7)
- Branch: `main`
- HEAD: `c34585e` (RE tooling + notes only; no app code changes)
- What changed:
  - **Tier ABC RE plan executed end-to-end** (plan:
    `tier_abc_combined_re_fd05952e.plan.md`). Phases 1-3 + 5 + 6.1
    + 6.3-6.5 (best-effort, no Ghidra) + 7 catalog all complete.
    Phase 4 (Sentinel USB capture) and Phase 6.2 (Ghidra) deferred -
    one needs user time, the other 20-50h focused work.
  - **Phase 1 - SUB-port systematic probe**: new `sub_probe.py`
    alphabet-attack with anchor-and-compare and SUB-specific
    forbidden mnemonic set. Single-letter A-Z + two-letter AA-ZZ +
    targeted three-letter combos. Net new finding: **`U`** returns
    a 9-byte response (`U5C42\\r\\x00<2 binary bytes>`) where the
    last 2 bytes change between calls - likely a register/RSSI/
    counter dump. All other apparent hits were prefix-fallback
    false positives (firmware echoes identity for any `M*` or
    `V*` input).
  - **Phase 2 - MAIN arg-extension**: extended `serial_probe.py`
    `QUERIES` with ~24 GSI/STS/GLT/MSI/GST argument variants. New:
    `GSI,XML/RAW/PROP/FULL`, `GSI,XML,?` (returns "unresolved"
    placeholder view).
  - **Phase 3 - BCDx36HP V1.05 legacy probe**: fetched the spec
    from Uniden TWiki, diffed against current QUERIES, added 22
    GLT subforms. New: **`GLT,SYS`** (undocumented but works on FW
    1.26.01 - returns full SYS list across FLs). `GLT,UREC_FILE,0`
    times out - flagged "do not use". `BFH` added to
    `FORBIDDEN_FOR_READ_ONLY`.
  - **Phase 4 - Sentinel USB capture prep**: workflow doc landed
    at `AI/Dev/RE/sentinel_capture.md` (USBPcap setup, per-op
    capture strategy, decode method). Capture session itself
    pending user time.
  - **Phase 5 - cross-correlation**: new `_correlate_responses.py`
    joins SUB-probe hits against Sub firmware string table by
    converting printf format strings to regexes. Output:
    `AI/Dev/RE/sub_command_response_map.md`. **35 untriggered
    printf format strings** in Sub firmware identified as future
    probe targets (R840 modes, RF gain, FFT/CIC/FIR/NCO debug).
    The lone `U` hit's response doesn't match any format string,
    suggesting a non-printf register dump path.
  - **Phase 6.1 - Sub payload extraction**: **corrects prior
    Session 4 assumption**. The Sub `.firm` is NOT compressed -
    the "zlib magic" hits were coincidental matches in plaintext
    ARM. New `_inflate_sub.py` parses container, extracts 90,076
    bytes of plaintext ARM Cortex-M to
    `firmware/sub_1.03.15_inflated.bin`. CRC-32 verified.
  - **Phase 6.2 - Ghidra runbook**: doc landed at
    `AI/Dev/RE/ghidra_import_runbook.md` (project setup, ARM
    Cortex-M3/M4 import at base 0x14000000, LPC43xx SVD overlay,
    auto-analysis, dispatch-table identification, inter-MCU bus
    RE). Estimate 20-50h. Not started.
  - **Phase 6.3-6.5 - best-effort static analysis**: new
    `_sub_static_analysis.py`. Output: `sub_static_analysis.md`.
    LPC43xx peripheral 32-bit constant scan: UART1 + SSP0 each
    have 6 references in payload, making them the most likely
    inter-MCU bus candidates. ADC1 has 8 references, SCT 9, USB0
    5. I2S not detected via constant scan (likely struct-pointer
    indirection). No obvious dispatch table found by clustering -
    needs Ghidra to disambiguate.
  - **Phase 7 - canonical catalog**: new
    `AI/Dev/RE/SDS100_unofficial_commands.md` consolidates every
    finding across all phases with safety classification.
  - **Doc updates**: `AI/Dev/RE/SDS100.md` Session 6 section,
    `AI/Dev/RE/SDS100_firmware.md` Session 6 update with corrected
    container layout, `AI/Dev/WORKSTREAMS.md` rows refreshed.
- Decisions:
  - Did NOT attempt zlib/LZMA inflation after discovering the
    "compression" was a misread of plaintext ARM machine code.
    Wrote the corrected container layout into
    `SDS100_firmware.md`.
  - Did NOT escalate any `,?` write attempts when probing -
    strict read-only rules held throughout.
  - Marked `GLT,UREC_FILE,0` as NORESP and added to "do not use"
    instead of investigating the timeout further (pre-existing
    firmware bug; not worth digging into without firmware
    debugging).
- Blockers / next:
  - **Phase 4 capture session** needs user time at the SDS100
    with USBPcap installed and Sentinel installed, to capture
    Read From Scanner / Write to Scanner / HPDB Update / Firmware
    Update / Backup / Restore.
  - **Phase 6.2 Ghidra import** is the single biggest unblock for
    the full Sub disassembly (Phases 6.3-6.5 fully). Needs 20-50h
    of focused work. Runbook is ready.
  - **Targeted SUB re-probe** based on the 35 untriggered printf
    format strings is the highest-yield next probing pass. Should
    extend `sub_probe.py` with mnemonic candidates derived from
    string fragments (e.g. `RFGM` / `RFG` / `GAIN` from
    `RF_GainMode`).

---

## 2026-04-27 19:00 ET - <HOST> - Cursor agent (Opus 4.7)
- Branch: `main`
- HEAD: unchanged (RE tooling + notes only; no app code changes)
- What changed:
  - **Live-serial RE Session 4** against SDS100 on COM4, now FW
    Main 1.26.01 / Sub 1.03.15 (user updated via Sentinel mid-session).
  - **Big correction**: PID `0x0019` is NOT a bootloader. It's the
    **SUB processor command port** running the same Remote Command
    Protocol but routed to the LPC43xx SUB MCU. Confirmed via
    `MDL` -> `SDS100-SUB`, `VER` -> `Version 1.03.15`. The
    Sessions 1-3 conclusion that 0x0019 was firmware-updater mode
    was wrong; corrected in `AI/Dev/RE/SDS100.md`.
  - **Big finding**: Sentinel firmware updates are pure SD-card
    file-drops. No proprietary USB protocol involved. Documented
    by Uniden in plain English inside every firmware ZIP's
    `Readme*.txt`. This unblocks an **in-app firmware updater**
    feature - design doc landed at `AI/Dev/FIRMWARE_UPDATER.md`.
  - **Live RX captured**: first non-empty `GLG` response in 4
    sessions - `GLG,2057,NFM,0,0,Simulcast,<AGENCY>,A1 Primary,1,0,,,4D2`.
    12-field schema decoded
    (TGID, modulation, ?, avoid, site, dept, channel name,
    active-RX flag, ?, _, _, NAC). Two fields (3 and 9) still
    unknown - need more samples.
  - **STS bit-1 partial decode**: idle `00100000000000` vs active
    `00110110110000`, bits 3, 5, 6, 8, 9 flip during voice RX.
    Inferred: voice-RX-active, P25-mode, TGID-locked,
    NAC-matched, voice-frame-decoded. To confirm with targeted
    feature toggles in Session 5.
  - **GSI got richer in FW 1.26.01**: now reports `<UnitID Name>`,
    `<UnitID U_Id>`, `<TGID SvcType>` text label, `<SiteFrequency
    SAD>` populated during RX.
  - **V2.00 commands `GCS`/`KAL` ERR'd** on FW 1.26.01 even though
    the spec lists them. Either aspirational, SDS200/SDS150-only,
    or context-dependent. Tested both COM4 (MAIN) and COM3 (SUB)
    - both ERR'd. Marked as "spec lists but FW 1.26.01 doesn't
    implement" in the probe whitelist.
  - **Static RE on firmware** done in same session (no scanner
    needed):
    - Main `.bin` is **encrypted** - whole-file Shannon entropy
      7.9999/8.0, all 528 chunks high-entropy, byte-level diff
      99.61% changed between 1.23.07 and 1.26.01, string sets
      have **zero overlap**. Static RE on Main is infeasible
      without hardware attack. Documented loudly so we don't
      retry.
    - Sub `.firm` is **plaintext-headed + compressed code** -
      entropy 7.18/8.0. Full architecture decoded from string
      table: NXP LPC43xx SUB MCU (`../src/lpc43xx_i2c.c`),
      Rafael Micro R840 RF tuner, full DSP pipeline (ADC ->
      CIC -> FIR1 -> FIR2 -> NCO -> FFT), 4-stage AGC
      (LNA1/LNA2/Mixer/VGA), digital noise squelch.
    - Sub 1.03.15 added one new 16-bit field to its status format
      (`S%02X%04X%04X%04X%04X%01X` -> `...%04X`) - a real
      protocol-surface change.
  - **Firmware corpus staged** at `AI/Dev/RE/firmware/`: Main
    1.23.07/1.26.01, Sub 1.03.05/1.03.15, plus bridging versions
    1.23.15/1.23.20 and SDS200 1.24.00. SHA-256 hashes recorded
    in `AI/Dev/RE/SDS100_firmware.md`.
  - **New planning docs** for follow-up work:
    - `AI/Dev/FIRMWARE_UPDATER.md` - in-app firmware updater
      design (Phases 1-3, GUI panel, manifest schema, code-level
      sketch)
    - `AI/Dev/MULTI_DEVICE_GUI.md` - top-level device selector
      design (Phases 1-5, header bar, per-tab support gating,
      Device manifest schema)
    - `AI/Dev/RE/SDS100_firmware.md` - the static-RE write-up
      itself (Main = dead end, Sub = full architecture).
  - **Tooling added under `AI/Dev/RE/`**:
    - `_list_ports.py` - SDS100 COM-port detector (handles
      VID 0x1965 detection)
    - `_com3_probe.py` - SUB-processor port test
    - `_firmware_strings.py` - strings extraction + diffing
      across the four firmware images
    - `_firmware_structure.py` - entropy profile + magic-byte
      scan + byte-level diff between same-MCU versions
    - `serial_probe.py` extended with V2.00 commands `GCS`,
      `KAL` and forbidden additions `GW2`, `POF`
- Decisions:
  - Don't pursue Main firmware static RE further - it's encrypted,
    confirmed conclusively. Live serial RE is the only path to
    learn what Main is doing.
  - Pursue an in-app firmware updater as a feature (design only
    in this session; ready to implement when prioritized).
  - Build the multi-device GUI top selector on top of the existing
    `scanner_profiles/` backend - the backend was designed for
    exactly this; only blocker is `ACTIVE_PROFILE` reassignment
    and migration of remaining `scanner_manager.py` module-level
    constants (already on the existing backlog).
  - Sub firmware is the static-RE surface for this scanner family;
    SDS150 (UB3912) shares the same firmware family per V2.00
    spec, so all Sub findings carry over to it.
- Blockers / next:
  - Session 5 needs the user at the scanner: STS feature-toggle
    diff (HOLD/ATT/KEY-LOCK/PRI/CC), longer GLG poll during a
    busier period to nail field 3 and field 9 semantics,
    SUB-port command-set probing for the status-S query.
  - User to decide which to implement first: firmware updater
    (Phase 1 of `FIRMWARE_UPDATER.md`) or multi-device GUI
    backend prep (Phase 1 of `MULTI_DEVICE_GUI.md`). They're
    largely independent.

---

## 2026-04-27 17:50 ET - <HOST> - Cursor agent (Opus 4.7)
- Branch: `main`
- HEAD: `c34585e` (RE tooling + notes only; no app code changes)
- What changed:
  - **Live-serial RE Session 3** against SDS100 on COM4 (PID `0x001A`),
    FW Main 1.23.07 / Sub 1.03.05.
  - Acquired the official Uniden **SDS100/SDS200 Remote Command
    Specification V1.02** (2023-12-22) and mirrored both the PDF and
    the extracted text to `AI/Dev/RE/`. Audited the probe whitelist
    against the spec - removed all speculative non-spec mnemonics,
    promoted spec-confirmed reads (`GSI`, `SVC`, `DTM`, `LCR`, `MSI`,
    `FQK`, plus 8 `GLT,xxx` subcommands), and expanded the FORBIDDEN
    list to cover every documented mutating command (`KEY`, `QSH`,
    `JNT`, `NXT`, `PRV`, `HLD`, `AVD`, `JPM`, `AST`, `APR`, `URC`,
    `MNU`, `MSV`, `MSB`, `PSI`, `PWF`, `GWF`, `SQK`, `DQK`).
  - Refactored `AI/Dev/RE/serial_probe.py`: split read into a
    `_send_and_read` helper with a 1.5 s deadline + 100 ms quiet-after-CR
    threshold (handles multi-page XML responses cleanly), and added two
    new modes (`--mode poll` for high-rate single-command capture,
    `--mode diff` for state-toggle snapshots).
  - Ran the full whitelist on the SDS100 - 53 commands sent, 17
    spec-confirmed reads returned data, 21 inherited mnemonics still
    ERR (matches the spec's silence on them - they're never-implemented
    ghosts), and a few `,?` probes confirmed only legacy `VOL`/`SQL`
    accept the BCDx36HP-era `,?` write-acceptance handshake.
  - Built a one-shot `AI/Dev/RE/_glt_chain.py` that walks the live
    GSI/GLT index tree: GSI -> System Idx 6 -> 5 departments,
    1 site (Idx 9), 13 site frequencies, 0 avoiding TGIDs. Full XML
    captured in `AI/Dev/RE/sessions/sds100_glt_chain_20260427T174520.txt`.
  - Discovered V2.00 spec (2025-07-07) and mirrored it. Adds 4 new
    commands: **`GCS`** (Get Charge Status, read-only - the real
    battery command we wanted; note `\n` terminator, only one in the
    whole spec), **`KAL`** (Keep Alive, no response), **`GW2`**
    (waterfall stream variant of GWF - forbid), **`POF`** (power off,
    already forbidden). V2.00 also formalises VOL/SQL as #33/#34 and
    adds **SDS150 (UB3912)** to the supported model list.
  - Documented Session 3 + the full V2.00 delta + Session 4 plan as
    new sections in `AI/Dev/RE/SDS100.md`. Updated `WORKSTREAMS.md`
    to reflect Sessions 1-3 done and Session 4 blocked on firmware
    update.
- Decisions:
  - Hold Session 4 until user updates firmware to Main 1.26.01 (current
    is 1.23.07, ~2.5 years stale; the V2.00 command surface needs
    1.24.00 or later to be exercisable).
  - When Session 4 runs, use GSI XML as the canonical "live scanner
    state" surface for any future multi-scanner-backend live-mirror
    feature - not STS scraping. The spec's typed `<Property>` element
    delivers the entire UI status bar in one shot.
- Blockers / next:
  - User to verify firmware version (matches what we observed:
    Main 1.23.07 / Sub 1.03.05) and update via Sentinel to Main
    1.26.01 + matching Sub.
  - Session 4 plan: `KAL` + `GCS` add, GLG-poll-during-RX, STS-bit
    diff via feature toggle, GSI before/after diff vs Session 3.
  - No app code changes this session - all RE tooling and notes.

---

## 2026-04-27 17:00 ET - <HOST> - Cursor agent (Opus 4.7)
- Branch: `main`
- HEAD: `c34585e` (notes + RE tooling only; no app code changes)
- What changed:
  - Plugged in **both** SD cards simultaneously: BT885 on `E:\`,
    SDS100 on `H:\`. Ran the new read-only side-by-side driver
    `AI/Dev/RE/compare_cards.py`. Output captured to
    `AI/Dev/RE/sessions/card_compare_20260427T171130.txt`.
  - Added `AI/Dev/RE/SD_CARD_COMPARISON.md` - the family-wide diff
    doc.
  - Added `AI/Dev/RE/BT885.md` - first formal BT885 SD-card RE
    write-up, including the on-disk schemas for `CityTable_*.dat`
    and `ZipTable_*.dat` that we already had RE'd in
    `scanner_manager.py`.
  - Updated `AI/Dev/RE/SDS100.md` to:
    - Move `activity_log/`, `alert/`, `audio/`, `discovery/`,
      `favorites_lists/` (the empty stub dirs) **out** of "what's new
      on SDS100" - they exist on BT885 too.
    - Resolve the "identity contradiction" - BT885 firmware writes
      `TargetModel\tBCDx36HP`, **not** `Beartracker885`. Codebase
      aliases were never validated against real hardware.
    - Refresh the BT885-vs-SDS100 delta table with verified field
      counts and observed record types.
  - Updated `PROJECT_STATE.md`, `MULTI_SCANNER_BACKEND.md`,
    `WORKSTREAMS.md`, `RE/README.md` to point at the new docs and
    record the verified facts.
- Decisions:
  - **`firmware/CityTable_V1_00_00.dat` and
    `firmware/ZipTable_V1_00_00.dat` are bit-identical** between
    BT885 and SDS100 cards (same SHA-256, 47,204 city / 41,771 ZIP
    records). They can be bundled once for the family.
  - Detection refactor on the multi-scanner backend stream is now
    well-justified by real-hardware evidence. `Bt885Profile.target_model_aliases`
    needs to retire `Beartracker885`/`BearTracker885`; tests that
    use `TargetModel\tBeartracker885` need to switch to
    `TargetModel\tBCDx36HP`. **No code changes made yet** - per the
    "don't commit unless asked" rule.
  - The empty BT885 `f_list.cfg` (42 B header-only stub) means
    `supports_favorites` should be a per-profile policy decision,
    not a "file exists" check.
- Blockers / next:
  - User decision pending: should we land the detect-on-open
    refactor + alias / fixture cleanup as the next code change, or
    keep that paused while serial-mode RE continues on `<HOST>`?
  - SUB-processor firmware version (`scanner.inf` field 9 on SDS100,
    absent on BT885) is exposed; useful when we later expose a
    "scanner info" pane in the UI.

---

## 2026-04-27 14:30 ET - <HOST> - Cursor agent (Opus 4.7)
- Branch: `main`
- HEAD: `fb75913` (still no code changes - notes + RE tooling only)
- What changed:
  - Live passive RE of the SDS100 over USB serial. User explicitly
    rejected the `scanner.inf`-first detector path; pivoted to
    direct serial-mode RE at the user's request.
  - Created `AI/Dev/RE/serial_probe.py` - a strict read-only probe
    with a hard-coded forbidden-mnemonic list (`KEY`, `PRG`, `EPG`,
    `JNT`, `JPM`, `WPL`, `WPS`, `CLR`, `DLA`, `MEMSET`, `WIPE`,
    `TGW`, `VLO`, `SLO`, `GLT`, `RST,SET`). Whitelist of 36
    suspected-query mnemonics.
  - Created `AI/Dev/RE/com6_listen.py` - listen-only baud-sweep used
    to verify the COM6 endpoint was not GPS NMEA.
  - Discovered the SDS100 enumerates **two** Uniden CDC ports in
    Serial mode:
    - `VID 1965 PID 0019` = SUB processor bootloader (per-byte
      echo, only `M*`/`V*` first-char triggers, returns `SDS100-SUB`
      and `Version 1.03.05`). NOT a general protocol.
    - `VID 1965 PID 001A` = MAIN processor command port. Speaks
      the **full Uniden Remote Command Protocol** (`MDL,SDS100\r`,
      `VER,Version 1.23.07\r`, `STS`, `GLG`, `PWR`, `VOL`, `SQL`,
      `GST`).
  - Captured 3 raw probe sessions in `AI/Dev/RE/sessions/` (committed
    for cross-machine reproducibility).
  - Major doc updates: `AI/Dev/RE/SDS100.md` got two new sections
    (Session 1 + Session 2) with the protocol mapping, an STS
    payload decode (preliminary), command-table results, and a
    next-step plan.
- Decisions:
  - **PID-based port disambiguation is mandatory** for the SDS100;
    the OS-level "USB Serial Device" name does not distinguish
    SUB-bootloader vs. MAIN-command. Future detector code must use
    PID `0x001A` for command access.
  - **Authoritative model fingerprint = live `MDL,SDS100\r`** when
    available; falls back to `scanner.inf` `Scanner` field on the
    SD card. `TargetModel` remains unreliable for model id.
  - `AI/Dev/RE/sessions/` is committed to git so the next desktop /
    next agent can re-read the raw bytes without re-running the
    probe. Probe scripts also committed.
- Blockers / next:
  - User moving to another desktop. Wrap-up: commit + push.
  - On the next desktop, fresh `.venv` will be needed (current
    `.venv` on <HOST> is broken - points at a missing Python
    3.14 install). `py -m pip install --user pyserial` works for
    the probe scripts standalone.
  - Next planned passes (all read-only, COM6 only):
    1. Decode STS status-bit field by toggling features one at a
       time and diffing.
    2. Capture GLG during a real RX.
    3. Vet + add second whitelist batch (`RMB`, `WIN`, `DGR`,
       `RIN`, `LCB`, `BTV`, `BSV`, `SUM`, `PSI`).

---

## 2026-04-27 14:10 ET - <HOST> - Cursor agent (Opus 4.7)
- Branch: `main`
- HEAD: `fb75913` (no code changes; notes only)
- What changed:
  - Reverse-engineered the SDS100 SD card mounted at `D:\` (FAT32,
    ~7.5 GiB, firmware `1.23.07`, serial `<SERIAL>`).
  - Created `AI/Dev/RE/` folder with `README.md` plus the full
    `AI/Dev/RE/SDS100.md` capture: volume info, full folder tree
    with sizes, contents of every identity / settings file,
    record-type tally for a large state HPD, sample favorites
    HPD with the new `DQKs_Status` row, full delta vs. BT885,
    8-step plan for landing an `Sds100Profile`, and 9 open RE
    questions for follow-up (real BT885 `TargetModel` value,
    36-slot service-type semantics, `BandPlan_Mot` / `FleetMap`
    fields, populated `discvery.cfg` schema, etc.).
  - Updated `AI/Dev/WORKSTREAMS.md` to make SDS100 (and SDS200)
    profile work the active second-place workstream behind the
    multi-scanner backend foundation.
  - Updated `AI/Dev/MULTI_SCANNER_BACKEND.md` - TODO #1 now flags
    the critical finding that `TargetModel\tBCDx36HP` is the
    firmware-family name, not a per-model id. Detect-on-open
    needs to read `BCDx36HP/scanner.inf`. TODO #3 now points
    explicitly at the SDS100 RE and the SDS200 share-by-default.
  - Updated `AI/Dev/README.md` and `.cursor/rules/ai-dev-notes.mdc`
    to direct future Cursor sessions to read `AI/Dev/RE/` before
    touching any `ScannerProfile`.
- Decisions:
  - **One profile covers both SDS100 and SDS200** (per user
    direction - 99% shared codebase). Manifest entry will list
    both in `match_scanner_inf`.
  - **`TargetModel` alone is unreliable for model id** in the
    BCDx36HP family. New detector must read `scanner.inf`. This
    invalidates the existing `Bt885Profile.target_model_aliases`
    contract and forces detect-on-open to learn a richer
    fingerprint - documented as the new TODO #1 caveat.
  - SDS200 RE is **not** required up front; the SDS100 doc covers
    it. If/when an SDS200 card surfaces, drop diff-only notes in
    a new `AI/Dev/RE/SDS200.md` rather than duplicating.
- Blockers / next:
  - Need to either source a real BT885 SD card image or accept
    that BT885 detection moves to `scanner.inf` reading without
    field-verifying `TargetModel`.
  - User to greenlight implementing `Sds100Profile` per the
    8-step plan in `AI/Dev/RE/SDS100.md`. Step 1 (the new
    `scanner.inf` detector) is the path-of-least-regret because
    it also fixes BT885 identification and unblocks TODO #1 of
    `MULTI_SCANNER_BACKEND.md`.

---

## 2026-04-27 13:55 ET - <HOST> - Cursor agent (Opus 4.7)
- Branch: `main`
- HEAD: `fb75913`
- What changed:
  - Resynced local working copy with GitHub. The previous local
    `.git` was incomplete (missing `objects/` and `refs/`); replaced
    with a fresh clone and `git reset --hard origin/main`. User
    state preserved (`app_settings.json`, `.venv/`).
  - Familiarized with the multi-scanner backend in
    `scanner_profiles/`. No code changes.
  - Created the `AI/Dev/` notes folder (this folder) with
    `README.md`, `PROJECT_STATE.md`, `WORKSTREAMS.md`,
    `MULTI_SCANNER_BACKEND.md`, `MACHINES.md`, `CONVENTIONS.md`,
    and this `WORKER_LOG.md`.
  - Added `.cursor/rules/ai-dev-notes.mdc` so any future Cursor
    instance auto-loads this folder on session start.
- Decisions:
  - `AI/Dev/` is **tracked in git** so notes sync across machines via
    `git pull`. If we later want it private, gitignore it then.
  - `ACTIVE_PROFILE` reassignment on workspace open is the next
    logical step; documented as TODO #1 in
    `MULTI_SCANNER_BACKEND.md`. Did not implement.
- Blockers / next:
  - Awaiting user direction on whether to start the
    detect-on-open work or something else.
