"""Virtual SD card subsystem.

A *virtual SD card* is a filesystem-side staging area that mirrors the
layout of a physical Uniden scanner SD card. It exists so the operator
can pre-build firmware updates, HPDB refreshes, or favorites edits
**before** committing them to the physical card - which is the only
way to safely flash firmware (the SDS100 will brick if a write is
interrupted mid-flash).

The two top-level concepts:

- :class:`VirtualCard` - one per :class:`device_manager.Device`. Owns
  a staging folder under the XDG data dir
  (``core.paths.virtual_sd_root()``, typically
  ``~/.local/share/scanner-manager/virtual-cards/<id>/`` on Linux)
  and a manifest file (``.staged.json``) that lets us round-trip
  arbitrary metadata (source URL, what type of payload it is, who
  staged it, etc.) across app restarts.

- :class:`StagedFile` - one row in the manifest. Carries enough
  metadata for the firmware updater wizard to validate the staged
  payload before flashing (kind, sha256, source URL, original
  filename, etc.).

The "reconcile HPDB" piece - merging Uniden's official HPDB updates
with the user's in-place edits without losing either side - is the
hardest part of the BT885 workflow. It is intentionally not
implemented in this first cut: HPDB-class staged files are copied
verbatim, and the operator gets a warning telling them to re-run
the editor's Audit dialog after applying.

The legacy Tk app's metastore-driven event-replay path
(``scanner_manager.py::ScannerManagerApp._on_run_updater_and_reconcile``)
is the long-term blueprint for that workflow; this module is the
first PySide6 surface that even has a place to plug it in.
"""

from __future__ import annotations

from .virtual_card import (
    StagedFile,
    StageKind,
    VirtualCard,
    VirtualCardError,
    default_root_dir,
)

__all__ = [
    "StagedFile",
    "StageKind",
    "VirtualCard",
    "VirtualCardError",
    "default_root_dir",
]
