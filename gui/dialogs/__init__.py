"""Qt port of the secondary Scanner Manager dialogs.

Phase 6 cutover surface:

- :mod:`workspaces` - WorkspaceManagerDialog (load / save named workspaces)
- :mod:`profile_snapshots` - ProfileSnapshotsDialog (snapshot / restore)
- :mod:`changes` - ChangesPanelDialog (recent change log via metastore)
- :mod:`sync_conflict` - SyncConflictDialog (resolve metastore conflicts)
- :mod:`city_manager` - CityManagerDialog (custom ZIP/county overrides)
- :mod:`uniden_tools` - UnidenToolsDialog (Sentinel / BT885 UM launcher)
- :mod:`update_available` - UpdateAvailableDialog (Scanner Manager self-update)
- :mod:`report_issue` - ReportIssueDialog (Help -> Report Issue, opens
  GitHub Issues with a templated bug report)

Each dialog is a QDialog driven by the existing backend modules
(``metastore``, ``updater``, ``uniden_tools``) so the Tk dialogs in
``scanner_manager.py`` can be retired as soon as the Qt shell is the
default entry.
"""

from __future__ import annotations

__all__ = [
    "workspaces",
    "profile_snapshots",
    "changes",
    "sync_conflict",
    "city_manager",
    "uniden_tools",
    "update_available",
    "report_issue",
]
