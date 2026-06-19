"""Audio capture + encoding subsystem.

The scanner has no USB-audio class device; we capture from the host
PC's soundcard input fed by the scanner's headphone jack. See
``AI/Dev/MULTI_DEVICE_GUI.md`` for the streaming architecture.

Modules:

- :mod:`audio.capture` - ``sounddevice`` input stream wrapper +
  level-meter callback.
- :mod:`audio.encoder` - MP3 (lameenc) and Opus (pyogg) encoders.
"""

from __future__ import annotations

__all__ = ["capture", "encoder"]
