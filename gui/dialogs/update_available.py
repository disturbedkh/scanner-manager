"""Qt port of the UpdateAvailableDialog.

Surfaces the result of :func:`updater.check_for_update`. Three modes:

- ``"available"`` - newer release found; offer Update Now + Open Page +
  Skip + Later.
- ``"current"`` - user manually checked, no newer version.
- ``"offline"`` - check failed (no network, GitHub down, etc.).

All network code lives in :mod:`updater`; the dialog is purely a thin
shell around :class:`updater.UpdateInfo`.
"""

from __future__ import annotations

import logging
import sys
import webbrowser
from typing import Optional

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

import updater

logger = logging.getLogger(__name__)

APP_RELEASES_URL = "https://github.com/disturbedkh/scanner-manager/releases"


class UpdateAvailableDialog(QDialog):
    """Surface the result of an update check (one of three modes)."""

    MODE_AVAILABLE = "available"
    MODE_CURRENT = "current"
    MODE_OFFLINE = "offline"

    def __init__(
        self,
        info: Optional[updater.UpdateInfo],
        current_version: str,
        mode: str = MODE_AVAILABLE,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Scanner Manager update")
        self.resize(620, 460)
        self._info = info
        self._mode = mode
        self._current = current_version
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        if self._mode == self.MODE_CURRENT:
            headline = f"You're on the latest version, v{self._current}."
        elif self._mode == self.MODE_OFFLINE:
            headline = "Couldn't reach GitHub to check for updates."
        else:
            new = self._info.version if self._info else "?"
            headline = f"Update available: v{self._current} -> v{new}"
        title = QLabel(f"<b>{headline}</b>")
        title.setStyleSheet("font-size: 13px;")
        layout.addWidget(title)

        body = QTextEdit()
        body.setReadOnly(True)
        if self._mode == self.MODE_AVAILABLE and self._info is not None:
            body.setPlainText((self._info.body or "Release notes unavailable.").strip())
        elif self._mode == self.MODE_CURRENT:
            body.setPlainText(
                "No newer release is published on GitHub.\n\n"
                f"You can always grab the source or a fresh build from\n{APP_RELEASES_URL}"
            )
        else:
            body.setPlainText(
                "Scanner Manager couldn't contact GitHub. Your network may "
                "be offline, proxied, or the service may be temporarily "
                "unavailable.\n\n"
                f"You can download updates manually from\n{APP_RELEASES_URL}"
            )
        layout.addWidget(body, 1)

        button_row = QHBoxLayout()
        if self._mode == self.MODE_AVAILABLE and self._info is not None:
            update_btn = QPushButton("Update Now")
            update_btn.clicked.connect(self._on_update_now)
            button_row.addWidget(update_btn)

        page_btn = QPushButton("Open Release Page")
        page_btn.clicked.connect(self._on_open_release)
        button_row.addWidget(page_btn)

        if self._mode == self.MODE_AVAILABLE:
            later_btn = QPushButton("Remind Me Later")
            later_btn.clicked.connect(self.reject)
            button_row.addWidget(later_btn)

        button_row.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        button_row.addWidget(close_btn)
        layout.addLayout(button_row)

    def _on_update_now(self) -> None:
        if self._info is None:
            self.accept()
            return
        # In-place swap currently targets Windows-frozen builds. On other
        # platforms we direct the user to the release page.
        if sys.platform != "win32" or not getattr(sys, "frozen", False):
            self._on_open_release()
            return
        webbrowser.open(self._info.html_url or APP_RELEASES_URL)
        QMessageBox.information(
            self, "Manual update",
            "Download the new EXE from the release page and replace this one. "
            "In-place swap is staged for a future release."
        )
        self.accept()

    def _on_open_release(self) -> None:
        target = (self._info.html_url if self._info else "") or APP_RELEASES_URL
        webbrowser.open(target)
