"""Live serial-mode drivers for Uniden scanners.

The driver layer is **GUI-agnostic**: each module exposes pure-Python
classes that produce typed events (``GsiSnapshot``, ``GlgEvent``,
``WaterfallFrame``). The Qt live-mode dock subscribes via Qt signals;
the streaming server subscribes via a callback queue.

Supported scanners:

- Uniden SDS100 / SDS200 (USB CDC; VID 0x1965, MAIN PID 0x001A,
  SUB PID 0x0019).

Not supported (no serial-mode RE):

- BearTracker 885 - returns no profile from
  ``scanner_profiles.detect_from_card`` for the live dock.

Safety: every command sent must be on the
:data:`scanner_drivers.serial_main.SAFE_QUERIES` whitelist; commands
on :data:`scanner_drivers.serial_main.FORBIDDEN_HEADS` are rejected
hard at the driver layer regardless of source.
"""

from __future__ import annotations

__all__ = [
    "usb_detect",
    "serial_main",
    "serial_sub",
]
