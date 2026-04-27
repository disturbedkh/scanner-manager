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

## 2026-04-27 14:30 ET - MINILAPTOP - Cursor agent (Opus 4.7)
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
    `.venv` on MINILAPTOP is broken - points at a missing Python
    3.14 install). `py -m pip install --user pyserial` works for
    the probe scripts standalone.
  - Next planned passes (all read-only, COM6 only):
    1. Decode STS status-bit field by toggling features one at a
       time and diffing.
    2. Capture GLG during a real RX.
    3. Vet + add second whitelist batch (`RMB`, `WIN`, `DGR`,
       `RIN`, `LCB`, `BTV`, `BSV`, `SUM`, `PSI`).

---

## 2026-04-27 14:10 ET - MINILAPTOP - Cursor agent (Opus 4.7)
- Branch: `main`
- HEAD: `fb75913` (no code changes; notes only)
- What changed:
  - Reverse-engineered the SDS100 SD card mounted at `D:\` (FAT32,
    ~7.5 GiB, firmware `1.23.07`, serial `38326-038000050-0DA`).
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

## 2026-04-27 13:55 ET - MINILAPTOP - Cursor agent (Opus 4.7)
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
