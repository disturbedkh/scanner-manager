"""Thin client for Uniden's two update FTP servers.

Reverse-engineered endpoints; credentials and paths verified by
static extraction from the publicly-shipped Sentinel + BT885 Update
Manager installers (see ``Metacache/Dev/RE/docs/uniden_update_endpoints.md``).

We only ever LIST + RETR. We do not write back to either server.
"""

from __future__ import annotations

import ftplib
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, List, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FtpEndpoint:
    host: str
    path: str
    user: str
    password: str
    label: str


SENTINEL_FTP = FtpEndpoint(
    host="ftp.homepatrol.com",
    path="/BCDx36HP/",
    user="homepatrolftp",
    password="green7Corn",  # NOSONAR - vendor-published read-only FTP credential
    label="Uniden Sentinel (BCDx36HP family)",
)

BT885_FTP = FtpEndpoint(
    host="ftp.uniden.com",
    path="/BT885/",
    user="BT885ftp2",
    password="89jZ53Ba",  # NOSONAR - vendor-published read-only FTP credential
    label="Uniden BT885 Update Manager",
)


@dataclass
class FtpEntry:
    """One file in the FTP listing."""

    name: str
    size_bytes: int
    modified: Optional[datetime]


class UnidenFtpClient:
    """Stateless thin wrapper around ``ftplib.FTP``.

    Each call opens a new connection - cheap on Uniden's servers
    (Sentinel itself does the same). The ``timeout`` defaults are
    generous so spotty connections don't false-fail; the GUI can
    surface the underlying ftplib error if anything goes wrong.
    """

    def __init__(
        self,
        endpoint: FtpEndpoint,
        list_timeout: float = 30.0,
        download_timeout: float = 240.0,
    ) -> None:
        self._endpoint = endpoint
        self._list_timeout = list_timeout
        self._download_timeout = download_timeout

    @property
    def endpoint(self) -> FtpEndpoint:
        return self._endpoint

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def listing(self) -> List[FtpEntry]:
        """Return the directory listing at ``endpoint.path``.

        Each entry has the filename + size + modified timestamp
        (parsed from MDTM, format ``YYYYMMDDHHMMSS``).
        """
        with ftplib.FTP(self._endpoint.host, timeout=self._list_timeout) as ftp:  # NOSONAR - Uniden firmware CDN is FTP-only
            ftp.login(self._endpoint.user, self._endpoint.password)
            ftp.cwd(self._endpoint.path)
            names = ftp.nlst()
            out: List[FtpEntry] = []
            for name in names:
                size = 0
                modified: Optional[datetime] = None
                try:
                    size = ftp.size(name) or 0
                except ftplib.error_perm:
                    pass
                try:
                    mdtm_response = ftp.sendcmd(f"MDTM {name}")
                    parts = mdtm_response.split()
                    if len(parts) >= 2:
                        modified = self._parse_mdtm(parts[1])
                except ftplib.error_perm:
                    pass
                out.append(FtpEntry(name=name, size_bytes=size, modified=modified))
            return out

    def download(
        self,
        filename: str,
        dst_path: str,
        progress_cb: Optional[Callable[[int, int], None]] = None,
        chunk_size: int = 8192,
    ) -> int:
        """Stream ``filename`` from the endpoint to ``dst_path``.

        ``progress_cb`` (if provided) receives ``(bytes_so_far, total_bytes)``
        on every chunk. Returns the total number of bytes written.
        """
        with ftplib.FTP(self._endpoint.host, timeout=self._download_timeout) as ftp:  # NOSONAR - Uniden firmware CDN is FTP-only
            ftp.login(self._endpoint.user, self._endpoint.password)
            ftp.cwd(self._endpoint.path)
            try:
                total = ftp.size(filename) or 0
            except ftplib.error_perm:
                total = 0
            written = 0
            with open(dst_path, "wb") as f:
                def write_chunk(chunk: bytes) -> None:
                    nonlocal written
                    f.write(chunk)
                    written += len(chunk)
                    if progress_cb is not None:
                        try:
                            progress_cb(written, total)
                        except Exception:
                            pass
                ftp.retrbinary(f"RETR {filename}", write_chunk, blocksize=chunk_size)
            return written

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_mdtm(text: str) -> Optional[datetime]:
        """Parse FTP MDTM ``YYYYMMDDHHMMSS[.fraction]``."""
        if not text:
            return None
        text = text.split(".", 1)[0]
        try:
            return datetime.strptime(text[:14], "%Y%m%d%H%M%S")
        except ValueError:
            return None
