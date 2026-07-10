# Scanner Manager user-facing style guide

> Status: shipped (v0.11.x) — rubric for UI strings and wiki/README copy,
> plus the **language-expansion matrix** used by doc-lane agents.
> Applies to [`wiki/`](../../wiki/) pages, root README, and Qt UI.
> Contributor ops checklists in this directory stay **L1** (not L4 prose).

This document is the rubric for every string the user sees —
button labels, tooltips, dialog bodies, status bar messages, and
everything in `wiki/` and the root README. If you're writing help text
or editing the UI, run your draft past the rules below before committing.

Doc-lane standing prompts: [`.cursor/agents/docs-*.md`](../../.cursor/agents/).

## Language-expansion matrix (L0–L4)

| Level | Name | Audience | Expansion | Forbidden in lead |
| --- | --- | --- | --- | --- |
| **L4** | Human front door | End users (computer-competent, not developers) | Full progressive disclosure: outcome → prerequisites → steps → pitfalls → optional Internals | Class names, opcodes, CI jargon (SSOT, lockfile), import paths |
| **L3** | Human feature / help | Same + power users | Same as L4; more detail OK after first screen; Glossary links for jargon | Internals in first paragraph |
| **L2** | Contributor narrative | Humans who will extend the project | Plain lead-in, then technical depth; status tables; lab links | Assuming reader already knows MCU/USB vocabulary without a one-line gloss |
| **L1** | Ops checklist | Release cutters / profile authors | Imperative checklists, tables, code pointers; minimal storytelling | Feature walkthroughs that belong in wiki |
| **L0** | AI / agent notebook | Cursor agents + multi-machine humans scanning fast | Terse bullets, tables, paths, commands; no tutorial prose | End-user “how to click” narratives; marketing tone |

**Mandatory for L4/L3:** Rules 1–2 below. **Recommended for L2 leads.**

## Wiki / README page template (L4 / L3)

Use this skeleton for user-facing pages:

1. **Status banner** — `> Status: shipped (v0.11.x)` (or `active plan` / `historical`).
2. **Opening (1–3 sentences)** — what you can do; no jargon, or define it immediately.
3. **Prerequisites** — what you need (SD card, USB mode, OS). Assume computer competency (unzip, file explorer, USB) but not developer skills.
4. **Steps** — numbered; use **exact Qt UI labels** the user sees.
5. **If something goes wrong** — short bullets + link to [Troubleshooting](https://github.com/disturbedkh/scanner-manager/wiki/Troubleshooting).
6. **Optional Internals / For contributors** — at the bottom only (Rule 2).

Prefer `0.11.x` over pinning `v0.11.1` unless a release-specific fact requires `v0.11.2`.

Qt shell is the default path; put legacy Tk in a short **Classic Tk shell** callout.

## Rule 1: Lead with the user outcome

Tell the user *what the control does for them*, then (only if
helpful) how it works under the hood.

Bad:

> Service type (overwrites user button mapping)

Good:

> Service type (changes which scanner button plays this channel)

Bad:

> Pipeline: green / amber / red

Good:

> Update pipeline: Ready / Needs attention / Blocked

## Rule 2: Internals go under an "Internals" heading

Opcodes, constants, class names, file-format field names, hash
prefixes, and `txn_id`-style identifiers are internal. They're fine
in developer docs and great in the **Architecture** page and in
each wiki page's **Internals** section at the bottom, but they
should never appear in the first paragraph of a user-facing page,
in a button label, or in a tooltip.

Bad (top of page):

> A multi-hundred-entry import would normally produce one
> MetaStore event per added row. Instead, Scanner Manager enters
> a batch with `log=False` and records one composite
> `OP_IMPORT_APPLY` event...

Good (top of page):

> The whole import is recorded as **one** entry in the Change
> History, so one **Revert** click rolls everything back.
>
> ...
>
> ## Internals
>
> Import events are typed `OP_IMPORT_APPLY` and share a `txn_id`
> with every row the import touched.

## Rule 3: No scaffolding phrases, no dev shorthand

Never ship text that reads like a code comment you meant to clean up.
Call out concrete, meaningful information. Phrases flagged by CI:

- `"green like 2/3/4"` / `"like 2,3,4"` - these are developer
  pattern-matching shorthand, not user info.
- `"BulkRemapDialog"` / `"AvoidStripDialog"` / any dialog *class*
  name in user copy. Use the menu / button label the user clicked.
- `"txn_id"` - if you need to talk about grouped events, say "grouped"
  or "bundled".
- `"ADD_CFREQ"` / `"OP_IMPORT_APPLY"` / other opcode strings - move
  these to the **Internals** section.
- `"cid=123"` / URL-parameter snippets as user instructions - tell
  the user to paste the full URL from their browser instead.
- `"(D) = P25 Phase I FDMA"` or other acronym-first explanations as
  the *first* line of a tooltip or dialog.
- `"same as N"` when describing one button / service type's
  relationship to another - explain each independently.

## Acceptance rubric (doc reform)

- No stale `v0.11.1` where product is `0.11.x` / `v0.11.2` (except changelog).
- No “design only / not implemented” for shipped features.
- `AGENTS.md` / WORKSTREAMS headlines match `Metacache/Dev/WORKSTREAMS.md`.
- First screen of every L3/L4 page passes Rules 1–2.
- After wiki clusters: `python scripts/check_wiki_tone.py` is clean.

## When in doubt

Ask: "If my non-technical friend read this out of context, would they
know what to do?" If not, rewrite.
