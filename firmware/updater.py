"""Pre-flight + apply + post-flash verify for firmware updates.

Workflow (mirrors what Sentinel and BT885 Update Manager do, no
external Uniden code involved):

1. ``backup_card()`` - copy ``BCDx36HP/`` to a timestamped folder so the
   user has a known-good rollback target.
2. ``preflight()`` - confirm the SD card hosts the model we're targeting
   (``scanner.inf`` field 1 has to match), check ``requires_sub_min``
   if the manifest declares one, and refuse if the cache file failed
   its SHA-256.
3. ``apply()`` - atomic copy (``.partial`` -> ``rename``) into the right
   directory:

   - SDS100/200 Main:  ``BCDx36HP/firmware/<filename>``
   - SDS100/200 Sub:   ``BCDx36HP/firmware/sub/<filename>``
   - HPDB snapshot:    ``BCDx36HP/HPDB/<filename>``

   Layout taken from ``Metacache/Dev/RE/docs/SDS100.md``.
4. ``postflash_verify()`` - re-read ``scanner.inf`` after the user
   ejects and reboots. The scanner rewrites field 4 (firmware version)
   on first boot, so we use that to confirm the new version stuck.
"""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional, Tuple

from scanner_profiles.base import ScannerProfile

from .library import FirmwareCache, FirmwareVersion, HpdbVersion

logger = logging.getLogger(__name__)


class FirmwareError(Exception):
    """Raised when a pre-flight or apply step fails."""


@dataclass
class PreflightResult:
    ok: bool
    reason: str = ""
    detected_model: str = ""
    current_main: str = ""
    current_sub: str = ""


# ----------------------------------------------------------------------
# Card layout helpers
# ----------------------------------------------------------------------


def card_main_firmware_dir(card_root: Path) -> Path:
    return card_root / "BCDx36HP" / "firmware"


def card_sub_firmware_dir(card_root: Path) -> Path:
    return card_root / "BCDx36HP" / "firmware" / "sub"


def card_hpdb_dir(card_root: Path) -> Path:
    return card_root / "BCDx36HP" / "HPDB"


def card_scanner_inf(card_root: Path) -> Path:
    return card_root / "BCDx36HP" / "scanner.inf"


# ----------------------------------------------------------------------
# scanner.inf parsing
# ----------------------------------------------------------------------


def read_scanner_inf(card_root: Path) -> Tuple[str, str, str, str]:
    """Return ``(model, hardware_id, sw_version_main, sw_version_sub)``.

    Empty strings for missing fields (the file usually has 4 lines).
    """
    path = card_scanner_inf(card_root)
    if not path.exists():
        return ("", "", "", "")
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ("", "", "", "")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    while len(lines) < 4:
        lines.append("")
    return (lines[0], lines[1], lines[2], lines[3])


# ----------------------------------------------------------------------
# Backup
# ----------------------------------------------------------------------


def backup_card(card_root: Path, dst_root: Optional[Path] = None) -> Path:
    """Mirror ``card_root/BCDx36HP/`` to a timestamped folder.

    Returns the full destination path. Skips files that fail to copy
    rather than aborting the whole backup.
    """
    src = card_root / "BCDx36HP"
    if not src.exists():
        raise FirmwareError(f"Card has no BCDx36HP/ folder: {card_root}")
    if dst_root is None:
        dst_root = card_root.parent / "scanner-manager-backups"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = Path(dst_root) / f"{src.name}_{timestamp}"
    target.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, target, dirs_exist_ok=True)
    return target


# ----------------------------------------------------------------------
# Pre-flight
# ----------------------------------------------------------------------


def _preflight_model_check(
    model: str, _profile: ScannerProfile
) -> Optional[PreflightResult]:
    if model:
        return None
    return PreflightResult(False, "scanner.inf field 1 is empty")


def _preflight_alias_check(
    model: str,
    profile: ScannerProfile,
    ver_main: str,
    ver_sub: str,
) -> Optional[PreflightResult]:
    aliases = set(profile.scanner_inf_aliases or ()) | {profile.id}
    if model in aliases or model.upper() in {a.upper() for a in aliases}:
        return None
    return PreflightResult(
        False,
        f"Card reports model {model!r}, but the active profile is {profile.id!r}",
        detected_model=model,
        current_main=ver_main,
        current_sub=ver_sub,
    )


def _preflight_cache_check(
    profile_id: str,
    cache: FirmwareCache,
    version: Optional[FirmwareVersion],
    label: str,
    model: str,
    ver_main: str,
    ver_sub: str,
) -> Optional[PreflightResult]:
    if version is None or cache.verify(profile_id, version):
        return None
    return PreflightResult(
        False,
        f"Cached {label} firmware {version.filename} failed SHA-256 verification",
        detected_model=model,
        current_main=ver_main,
        current_sub=ver_sub,
    )


def _preflight_sub_min_check(
    ver_sub: str,
    requires_sub_min: Optional[Tuple[int, int, int]],
    model: str,
    ver_main: str,
) -> Optional[PreflightResult]:
    if requires_sub_min is None or not ver_sub:
        return None
    cur = _parse_version_text(ver_sub)
    if cur is None or cur >= requires_sub_min:
        return None
    need = "{}.{}.{}".format(*requires_sub_min)
    return PreflightResult(
        False,
        f"This main firmware requires sub firmware >= {need}; card has {ver_sub}",
        detected_model=model,
        current_main=ver_main,
        current_sub=ver_sub,
    )


