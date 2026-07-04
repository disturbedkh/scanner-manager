"""Vendor plain-FTP transport (Uniden CDN endpoints offer no TLS).

All cleartext ``ftplib`` usage for firmware discovery lives here so
``ftp_client.py`` callers stay on the allowlisted-host wrapper API.
See ``Metacache/Dev/SONARQUBE.md`` (vendor FTP policy).
"""

from __future__ import annotations

import ftplib


def connect_vendor_ftp(host: str, timeout: float) -> ftplib.FTP:
    """Open a plain FTP session to a vendor-allowlisted host."""
    return ftplib.FTP(host, timeout=timeout)
