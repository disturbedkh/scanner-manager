# Plan: Virtual scanner (SDR-backed "software SDS100")

| Field | Value |
|---|---|
| Status | **Exploratory** - not yet a tracked work-stream. |
| Owner | TBD |
| Depends on | Existing SD card / Sentinel / SUB-firmware RE work. |
| Promoted from | Brainstorming after Phase 0/1/2 RE completed. |

## TL;DR

A "virtual SDS100" is feasible **as a compatibility-and-UX layer
over an existing open-source SDR/decoder stack**, not as a
ground-up reimplementation of the Uniden DSP pipeline.

You plug an RTL-SDR / Airspy / HackRF / RSP1A into a PC, point our
app at it, and the user sees the SDS100 UI/UX (favorites, scan
state, GLG-style live RX, GSI-style display, recording, ZIP/GPS
filtering, etc.) backed by a software receiver. The hard radio work
- IF demodulation, P25/DMR/NXDN/EDACS decoding, talkgroup tracking
- comes from existing OSS projects we'd integrate with, not from
us.

The previously-RE'd SDS100 work is mostly **compatibility surface**:
SD card formats, GSI XML schema, HPDB + favorites + city/zip tables,
Sentinel-style file flow. The physical-layer DSP from the SUB
firmware is interesting but not the recommended path.

## Why "virtual scanner" at all?

Three concrete user wins:

1. **No hardware lock-in.** A user with a $30 RTL-SDR can run our
   app the same way someone with a real SDS100 does, and reuse the
   same favorite-list / coverage-map / recording workflow.
2. **PC-class compute.** A laptop has 100x the CPU/RAM of the
   embedded SUB MCU. We can do things the real scanner can't:
   waterfall display, multi-channel parallel decode, tap-and-record
   for every active TGID simultaneously, automatic talkgroup
   discovery from RR/uniden-DB, audio-feed replay alongside live RX.
3. **Same data model.** Because we already speak BCDx36HP HPDB,
   Sentinel-shaped favorites, and the GSI XML schema, the user's
   workspace is portable: fav list -> virtual scanner -> physical
   SDS100 -> back, no conversion.

## Three feasibility tiers

### Tier A - "Sentinel for SDR" (recommended starting point)

Use the SDS100 RE purely as a **format compatibility** layer; the
radio is a third-party SDR + decoder.

- **What we provide**: the existing app GUI, favorites/HPDB/GLT
  parsing, ZIP/GPS coverage, RR import, recording manager, plus a
  thin "SDR runtime" pane that drives an external decoder process
  (DSDplus, OP25, SDRTrunk) over its existing IPC (file, socket,
  named pipe).
- **What we don't provide**: a custom DSP pipeline. Decoding is
  delegated.
- **What the user sees**: feels like running our app against a real
  scanner, except "the scanner" is a SDRTrunk window in the
  background producing the audio + control stream.
- **Effort**: medium. Most cost is plumbing (driver process, IPC,
  config-file generation from our HPDB) plus UI for the SDR runtime
  pane.
- **Pros**: ships in months, leverages mature OSS decoders.
- **Cons**: bound to whatever the chosen decoder's protocol family
  list happens to support (P25 phase 1/2 yes; some niche systems no).

### Tier B - "GNU Radio + custom blocks" (medium-term)

Replace the bundled OSS decoder with a GNU Radio flowgraph we drive
ourselves, importing established gr-dsd / gr-dmr / gr-osmosdr
blocks for protocol decode, but owning the orchestration, tuner
control, RSSI metering, GLG-equivalent live-channel monitor, etc.

- **What we provide**: a GNU Radio top-block configurator, RTL-SDR /
  Airspy / SDRplay tuner control, our own scan-state machine
  (replicating SDS100 scan-state semantics), our own GLG-equivalent
  LIVE-RX read-out.
- **What we don't provide**: protocol-level demod (P25 framing, DMR
  burst sync, etc.) - those stay in upstream GNU Radio modules.
- **Effort**: large. GNU Radio integration is a known pain point;
  packaging gr-dsd into a Windows installer alone is non-trivial.
- **Pros**: tighter UX coupling, no second window, independent of
  any one decoder project.
- **Cons**: long tail of "this RF protocol works but only at >100
  kHz IF" issues, hardware-specific tuner quirks, etc.

### Tier C - "Replay the SUB DSP pipeline" (research project)

Use what we know about the SUB firmware's DSP path (R840 tuner ->
ADC -> FFT -> filter chain -> decoder ->
[Inter-MCU bus](../../../../wiki/RE-Inter-MCU-Bus.md)) and reimplement
the same pipeline in software.

- **What we'd reuse**: the format-string xrefs we found (`R840_FM`,
  `FFT_PEAK,%ddB`, `Noise Squelch,%6d`), the per-state DSP probes
  (`q`/`r`/`s`/`m`/`v` from the
  [SUB debug surface](../../../../wiki/RE-Serial-Protocol.md)), and the
  command dispatch in `tools/firmware/extract_dispatch.py`.
- **What we'd build**: a Python or C++ DSP pipeline matching the
  SUB's filter-bank semantics, fed from a generic SDR front-end.
- **Why this is a research project**: the SUB firmware's DSP is
  hand-tuned for a specific clock domain and a specific RF
  frontend; copying its block diagram is not the same as
  reproducing its performance. Plus, "we matched Uniden's DSP" is
  not actually a user-visible feature - users want talkgroups
  decoded, not "the same noise-squelch curve".
