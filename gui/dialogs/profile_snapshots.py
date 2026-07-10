"""Qt port of the ProfileSnapshotsDialog.

A "profile snapshot" is a versioned copy of an HPD config + its
metastore sidecar. The user can take an ad-hoc snapshot before any
risky bulk edit (button-filter sweep, RR import, etc.), then later
restore one of those snapshots if the change went sideways.

Storage layout::

    <user_data>/scanner-manager/snapshots/<scanner_profile_id>/
        <snapshot_id>/
            scanner.inf
            <hpd files...>
            metastore/
                ...
            snapshot.json   (label, created, notes)
"""

from __future__ import annotations

import json
import logging
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

logger = logging.getLogger(__name__)


def _snapshots_root() -> Path:
    from core.paths import config_dir

    return config_dir() / "snapshots"


@dataclass
class Snapshot:
    id: str
    label: str
    created: str
    notes: str
    path: Path
    scanner_profile_id: str

    def to_dict(self):
        return {
            "id": self.id,
            "label": self.label,
            "created": self.created,
            "notes": self.notes,
            "scanner_profile_id": self.scanner_profile_id,
        }


def list_snapshots(scanner_profile_id: str) -> List[Snapshot]:
    base = _snapshots_root() / scanner_profile_id
    if not base.exists():
        return []
    out: List[Snapshot] = []
    for entry in sorted(base.iterdir(), reverse=True):
        if not entry.is_dir():
            continue
        manifest = entry / "snapshot.json"
        if not manifest.exists():
            continue
        try:
            raw = json.loads(manifest.read_text(encoding="utf-8"))
        except Exception:
            continue
        out.append(
            Snapshot(
                id=raw.get("id", entry.name),
                label=raw.get("label", entry.name),
                created=raw.get("created", ""),
                notes=raw.get("notes", ""),
                path=entry,
                scanner_profile_id=scanner_profile_id,
            )
        )
    return out


def take_snapshot(card_root: Path, scanner_profile_id: str, label: str, notes: str = "") -> Snapshot:
    """Mirror BCDx36HP/ into the snapshot store and return the Snapshot."""
    if not card_root.exists():
        raise FileNotFoundError(f"Card path does not exist: {card_root}")
    snap_id = uuid.uuid4().hex[:12]
    target = _snapshots_root() / scanner_profile_id / snap_id
    target.mkdir(parents=True, exist_ok=True)
    src = card_root / "BCDx36HP"
    if src.exists():
        shutil.copytree(src, target / "BCDx36HP", dirs_exist_ok=True)
    snap = Snapshot(
        id=snap_id,
        label=label,
        created=datetime.now().isoformat(timespec="seconds"),
        notes=notes,
        path=target,
        scanner_profile_id=scanner_profile_id,
    )
    (target / "snapshot.json").write_text(json.dumps(snap.to_dict(), indent=2), encoding="utf-8")
    return snap


def restore_snapshot(snapshot: Snapshot, card_root: Path) -> None:
    """Copy the snapshot's BCDx36HP/ back over the card."""
    src = snapshot.path / "BCDx36HP"
    if not src.exists():
        raise FileNotFoundError(f"Snapshot {snapshot.id} has no BCDx36HP/ payload")
    dst = card_root / "BCDx36HP"
    dst.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst, dirs_exist_ok=True)


# ----------------------------------------------------------------------
# Dialog
# ----------------------------------------------------------------------


class ProfileSnapshotsDialog(QDialog):
    """List + create + restore + delete profile snapshots."""

    snapshotRestored = Signal(Snapshot)

    def __init__(self, scanner_profile_id: str, card_root: Optional[Path], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Profile snapshots")
        self.resize(640, 460)
        self._scanner_profile_id = scanner_profile_id
        self._card_root = Path(card_root) if card_root else None
        self._build_ui()
        self._refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<b>Profile snapshots</b>"))
        layout.addWidget(QLabel(
            "Snapshots store a copy of the scanner's BCDx36HP/ folder "
            "before risky edits so you can roll back."
        ))

        self._list = QListWidget()
        self._list.itemSelectionChanged.connect(self._on_selection)
        layout.addWidget(self._list, 1)

        self._notes = QTextEdit()
        self._notes.setReadOnly(True)
        self._notes.setMaximumHeight(120)
        layout.addWidget(self._notes)

        button_row = QHBoxLayout()
        new_btn = QPushButton("Take snapshot…")
        new_btn.clicked.connect(self._on_take)
        button_row.addWidget(new_btn)

        restore_btn = QPushButton("Restore selected…")
        restore_btn.clicked.connect(self._on_restore)
        button_row.addWidget(restore_btn)

        delete_btn = QPushButton("Delete")
        delete_btn.clicked.connect(self._on_delete)
        button_row.addWidget(delete_btn)

        button_row.addStretch(1)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        button_row.addWidget(close_btn)
        layout.addLayout(button_row)

    def _refresh(self) -> None:
        self._list.clear()
        for s in list_snapshots(self._scanner_profile_id):
            text = f"{s.created or '?'}  ·  {s.label}"
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, s)
            self._list.addItem(item)

    def _selected(self) -> Optional[Snapshot]:
        item = self._list.currentItem()
        return item.data(Qt.UserRole) if item else None

    def _on_selection(self) -> None:
        s = self._selected()
        self._notes.setPlainText(s.notes if s else "")

    def _on_take(self) -> None:
        if self._card_root is None:
            QMessageBox.information(
                self, "No card",
                "This device has no SD card path; configure one in Devices > Manage devices."
            )
            return
        label, ok = QInputDialog.getText(self, "Snapshot label", "Label:")
        if not ok or not label.strip():
            return
        try:
            take_snapshot(self._card_root, self._scanner_profile_id, label.strip())
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Snapshot failed", str(exc))
            return
        self._refresh()

    def _on_restore(self) -> None:
        s = self._selected()
        if s is None or self._card_root is None:
            return
        confirm = QMessageBox.question(
            self, "Restore snapshot",
            f"Restore {s.label!r} ({s.created}) over the current card?\n"
            "This overwrites BCDx36HP/ on the SD card.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            restore_snapshot(s, self._card_root)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Restore failed", str(exc))
            return
        self.snapshotRestored.emit(s)
        QMessageBox.information(self, "Restore", "Snapshot restored.")

    def _on_delete(self) -> None:
        s = self._selected()
        if s is None:
            return
        confirm = QMessageBox.question(
            self, "Delete snapshot",
            f"Delete snapshot {s.label!r}? This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            shutil.rmtree(s.path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Delete failed", str(exc))
            return
        self._refresh()
