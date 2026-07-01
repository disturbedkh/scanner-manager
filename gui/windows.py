"""Standalone top-level windows that live alongside MainWindow.

These are full QMainWindows (not QDialogs / QDockWidgets) so the user
can resize, maximize, and arrange them as independent screens. Each
window holds a single child widget that's owned (or borrowed) by
MainWindow; closing a window does not destroy the child, it just
re-parents it back to its original home.

Today this module hosts:

- :class:`CoverageWindow` - shows the CoveragePanel as its own window.
  Opened from View > Coverage / heatmap… for all profiles.
- :class:`LogWindow` - shows the app log as its own window so users
  can park it on a second monitor while the main window holds the
  editor + live mirror.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QPlainTextEdit,
    QStatusBar,
    QToolBar,
    QWidget,
)


class CoverageWindow(QMainWindow):
    """Detached coverage / heatmap / map window.

    The window does not own the CoveragePanel - it borrows it from
    MainWindow's hidden host. On close, the panel is returned
    (re-parented) to that host.
    """

    closed = Signal()

    def __init__(
        self,
        coverage_widget: QWidget,
        original_parent: Optional[QWidget] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Coverage / heatmap")
        self.resize(900, 720)
        self._coverage = coverage_widget
        self._original_parent = original_parent

        toolbar = QToolBar()
        refresh_action = QAction("Refresh coverage", self)
        refresh_action.triggered.connect(self._on_refresh)
        toolbar.addAction(refresh_action)
        self.addToolBar(toolbar)

        # Take ownership for the lifetime of the window
        self._coverage.setParent(self)
        self.setCentralWidget(self._coverage)

        bar = QStatusBar()
        bar.showMessage("View menu popout; close to hide.")
        self.setStatusBar(bar)

    def _on_refresh(self) -> None:
        refresh = getattr(self._coverage, "refresh_from_hpdb", None)
        if callable(refresh):
            refresh()

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        # Return the coverage widget to its hidden host.
        if self._original_parent is not None:
            try:
                self._coverage.setParent(self._original_parent)
            except Exception:
                pass
        self.closed.emit()
        super().closeEvent(event)


class LogWindow(QMainWindow):
    """Detached app-log window.

    Mirrors writes from a QPlainTextEdit owned by MainWindow without
    duplicating storage - we install a Qt handler that calls
    :meth:`append` on this window's view.
    """

    closed = Signal()

    def __init__(self, log_view: QPlainTextEdit, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Scanner Manager - Log")
        self.resize(720, 480)
        self._log_view = log_view

        toolbar = QToolBar()
        clear_action = QAction("Clear", self)
        clear_action.triggered.connect(self._log_view.clear)
        toolbar.addAction(clear_action)

        copy_action = QAction("Copy all", self)
        copy_action.triggered.connect(self._on_copy_all)
        toolbar.addAction(copy_action)
        self.addToolBar(toolbar)

        # Re-parent the log view into this window. When the window is
        # closed we keep the view alive (it just becomes parentless)
        # so MainWindow can re-attach it on demand.
        self._log_view.setParent(self)
        self.setCentralWidget(self._log_view)

    def _on_copy_all(self) -> None:
        QApplication.clipboard().setText(self._log_view.toPlainText())

    def closeEvent(self, event) -> None:  # noqa: N802
        self.closed.emit()
        super().closeEvent(event)


class FirmwareWindow(QMainWindow):
    """Detached firmware updater window.

    Borrows the FirmwareDock from MainWindow and re-parents it into a
    standalone window. On close the widget is returned to its original
    parent so its state (selected device, downloaded cache, etc.)
    survives across open / close cycles.

    Launched from MainWindow's Tools menu and only enabled when the
    user is in Storage mode (the radio cannot expose its SD card while
    in Serial Mode, so a firmware update would fail with a "device
    busy" error).
    """

    closed = Signal()

    def __init__(
        self,
        firmware_widget: QWidget,
        original_parent: Optional[QWidget] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Firmware updater")
        self.resize(960, 720)
        self._firmware = firmware_widget
        self._original_parent = original_parent

        bar = QStatusBar()
        bar.showMessage(
            "Firmware updater - SDS100/200 (Sentinel FTP) and BT885 (BT885 FTP). "
            "Close this window to return the panel to its hidden home."
        )
        self.setStatusBar(bar)

        # Re-parent firmware widget for the lifetime of the window
        self._firmware.setParent(self)
        self.setCentralWidget(self._firmware)

    def showEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        on_shown = getattr(self._firmware, "on_firmware_window_shown", None)
        if callable(on_shown):
            on_shown()
        super().showEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._original_parent is not None:
            try:
                self._firmware.setParent(self._original_parent)
            except Exception:
                pass
        self.closed.emit()
        super().closeEvent(event)
