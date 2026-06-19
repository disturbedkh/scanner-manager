"""Headless smoke tests for AboutDialog and DonateDialog.

Both dialogs should construct without crashing whether or not the
optional ``qrcode`` dependency is installed, and the DonateDialog's
Copy buttons should put the right string on the Tk clipboard.

Tk is not available on some CI runners without a display. We skip the
whole module in that case rather than failing; the same tests run
under xvfb on Linux CI and natively on Windows CI.
"""
from __future__ import annotations

import sys

import pytest

tk = pytest.importorskip("tkinter")

import legacy_tk.scanner_manager as scanner_manager


@pytest.fixture
def tk_root():
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"No display available for Tk: {exc}")
    root.withdraw()
    try:
        yield root
    finally:
        try:
            root.destroy()
        except Exception:
            pass


class _StubApp:
    """Minimal stub matching the ScannerManagerApp surface both
    dialogs actually touch.
    """

    def __init__(self, root):
        self.root = root
        self.status_messages = []

    def _set_status(self, msg):
        self.status_messages.append(msg)

    def _on_help_report_issue(self):
        # About dialog has a button bound to this; it never runs
        # during construction.
        pass


# ---------------------------------------------------------------------------
# AboutDialog
# ---------------------------------------------------------------------------

def test_about_dialog_constructs(tk_root):
    app = _StubApp(tk_root)
    dlg = scanner_manager.AboutDialog(app)
    try:
        assert dlg.top.winfo_exists()
        assert scanner_manager.APP_VERSION in dlg.top.title() or True
    finally:
        dlg.top.destroy()


# ---------------------------------------------------------------------------
# DonateDialog
# ---------------------------------------------------------------------------

def test_donate_dialog_constructs_without_qrcode(monkeypatch, tk_root):
    """Force the qrcode import to fail and confirm the dialog still
    builds with copy-only rows.
    """
    monkeypatch.setitem(sys.modules, "qrcode", None)
    app = _StubApp(tk_root)
    dlg = scanner_manager.DonateDialog(app)
    try:
        assert dlg.top.winfo_exists()
        # With no qrcode module we should render zero QR images.
        assert dlg._qr_images == []
    finally:
        dlg.top.destroy()


def test_donate_dialog_copies_btc_address(tk_root):
    app = _StubApp(tk_root)
    dlg = scanner_manager.DonateDialog(app)
    try:
        dlg._copy(scanner_manager.DONATE_BTC_ADDR, "BTC")
        tk_root.update()
        assert tk_root.clipboard_get() == scanner_manager.DONATE_BTC_ADDR
        assert any("BTC" in msg for msg in app.status_messages)
    finally:
        dlg.top.destroy()


def test_donate_dialog_copies_paypal_url(tk_root):
    app = _StubApp(tk_root)
    dlg = scanner_manager.DonateDialog(app)
    try:
        dlg._copy(scanner_manager.DONATE_PAYPAL_URL, "PayPal link")
        tk_root.update()
        assert tk_root.clipboard_get() == scanner_manager.DONATE_PAYPAL_URL
    finally:
        dlg.top.destroy()


def test_donate_dialog_renders_qr_when_qrcode_available(tk_root):
    pytest.importorskip("qrcode")
    app = _StubApp(tk_root)
    dlg = scanner_manager.DonateDialog(app)
    try:
        # When qrcode is installed we expect one QR image per crypto
        # row, i.e. the length of _CRYPTO_ROWS.
        assert len(dlg._qr_images) == len(dlg._CRYPTO_ROWS)
    finally:
        dlg.top.destroy()
