"""Combined BT885 inspector column for the editor dock.

Merges the BearTracker scanner-button row (including "Include other
types") and HPDB entry details into one vertical panel for the Wave 3
two-column BT885 layout.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget

from scanner_profiles import ScannerProfile

from .details_panel import Bt885DetailsPanel
from .profile_panels import ButtonFilterPanel


class Bt885InspectorPanel(QWidget):
    """BT885-only inspector: button filters + details."""

    includeOthersChanged = Signal(bool)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        self._button_panel = ButtonFilterPanel()
        self._button_panel.includeOthersChanged.connect(self.includeOthersChanged.emit)
        layout.addWidget(self._button_panel)

        self._details_panel = Bt885DetailsPanel()
        layout.addWidget(self._details_panel, stretch=1)

    def button_filter_panel(self) -> ButtonFilterPanel:
        return self._button_panel

    def details_panel(self) -> Bt885DetailsPanel:
        return self._details_panel

    def include_others(self) -> bool:
        return self._button_panel.include_others()

    def set_profile(self, profile: ScannerProfile) -> None:
        self._details_panel.set_profile(profile)
