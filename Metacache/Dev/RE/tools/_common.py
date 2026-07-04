"""Shared helpers for ``Metacache/Dev/RE/tools/`` scripts.

The goal of this module is twofold:

1. Centralise the small bits of knowledge that every probe / decoder
   in the tools tree needs: Uniden's USB VID, the MAIN/SUB PIDs, where
   the repo root lives relative to the tools directory, where to write
   probe sessions and pcap captures, etc.

2. Force every tool to be **portable across machines**. None of the
   modules in ``tools/`` should hard-code ``COM4`` or ``E:\\`` or a
   specific user's home directory. Instead, they should call helpers
   from this module, which:

   - auto-detects an Uniden CDC port by VID/PID at runtime,
   - requires an explicit ``--port`` if multiple candidates are
     present and discovery is ambiguous,
   - resolves the repo root from the importing file's location
     (``__file__``-based, no environment assumptions).

This is intentionally a **lightweight** module - no numpy, no
pyserial-required-at-import. The only third-party import is
``pyserial.tools.list_ports``, gated behind a try/except so callers
that don't need port detection (e.g. firmware-blob analysers) can
import this module without pyserial installed.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import re
import sys
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# USB identity of the Uniden SDS100 / SDS200 / BCDx36HP family
# ---------------------------------------------------------------------------
# These are public constants from `lsusb` / `Get-PnpDevice` output and
# from the official Sentinel installer's INF files. They're not PII -
# every SDS100 in the world has these VID/PIDs.
UNIDEN_VID: int = 0x1965
UNIDEN_MAIN_PID: int = 0x001A   # MAIN MCU (Uniden Remote Command Protocol)
UNIDEN_SUB_PID: int = 0x0019    # SUB MCU (DSP/RF debug surface)

# Convenience set used when filtering ports by *any* Uniden CDC.
UNIDEN_PIDS: frozenset[int] = frozenset({UNIDEN_MAIN_PID, UNIDEN_SUB_PID})


# ---------------------------------------------------------------------------
# Path helpers - everything is anchored to the repo root, computed from
# the location of this very file. This makes the tools work whether the
# repo is cloned to ``/home/dev/code/scanner-manager``,
# ``C:\Users\X\scanner-manager``, or anywhere else.
# ---------------------------------------------------------------------------

# tools/_common.py -> tools/ -> RE/ -> Dev/ -> AI/ -> <repo root>
REPO_ROOT: Path = Path(__file__).resolve().parents[4]
RE_ROOT: Path = REPO_ROOT / "AI" / "Dev" / "RE"
TOOLS_ROOT: Path = RE_ROOT / "tools"
SESSIONS_DIR: Path = RE_ROOT / "sessions"
PCAPS_DIR: Path = RE_ROOT / "sentinel_pcaps"
FIRMWARE_DIR: Path = RE_ROOT / "firmware"
FIRMWARE_ANALYSIS_DIR: Path = RE_ROOT / "firmware_analysis"
DOCS_DIR: Path = RE_ROOT / "docs"
SPECS_DIR: Path = RE_ROOT / "specs"


def ensure_dir(path: Path) -> Path:
    """Create ``path`` (and parents) if missing; return it."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def safe_user_path(base: Path, user_path: Path | str) -> Path:
    """Resolve ``user_path`` under ``base``; reject directory traversal."""
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from core.path_utils import safe_resolve_path

    return safe_resolve_path(base, user_path)


def validate_executable(path: Path | str, *, label: str = "executable") -> Path:
    """Return a resolved executable path or raise ``FileNotFoundError``."""
    resolved = Path(path).expanduser().resolve(strict=False)
    if not resolved.is_file():
        raise FileNotFoundError(f"{label} not found: {resolved}")
    return resolved


_USBPCAP_INTERFACE_RE = re.compile(r"^\\\\\.\\USBPcap\d+$", re.IGNORECASE)


def validate_usbpcap_interface(interface: str) -> str:
    """Reject malformed USBPcap interface tokens before subprocess use."""
    if not _USBPCAP_INTERFACE_RE.match(interface):
        raise ValueError(f"Invalid USBPcap interface: {interface!r}")
    return interface


def validate_drive_root(drive: str) -> Path:
    """Accept a Windows drive root like ``E:`` or ``E:\\``."""
    text = str(drive).strip().rstrip("\\/")
    if not re.fullmatch(r"[A-Za-z]:", text):
        raise ValueError(f"Invalid drive root: {drive!r}")
    return Path(text + "\\")


def validate_capture_devices(devices: str) -> str:
    """Allow only comma-separated decimal USB device addresses."""
    if not re.fullmatch(r"\d+(?:,\d+)*", devices.strip()):
        raise ValueError(f"Invalid --devices value: {devices!r}")
    return devices.strip()


