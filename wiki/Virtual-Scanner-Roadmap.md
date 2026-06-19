# Virtual scanner: roadmap

> Where this fits: forward-looking roadmap for an SDR-backed
> "software SDS100" that reuses our existing RE work as a
> compatibility layer. For the consolidated narrative start at
> [Reverse Engineering](Reverse-Engineering).
>
> **Status: exploratory.** This is a "what would it take to..."
> sketch, not a tracked workstream. Source plan:
> [`Metacache/Dev/RE/plans/virtual_scanner.md`](https://github.com/your-org/your-repo/blob/main/Metacache/Dev/RE/plans/virtual_scanner.md)
> (replace with the canonical repo path once forked).

## TL;DR

A virtual SDS100 is feasible **as a compatibility-and-UX layer over
an existing open-source SDR/decoder stack**, not as a ground-up
reimplementation of the Uniden DSP pipeline. The user plugs in an
RTL-SDR (or Airspy / HackRF / SDRplay), points our app at it, and
sees the same favorites + scan workflow they'd see with a real
SDS100 - except the radio is software, the audio comes from
SDRTrunk / OP25 / DSDplus, and the compute headroom is whatever
laptop they're on.

## Why bother?

- **No hardware lock-in.** $30 RTL-SDR vs. $700 SDS100 for a casual
  user; same UX surface either way.
- **PC-class compute.** Waterfalls, parallel-decode every active
  TGID, replay across recordings, etc. - things the embedded SUB
  MCU can't physically do.
- **Same data model.** Favorites / HPDB / GLT / GSI XML / ZIP
  coverage all already round-trip thanks to our RE work. A user's
  workspace ports between physical and virtual scanner without
  conversion.

## The three feasibility tiers

| Tier | Approach | Effort | Recommended? |
|---|---|---|---|
| **A** | "Sentinel for SDR" - drive an existing OSS decoder (SDRTrunk / OP25 / DSDplus) from our app via its existing IPC | Medium | **Yes - start here** |
| **B** | GNU Radio top-block configurator with our own scan-state machine, leveraging gr-dsd / gr-dmr / gr-osmosdr | Large | Maybe later |
| **C** | Reimplement the SUB DSP pipeline (R840 -> FFT -> filter chain -> decoder) in software | Very large | Research-only |

Full reasoning - layer-by-layer breakdown, decoder choice, GLG
mapping, license risk, packaging risk - lives in
`Metacache/Dev/RE/plans/virtual_scanner.md`. This page is the wiki-facing
TL;DR; the plan file is the authoritative spec.

## What from existing RE work feeds straight in

| Wiki page | Used for |
|---|---|
| [RE-SD-Card](RE-SD-Card) + [RE-Sentinel](RE-Sentinel) | favorites / HPDB / scanner.cfg parsers we already use end-to-end |
| [RE-Serial-Protocol](RE-Serial-Protocol) (GLG / GSI / STS) | UI/UX surface to mirror in software |
| [RE-Firmware](RE-Firmware) (R840, FFT, noise-squelch format strings) | informs Tier C only |
| [RE-Inter-MCU-Bus](RE-Inter-MCU-Bus) | informs Tier C only |

## Recommended starting spike

1. Get SDRTrunk running standalone with an RTL-SDR.
2. Generate a SDRTrunk `.playlist` from a user's HPDB favorites
   (Python prototype, no UI).
3. Subscribe to SDRTrunk's call-event stream (REST or zeromq) and
   render it in a GLG-equivalent panel in our app.
4. If those three steps succeed, promote to a real workstream and
   write a milestone.

## Risk register (summary)

| Risk | Mitigation |
|---|---|
| Encrypted talkgroups | Same limitation as a physical scanner; surface clearly. |
| Decoder churn / IPC breaking | Pin a known-good SDRTrunk version; integration-test on captured baseband. |
| GNU Radio packaging on Windows | Tier A doesn't need it; only kicks in if/when we move to Tier B. |
| Legal restrictions on scanning | Same as physical scanners. |

## Open questions

1. License compatibility (SDRTrunk is GPL-3, our app is MIT).
2. How completely SDRTrunk's call events map to the GLG schema.
3. Recording format choice (match SDS100 WAV layout vs. richer
   FLAC/JSON).
4. GPS source on a PC (manual, gpsd, phone bridge).

If any of those resolve cleanly, this moves from "exploratory" to
"prioritised". Until then, treat this page as a discussion artefact
- comments and counter-proposals welcome via GitHub Discussions
("Ideas" or "Tooling / Development" categories).
