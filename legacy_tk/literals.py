"""Shared UI and message string literals for legacy Tk (Sonar S1192)."""

from __future__ import annotations

# Tk event bindings
_LIT_COMBOBOX_SELECTED = "<<ComboboxSelected>>"
_LIT_TREEVIEW_SELECT = "<<TreeviewSelect>>"
_LIT_BUTTON_1 = "<Button-1>"

# Treeview layout
_LIT_TREE_HEADINGS = "tree headings"

# Form labels
_LIT_NAME_COLON = "Name:"
_LIT_MODE_COLON = "Mode:"
_LIT_FREQ_MHZ_COLON = "Frequency (MHz):"

# Location / county UI
_LIT_AUTO_FROM_ZIP = "(Auto from ZIP)"

# File dialogs
_LIT_EXE_GLOB = "*.exe"
_LIT_ALL_FILES = "All Files"

# Profile / workspace actions
_LIT_PROFILE_NOT_FOUND = "Profile not found."
_LIT_SWAP_PROFILE = "Swap Profile"
_LIT_RESTORE_SNAPSHOT = "Restore Snapshot"
_LIT_RESTORE_SESSION = "Restore Session"
_LIT_REVERT_TO_POINT = "Revert to point"

# Coverage / tools menu
_LIT_COVERAGE_HEATMAP = "Coverage Heatmap"
_LIT_COVERAGE_MAP = "Coverage Map"
_LIT_BULK_REMAP = "Bulk Remap"
_LIT_SELECT_TOOL_FIRST = "Select a tool first."

# Import / RR dialogs
_LIT_IMPORT_SELECTED = "Import Selected"
_LIT_RR_GROUP = "RadioReference Group"
_LIT_FETCH_ERROR = "Fetch Error"
_LIT_NO_FREQS_ON_PAGE = "No frequencies found on that page."
_LIT_NO_FREQUENCIES = "No Frequencies"

# HPD prerequisite messages
_LIT_LOAD_HPD_FIRST = "Load an HPD file first."

# HTML parsing regex fragments
_LIT_RE_TR_ROW = r"<tr[^>]*>(.*?)</tr>"