def utc_stamp(fmt: str = "%Y%m%dT%H%M%SZ") -> str:
    """UTC timestamp suitable for filenames."""
    return _dt.datetime.now(tz=_dt.timezone.utc).strftime(fmt)


# ---------------------------------------------------------------------------
# Port detection - lazy import so we don't force pyserial on tools that
# don't need it (e.g. firmware blob analysers).
# ---------------------------------------------------------------------------

class PortDetectionError(RuntimeError):
    """Raised when the user-requested port can't be located or is
    ambiguous and no ``--port`` was passed."""


def list_uniden_ports() -> list:
    """Return a list of pyserial ``ListPortInfo`` for every Uniden CDC
    port currently visible to the OS.

    Empty list if no scanner is connected or pyserial isn't installed.
    """
    try:
        import serial.tools.list_ports as lp  # type: ignore
    except ImportError as e:  # pragma: no cover - environmental
        raise PortDetectionError(
            "pyserial is required for port detection. "
            "Install with: py -m pip install --user pyserial"
        ) from e

    return [
        p for p in lp.comports()
        if p.vid == UNIDEN_VID and p.pid in UNIDEN_PIDS
    ]


def find_uniden_port(
    *,
    pid: Optional[int] = None,
    explicit: Optional[str] = None,
) -> str:
    """Resolve a single Uniden CDC port to use.

    Resolution order:
      1. If ``explicit`` (e.g. from ``--port COM4``) is given, return it
         as-is - we trust the user.
      2. If ``pid`` is given, look for exactly one matching port and
         return its device name.
      3. Otherwise, look for exactly one Uniden port total and return it.

    Raises ``PortDetectionError`` if zero or more than one port matches
    and no explicit override is provided.
    """
    if explicit:
        return explicit

    candidates = list_uniden_ports()
    if pid is not None:
        candidates = [p for p in candidates if p.pid == pid]

    if not candidates:
        raise PortDetectionError(
            f"No Uniden CDC port found (VID=0x{UNIDEN_VID:04x}"
            + (f", PID=0x{pid:04x}" if pid is not None else "")
            + "). Plug the scanner in, switch it to Serial Mode, "
              "then re-run."
        )
    if len(candidates) > 1:
        names = ", ".join(p.device for p in candidates)
        raise PortDetectionError(
            f"Multiple Uniden ports detected ({names}); pass "
            f"--port <DEVICE> to pick one."
        )
    return candidates[0].device


def require_port(
    args: argparse.Namespace,
    *,
    pid: Optional[int] = None,
    attr: str = "port",
) -> str:
    """Convenience wrapper for argparse-driven scripts.

    Reads ``args.<attr>`` (default ``args.port``). If unset, calls
    :func:`find_uniden_port` to auto-discover. Returns a port name like
    ``COM4`` or ``/dev/ttyACM0``.
    """
    explicit = getattr(args, attr, None)
    return find_uniden_port(pid=pid, explicit=explicit)


def add_port_arg(
    parser: argparse.ArgumentParser,
    *,
    flag: str = "--port",
    help_extra: str = "",
) -> None:
    """Standardised ``--port`` flag for tools.

    Tools should call this instead of inventing their own copy. Keeps
    help text consistent and makes it easy to grep for them later.
    """
    parser.add_argument(
        flag,
        default=None,
        help=(
            "Serial device to use (e.g. COM4, /dev/ttyACM0). If "
            "omitted, auto-detect by Uniden VID/PID. "
        ) + help_extra,
    )


# ---------------------------------------------------------------------------
# Generic file-rotation helper used by tools that produce binary captures
# (USBPcap pcaps, .disk.bin reconstructions, etc.).
# ---------------------------------------------------------------------------

