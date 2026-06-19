"""Firmware update subsystem.

Modules:

- :mod:`firmware.ftp_client` - thin ``ftplib`` wrapper for the two
  Uniden update endpoints (``ftp.homepatrol.com`` for the
  BCDx36HP family + SDS100/200, ``ftp.uniden.com`` for BT885 HPDB).
- :mod:`firmware.library` - local cache + version parsing + per-family
  matching.
- :mod:`firmware.updater` - pre-flight + atomic copy + post-flash
  verify.

Endpoint inventory + update-check algorithm are documented in
``Metacache/Dev/RE/docs/uniden_update_endpoints.md``. We never modify
firmware blobs; the bytes are dropped on the SD card byte-for-byte
the same way Sentinel and BT885 Update Manager do.
"""

from __future__ import annotations

__all__ = ["ftp_client", "library", "updater"]
