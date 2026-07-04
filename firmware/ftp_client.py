"""Thin client for Uniden's two update FTP servers.

Reverse-engineered endpoints; credentials and paths verified by
static extraction from the publicly-shipped Sentinel + BT885 Update
Manager installers (see ``Metacache/Dev/RE/docs/uniden_update_endpoints.md``).

Credentials are loaded from ``data/uniden_installers.json`` at runtime.
We only ever LIST + RETR on vendor-allowlisted hosts.
"""

from __future__ import annotations

import ftplib
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, FrozenSet, List, Optional

logger = logging.getLogger(__name__)

_MANIFEST_PATH = Path(__file__).resolve().parent.parent / "data" / "uniden_installers.json"
_FTP_ALLOWED_HOSTS: FrozenSet[str] = frozenset()


@dataclass(frozen=True)
class FtpEndpoint:
    host: str
    path: str
    user: str
    password: str
    label: str


def _load_manifest() -> dict:
    with _MANIFEST_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def _endpoint_from_manifest(manifest: dict, key: str) -> FtpEndpoint:
    raw = manifest["ftp_endpoints"][key]
    return FtpEndpoint(
        host=raw["host"],
        path=raw["path"],
        user=raw["user"],
        password=raw["password"],
        label=raw["label"],
    )


def _build_endpoints() -> tuple[FtpEndpoint, FtpEndpoint, FrozenSet[str]]:
    manifest = _load_manifest()
    allowed = frozenset(str(h).lower() for h in manifest.get("ftp_allowed_hosts", []))
    sentinel = _endpoint_from_manifest(manifest, "sentinel")
    bt885 = _endpoint_from_manifest(manifest, "bt885")
    for ep in (sentinel, bt885):
        if ep.host.lower() not in allowed:
            raise ValueError(f"FTP host not allowlisted: {ep.host}")
    return sentinel, bt885, allowed


SENTINEL_FTP, BT885_FTP, _FTP_ALLOWED_HOSTS = _build_endpoints()


@dataclass
class FtpEntry:
    """One file in the FTP listing."""

    name: str
    size_bytes: int
    modified: Optional[datetime]


class UnidenFtpClient:
    """Stateless thin wrapper around ``ftplib.FTP``."""

    def __init__(
        self,
        endpoint: FtpEndpoint,
        list_timeout: float = 30.0,
        download_timeout: float = 240.0,
    ) -> None:
        if endpoint.host.lower() not in _FTP_ALLOWED_HOSTS:
            raise ValueError(f"Refusing FTP connection to non-allowlisted host: {endpoint.host}")
        self._endpoint = endpoint
        self._list_timeout = list_timeout
        self._download_timeout = download_timeout

    @property
    def endpoint(self) -> FtpEndpoint:
        return self._endpoint

    def listing(self) -> List[FtpEntry]:
        """Return the directory listing at ``endpoint.path``."""
        with self._open_ftp(self._list_timeout) as ftp:
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
        """Stream ``filename`` from the endpoint to ``dst_path``."""
        with self._open_ftp(self._download_timeout) as ftp:
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

    def _open_ftp(self, timeout: float) -> ftplib.FTP:
        """Open FTP to the configured vendor host (Uniden CDN is FTP-only)."""
        return ftplib.FTP(self._endpoint.host, timeout=timeout)

    @staticmethod
    def _parse_mdtm(text: str) -> Optional[datetime]:
        if not text:
            return None
        text = text.split(".", 1)[0]
        try:
            return datetime.strptime(text[:14], "%Y%m%d%H%M%S")
        except ValueError:
            return None
