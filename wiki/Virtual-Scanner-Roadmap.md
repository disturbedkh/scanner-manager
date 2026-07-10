# Virtual scanner: roadmap

> Status: active plan (v0.11.x) — exploratory sketch, not a tracked workstream.

> Where this fits: forward-looking SDR-backed “software SDS100” that
> reuses existing RE as a compatibility layer. Start at
> [Reverse Engineering](Reverse-Engineering).

## What this answers

Whether a virtual SDS100 is worth pursuing, which feasibility tier
to start with, and which existing RE surfaces feed the design —
without treating this as a committed milestone.

## Known vs OPEN

| Topic | State | Notes |
|---|---|---|
| Tier A/B/C feasibility sketch | DONE (plan) | Lab plan is SSOT |
| Recommended start = Tier A (SDRTrunk/OP25 IPC) | Proposed | Not scheduled |
| GPL-3 (SDRTrunk) vs app license | OPEN | |
| GLG ↔ decoder call-event mapping | OPEN | |
| Recording format choice | OPEN | |
| PC GPS source | OPEN | |

## Deep dive

### TL;DR

A virtual SDS100 is feasible as a **compatibility-and-UX layer over
an existing OSS SDR/decoder stack**, not as a ground-up Uniden DSP
reimplementation. User plugs in RTL-SDR (or Airspy / HackRF /
SDRplay), points the app at it, and keeps favorites / scan workflow
while audio/decode come from SDRTrunk / OP25 / DSDplus.

### Why bother?

- No hardware lock-in ($30 dongle vs $700 scanner) with the same UX.
- PC-class compute (parallel TGID decode, rich waterfalls, replay).
- Same data model — HPDB / favorites / GSI-shaped UI already RE’d.

### Three feasibility tiers

| Tier | Approach | Effort | Recommended? |
|---|---|---|---|
| **A** | Drive OSS decoder (SDRTrunk / OP25 / DSDplus) via existing IPC | Medium | **Yes — start here** |
| **B** | GNU Radio top-block + our scan-state machine | Large | Later |
| **C** | Reimplement SUB DSP pipeline in software | Very large | Research-only |

Full layer-by-layer reasoning, decoder choice, license/packaging
risk: **`Metacache/Dev/RE/plans/virtual_scanner.md`** (authoritative).
This page is the wiki TL;DR.

### What existing RE feeds in

| Wiki page | Used for |
|---|---|
| [RE-SD-Card](RE-SD-Card) + [RE-Sentinel](RE-Sentinel) | Favorites / HPDB parsers |
| [RE-Serial-Protocol](RE-Serial-Protocol) (GLG / GSI / STS) | UI surface to mirror |
| [RE-Firmware](RE-Firmware) (R840 / FFT strings) | Tier C only |
| [RE-Inter-MCU-Bus](RE-Inter-MCU-Bus) | Tier C only |

### Recommended starting spike

1. SDRTrunk standalone + RTL-SDR.
2. Generate SDRTrunk `.playlist` from HPDB favorites (Python, no UI).
3. Subscribe to call-event stream; render GLG-equivalent panel.
4. If green, promote to a real workstream + milestones.

### Risk register (summary)

| Risk | Mitigation |
|---|---|
| Encrypted talkgroups | Same as physical scanner; surface clearly |
| Decoder IPC churn | Pin known-good version; test on captured baseband |
| GNU Radio on Windows | Tier A avoids it |
| Legal scanning limits | Same as physical |

Until open questions resolve, treat this as a discussion artefact
(GitHub Discussions: Ideas / Tooling).

## Lab pointers

| Path | Role |
|---|---|
| `Metacache/Dev/RE/plans/virtual_scanner.md` | **SSOT** full plan |
| `Metacache/Dev/RE/plans/README.md` | Plans index |
| `Metacache/Dev/RE/docs/SDS100_unofficial_commands.md` | GLG / GSI field notes |
| `Metacache/Dev/RE/docs/SDS100.md` | SD + serial context for compatibility surface |
