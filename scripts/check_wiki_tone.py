#!/usr/bin/env python3
"""Tone linter for wiki/*.md and selected UI copy.

Fails the build when user-facing documentation contains developer
shorthand that's been called out in Metacache/docs/style-guide.md. The rule set
is intentionally narrow and explicit: add to ``DENYLIST`` only after a
language review, never to silence a lint failure on a one-off page.

Internals sections (everything under a top-level ``## Internals``
heading) are allowed to use developer terms. The linter skips
anything after that heading so authors can park implementation notes
at the bottom of the page without triggering.

Usage::

    python scripts/check_wiki_tone.py
    python scripts/check_wiki_tone.py wiki/My-Page.md
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterable, List, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
WIKI_DIR = REPO_ROOT / "wiki"

DENYLIST: List[str] = [
    "green like",
    "like 2,3,4",
    "like 2/3/4",
    "BulkRemapDialog",
    "AvoidStripDialog",
    "txn_id",
    "ADD_CFREQ",
    "ADD_TGID",
    "OP_IMPORT_APPLY",
    "OP_EDIT_ENTRY",
    "cid=123",
    "(D) = P25 Phase I FDMA",
    "(T) = P25 Phase II TDMA",
    "FDMA",
    "TDMA",
    "same as 2",
    "same as 3",
    "same as 4",
    "same as 14",
]

ALLOWED_AFTER_HEADING = "## Internals"

# Pages that are developer-facing by design. These are exempt from the
# tone check because their entire purpose is to explain the internals.
DEVELOPER_PAGES = {
    "Architecture.md",
}


def _split_body_and_internals(text: str) -> str:
    """Return only the body of the doc, stripping everything under
    the first top-level ``## Internals`` heading.
    """
    lines = text.splitlines()
    out: List[str] = []
    in_internals = False
    for line in lines:
        if line.strip() == ALLOWED_AFTER_HEADING:
            in_internals = True
            continue
        if in_internals:
            if line.startswith("## ") and line.strip() != ALLOWED_AFTER_HEADING:
                in_internals = False
            else:
                continue
        out.append(line)
    return "\n".join(out)


def _scan(path: Path) -> List[Tuple[int, str, str]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    body = _split_body_and_internals(text)
    hits: List[Tuple[int, str, str]] = []
    for lineno, raw in enumerate(body.splitlines(), start=1):
        for needle in DENYLIST:
            if needle in raw:
                hits.append((lineno, needle, raw.strip()))
    return hits


def _targets(argv: Iterable[str]) -> List[Path]:
    args = list(argv)
    if args:
        return [Path(a) for a in args]
    return sorted(WIKI_DIR.glob("*.md"))


def main(argv: List[str]) -> int:
    targets = _targets(argv)
    failed = False
    for path in targets:
        if not path.exists():
            print(f"warning: {path} does not exist, skipping")
            continue
        if path.name in DEVELOPER_PAGES:
            continue
        hits = _scan(path)
        if hits:
            failed = True
            print(f"\n{path}:")
            for lineno, needle, line in hits:
                print(f"  line {lineno}: {needle!r}")
                print(f"    > {line}")
    if failed:
        print(
            "\nTone check failed. See Metacache/docs/style-guide.md for guidance,\n"
            "or move internals under a '## Internals' heading at the\n"
            "bottom of the page."
        )
        return 1
    print(f"Tone check passed ({len(targets)} file(s)).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
