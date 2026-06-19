"""Profile-gated side panels for the editor dock.

- :class:`ButtonFilterPanel` (BT885 only): the scanner-button row
  used by the Tk app to preview which entries play on each hardware
  button (Police / Fire / EMS / DOT / Multi).
- :class:`FavoritesListsPanel` (SDS100/200 only): browse Favorites
  Lists under ``BCDx36HP/favorites_lists/``.
- :class:`ProfileCfgPanel` (SDS100/200 only): read-only viewer for
  ``BCDx36HP/profile.cfg`` (write support lands in Phase 6).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Tuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from scanner_profiles import ScannerProfile

logger = logging.getLogger(__name__)


class ButtonFilterPanel(QWidget):
    """BT885 scanner-button preview row."""

    selectionChanged = Signal(set)

    BUTTONS: Tuple[Tuple[str, str], ...] = (
        ("POLICE", "Police"),
        ("FIRE", "Fire"),
        ("EMS", "EMS"),
        ("DOT", "DOT"),
        ("MULTI", "Multi"),
    )

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        box = QGroupBox("BearTracker scanner buttons")
        row = QHBoxLayout(box)
        self._checks = {}
        for key, label in self.BUTTONS:
            cb = QCheckBox(label)
            cb.setChecked(True)
            cb.toggled.connect(lambda _checked, k=key: self._on_toggled(k))
            row.addWidget(cb)
            self._checks[key] = cb
        row.addStretch(1)
        layout.addWidget(box)

    def selected_buttons(self) -> set:
        return {k for k, cb in self._checks.items() if cb.isChecked()}

    def _on_toggled(self, _key: str) -> None:
        self.selectionChanged.emit(self.selected_buttons())


class FavoritesListsPanel(QWidget):
    """SDS100/200 Favorites Lists browser (Phase 2 read-only)."""

    favoriteSelected = Signal(str)  # path

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        layout.addWidget(QLabel("<b>Favorites Lists</b>"))

        self._list = QListWidget()
        self._list.itemDoubleClicked.connect(self._on_double_clicked)
        layout.addWidget(self._list)

        self._info = QLabel("Select a list to inspect (Phase 2 = read-only)")
        self._info.setStyleSheet("color: #777;")
        layout.addWidget(self._info)

    def set_card_path(self, sd_path: str) -> None:
        self._list.clear()
        if not sd_path:
            return
        root = Path(sd_path)
        candidates = (
            root / "BCDx36HP" / "favorites_lists",
            root / "favorites_lists",
        )
        fav_dir = next(
            (c for c in candidates if c.exists() and c.is_dir()), None
        )
        if fav_dir is None:
            self._info.setText(
                "No favorites_lists/ folder on this card (BT885 cards don't have one)."
            )
            return

        files = sorted(fav_dir.glob("f_*.hpd"))
        if not files:
            self._info.setText(f"No f_*.hpd files in {fav_dir}")
            return

        for f in files:
            item = QListWidgetItem(f.name)
            item.setData(Qt.UserRole, str(f))
            self._list.addItem(item)
        self._info.setText(
            f"{len(files)} favorites lists. Double-click to surface a quick summary."
        )

    def _on_double_clicked(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.UserRole)
        if path:
            self.favoriteSelected.emit(path)


class ProfileCfgPanel(QWidget):
    """SDS100/200 ``profile.cfg`` viewer (Phase 2 = read-only)."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        layout.addWidget(QLabel("<b>profile.cfg</b>  (read-only — write support in Phase 6)"))

        self._view = QPlainTextEdit()
        self._view.setReadOnly(True)
        self._view.setPlaceholderText("No profile.cfg on this card")
        layout.addWidget(self._view)

    def set_card_path(self, sd_path: str) -> None:
        self._view.clear()
        if not sd_path:
            return
        root = Path(sd_path)
        candidates = (
            root / "BCDx36HP" / "profile.cfg",
            root / "profile.cfg",
        )
        cfg_path = next((c for c in candidates if c.exists()), None)
        if cfg_path is None:
            self._view.setPlaceholderText(
                "No BCDx36HP/profile.cfg on this card "
                "(BT885 cards don't have one)."
            )
            return
        try:
            text = cfg_path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            self._view.setPlainText(f"<error reading {cfg_path}: {exc}>")
            return
        self._view.setPlainText(text)


class ProfileSidePanel(QWidget):
    """Container that hosts the right per-profile panel.

    Swaps internals when :meth:`set_profile` is called. For BT885 this
    is just the button-filter row; for SDS100/200 we show a tab widget
    with Favorites Lists + profile.cfg.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._profile: Optional[ScannerProfile] = None
        self._sd_path: Optional[str] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        self._button_panel = ButtonFilterPanel()
        layout.addWidget(self._button_panel)

        self._sds_tabs = QTabWidget()
        self._favorites_panel = FavoritesListsPanel()
        self._profile_cfg_panel = ProfileCfgPanel()
        self._sds_tabs.addTab(self._favorites_panel, "Favorites Lists")
        self._sds_tabs.addTab(self._profile_cfg_panel, "profile.cfg")
        layout.addWidget(self._sds_tabs, stretch=1)

        self._set_visibility_for_profile(None)

    def set_profile(self, profile: ScannerProfile) -> None:
        self._profile = profile
        self._set_visibility_for_profile(profile)

    def set_card_path(self, sd_path: Optional[str]) -> None:
        self._sd_path = sd_path or ""
        self._favorites_panel.set_card_path(self._sd_path)
        self._profile_cfg_panel.set_card_path(self._sd_path)

    def _set_visibility_for_profile(self, profile: Optional[ScannerProfile]) -> None:
        if profile is None:
            self._button_panel.setVisible(False)
            self._sds_tabs.setVisible(False)
            return
        # BT885 has hardware buttons; SDS does not
        self._button_panel.setVisible(not profile.supports_favorites_lists)
        # SDS-class scanners get the Favorites + profile.cfg tabs
        self._sds_tabs.setVisible(
            profile.supports_favorites_lists or profile.supports_profile_cfg
        )
