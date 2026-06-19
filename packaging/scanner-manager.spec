# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for Scanner Manager - cross-platform.
#
# Build with (from repo root):
#   pyinstaller packaging/scanner-manager.spec --noconfirm
#
# Produces:
#   Windows : dist/ScannerManager.exe          (one-file, windowed)
#   macOS   : dist/ScannerManager.app          (.app bundle)
#             + dist/ScannerManager             (matching unix binary)
#   Linux   : dist/ScannerManager              (one-file, windowed)
#
# A release workflow (.github/workflows/release.yml) runs this spec on
# windows-latest, macos-latest, and ubuntu-latest and attaches each
# platform's artifact to the GitHub Release.
"""PyInstaller spec for the Scanner Manager one-file build."""
from __future__ import annotations

import os
import sys
from pathlib import Path

# PyInstaller executes spec files via exec(), so __file__ is not set
# inside the spec body. Anchor paths to the current working directory
# instead (the build command is always run from the repo root).
REPO_ROOT = Path(os.getcwd()).resolve()
# Phase 6 cutover: the Qt shell (gui/app.py) is now the default
# packaged entry. The legacy Tk app at scanner_manager.py is still
# importable as the `scanner-manager-tk` console script for users
# who explicitly opt into it, but we no longer ship the Tk shell as
# the default frozen binary.
ENTRY = str(REPO_ROOT / "gui" / "app.py")

IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"
IS_LINUX = not IS_WINDOWS and not IS_MACOS

# Icons:
#  * Windows prefers .ico (multi-resolution)
#  * macOS needs .icns for .app bundles
#  * Linux accepts .ico/.png but PyInstaller ignores it for the binary
ICO_PATH = REPO_ROOT / "packaging" / "icon.ico"
ICNS_PATH = REPO_ROOT / "packaging" / "icon.icns"
if IS_MACOS and ICNS_PATH.exists():
    ICON: str | None = str(ICNS_PATH)
elif ICO_PATH.exists():
    ICON = str(ICO_PATH)
else:
    ICON = None

# Files that must be bundled into the EXE so runtime lookups work.
datas = [
    (str(REPO_ROOT / "data" / "uniden_installers.json"), "data"),
    (str(REPO_ROOT / "data" / "scanner_profiles.json"), "data"),
    (str(REPO_ROOT / "LICENSE"), "."),
    (str(REPO_ROOT / "DISCLAIMER.md"), "."),
    (str(REPO_ROOT / "THIRD_PARTY_NOTICES.md"), "."),
]
optional = REPO_ROOT / "data" / "zip_county_map.json"
if optional.exists():
    datas.append((str(optional), "data"))

# Optional third-party deps. We guard every import in the app with
# try/except, so PyInstaller won't crash when these aren't installed in
# the build environment. Listing them as hiddenimports just ensures
# they *do* get included when they are present.
hiddenimports = [
    # Optional third-party deps - guarded with try/except in app code.
    "zeep",
    "keyring",
    "qrcode",
    # Scanner-profile registry: each profile self-registers at import,
    # so we hint PyInstaller to keep them all bundled.
    "scanner_profiles",
    "scanner_profiles.base",
    "scanner_profiles.registry",
    "scanner_profiles.bt885",
    "scanner_profiles.sds100",
    # Backend modules (core package + legacy Tk).
    "core",
    "core.metastore",
    "core.sdcard",
    "core.coverage_maps",
    "core.rr_api",
    "core.device_manager",
    "core.uniden_tools",
    "core.app_updater",
    "legacy_tk",
    "legacy_tk.scanner_manager",
    "virtual_sd",
    "virtual_sd.virtual_card",
    "gui",
    "gui.app",
    "gui.main_window",
    "gui.header",
    "gui.windows",
    "gui.editor",
    "gui.editor.editor_dock",
    "gui.live",
    "gui.live.live_dock",
    "gui.streaming",
    "gui.firmware",
    "gui.firmware.firmware_dock",
    "gui.dialogs",
    "scanner_drivers",
    "scanner_drivers.serial_main",
    "scanner_drivers.serial_sub",
    "scanner_drivers.usb_detect",
    "audio",
    "audio.capture",
    "audio.encoder",
    "streaming",
    "streaming.server",
    "streaming.icecast",
    "streaming.broadcastify",
    "firmware",
    "firmware.ftp_client",
    "firmware.library",
    "firmware.updater",
    # Qt shell.
    "PySide6",
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "pyqtgraph",
    "pyserial",
    "sounddevice",
    "numpy",
    "fastapi",
    "uvicorn",
    "websockets",
    "httpx",
    "lameenc",
    "pyogg",
]

block_cipher = None


a = Analysis(
    [ENTRY],
    pathex=[str(REPO_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Cut-outs: we don't use any of these and they balloon the EXE.
        # NOTE: PySide6 is no longer excluded - it's the default UI now.
        "matplotlib",
        "pandas",
        "scipy",
        "PIL",
        "PyQt5",
        "PyQt6",
        "PySide2",
        # Tk drag-along: we still ship the legacy Tk app via the
        # `scanner-manager-tk` entry, but the frozen build targets the
        # Qt shell, so we can drop tkintermapview to shed weight.
        "tkintermapview",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="ScannerManager",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    # windowed=True hides the console on Windows and suppresses stdout
    # attachment on macOS. On Linux it's effectively a no-op - the
    # binary will still produce output if launched from a terminal.
    console=False,
    windowed=True,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON,
)

# macOS-specific .app bundle. On Windows / Linux the EXE above is the
# final artifact; macOS expects a ``.app`` directory so Finder can show
# the icon and double-click handlers work correctly.
if IS_MACOS:
    app = BUNDLE(
        exe,
        name="ScannerManager.app",
        icon=ICON,
        bundle_identifier="org.disturbedkh.scanner-manager",
        info_plist={
            "CFBundleName": "Scanner Manager",
            "CFBundleDisplayName": "Scanner Manager",
            "CFBundleShortVersionString": os.environ.get(
                "SCANNER_MANAGER_VERSION", "0.10.0"
            ),
            "CFBundleVersion": os.environ.get(
                "SCANNER_MANAGER_VERSION", "0.10.0"
            ),
            "NSHighResolutionCapable": True,
            # We read removable SD cards; declare the usage description
            # so Finder prompts nicely on recent macOS versions.
            "NSRemovableVolumesUsageDescription": (
                "Scanner Manager reads and writes HPD configuration "
                "files on your scanner's SD card."
            ),
        },
    )
