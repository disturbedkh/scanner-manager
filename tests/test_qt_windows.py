"""Smoke tests for the standalone CoverageWindow + LogWindow."""

from __future__ import annotations

import os

import pytest

pytest.importorskip("pytestqt")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QPlainTextEdit, QWidget  # noqa: E402

from gui.windows import CoverageWindow, LogWindow  # noqa: E402


def test_coverage_window_takes_ownership_of_widget(qtbot):
    original_parent = QWidget()
    coverage = QWidget(original_parent)
    qtbot.addWidget(original_parent)
    win = CoverageWindow(coverage, original_parent=original_parent)
    qtbot.addWidget(win)
    assert win.centralWidget() is coverage
    assert coverage.parent() is win


def test_coverage_window_returns_widget_to_original_parent_on_close(qtbot):
    original_parent = QWidget()
    coverage = QWidget(original_parent)
    qtbot.addWidget(original_parent)
    win = CoverageWindow(coverage, original_parent=original_parent)
    qtbot.addWidget(win)
    win.close()
    # closeEvent re-parents the widget back so the editor dock can
    # display it again.
    assert coverage.parent() is original_parent


def test_log_window_hosts_a_persistent_view(qtbot):
    view = QPlainTextEdit()
    view.appendPlainText("hello")
    win = LogWindow(view)
    qtbot.addWidget(win)
    assert win.centralWidget() is view
    assert "hello" in view.toPlainText()


def test_log_window_close_emits_closed_signal(qtbot):
    view = QPlainTextEdit()
    win = LogWindow(view)
    qtbot.addWidget(win)
    closed_calls = []
    win.closed.connect(lambda: closed_calls.append(True))
    win.close()
    assert closed_calls == [True]
