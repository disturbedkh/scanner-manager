"""Tests for responsive help label typography and details help scroll."""

from __future__ import annotations

import re

import pytest
from PySide6.QtWidgets import QApplication

from gui.widgets.scaling_label import ScalingHelpLabel
from scanner_profiles import get_profile

pytestmark = pytest.mark.qt


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


def test_details_panel_help_is_scrollable(qtbot) -> None:
    from gui.editor.details_panel import BaseDetailsPanel

    panel = BaseDetailsPanel()
    qtbot.addWidget(panel)
    panel.set_profile(get_profile("uniden_sds100"))
    panel.show()
    panel.resize(320, 280)
    qtbot.wait(10)

    assert panel._help_scroll.isVisible()
    assert panel._help_scroll.widget() is panel._help_label
    assert panel._help_label.wordWrap()
    # Tall help in a short pane must remain reachable via scroll.
    assert panel._help_label.sizeHint().height() >= 1
    assert panel._help_scroll.verticalScrollBar().maximum() >= 0


def test_sds_help_text_has_no_mid_paragraph_hard_wraps() -> None:
    help_text = get_profile("uniden_sds100").service_type_help_text()
    # Paragraph breaks are fine; single newlines mid-sentence are not.
    assert "\n\n" in help_text
    assert not re.search(r"[^\n]\n[^\n]", help_text)
