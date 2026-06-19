# Dev Notes

This folder (`Metacache/Dev/`) is the **shared brain** for AI agents (Cursor) and human
developers working on `scanner-manager` from multiple machines and chat
sessions. Anything that needs to survive a session reset, hop between
desktops, or get picked up by a fresh Cursor agent goes here.

User-facing docs live in sibling [`../docs/`](../docs/) under Metacache.

> If you are a Cursor agent landing in this repo for the first time:
> **read this entire folder before doing anything**, in the order
> below.

## Read order on session start

1. `PROJECT_STATE.md` - one-screen snapshot of where the project is
   right now (latest commit, layout, what runs, what's broken).
2. `WORKSTREAMS.md` - active workstreams with owners and status.
   Today the headline workstream is the **multi-scanner backend**.
3. `MULTI_SCANNER_BACKEND.md` - deep dive on the `scanner_profiles/`
   driver layer that another contributor started. Required reading
   before touching anything under `scanner_profiles/`,
   `scanner_manager.ACTIVE_PROFILE`, or HPD `TargetModel` parsing.
4. `RE/` - reverse-engineering notes per scanner model **plus live
   probe tooling**. Start with `RE/README.md`, then read any
   per-scanner file relevant to your task (`RE/SDS100.md` for
   SDS100/SDS200 work, etc.). These are the canonical "what does
   the scanner actually write to disk and over the wire" reference.
   - `RE/serial_probe.py` + `RE/com6_listen.py` are READ-ONLY probe
     scripts. Always run them through `RE/README.md`'s instructions;
     never extend them with a write-shape command without confirming
     in the Uniden Operation Specification that it is query-only.
   - `RE/sessions/` contains raw timestamped probe captures. They
     are committed so you can re-derive analysis without re-running
     the probe against a connected scanner.
5. `MACHINES.md` - per-desktop quirks (paths, Python versions, OS).
   Find your hostname; if it's not there, add it.
6. `WORKER_LOG.md` - append-only log of meaningful sessions and
   decisions. Read the last few entries to see what just happened.
7. `CONVENTIONS.md` - house rules for editing this repo (lint, tests,
   commits, PRs).
8. `CURSOR.md` - Cursor rules, skills, hooks, and MCP setup for this
   repo (also see root `AGENTS.md`).

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
  `MULTI_SCANNER_BACKEND.md`.** That work is in progress and has its
  own contract documented there.
- **Don't break parity.** `tests/test_bt885_parity.py` is the canary
  for the BT885 profile staying in sync with `scanner_manager.py`
  module-level constants. If you change one, change both.
- **Don't commit unless the user asks.** This repo's policy.
- **Update the docs you change.** If your change invalidates anything
  in this folder, fix it in the same session.
