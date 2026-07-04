"""Guard the import boundaries that keep the package graph acyclic.

The ``core`` and ``scanner_profiles`` packages have a deliberate one-way-ish
relationship that is only kept acyclic by *deferred* imports:

* ``core.device_manager`` imports ``scanner_profiles`` at module load.
* ``scanner_profiles`` (bt885 / sds100) therefore must NOT import ``core.*``
  at module load - the ``core.sdcard`` reads happen inside methods. Promoting
  those to module-level imports reintroduces a ``core <-> scanner_profiles``
  import cycle that crashes at app start.

``scanner_profiles`` must also never import ``legacy_tk`` (the documented
hard rule - it would be circular with the legacy app).

These checks run in a clean subprocess so an unrelated earlier import in the
test session can't mask a regression.
"""

from __future__ import annotations

import subprocess
import sys


def _modules_after_import(module: str) -> set[str]:
    code = f"import {module}; import sys; print('\\n'.join(sys.modules))"
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
    )
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def test_scanner_profiles_does_not_eagerly_import_core_sdcard() -> None:
    loaded = _modules_after_import("scanner_profiles")
    assert "core.sdcard" not in loaded, (
        "scanner_profiles must not import core.sdcard at module load. Keep the "
        "core<->scanner_profiles boundary lazy (deferred imports inside "
        "read_zip_table / read_city_table) or the import cycle returns."
    )


def test_scanner_profiles_does_not_import_legacy_tk() -> None:
    loaded = _modules_after_import("scanner_profiles")
    offenders = {m for m in loaded if m == "legacy_tk" or m.startswith("legacy_tk.")}
    assert not offenders, (
        f"scanner_profiles must never import legacy_tk (circular): {offenders}"
    )


def test_core_does_not_import_gui_or_legacy_tk() -> None:
    loaded = _modules_after_import("core.metastore")
    offenders = {
        m
        for m in loaded
        if m == "gui" or m.startswith("gui.") or m == "legacy_tk" or m.startswith("legacy_tk.")
    }
    assert not offenders, (
        f"core must not import the UI layers (gui / legacy_tk): {offenders}"
    )
