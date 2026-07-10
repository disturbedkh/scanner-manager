# Dev Notes

> Status: **active plan** — shared agent + developer notebook for
> `Metacache/Dev/`. Read before touching profiles, GUI, or firmware.

**End users → [`wiki/`](../../wiki/)** (L4/L3). This tree is L0 agent notebook.

This folder (`Metacache/Dev/`) is the **shared brain** for AI agents (Cursor) and human
developers working on `scanner-manager` from multiple machines and chat
sessions. Anything that needs to survive a session reset, hop between
desktops, or get picked up by a fresh Cursor agent goes here.

**Documentation layers** (see also [`Metacache/README.md`](../README.md) — IA
charter owned by ops docs; L0–L4 matrix: [`../docs/style-guide.md`](../docs/style-guide.md)):

| Layer | Path | Audience | Lang |
| --- | --- | --- | --- |
| User wiki | `wiki/` | Feature tours, quickstart, troubleshooting | L4/L3 |
| Contributor ops | `Metacache/docs/` | Release checklist, formats, style | L1 |
| Agent notebook | `Metacache/Dev/` (this tree, excl. deep RE) | PROJECT_STATE, WORKSTREAMS, as-built refs | L0 |
| RE lab | `Metacache/Dev/RE/` | Session logs, catalogs — **facts win over wiki** | L0/L2 |

User-facing ops docs live in sibling [`../docs/`](../docs/) under Metacache.

**Archive policy**

| Artifact | Policy |
| --- | --- |
| `WORKER_LOG.md` | **Append-only** — newest on top; do not rewrite/delete history |
| `REVIEW_YYYY-MM.md` | **Historical** snapshot of a doc-refresh wave; fix factual residuals only |

> If you are a Cursor agent landing in this repo for the first time:
> **read this entire folder before doing anything**, in the order
> below.

## Read order on session start

1. `PROJECT_STATE.md` - one-screen snapshot of where the project is
   right now (latest commit, layout, what runs, what's broken).
2. `WORKSTREAMS.md` - active workstreams with owners and status.
   Headline shipped areas: **multi-scanner profiles**, **multi-device Qt
   header**, **firmware updater**, **streaming** (`v0.11.x beta`).
3. `MULTI_SCANNER_BACKEND.md` - required before touching
   `scanner_profiles/`, `set_active_profile()`, or HPD `TargetModel`
   parsing. Covers `detect_from_card()` and both shipping profiles.
4. As-built GUI/firmware refs (when relevant):
   - `MULTI_DEVICE_GUI.md` — header device selector, Live/Storage gating.
   - `FIRMWARE_UPDATER.md` — FTP discovery + SD-card update workflow.
5. `RE/` - reverse-engineering notes per scanner model **plus live
   probe tooling**. Start with `RE/README.md`, then read any
   per-scanner file relevant to your task (`RE/docs/SDS100.md` for
   SDS100/SDS200 work, `RE/docs/BT885.md` for BT885, etc.). These are
   the canonical "what does the scanner actually write to disk and over
   the wire" reference.
   - `RE/tools/probes/serial_probe.py` + legacy `RE/tools/legacy/com6_listen.py`
     are READ-ONLY probe scripts. Always run them through `RE/README.md`'s
     instructions; never extend them with a write-shape command without
     confirming in the Uniden Operation Specification that it is query-only.
   - `RE/sessions/` contains raw timestamped probe captures. They
     are committed so you can re-derive analysis without re-running
     the probe against a connected scanner.
6. `MACHINES.md` - per-desktop quirks (paths, Python versions, OS).
   Find your hostname; if it's not there, add it.
7. `WORKER_LOG.md` - append-only log of meaningful sessions and
   decisions. Read the last few entries to see what just happened.
8. `CONVENTIONS.md` - house rules for editing this repo (lint, tests,
   commits, PRs, doc-layer obligations).
9. `CURSOR.md` - Cursor rules, skills, hooks, and MCP setup for this
   repo (also see root `AGENTS.md`).

Linux beta closeout / Ubuntu HIL checklist (when verifying a real
desktop install): `LINUX_BARE_METAL_HANDOFF.md`.

## Write order on session end

Before you stop working in a session, append to:

- `WORKER_LOG.md` - one entry: date, machine, agent, branch, what
  changed, what's next, blockers.
- Any of the topic docs above that you materially updated.

The format for log entries is shown at the top of `WORKER_LOG.md`.

## Why this folder exists

- **Cross-machine.** The user works from at least two desktops. Notes
  live in git so a `git pull` syncs them.
- **Cross-session.** A new Cursor chat has no memory of the last one;
  these files are the memory.
- **Cross-worker.** A second contributor started the multi-scanner
  backend. We need a place to track what they shipped, what's
  in-flight, and what we should not touch yet.

## Ground rules for agents

- **Don't edit code under `scanner_profiles/` without first reading
  `MULTI_SCANNER_BACKEND.md`.** That work has its own contract documented
  there.
- **Don't break parity.** `tests/test_bt885_parity.py` is the canary
  for the BT885 profile staying in sync with `legacy_tk/scanner_manager.py`
  module-level constants. SDS100: `tests/test_sds100_profile.py`.
- **Don't commit unless the user asks.** This repo's policy.
- **Update the docs you change.** If your change invalidates anything
  in this folder, fix it in the same session (see `CONVENTIONS.md` for
  which layer to edit).
