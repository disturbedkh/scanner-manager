"""Qt-based GUI for Scanner Manager.

The Qt shell is the new top-level UI for the multi-scanner manager.
It replaces the single-file Tkinter app in ``scanner_manager.py``
incrementally - the legacy Tk app remains runnable as
``scanner-manager-tk`` until the cutover phase.

Top-level entry point: :func:`gui.app.main`.

Architecture (per ``Metacache/Dev/MULTI_DEVICE_GUI.md``):

- :mod:`gui.app` - QApplication entry, theme/style.
- :mod:`gui.main_window` - main window, dock layout, status bar, menu.
- :mod:`gui.header` - top device-selector bar.
- :mod:`gui.devices_dialog` - Add/Edit/Delete Device wizard.
- :mod:`gui.editor` - HPDB tree editor (Phase 2).
- :mod:`gui.live` - live serial-mode panel (Phase 3, SDS100/200 only).
- :mod:`gui.streaming` - audio capture + LAN listener + push (Phase 4).
- :mod:`gui.firmware` - firmware library + update wizard (Phase 5).
"""

from __future__ import annotations

__all__ = ["app", "main_window", "header", "devices_dialog"]
