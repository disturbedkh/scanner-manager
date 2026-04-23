# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for Scanner Manager.
#
# Build with (from repo root):
#   pyinstaller packaging/scanner-manager.spec --noconfirm
#
# This produces dist/ScannerManager.exe on Windows. A matching release
# workflow (.github/workflows/release.yml) runs this on every v* tag
# and attaches the EXE plus its SHA-256 to the GitHub Release.
"""PyInstaller spec for the Scanner Manager one-file EXE build."""
from __future__ import annotations

import os
import sys
from pathlib import Path

# PyInstaller executes spec files via exec(), so __file__ is not set
# inside the spec body. Anchor paths to the current working directory
# instead (the build command is always run from the repo root).
REPO_ROOT = Path(os.getcwd()).resolve()
ENTRY = str(REPO_ROOT / "scanner_manager.py")
ICON_PATH = REPO_ROOT / "packaging" / "icon.ico"

# Files that must be bundled into the EXE so runtime lookups work.
datas = [
    (str(REPO_ROOT / "data" / "uniden_installers.json"), "data"),
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
    console=False,
    windowed=True,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON_PATH) if ICON_PATH.exists() else None,
)