- **Effort**: very large.
- **Pros**: bragging rights; potentially useful for academic
  publications about scanner DSP architecture.
- **Cons**: zero strategic ROI compared with Tier A/B.

## Recommended path

**Start with Tier A.** Prototype against SDRTrunk (the most active
OSS scanner project; supports P25 phase 1/2, DMR, NXDN, MotoTRBO,
LTR, ProVoice, EDACS narrow). Feed it a `.playlist` config we
generate from our HPDB on the fly. Mirror its scan-state into our
GLG-equivalent UI via its already-existing JSON-over-HTTP-API
(`http://localhost:NNNN/api/`) or its zeromq publisher.

If/when Tier A users start asking for things SDRTrunk can't do
(custom RSSI heatmap correlated with GPS coordinate, parallel-record
all active TGIDs, etc.), roll Tier B as a "Pro" runtime and switch
the runtime panel between them.

Tier C stays a backlog item.

## Hardware compatibility matrix (target)

| Tuner | Bandwidth | Frequency | Recommended for |
|---|---|---|---|
| RTL-SDR v3/v4 | ~2.4 MHz | 24 MHz - 1.7 GHz | entry-level, public-safety LMR |
| Airspy R2/Mini | 10/6 MHz | 24 MHz - 1.8 GHz | wideband multi-channel |
| Airspy HF+ Discovery | 768 kHz | 0.5 kHz - 260 MHz | HF/VHF hobbyist |
| SDRplay RSP1A/RSPdx | 10 MHz | 1 kHz - 2 GHz | multi-band coverage |
| HackRF One | 20 MHz | 1 MHz - 6 GHz | half-duplex, broad coverage |
| LimeSDR | 30 MHz | 100 kHz - 3.8 GHz | full-duplex (advanced) |

Antenna: a single discone or a wideband vertical (e.g. Diamond D-130NJ,
Comet GP-3) covers most public-safety use cases. The app should
ship a "what frequencies do you actually need?" wizard that points
the user at appropriate antenna recommendations rather than
shipping its own antenna catalog.

## Risk register

| Risk | Mitigation |
|---|---|
| **Encrypted talkgroups.** Most P25 phase 2 trunked systems carry encrypted traffic. We can't decrypt. | Same limitation as a physical scanner. Surface this clearly in the GLG-equivalent display. |
| **OSS decoder churn.** SDRTrunk and OP25 evolve independently. Our IPC contract may break. | Pin a known-good version, document the upgrade procedure, integration-test as part of CI on a captured baseband. |
| **Windows packaging.** GNU Radio on Windows is fragile; SDRTrunk needs Java; Liquid DSP libs are platform-specific. | Tier A only requires the user to install one external app (SDRTrunk). Tier B is the real packaging risk. |
| **Legal.** Some jurisdictions restrict scanning specific frequencies. | Same as physical scanners. Document; don't ship region-specific frequency lists ourselves. |
| **No mobility.** A real scanner is portable. | Out of scope; this product is "scanner UI + recording + analytics on a PC", not a replacement for portable scanning. |

## What from the existing RE work feeds straight in

Every artifact below is already in the repo and immediately useful
for the virtual-scanner work. No additional RE pass needed:

| Artifact | Used for |
|---|---|
| `wiki/RE-SD-Card.md` + `Metacache/Dev/RE/docs/SD_CARD_COMPARISON.md` | favorites/HPDB schema we already parse end-to-end |
| `Metacache/Dev/RE/docs/sentinel_api.md` | the file-set we'd round-trip with for "virtual sentinel" of our own |
| `Metacache/Dev/RE/docs/SDS100_unofficial_commands.md` (GLT/GSI/STS) | UI/UX surface to mirror in software |
| `Metacache/Dev/RE/docs/sub_command_dispatch.md` (DSP debug commands) | informs Tier C only |
| `Metacache/Dev/RE/docs/sub_static_analysis.md` (R840/FFT format strings) | informs Tier C only |

## Open questions

1. **License compatibility.** SDRTrunk is GPL-3; can our (MIT)
   project ship a workflow that depends on it without a license
   conflict? (Probably yes if we don't statically link, but verify.)
2. **How much of the GLG schema actually maps to non-Uniden
   decoder output?** Need a side-by-side capture: a real SDS100's
   GLG line vs. SDRTrunk's "current call" event.
3. **Recording format.** Real SDS100 records to WAV + sidecar
   metadata. Should the virtual scanner match byte-for-byte
   (workflow portability), or use a richer format (FLAC + JSON)?
4. **Live position.** SDS100 already supports GPS + ZIP-driven
   activation. PC has no built-in GPS; do we accept manual
   coordinates, gpsd, or a phone bridge?

## Next steps if/when this gets prioritised

1. Spike: SDRTrunk control via its REST/zeromq surface from a
   Python prototype. End goal: programmatically load a generated
   `.playlist` and read back call events.
2. Spike: HPDB -> SDRTrunk playlist transcoder that round-trips a
   user's SDS100 favorites.
3. UX mock: GLG-equivalent live-RX panel showing (TGID, system,
   alias, RSSI, decoder) - with the data sourced from SDRTrunk's
   call stream.
4. Promote to a real workstream + milestone if all three spikes
   succeed.
