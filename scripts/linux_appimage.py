"""Stage a Linux AppDir and optionally run appimagetool.

Used by ``scripts/build_release.py`` after the one-file PyInstaller
binary is produced. Tar.gz remains the release SSOT; AppImage is an
additional desktop-friendly artifact.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

_APP_NAME = "ScannerManager"
_APPIMAGE_NAME = "ScannerManager-x86_64.AppImage"
_DESKTOP_NAME = "scanner-manager.desktop"
_ICON_NAME = "scanner-manager.png"
_UDEV_NAME = "99-uniden-scanner.rules"


def desktop_file_path(repo_root: Path) -> Path:
    return repo_root / "packaging" / "linux" / _DESKTOP_NAME


def icon_file_path(repo_root: Path) -> Path:
    return repo_root / "packaging" / "linux" / _ICON_NAME


def udev_file_path(repo_root: Path) -> Path:
    return repo_root / "packaging" / "linux" / _UDEV_NAME


def parse_desktop_keys(text: str) -> dict[str, str]:
    """Parse key=value lines from a .desktop file (ignores sections/comments)."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("["):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip()
    return out


def required_desktop_keys() -> tuple[str, ...]:
    return ("Type", "Name", "Exec", "Icon", "Categories")


def stage_appdir(
    *,
    repo_root: Path,
    binary: Path,
    appdir: Path,
) -> Path:
    """Populate *appdir* for AppImage packaging. Returns *appdir*.

    Layout (AppImage convention)::

        AppDir/
          AppRun -> usr/bin/ScannerManager
          scanner-manager.desktop
          scanner-manager.png
          usr/bin/ScannerManager
          usr/share/applications/scanner-manager.desktop
          usr/share/icons/hicolor/256x256/apps/scanner-manager.png
          usr/share/doc/scanner-manager/99-uniden-scanner.rules
          usr/share/doc/scanner-manager/README-udev.txt
    """
    if not binary.is_file():
        raise FileNotFoundError(f"Frozen binary missing: {binary}")
    desktop_src = desktop_file_path(repo_root)
    icon_src = icon_file_path(repo_root)
    udev_src = udev_file_path(repo_root)
    if not desktop_src.is_file():
        raise FileNotFoundError(f"Missing desktop entry: {desktop_src}")
    if not icon_src.is_file():
        raise FileNotFoundError(f"Missing AppImage icon: {icon_src}")

    if appdir.exists():
        shutil.rmtree(appdir)
    bin_dir = appdir / "usr" / "bin"
    apps_dir = appdir / "usr" / "share" / "applications"
    icons_dir = appdir / "usr" / "share" / "icons" / "hicolor" / "256x256" / "apps"
    doc_dir = appdir / "usr" / "share" / "doc" / "scanner-manager"
    for d in (bin_dir, apps_dir, icons_dir, doc_dir):
        d.mkdir(parents=True, exist_ok=True)

    dest_bin = bin_dir / _APP_NAME
    shutil.copy2(binary, dest_bin)
    dest_bin.chmod(0o755)

    desktop_text = desktop_src.read_text(encoding="utf-8")
    keys = parse_desktop_keys(desktop_text)
    for req in required_desktop_keys():
        if req not in keys:
            raise ValueError(f"Desktop file missing required key: {req}")

    apps_desktop = apps_dir / _DESKTOP_NAME
    apps_desktop.write_text(desktop_text, encoding="utf-8")
    shutil.copy2(apps_desktop, appdir / _DESKTOP_NAME)

    icon_dest = icons_dir / _ICON_NAME
    shutil.copy2(icon_src, icon_dest)
    shutil.copy2(icon_src, appdir / _ICON_NAME)

    if udev_src.is_file():
        shutil.copy2(udev_src, doc_dir / _UDEV_NAME)
        (doc_dir / "README-udev.txt").write_text(
            "Uniden CDC serial udev rules (optional host install):\n"
            f"  sudo cp usr/share/doc/scanner-manager/{_UDEV_NAME} "
            "/etc/udev/rules.d/\n"
            "  sudo udevadm control --reload-rules && sudo udevadm trigger\n"
            "  sudo usermod -aG dialout \"$USER\"  # then re-login\n"
            "\n"
            "The AppImage does not install udev rules automatically.\n",
            encoding="utf-8",
        )

    apprun = appdir / "AppRun"
    if apprun.exists() or apprun.is_symlink():
        apprun.unlink()
    # Relative symlink so the AppDir is relocatable; fall back to a
    # shell wrapper when symlinks are unavailable (e.g. Windows tests).
    try:
        apprun.symlink_to(Path("usr") / "bin" / _APP_NAME)
    except OSError:
        apprun.write_text(
            "#!/bin/sh\n"
            "exec \"$(dirname \"$0\")/usr/bin/ScannerManager\" \"$@\"\n",
            encoding="utf-8",
            newline="\n",
        )
        apprun.chmod(0o755)

    return appdir


def find_appimagetool() -> Optional[Path]:
    env = os.environ.get("APPIMAGE_TOOL", "").strip()
    if env:
        path = Path(env)
        if path.is_file():
            return path
    which = shutil.which("appimagetool")
    return Path(which) if which else None


def build_appimage(
    *,
    repo_root: Path,
    binary: Path,
    out_dir: Path,
    appimagetool: Optional[Path] = None,
) -> Optional[Path]:
    """Stage AppDir and run appimagetool. Returns AppImage path or None if skipped."""
    tool = appimagetool if appimagetool is not None else find_appimagetool()
    if tool is None:
        print(
            "appimagetool not found (set APPIMAGE_TOOL or install on PATH); "
            "skipping AppImage",
            flush=True,
        )
        return None

    appdir = out_dir / "ScannerManager.AppDir"
    stage_appdir(repo_root=repo_root, binary=binary, appdir=appdir)
    out_path = out_dir / _APPIMAGE_NAME
    if out_path.exists():
        out_path.unlink()
    env = os.environ.copy()
    # Continuous/build without FUSE on CI containers
    env.setdefault("APPIMAGE_EXTRACT_AND_RUN", "1")
    print("+", tool, appdir, out_path, flush=True)
    subprocess.run(
        [str(tool), str(appdir), str(out_path)],
        cwd=out_dir,
        env=env,
        check=True,
    )
    if not out_path.is_file():
        raise SystemExit(f"appimagetool did not produce {out_path}")
    out_path.chmod(0o755)
    return out_path
