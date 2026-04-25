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
ENTRY = str(REPO_ROOT / "scanner_manager.py")

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
    "tkintermapview",
    "zeep",
    "keyring",
    "qrcode",
    "scanner_profiles",
    "scanner_profiles.base",
    "scanner_profiles.registry",
    "scanner_profiles.bt885",
    "scanner_profiles.compat",
    "coverage_maps",
    "updater",
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
        "matplotlib",
        "numpy",
        "pandas",
        "scipy",
        "PIL",
        "PyQt5",
        "PyQt6",
        "PySide2",
        "PySide6",
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
                "SCANNER_MANAGER_VERSION", "0.9.0b2"
            ),
            "CFBundleVersion": os.environ.get(
                "SCANNER_MANAGER_VERSION", "0.9.0b2"
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
