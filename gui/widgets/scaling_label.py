"""Word-wrapped label that scales font size with available space."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QResizeEvent
from PySide6.QtWidgets import QLabel, QWidget


class ScalingHelpLabel(QLabel):
    """Increase point size when the widget has extra vertical room."""

    _MIN_HEIGHT = 200
    _MAX_SCALE = 1.6

    def __init__(
        self,
        text: str = "",
        *,
        min_scale: float = 1.0,
        max_scale: float = _MAX_SCALE,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(text, parent)
        self._min_scale = min_scale
        self._scale_ceiling = max_scale
        self._base_point_size = float(self.font().pointSizeF() or self.font().pointSize() or 9)
        self.setWordWrap(True)
        self._apply_scaled_font()

    def setText(self, text: str) -> None:  # noqa: N802 (Qt naming)
        super().setText(text)
        self._apply_scaled_font()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._apply_scaled_font()

    def _apply_scaled_font(self) -> None:
        height = self.height()
        if height <= 0:
            height = self.sizeHint().height()
        if height <= self._MIN_HEIGHT:
            scale = self._min_scale
        else:
            extra = min(height - self._MIN_HEIGHT, 240)
            scale = self._min_scale + (extra / 240.0) * (self._scale_ceiling - self._min_scale)
        scale = max(self._min_scale, min(self._scale_ceiling, scale))
        font = QFont(self.font())
        font.setPointSizeF(self._base_point_size * scale)
        self.setFont(font)
