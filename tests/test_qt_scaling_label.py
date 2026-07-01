"""Tests for responsive help label typography."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

from gui.widgets.scaling_label import ScalingHelpLabel


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_scaling_help_label_grows_with_height(qtbot) -> None:
    label = ScalingHelpLabel("Help text for scaling test.")
    label.resize(380, 120)
    qtbot.addWidget(label)
    label._apply_scaled_font()
    small_size = label.font().pointSizeF()

    label.resize(380, 420)
    qtbot.wait(10)
    label._apply_scaled_font()
    large_size = label.font().pointSizeF()

    assert large_size > small_size
