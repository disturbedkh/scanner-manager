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


class _FakeController:
    """Stand-in poller controller exposing the close/deleteLater seam."""

    def __init__(self) -> None:
        self.closed = False
        self.deleted = False

    def close(self) -> None:
        self.closed = True

    def deleteLater(self) -> None:  # noqa: N802 (Qt naming)
        self.deleted = True


def _fake_connected(dock) -> tuple:
    main = _FakeController()
    sub = _FakeController()
    dock._main_controller = main
    dock._sub_controller = sub
    dock._connect_btn.setEnabled(False)
    dock._disconnect_btn.setEnabled(True)
    dock._diag_btn.setEnabled(True)
    return main, sub


def test_disconnect_closes_and_schedules_controller_deletion(qtbot):
    """A5: disconnect must deleteLater() the parented controllers."""
    dock = LiveDock()
    qtbot.addWidget(dock)
    main, sub = _fake_connected(dock)

    dock.disconnect()

    assert main.closed and main.deleted
    assert sub.closed and sub.deleted
    assert dock._main_controller is None
    assert dock._sub_controller is None


def test_main_poller_failure_returns_to_clean_disconnected_state(qtbot):
    """A7: a MAIN failure tears the whole session down cleanly."""
    dock = LiveDock()
    qtbot.addWidget(dock)
    main, sub = _fake_connected(dock)

    dock._on_main_failed("device vanished")

    assert main.closed and sub.closed
    assert dock._main_controller is None
    assert dock._sub_controller is None
    assert dock._connect_btn.isEnabled()
    assert not dock._disconnect_btn.isEnabled()
    assert not dock._diag_btn.isEnabled()
    assert "MAIN poller stopped" in dock._status_label.text()


def test_sub_poller_failure_keeps_main_session(qtbot):
    """A7: an optional-SUB failure only tears down the SUB poller."""
    dock = LiveDock()
    qtbot.addWidget(dock)
    main, sub = _fake_connected(dock)

    dock._on_sub_failed("sub cable pulled")

    assert sub.closed and sub.deleted
    assert dock._sub_controller is None
    assert dock._main_controller is main  # MAIN session preserved
    assert dock._disconnect_btn.isEnabled()
    assert "SUB poller stopped" in dock._status_label.text()
