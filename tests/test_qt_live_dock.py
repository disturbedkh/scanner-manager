"""Smoke tests for the Live dock's Control / Monitoring tab split."""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.qt

pytest.importorskip("pytestqt")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gui.live.live_dock import LiveDock  # noqa: E402
from gui.live.virtual_scanner import VirtualScannerPanel  # noqa: E402
from gui.live.widgets import (  # noqa: E402
    GlgFeedWidget,
    GsiMirrorWidget,
    MetersWidget,
)


def test_live_dock_has_control_and_monitoring_tabs(qtbot):
    dock = LiveDock()
    qtbot.addWidget(dock)
    tabs = dock._live_tabs
    assert tabs.count() == 2
    assert tabs.tabText(0) == "Live - Control"
    assert tabs.tabText(1) == "Live - Monitoring"


def test_control_tab_hosts_faceplate(qtbot):
    dock = LiveDock()
    qtbot.addWidget(dock)
    control_page = dock._live_tabs.widget(0)
    # The faceplate lives under the Control tab, the monitoring widgets do not.
    assert control_page.findChildren(VirtualScannerPanel)
    assert not control_page.findChildren(GsiMirrorWidget)
    assert not control_page.findChildren(GlgFeedWidget)


def test_monitoring_tab_hosts_passive_displays(qtbot):
    dock = LiveDock()
    qtbot.addWidget(dock)
    monitoring_page = dock._live_tabs.widget(1)
    assert monitoring_page.findChildren(GsiMirrorWidget)
    assert monitoring_page.findChildren(MetersWidget)
    assert monitoring_page.findChildren(GlgFeedWidget)
    # The waterfall stack is parented under the monitoring page too.
    assert dock._wf_stack in monitoring_page.findChildren(type(dock._wf_stack))
    # And the faceplate is NOT on the monitoring tab.
    assert not monitoring_page.findChildren(VirtualScannerPanel)
