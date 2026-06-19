"""Smoke tests for firmware.ftp_client.

We don't hit the real Uniden FTP server in CI; we stub ``ftplib.FTP``
with a fake transport that records every command and returns canned
listings + bytes. This validates:

- ``UnidenFtpClient.listing`` issues the right login + cwd + nlst +
  size + MDTM commands and parses MDTM correctly.
- ``UnidenFtpClient.download`` writes the streamed bytes to disk and
  invokes the progress callback.
- The two endpoint constants point at the right hosts.
"""

from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

import pytest

from firmware import ftp_client as ftp_module
from firmware.ftp_client import (
    BT885_FTP,
    SENTINEL_FTP,
    UnidenFtpClient,
)

# ----------------------------------------------------------------------
# Fakes
# ----------------------------------------------------------------------


class _FakeFtp:
    """Stand-in for ``ftplib.FTP`` that records calls."""

    DEFAULT_LISTING = [
        "SDS-100_V1_26_01.bin",
        "SDS-100-SUB_V1_03_15.firm",
        "MasterHpdb_05_03_2026.gz",
    ]
    DEFAULT_SIZES = {
        "SDS-100_V1_26_01.bin": 2_165_424,
        "SDS-100-SUB_V1_03_15.firm": 89_120,
        "MasterHpdb_05_03_2026.gz": 12_115_456,
    }
    DEFAULT_MDTMS = {
        "SDS-100_V1_26_01.bin": "20260419120145",
        "SDS-100-SUB_V1_03_15.firm": "20251017090030",
        "MasterHpdb_05_03_2026.gz": "20260503000000",
    }

    instances: List["_FakeFtp"] = []

    def __init__(self, host=None, timeout=None, listing=None, sizes=None, mdtms=None,
                 retr_payload=b""):
        self.host = host
        self.timeout = timeout
        self.commands: List[str] = []
        self.cwd_path: str = ""
        self._listing = listing if listing is not None else list(self.DEFAULT_LISTING)
        self._sizes = sizes if sizes is not None else dict(self.DEFAULT_SIZES)
        self._mdtms = mdtms if mdtms is not None else dict(self.DEFAULT_MDTMS)
        self._retr_payload = retr_payload
        _FakeFtp.instances.append(self)

    # context-manager protocol
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def login(self, user, password):
        self.commands.append(f"USER {user}")
        self.commands.append(f"PASS {password}")

    def cwd(self, path):
        self.cwd_path = path
        self.commands.append(f"CWD {path}")

    def nlst(self):
        self.commands.append("NLST")
        return list(self._listing)

    def size(self, name):
        self.commands.append(f"SIZE {name}")
        return self._sizes.get(name)

    def sendcmd(self, cmd):
        self.commands.append(cmd)
        if cmd.startswith("MDTM "):
            name = cmd.split(" ", 1)[1]
            ts = self._mdtms.get(name)
            if ts is None:
                from ftplib import error_perm
                raise error_perm(f"550 {name}: no such file")
            return f"213 {ts}"
        return "200 OK"

    def retrbinary(self, cmd, callback, blocksize=8192):
        self.commands.append(cmd)
        # Stream the canned payload in blocks
        buf = io.BytesIO(self._retr_payload)
        while True:
            chunk = buf.read(blocksize)
            if not chunk:
                break
            callback(chunk)


@pytest.fixture(autouse=True)
def reset_fake_instances():
    _FakeFtp.instances.clear()
    yield
    _FakeFtp.instances.clear()


@pytest.fixture
def patch_ftplib(monkeypatch):
    def factory(**kwargs):
        def _ctor(host, timeout=None):
            return _FakeFtp(host=host, timeout=timeout, **kwargs)
        monkeypatch.setattr(ftp_module.ftplib, "FTP", _ctor)
    return factory


# ----------------------------------------------------------------------
# Endpoint constants
# ----------------------------------------------------------------------


def test_endpoints_point_at_known_hosts():
    assert SENTINEL_FTP.host == "ftp.homepatrol.com"
    assert SENTINEL_FTP.path == "/BCDx36HP/"
    assert BT885_FTP.host == "ftp.uniden.com"
    assert BT885_FTP.path == "/BT885/"


# ----------------------------------------------------------------------
# Listing
# ----------------------------------------------------------------------


def test_listing_runs_login_cwd_nlst_size_mdtm(patch_ftplib):
    patch_ftplib()
    client = UnidenFtpClient(SENTINEL_FTP)
    entries = client.listing()
    assert len(entries) == 3
    assert {e.name for e in entries} == set(_FakeFtp.DEFAULT_LISTING)

    # Confirm the FTP transport actually saw the protocol verbs we expect.
    fake = _FakeFtp.instances[0]
    cmds = fake.commands
    assert cmds[0] == f"USER {SENTINEL_FTP.user}"
    assert cmds[1] == f"PASS {SENTINEL_FTP.password}"
    assert cmds[2] == f"CWD {SENTINEL_FTP.path}"
    assert "NLST" in cmds
    assert any(c.startswith("SIZE ") for c in cmds)
    assert any(c.startswith("MDTM ") for c in cmds)


def test_listing_parses_mdtm_into_datetime(patch_ftplib):
    patch_ftplib()
    client = UnidenFtpClient(SENTINEL_FTP)
    entries = client.listing()
    by_name = {e.name: e for e in entries}
    assert isinstance(by_name["SDS-100_V1_26_01.bin"].modified, datetime)
    assert by_name["SDS-100_V1_26_01.bin"].modified == datetime(2026, 4, 19, 12, 1, 45)


def test_listing_handles_size_failure_gracefully(patch_ftplib):
    """If SIZE fails on a file, that entry should still appear with size=0."""
    patch_ftplib(sizes={})  # SIZE returns None for everything
    client = UnidenFtpClient(SENTINEL_FTP)
    entries = client.listing()
    assert len(entries) == 3
    assert all(e.size_bytes == 0 for e in entries)


def test_parse_mdtm_handles_fractional_and_garbage():
    assert UnidenFtpClient._parse_mdtm("20260503000000.123") == datetime(2026, 5, 3)
    assert UnidenFtpClient._parse_mdtm("not-a-timestamp") is None
    assert UnidenFtpClient._parse_mdtm("") is None


# ----------------------------------------------------------------------
# Download
# ----------------------------------------------------------------------


def test_download_writes_payload_and_calls_progress(patch_ftplib, tmp_path: Path):
    payload = b"hello-firmware-blob" * 100  # 1900 bytes
    patch_ftplib(retr_payload=payload)
    client = UnidenFtpClient(SENTINEL_FTP)
    dst = tmp_path / "SDS-100_V1_26_01.bin"

    progress_calls: List[Tuple[int, int]] = []

    def cb(written, total):
        progress_calls.append((written, total))

    written = client.download("SDS-100_V1_26_01.bin", str(dst), progress_cb=cb, chunk_size=512)
    assert dst.read_bytes() == payload
    assert written == len(payload)
    assert len(progress_calls) >= 1
    final_written, final_total = progress_calls[-1]
    assert final_written == len(payload)


def test_download_swallows_progress_callback_errors(patch_ftplib, tmp_path: Path):
    """A buggy GUI callback shouldn't tank the download."""
    payload = b"x" * 1000
    patch_ftplib(retr_payload=payload)
    client = UnidenFtpClient(SENTINEL_FTP)
    dst = tmp_path / "out.bin"

    def cb(written, total):
        raise ValueError("simulated callback failure")

    written = client.download("out.bin", str(dst), progress_cb=cb, chunk_size=128)
    assert dst.read_bytes() == payload
    assert written == len(payload)
