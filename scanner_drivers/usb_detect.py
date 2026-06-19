"""USB / serial-port discovery for Uniden scanners.

Wraps :mod:`serial.tools.list_ports` so the GUI can answer
"is the SDS100 plugged in and in serial mode?" without reaching
into pyserial directly.

The Uniden SDS100/200 enumerates as **two** USB CDC virtual COM
ports when in serial mode:

- VID 0x1965, PID 0x001A → MAIN command port (URCP: GSI/GLG/STS/...)
- VID 0x1965, PID 0x0019 → SUB command port  (FFT/ADC debug stream)

Verified against real hardware in
``Metacache/Dev/RE/docs/SDS100_unofficial_commands.md`` Session 3.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple

from scanner_profiles import ScannerProfile

logger = logging.getLogger(__name__)

UNIDEN_VID = 0x1965
SDS_PID_MAIN = 0x001A
SDS_PID_SUB = 0x0019


@dataclass
class DetectedPort:
    """One serial port discovered by :func:`enumerate_ports`."""

    device: str          # OS-level port name (e.g. "COM7" or "/dev/ttyACM0")
    description: str
    hwid: str
    vid: Optional[int]
    pid: Optional[int]
    serial_number: Optional[str]


@dataclass
class ScannerPorts:
    """A matched (MAIN, SUB) pair for one scanner."""

    main: Optional[DetectedPort] = None
    sub: Optional[DetectedPort] = None

    @property
    def is_complete(self) -> bool:
        return self.main is not None and self.sub is not None

    @property
    def has_any(self) -> bool:
        return self.main is not None or self.sub is not None


def enumerate_ports() -> List[DetectedPort]:
    """Return every serial port currently visible to the OS.

    Returns an empty list (with a debug log line) if pyserial isn't
    installed, so calling code can decide what to do.
    """
    try:
        import serial.tools.list_ports as lp
    except ImportError:
        logger.debug("pyserial not installed; enumerate_ports returns []")
        return []

    out: List[DetectedPort] = []
    for entry in lp.comports():
        out.append(
            DetectedPort(
                device=entry.device,
                description=entry.description or "",
                hwid=entry.hwid or "",
                vid=getattr(entry, "vid", None),
                pid=getattr(entry, "pid", None),
                serial_number=getattr(entry, "serial_number", None),
            )
        )
    return out


def find_ports_for_profile(profile: ScannerProfile) -> ScannerPorts:
    """Return the (MAIN, SUB) port pair for a given profile, if found.

    Looks up :attr:`ScannerProfile.usb_vid_pid_main` /
    :attr:`usb_vid_pid_sub` and matches any visible port. If the
    profile has neither (e.g. BT885), returns an empty
    :class:`ScannerPorts`.
    """
    main_vidpid = profile.usb_vid_pid_main
    sub_vidpid = profile.usb_vid_pid_sub
    pairs = enumerate_ports()
    out = ScannerPorts()
    for port in pairs:
        if main_vidpid and out.main is None and _matches(port, main_vidpid):
            out.main = port
        elif sub_vidpid and out.sub is None and _matches(port, sub_vidpid):
            out.sub = port
    return out


def _find_sub_for_main(
    main: DetectedPort,
    sub_ports: List[DetectedPort],
    used_subs: set,
) -> Optional[DetectedPort]:
    if main.serial_number:
        for sub in sub_ports:
            if (
                sub.serial_number == main.serial_number
                and id(sub) not in used_subs
            ):
                used_subs.add(id(sub))
                return sub
    for sub in sub_ports:
        if id(sub) not in used_subs:
            used_subs.add(id(sub))
            return sub
    return None


def find_all_uniden_pairs() -> List[ScannerPorts]:
    """Return every Uniden VID port grouped by serial-number into pairs.

    A typical SDS100 produces two ports with the same USB serial
    number; we use that to disambiguate when more than one scanner is
    plugged in. Falls back to "first MAIN + first SUB" if serial-numbers
    are missing.
    """
    main_ports: List[DetectedPort] = []
    sub_ports: List[DetectedPort] = []
    for port in enumerate_ports():
        if port.vid != UNIDEN_VID:
            continue
        if port.pid == SDS_PID_MAIN:
            main_ports.append(port)
        elif port.pid == SDS_PID_SUB:
            sub_ports.append(port)
    pairs: List[ScannerPorts] = []
    used_subs = set()
    for main in main_ports:
        match = _find_sub_for_main(main, sub_ports, used_subs)
        pairs.append(ScannerPorts(main=main, sub=match))
    # Stragglers: SUB without a MAIN
    for sub in sub_ports:
        if id(sub) not in used_subs:
            pairs.append(ScannerPorts(sub=sub))
    return pairs


def _matches(port: DetectedPort, vidpid: Tuple[int, int]) -> bool:
    return port.vid == vidpid[0] and port.pid == vidpid[1]
