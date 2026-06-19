"""Qt application entry point for Scanner Manager.

Launched via the ``scanner-manager-qt`` console script (defined in
``pyproject.toml``). Sets up the QApplication, applies a consistent
style + dark/light auto theme, hooks the crash logger, and shows
the main window.
"""

from __future__ import annotations

import logging
import os
import sys
import traceback
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication, QMessageBox

from .main_window import MainWindow

logger = logging.getLogger(__name__)


def _crash_log_dir() -> Path:
    """Return a writable directory for crash logs."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Logs"
    else:
        base = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local" / "state")))
    out = base / "scanner-manager" / "crash"
    out.mkdir(parents=True, exist_ok=True)
    return out


def _install_global_excepthook(window: Optional[MainWindow]) -> None:
    """Catch unhandled exceptions, write a crash log, and surface a dialog.

    Mirrors the Tk app's ``_install_crash_hook`` behavior so users
    get the same "save this file and report" path on the new shell.
    """
    log_dir = _crash_log_dir()

    def hook(exc_type, exc_value, exc_tb) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        try:
            from datetime import datetime
            ts = datetime.now().strftime("%Y%m%d-%H%M%S")
            log_path = log_dir / f"crash-{ts}.log"
            with log_path.open("w", encoding="utf-8") as f:
                f.write(f"Scanner Manager crash log - {ts}\n\n")
                traceback.print_exception(exc_type, exc_value, exc_tb, file=f)
            logger.error("Unhandled exception logged to %s", log_path)
        except Exception:  # pragma: no cover - last-ditch
            log_path = None

        if window is not None and QApplication.instance() is not None:
            QMessageBox.critical(
                window,
                "Scanner Manager - Unexpected error",
                f"An unexpected error occurred:\n\n{exc_value}\n\n"
                f"A crash log was written to:\n{log_path}\n\n"
                "Please attach this file when reporting the issue.",
            )

    sys.excepthook = hook


def _apply_app_style(app: QApplication) -> None:
    """Pick the Fusion style + dark/light auto-theme based on the OS."""
    QApplication.setStyle("Fusion")
    palette = app.palette()
    is_dark = (
        palette.color(QPalette.ColorRole.Window).lightness() < 128
        if hasattr(QPalette, "ColorRole")
        else False
    )
    # The Fusion style auto-respects the system palette on every platform;
    # we just leave it untouched. If we want a hard-pinned dark theme later,
    # this is the place to construct + setPalette().
    if is_dark:
        logger.debug("Detected dark system palette")


def _set_app_metadata() -> None:
    QCoreApplication.setApplicationName("Scanner Manager")
    QCoreApplication.setOrganizationName("Scanner Manager Contributors")
    QCoreApplication.setOrganizationDomain("scanner-manager.local")
    try:
        from importlib.metadata import PackageNotFoundError, version
        try:
            QCoreApplication.setApplicationVersion(
                version("beartracker-885-scanner-manager")
            )
        except PackageNotFoundError:
            QCoreApplication.setApplicationVersion("0.9.0b3-dev")
    except Exception:
        QCoreApplication.setApplicationVersion("0.9.0b3-dev")


def main(argv: Optional[list] = None) -> int:
    """Launch the Qt main window. Returns the Qt exit code."""
    if argv is None:
        argv = sys.argv

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # High-DPI scaling: AA_EnableHighDpiScaling / AA_UseHighDpiPixmaps
    # were deprecated in Qt 6 because the behavior is always on. We
    # only set them on Qt 5 (PyQt5 / PySide2) for backwards compat
    # with anyone running an older binding.
    qt_major = int(getattr(Qt, "__version__", "6").split(".")[0]) if hasattr(Qt, "__version__") else 6
    if qt_major < 6:
        if hasattr(Qt, "AA_EnableHighDpiScaling"):
            QCoreApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        if hasattr(Qt, "AA_UseHighDpiPixmaps"):
            QCoreApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(argv)
    _set_app_metadata()
    _apply_app_style(app)

    window = MainWindow()
    _install_global_excepthook(window)
    window.show()

    # Optional dev-only debug bridge. The dev_mcp/ tree is gitignored;
    # if a developer hasn't dropped it in, this is a silent no-op.
    # Gated behind an env var so nothing happens by default even when
    # the package is installed.
    if os.environ.get("SCANNER_MANAGER_DEV_MCP") == "1":
        try:
            from dev_mcp import attach as _dev_attach
            _dev_attach.maybe_start(window)
        except ImportError:
            logging.getLogger(__name__).debug(
                "SCANNER_MANAGER_DEV_MCP=1 set but dev_mcp/ is not installed."
            )
        except Exception:
            logging.getLogger(__name__).exception("dev-MCP attach failed")

    return app.exec()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
