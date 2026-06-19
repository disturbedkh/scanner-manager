"""Shared Qt test doubles for ``gui.app.main`` smoke tests."""

from __future__ import annotations

from PySide6.QtGui import QPalette


class FakeQApplication:
    """Minimal QApplication stand-in."""

    def __init__(self, argv: list | None = None) -> None:
        self.argv = argv

    def exec(self) -> int:
        return 0

    def palette(self) -> QPalette:
        return QPalette()

    @staticmethod
    def setStyle(_name: str) -> None:  # NOSONAR - mirrors Qt QApplication.setStyle
        return None


class FakeQApplicationExec42(FakeQApplication):
    """FakeQApplication whose ``exec()`` returns 42."""

    def exec(self) -> int:
        return 42


class FakeQt5:
    """Minimal Qt module stand-in for Qt5 high-DPI attribute checks."""

    __version__ = "5.15.2"
    AA_EnableHighDpiScaling = object()  # NOSONAR - mirrors Qt.ApplicationAttribute
    AA_UseHighDpiPixmaps = object()


class FakeMainWindow:
    """MainWindow stand-in that optionally records ``show()`` calls."""

    def __init__(self, shown: list | None = None) -> None:
        self._shown = shown

    def show(self) -> None:
        if self._shown is not None:
            self._shown.append(True)


class FakeMainWindowNoOp:
    """MainWindow stand-in with a no-op ``show()``."""

    def show(self) -> None:
        pass  # test double: intentionally empty


def fake_qapplication_recording(recorder: list) -> type[FakeQApplication]:
    """Return a FakeQApplication subclass that records constructor argv."""

    class _RecordingFakeQApplication(FakeQApplication):
        def __init__(self, argv: list) -> None:
            recorder.append(argv)
            super().__init__(argv)

    return _RecordingFakeQApplication
