"""Qt port of the WorkspaceManagerDialog.

A "workspace" is a named bundle of state that the user can switch
between: device list, RR credentials, recently-opened HPD files,
and preferred SD card paths. The Tk version reads / writes
``workspaces.json`` next to the executable; we keep the same on-disk
format so the two app shells can coexist for one release.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Persistence helpers
# ----------------------------------------------------------------------


def _default_workspaces_path() -> Path:
    """Return ``workspaces.json`` next to the user data directory."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    return base / "scanner-manager" / "workspaces.json"


@dataclass
class Workspace:
    name: str
    devices_path: str = ""
    notes: str = ""
    created: str = ""
    last_used: str = ""

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "devices_path": self.devices_path,
            "notes": self.notes,
            "created": self.created,
            "last_used": self.last_used,
        }

    @classmethod
    def from_dict(cls, raw: Dict) -> "Workspace":
        return cls(
            name=raw.get("name", "Unnamed"),
            devices_path=raw.get("devices_path", ""),
            notes=raw.get("notes", ""),
            created=raw.get("created", ""),
            last_used=raw.get("last_used", ""),
        )


def load_workspaces(path: Optional[Path] = None) -> List[Workspace]:
    target = Path(path) if path else _default_workspaces_path()
    if not target.exists():
        return []
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(raw, dict):
        return []
    return [Workspace.from_dict(entry) for entry in raw.get("workspaces", []) if isinstance(entry, dict)]


def save_workspaces(workspaces: List[Workspace], path: Optional[Path] = None) -> None:
    target = Path(path) if path else _default_workspaces_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": 1, "workspaces": [w.to_dict() for w in workspaces]}
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, target)


# ----------------------------------------------------------------------
# Dialog
# ----------------------------------------------------------------------


class WorkspaceManagerDialog(QDialog):
    """Manage named workspaces (create / rename / delete / load)."""

    workspaceLoaded = Signal(Workspace)

    def __init__(self, parent=None, path: Optional[Path] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Workspaces")
        self.resize(560, 420)
        self._path = Path(path) if path else _default_workspaces_path()
        self._workspaces: List[Workspace] = load_workspaces(self._path)
        self._build_ui()
        self._refresh_list()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("<b>Workspaces</b>"))
        layout.addWidget(QLabel(
            "A workspace bundles a devices.json + RR credentials so you "
            "can switch between e.g. a 'Home' and 'Travel' setup."
        ))

        self._list = QListWidget()
        self._list.itemDoubleClicked.connect(self._on_load)
        layout.addWidget(self._list, 1)

        button_row = QHBoxLayout()
        new_btn = QPushButton("New…")
        new_btn.clicked.connect(self._on_new)
        button_row.addWidget(new_btn)

        rename_btn = QPushButton("Rename…")
        rename_btn.clicked.connect(self._on_rename)
        button_row.addWidget(rename_btn)

        delete_btn = QPushButton("Delete")
        delete_btn.clicked.connect(self._on_delete)
        button_row.addWidget(delete_btn)

        button_row.addStretch(1)

        load_btn = QPushButton("Load")
        load_btn.clicked.connect(self._on_load)
        load_btn.setDefault(True)
        button_row.addWidget(load_btn)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        button_row.addWidget(close_btn)

        layout.addLayout(button_row)

    def _refresh_list(self) -> None:
        self._list.clear()
        for w in self._workspaces:
            text = w.name
            if w.last_used:
                text = f"{w.name}  ·  last used {w.last_used}"
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, w)
            self._list.addItem(item)

    def _selected(self) -> Optional[Workspace]:
        item = self._list.currentItem()
        return item.data(Qt.UserRole) if item else None

    def _persist(self) -> None:
        save_workspaces(self._workspaces, self._path)

    def _on_new(self) -> None:
        name, ok = QInputDialog.getText(self, "New workspace", "Name:")
        if not ok or not name.strip():
            return
        path, _filter = QFileDialog.getOpenFileName(
            self, "Select devices.json for this workspace",
            "", "JSON (*.json);;All files (*.*)"
        )
        ws = Workspace(
            name=name.strip(),
            devices_path=path,
            created=datetime.now().isoformat(timespec="seconds"),
        )
        self._workspaces.append(ws)
        self._persist()
        self._refresh_list()

    def _on_rename(self) -> None:
        ws = self._selected()
        if ws is None:
            return
        name, ok = QInputDialog.getText(self, "Rename", "New name:", text=ws.name)
        if ok and name.strip():
            ws.name = name.strip()
            self._persist()
            self._refresh_list()

    def _on_delete(self) -> None:
        ws = self._selected()
        if ws is None:
            return
        confirm = QMessageBox.question(
            self, "Delete workspace",
            f"Delete workspace {ws.name!r}?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        self._workspaces = [w for w in self._workspaces if w.name != ws.name]
        self._persist()
        self._refresh_list()

    def _on_load(self) -> None:
        ws = self._selected()
        if ws is None:
            QMessageBox.information(self, "Load", "Select a workspace first.")
            return
        ws.last_used = datetime.now().isoformat(timespec="seconds")
        self._persist()
        self.workspaceLoaded.emit(ws)
        self.accept()
