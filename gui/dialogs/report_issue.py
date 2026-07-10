"""Help -> Report Issue dialog (Qt context).

Collects free-form bug-report text, attaches the most recent crash log
if one exists, and opens the templated GitHub Issues new-issue URL in
the user's browser. The crash log path comes from the same
``_crash_log_dir()`` the global excepthook in :mod:`gui.app` writes to.
"""

from __future__ import annotations

import logging
import platform
import sys
import urllib.parse
import webbrowser
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

logger = logging.getLogger(__name__)

ISSUES_NEW_URL = "https://github.com/disturbedkh/scanner-manager/issues/new"


def _crash_log_dir() -> Path:
    from core.paths import state_dir

    return state_dir() / "crash"


def find_latest_crash_log() -> Optional[Path]:
    base = _crash_log_dir()
    if not base.exists():
        return None
    logs = sorted(base.glob("crash-*.log"), reverse=True)
    return logs[0] if logs else None


def _system_summary() -> str:
    return (
        f"OS:        {platform.platform()}\n"
        f"Python:    {sys.version.splitlines()[0]}\n"
        f"Frozen:    {bool(getattr(sys, 'frozen', False))}\n"
        f"Argv:      {' '.join(sys.argv)}\n"
    )


def _read_app_version() -> str:
    try:
        from importlib.metadata import PackageNotFoundError, version
        try:
            return version("beartracker-885-scanner-manager")
        except PackageNotFoundError:
            pass
    except Exception:
        pass
    return "dev"


class ReportIssueDialog(QDialog):
    """Help -> Report Issue."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Report an issue")
        self.resize(640, 540)
        self._latest_crash = find_latest_crash_log()
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("<b>What went wrong?</b>"))
        layout.addWidget(QLabel(
            "Describe what you were doing and what you expected. "
            "Steps to reproduce help us a lot."
        ))

        self._description = QTextEdit()
        self._description.setPlaceholderText(
            "I clicked X, expected Y, got Z..."
        )
        layout.addWidget(self._description, 1)

        self._include_system = QCheckBox("Include system info (OS, Python version)")
        self._include_system.setChecked(True)
        layout.addWidget(self._include_system)

        self._include_crash = QCheckBox()
        if self._latest_crash:
            self._include_crash.setText(f"Include latest crash log ({self._latest_crash.name})")
            self._include_crash.setChecked(True)
        else:
            self._include_crash.setText("(no crash log found)")
            self._include_crash.setChecked(False)
            self._include_crash.setEnabled(False)
        layout.addWidget(self._include_crash)

        button_row = QHBoxLayout()
        copy_btn = QPushButton("Copy details")
        copy_btn.clicked.connect(self._on_copy)
        button_row.addWidget(copy_btn)

        button_row.addStretch(1)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_row.addWidget(cancel_btn)

        open_btn = QPushButton("Open in GitHub")
        open_btn.clicked.connect(self._on_open)
        open_btn.setDefault(True)
        button_row.addWidget(open_btn)
        layout.addLayout(button_row)

    def _build_body(self) -> str:
        parts = [self._description.toPlainText().strip(), ""]
        if self._include_system.isChecked():
            parts.extend(["", "## Environment", "```", _system_summary(),
                          f"App version: {_read_app_version()}", "```"])
        if self._include_crash.isChecked() and self._latest_crash is not None:
            parts.append("")
            parts.append(f"## Latest crash log ({self._latest_crash.name})")
            parts.append("```")
            try:
                parts.append(self._latest_crash.read_text(encoding="utf-8", errors="replace")[:8000])
            except Exception as exc:  # noqa: BLE001
                parts.append(f"<could not read crash log: {exc}>")
            parts.append("```")
        return "\n".join(parts)

    def _on_copy(self) -> None:
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(self._build_body())
        QMessageBox.information(self, "Copied", "Issue details copied to clipboard.")

    def _on_open(self) -> None:
        body = self._build_body()
        title = self._description.toPlainText().strip().splitlines()[0:1]
        title_text = title[0][:80] if title else "Bug report"
        params = urllib.parse.urlencode({"title": title_text, "body": body})
        webbrowser.open(f"{ISSUES_NEW_URL}?{params}")
        self.accept()
