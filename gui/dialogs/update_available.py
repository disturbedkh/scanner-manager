"""Qt port of the UpdateAvailableDialog.

Surfaces the result of :func:`updater.check_for_update`. Three modes:

- ``"available"`` - newer release found; offer Update Now + Open Page +
  Skip + Later.
- ``"current"`` - user manually checked, no newer version.
- ``"offline"`` - check failed (no network, GitHub down, etc.).

All network code lives in :mod:`core.app_updater`; the dialog is a thin
shell around :class:`updater.UpdateInfo`. Frozen Linux tar.gz/ELF builds
can Update Now in-place; AppImage / macOS / source installs open the
release page.
"""

from __future__ import annotations

import logging
import os
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

import core.app_updater as updater

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

        frozen = bool(getattr(sys, "frozen", False))
        if not frozen:
            self._on_open_release()
            return

        if updater.is_running_as_appimage():
            QMessageBox.information(
                self,
                "AppImage update",
                "In-place Update Now applies to the Linux tar.gz/ELF build.\n\n"
                "For AppImage installs, download the new "
                "ScannerManager-x86_64.AppImage from the release page and "
                "replace this file.",
            )
            self._on_open_release()
            return

        if sys.platform.startswith("linux"):
            self._apply_linux_frozen_update()
            return

        # Windows frozen: swap helper exists but dialog still directs to
        # the release page until Windows Update Now is fully wired.
        if sys.platform == "win32":
            webbrowser.open(self._info.html_url or APP_RELEASES_URL)
            QMessageBox.information(
                self,
                "Manual update",
                "Download the new EXE from the release page and replace this one. "
                "In-place swap is staged for a future release.",
            )
            self.accept()
            return

        # macOS frozen (and anything else)
        self._on_open_release()

    def _apply_linux_frozen_update(self) -> None:
        assert self._info is not None
        current = updater.frozen_executable_path()
        try:
            updater.install_linux_update_from_release(
                self._info,
                current,
            )
        except Exception as exc:  # noqa: BLE001 — surface any download/swap failure
            logger.exception("Linux in-place update failed")
            QMessageBox.critical(
                self,
                "Update failed",
                f"Could not download or apply the update:\n\n{exc}\n\n"
                "You can still use Open Release Page for a manual install.",
            )
            return
        QMessageBox.information(
            self,
            "Updating",
            "The update was downloaded and verified. Scanner Manager will "
            "restart with the new version.",
        )
        self.accept()
        os._exit(0)

    def _on_open_release(self) -> None:
        target = (self._info.html_url if self._info else "") or APP_RELEASES_URL
        webbrowser.open(target)
