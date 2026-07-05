# Scanner Manager user-facing style guide

> Status: shipped (v0.11.x) — rubric for UI strings and wiki copy.
> Applies to [`wiki/`](../../wiki/) pages and Qt UI; not contributor ops
> checklists in this directory.

This document is the rubric for every string the user sees -
button labels, tooltips, dialog bodies, status bar messages, and
everything in `wiki/`. If you're writing help text or editing the
UI, run your draft past the three rules below before committing.

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

## When in doubt

Ask: "If my non-technical friend read this out of context, would they
know what to do?" If not, rewrite.
