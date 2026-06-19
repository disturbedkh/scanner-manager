"""Qt port of the SyncConflictDialog.

Surfaces a side-by-side comparison of two metastore baselines for the
same entry / group when a sync detects divergence. The user picks which
side wins (local or remote) or skips the conflict.
"""

from __future__ import annotations

import json
import logging
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

logger = logging.getLogger(__name__)


class SyncConflictDialog(QDialog):
    """Show one conflict at a time; emit the user's choice.

    ``conflicts`` is a list of dicts with keys::

        {"target_id": "...",
         "summary":   "...",
         "local":     {<baseline dict>},
         "remote":    {<baseline dict>}}
    """

    KEEP_LOCAL = "local"
    KEEP_REMOTE = "remote"
    SKIP = "skip"

    decisionMade = Signal(str, str)  # target_id, choice

    def __init__(self, conflicts: List[Dict], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Resolve sync conflicts")
        self.resize(900, 540)
        self._conflicts = list(conflicts)
        self._index = 0
        self._build_ui()
        self._render_current()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        self._header = QLabel()
        self._header.setStyleSheet("font-weight: bold;")
        layout.addWidget(self._header)

        body = QHBoxLayout()
        # Local
        local_box = QVBoxLayout()
        local_box.addWidget(QLabel("Local"))
        self._local_view = QTextEdit()
        self._local_view.setReadOnly(True)
        local_box.addWidget(self._local_view, 1)
        body.addLayout(local_box, 1)

        # Remote
        remote_box = QVBoxLayout()
        remote_box.addWidget(QLabel("Remote"))
        self._remote_view = QTextEdit()
        self._remote_view.setReadOnly(True)
        remote_box.addWidget(self._remote_view, 1)
        body.addLayout(remote_box, 1)

        layout.addLayout(body, 1)

        button_row = QHBoxLayout()
        keep_local = QPushButton("Keep Local")
        keep_local.clicked.connect(lambda: self._decide(self.KEEP_LOCAL))
        button_row.addWidget(keep_local)

        keep_remote = QPushButton("Keep Remote")
        keep_remote.clicked.connect(lambda: self._decide(self.KEEP_REMOTE))
        button_row.addWidget(keep_remote)

        skip_btn = QPushButton("Skip")
        skip_btn.clicked.connect(lambda: self._decide(self.SKIP))
        button_row.addWidget(skip_btn)

        button_row.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        button_row.addWidget(close_btn)
        layout.addLayout(button_row)

    def _render_current(self) -> None:
        if self._index >= len(self._conflicts):
            self.accept()
            return
        conflict = self._conflicts[self._index]
        self._header.setText(
            f"Conflict {self._index + 1} / {len(self._conflicts)} - "
            f"{conflict.get('summary', conflict.get('target_id', ''))}"
        )
        self._local_view.setPlainText(json.dumps(conflict.get("local", {}), indent=2, default=str))
        self._remote_view.setPlainText(json.dumps(conflict.get("remote", {}), indent=2, default=str))

    def _decide(self, choice: str) -> None:
        if self._index < len(self._conflicts):
            target = self._conflicts[self._index].get("target_id", "")
            self.decisionMade.emit(target, choice)
            self._index += 1
        self._render_current()
