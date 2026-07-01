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
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

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

_PROFILE_CFG = "profile.cfg"
_REL_MISSING = "__missing__"

# Disk-read caches keyed by (sd_path, rel_path, mtime). Wave 2 calls
# :func:`invalidate_card_cache` after card reload/save.
_FavoritesKey = Tuple[str, str, float]
_ProfileCfgKey = Tuple[str, str, float]


@dataclass(frozen=True)
class _FavoritesCacheEntry:
    items: Tuple[Tuple[str, str], ...]
    info_text: str


@dataclass(frozen=True)
class _ProfileCfgCacheEntry:
    text: str
    placeholder: Optional[str] = None


_favorites_cache: Dict[_FavoritesKey, _FavoritesCacheEntry] = {}
_profile_cfg_cache: Dict[_ProfileCfgKey, _ProfileCfgCacheEntry] = {}


def _normalize_sd_path(sd_path: str) -> str:
    if not sd_path:
        return ""
    return str(Path(sd_path).resolve())


def _favorites_dir(root: Path) -> Optional[Path]:
    candidates = (
        root / "BCDx36HP" / "favorites_lists",
        root / "favorites_lists",
    )
    return next((c for c in candidates if c.exists() and c.is_dir()), None)


def _profile_cfg_path(root: Path) -> Optional[Path]:
    candidates = (
        root / "BCDx36HP" / _PROFILE_CFG,
        root / _PROFILE_CFG,
    )
    return next((c for c in candidates if c.exists()), None)


def _favorites_cache_key(sd_path: str) -> _FavoritesKey:
    norm = _normalize_sd_path(sd_path)
    fav_dir = _favorites_dir(Path(sd_path))
    if fav_dir is None:
        return (norm, _REL_MISSING, 0.0)
    rel = str(fav_dir.relative_to(Path(sd_path))).replace("\\", "/")
    files = sorted(fav_dir.glob("f_*.hpd"))
    mtime = fav_dir.stat().st_mtime
    for f in files:
        mtime = max(mtime, f.stat().st_mtime)
    return (norm, rel, mtime)


def _profile_cfg_cache_key(sd_path: str) -> _ProfileCfgKey:
    norm = _normalize_sd_path(sd_path)
    cfg_path = _profile_cfg_path(Path(sd_path))
    if cfg_path is None:
        return (norm, _REL_MISSING, 0.0)
    rel = str(cfg_path.relative_to(Path(sd_path))).replace("\\", "/")
    return (norm, rel, cfg_path.stat().st_mtime)


def _load_favorites_entry(sd_path: str) -> _FavoritesCacheEntry:
    root = Path(sd_path)
    fav_dir = _favorites_dir(root)
    if fav_dir is None:
        return _FavoritesCacheEntry(
            (),
            "No favorites_lists/ folder on this card (BT885 cards don't have one).",
        )
    files = sorted(fav_dir.glob("f_*.hpd"))
    if not files:
        return _FavoritesCacheEntry(
            (),
            f"No f_*.hpd files in {fav_dir}",
        )
    items = tuple((f.name, str(f)) for f in files)
    return _FavoritesCacheEntry(
        items,
        f"{len(files)} favorites lists. Double-click to surface a quick summary.",
    )


def _load_profile_cfg_entry(sd_path: str) -> _ProfileCfgCacheEntry:
    root = Path(sd_path)
    cfg_path = _profile_cfg_path(root)
    if cfg_path is None:
        return _ProfileCfgCacheEntry(
            "",
            "No BCDx36HP/profile.cfg on this card "
            "(BT885 cards don't have one).",
        )
    try:
        text = cfg_path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return _ProfileCfgCacheEntry(f"<error reading {cfg_path}: {exc}>")
    return _ProfileCfgCacheEntry(text)


def invalidate_card_cache(sd_path: Optional[str] = None) -> None:
    """Drop cached favorites/profile.cfg reads for one card or all cards."""
    if sd_path is None:
        _favorites_cache.clear()
        _profile_cfg_cache.clear()
        return
    norm = _normalize_sd_path(sd_path)
    for cache in (_favorites_cache, _profile_cfg_cache):
        for key in [k for k in cache if k[0] == norm]:
            del cache[key]


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

        self._last_cache_key: Optional[_FavoritesKey] = None

    def set_card_path(self, sd_path: str) -> None:
        if not sd_path:
            self._list.clear()
            self._last_cache_key = None
            return

        key = _favorites_cache_key(sd_path)
        if key == self._last_cache_key:
            return

        entry = _favorites_cache.get(key)
        if entry is None:
            entry = _load_favorites_entry(sd_path)
            _favorites_cache[key] = entry

        self._list.clear()
        for name, full_path in entry.items:
            item = QListWidgetItem(name)
            item.setData(Qt.UserRole, full_path)
            self._list.addItem(item)
        self._info.setText(entry.info_text)
        self._last_cache_key = key

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

        layout.addWidget(QLabel(f"<b>{_PROFILE_CFG}</b>  (read-only — write support in Phase 6)"))

        self._view = QPlainTextEdit()
        self._view.setReadOnly(True)
        self._view.setPlaceholderText(f"No {_PROFILE_CFG} on this card")
        layout.addWidget(self._view)

        self._last_cache_key: Optional[_ProfileCfgKey] = None

    def set_card_path(self, sd_path: str) -> None:
        if not sd_path:
            self._view.clear()
            self._last_cache_key = None
            return

        key = _profile_cfg_cache_key(sd_path)
        if key == self._last_cache_key:
            return

        entry = _profile_cfg_cache.get(key)
        if entry is None:
            entry = _load_profile_cfg_entry(sd_path)
            _profile_cfg_cache[key] = entry

        if entry.placeholder is not None:
            self._view.clear()
            self._view.setPlaceholderText(entry.placeholder)
        else:
            self._view.setPlainText(entry.text)
        self._last_cache_key = key


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

    def button_filter_panel(self) -> ButtonFilterPanel:
        return self._button_panel

    def set_profile(self, profile: ScannerProfile) -> None:
        self._profile = profile
        self._set_visibility_for_profile(profile)

    def set_card_path(self, sd_path: Optional[str]) -> None:
        self._sd_path = sd_path or ""
        self._favorites_panel.set_card_path(self._sd_path)
        self._profile_cfg_panel.set_card_path(self._sd_path)

    def invalidate_card_cache(self, sd_path: Optional[str] = None) -> None:
        """Clear cached card reads; resets child panel fast-path keys."""
        invalidate_card_cache(sd_path)
        if sd_path is None or sd_path == self._sd_path:
            self._favorites_panel._last_cache_key = None
            self._profile_cfg_panel._last_cache_key = None

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
