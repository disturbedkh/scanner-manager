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

from core.device_manager import _default_devices_path
from gui.widgets.scaling_label import ScalingHelpLabel

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Persistence helpers
# ----------------------------------------------------------------------


def _default_workspaces_path() -> Path:
    """Return ``workspaces.json`` next to the user data directory."""
    from core.paths import config_dir

    return config_dir() / "workspaces.json"


def workspace_help_text(default_devices_path: Optional[Path] = None) -> str:
    """User-facing explanation of workspaces and ``devices.json``."""
    default_path = default_devices_path or _default_devices_path()
    if sys.platform == "win32":
        fallback = "%APPDATA%\\scanner-manager\\devices.json"
    elif sys.platform == "darwin":
        fallback = "~/Library/Application Support/scanner-manager/devices.json"
    else:
        fallback = "~/.config/scanner-manager/devices.json"

    return (
        "What is devices.json?\n"
        "  The device manifest: your registered scanners (label, scanner "
        "family, SD card path). The header dropdown reads from it.\n"
        "\n"
        "Where to find it:\n"
        f"  Default path: {default_path}\n"
        f"  Packaged fallback: {fallback}\n"
        "  Edit the active list via Devices → Manage devices…\n"
        "\n"
        "What a workspace does:\n"
        "  Saves a name → path to a devices.json so you can switch "
        "between setups (e.g. Home vs Travel) without overwriting "
        "your default file."
    )


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


def format_workspace_list_text(ws: Workspace) -> str:
    """Primary list line for a workspace row."""
    text = ws.name
    if ws.last_used:
        text = f"{ws.name}  ·  last used {ws.last_used}"
    return text


def format_workspace_list_tooltip(ws: Workspace) -> str:
    """Secondary detail shown as tooltip."""
    if ws.devices_path:
        return f"devices.json at {ws.devices_path}"
    return "No devices.json path configured"


# ----------------------------------------------------------------------
# Dialog
# ----------------------------------------------------------------------


class WorkspaceManagerDialog(QDialog):
    """Manage named workspaces (create / rename / delete / load)."""

    workspaceLoaded = Signal(Workspace)
    defaultDeviceListRequested = Signal()

    def __init__(self, parent=None, path: Optional[Path] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Workspaces")
        self.resize(640, 480)
        self._path = Path(path) if path else _default_workspaces_path()
        self._workspaces: List[Workspace] = load_workspaces(self._path)
        self._build_ui()
        self._refresh_list()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("<b>Workspaces</b>"))
        self._intro = ScalingHelpLabel(workspace_help_text())
        self._intro.setStyleSheet("color: #444;")
        layout.addWidget(self._intro)

        self._list = QListWidget()
        self._list.itemDoubleClicked.connect(self._on_load)
        layout.addWidget(self._list, 1)

        button_row = QHBoxLayout()
        new_btn = QPushButton("New…")
        new_btn.clicked.connect(self._on_new)
        button_row.addWidget(new_btn)

        new_default_btn = QPushButton("New from default devices.json")
        new_default_btn.setToolTip(
            f"Create a workspace pointing at {_default_devices_path()}"
        )
        new_default_btn.clicked.connect(self._on_new_from_default)
        button_row.addWidget(new_default_btn)

        rename_btn = QPushButton("Rename…")
        rename_btn.clicked.connect(self._on_rename)
        button_row.addWidget(rename_btn)

        delete_btn = QPushButton("Delete")
        delete_btn.clicked.connect(self._on_delete)
        button_row.addWidget(delete_btn)

        button_row.addStretch(1)

        default_btn = QPushButton("Use default device list")
        default_btn.setToolTip(
            "Stop using a named workspace and reload the default devices.json"
        )
        default_btn.clicked.connect(self._on_use_default_device_list)
        button_row.addWidget(default_btn)

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
            item = QListWidgetItem(format_workspace_list_text(w))
            item.setToolTip(format_workspace_list_tooltip(w))
            item.setData(Qt.UserRole, w)
            self._list.addItem(item)

    def _selected(self) -> Optional[Workspace]:
        item = self._list.currentItem()
        return item.data(Qt.UserRole) if item else None

    def _persist(self) -> None:
        save_workspaces(self._workspaces, self._path)

    def _prompt_workspace_name(self) -> Optional[str]:
        name, ok = QInputDialog.getText(self, "New workspace", "Name:")
        if not ok or not name.strip():
            return None
        return name.strip()

    def _create_workspace(self, name: str, devices_path: str) -> None:
        ws = Workspace(
            name=name,
            devices_path=devices_path,
            created=datetime.now().isoformat(timespec="seconds"),
        )
        self._workspaces.append(ws)
        self._persist()
        self._refresh_list()

    def _on_new(self) -> None:
        name = self._prompt_workspace_name()
        if name is None:
            return
        path, _filter = QFileDialog.getOpenFileName(
            self,
            "Select devices.json for this workspace",
            str(_default_devices_path().parent),
            "JSON (*.json);;All files (*.*)",
        )
        if not path:
            return
        self._create_workspace(name, path)

    def _on_new_from_default(self) -> None:
        name = self._prompt_workspace_name()
        if name is None:
            return
        self._create_workspace(name, str(_default_devices_path()))

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
            self,
            "Delete workspace",
            f"Delete workspace {ws.name!r}?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        self._workspaces = [w for w in self._workspaces if w.name != ws.name]
        self._persist()
        self._refresh_list()

    def _on_use_default_device_list(self) -> None:
        self.defaultDeviceListRequested.emit()
        self.accept()

    def _on_load(self) -> None:
        ws = self._selected()
        if ws is None:
            QMessageBox.information(self, "Load", "Select a workspace first.")
            return
        if not ws.devices_path:
            QMessageBox.warning(
                self,
                "Load",
                "This workspace has no devices.json path configured.",
            )
            return
        if not Path(ws.devices_path).exists():
            QMessageBox.warning(
                self,
                "Load",
                f"devices.json not found:\n{ws.devices_path}",
            )
            return
        ws.last_used = datetime.now().isoformat(timespec="seconds")
        self._persist()
        self.workspaceLoaded.emit(ws)
        self.accept()