def find_latest_sub_firmware() -> Optional[Path]:
    """Locate the canonical SUB firmware blob to analyse.

    Returns the most-recently-modified ``*_inflated.bin`` in
    ``Metacache/Dev/RE/firmware/``, or ``None`` if no inflated SUB firmware
    has been generated yet (run ``tools/firmware/inflate_sub.py``
    first).

    Tools that statically analyse SUB firmware should use this as a
    default when the user doesn't pass ``--firmware <path>``.
    """
    if not FIRMWARE_DIR.exists():
        return None
    matches = sorted(
        FIRMWARE_DIR.glob("*_inflated.bin"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return matches[0] if matches else None


def find_latest_sub_strings() -> Optional[Path]:
    """Locate the most-recently-extracted SUB-firmware strings file.

    Returns the most-recently-modified ``sub_*.strings.txt`` in
    ``Metacache/Dev/RE/firmware_analysis/``, or ``None`` if none exists.
    """
    if not FIRMWARE_ANALYSIS_DIR.exists():
        return None
    matches = sorted(
        FIRMWARE_ANALYSIS_DIR.glob("sub_*.strings.txt"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return matches[0] if matches else None


def add_firmware_arg(
    parser: argparse.ArgumentParser,
    *,
    flag: str = "--firmware",
    help_text: str = "Path to firmware blob to analyse. Default: most-recent inflated SUB blob in Metacache/Dev/RE/firmware/.",
) -> None:
    """Standardised ``--firmware`` flag for tools that consume a
    firmware binary. The default is computed lazily so help text
    doesn't bake in a specific filename."""
    parser.add_argument(flag, type=Path, default=None, help=help_text)


def resolve_firmware(
    args: argparse.Namespace,
    *,
    attr: str = "firmware",
    finder=find_latest_sub_firmware,
) -> Path:
    """Read ``args.<attr>``; if unset, fall back to ``finder()``.

    Raises ``FileNotFoundError`` if neither user-supplied nor
    discoverable.
    """
    explicit = getattr(args, attr, None)
    if explicit:
        return safe_user_path(REPO_ROOT, explicit)
    found = finder()
    if not found:
        raise FileNotFoundError(
            "No firmware blob given and none found by auto-discovery. "
            f"Pass --{attr} <path> or place a *_inflated.bin in {FIRMWARE_DIR}."
        )
    return found


def rotate_path(target: Path, *, suffix_format: str = "%Y%m%dT%H%M%SZ") -> Path:
    """If ``target`` already exists, return a sibling path with a UTC
    timestamp suffix; otherwise return ``target`` unchanged.

    Example:
        ``foo.pcap`` -> ``foo.20260503T112900Z.pcap`` if ``foo.pcap``
        already exists on disk.

    This exists primarily to work around USBPcap's "Thread started
    with invalid write handle!" error, which surfaces when a previous
    capture session has the file locked.
    """
    if not target.exists():
        return target
    stem = target.stem
    suffix = target.suffix
    stamp = _dt.datetime.now(tz=_dt.timezone.utc).strftime(suffix_format)
    return target.with_name(f"{stem}.{stamp}{suffix}")


__all__ = [
    "UNIDEN_VID",
    "UNIDEN_MAIN_PID",
    "UNIDEN_SUB_PID",
    "UNIDEN_PIDS",
    "REPO_ROOT",
    "RE_ROOT",
    "TOOLS_ROOT",
    "SESSIONS_DIR",
    "PCAPS_DIR",
    "FIRMWARE_DIR",
    "FIRMWARE_ANALYSIS_DIR",
    "DOCS_DIR",
    "SPECS_DIR",
    "ensure_dir",
    "safe_user_path",
    "validate_executable",
    "validate_usbpcap_interface",
    "validate_drive_root",
    "validate_capture_devices",
    "utc_stamp",
    "PortDetectionError",
    "list_uniden_ports",
    "find_uniden_port",
    "require_port",
    "add_port_arg",
    "find_latest_sub_firmware",
    "find_latest_sub_strings",
    "add_firmware_arg",
    "resolve_firmware",
    "rotate_path",
]


def _selftest() -> None:
    """Smoke-test: verify path constants resolve sanely. Run with:
        py Metacache/Dev/RE/tools/_common.py
    """
    print(f"REPO_ROOT          = {REPO_ROOT}")
    print(f"RE_ROOT            = {RE_ROOT}     exists={RE_ROOT.exists()}")
    print(f"TOOLS_ROOT         = {TOOLS_ROOT}  exists={TOOLS_ROOT.exists()}")
    print(f"SESSIONS_DIR       = {SESSIONS_DIR}")
    print(f"PCAPS_DIR          = {PCAPS_DIR}")
    print(f"FIRMWARE_DIR       = {FIRMWARE_DIR}")
    print(f"DOCS_DIR           = {DOCS_DIR}")
    try:
        ports = list_uniden_ports()
    except PortDetectionError as e:
        print(f"\n(port detection skipped: {e})")
        return
    if not ports:
        print("\n(no Uniden CDC ports currently connected)")
        return
    print("\nUniden CDC ports currently visible:")
    for p in ports:
        if p.pid == UNIDEN_MAIN_PID:
            role = "MAIN"
        elif p.pid == UNIDEN_SUB_PID:
            role = "SUB"
        else:
            role = "?"
        print(f"  {p.device}  PID=0x{p.pid:04x} ({role})  {p.description}")


if __name__ == "__main__":
    _selftest()