def preflight(
    card_root: Path,
    profile: ScannerProfile,
    cache: FirmwareCache,
    main_version: Optional[FirmwareVersion] = None,
    sub_version: Optional[FirmwareVersion] = None,
    requires_sub_min: Optional[Tuple[int, int, int]] = None,
) -> PreflightResult:
    """Verify the card matches the profile and the cache is intact.

    All checks are read-only.
    """
    if not card_root.exists():
        return PreflightResult(False, f"Card path does not exist: {card_root}")
    if not card_scanner_inf(card_root).exists():
        return PreflightResult(False, "Card has no BCDx36HP/scanner.inf")
    model, _hw, ver_main, ver_sub = read_scanner_inf(card_root)
    for check in (
        lambda: _preflight_model_check(model, profile),
        lambda: _preflight_alias_check(model, profile, ver_main, ver_sub),
        lambda: _preflight_cache_check(
            profile.id, cache, main_version, "main", model, ver_main, ver_sub
        ),
        lambda: _preflight_cache_check(
            profile.id, cache, sub_version, "sub", model, ver_main, ver_sub
        ),
        lambda: _preflight_sub_min_check(
            ver_sub, requires_sub_min, model, ver_main
        ),
    ):
        result = check()
        if result is not None:
            return result
    return PreflightResult(
        True,
        "ok",
        detected_model=model,
        current_main=ver_main,
        current_sub=ver_sub,
    )


def _parse_version_text(text: str) -> Optional[Tuple[int, int, int]]:
    parts = text.replace("V", "").replace("v", "").split(".")
    if len(parts) < 3:
        return None
    try:
        return (int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError:
        return None


# ----------------------------------------------------------------------
# Apply
# ----------------------------------------------------------------------


def _atomic_copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".partial")
    if tmp.exists():
        tmp.unlink()
    shutil.copyfile(src, tmp)
    if dst.exists():
        dst.unlink()
    os.replace(tmp, dst)


def _purge_existing(directory: Path, suffixes: Iterable[str]) -> None:
    """Delete stale firmware images so the scanner picks up the new one.

    Sentinel removes any prior ``.bin``/``.firm`` in the firmware
    folder before copying the new image; we mirror that behavior so
    the bootloader doesn't load the older one by name precedence.
    """
    if not directory.exists():
        return
    for entry in directory.iterdir():
        if entry.is_file() and entry.suffix.lower() in suffixes:
            try:
                entry.unlink()
            except OSError:
                logger.warning("Failed to remove stale firmware: %s", entry)


def apply_main_firmware(
    card_root: Path,
    cache: FirmwareCache,
    family_id: str,
    version: FirmwareVersion,
) -> Path:
    src = cache.path_for(family_id, version)
    if not src.exists():
        raise FirmwareError(f"Cached main firmware not found: {src}")
    dst_dir = card_main_firmware_dir(card_root)
    _purge_existing(dst_dir, {".bin"})
    dst = dst_dir / version.filename
    _atomic_copy(src, dst)
    return dst


def apply_sub_firmware(
    card_root: Path,
    cache: FirmwareCache,
    family_id: str,
    version: FirmwareVersion,
) -> Path:
    src = cache.path_for(family_id, version)
    if not src.exists():
        raise FirmwareError(f"Cached sub firmware not found: {src}")
    dst_dir = card_sub_firmware_dir(card_root)
    _purge_existing(dst_dir, {".firm"})
    dst = dst_dir / version.filename
    _atomic_copy(src, dst)
    return dst


def apply_hpdb(
    card_root: Path,
    src_path: Path,
    _version: Optional[HpdbVersion] = None,
    purge_existing: bool = True,
) -> Path:
    """Copy a HPDB snapshot ``.gz`` into ``BCDx36HP/HPDB/``.

    ``src_path`` is the local file path (e.g. just downloaded by
    ``UnidenFtpClient.download``). ``version`` is purely informational.
    """
    if not src_path.exists():
        raise FirmwareError(f"HPDB source not found: {src_path}")
    dst_dir = card_hpdb_dir(card_root)
    if purge_existing:
        _purge_existing(dst_dir, {".gz"})
    dst = dst_dir / src_path.name
    _atomic_copy(src_path, dst)
    return dst


# ----------------------------------------------------------------------
# Post-flash verify
# ----------------------------------------------------------------------


def postflash_verify(
    card_root: Path,
    expected_main: Optional[FirmwareVersion] = None,
    expected_sub: Optional[FirmwareVersion] = None,
) -> Tuple[bool, str]:
    """Read ``scanner.inf`` after reboot; confirm the version sticks."""
    _model, _hw, ver_main, ver_sub = read_scanner_inf(card_root)
    if expected_main is not None and ver_main:
        cur = _parse_version_text(ver_main)
        if cur is not None and cur != expected_main.sort_key:
            want = "{}.{}.{}".format(*expected_main.sort_key)
            return (False, f"main firmware reports {ver_main}, expected {want}")
    if expected_sub is not None and ver_sub:
        cur = _parse_version_text(ver_sub)
        if cur is not None and cur != expected_sub.sort_key:
            want = "{}.{}.{}".format(*expected_sub.sort_key)
            return (False, f"sub firmware reports {ver_sub}, expected {want}")
    return (True, "ok")
